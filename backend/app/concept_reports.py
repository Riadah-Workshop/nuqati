"""Reference-inspired fleet reports (additive; existing reporting endpoints unchanged).

The reports follow the informational concepts of external examples, not their
branding, typography or proprietary scoring formulas.  They are deliberately
explicit about GPS coverage and the absence of measured fuel/engine data.
"""
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from io import BytesIO, StringIO
from zoneinfo import ZoneInfo
import csv
import math

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .auth import allow, current_user, scope
from .db import get_db
from .models import Company, Driver, DriverLocation, DriverMetadata, DrivingEvent, Trip, User, Vehicle
from .rate_limits import limit

RIYADH = ZoneInfo('Asia/Riyadh')
KINDS = ('movement', 'daily-trips', 'utilization', 'daily-rag')
TITLES = {
    'movement': ('Trip Movement Detail', 'تفاصيل حركة الرحلات'),
    'daily-trips': ('Daily Fleet Trips', 'الرحلات اليومية للأسطول'),
    'utilization': ('Vehicle Utilization Calendar', 'تقويم استخدام المركبات'),
    'daily-rag': ('Daily Driver Safety & RAG', 'سلامة السائقين وتصنيف RAG اليومي'),
}

# Keys -> English heading / Arabic heading.  Generated day columns are dynamic.
FIELDS = {
 'date':('Date','التاريخ'), 'month':('Month','الشهر'), 'day':('Day','اليوم'), 'driver':('Driver','السائق'),
 'driver_id':('Driver ID','معرّف السائق'), 'site':('Site / department','الموقع / القسم'),
 'vehicle':('Vehicle','المركبة'), 'plate':('Plate number','رقم اللوحة'), 'vehicle_id':('Vehicle ID','معرّف المركبة'),
 'trip_id':('Trip #','رقم الرحلة'), 'departure':('Departure (Saudi time)','المغادرة (توقيت السعودية)'),
 'arrival':('Arrival (Saudi time)','الوصول (توقيت السعودية)'),
 'depart_from':('Departure GPS coordinates','إحداثيات الانطلاق'),
 'arrive_at':('Arrival GPS coordinates','إحداثيات الوصول'),
 'elapsed':('Trip duration','مدة الرحلة'), 'moving':('GPS moving time','وقت الحركة المرصود GPS'),
 'stationary':('GPS stationary time','وقت الوقوف المرصود GPS'),
 'idle_time':('Measured engine idle time','خمول المحرك المقاس'),
 'distance':('Distance (km)','المسافة (كم)'),
 'max_speed':('Max GPS speed (km/h)','أقصى سرعة GPS (كم/س)'),
 'avg_speed':('Avg. GPS speed (km/h)','متوسط سرعة GPS (كم/س)'),
 'next_departure':('Next vehicle trip','رحلة المركبة التالية'),
 'trip_gap':('Gap until next trip','الفاصل حتى الرحلة التالية'),
 'trips':('Trip count','عدد الرحلات'),
 'first_trip':('First departure','أول مغادرة'), 'last_trip':('Last arrival','آخر وصول'),
 'fuel_l':('Measured fuel (L)','الوقود المقاس (لتر)'),
 'km_per_l':('Measured efficiency (km/L)','كفاءة الوقود المقاسة (كم/لتر)'),
 'weekday_km':('Sun–Thu distance (km)','مسافة الأحد–الخميس (كم)'),
 'weekend_km':('Fri–Sat distance (km)','مسافة الجمعة–السبت (كم)'),
 'days_with_trips':('Days with trips','أيام بها رحلات'),
 'days_without_trips':('Days without trips','أيام بلا رحلات'),
 'utilization_pct':('Days with trips (%)','نسبة الأيام ذات الرحلات (%)'),
 'ha':('Harsh acceleration','التسارع العنيف'),
 'ha_100':('Acceleration / 100 km','التسارع لكل 100 كم'),
 'hb':('Harsh braking','الفرملة العنيفة'),
 'hb_100':('Braking / 100 km','الفرملة لكل 100 كم'),
 'hc':('Harsh cornering','الانعطاف الحاد'),
 'hc_100':('Cornering / 100 km','الانعطاف لكل 100 كم'),
 'speed_events':('Speeding events','أحداث تجاوز السرعة'),
 'max_event_speed':('Highest speeding event (km/h)','أعلى سرعة لمخالفة (كم/س)'),
 'speed_seconds':('GPS-observed speeding','تجاوز السرعة المرصود GPS'),
 'seconds_10km':('Speeding sec / 10 km','ثواني التجاوز لكل 10 كم'),
 'score':('Official Nuqati score','تقييم نقاطي الرسمي'),
 'rag':('RAG class','تصنيف RAG'),
}
MOVEMENT_KEYS=['date','driver','driver_id','site','vehicle','plate','vehicle_id','trip_id','departure','depart_from','moving','stationary','elapsed','distance','max_speed','avg_speed','arrival','arrive_at','next_departure','trip_gap']
DAILY_KEYS=['date','day','site','vehicle','plate','vehicle_id','driver','driver_id','trips','first_trip','last_trip','moving','stationary','idle_time','elapsed','distance','fuel_l','km_per_l','avg_speed','max_speed']
RAG_KEYS=['driver','driver_id','site','month','date','distance','ha','ha_100','hb','hb_100','hc','hc_100','speed_events','max_event_speed','speed_seconds','seconds_10km','score','rag']


