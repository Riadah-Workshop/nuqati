"""Live fleet snapshot, active-event settings, live position requests and public live shares."""

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..audit import audit
from ..auth import allow, current_user, scope
from ..db import get_db
from ..models import AppSetting, Driver, DriverLocation, DrivingEvent, Trip, User, Vehicle
from .fleet_settings import EVENT_KINDS
from .geofence_zones import (
    _company_for_policy,
    _setting_json,
    _zone_boundary_distance_m,
    _zone_contains,
    phase4_zones,
)
from .shared import own_driver

# Fleet live telemetry: dedicated company-scoped snapshot, separate from the
# period-based score reports. No location is invented when the GPS is stale.
@app.get('/api/v1/fleet/live-snapshot')
def fleet_live_snapshot(company_id: int | None = None, minutes: int = 30,
                        db: Session = Depends(get_db), user: User = Depends(current_user)):
    cid = _company_for_policy(db, user, company_id)
    minutes = max(1, min(minutes, 180))
    now = datetime.now(timezone.utc)
    zones = phase4_zones(db, cid)
    vehicles = list(db.scalars(select(Vehicle).where(Vehicle.company_id == cid).order_by(Vehicle.plate_number)).all())
    drivers = {d.id: d for d in db.scalars(select(Driver).where(Driver.company_id == cid)).all()}
    positions = []
    for vehicle in vehicles:
        loc = None
        trip = None
        if vehicle.assigned_driver_id:
            loc = db.scalar(select(DriverLocation).where(
                DriverLocation.company_id == cid,
                DriverLocation.driver_id == vehicle.assigned_driver_id,
                DriverLocation.trip_id.in_(select(Trip.id).where(Trip.vehicle_id == vehicle.id))
            ).order_by(DriverLocation.recorded_at.desc(), DriverLocation.id.desc()).limit(1))
            if loc:
                trip = db.get(Trip, loc.trip_id)
        # A completed on-demand request can provide a fresher snapshot than
        # the normal trip samples. Keep the result separate from trip mileage.
        requested = _setting_json(db, f'live_request:{vehicle.id}', {})
        # Preserve the last explicitly requested GPS fix even after a later request
        # becomes pending/expired. A stale fix is shown as STALE, never as live.
        latest_requested = _setting_json(db, f'last_live_fix:{vehicle.id}', {})
        request_result = requested.get('result') if requested.get('status') == 'completed' else None
        if (not request_result or request_result.get('driver_id') != vehicle.assigned_driver_id):
            request_result = latest_requested
        if request_result and request_result.get('driver_id') == vehicle.assigned_driver_id:
            try:
                requested_at = datetime.fromisoformat(request_result['recorded_at'])
                existing_at = (loc.recorded_at.replace(tzinfo=timezone.utc) if loc and loc.recorded_at.tzinfo is None else loc.recorded_at) if loc else None
                if (not existing_at or requested_at > existing_at) and requested_at <= now + timedelta(seconds=5):
                    from types import SimpleNamespace
                    loc = SimpleNamespace(latitude=request_result['latitude'],longitude=request_result['longitude'],
                                          speed_kmh=request_result['speed_kmh'],accuracy_m=request_result['accuracy_m'],
                                          recorded_at=requested_at)
                    trip = None
            except (KeyError,ValueError,TypeError): pass
        driver = drivers.get(vehicle.assigned_driver_id)
        age = max(0, (now - (loc.recorded_at.replace(tzinfo=timezone.utc) if loc.recorded_at.tzinfo is None else loc.recorded_at)).total_seconds()) if loc else None
        privacy_on = False
        if vehicle.assigned_driver_id:
            audit = db.execute(text('''SELECT privacy_enabled FROM mobile_privacy_audit
                WHERE driver_id=:did ORDER BY selected_at DESC LIMIT 1'''),
                {'did':vehicle.assigned_driver_id}).first()
            privacy_on = bool(audit and audit[0])
        accurate = bool(not privacy_on and loc and loc.accuracy_m is not None and 0 <= loc.accuracy_m <= 100)
        recent = bool(accurate and age is not None and age <= 300)
        speed = float(loc.speed_kmh or 0) if loc else None
        state = ('moving' if speed is not None and speed >= 5 else
                 'stationary' if speed is not None and speed <= 2 else 'uncertain') if recent else 'stale'
        if privacy_on: state = 'privacy'
        memberships = []
        if loc and accurate:
            for zone in zones:
                if zone.get('vehicle_ids') is not None and vehicle.id not in zone['vehicle_ids']:
                    continue
                distance_to_boundary = _zone_boundary_distance_m(zone, loc.latitude, loc.longitude)
                # GPS accuracy overlapping a circle or polygon boundary is uncertain.
                if distance_to_boundary <= max(5, float(loc.accuracy_m or 0)):
                    membership = 'boundary_uncertain'
                else:
                    membership = 'inside' if _zone_contains(zone, loc.latitude, loc.longitude) else 'outside'
                memberships.append({'id':zone['id'],'name':zone['name'],'status':membership,
                                    'speed_limit_kmh':zone.get('speed_limit_kmh')})
        positions.append({'vehicle_id':vehicle.id,'plate':vehicle.plate_number,'make_model':vehicle.make_model,
                          'driver_id':driver.id if driver else None,'driver_name':driver.full_name if driver else None,
                          'latitude':loc.latitude if loc and accurate else None,
                          'longitude':loc.longitude if loc and accurate else None,
                          'speed_kmh':speed if accurate else None,'accuracy_m':loc.accuracy_m if accurate else None,
                          'recorded_at':loc.recorded_at.isoformat() if loc and not privacy_on else None,
                          'age_seconds':round(age) if age is not None and not privacy_on else None,
                          'state':state,'trip_active':bool(trip and trip.status == 'active'),
                          'geofences':memberships})
    since = now - timedelta(minutes=minutes)
    active_kinds = _setting_json(db, f'live_active_event_kinds:{cid}',
                                 ['speeding','geofence_entry','geofence_exit','geofence_restricted'])
    # A passive event is always retained for history, never promoted into live scoring.
    recent_events = list(db.scalars(select(DrivingEvent).where(
        DrivingEvent.company_id == cid, DrivingEvent.recorded_at >= since,
        DrivingEvent.latitude.is_not(None), DrivingEvent.longitude.is_not(None)
    ).order_by(DrivingEvent.recorded_at.desc()).limit(300)).all())
    may_view_passive = user.role in ('super_admin','company_admin','fleet_manager')
    events = [{'id':e.id,'type':e.event_type,'driver_id':e.driver_id,
               'recorded_at':e.recorded_at.isoformat(),'latitude':e.latitude,'longitude':e.longitude,
               'value':e.value,'layer':'active' if e.event_type in active_kinds else 'passive'}
              for e in recent_events if e.event_type in active_kinds or may_view_passive]
    return {'company_id':cid,'generated_at':now.isoformat(),'positions':positions,
            'zones':zones,'events':events,'active_event_kinds':active_kinds}

