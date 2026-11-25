"""Trip lifecycle and ingestion: start, GPS samples, safety events, finish, force-end, delete, search, route, fleet report."""

import math
from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import engine, get_db
from ..models import Driver, DriverLocation, DrivingEvent, OdometerReading, Trip, User, Vehicle
from .driving_policy import event_condition_view, gps_compare
from .fleet_settings import event_policy, severity_settings, thresholds
from .geofence_zones import phase4_candidates, phase4_settings
from .scoring import calculate_safety_score, flexible_rag_policy, score_policy
from .shared import own_driver

# Driver/company-scoped human-facing trip numbers are separate from the global,
# PostgreSQL-assigned trips.id. Backfill existing trips once in a transaction.
# Existing trip numbers are stable; deleted testing trips can be reset normally.

def trip_number_for(db: Session, trip: Trip) -> int:
    '''Must be called with the owner's Driver row locked for allocation.'''
    number=db.scalar(text('SELECT trip_number FROM mobile_trip_numbers WHERE trip_id=:id'), {'id':trip.id})
    if number is not None: return int(number)
    number=db.scalar(text('''SELECT COALESCE(MAX(trip_number),0)+1
        FROM mobile_trip_numbers WHERE company_id=:c AND driver_id=:d'''),
        {'c':trip.company_id,'d':trip.driver_id})
    db.execute(text('''INSERT INTO mobile_trip_numbers
        (trip_id,company_id,driver_id,trip_number) VALUES (:id,:c,:d,:n)'''),
        {'id':trip.id,'c':trip.company_id,'d':trip.driver_id,'n':number})
    return int(number)