def _stamp(value):
    if value is None:return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _local(value, date_only=False):
    if value is None:return None
    return _stamp(value).astimezone(RIYADH).strftime('%Y-%m-%d' if date_only else '%Y-%m-%d %H:%M:%S')


def _duration(seconds):
    if seconds is None:return None
    secs=max(0,int(round(seconds)))
    return f'{secs//3600:02d}:{secs//60%60:02d}:{secs%60:02d}'


def _coordinates(point):
    return f'{point[0]:.5f}, {point[1]:.5f}' if point else None


def _safe(value):
    if value is None:return None
    try:
        n=float(value)
        return n if math.isfinite(n) else None
    except (ValueError,TypeError):return None


def _gps_for_trips(db, ids, speed_limit):
    """Stream GPS samples; count only consecutive good fixes <= 10 s apart.

    No inferred engine-idle time and no interpolation over GPS outages.
    """
    result={tid:{'moving':0.,'stationary':0.,'speeding':0.,'covered':0.,'n':0,'speed_sum':0.,'speed_max':None,'first':None,'last':None} for tid in ids}
    if not ids:return result
    last_tid=None;previous=None
    q=(select(DriverLocation.trip_id,DriverLocation.recorded_at,DriverLocation.latitude,
              DriverLocation.longitude,DriverLocation.speed_kmh,DriverLocation.accuracy_m)
       .where(DriverLocation.trip_id.in_(ids)).order_by(DriverLocation.trip_id,DriverLocation.recorded_at,DriverLocation.id))
    for tid,at,lat,lon,speed,accuracy in db.execute(q).yield_per(3000):
        item=result[tid]; speed=_safe(speed);accuracy=_safe(accuracy)
        valid=(at is not None and speed is not None and 0<=speed<=250 and
               accuracy is not None and 0<=accuracy<=25 and
               _safe(lat) is not None and _safe(lon) is not None)
        if tid != last_tid: previous=None;last_tid=tid
        if not valid:
            previous=None
            continue
        item['n']+=1;item['speed_sum']+=speed
        item['speed_max']=max(item['speed_max'] or 0.,speed)
        if item['first'] is None:item['first']=(lat,lon)
        item['last']=(lat,lon)
        if previous:
            delta=(_stamp(at)-_stamp(previous[0])).total_seconds()
            if 0<delta<=10:
                item['covered']+=delta
                if speed>=5 and previous[1]>=5:item['moving']+=delta
                if speed<5 and previous[1]<5:item['stationary']+=delta
                if speed>speed_limit and previous[1]>speed_limit:item['speeding']+=delta
        previous=(at,speed)
    return result


