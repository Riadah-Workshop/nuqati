"""Per-company thresholds, severity settings and event policy."""

import json

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import get_db
from ..models import AppSetting, Company, CompanyDrivingSettings, User

class Thresholds(BaseModel):
    speeding_kmh: float = Field(ge=20,le=200)
    harsh_accel_ms2: float = Field(ge=1,le=10)
    harsh_brake_ms2: float = Field(ge=1,le=10)
    aggressive_brake_ms2: float | None = Field(default=None,ge=1,le=20)
    aggressive_accel_ms2: float | None = Field(default=None,ge=1,le=20)

def thresholds(db,cid):
    t=db.get(CompanyDrivingSettings,cid)
    return t or CompanyDrivingSettings(company_id=cid,speeding_kmh=100,harsh_accel_ms2=3,harsh_brake_ms2=3)

def severity_settings(db,cid):
    t=thresholds(db,cid)
    row=db.get(AppSetting,f'severity_policy:{cid}')
    try: saved=json.loads(row.value) if row else {}
    except (ValueError,TypeError):saved={}
    return {'aggressive_brake_ms2':saved.get('aggressive_brake_ms2',t.harsh_brake_ms2*1.5),
            'aggressive_accel_ms2':saved.get('aggressive_accel_ms2',t.harsh_accel_ms2*1.5)}

@app.get('/api/v1/fleet/settings')
def fleet_settings(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None: raise HTTPException(422,'Choose a company')
    scope(user,cid)
    t=thresholds(db,cid)
    return {'company_id':cid,'speeding_kmh':t.speeding_kmh,'harsh_accel_ms2':t.harsh_accel_ms2,'harsh_brake_ms2':t.harsh_brake_ms2,**severity_settings(db,cid)}

@app.put('/api/v1/fleet/settings')
def save_fleet_settings(data:Thresholds,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid): raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    t=db.get(CompanyDrivingSettings,cid)
    if not t: t=CompanyDrivingSettings(company_id=cid);db.add(t)
    for k in ('speeding_kmh','harsh_accel_ms2','harsh_brake_ms2'):setattr(t,k,getattr(data,k))
    severity={'aggressive_brake_ms2':data.aggressive_brake_ms2 or data.harsh_brake_ms2*1.5,'aggressive_accel_ms2':data.aggressive_accel_ms2 or data.harsh_accel_ms2*1.5}
    if severity['aggressive_brake_ms2']<=data.harsh_brake_ms2 or severity['aggressive_accel_ms2']<=data.harsh_accel_ms2:raise HTTPException(422,'Aggressive thresholds must exceed harsh thresholds')
    row=db.get(AppSetting,f'severity_policy:{cid}')
    if row:row.value=json.dumps(severity)
    else:db.add(AppSetting(key=f'severity_policy:{cid}',value=json.dumps(severity)))
    db.commit()
    return {'company_id':cid,**data.model_dump(),**severity}

EVENT_KINDS = ('speeding', 'excessive_speeding', 'harsh_acceleration', 'excessive_harsh_acceleration', 'harsh_braking', 'excessive_harsh_braking', 'harsh_cornering', 'geofence_entry', 'geofence_exit', 'geofence_restricted')

# Company-specific event switches are stored in existing AppSetting records (no migration).
def event_policy(db, cid):
    key=f'driving_event_policy:{cid}'
    setting=db.get(AppSetting,key)
    try: raw=json.loads(setting.value) if setting else {}
    except (ValueError,TypeError): raw={}
    return {'enabled':{kind:raw.get('enabled',{}).get(kind,True) is True for kind in EVENT_KINDS},
            'enforce_gps_conditions':raw.get('enforce_gps_conditions',True) is True}

class EventPolicyIn(BaseModel):
    enabled: dict[str,bool]
    enforce_gps_conditions: bool = True

@app.get('/api/v1/fleet/event-policy')
def get_event_policy(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid): raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    return {'company_id':cid,**event_policy(db,cid)}

@app.put('/api/v1/fleet/event-policy')
def put_event_policy(data:EventPolicyIn,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid): raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    if set(data.enabled)!=set(EVENT_KINDS): raise HTTPException(422,'Provide all event switches')
    key=f'driving_event_policy:{cid}'
    setting=db.get(AppSetting,key)
    if setting is None: setting=AppSetting(key=key,value='{}');db.add(setting)
    setting.value=json.dumps(data.model_dump());db.commit()
    return {'company_id':cid,**event_policy(db,cid)}
