"""Monthly fleet reports and their CSV/Excel/PDF export."""

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
from typing import Literal

from fastapi import Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_app import app
from ..audit import audit_commit
from ..auth import allow, current_user, scope
from ..db import get_db
from ..models import Company, Driver, DrivingEvent, Trip, User, Vehicle
from .fleet_settings import thresholds
from .scoring import calculate_safety_score, flexible_rag_policy, score_policy

def _monthly_fleet_data(db, cid, year, month, driver_id=None):
    start=datetime(year,month,1,tzinfo=timezone.utc)
    end=datetime(year+1,1,1,tzinfo=timezone.utc) if month==12 else datetime(year,month+1,1,tzinfo=timezone.utc)
    company=db.get(Company,cid)
    vehicles=list(db.scalars(select(Vehicle).where(Vehicle.company_id==cid).order_by(Vehicle.plate_number)).all())
    drivers=list(db.scalars(select(Driver).where(Driver.company_id==cid,*([Driver.id==driver_id] if driver_id is not None else [])).order_by(Driver.full_name)).all())
    if driver_id is not None and not drivers:raise HTTPException(404,'Driver not found in company')
    all_drivers={d.id:d for d in db.scalars(select(Driver).where(Driver.company_id==cid)).all()}
    trips=list(db.scalars(select(Trip).where(Trip.company_id==cid,Trip.started_at>=start,Trip.started_at<end,Trip.status=='completed')).all())
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.recorded_at>=start,DrivingEvent.recorded_at<end,DrivingEvent.trip_id.in_(select(Trip.id).where(Trip.status=='completed')))).all())
    policy=score_policy(db,cid);speed_limit=thresholds(db,cid).speeding_kmh
    vehicle_rows=[]
    for v in vehicles:
        vt=[t for t in trips if t.vehicle_id==v.id]
        ids=sorted({t.driver_id for t in vt})
        assigned=all_drivers.get(v.assigned_driver_id)
        vehicle_rows.append({'vehicle_id':v.id,'plate_number':v.plate_number,'model':v.make_model,'odometer_km':v.odometer_km,'assigned_driver':assigned.full_name if assigned else '', 'assigned_driver_id':v.assigned_driver_id,'monthly_driver_names':', '.join(all_drivers[i].full_name for i in ids if i in all_drivers),'trip_count':len(vt),'distance_km':round(sum(max(0,t.distance_km or 0) for t in vt),2)})
    rows=[]
    for d in drivers:
        dt=[t for t in trips if t.driver_id==d.id]
        ev=[e for e in events if e.driver_id==d.id]
        km=sum(max(0,t.distance_km or 0) for t in dt)
        seconds=sum(max(0,(t.ended_at-t.started_at).total_seconds()) for t in dt if t.ended_at and t.started_at)
        counts={kind:sum(e.event_type in (kind,'excessive_'+kind) for e in ev) for kind in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')}
        score=calculate_safety_score(ev,km,policy,speed_limit,db=db,trips=dt,flexible_policy=flexible_rag_policy(db,cid))
        counts['excessive_speeding']=score['categories']['excessive_speeding']
        # Excessive speeding is a subset of speeding, not an additional violation.
        rag=score.get('rag','').capitalize() if score['score'] is not None and score.get('score_model')=='flexible_rag' else ('Green' if score['score'] is not None and score['score']>=90 else 'Amber' if score['score'] is not None and score['score']>=60 else 'Red' if score['score'] is not None else 'No data')
        by_vehicle=[]
        for v in vehicles:
            subset=[t for t in dt if t.vehicle_id==v.id]
            if subset:by_vehicle.append({'vehicle_id':v.id,'plate_number':v.plate_number,'trips':len(subset),'distance_km':round(sum(max(0,t.distance_km or 0) for t in subset),2),'driving_hours':round(sum(max(0,(t.ended_at-t.started_at).total_seconds()) for t in subset if t.ended_at and t.started_at)/3600,2)})
        rows.append({'driver_id':d.id,'driver_name':d.full_name,'trip_count':len(dt),'distance_km':round(km,2),'driving_hours':round(seconds/3600,2),'active_days':len({t.started_at.date() for t in dt}),'score':score['score'],'rag':rag,'score_model':score.get('score_model','legacy_100'),'score_breakdown':score,'risk':score['risk'],'violations':counts,'total_violations':sum(counts[k] for k in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')),'vehicles':by_vehicle})
    return {'company_id':cid,'company_name':company.name if company else '', 'year':year,'month':month,'month_label':f'{year}-{month:02d}','period_start':start.isoformat(),'period_end_exclusive':end.isoformat(),'score_model':'flexible_rag' if flexible_rag_policy(db,cid)['enabled'] else 'legacy_100','vehicles':vehicle_rows,'drivers':rows,'notes':['All times are UTC. Only completed trips are counted for utilization.','Driving hours are elapsed trip durations, not engine-on hours.','Excessive speeding is included in speeding totals and must not be added again.','No score means insufficient distance; no RAG color is assigned.','Vehicle assignment is current; monthly vehicle usage is based on recorded trips.']}

@app.get('/api/v1/fleet/monthly-reports')
def monthly_fleet_reports(year:int,month:int,company_id:int|None=None,driver_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    if year<2020 or year>2100 or month<1 or month>12:raise HTTPException(422,'Invalid year or month')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None:raise HTTPException(422,'Select company')
    scope(user,cid)
    return _monthly_fleet_data(db,cid,year,month,driver_id)

@app.get('/api/v1/fleet/monthly-reports/export')
def monthly_fleet_export(year:int,month:int,format:Literal['pdf','csv','xlsx'],kind:Literal['vehicles','utilization','rag','violations'],company_id:int|None=None,driver_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    data=monthly_fleet_reports(year,month,company_id,driver_id,db,user)
    audit_commit(db,'report.export',actor=user,target_type='monthly_report',target_id=f'{year}-{month:02d}',company_id=(company_id if user.role=='super_admin' else user.company_id),detail={'kind':kind,'format':format,'driver_id':driver_id})
    headers={
      'vehicles':['Plate','Model','Assigned driver','Monthly drivers','Odometer km','Trips','Distance km'],
      'utilization':['Driver','Vehicle','Trips','Distance km','Driving hours','Active days'],
      'rag':['Driver','Official score (lower better)' if data.get('score_model')=='flexible_rag' else 'Score / 100','RAG','Risk','Trips','Distance km'],
      'violations':['Driver','Speeding (includes excessive)','Excessive speeding','Harsh braking','Harsh acceleration','Harsh cornering','Total violations']}
    cols=headers[kind];rows=[]
    if kind=='vehicles':
        rows=[[v['plate_number'],v['model'],v['assigned_driver'],v['monthly_driver_names'],v['odometer_km'],v['trip_count'],v['distance_km']] for v in data['vehicles']]
    elif kind=='utilization':
        rows=[[d['driver_name'],v['plate_number'],v['trips'],v['distance_km'],v['driving_hours'],d['active_days']] for d in data['drivers'] for v in d['vehicles']]
    elif kind=='rag':
        rows=[[d['driver_name'],d['score'],d['rag'],d['risk'],d['trip_count'],d['distance_km']] for d in data['drivers']]
    else:
        rows=[[d['driver_name'],d['violations']['speeding'],d['violations']['excessive_speeding'],d['violations']['harsh_braking'],d['violations']['harsh_acceleration'],d['violations']['harsh_cornering'],d['total_violations']] for d in data['drivers']]
    filename=f"nuqati-{kind}-{data['company_id']}-{data['month_label']}.{format}"
    if format=='csv':
        f=StringIO();w=csv.writer(f);w.writerow(cols);w.writerows(rows)
        payload=('\ufeff'+f.getvalue()).encode('utf-8-sig')
        mime='text/csv; charset=utf-8'
    elif format=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb=Workbook();ws=wb.active;ws.title=kind.capitalize();ws.append(cols)
        for row in rows:ws.append([v if v is not None else '' for v in row])
        for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17324D')
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:
            letter=col[0].column_letter;ws.column_dimensions[letter].width=min(42,max(13,max(len(str(c.value or '')) for c in col)+2))
        f=BytesIO();wb.save(f);payload=f.getvalue()
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import landscape,A4
        f=BytesIO();doc=SimpleDocTemplate(f,pagesize=landscape(A4),leftMargin=22,rightMargin=22)
        styles=getSampleStyleSheet()
        content=[Paragraph(f"Nuqati | {kind.capitalize()} | {data['company_name']} | {data['month_label']}",styles['Title']),Spacer(1,12)]
        table=Table([[str(c) for c in cols]]+[[str(v if v is not None else '') for v in row] for row in rows],repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#17324D')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTSIZE',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),6),('GRID',(0,0),(-1,-1),0.25,colors.lightgrey)]))
        content.append(table);doc.build(content);payload=f.getvalue();mime='application/pdf'
    return StreamingResponse(BytesIO(payload),media_type=mime,headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})