def _dataset(db, cid, kind, start, end, driver_id, vehicle_id, deps):
    from_dt=datetime.combine(start,time.min,RIYADH).astimezone(timezone.utc)
    to_dt=datetime.combine(end+timedelta(days=1),time.min,RIYADH).astimezone(timezone.utc)
    company=db.get(Company,cid)
    drivers={d.id:d for d in db.scalars(select(Driver).where(Driver.company_id==cid)).all()}
    vehicles={v.id:v for v in db.scalars(select(Vehicle).where(Vehicle.company_id==cid)).all()}
    if driver_id is not None and driver_id not in drivers:raise HTTPException(404,'Driver not found in company')
    if vehicle_id is not None and vehicle_id not in vehicles:raise HTTPException(404,'Vehicle not found in company')
    sites={m.driver_id:m.site_name for m in db.scalars(select(DriverMetadata).where(DriverMetadata.driver_id.in_(list(drivers)))).all()} if drivers else {}
    conditions=[Trip.company_id==cid,Trip.started_at>=from_dt,Trip.started_at<to_dt,Trip.status=='completed',Trip.ended_at.is_not(None)]
    if driver_id is not None:conditions.append(Trip.driver_id==driver_id)
    if vehicle_id is not None:conditions.append(Trip.vehicle_id==vehicle_id)
    trips=list(db.scalars(select(Trip).where(*conditions).order_by(Trip.started_at,Trip.id).limit(2501)).all())
    if len(trips)>2500:raise HTTPException(422,'More than 2,500 completed trips: narrow the date or vehicle/driver filter')
    ids=[t.id for t in trips]
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.trip_id.in_(ids))).all()) if ids and kind=='daily-rag' else []
    grouped_events=defaultdict(list)
    for e in events:grouped_events[e.trip_id].append(e)
    speed_limit=deps['thresholds'](db,cid).speeding_kmh if kind!='utilization' and ids else 100
    samples=_gps_for_trips(db,ids,speed_limit) if kind!='utilization' else {}
    by_vehicle=defaultdict(list); by_day=defaultdict(list); by_driver_day=defaultdict(list)
    for t in trips:
        day=_local(t.started_at,True)
        by_vehicle[t.vehicle_id].append(t)
        by_day[(day,t.vehicle_id,t.driver_id)].append(t)
        by_driver_day[(day,t.driver_id)].append(t)
    day_count=(end-start).days+1
    total_km=round(sum(max(0.,t.distance_km or 0.) for t in trips),2)
    summary={'trips':len(trips),'distance_km':total_km,'vehicles':len({t.vehicle_id for t in trips}),'drivers':len({t.driver_id for t in trips}), 'days':day_count}
    all_notes=[
        'Saudi Arabia local time (UTC+03:00); trips are grouped by departure date.',
        'Completed trips only. Distance is the recorded trip distance; durations are elapsed trip time, not engine-on time.',
        'GPS movement, stationary time and speeding duration use consecutive high-quality GPS fixes <=10 seconds apart; gaps are excluded.',
        'GPS locations are coordinates, not reverse-geocoded street addresses. GPS speed is sample-based.',
        'Fuel consumption and actual engine idling are not measured by Nuqati; no values are fabricated.',
    ]
    notes_ar=[
        'جميع الأوقات بتوقيت السعودية (UTC+03:00)، وتُنسب الرحلات إلى تاريخ الانطلاق.',
        'الرحلات المكتملة فقط؛ المسافة من سجل الرحلة، والمدة الزمنية لا تعني ساعات تشغيل المحرك.',
        'حركة GPS والوقوف وتجاوز السرعة مبنية على قراءات دقيقة متتالية بفاصل لا يتجاوز 10 ثوانٍ؛ ولا تُحتسب فترات انقطاع GPS.',
        'أماكن الانطلاق والوصول تُعرض كإحداثيات GPS وليست عناوين شوارع؛ السرعة مستندة إلى عينات GPS.',
        'لا يقيس نقاطي استهلاك الوقود أو الخمول الفعلي للمحرك، ولا تُنشأ قيم تقديرية على أنها قياسات.',
    ]
    rows=[];columns=[]
    if kind=='movement':
        columns=[{'key':k,'en':FIELDS[k][0],'ar':FIELDS[k][1]} for k in MOVEMENT_KEYS]
        for veh_id,ts in by_vehicle.items():
            for ix,t in enumerate(ts):
                d=drivers.get(t.driver_id);v=vehicles.get(t.vehicle_id);gp=samples[t.id]
                next_trip=ts[ix+1] if ix+1<len(ts) else None
                gap=(_stamp(next_trip.started_at)-_stamp(t.ended_at)).total_seconds() if next_trip else None
                gap=gap if gap is not None and gap>=0 else None
                rows.append({'date':_local(t.started_at,True),'driver':d.full_name if d else '—','driver_id':t.driver_id,'site':sites.get(t.driver_id) or None,
                  'vehicle':v.make_model if v else None,'plate':v.plate_number if v else None,'vehicle_id':t.vehicle_id,'trip_id':t.id,
                  'departure':_local(t.started_at),'depart_from':_coordinates(gp['first']),
                  'moving':_duration(gp['moving']) if gp['covered'] else None,
                  'stationary':_duration(gp['stationary']) if gp['covered'] else None,
                  'elapsed':_duration((_stamp(t.ended_at)-_stamp(t.started_at)).total_seconds()),
                  'distance':round(max(0.,t.distance_km or 0.),3),
                  'max_speed':round(gp['speed_max'],1) if gp['n'] else None,
                  'avg_speed':round(gp['speed_sum']/gp['n'],1) if gp['n'] else None,
                  'arrival':_local(t.ended_at),'arrive_at':_coordinates(gp['last']),
                  'next_departure':_local(next_trip.started_at) if next_trip else None,
                  'trip_gap':_duration(gap)})
        rows.sort(key=lambda x:(x['departure'],x['trip_id']))
        all_notes.append('The gap until the next trip is not proof of parking at the same location.')
        notes_ar.append('الفاصل حتى الرحلة التالية لا يثبت أن المركبة بقيت في الموقع نفسه.')
    elif kind=='daily-trips':
        columns=[{'key':k,'en':FIELDS[k][0],'ar':FIELDS[k][1]} for k in DAILY_KEYS]
        for (day,veh_id,drv_id),ts in sorted(by_day.items()):
            d=drivers.get(drv_id);v=vehicles.get(veh_id)
            points=[samples[t.id] for t in ts]
            n=sum(g['n'] for g in points)
            observed=sum(g['covered'] for g in points)
            rows.append({'date':day,'day':date.fromisoformat(day).strftime('%A'),'site':sites.get(drv_id) or None,
              'vehicle':v.make_model if v else None,'plate':v.plate_number if v else None,'vehicle_id':veh_id,
              'driver':d.full_name if d else '—','driver_id':drv_id,'trips':len(ts),
              'first_trip':_local(ts[0].started_at),'last_trip':_local(max(t.ended_at for t in ts)),
              'moving':_duration(sum(g['moving'] for g in points)) if observed else None,
              'stationary':_duration(sum(g['stationary'] for g in points)) if observed else None,
              'idle_time':None,
              'elapsed':_duration(sum(max(0,(_stamp(t.ended_at)-_stamp(t.started_at)).total_seconds()) for t in ts)),
              'distance':round(sum(max(0.,t.distance_km or 0.) for t in ts),3),
              'fuel_l':None,'km_per_l':None,
              'avg_speed':round(sum(g['speed_sum'] for g in points)/n,1) if n else None,
              'max_speed':round(max((g['speed_max'] or 0) for g in points),1) if n else None})
        all_notes.append('Fuel and km/L columns intentionally remain blank until a reliable fuel-data source is integrated.')
        notes_ar.append('تظل حقول الوقود والكيلومتر لكل لتر فارغة حتى إضافة مصدر موثوق لبيانات الوقود.')
    elif kind=='utilization':
        days=[start+timedelta(days=i) for i in range(day_count)]
        columns=[{'key':k,'en':FIELDS[k][0],'ar':FIELDS[k][1]} for k in ['site','vehicle','plate','vehicle_id']]
        columns.extend({'key':'day_'+d.isoformat(),'en':d.strftime('%a %d/%m'),'ar':d.strftime('%d/%m')} for d in days)
        columns.extend({'key':k,'en':FIELDS[k][0],'ar':FIELDS[k][1]} for k in ['weekday_km','weekend_km','distance','days_with_trips','days_without_trips','utilization_pct'])
        # All company vehicles are listed in unfiltered company reports, including unused ones.
        eligible=sorted(vehicles.values(),key=lambda v:(v.plate_number,v.id))
        if vehicle_id is not None:eligible=[v for v in eligible if v.id==vehicle_id]
        if driver_id is not None:eligible=[v for v in eligible if any(t.driver_id==driver_id for t in by_vehicle.get(v.id,[]))]
        for v in eligible:
            ts=by_vehicle.get(v.id,[])
            distance_by_day=defaultdict(float)
            for t in ts:distance_by_day[_local(t.started_at,True)]+=max(0.,t.distance_km or 0.)
            weekday=sum(val for day,val in distance_by_day.items() if date.fromisoformat(day).weekday() not in (4,5))
            weekend=sum(val for day,val in distance_by_day.items() if date.fromisoformat(day).weekday() in (4,5))
            row={'site':sites.get(v.assigned_driver_id) or None,'vehicle':v.make_model,'plate':v.plate_number,'vehicle_id':v.id}
            row.update({'day_'+d.isoformat():round(distance_by_day.get(d.isoformat(),0.),2) for d in days})
            row.update({'weekday_km':round(weekday,2),'weekend_km':round(weekend,2),
              'distance':round(sum(distance_by_day.values()),2),'days_with_trips':len(distance_by_day),
              'days_without_trips':day_count-len(distance_by_day),
              'utilization_pct':round(100*len(distance_by_day)/day_count,1)})
            rows.append(row)
        all_notes.append('Saudi weekend: Friday–Saturday. A day without a recorded trip is not proof the vehicle was unused.')
        notes_ar.append('عطلة نهاية الأسبوع في السعودية هي الجمعة والسبت، واليوم بلا رحلة مسجلة لا يثبت عدم استخدام المركبة.')
        all_notes.append('Site is taken from the currently assigned driver where known, not an independently verified trip location.')
        notes_ar.append('الموقع مستمد من السائق المعيّن حالياً عند توفره، وليس موقعاً مؤكداً لكل رحلة.')
    else: # daily-rag
        columns=[{'key':k,'en':FIELDS[k][0],'ar':FIELDS[k][1]} for k in RAG_KEYS]
        policy=deps['score_policy'](db,cid)
        flex=deps['flexible_rag_policy'](db,cid)
        for (day,drv_id),ts in sorted(by_driver_day.items()):
            ev=[event for t in ts for event in grouped_events[t.id]]
            km=sum(max(0.,t.distance_km or 0.) for t in ts)
            score=deps['calculate_safety_score'](ev,km,policy,speed_limit,db=db,trips=ts,flexible_policy=flex)
            ha=sum(e.event_type=='harsh_acceleration' for e in ev)
            hb=sum(e.event_type=='harsh_braking' for e in ev)
            hc=sum(e.event_type=='harsh_cornering' for e in ev)
            speeding=[e for e in ev if e.event_type in ('speeding','excessive_speeding')]
            seconds=sum(samples[t.id]['speeding'] for t in ts)
            covered=sum(samples[t.id]['covered'] for t in ts)
            if score['score'] is None:rag=None
            elif score.get('score_model')=='flexible_rag':rag=score.get('rag')
            else:rag='green' if score['score']>=90 else 'amber' if score['score']>=60 else 'red'
            rows.append({'driver':drivers[drv_id].full_name if drv_id in drivers else '—','driver_id':drv_id,
              'site':sites.get(drv_id) or None,'month':day[:7],'date':day,'distance':round(km,3),
              'ha':ha,'ha_100':round(ha*100/km,2) if km>0 else None,
              'hb':hb,'hb_100':round(hb*100/km,2) if km>0 else None,
              'hc':hc,'hc_100':round(hc*100/km,2) if km>0 else None,
              'speed_events':len(speeding),
              'max_event_speed':round(max((e.value or 0) for e in speeding),1) if speeding else None,
              'speed_seconds':_duration(seconds) if covered else None,
              'seconds_10km':round(seconds*10/km,2) if covered and km>0 else None,
              'score':score['score'],'rag':rag})
        model='flexible_rag' if flex.get('enabled') else 'legacy_100'
        all_notes.append('Scores and RAG use the company-approved Nuqati scoring policy; no SANAD score formula is copied.')
        notes_ar.append('تستخدم الدرجات وتصنيف RAG سياسة نقاطي المعتمدة للشركة، من دون نسخ أي معادلة من التقرير المرجعي.')
        all_notes.append('Score model: '+('Flexible RAG: lower penalty is better.' if model=='flexible_rag' else 'Legacy score: higher out of 100 is better.'))
        notes_ar.append('نموذج التقييم: '+('RAG مرن، الأقل أفضل.' if model=='flexible_rag' else 'التقييم التقليدي من 100، الأعلى أفضل.'))
        all_notes.append('Speeding seconds are from observed GPS intervals only, not a measured complete duration.')
        notes_ar.append('ثواني تجاوز السرعة مبنية فقط على فترات GPS المرصودة، وليست مدة مؤكدة كاملة.')
    return {'kind':kind,'title':{'en':TITLES[kind][0],'ar':TITLES[kind][1]},
            'company_id':cid,'company_name':company.name if company else '',
            'start_date':start.isoformat(),'end_date':end.isoformat(),
            'columns':columns,'rows':rows,'summary':summary,'notes':all_notes,'notes_ar':notes_ar,
            'score_model':('flexible_rag' if deps['flexible_rag_policy'](db,cid).get('enabled') else 'legacy_100') if kind=='daily-rag' else None}