class LiveActiveEventsIn(BaseModel):
    event_types: list[str]

@app.put('/api/v1/fleet/live-active-events')
def update_live_active_events(payload: LiveActiveEventsIn, company_id:int | None = None,
                              db:Session = Depends(get_db),user:User = Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid = _company_for_policy(db,user,company_id)
    supported = set(EVENT_KINDS)
    if len(payload.event_types) != len(set(payload.event_types)) or any(k not in supported for k in payload.event_types):
        raise HTTPException(422,'Invalid event types')
    key = f'live_active_event_kinds:{cid}'
    row = db.get(AppSetting,key)
    if row: row.value = json.dumps(payload.event_types)
    else: db.add(AppSetting(key=key,value=json.dumps(payload.event_types)))
    db.commit()
    return {'active_event_kinds':payload.event_types}

# On-demand position requests use a short-lived command; a driver app must
# actually return a fresh fix. No device can be remotely forced to enable GPS.
class LivePositionReply(BaseModel):
    request_id: str = Field(min_length=12,max_length=80)
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    accuracy_m: float = Field(ge=0,le=1000)
    speed_kmh: float = Field(ge=0,le=350)
    recorded_at: datetime

@app.post('/api/v1/fleet/live-position-request/{vehicle_id}')
def request_live_position(vehicle_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    vehicle=db.get(Vehicle,vehicle_id)
    if not vehicle:raise HTTPException(404,'Vehicle not found')
    scope(user,vehicle.company_id)
    if not vehicle.assigned_driver_id:raise HTTPException(422,'Vehicle has no assigned driver')
    key=f'live_request:{vehicle_id}'
    old=_setting_json(db,key,{})
    now=datetime.now(timezone.utc)
    if old.get('requested_at'):
        try:
            elapsed=(now-datetime.fromisoformat(old['requested_at'])).total_seconds()
            if elapsed<30:raise HTTPException(429,'Wait 30 seconds between position requests')
        except ValueError: pass
    data={'request_id':secrets.token_urlsafe(18),'vehicle_id':vehicle_id,
          'driver_id':vehicle.assigned_driver_id,'requested_at':now.isoformat(),
          'expires_at':(now+timedelta(minutes=2)).isoformat(),'status':'pending'}
    row=db.get(AppSetting,key)
    if row:row.value=json.dumps(data)
    else:db.add(AppSetting(key=key,value=json.dumps(data)))
    db.commit()
    return {'request_id':data['request_id'],'status':'pending','expires_at':data['expires_at']}

@app.get('/api/v1/mobile/live-position-request')
def mobile_live_position_request(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.company_id==d.company_id,Vehicle.assigned_driver_id==d.id))
    if not v:return {'status':'none'}
    data=_setting_json(db,f'live_request:{v.id}',{})
    if not data or data.get('driver_id')!=d.id or data.get('status')!='pending':return {'status':'none'}
    try:
        if datetime.fromisoformat(data['expires_at'])<datetime.now(timezone.utc):return {'status':'expired'}
    except (ValueError,KeyError):return {'status':'none'}
    return {'status':'pending','request_id':data['request_id']}

@app.post('/api/v1/mobile/live-position-reply')
def mobile_live_position_reply(payload:LivePositionReply,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.company_id==d.company_id,Vehicle.assigned_driver_id==d.id))
    if not v:raise HTTPException(404,'Assigned vehicle missing')
    key=f'live_request:{v.id}'
    data=_setting_json(db,key,{})
    now=datetime.now(timezone.utc)
    if data.get('driver_id')!=d.id or data.get('request_id')!=payload.request_id or data.get('status')!='pending':
        raise HTTPException(409,'Position request is no longer pending')
    if datetime.fromisoformat(data['expires_at'])<now:raise HTTPException(410,'Position request expired')
    at=payload.recorded_at.replace(tzinfo=timezone.utc) if payload.recorded_at.tzinfo is None else payload.recorded_at.astimezone(timezone.utc)
    if abs((now-at).total_seconds())>90:raise HTTPException(422,'A fresh GPS fix is required')
    if payload.accuracy_m>100:raise HTTPException(422,'GPS accuracy too low')
    result={'latitude':payload.latitude,'longitude':payload.longitude,'recorded_at':at.isoformat(),
            'accuracy_m':payload.accuracy_m,'speed_kmh':payload.speed_kmh,'vehicle_id':v.id,'driver_id':d.id}
    data['status']='completed';data['result']=result
    db.get(AppSetting,key).value=json.dumps(data)
    # Store this independently so a new pending request never erases the
    # previous known position. Privacy enforcement remains in live-snapshot.
    last_key=f'last_live_fix:{v.id}'
    last_row=db.get(AppSetting,last_key)
    if last_row:last_row.value=json.dumps(result)
    else:db.add(AppSetting(key=last_key,value=json.dumps(result)))
    db.commit()
    return {'accepted':True}

