"""Driver-app evidence and audit trails: privacy requests, lifecycle events, heartbeats, notification evidence, safety observations."""

import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user
from ..db import engine, get_db
from ..models import User, Vehicle
from ..rate_limits import limit
from .shared import own_driver

# Privacy evidence: append-only, idempotent, and intentionally location-free.

class PrivacyEvidence(BaseModel):
    event_id: str = Field(min_length=8, max_length=90, pattern=r'^[a-zA-Z0-9_-]+$')
    privacy_enabled: bool
    selected_at: datetime

@app.post('/api/v1/mobile/privacy-evidence')
def record_privacy_evidence(payload: PrivacyEvidence, db: Session=Depends(get_db), user: User=Depends(current_user)):
    driver=own_driver(db,user)
    selected=payload.selected_at
    if selected.tzinfo is None: selected=selected.replace(tzinfo=timezone.utc)
    selected=selected.astimezone(timezone.utc)
    if selected>datetime.now(timezone.utc)+timedelta(minutes=5) or selected<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid privacy selection timestamp')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    existing=db.execute(text('SELECT driver_id, privacy_enabled FROM mobile_privacy_audit WHERE event_id=:id'),{'id':payload.event_id}).first()
    if existing:
        if existing[0]!=driver.id or existing[1]!=payload.privacy_enabled:raise HTTPException(409,'Conflicting privacy event ID')
        return {'accepted':True,'duplicate':True}
    db.execute(text('''INSERT INTO mobile_privacy_audit
        (event_id,company_id,driver_id,vehicle_id,privacy_enabled,selected_at)
        VALUES (:id,:cid,:did,:vid,:enabled,:selected)'''),
        {'id':payload.event_id,'cid':driver.company_id,'did':driver.id,'vid':vehicle.id if vehicle else None,
         'enabled':payload.privacy_enabled,'selected':selected})
    db.commit()
    return {'accepted':True,'duplicate':False}

# Server-authoritative privacy approval. Pending requests never disable tracking.

class DriverPrivacyRequestIn(BaseModel):
    reason: str = Field(default='',max_length=500)

class DriverPrivacyDecision(BaseModel):
    approve: bool