def _sheet_cell(value):
    if value is None or value=='':return '—'
    if isinstance(value,str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
        return '\''+value
    return value


def _excel(data, lang):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from openpyxl.utils import get_column_letter
    from openpyxl.worksheet.page import PageMargins
    wb=Workbook();ws=wb.active;ws.title='Nuqati '+data['kind'].replace('-',' ').title()[:20]
    cols=data['columns'];n=len(cols)
    navy='142838';green='C8EF7D';muted='6C8492'
    ws.merge_cells(start_row=1,start_column=1,end_row=1,end_column=n)
    cell=ws.cell(1,1,'NUQATI  /  '+data['title'][lang]);cell.font=Font(name='Aptos Display',size=20,bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor=navy);cell.alignment=Alignment(vertical='center')
    ws.row_dimensions[1].height=43
    ws.merge_cells(start_row=2,start_column=1,end_row=2,end_column=n)
    cell=ws.cell(2,1,f"Company: {data['company_name']}   |   {data['start_date']} — {data['end_date']}   |   Asia/Riyadh (UTC+03:00)")
    cell.font=Font(size=10,color='284258',bold=True);cell.alignment=Alignment(vertical='center');ws.row_dimensions[2].height=27
    ws.merge_cells(start_row=3,start_column=1,end_row=3,end_column=n)
    info=data['summary'];cell=ws.cell(3,1,f"TRIPS  {info['trips']}     DISTANCE  {info['distance_km']:,.2f} km     DRIVERS  {info['drivers']}     VEHICLES  {info['vehicles']}")
    cell.font=Font(size=11,bold=True,color=navy);cell.fill=PatternFill('solid',fgColor='E7F4CF');ws.row_dimensions[3].height=27
    hdr=5
    for ix,col in enumerate(cols,1):
        c=ws.cell(hdr,ix,col[lang]);c.font=Font(bold=True,color=navy,size=10);c.fill=PatternFill('solid',fgColor=green)
        c.alignment=Alignment(wrap_text=True,vertical='center')
        ws.column_dimensions[get_column_letter(ix)].width=min(36,max(15,len(col[lang])*0.85+5))
    ws.row_dimensions[hdr].height=35
    for idx,row in enumerate(data['rows'],hdr+1):
        for colidx,col in enumerate(cols,1):
            k=col['key'];val=_sheet_cell(row.get(k))
            c=ws.cell(idx,colidx,val);c.font=Font(name='Aptos',size=10,color=navy)
            c.alignment=Alignment(vertical='center',wrap_text=k in ('depart_from','arrive_at','vehicle','site'))
            c.fill=PatternFill('solid',fgColor='F2F7F8' if idx%2==0 else 'FFFFFF')
            if k=='rag' and row.get('rag'):
                val=str(row['rag']).lower();color={'green':'DDF6E3','amber':'FFF1C1','red':'FFE1E1'}.get(val,'F2F7F8')
                c.fill=PatternFill('solid',fgColor=color);c.font=Font(bold=True,color={'green':'126737','amber':'8D5B00','red':'A12626'}.get(val,navy))
        ws.row_dimensions[idx].height=25
    if data['rows']:
        last=hdr+len(data['rows'])
        ws.auto_filter.ref=f'A{hdr}:{get_column_letter(n)}{last}'
    ws.freeze_panes=f'D{hdr+1}' if n>=4 else f'A{hdr+1}'
    note_row=hdr+len(data['rows'])+2
    ws.merge_cells(start_row=note_row,start_column=1,end_row=note_row,end_column=n)
    note=ws.cell(note_row,1,'DATA NOTES / ملاحظات البيانات');note.font=Font(size=11,bold=True,color=navy);note.fill=PatternFill('solid',fgColor=green)
    for i,note_text in enumerate(data.get('notes_ar',data['notes']) if lang=='ar' else data['notes'],note_row+1):
        ws.merge_cells(start_row=i,start_column=1,end_row=i,end_column=n)
        c=ws.cell(i,1,'• '+note_text);c.font=Font(size=10,color=muted);c.alignment=Alignment(wrap_text=True,vertical='center');ws.row_dimensions[i].height=28
    ws.sheet_view.showGridLines=False;ws.print_options.horizontalCentered=True
    ws.page_setup.orientation='landscape';ws.page_setup.paperSize=ws.PAPERSIZE_A3;ws.sheet_properties.pageSetUpPr.fitToPage=True;ws.page_setup.fitToWidth=1;ws.page_setup.fitToHeight=0
    ws.print_title_rows='1:5';ws.page_margins=PageMargins(left=.25,right=.25,top=.5,bottom=.5,header=.2,footer=.2)
    output=BytesIO();wb.save(output);return output.getvalue()


def _csv_safe(value):
    if value is None:return ''
    if isinstance(value,str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
        return '\''+value
    return value


def _csv(data,lang):
    f=StringIO();writer=csv.writer(f)
    writer.writerow(['Nuqati',data['title'][lang]])
    writer.writerow(['Company',_csv_safe(data['company_name']),'From',data['start_date'],'To',data['end_date'],'Timezone','Asia/Riyadh'])
    writer.writerow([])
    writer.writerow([c[lang] for c in data['columns']])
    for row in data['rows']:
        writer.writerow([_csv_safe(row.get(c['key'])) for c in data['columns']])
    writer.writerow([]);writer.writerow(['Data notes'])
    for note in (data.get('notes_ar',data['notes']) if lang=='ar' else data['notes']):writer.writerow([note])
    return ('\ufeff'+f.getvalue()).encode('utf-8')


def _pdf(data):
    # English headings ensure standard reportlab fonts render accurately, even when
    # the platform interface is Arabic (Arabic shaping isn't provided by reportlab).
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.pagesizes import landscape, A3
    from reportlab.lib.enums import TA_CENTER
    from xml.sax.saxutils import escape
    f=BytesIO();doc=SimpleDocTemplate(f,pagesize=landscape(A3),leftMargin=20,rightMargin=20,topMargin=20,bottomMargin=20)
    styles=getSampleStyleSheet();cell_style=ParagraphStyle('data',parent=styles['Normal'],fontSize=6.8,leading=9)
    head_style=ParagraphStyle('heading',parent=cell_style,fontName='Helvetica-Bold',textColor=colors.HexColor('#142838'))
    body=[Paragraph('NUQATI  /  '+escape(data['title']['en']),styles['Title']),
          Paragraph(escape(data['company_name'])+'  |  '+data['start_date']+' — '+data['end_date']+'  |  Saudi time (UTC+03:00)',styles['Normal']),Spacer(1,8),
          Paragraph(f"Trips: {data['summary']['trips']}   |   Distance: {data['summary']['distance_km']} km   |   Drivers: {data['summary']['drivers']}",styles['Heading3']),Spacer(1,8)]
    cols=data['columns'];n=len(cols);available=landscape(A3)[0]-40
    raw=[max(45,min(115,len(c['en'])*3+20)) for c in cols]
    scale=available/sum(raw);widths=[w*scale for w in raw]
    # Limited rows per table automatically flow across PDF pages; repeat column headers.
    cells=[[Paragraph(escape(c['en']),head_style) for c in cols]]
    for row in data['rows']:
        cells.append([Paragraph(escape(str(_sheet_cell(row.get(c['key'])))),cell_style) for c in cols])
    if len(cells)==1:cells.append([Paragraph('No matching completed trips',cell_style)]+['']*(n-1))
    t=Table(cells,colWidths=widths,repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#C8EF7D')),
       ('VALIGN',(0,0),(-1,-1),'TOP'),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F2F7F8')]),
       ('LINEBELOW',(0,0),(-1,0),.6,colors.HexColor('#142838')),
       ('BOTTOMPADDING',(0,0),(-1,-1),5),('TOPPADDING',(0,0),(-1,-1),5)]))
    body.extend([t,Spacer(1,12),Paragraph('Data limitations',styles['Heading3'])])
    for note in data['notes']:body.append(Paragraph('• '+escape(note),styles['Normal']))
    doc.build(body)
    return f.getvalue()