@app.get('/api/v1/fleet/live-position-request/{vehicle_id}')
def live_position_request_status(vehicle_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    v=db.get(Vehicle,vehicle_id)
    if not v:raise HTTPException(404,'Vehicle not found')
    scope(user,v.company_id)
    data=_setting_json(db,f'live_request:{vehicle_id}',{})
    if not data:return {'status':'none'}
    status=data.get('status','none')
    if data.get('expires_at') and datetime.fromisoformat(data['expires_at'])<datetime.now(timezone.utc) and status=='pending':status='expired'
    return {'status':status,'requested_at':data.get('requested_at'),'result':data.get('result') if status=='completed' else None}

# Private per-creator links. Public route only exposes a fresh position of
# one explicitly selected vehicle; never shares historical trails or identities.
class LiveShareCreate(BaseModel):
    vehicle_id: int
    expiry_minutes: int = Field(default=15,ge=1,le=60)

@app.post('/api/v1/fleet/live-shares')
def create_live_share(payload:LiveShareCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    v=db.get(Vehicle,payload.vehicle_id)
    if not v:raise HTTPException(404,'Vehicle not found')
    scope(user,v.company_id)
    token=secrets.token_urlsafe(32)
    digest=hashlib.sha256(token.encode()).hexdigest()
    record={'creator_id':user.id,'vehicle_id':v.id,'company_id':v.company_id,
            'created_at':datetime.now(timezone.utc).isoformat(),
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=payload.expiry_minutes)).isoformat(),
            'revoked':False}
    db.add(AppSetting(key=f'live_share:{digest}',value=json.dumps(record)))
    audit(db,'live_share.create',actor=user,target_type='vehicle',target_id=v.id,company_id=v.company_id,detail={'expiry_minutes':payload.expiry_minutes})
    db.commit()
    return {'share_id':digest,'token':token,'expires_at':record['expires_at']}

