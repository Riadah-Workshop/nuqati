"""Company-scoped scheduled CSV reporting; independent of Nuqati HTTP login sessions."""
from __future__ import annotations
import csv, io, json, os, re, smtplib, ssl, time
from datetime import datetime, timedelta, timezone, date
from calendar import monthrange
from email.message import EmailMessage
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session
from .db import engine, get_db, SessionLocal
from .auth import current_user, allow
from . import heartbeat
from .models import User, Company, Driver, DriverMetadata, Vehicle, Trip, DrivingEvent

# The table report_email_subscriptions is created by an Alembic revision (backend/app/migrations).
KINDS={'vehicle_utilization','driver_violations','driver_scores','rag'}
FREQUENCIES={'daily','weekly','monthly','quarterly','yearly'}
SCOPES={'all','selected','site'}
EMAIL=re.compile(r'^[^\s@]+@[^\s@]+\.[^\s@]+$')

class SubscriptionIn(BaseModel):
    company_id:int|None=None
    recipient:str=Field(min_length=5,max_length=254)
    kind:str
    frequency:str
    scope_type:str='all'
    selected_ids:list[int]=Field(default_factory=list,max_length=300)
    site_name:str|None=Field(default=None,max_length=160)
    weekday:int=Field(default=0,ge=0,le=6)
    month_day:int=Field(default=1,ge=1,le=31)
    anchor_month:int=Field(default=1,ge=1,le=12)
    send_hour:int=Field(default=9,ge=0,le=23)
    send_minute:int=Field(default=0,ge=0,le=59)
    timezone:str='Asia/Riyadh'

def next_time(p, now=None):
    now=now or datetime.now(timezone.utc)
    try: tz=ZoneInfo(p['timezone'])
    except (ZoneInfoNotFoundError,KeyError):raise ValueError('Unsupported IANA timezone')
    current=now.astimezone(tz)
    for i in range(0,380):
        candidate_day=current.date()+timedelta(days=i)
        freq=p['frequency']
        if freq=='weekly' and candidate_day.weekday()!=p['weekday']: continue
        if freq in ('monthly','quarterly','yearly'):
            if candidate_day.day!=min(p['month_day'],monthrange(candidate_day.year,candidate_day.month)[1]):continue
            if freq=='quarterly' and (candidate_day.month-p['anchor_month'])%3:continue
            if freq=='yearly' and candidate_day.month!=p['anchor_month']:continue
        dt=datetime(candidate_day.year,candidate_day.month,candidate_day.day,p['send_hour'],p['send_minute'],tzinfo=tz)
        if dt.astimezone(timezone.utc)>now:return dt.astimezone(timezone.utc)
    raise ValueError('Unable to schedule')

def validate_subscription(data:SubscriptionIn,db:Session,user:User):
    allow(user,'super_admin','company_admin','fleet_manager')
    cid=data.company_id if user.role=='super_admin' else user.company_id
    if not cid or not db.get(Company,cid):raise HTTPException(422,'Select valid company')
    if data.kind not in KINDS or data.frequency not in FREQUENCIES or data.scope_type not in SCOPES:raise HTTPException(422,'Invalid report type, frequency or scope')
    if data.kind=='rag' and data.scope_type!='all':raise HTTPException(422,'RAG report always includes all drivers')
    if not EMAIL.fullmatch(data.recipient.strip()):raise HTTPException(422,'Invalid recipient email')
    if data.scope_type=='site' and not (data.site_name or '').strip():raise HTTPException(422,'Select a department/site')
    if data.scope_type=='selected' and not data.selected_ids:raise HTTPException(422,'Select at least one driver or vehicle')
    if len(set(data.selected_ids))!=len(data.selected_ids):raise HTTPException(422,'Duplicate selections')
    if data.scope_type=='selected':
        model=Vehicle if data.kind=='vehicle_utilization' else Driver
        ids=set(db.scalars(select(model.id).where(model.company_id==cid,model.id.in_(data.selected_ids))).all())
        if ids!=set(data.selected_ids):raise HTTPException(403,'Selections must belong to company')
    if data.scope_type=='site':
        present=db.execute(text('''SELECT 1 FROM driver_metadata m JOIN drivers d ON d.id=m.driver_id
            WHERE d.company_id=:cid AND m.site_name=:site LIMIT 1'''),{'cid':cid,'site':data.site_name.strip()}).first()
        if not present:raise HTTPException(422,'Unknown department/site')
    payload=data.model_dump();payload['company_id']=cid;payload['recipient']=data.recipient.strip().lower();payload['site_name']=(data.site_name or '').strip() or None
    try:next_time(payload)
    except ValueError as e:raise HTTPException(422,str(e))
    return payload