@app.post('/api/v1/mobile/privacy-request')
def create_driver_privacy_request(payload:DriverPrivacyRequestIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    latest=db.execute(text('SELECT id,status FROM driver_privacy_requests WHERE driver_id=:d ORDER BY id DESC LIMIT 1'),{'d':driver.id}).first()
    if latest and latest[1] in ('pending','approved','active'):
        return {'id':latest[0],'status':latest[1]}
    result=db.execute(text('INSERT INTO driver_privacy_requests(company_id,driver_id,reason) VALUES (:c,:d,:r) RETURNING id'),{'c':driver.company_id,'d':driver.id,'r':payload.reason.strip()})
    request_id=result.scalar_one();db.commit()
    return {'id':request_id,'status':'pending'}

@app.get('/api/v1/mobile/privacy-request/status')
def driver_privacy_request_status(db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    row=db.execute(text('SELECT id,status FROM driver_privacy_requests WHERE driver_id=:d ORDER BY id DESC LIMIT 1'),{'d':driver.id}).first()
    return {'id':row[0] if row else None,'status':row[1] if row else 'none'}

@app.post('/api/v1/mobile/privacy-request/{request_id}/activate')
def activate_driver_privacy_request(request_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    # A pending/rejected/revoked request can never be used to activate tracking privacy.
    changed=db.execute(text("""UPDATE driver_privacy_requests SET status='active',activated_at=CURRENT_TIMESTAMP
      WHERE id=:id AND driver_id=:d AND status='approved' RETURNING id"""),{'id':request_id,'d':driver.id}).first()
    if not changed:
        row=db.execute(text('SELECT status FROM driver_privacy_requests WHERE id=:id AND driver_id=:d'),{'id':request_id,'d':driver.id}).first()
        if not row or row[0]!='active':raise HTTPException(409,'Privacy approval is not valid')
    db.commit();return {'status':'active'}

@app.post('/api/v1/mobile/privacy-request/disable')
def disable_driver_privacy_request(db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    db.execute(text("""UPDATE driver_privacy_requests SET status='ended',ended_at=CURRENT_TIMESTAMP
      WHERE driver_id=:d AND status IN ('pending','approved','active')"""),{'d':driver.id})
    db.commit();return {'status':'ended'}

@app.get('/api/v1/fleet/privacy-requests')
def fleet_privacy_requests(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    clause='' if user.role=='super_admin' else 'WHERE r.company_id=:cid'
    rows=db.execute(text(f"""SELECT r.*,d.full_name AS driver_name,c.name AS company_name
      FROM driver_privacy_requests r JOIN drivers d ON d.id=r.driver_id JOIN companies c ON c.id=r.company_id
      {clause} ORDER BY CASE WHEN r.status='pending' THEN 0 ELSE 1 END,r.requested_at DESC LIMIT 500"""),{} if user.role=='super_admin' else {'cid':user.company_id}).mappings().all()
    return [dict(row) for row in rows]

@app.post('/api/v1/fleet/privacy-requests/{request_id}/decision')
def decide_driver_privacy_request(request_id:int,payload:DriverPrivacyDecision,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    clause='' if user.role=='super_admin' else ' AND company_id=:cid'
    args={'id':request_id,'uid':user.id,'status':'approved' if payload.approve else 'rejected'}
    if user.role!='super_admin':args['cid']=user.company_id
    row=db.execute(text(f"""UPDATE driver_privacy_requests SET status=:status,decided_at=CURRENT_TIMESTAMP,decided_by=:uid
        WHERE id=:id AND status='pending'{clause} RETURNING id"""),args).first()
    if not row:raise HTTPException(409,'Request not pending or outside your company')
    db.commit();return {'status':args['status']}

@app.post('/api/v1/fleet/privacy-requests/{request_id}/revoke')
def revoke_driver_privacy_request(request_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    clause='' if user.role=='super_admin' else ' AND company_id=:cid'
    args={'id':request_id,'uid':user.id}
    if user.role!='super_admin':args['cid']=user.company_id
    row=db.execute(text(f"""UPDATE driver_privacy_requests SET status='revoked',ended_at=CURRENT_TIMESTAMP,decided_by=:uid
      WHERE id=:id AND status IN ('approved','active'){clause} RETURNING id"""),args).first()
    if not row:raise HTTPException(409,'Request not active or outside your company')
    db.commit();return {'status':'revoked'}

# Non-location device lifecycle and preference audit (separate from Privacy Mode selection).
class MobileLifecycleEvent(BaseModel):
    event_id: str = Field(min_length=8,max_length=90,pattern=r'^[a-zA-Z0-9_-]+$')
    event_type: Literal['first_authenticated_launch','camera_monitoring_disabled','camera_monitoring_enabled','login','logout']
    occurred_at: datetime

@app.post('/api/v1/mobile/lifecycle-event')
def mobile_lifecycle_event(payload:MobileLifecycleEvent,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    at=payload.occurred_at
    if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
    at=at.astimezone(timezone.utc)
    if at>datetime.now(timezone.utc)+timedelta(minutes=5) or at<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid event time')
    row=db.execute(text('SELECT driver_id,event_type FROM mobile_lifecycle_audit WHERE event_id=:id'),{'id':payload.event_id}).first()
    if row:
        if row[0]!=driver.id or row[1]!=payload.event_type:raise HTTPException(409,'Conflicting event ID')
        return {'accepted':True,'duplicate':True}
    db.execute(text('INSERT INTO mobile_lifecycle_audit(event_id,company_id,driver_id,event_type,occurred_at) VALUES (:i,:c,:d,:t,:a)'),
      {'i':payload.event_id,'c':driver.company_id,'d':driver.id,'t':payload.event_type,'a':at})
    db.commit();return {'accepted':True,'duplicate':False}

@app.get('/api/v1/fleet/lifecycle-audit')
def fleet_lifecycle_audit(limit:int=100,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    args={'limit':max(1,min(limit,500))}
    where=''
    if user.role!='super_admin':where='WHERE company_id=:cid';args['cid']=user.company_id
    rows=db.execute(text(f'SELECT * FROM mobile_lifecycle_audit {where} ORDER BY received_at DESC LIMIT :limit'),args).mappings().all()
    return [dict(r) for r in rows]

@app.get('/api/v1/privacy-audit')
def list_privacy_audit(limit:int=100,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    limit=max(1,min(limit,500))
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    args={'limit':limit} if user.role=='super_admin' else {'limit':limit,'cid':user.company_id}
    rows=db.execute(text(f'''SELECT event_id,company_id,driver_id,vehicle_id,privacy_enabled,selected_at,received_at
        FROM mobile_privacy_audit {where} ORDER BY received_at DESC LIMIT :limit'''),args).mappings().all()
    return [dict(row) for row in rows]

# Latest device heartbeat (no coordinates). Updated by the background location service.

class TrackingHeartbeatIn(BaseModel):
    screen_state: Literal['locked','unlocked','unknown']
    trip_active: bool
    gps_fix_age_s: int | None = Field(default=None, ge=0, le=86400)
    connectivity_policy_version: int = Field(default=1,ge=1,le=2)
    # No location data. Values are nullable for older Driver releases.
    queued_gps_points: int | None = Field(default=None,ge=0,le=10000000)
    queued_safety_events: int | None = Field(default=None,ge=0,le=10000000)
    queued_trips: int | None = Field(default=None,ge=0,le=10000000)
    captured_at: datetime

@app.post('/api/v1/mobile/tracking-heartbeat',dependencies=[Depends(limit('heartbeat'))])
def mobile_tracking_heartbeat(payload: TrackingHeartbeatIn, db: Session=Depends(get_db), user: User=Depends(current_user)):
    driver=own_driver(db,user)
    captured=payload.captured_at
    if captured.tzinfo is None: captured=captured.replace(tzinfo=timezone.utc)
    captured=captured.astimezone(timezone.utc)
    if abs((datetime.now(timezone.utc)-captured).total_seconds())>300:
        raise HTTPException(422,'Invalid heartbeat time')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    db.execute(text("""INSERT INTO mobile_tracking_heartbeat
      (driver_id,company_id,vehicle_id,screen_state,trip_active,gps_fix_age_s,captured_at,received_at,connectivity_policy_version,queued_gps_points,queued_safety_events,queued_trips)
      VALUES (:did,:cid,:vid,:screen,:active,:age,:at,CURRENT_TIMESTAMP,:policy,:gpsq,:eventq,:tripq)
      ON CONFLICT (driver_id) DO UPDATE SET
        company_id=EXCLUDED.company_id,vehicle_id=EXCLUDED.vehicle_id,
        screen_state=EXCLUDED.screen_state,trip_active=EXCLUDED.trip_active,
        gps_fix_age_s=EXCLUDED.gps_fix_age_s,captured_at=EXCLUDED.captured_at,
        connectivity_policy_version=EXCLUDED.connectivity_policy_version,
        queued_gps_points=EXCLUDED.queued_gps_points,
        queued_safety_events=EXCLUDED.queued_safety_events,
        queued_trips=EXCLUDED.queued_trips,
        received_at=CURRENT_TIMESTAMP"""),
      {'did':driver.id,'cid':driver.company_id,'vid':vehicle.id if vehicle else None,
       'screen':payload.screen_state,'active':payload.trip_active,
       'age':payload.gps_fix_age_s,'at':captured,'policy':payload.connectivity_policy_version,
       'gpsq':payload.queued_gps_points,'eventq':payload.queued_safety_events,'tripq':payload.queued_trips})
    db.commit()
    return {'accepted':True}

@app.get('/api/v1/tracking-heartbeats')
def list_tracking_heartbeats(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    args={} if user.role=='super_admin' else {'cid':user.company_id}
    rows=db.execute(text(f"""SELECT driver_id,company_id,vehicle_id,screen_state,
        trip_active,gps_fix_age_s,captured_at,received_at,
        queued_gps_points,queued_safety_events,queued_trips
        FROM mobile_tracking_heartbeat {where} ORDER BY received_at DESC LIMIT 500"""),args).mappings().all()
    return [dict(row) for row in rows]

# Driver alert preferences: separate from GPS privacy, append-only and location-free.

class NotificationEvidence(BaseModel):
    event_id: str = Field(min_length=8,max_length=90,pattern=r'^[a-zA-Z0-9_-]+$')
    notifications_enabled: bool
    selected_at: datetime

@app.post('/api/v1/mobile/notification-evidence')
def record_notification_evidence(payload: NotificationEvidence,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    selected=payload.selected_at
    if selected.tzinfo is None: selected=selected.replace(tzinfo=timezone.utc)
    selected=selected.astimezone(timezone.utc)
    if selected>datetime.now(timezone.utc)+timedelta(minutes=5) or selected<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid notification preference timestamp')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    existing=db.execute(text('SELECT driver_id,notifications_enabled FROM mobile_notification_audit WHERE event_id=:id'),{'id':payload.event_id}).first()
    if existing:
        if existing[0]!=driver.id or existing[1]!=payload.notifications_enabled: raise HTTPException(409,'Conflicting notification event ID')
        return {'accepted':True,'duplicate':True}
    db.execute(text('''INSERT INTO mobile_notification_audit
        (event_id,company_id,driver_id,vehicle_id,notifications_enabled,selected_at)
        VALUES (:id,:cid,:did,:vid,:enabled,:selected)'''),
        {'id':payload.event_id,'cid':driver.company_id,'did':driver.id,
         'vid':vehicle.id if vehicle else None,'enabled':payload.notifications_enabled,'selected':selected})
    db.commit()
    return {'accepted':True,'duplicate':False}

@app.get('/api/v1/notification-audit')
def list_notification_audit(limit:int=500,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    limit=max(1,min(limit,500))
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    args={'limit':limit} if user.role=='super_admin' else {'limit':limit,'cid':user.company_id}
    rows=db.execute(text(f'''SELECT event_id,company_id,driver_id,vehicle_id,notifications_enabled,selected_at,received_at
        FROM mobile_notification_audit {where} ORDER BY received_at DESC LIMIT :limit'''),args).mappings().all()
    return [dict(row) for row in rows]

# Camera activity: metadata only, never audio, photographs or video.

class SafetyObservation(BaseModel):
    event_id: str = Field(min_length=8,max_length=90,pattern=r'^[a-zA-Z0-9_-]+$')
    event_type: str
    speed_kmh: float | None = None
    observed_at: datetime

@app.post('/api/v1/mobile/safety-observation')
def record_safety_observation(payload:SafetyObservation,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    # This only reports camera-in-use observations, NOT confirmed video calls.
    if payload.event_type!='possible_camera_use_driving':
        raise HTTPException(422,'Unsupported observation type')
    if payload.speed_kmh is None or not math.isfinite(payload.speed_kmh) or not 30<=payload.speed_kmh<=250:
        raise HTTPException(422,'Invalid speed')
    when=payload.observed_at
    if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
    when=when.astimezone(timezone.utc)
    if not datetime.now(timezone.utc)-timedelta(days=7)<=when<=datetime.now(timezone.utc)+timedelta(minutes=5):
        raise HTTPException(422,'Invalid observation timestamp')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    existing=db.execute(text('SELECT driver_id FROM mobile_safety_observation WHERE event_id=:id'),{'id':payload.event_id}).first()
    if existing:
        if existing[0]!=driver.id:raise HTTPException(409,'Conflicting observation id')
        return {'accepted':True,'duplicate':True}
    db.execute(text("""INSERT INTO mobile_safety_observation (event_id,company_id,driver_id,vehicle_id,event_type,speed_kmh,observed_at)
      VALUES (:id,:company,:driver,:vehicle,:kind,:speed,:observed)"""),
      {'id':payload.event_id,'company':driver.company_id,'driver':driver.id,'vehicle':vehicle.id if vehicle else None,
       'kind':payload.event_type,'speed':payload.speed_kmh,'observed':when})
    db.commit()
    return {'accepted':True,'duplicate':False}

@app.get('/api/v1/safety-observations')
def list_safety_observations(limit:int=100,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    params={'limit':max(1,min(500,limit))}
    if user.role!='super_admin':params['cid']=user.company_id
    return [dict(row) for row in db.execute(text(f"""SELECT event_id,company_id,driver_id,vehicle_id,event_type,speed_kmh,observed_at,received_at
      FROM mobile_safety_observation {where} ORDER BY received_at DESC LIMIT :limit"""),params).mappings()]