@app.get('/api/v1/fleet/live-shares')
def list_live_shares(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    rows=db.scalars(select(AppSetting).where(AppSetting.key.like('live_share:%'))).all()
    items=[]
    for row in rows:
        try:data=json.loads(row.value)
        except (TypeError,ValueError):continue
        if data.get('creator_id')==user.id:
            items.append({'share_id':row.key.split(':',1)[1],**data})
    return items

@app.delete('/api/v1/fleet/live-shares/{share_id}')
def revoke_live_share(share_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    if len(share_id)!=64 or any(c not in '0123456789abcdef' for c in share_id):raise HTTPException(404,'Not found')
    row=db.get(AppSetting,f'live_share:{share_id}')
    if not row:raise HTTPException(404,'Not found')
    data=json.loads(row.value)
    if data.get('creator_id')!=user.id:raise HTTPException(404,'Not found')
    data['revoked']=True;row.value=json.dumps(data)
    audit(db,'live_share.revoke',actor=user,target_type='vehicle',target_id=data.get('vehicle_id'),company_id=data.get('company_id'))
    db.commit()
    return {'revoked':True}

@app.get('/api/v1/public/live-share/{token}')
def read_live_share(token:str,db:Session=Depends(get_db)):
    if len(token)<32 or len(token)>120:raise HTTPException(404,'Link unavailable')
    row=db.get(AppSetting,'live_share:'+hashlib.sha256(token.encode()).hexdigest())
    if not row:raise HTTPException(404,'Link unavailable')
    data=json.loads(row.value)
    if data.get('revoked') or datetime.fromisoformat(data['expires_at'])<datetime.now(timezone.utc):
        raise HTTPException(410,'Link expired')
    v=db.get(Vehicle,data['vehicle_id'])
    if not v or v.company_id!=data['company_id'] or not v.assigned_driver_id:
        raise HTTPException(404,'Vehicle unavailable')
    loc=db.scalar(select(DriverLocation).where(DriverLocation.company_id==v.company_id,
        DriverLocation.driver_id==v.assigned_driver_id,
        DriverLocation.trip_id.in_(select(Trip.id).where(Trip.vehicle_id==v.id)))
        .order_by(DriverLocation.recorded_at.desc()).limit(1))
    if not loc:return {'status':'unavailable','expires_at':data['expires_at']}
    at=loc.recorded_at.replace(tzinfo=timezone.utc) if loc.recorded_at.tzinfo is None else loc.recorded_at
    age=(datetime.now(timezone.utc)-at).total_seconds()
    privacy=db.execute(text('''SELECT privacy_enabled,selected_at FROM mobile_privacy_audit
      WHERE driver_id=:did ORDER BY selected_at DESC LIMIT 1'''),{'did':v.assigned_driver_id}).first()
    if privacy and privacy[0]:return {'status':'unavailable','expires_at':data['expires_at']}
    trip=db.get(Trip,loc.trip_id)
    if not trip or trip.status!='active' or age<0 or age>120 or loc.accuracy_m is None or loc.accuracy_m>100:
        return {'status':'unavailable','expires_at':data['expires_at']}
    return {'status':'available','plate':v.plate_number,'latitude':loc.latitude,'longitude':loc.longitude,
            'speed_kmh':loc.speed_kmh,'recorded_at':at.isoformat(),'expires_at':data['expires_at']}