@app.get('/api/v1/mobile/trips/sync-state')
def mobile_trip_sync_state(db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Authoritative driver-scoped trip state. IDs are allocated only by PostgreSQL."""
    d=own_driver(db,user)
    latest=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id).order_by(Trip.id.desc()).limit(1))
    active=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id,Trip.status=='active').order_by(Trip.id.desc()).limit(1))
    last_number=db.scalar(text('''SELECT MAX(trip_number) FROM mobile_trip_numbers
        WHERE company_id=:c AND driver_id=:d'''),{'c':d.company_id,'d':d.id}) or 0
    return {'driver_id':d.id,'company_id':d.company_id,
            'latest_trip_id':latest.id if latest else None,
            'latest_trip_number':int(last_number) if last_number else None,
            'next_trip_number':int(last_number)+1,
            'latest_trip_status':latest.status if latest else None,
            'active_trip_id':active.id if active else None,
            'server_assigns_trip_ids':True}

@app.get('/api/v1/mobile/trips/active')
def get_active_mobile_trip(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    trip=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id,Trip.status=='active').order_by(Trip.id.desc()).limit(1))
    if not trip:
        return {'active':False,'trip_id':None}
    number=db.scalar(text('SELECT trip_number FROM mobile_trip_numbers WHERE trip_id=:id'),{'id':trip.id})
    return {'active':True,'trip_id':trip.id,'trip_number':int(number) if number is not None else None,
            'started_at':trip.started_at.isoformat() if trip.started_at else None}

# Stable device trip IDs make retries idempotent and preserve offline trip boundaries.

class OfflineTripStart(BaseModel):
    client_trip_id: str | None = Field(default=None, min_length=8, max_length=90, pattern=r'^[a-zA-Z0-9_-]+$')
    started_at: datetime | None = None
    recorded_driver_id: int | None = None
    recorded_company_id: int | None = None
    recorded_vehicle_id: int | None = None

class OfflineTripFinish(BaseModel):
    ended_at: datetime | None = None

def _safe_device_time(value:datetime | None):
    if value is None: return datetime.now(timezone.utc)
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    value=value.astimezone(timezone.utc)
    if value>datetime.now(timezone.utc)+timedelta(minutes=5) or value<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid device trip timestamp')
    return value

@app.post('/api/v1/mobile/trips/start', status_code=201)
def start_mobile_trip(payload:OfflineTripStart | None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    # Serialize starts for this driver so concurrent retries cannot allocate two trips.
    db.scalar(select(Driver).where(Driver.id==d.id).with_for_update())
    client_id=payload.client_trip_id if payload else None
    # Offline uploads must carry the immutable identity recorded when the trip began.
    if client_id:
        if not payload or payload.recorded_driver_id!=d.id or payload.recorded_company_id!=d.company_id or not payload.recorded_vehicle_id:
            raise HTTPException(403,'Recorded trip owner does not match authenticated driver and company')
        # Client IDs are global across drivers; never accept another driver's mapping.
        collision=db.execute(text('SELECT driver_id FROM mobile_trip_client_ids WHERE client_trip_id=:c AND driver_id<>:d LIMIT 1'),{'c':client_id,'d':d.id}).first()
        if collision: raise HTTPException(409,'Client trip ID belongs to a different driver')
    started=_safe_device_time(payload.started_at if payload else None)
    if client_id:
        deleted=db.execute(text('SELECT 1 FROM deleted_mobile_trip_clients WHERE driver_id=:d AND client_trip_id=:c'),{'d':d.id,'c':client_id}).first()
        if deleted:raise HTTPException(410,'This trip was permanently deleted by an administrator')
        mapping=db.execute(text('SELECT trip_id FROM mobile_trip_client_ids WHERE driver_id=:d AND client_trip_id=:c'),{'d':d.id,'c':client_id}).first()
        if mapping:
            existing=db.get(Trip,mapping[0])
            if not existing: raise HTTPException(409,'Mapped trip missing')
            if existing.driver_id!=d.id or existing.company_id!=d.company_id or existing.vehicle_id!=payload.recorded_vehicle_id:
                raise HTTPException(403,'Recorded trip identity does not match original trip')
            trip_number=trip_number_for(db,existing)
            db.commit()
            return {'trip_id':existing.id,'trip_number':trip_number,'started_at':existing.started_at.isoformat(),'resumed':True}
    v=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))
    if not v: raise HTTPException(409,'Assign a vehicle to this driver first')
    if client_id and v.id!=payload.recorded_vehicle_id:
        raise HTTPException(409,'Recorded vehicle differs from currently assigned vehicle; manual review required')
    if not client_id:
        # Preserve the legacy start/resume contract for callers without device IDs.
        existing=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id,
                                            Trip.status=='active').order_by(Trip.id.desc()).limit(1))
        if existing:
            trip_number=trip_number_for(db,existing)
            db.commit()
            return {'trip_id':existing.id,'trip_number':trip_number,'started_at':existing.started_at.isoformat(),'resumed':True}
    # A different client ID is a different locally recorded journey. An older active
    # record must not block offline replay or absorb this journey's GPS/events.
    # Leave it intact: only its own finish request may finalize it and its mileage.
    trip=Trip(company_id=d.company_id,driver_id=d.id,vehicle_id=v.id,status='active',started_at=started)
    db.add(trip);db.flush()
    trip_number=trip_number_for(db,trip)
    if client_id:
        db.execute(text('INSERT INTO mobile_trip_client_ids (driver_id,client_trip_id,trip_id) VALUES (:d,:c,:t)'),
                   {'d':d.id,'c':client_id,'t':trip.id})
    db.commit();db.refresh(trip)
    return {'trip_id':trip.id,'trip_number':trip_number,'started_at':trip.started_at.isoformat()}

# Phase 1B: persist client sample IDs so reconnect retries cannot duplicate GPS points.
# This additive table does not modify existing trip/location schemas.

class Sample(BaseModel):
    sample_id: str | None = Field(default=None, min_length=8, max_length=80)
    captured_at: datetime | None = None
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    accuracy_m: float = Field(ge=0,le=10000)
    speed_kmh: float = Field(ge=0,le=350)
    acceleration_ms2: float = Field(ge=-30,le=30,default=0)
    gps_age_seconds: float | None = Field(default=None,ge=0,le=3600)
    gps_hdop: float | None = Field(default=None,ge=0,le=100)
    gps_satellites: int | None = Field(default=None,ge=0,le=100)

def _mobile_replay_days(db, trip, stable_id):
    if stable_id and db.execute(text('SELECT 1 FROM mobile_trip_client_ids WHERE trip_id=:t AND driver_id=:d'),
                               {'t':trip.id,'d':trip.driver_id}).first():
        return 90  # Same maximum age as offline trip creation.
    return 14

@app.post('/api/v1/mobile/trips/{trip_id}/sample')
def submit_sample(trip_id:int,data:Sample,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id or trip.company_id!=d.company_id: raise HTTPException(404,'Trip not found')
    if trip.status not in ('active','completed'): raise HTTPException(409,'Trip is not eligible for GPS samples')
    if data.accuracy_m>50: return {'accepted':False,'reason':'GPS accuracy worse than 50m'}
    now=datetime.now(timezone.utc)
    captured=data.captured_at or now
    if captured.tzinfo is None: captured=captured.replace(tzinfo=timezone.utc)
    captured=captured.astimezone(timezone.utc)
    if captured>now+timedelta(seconds=30) or (captured<now-timedelta(days=14) and captured<now-timedelta(days=_mobile_replay_days(db,trip,data.sample_id))):
        raise HTTPException(422,'GPS capture time outside accepted range')
    if captured < (trip.started_at.replace(tzinfo=timezone.utc) if trip.started_at.tzinfo is None else trip.started_at.astimezone(timezone.utc))-timedelta(seconds=30):
        raise HTTPException(422,'GPS capture time outside accepted range')
    if data.sample_id:
        seen=db.execute(text('SELECT 1 FROM mobile_gps_sample_receipts WHERE trip_id=:t AND sample_id=:s'),{'t':trip.id,'s':data.sample_id}).first()
        if seen: return {'accepted':True,'duplicate':True,'events':[],'rejected_events':{}}

    if trip.status=='completed':
        # Historical uploads must belong to this completed journey, not a newer trip.
        # Keep the trip, score, distance and already-posted odometer unchanged.
        def as_utc(value):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        if not trip.ended_at or captured<as_utc(trip.started_at)-timedelta(seconds=30) or captured>as_utc(trip.ended_at)+timedelta(seconds=30):
            raise HTTPException(422,'GPS capture time outside completed trip interval')
        # Legacy samples without IDs cannot be reliably deduplicated on retry.
        # Require stable IDs for completed-trip uploads to avoid duplicate history.
        if not data.sample_id:
            raise HTTPException(422,'sample_id required for completed trip replay')
        db.add(DriverLocation(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,
            latitude=data.latitude,longitude=data.longitude,accuracy_m=data.accuracy_m,
            speed_kmh=data.speed_kmh,recorded_at=captured))
        db.execute(text('INSERT INTO mobile_gps_sample_receipts (trip_id,sample_id,captured_at) VALUES (:t,:s,:c)'),
            {'t':trip.id,'s':data.sample_id,'c':captured})
        db.commit()
        return {'accepted':True,'historical':True,'events':[],'rejected_events':{}}

    previous=db.scalar(select(DriverLocation).where(DriverLocation.trip_id==trip.id).order_by(DriverLocation.id.desc()).limit(1))
    if previous:
        previous_at = previous.recorded_at.replace(tzinfo=timezone.utc) if previous.recorded_at.tzinfo is None else previous.recorded_at.astimezone(timezone.utc)
        elapsed_since_previous = (captured - previous_at).total_seconds()
        if elapsed_since_previous < 0:
            raise HTTPException(422, 'GPS sample older than latest accepted sample; upload oldest first')
        if elapsed_since_previous < 0.7:
            # A sub-700ms sample is a redundant GPS fix, not a transient HTTP rate limit.
            # Acknowledge its stable ID without double-counting distance or events.
            if data.sample_id:
                db.execute(text('INSERT INTO mobile_gps_sample_receipts (trip_id,sample_id,captured_at) VALUES (:t,:s,:c) ON CONFLICT (trip_id,sample_id) DO NOTHING'),
                           {'t':trip.id,'s':data.sample_id,'c':captured})
                db.commit()
            return {'accepted':True,'duplicate':True,'filtered_short_interval':True,'events':[],'rejected_events':{}}
    row=DriverLocation(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,latitude=data.latitude,longitude=data.longitude,accuracy_m=data.accuracy_m,speed_kmh=data.speed_kmh,recorded_at=captured)
    db.add(row)
    # Accumulate plausible point-to-point distance; ignore GPS jumps and stationary jitter.
    if previous and previous.accuracy_m is not None and previous.accuracy_m<=30 and data.accuracy_m<=30:
        elapsed=(captured-previous.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()
        a1,a2=math.radians(previous.latitude),math.radians(data.latitude)
        da=a2-a1; dl=math.radians(data.longitude-previous.longitude)
        h=math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2
        metres=6371000*2*math.asin(min(1.0,math.sqrt(max(0.0,h))))
        # Avoid counting stationary GPS noise; reject impossible jumps.
        if elapsed>0 and 5<=metres<=min(80*elapsed,1000) and (metres/elapsed)<=max(12.0,data.speed_kmh/3.6+8.0):
            trip.distance_km=(trip.distance_km or 0.0)+metres/1000
    cfg=thresholds(db,d.company_id); policy=event_policy(db,d.company_id); kinds=[]
    if policy['enabled']['speeding'] and data.speed_kmh>cfg.speeding_kmh:
        severe_speed=cfg.speeding_kmh+score_policy(db,d.company_id)['excessive_speed_margin_kmh']
        speed_kind='excessive_speeding' if data.speed_kmh>severe_speed and policy['enabled'].get('excessive_speeding',True) else 'speeding'
        kinds.append((speed_kind,data.speed_kmh))
    if policy['enabled']['harsh_acceleration'] and data.acceleration_ms2>=cfg.harsh_accel_ms2:
        severe=severity_settings(db,d.company_id)['aggressive_accel_ms2']
        kind='excessive_harsh_acceleration' if data.acceleration_ms2>=severe and policy['enabled'].get('excessive_harsh_acceleration',True) else 'harsh_acceleration'
        kinds.append((kind,data.acceleration_ms2))
    if policy['enabled']['harsh_braking'] and data.acceleration_ms2<=-cfg.harsh_brake_ms2:
        severe=severity_settings(db,d.company_id)['aggressive_brake_ms2']
        kind='excessive_harsh_braking' if -data.acceleration_ms2>=severe and policy['enabled'].get('excessive_harsh_braking',True) else 'harsh_braking'
        kinds.append((kind,abs(data.acceleration_ms2)))
    # Confirm accelerometer-like GPS speed delta independently; a single GPS speed
    # glitch or a large gap must not deduct driver points.
    if previous:
        delta=(captured-previous.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()
        prev_speed=previous.speed_kmh or 0.0
        if 0.7 <= delta <= 5 and previous.accuracy_m <= 20 and data.accuracy_m <= 20 and max(prev_speed,data.speed_kmh)>=15:
            derived=(data.speed_kmh-prev_speed)/3.6/delta
            kinds=[(kind,value) for kind,value in kinds if kind.removeprefix('excessive_') not in ('harsh_braking','harsh_acceleration') or (kind.removeprefix('excessive_')=='harsh_braking' and derived<=-cfg.harsh_brake_ms2 and abs(derived-data.acceleration_ms2)<=2.0) or (kind.removeprefix('excessive_')=='harsh_acceleration' and derived>=cfg.harsh_accel_ms2 and abs(derived-data.acceleration_ms2)<=2.0)]
        else:
            kinds=[(kind,value) for kind,value in kinds if kind.removeprefix('excessive_') not in ('harsh_braking','harsh_acceleration')]
    else:
        kinds=[(kind,value) for kind,value in kinds if kind.removeprefix('excessive_') not in ('harsh_braking','harsh_acceleration')]
    kinds.extend((kind,value) for kind,value in phase4_candidates(db,trip,previous,data,captured) if policy['enabled'].get(kind,False))
    # Fail closed for missing or stale GPS metadata when a condition is enabled.
    # Location history can still be stored; only qualified samples create violations.
    qualified=[];rejected={}
    for kind,value in kinds:
        cond=event_condition_view(db,d.company_id,kind)
        if not policy['enforce_gps_conditions']:
            qualified.append((kind,value))
            continue
        reason=None
        if not gps_compare(data.accuracy_m,cond['accuracy_operator'],cond['max_accuracy_m']): reason='gps_accuracy'
        elif data.gps_age_seconds is None or not gps_compare(data.gps_age_seconds,cond['gps_age_operator'],cond['max_gps_age_seconds']): reason='gps_age_missing_or_stale'
        elif cond['max_hdop'] is not None and (data.gps_hdop is None or not gps_compare(data.gps_hdop,cond['hdop_operator'],cond['max_hdop'])): reason='gps_hdop_missing_or_high'
        elif cond['min_satellites'] is not None and (data.gps_satellites is None or not gps_compare(data.gps_satellites,cond['satellites_operator'],cond['min_satellites'])): reason='gps_satellites_missing_or_low'
        if reason: rejected[kind]=reason
        else: qualified.append((kind,value))
    # One event per category per 30 seconds, to avoid counting every sample as a separate violation.
    for kind,value in qualified:
        latest=db.scalar(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id,DrivingEvent.event_type==kind).order_by(DrivingEvent.id.desc()).limit(1))
        if latest and (captured-latest.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()<30: continue
        db.add(DrivingEvent(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,event_type=kind,value=value,latitude=data.latitude,longitude=data.longitude,recorded_at=captured))
    if data.sample_id:
        db.execute(text('INSERT INTO mobile_gps_sample_receipts (trip_id,sample_id,captured_at) VALUES (:t,:s,:c)'),
                   {'t':trip.id,'s':data.sample_id,'c':captured})
    db.commit();return {'accepted':True,'events': [x[0] for x in qualified], 'rejected_events': rejected}

# Stable receipts for locally detected events. Each receipt is scoped to the authenticated driver.

class LocalSafetyEvent(BaseModel):
    event_id: str = Field(min_length=8,max_length=160)
    event_type: str
    recorded_at: datetime
    value: float | None = None

@app.post('/api/v1/mobile/trips/{trip_id}/safety-event')
def sync_mobile_safety_event(trip_id:int,data:LocalSafetyEvent,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id or trip.company_id!=d.company_id:
        raise HTTPException(404,'Trip not found')
    kinds={'speeding','excessive_speeding','harsh_braking','excessive_harsh_braking',
           'harsh_acceleration','excessive_harsh_acceleration','harsh_cornering',
           'speeding_session','excessive_speeding_session'}
    if data.event_type not in kinds:raise HTTPException(422,'Unsupported safety event')
    captured=data.recorded_at
    if captured.tzinfo is None:captured=captured.replace(tzinfo=timezone.utc)
    captured=captured.astimezone(timezone.utc)
    if captured>datetime.now(timezone.utc)+timedelta(seconds=30) or (captured<datetime.now(timezone.utc)-timedelta(days=14) and captured<datetime.now(timezone.utc)-timedelta(days=_mobile_replay_days(db,trip,data.event_id))):
        raise HTTPException(422,'Event timestamp outside sync window')
    if captured<trip.started_at.replace(tzinfo=timezone.utc)-timedelta(seconds=30):
        raise HTTPException(422,'Event before trip')
    if trip.ended_at and captured>(trip.ended_at.replace(tzinfo=timezone.utc) if trip.ended_at.tzinfo is None else trip.ended_at.astimezone(timezone.utc))+timedelta(seconds=30):
        raise HTTPException(422,'Event after trip')
    receipt=db.execute(text('SELECT 1 FROM mobile_safety_event_receipts WHERE driver_id=:d AND event_id=:e'),{'d':d.id,'e':data.event_id}).first()
    if receipt:return {'accepted':True,'duplicate':True}
    # Only accept events anchored to actual GPS data already uploaded by this driver.
    # GPS anchors arrive chronologically. Select the *closest* fix to the event,
    # not the last fix in a 10s window (which could have a much lower speed).
    point=db.scalar(select(DriverLocation).where(DriverLocation.trip_id==trip.id,
        DriverLocation.recorded_at>=captured-timedelta(seconds=5),
        DriverLocation.recorded_at<=captured+timedelta(seconds=5))
        .order_by(func.abs(func.extract('epoch',DriverLocation.recorded_at-captured)),DriverLocation.id.desc()).limit(1))
    if point is None:raise HTTPException(422,{'code':'GPS_ANCHOR_MISSING','message':'No matching GPS sample within 5 seconds','event_id':data.event_id})
    base=data.event_type.removeprefix('excessive_')
    settings=thresholds(db,d.company_id)
    if base=='speeding' and point.speed_kmh<=settings.speeding_kmh:
        # Acknowledge the mobile observation without adding an invalid backend violation.
        # Prevents a permanently unmatchable speed event from blocking all later uploads.
        db.execute(text('INSERT INTO mobile_safety_event_receipts(driver_id,event_id,trip_id) VALUES (:d,:e,:t)'),
                   {'d':d.id,'e':data.event_id,'t':trip.id})
        db.commit()
        return {'accepted':True,'recorded':False,'reason':'SPEED_BELOW_SERVER_THRESHOLD'}
    if data.event_type in ('speeding_session','excessive_speeding_session'):
        # A completed native session reports elapsed seconds at its end timestamp.
        # Store it as a distinct event, preserving existing score categories and schemas.
        if data.value is None or not math.isfinite(data.value) or data.value < 0 or data.value > 86400:
            raise HTTPException(422,'Invalid speeding duration')
        db.add(DrivingEvent(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,
            event_type=data.event_type,value=data.value,latitude=point.latitude,
            longitude=point.longitude,recorded_at=captured))
        db.execute(text('INSERT INTO mobile_safety_event_receipts(driver_id,event_id,trip_id) VALUES (:d,:e,:t)'),
                   {'d':d.id,'e':data.event_id,'t':trip.id})
        db.commit()
        return {'accepted':True,'recorded':True,'duration_seconds':data.value}
    if base=='harsh_cornering' and point.speed_kmh<phase4_settings(db,d.company_id)['min_cornering_speed_kmh']:
        raise HTTPException(422,'Cornering below minimum speed')
    if data.value is not None and (not math.isfinite(data.value) or data.value<0 or data.value>350):
        raise HTTPException(422,'Invalid event value')
    # A backend-derived event in the same 30-second window is the same incident.
    existing=db.scalar(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id,
        DrivingEvent.event_type.in_((base,'excessive_'+base)),
        DrivingEvent.recorded_at>=captured-timedelta(seconds=15),
        DrivingEvent.recorded_at<=captured+timedelta(seconds=15)).order_by(DrivingEvent.id.desc()).limit(1))
    if not existing:
        db.add(DrivingEvent(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,
            event_type=data.event_type,value=data.value or 0.0,latitude=point.latitude,
            longitude=point.longitude,recorded_at=captured))
    db.execute(text('INSERT INTO mobile_safety_event_receipts(driver_id,event_id,trip_id) VALUES (:d,:e,:t)'),
               {'d':d.id,'e':data.event_id,'t':trip.id})
    db.commit()
    return {'accepted':True,'matched_existing':bool(existing)}

@app.get('/api/v1/fleet/speeding-sessions')
def fleet_speeding_sessions(company_id:int|None=None,driver_id:int|None=None,limit:int=200,
                           db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None:raise HTTPException(422,'Choose a company')
    scope(user,cid)
    query=select(DrivingEvent).where(DrivingEvent.company_id==cid,
        DrivingEvent.event_type.in_(('speeding_session','excessive_speeding_session')))
    if driver_id is not None:query=query.where(DrivingEvent.driver_id==driver_id)
    events=db.scalars(query.order_by(DrivingEvent.recorded_at.desc()).limit(max(1,min(limit,1000)))).all()
    return {'company_id':cid,'sessions':[{'trip_id':e.trip_id,'driver_id':e.driver_id,
        'severity':'aggressive' if e.event_type=='excessive_speeding_session' else 'normal',
        'duration_seconds':e.value,'ended_at':e.recorded_at.isoformat(),
        'started_at':(e.recorded_at-timedelta(seconds=e.value)).isoformat()}
        for e in events]}

# Administrative recovery: does not fabricate GPS data or restart the driver's device.
class AdminTripEnd(BaseModel):
    reason: str = Field(min_length=8,max_length=500)

@app.post('/api/v1/fleet/trips/{trip_id}/force-end')
def force_end_fleet_trip(trip_id:int,payload:AdminTripEnd,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    trip=db.scalar(select(Trip).where(Trip.id==trip_id).with_for_update())
    if not trip:raise HTTPException(404,'Trip not found')
    if user.role!='super_admin' and trip.company_id!=user.company_id:
        raise HTTPException(403,'Trip belongs to another company')
    if trip.status!='active':raise HTTPException(409,'Only active trips may be force-ended')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.id==trip.vehicle_id).with_for_update())
    if not vehicle:raise HTTPException(404,'Vehicle not found')
    now=datetime.now(timezone.utc)
    trip.ended_at=max(now,trip.started_at.replace(tzinfo=timezone.utc))
    trip.status='completed'
    added=max(0.0,trip.distance_km or 0.0)
    if vehicle.odometer_km is not None and added>0:
        vehicle.odometer_km+=added
        db.add(OdometerReading(company_id=vehicle.company_id,vehicle_id=vehicle.id,reading_km=vehicle.odometer_km,source='GPS_TRIP',note=f'Admin-ended trip #{trip.id}: +{added:.3f} km'))
    db.execute(text('INSERT INTO admin_trip_end_audit(trip_id,company_id,performed_by,reason) VALUES (:t,:c,:u,:r)'),
      {'t':trip.id,'c':trip.company_id,'u':user.id,'r':payload.reason.strip()})
    db.commit()
    return {'trip_id':trip.id,'status':'completed','ended_by_admin':True,'distance_km':added,
            'warning':'This does not remotely stop the Android GPS service. The driver must reconcile server trip state.'}

# Explicit administrative removal; GPS receipt and client-trip mappings must not
# survive a deleted trip. A small tombstone prevents delayed offline replay from
# recreating it (the driver app must discard 410 Gone before trying again).

class AdminTripDelete(BaseModel):
    confirm_trip_id: int
    reason: str = Field(min_length=8,max_length=500)

def _admin_editable_trip(trip_id:int,db:Session,user:User):
    allow(user,'super_admin','company_admin')
    trip=db.scalar(select(Trip).where(Trip.id==trip_id).with_for_update())
    if trip is None:raise HTTPException(404,'Trip not found')
    scope(user,trip.company_id)
    if trip.status=='active':raise HTTPException(409,'End the trip before deleting it')
    return trip

@app.delete('/api/v1/fleet/trips/{trip_id}/events/{event_id}')
def delete_fleet_trip_event(trip_id:int,event_id:int,payload:AdminTripDelete,db:Session=Depends(get_db),user:User=Depends(current_user)):
    trip=_admin_editable_trip(trip_id,db,user)
    if payload.confirm_trip_id!=trip_id:raise HTTPException(422,'Trip confirmation does not match')
    event=db.scalar(select(DrivingEvent).where(DrivingEvent.id==event_id,DrivingEvent.trip_id==trip_id))
    if event is None:raise HTTPException(404,'Trip event not found')
    db.delete(event)
    db.execute(text("""INSERT INTO admin_trip_deletion_audit(trip_id,company_id,performed_by,action,event_id,reason)
      VALUES (:t,:c,:u,'delete_event',:e,:r)"""),{'t':trip_id,'c':trip.company_id,'u':user.id,'e':event_id,'r':payload.reason.strip()})
    db.commit()
    return {'deleted':True,'trip_id':trip_id,'event_id':event_id}

@app.delete('/api/v1/fleet/trips/{trip_id}')
def delete_fleet_trip(trip_id:int,payload:AdminTripDelete,db:Session=Depends(get_db),user:User=Depends(current_user)):
    trip=_admin_editable_trip(trip_id,db,user)
    if payload.confirm_trip_id!=trip_id:raise HTTPException(422,'Trip confirmation does not match')
    params={'t':trip_id,'c':trip.company_id,'u':user.id,'r':payload.reason.strip()}
    # Retain only the replay guard (not the trip or its GPS coordinates).
    db.execute(text("""INSERT INTO deleted_mobile_trip_clients(driver_id,client_trip_id)
      SELECT driver_id,client_trip_id FROM mobile_trip_client_ids WHERE trip_id=:t
      ON CONFLICT (driver_id,client_trip_id) DO NOTHING"""),params)
    events=db.execute(delete(DrivingEvent).where(DrivingEvent.trip_id==trip_id)).rowcount
    points=db.execute(delete(DriverLocation).where(DriverLocation.trip_id==trip_id)).rowcount
    for table in ('mobile_gps_sample_receipts','mobile_safety_event_receipts',
                  'mobile_trip_client_ids','mobile_trip_numbers'):
        db.execute(text(f'DELETE FROM {table} WHERE trip_id=:t'),params)
    # Preserve the independent audit trail but remove trip-specific mileage adjustments.
    db.execute(text("DELETE FROM odometer_readings WHERE source='GPS_TRIP' AND note LIKE :note"),{'note':f'%trip #{trip_id}: %'})
    db.delete(trip)
    db.execute(text("""INSERT INTO admin_trip_deletion_audit(trip_id,company_id,performed_by,action,reason)
      VALUES (:t,:c,:u,'delete_trip',:r)"""),params)
    db.commit()
    return {'deleted':True,'trip_id':trip_id,'events_removed':events,'gps_points_removed':points,
            'note':'Existing vehicle odometer values are not automatically reversed.'}

@app.post('/api/v1/mobile/trips/{trip_id}/finish')
def finish_mobile_trip(trip_id:int,payload:OfflineTripFinish | None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id: raise HTTPException(404,'Trip not found')
    if trip.status=='completed': return {'trip_id':trip.id,'status':'completed','distance_km':trip.distance_km}
    if trip.status!='active': raise HTTPException(409,'Trip cannot be completed')
    # Lock the vehicle to serialize mileage updates from overlapping trip completions.
    vehicle=db.scalar(select(Vehicle).where(Vehicle.id==trip.vehicle_id).with_for_update())
    if not vehicle: raise HTTPException(404,'Vehicle not found')
    trip.ended_at=_safe_device_time(payload.ended_at if payload else None)
    if trip.ended_at<trip.started_at: raise HTTPException(422,'Trip finish precedes trip start')
    trip.status='completed'
    added=max(0.0,trip.distance_km or 0.0)
    if vehicle.odometer_km is not None and added>0:
        vehicle.odometer_km+=added
        db.add(OdometerReading(company_id=vehicle.company_id,vehicle_id=vehicle.id,reading_km=vehicle.odometer_km,source='GPS_TRIP',note=f'Completed trip #{trip.id}: +{added:.3f} km'))
    db.commit()
    return {'trip_id':trip.id,'status':'completed','distance_km':added,'vehicle_odometer_km':vehicle.odometer_km}

def period_start(period):
    now=datetime.now(timezone.utc)
    if period=='daily': return now-timedelta(days=1)
    if period=='weekly': return now-timedelta(days=7)
    if period=='monthly': return now-timedelta(days=30)
    if period=='yearly': return now-timedelta(days=365)
    raise HTTPException(422,'period must be daily, weekly, monthly or yearly')

@app.get('/api/v1/fleet/trips/{trip_id}/route')
def fleet_trip_route(trip_id:int, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff','driver')
    trip=db.get(Trip,trip_id)
    if not trip: raise HTTPException(404,'Trip not found')
    scope(user,trip.company_id)
    if user.role=='driver' and own_driver(db,user).id!=trip.driver_id:
        raise HTTPException(403,'Own trips only')
    points=list(db.scalars(select(DriverLocation).where(DriverLocation.trip_id==trip.id).order_by(DriverLocation.recorded_at,DriverLocation.id).limit(10001)).all())
    truncated=len(points)>10000
    points=points[:10000]
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id).order_by(DrivingEvent.recorded_at)).all())
    def point(p):
        return {'latitude':p.latitude,'longitude':p.longitude,'recorded_at':p.recorded_at.isoformat(),'speed_kmh':p.speed_kmh,'accuracy_m':p.accuracy_m}
    valid=[p for p in points if p.speed_kmh is not None and 0<=p.speed_kmh<=350 and p.accuracy_m is not None and p.accuracy_m<=100]
    return {'trip_id':trip.id,'status':trip.status,'started_at':trip.started_at.isoformat(),
            'ended_at':trip.ended_at.isoformat() if trip.ended_at else None,
            'distance_km':trip.distance_km,'max_speed_kmh':max((p.speed_kmh for p in valid),default=None),
            'points':[point(p) for p in points],'start':point(points[0]) if points else None,
            'end':point(points[-1]) if points else None,'truncated':truncated,
            'violations':[{'id':e.id,'type':e.event_type,'value':e.value,'latitude':e.latitude,
                           'longitude':e.longitude,'recorded_at':e.recorded_at.isoformat()} for e in events]}

# Precise historical search uses server-side company authorization and UTC timestamps.
@app.get('/api/v1/fleet/trips/search')
def search_fleet_trips(start_at:datetime,end_at:datetime,company_id:int|None=None,driver_id:int|None=None,vehicle_id:int|None=None,limit:int=500,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff','driver')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None: raise HTTPException(422,'Select a company')
    scope(user,cid)
    if start_at.tzinfo is None or end_at.tzinfo is None:raise HTTPException(422,'Timezone offsets required')
    start_at=start_at.astimezone(timezone.utc);end_at=end_at.astimezone(timezone.utc)
    if end_at<=start_at or end_at-start_at>timedelta(days=366):raise HTTPException(422,'Select a positive interval of at most 366 days')
    if driver_id is not None:
        driver=db.get(Driver,driver_id)
        if not driver or driver.company_id!=cid:raise HTTPException(404,'Driver not found')
    if vehicle_id is not None:
        vehicle=db.get(Vehicle,vehicle_id)
        if not vehicle or vehicle.company_id!=cid:raise HTTPException(404,'Vehicle not found')
    if user.role=='driver':
        own=own_driver(db,user)
        if driver_id is not None and driver_id!=own.id:raise HTTPException(403,'Own trips only')
        driver_id=own.id
    limit=max(1,min(limit,2000))
    query=select(Trip).where(Trip.company_id==cid,Trip.started_at>=start_at,Trip.started_at<=end_at)
    if driver_id is not None:query=query.where(Trip.driver_id==driver_id)
    if vehicle_id is not None:query=query.where(Trip.vehicle_id==vehicle_id)
    rows=list(db.scalars(query.order_by(Trip.started_at.asc(),Trip.id.asc()).limit(limit+1)).all())
    truncated=len(rows)>limit
    rows=rows[:limit]
    names={d.id:d.full_name for d in db.scalars(select(Driver).where(Driver.company_id==cid)).all()}
    # Historical event counts are scoped to the already-authorized trip IDs.
    # Do not infer violations from speed samples or from the report period.
    trip_ids=[t.id for t in rows]
    event_counts={}
    if trip_ids:
        for tid,count in db.execute(select(DrivingEvent.trip_id,func.count(DrivingEvent.id)).where(DrivingEvent.trip_id.in_(trip_ids)).group_by(DrivingEvent.trip_id)):
            event_counts[tid]=count
    return {'company_id':cid,'start_at':start_at.isoformat(),'end_at':end_at.isoformat(),'truncated':truncated,'trips':[{'id':t.id,'driver_id':t.driver_id,'driver_name':names.get(t.driver_id,'Unknown'),'vehicle_id':t.vehicle_id,'started_at':t.started_at.isoformat(),'ended_at':t.ended_at.isoformat() if t.ended_at else None,'status':t.status,'distance_km':t.distance_km,'event_count':event_counts.get(t.id,0)} for t in rows]}

@app.get('/api/v1/fleet/report')
def fleet_report(period:Literal['daily','weekly','monthly','yearly']='daily',company_id:int|None=None,driver_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff','driver')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None: raise HTTPException(422,'Select company')
    scope(user,cid)
    if user.role=='driver':
        d=own_driver(db,user)
        if driver_id is not None and driver_id!=d.id: raise HTTPException(403,'Own report only')
        driver_id=d.id
    if driver_id is not None:
        d=db.get(Driver,driver_id)
        if not d or d.company_id!=cid: raise HTTPException(404,'Driver not found in company')
    since=period_start(period)
    drivers=list(db.scalars(select(Driver).where(Driver.company_id==cid,*([Driver.id==driver_id] if driver_id else []))).all())
    output=[]
    for d in drivers:
        trips=list(db.scalars(select(Trip).where(Trip.company_id==cid,Trip.driver_id==d.id,Trip.started_at>=since).order_by(Trip.started_at.desc())).all())
        # Live counters include active-trip events. The official score continues
        # to use completed trips only, keeping provisional data out of the RAG.
        events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.driver_id==d.id,DrivingEvent.recorded_at>=since)).all())
        completed_trip_ids={t.id for t in trips if t.status=='completed'}
        official_events=[e for e in events if e.trip_id in completed_trip_ids]
        counts={k:sum(e.event_type==k or (k=='speeding' and e.event_type=='excessive_speeding') for e in events) for k in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')}
        km=sum(max(0,t.distance_km or 0) for t in trips if t.status=='completed')
        breakdown=calculate_safety_score(official_events,km,score_policy(db,cid),thresholds(db,cid).speeding_kmh,db=db,trips=[t for t in trips if t.status=='completed'],flexible_policy=flexible_rag_policy(db,cid))
        score=breakdown['score']
        loc=db.scalar(select(DriverLocation).where(DriverLocation.company_id==cid,DriverLocation.driver_id==d.id).order_by(DriverLocation.id.desc()).limit(1))
        output.append({'driver_id':d.id,'driver_name':d.full_name,'trips':len(trips),'score':score,'score_model':breakdown.get('score_model','legacy_100'),'risk':breakdown['risk'],'score_breakdown':breakdown,'violations':counts,'latest_location':{'latitude':loc.latitude,'longitude':loc.longitude,'recorded_at':loc.recorded_at.isoformat(),'accuracy_m':loc.accuracy_m} if loc else None,'trip_details':[{'id':t.id,'vehicle_id':t.vehicle_id,'started_at':t.started_at.isoformat(),'ended_at':t.ended_at.isoformat() if t.ended_at else None,'status':t.status,'distance_km':t.distance_km,'max_speed_kmh':db.scalar(select(func.max(DriverLocation.speed_kmh)).where(DriverLocation.trip_id==t.id,DriverLocation.accuracy_m<=100,DriverLocation.speed_kmh>=0,DriverLocation.speed_kmh<=350)),'violations':[{'type':e.event_type,'value':e.value,'recorded_at':e.recorded_at.isoformat()} for e in events if e.trip_id==t.id]} for t in trips]})
    scores=[x['score'] for x in output if x['score'] is not None]
    return {'company_id':cid,'period':period,'from':since.isoformat(),'driver_count':len(output),'trip_count':sum(x['trips'] for x in output),'average_score':round(sum(scores)/len(scores),2) if scores else None,'score_model':'flexible_rag' if flexible_rag_policy(db,cid)['enabled'] else 'legacy_100','drivers':output}
