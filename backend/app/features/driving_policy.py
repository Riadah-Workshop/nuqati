"""Geofence crossings, mobile driving policy and acknowledgements, event conditions."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import get_db
from ..models import (
    AppSetting,
    Company,
    CompanyEventCondition,
    Driver,
    DriverLocation,
    Trip,
    User,
    Vehicle,
)
from .fleet_settings import EVENT_KINDS, event_policy, severity_settings, thresholds
from .geofence_zones import _company_for_policy, _zone_contains, phase4_settings, phase4_zones
from .scoring import score_policy
from .shared import own_driver

# Driver-only, per-vehicle geofence policy for on-device coaching.
def _driver_geofence_rules(db, driver):
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    if vehicle is None:
        return []
    return [{'id':z['id'],'name':z['name'],'latitude':z['latitude'],'longitude':z['longitude'],
             'radius_m':z['radius_m'],'shape':z.get('shape','circle'),'polygon_points':z.get('polygon_points'),
             'mode':z.get('mode','normal'),'speed_limit_kmh':z.get('speed_limit_kmh')}
            for z in phase4_zones(db,driver.company_id)
            if z.get('vehicle_ids') is None or vehicle.id in z['vehicle_ids']]

@app.get('/api/v1/fleet/geofence-crossings')
def geofence_crossings(company_id:int|None=None,driver_id:int|None=None,zone_id:str|None=None,
                       start_at:datetime|None=None,end_at:datetime|None=None,limit:int=500,
                       db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=_company_for_policy(db,user,company_id)
    end=end_at or datetime.now(timezone.utc)
    start=start_at or end-timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None: raise HTTPException(422,'Use timezone-aware dates')
    if start>=end or end-start>timedelta(days=31):raise HTTPException(422,'Choose a valid range up to 31 days')
    if driver_id is not None and not db.scalar(select(Driver.id).where(Driver.company_id==cid,Driver.id==driver_id)):
        raise HTTPException(404,'Driver not found in company')
    zones=[z for z in phase4_zones(db,cid) if zone_id is None or z['id']==zone_id]
    if zone_id is not None and not zones:raise HTTPException(404,'Geofence not found')
    limit=max(1,min(limit,2000))
    # Reconstruct named crossings from persisted GPS samples. Do not infer crossings across GPS gaps.
    query=select(DriverLocation).where(DriverLocation.company_id==cid,DriverLocation.recorded_at>=start,
                    DriverLocation.recorded_at<=end,DriverLocation.accuracy_m>0,DriverLocation.accuracy_m<=25)
    if driver_id is not None:query=query.where(DriverLocation.driver_id==driver_id)
    samples=list(db.scalars(query.order_by(DriverLocation.driver_id,DriverLocation.trip_id,DriverLocation.recorded_at,DriverLocation.id).limit(60001)).all())
    truncated=len(samples)>60000
    if truncated:samples=samples[:60000]
    sample_trip_ids={x.trip_id for x in samples}
    trips={t.id:t for t in db.scalars(select(Trip).where(Trip.company_id==cid,Trip.id.in_(sample_trip_ids))).all()} if sample_trip_ids else {}
    driver_names={d.id:d.full_name for d in db.scalars(select(Driver).where(Driver.company_id==cid)).all()}
    plates={v.id:v.plate_number for v in db.scalars(select(Vehicle).where(Vehicle.company_id==cid)).all()}
    result=[];prev={}
    for point in samples:
        key=(point.driver_id,point.trip_id)
        before=prev.get(key);prev[key]=point
        if before is None:continue
        elapsed=(point.recorded_at-before.recorded_at).total_seconds()
        if elapsed<=0 or elapsed>120:continue
        trip=trips.get(point.trip_id)
        if trip is None:continue
        for z in zones:
            if z.get('vehicle_ids') is not None and trip.vehicle_id not in z['vehicle_ids']:continue
            was=_zone_contains(z,before.latitude,before.longitude)
            now=_zone_contains(z,point.latitude,point.longitude)
            if was==now:continue
            result.append({'event':'entry' if now else 'exit','zone_id':z['id'],'zone_name':z['name'],
                           'driver_id':point.driver_id,'driver_name':driver_names.get(point.driver_id,'—'),
                           'vehicle_id':trip.vehicle_id,'plate_number':plates.get(trip.vehicle_id,'—'),
                           'trip_id':point.trip_id,'time':point.recorded_at.isoformat(),
                           'speed_kmh':round(point.speed_kmh,1),'latitude':point.latitude,'longitude':point.longitude,
                           'speed_limit_kmh':z.get('speed_limit_kmh')})
    result.sort(key=lambda r:r['time'],reverse=True)
    return {'events':result[:limit],'truncated':truncated or len(result)>limit,'sample_count':len(samples),
            'start_at':start.isoformat(),'end_at':end.isoformat(),'reconstruction':True}

def driver_mobile_policy_payload(db: Session, driver: Driver):
    """One canonical per-driver hash for mobile delivery, ACK and fleet status.

    Company speed zones can differ by assigned vehicle, so there is no reliable
    single company-wide expected hash to compare every driver's receipt against.
    """
    t=thresholds(db,driver.company_id)
    payload={'company_id':driver.company_id,'speeding_kmh':t.speeding_kmh,'harsh_accel_ms2':t.harsh_accel_ms2,
            'harsh_brake_ms2':t.harsh_brake_ms2,'excessive_speed_margin_kmh':score_policy(db,driver.company_id)['excessive_speed_margin_kmh'],**severity_settings(db,driver.company_id),**event_policy(db,driver.company_id), 'phase4': phase4_settings(db,driver.company_id), 'geofence_speed_zones': _driver_geofence_rules(db,driver)}
    payload['policy_version']=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()[:20]
    return payload

@app.get('/api/v1/mobile/driving-policy')
def mobile_driving_policy(db:Session=Depends(get_db),user:User=Depends(current_user)):
    return driver_mobile_policy_payload(db,own_driver(db,user))

class MobilePolicyAckIn(BaseModel):
    policy_version: str = Field(min_length=20,max_length=20,pattern=r'^[0-9a-f]{20}$')

@app.post('/api/v1/mobile/driving-policy/ack')
def acknowledge_mobile_driving_policy(data:MobilePolicyAckIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    current=mobile_driving_policy(db,user)
    if data.policy_version!=current['policy_version']:
        raise HTTPException(409,'Policy has changed; refresh before acknowledging')
    key=f'driving_policy_ack:{driver.company_id}:{driver.id}'
    row=db.get(AppSetting,key)
    if row is None:
        row=AppSetting(key=key,value='{}');db.add(row)
    row.value=json.dumps({'version':data.policy_version,'received_at':datetime.now(timezone.utc).isoformat()})
    db.commit()
    return {'acknowledged':True,'policy_version':data.policy_version}

@app.get('/api/v1/fleet/driving-policy/ack')
def driving_policy_ack_status(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid):raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    rows=[]
    versions=set()
    for driver in db.scalars(select(Driver).where(Driver.company_id==cid)).all():
        expected_version=driver_mobile_policy_payload(db,driver)['policy_version']
        versions.add(expected_version)
        record=db.get(AppSetting,f'driving_policy_ack:{cid}:{driver.id}')
        try: ack=json.loads(record.value) if record else {}
        except (ValueError,TypeError):ack={}
        rows.append({'driver_id':driver.id,'driver_name':driver.full_name,
                     'policy_version':expected_version,
                     'acknowledged_version':ack.get('version'), 'received_at':ack.get('received_at'),
                     'status':'received' if ack.get('version')==expected_version else 'pending'})
    return {'company_id':cid,'policy_version':next(iter(versions)) if len(versions)==1 else None,'drivers':rows}



class EventConditionIn(BaseModel):
    max_gps_age_seconds: float = Field(ge=0.1, le=60)
    max_hdop: float | None = Field(default=None, gt=0, le=50)
    min_satellites: int | None = Field(default=None, ge=1, le=50)
    max_accuracy_m: float = Field(default=50, gt=0, le=500)
    gps_age_operator: str = '<'
    hdop_operator: str = '<'
    satellites_operator: str = '>'
    accuracy_operator: str = '<'

def gps_condition_operators(db, cid, kind):
    setting=db.get(AppSetting, f'gps_event_ops:{cid}:{kind}')
    try: values=json.loads(setting.value) if setting else {}
    except (ValueError, TypeError): values={}
    return {key:values.get(key,default) if values.get(key,default) in ('<','<=','>','>=','=') else default
            for key,default in [('gps_age_operator','<'),('hdop_operator','<'),('satellites_operator','>'),('accuracy_operator','<')]}

def gps_compare(value, operator, threshold):
    if value is None: return False
    return {'<':lambda:value<threshold, '<=':lambda:value<=threshold,
            '>':lambda:value>threshold, '>=':lambda:value>=threshold,
            '=':lambda:value==threshold}[operator]()

def event_condition_view(db, cid, kind):
    c = db.get(CompanyEventCondition, (cid, kind))
    return {'event_type': kind, **gps_condition_operators(db,cid,kind),
            'max_gps_age_seconds': c.max_gps_age_seconds if c else (10 if kind == 'speeding' else 2),
            'max_hdop': c.max_hdop if c else None,
            'min_satellites': c.min_satellites if c else None,
            'max_accuracy_m': c.max_accuracy_m if c else 50}

@app.get('/api/v1/fleet/event-conditions')
def get_event_conditions(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid): raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    return {'company_id':cid,'events':[event_condition_view(db,cid,k) for k in EVENT_KINDS]}

@app.put('/api/v1/fleet/event-conditions/{event_type}')
def put_event_condition(event_type:str,data:EventConditionIn,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    if event_type not in EVENT_KINDS: raise HTTPException(404,'Unknown event type')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid): raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    c=db.get(CompanyEventCondition,(cid,event_type))
    if not c: c=CompanyEventCondition(company_id=cid,event_type=event_type);db.add(c)
    for k,v in data.model_dump(exclude={'gps_age_operator','hdop_operator','satellites_operator','accuracy_operator'}).items(): setattr(c,k,v)
    key=f'gps_event_ops:{cid}:{event_type}'
    setting=db.get(AppSetting,key)
    if not setting:
        setting=AppSetting(key=key,value='{}');db.add(setting)
    setting.value=json.dumps({k:getattr(data,k) for k in ('gps_age_operator','hdop_operator','satellites_operator','accuracy_operator')})
    db.commit()
    return event_condition_view(db,cid,event_type)