def read_record(r):
    d=dict(r);d['selected_ids']=json.loads(d.get('selected_ids') or '[]')
    for k in ('next_send_at','last_sent_at','created_at'):
        if d.get(k):d[k]=d[k].isoformat()
    return d

def install_report_subscriptions(app):
    @app.get('/api/v1/fleet/report-subscriptions')
    def list_reports(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
        allow(user,'super_admin','company_admin','fleet_manager')
        if user.role=='super_admin':
            if not company_id:return []
            cid=company_id
        else:cid=user.company_id
        rows=db.execute(text('SELECT * FROM report_email_subscriptions WHERE company_id=:cid ORDER BY id DESC'),{'cid':cid}).mappings().all()
        return [read_record(r) for r in rows]
    @app.get('/api/v1/fleet/report-subscriptions/sites')
    def list_sites(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
        allow(user,'super_admin','company_admin','fleet_manager')
        cid=company_id if user.role=='super_admin' else user.company_id
        if not cid:return []
        return list(db.scalars(select(DriverMetadata.site_name).join(Driver,Driver.id==DriverMetadata.driver_id).where(Driver.company_id==cid).distinct().order_by(DriverMetadata.site_name)).all())
    @app.post('/api/v1/fleet/report-subscriptions',status_code=201)
    def create_report(data:SubscriptionIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
        p=validate_subscription(data,db,user)
        row=db.execute(text('''INSERT INTO report_email_subscriptions
          (company_id,created_by,recipient,kind,frequency,scope_type,selected_ids,site_name,weekday,month_day,anchor_month,send_hour,send_minute,timezone,next_send_at)
          VALUES (:company_id,:created_by,:recipient,:kind,:frequency,:scope_type,:selected_ids,:site_name,:weekday,:month_day,:anchor_month,:send_hour,:send_minute,:timezone,:next_send_at) RETURNING id'''),{
            **p,'created_by':user.id,'selected_ids':json.dumps(p['selected_ids']),'next_send_at':next_time(p)
          }).scalar_one()
        from .audit import audit
        audit(db,'report_subscription.create',actor=user,target_type='report_subscription',target_id=row,company_id=p['company_id'],
              detail={'kind':p['kind'],'frequency':p['frequency'],'scope_type':p['scope_type'],'recipient_domain':p['recipient'].split('@')[-1]})
        db.commit();return {'id':row,'next_send_at':next_time(p).isoformat()}
    @app.patch('/api/v1/fleet/report-subscriptions/{sid}')
    def toggle_report(sid:int,enabled:bool,db:Session=Depends(get_db),user:User=Depends(current_user)):
        allow(user,'super_admin','company_admin','fleet_manager')
        r=db.execute(text('SELECT company_id FROM report_email_subscriptions WHERE id=:id'),{'id':sid}).first()
        if not r or (user.role!='super_admin' and r[0]!=user.company_id):raise HTTPException(404,'Subscription not found')
        db.execute(text('UPDATE report_email_subscriptions SET enabled=:enabled WHERE id=:id'),{'id':sid,'enabled':enabled})
        from .audit import audit
        audit(db,'report_subscription.toggle',actor=user,target_type='report_subscription',target_id=sid,company_id=r[0],detail={'enabled':enabled})
        db.commit()
        return {'updated':True}
    @app.delete('/api/v1/fleet/report-subscriptions/{sid}')
    def delete_report(sid:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
        allow(user,'super_admin','company_admin','fleet_manager')
        r=db.execute(text('SELECT company_id FROM report_email_subscriptions WHERE id=:id'),{'id':sid}).first()
        if not r or (user.role!='super_admin' and r[0]!=user.company_id):raise HTTPException(404,'Subscription not found')
        db.execute(text('DELETE FROM report_email_subscriptions WHERE id=:id'),{'id':sid})
        from .audit import audit
        audit(db,'report_subscription.delete',actor=user,target_type='report_subscription',target_id=sid,company_id=r[0])
        db.commit()
        return {'deleted':True}


def report_window(p,send_at):
    from datetime import time as dtime
    tz=ZoneInfo(p['timezone']);local=send_at.astimezone(tz)
    # Report covers prior complete local calendar periods, never the incomplete current day.
    end_day=local.date()
    f=p['frequency']
    if f=='daily':start_day=end_day-timedelta(days=1)
    elif f=='weekly':start_day=end_day-timedelta(days=7)
    elif f=='monthly':start_day=add_months(end_day,-1)
    elif f=='quarterly':start_day=add_months(end_day,-3)
    else:start_day=add_months(end_day,-12)
    return datetime.combine(start_day,dtime.min,tzinfo=tz).astimezone(timezone.utc),datetime.combine(end_day,dtime.min,tzinfo=tz).astimezone(timezone.utc)

def add_months(d,n):
    y=d.year+(d.month-1+n)//12;m=(d.month-1+n)%12+1
    return date(y,m,min(d.day,monthrange(y,m)[1]))

def generate_csv(db,p,send_at):
    from .main import calculate_safety_score, score_policy, thresholds, flexible_rag_policy
    start,end=report_window(p,send_at)
    cid=p['company_id']
    drivers=db.scalars(select(Driver).where(Driver.company_id==cid)).all()
    vehicles=db.scalars(select(Vehicle).where(Vehicle.company_id==cid)).all()
    meta={m.driver_id:m.site_name for m in db.scalars(select(DriverMetadata).join(Driver,Driver.id==DriverMetadata.driver_id).where(Driver.company_id==cid)).all()}
    selected=set(json.loads(p['selected_ids']))
    def matches_driver(d):return p['scope_type']=='all' or (p['scope_type']=='selected' and d.id in selected) or (p['scope_type']=='site' and meta.get(d.id)==p['site_name'])
    vd={v.id:v for v in vehicles}
    matched_drivers=[d for d in drivers if matches_driver(d)]
    if p['kind']=='vehicle_utilization':
        chosen=[v for v in vehicles if p['scope_type']=='all' or (p['scope_type']=='selected' and v.id in selected) or (p['scope_type']=='site' and v.assigned_driver_id in {d.id for d in matched_drivers})]
        trip_rows=db.scalars(select(Trip).where(Trip.company_id==cid,Trip.status=='completed',Trip.started_at>=start,Trip.started_at<end,Trip.vehicle_id.in_([v.id for v in chosen]))).all() if chosen else []
        headers=['Vehicle','Department / site','Trips','Distance (km)','Driving hours','Reporting start UTC','Reporting end UTC']
        rows=[]
        for v in chosen:
            own=[t for t in trip_rows if t.vehicle_id==v.id]
            rows.append([v.plate_number,meta.get(v.assigned_driver_id,''),len(own),round(sum(max(0,t.distance_km or 0) for t in own),2),round(sum(max(0,(t.ended_at-t.started_at).total_seconds()) for t in own if t.ended_at)/3600,2),start.isoformat(),end.isoformat()])
    else:
        trip_rows=db.scalars(select(Trip).where(Trip.company_id==cid,Trip.status=='completed',Trip.started_at>=start,Trip.started_at<end,Trip.driver_id.in_([d.id for d in matched_drivers]))).all() if matched_drivers else []
        trip_ids=[t.id for t in trip_rows]
        ev=db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.recorded_at>=start,DrivingEvent.recorded_at<end,DrivingEvent.trip_id.in_(trip_ids))).all() if trip_ids else []
        pol=score_policy(db,cid);flex_policy=flexible_rag_policy(db,cid);speed=thresholds(db,cid).speeding_kmh
        if p['kind']=='driver_violations':headers=['Driver','Department / site','Speeding','Harsh braking','Harsh acceleration','Harsh cornering','Total confirmed violations','From UTC','To UTC']
        elif p['kind']=='driver_scores':headers=['Driver','Department / site','Distance km','Official score','Scoring model','RAG','Legacy points deducted','From UTC','To UTC']
        else:headers=['Driver','Department / site','Official score','Scoring model','RAG','Distance km','Trips','From UTC','To UTC']
        rows=[]
        for d in matched_drivers:
            ts=[t for t in trip_rows if t.driver_id==d.id];events=[e for e in ev if e.driver_id==d.id]
            km=sum(max(0,t.distance_km or 0) for t in ts)
            result=calculate_safety_score(events,km,pol,speed,db=db,trips=ts,flexible_policy=flex_policy);score=result['score']
            model=result.get('score_model','legacy_100')
            rag='No data' if score is None else (result.get('rag') or ('green' if score>=90 else 'amber' if score>=60 else 'red')).capitalize()
            common=[d.full_name,meta.get(d.id,'')]
            if p['kind']=='driver_violations':rows.append(common+[*[sum(e.event_type==k for e in events) for k in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')],len(events),start.isoformat(),end.isoformat()])
            elif p['kind']=='driver_scores':rows.append(common+[round(km,2),score,model,rag,round(sum(result['deductions'].values()),2) if model=='legacy_100' else '',start.isoformat(),end.isoformat()])
            else:rows.append(common+[score,model,rag,round(km,2),len(ts),start.isoformat(),end.isoformat()])
    output=io.StringIO();writer=csv.writer(output);writer.writerow(headers);writer.writerows(rows)
    return ('\ufeff'+output.getvalue()).encode('utf-8-sig'), start,end

def deliver(p,payload,start,end):
    host=os.environ.get('NUQATI_SMTP_HOST','');username=os.environ.get('NUQATI_SMTP_USER','');password=os.environ.get('NUQATI_SMTP_PASSWORD','')
    if not (host and username and password):raise RuntimeError('SMTP environment incomplete')
    msg=EmailMessage();msg['From']=os.environ.get('NUQATI_EMAIL_FROM','noreply@al-riadah.sa');msg['To']=p['recipient']
    msg['Subject']=f"Nuqati | {p['kind'].replace('_',' ').title()} | {p['frequency'].title()}"
    msg.set_content(f"Nuqati scheduled fleet report\nReporting period UTC: {start.isoformat()} to {end.isoformat()} (exclusive)\nCompany ID: {p['company_id']}\nDepartment scope: {p['site_name'] or p['scope_type']}\nOnly confirmed events on completed trips affect scores.\nPlease handle this driver data confidentially.")
    msg.add_attachment(payload,maintype='text',subtype='csv',filename=f"nuqati-{p['kind']}-{start.date()}-{end.date()}.csv")
    with smtplib.SMTP(host,int(os.environ.get('NUQATI_SMTP_PORT','587')),timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context());smtp.login(username,password);smtp.send_message(msg)

def run_due_once():
    with SessionLocal() as db:
        now=datetime.now(timezone.utc)
        ids=db.execute(text('SELECT id FROM report_email_subscriptions WHERE enabled AND next_send_at<=:now ORDER BY next_send_at LIMIT 10'),{'now':now}).scalars().all()
    for sid in ids:
        with SessionLocal() as db:
            # Locks prevent multiple worker replicas from sending same report simultaneously.
            row=db.execute(text('SELECT * FROM report_email_subscriptions WHERE id=:id AND enabled AND next_send_at<=:now FOR UPDATE SKIP LOCKED'),{'id':sid,'now':datetime.now(timezone.utc)}).mappings().first()
            if not row:continue
            p=dict(row)
            try:
                payload,start,end=generate_csv(db,p,p['next_send_at'])
                deliver(p,payload,start,end)
                nxt=next_time(p,datetime.now(timezone.utc))
                db.execute(text('UPDATE report_email_subscriptions SET last_sent_at=:now,next_send_at=:next,last_error=NULL WHERE id=:id'),{'id':sid,'now':datetime.now(timezone.utc),'next':nxt})
            except Exception as exc:
                # Keep subscription active; retry 15 min later, never log credentials.
                db.execute(text('UPDATE report_email_subscriptions SET next_send_at=:retry,last_error=:error WHERE id=:id'),{'id':sid,'retry':datetime.now(timezone.utc)+timedelta(minutes=15),'error':str(exc)[:300]})
                print(f'Report subscription #{sid} failed: {type(exc).__name__}',flush=True)
            db.commit()

def main():
    heartbeat.start_watchdog('report_scheduler')
    while True:
        heartbeat.beat('report_scheduler')
        try:run_due_once()
        except Exception as exc:print('Scheduler cycle failed:',type(exc).__name__,str(exc)[:200],flush=True)
        time.sleep(30)

if __name__=='__main__':main()