def register_concept_reports(app, **deps):
    def read(kind, start_date, end_date, driver_id, vehicle_id, company_id, db, user):
        allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
        if kind not in KINDS:raise HTTPException(404,'Unknown report type')
        if end_date<start_date or (end_date-start_date).days>30:raise HTTPException(422,'Select a date range of 1 to 31 days')
        cid=company_id if user.role=='super_admin' else user.company_id
        if cid is None:raise HTTPException(422,'Select a company')
        scope(user,cid)
        if db.get(Company,cid) is None:raise HTTPException(404,'Company not found')
        return _dataset(db,cid,kind,start_date,end_date,driver_id,vehicle_id,deps)

    @app.get('/api/v1/fleet/concept-reports/{kind}',dependencies=[Depends(limit('report'))])
    def concept_report(kind:str,start_date:date,end_date:date,driver_id:int|None=None,vehicle_id:int|None=None,
                       company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
        return read(kind,start_date,end_date,driver_id,vehicle_id,company_id,db,user)

    @app.get('/api/v1/fleet/concept-reports/{kind}/export',dependencies=[Depends(limit('export'))])
    def concept_report_export(kind:str,start_date:date,end_date:date,format:str='xlsx',lang:str='en',
                              driver_id:int|None=None,vehicle_id:int|None=None,company_id:int|None=None,
                              db:Session=Depends(get_db),user:User=Depends(current_user)):
        if format not in ('xlsx','csv','pdf') or lang not in ('en','ar'):raise HTTPException(422,'Invalid export format or language')
        data=read(kind,start_date,end_date,driver_id,vehicle_id,company_id,db,user)
        from .audit import audit_commit
        audit_commit(db,'report.export',actor=user,target_type='concept_report',target_id=kind,company_id=(company_id if user.role=='super_admin' else user.company_id),
                     detail={'format':format,'start_date':start_date.isoformat(),'end_date':end_date.isoformat(),'driver_id':driver_id,'vehicle_id':vehicle_id})
        if format=='xlsx':payload=_excel(data,lang);mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        elif format=='pdf':payload=_pdf(data);mime='application/pdf'
        else:payload=_csv(data,lang);mime='text/csv; charset=utf-8'
        filename=f"nuqati-{kind}-{start_date.isoformat()}-{end_date.isoformat()}.{format}"
        return StreamingResponse(BytesIO(payload),media_type=mime,headers={
            'Content-Disposition':f'attachment; filename="{filename}"',
            'Cache-Control':'private, no-store'})
