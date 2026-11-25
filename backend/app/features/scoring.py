"""Safety Score v1, score policy, flexible RAG policy and reports, phase 4 risk."""

import json
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user
from ..db import get_db
from ..models import AppSetting, Driver, DriverLocation, DrivingEvent, Trip, User
from .fleet_settings import thresholds
from .geofence_zones import _company_for_policy, _setting_json
from .shared import own_driver

# Nuqati Safety Score v1: configurable per-company GPS-only scoring.
SCORE_CATEGORIES = ('harsh_acceleration','harsh_braking','harsh_cornering','speeding','excessive_speeding')
DEFAULT_SCORE_WEIGHTS = {'harsh_acceleration':20,'harsh_braking':20,'harsh_cornering':20,'speeding':25,'excessive_speeding':15}

class ScorePolicyIn(BaseModel):
    weights: dict[str,int]
    excessive_speed_margin_kmh: float = Field(default=20,ge=5,le=100)
    events_per_100km_full_penalty: float = Field(default=10,gt=0,le=100)
    minimum_distance_km: float = Field(default=20,ge=20,le=100)

def score_policy(db,cid):
    raw=_setting_json(db,f'safety_score_policy:{cid}',{})
    policy={'weights':DEFAULT_SCORE_WEIGHTS.copy(),'excessive_speed_margin_kmh':20.0,'events_per_100km_full_penalty':10.0,'minimum_distance_km':20.0}
    if isinstance(raw,dict):
        try:
            raw={**policy,**raw}
            raw['minimum_distance_km']=max(20.0,float(raw.get('minimum_distance_km',20)))
            return ScorePolicyIn(**raw).model_dump()
        except Exception: pass
    return policy

def validate_score_policy(policy):
    if set(policy.weights)!=set(SCORE_CATEGORIES) or any(type(v)!=int or v<0 or v>100 for v in policy.weights.values()) or sum(policy.weights.values())!=100:
        raise HTTPException(422,'Provide all five integer scoring weights totaling exactly 100')

# Flexible RAG scoring is opt-in per company. Existing 100-point policies remain intact.
# A lower Flexible RAG score is better; it is never converted into a 100-point score.
RAG_EVENT_TYPES = ('speeding','excessive_speeding','harsh_acceleration','harsh_braking','harsh_cornering',
                   'geofence_entry','geofence_exit','geofence_restricted')
DEFAULT_RAG_EVENTS = [
    {'kind':'speeding','score_on':'duration','weight':1.0,'amber_min':2.0,'amber_max':5.0},
    {'kind':'harsh_acceleration','score_on':'occurrence','weight':1.0,'amber_min':2.0,'amber_max':5.0},
    {'kind':'harsh_braking','score_on':'occurrence','weight':1.0,'amber_min':2.0,'amber_max':5.0},
]

class FlexibleRagEventIn(BaseModel):
    kind: str
    score_on: Literal['occurrence','duration','both']
    weight: float = Field(default=1.0,gt=0,le=100)
    amber_min: float = Field(default=2,ge=0,le=10000)
    amber_max: float = Field(default=5,ge=0,le=10000)

class FlexibleRagPolicyIn(BaseModel):
    enabled: bool = False
    events: list[FlexibleRagEventIn] = Field(default_factory=lambda:[FlexibleRagEventIn(**x) for x in DEFAULT_RAG_EVENTS],min_length=1,max_length=10)
    overall_amber_min: float = Field(default=2,ge=0,le=10000)
    overall_amber_max: float = Field(default=5,ge=0,le=10000)
    distance_unit_km: float = Field(default=100,gt=0,le=1000)
    minimum_distance_km: float = Field(default=20,ge=1,le=1000)
    # Default scoring sums the three standard categories; custom scoring uses
    # a weighted mean, matching this explicitly documented Nuqati model.
    aggregation: Literal['sum','weighted_average'] = 'sum'

def flexible_rag_policy(db,cid):
    raw=_setting_json(db,f'flexible_rag_policy:{cid}',{})
    try:
        return FlexibleRagPolicyIn(**raw).model_dump() if isinstance(raw,dict) else FlexibleRagPolicyIn().model_dump()
    except Exception:
        return FlexibleRagPolicyIn().model_dump()

def validate_flexible_rag_policy(data):
    kinds=[e.kind for e in data.events]
    if len(set(kinds))!=len(kinds) or not set(kinds).issubset(RAG_EVENT_TYPES):
        raise HTTPException(422,'Select unique, supported driving events (maximum 10)')
    if any(e.amber_max<e.amber_min for e in data.events) or data.overall_amber_max<data.overall_amber_min:
        raise HTTPException(422,'Amber maximum must be greater than or equal to minimum')
    # Presently only speeding has timestamped duration evidence (GPS speed samples).
    if any(e.score_on in ('duration','both') and e.kind!='speeding' for e in data.events):
        raise HTTPException(422,'Duration scoring currently requires speeding GPS data. Other events support occurrences only.')

@app.get('/api/v1/fleet/flexible-rag/policy')
def get_flexible_rag_policy(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    cid=_company_for_policy(db,user,company_id)
    return {'company_id':cid,**flexible_rag_policy(db,cid),'supported_events':list(RAG_EVENT_TYPES),
            'duration_supported_events':['speeding'],'lower_is_better':True}

@app.put('/api/v1/fleet/flexible-rag/policy')
def save_flexible_rag_policy(data:FlexibleRagPolicyIn,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    # Only company-scoped administrators can change the official scoring standard.
    allow(user,'super_admin','company_admin')
    cid=_company_for_policy(db,user,company_id)
    validate_flexible_rag_policy(data)
    key=f'flexible_rag_policy:{cid}'
    row=db.get(AppSetting,key)
    if row is None:row=AppSetting(key=key,value='{}');db.add(row)
    row.value=json.dumps(data.model_dump());db.commit()
    return {'company_id':cid,**data.model_dump(),'lower_is_better':True}

def _speeding_duration_seconds(db,trips,threshold_kmh):
    # Calculate from recorded GPS samples rather than inferring duration from event count.
    # Only consecutive, accurate over-limit fixes up to 10 seconds apart count;
    # longer missing intervals, invalid speeds and low-quality fixes are excluded.
    if db is None or not trips:return (0.0,0.0)
    ids=list({int(t.id) for t in trips})
    if not ids:return (0.0,0.0)
    points=db.execute(select(DriverLocation.trip_id,DriverLocation.recorded_at,DriverLocation.speed_kmh,DriverLocation.accuracy_m)
                      .where(DriverLocation.trip_id.in_(ids))
                      .order_by(DriverLocation.trip_id,DriverLocation.recorded_at)).all()
    total=0.0;covered=0.0;last=None
    for tid,at,speed,accuracy in points:
        valid=(at is not None and speed is not None and accuracy is not None and
               0<=float(speed)<=250 and float(accuracy)<=25)
        if last is not None and last[0]==tid and valid and last[3]:
            delta=(at-last[1]).total_seconds()
            if 0<delta<=10:
                covered+=delta
                if float(speed)>threshold_kmh and last[2]>threshold_kmh:
                    total+=delta
        last=(tid,at,float(speed or 0),valid)
    total_trip_seconds=sum(max(0,(t.ended_at-t.started_at).total_seconds()) for t in trips if t.ended_at and t.started_at)
    coverage=covered/total_trip_seconds if total_trip_seconds>0 else 0.0
    return (total,min(1.0,coverage))

def flexible_rag_score(events,distance_km,policy,speed_threshold_kmh,db=None,trips=None):
    distance_km=max(0.0,float(distance_km or 0))
    types={kind:0 for kind in RAG_EVENT_TYPES}
    for ev in events:
        if ev.event_type in types:types[ev.event_type]+=1
        if ev.event_type=='speeding' and float(ev.value or 0)>=speed_threshold_kmh+20:
            types['excessive_speeding']+=1
    if distance_km<policy['minimum_distance_km']:
        return {'score':None,'rag':None,'risk':'insufficient_data','score_model':'flexible_rag',
                'score_direction':'lower_is_better','distance_km':round(distance_km,2),
                'categories':types,'deductions':{},'reason':'insufficient_distance',
                'minimum_distance_km':policy['minimum_distance_km'],'event_breakdown':[]}
    needs_duration=any(e['kind']=='speeding' and e['score_on'] in ('duration','both') for e in policy['events'])
    duration,coverage=_speeding_duration_seconds(db,trips,speed_threshold_kmh) if needs_duration else (0.0,1.0)
    if needs_duration and coverage<0.5:
        return {'score':None,'rag':None,'risk':'insufficient_data','score_model':'flexible_rag',
                'score_direction':'lower_is_better','distance_km':round(distance_km,2),
                'categories':types,'deductions':{},'reason':'insufficient_gps_duration_coverage',
                'gps_coverage_pct':round(coverage*100,1),'event_breakdown':[]}
    rows=[]
    for e in policy['events']:
        count=types[e['kind']]
        occ=(count/distance_km)*policy['distance_unit_km']
        dur_s=duration if e['kind']=='speeding' else 0
        dur=((dur_s/10)/distance_km)*policy['distance_unit_km']
        metric=(occ if e['score_on'] in ('occurrence','both') else 0) + (dur if e['score_on'] in ('duration','both') else 0)
        rag='green' if metric<e['amber_min'] else 'red' if metric>e['amber_max'] else 'amber'
        rows.append({'event':e['kind'],'score_on':e['score_on'],'occurrences':count,
                     'duration_seconds':round(dur_s,1),'weight':e['weight'],
                     'score':round(metric,3),'rag':rag,'amber_min':e['amber_min'],'amber_max':e['amber_max']})
    if policy['aggregation']=='weighted_average':
        score=sum(r['score']*r['weight'] for r in rows)/sum(r['weight'] for r in rows)
    else:
        score=sum(r['score']*r['weight'] for r in rows)
    score=round(score,3)
    rag='green' if score<policy['overall_amber_min'] else 'red' if score>policy['overall_amber_max'] else 'amber'
    return {'score':score,'rag':rag,'risk':{'green':'low','amber':'medium','red':'high'}[rag],
            'score_model':'flexible_rag','score_direction':'lower_is_better',
            'distance_km':round(distance_km,2),'categories':types,'deductions':{},
            'event_breakdown':rows,'distance_unit_km':policy['distance_unit_km'],
            'aggregation':policy['aggregation'],'minimum_distance_km':policy['minimum_distance_km'],
            'overall_amber_min':policy['overall_amber_min'],'overall_amber_max':policy['overall_amber_max']}

def calculate_safety_score(events, distance_km, policy, speed_threshold_kmh, db=None, trips=None, flexible_policy=None):
    if flexible_policy is not None and flexible_policy.get('enabled'):
        return flexible_rag_score(events,distance_km,flexible_policy,speed_threshold_kmh,db=db,trips=trips)
    counts={k:0 for k in SCORE_CATEGORIES}
    for event in events:
        kind=event.event_type
        if kind=='speeding':
            try: excessive=float(event.value)>=speed_threshold_kmh+policy['excessive_speed_margin_kmh']
            except (TypeError,ValueError): excessive=False
            kind='excessive_speeding' if excessive else 'speeding'
        if kind in counts:counts[kind]+=1
    if distance_km<policy['minimum_distance_km']:
        return {'score':None,'risk':'insufficient_data','distance_km':round(distance_km,2),'categories':counts,'deductions':{},'reason':'insufficient_distance'}
    deductions={k:round(policy['weights'][k]*min(1.0,(count*100/distance_km)/policy['events_per_100km_full_penalty']),2) for k,count in counts.items()}
    score=max(0,round(100-sum(deductions.values())))
    risk='low' if score>=90 else 'mild' if score>=75 else 'medium' if score>=60 else 'high'
    return {'score':score,'risk':risk,'distance_km':round(distance_km,2),'categories':counts,'deductions':deductions}

@app.get('/api/v1/mobile/trips/recent-scores')
def mobile_recent_trip_scores(db:Session=Depends(get_db),user:User=Depends(current_user)):
    # Read-only projection of the SAME official scoring function used by fleet reports.
    d=own_driver(db,user)
    trips=list(db.scalars(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id,Trip.status=='completed').order_by(Trip.ended_at.desc(),Trip.id.desc()).limit(2)).all())
    policy=score_policy(db,d.company_id)
    speed_limit=thresholds(db,d.company_id).speeding_kmh
    output=[]
    for trip in trips:
        events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id)).all())
        result=calculate_safety_score(events,max(0.0,trip.distance_km or 0.0),policy,speed_limit,db=db,trips=[trip],flexible_policy=flexible_rag_policy(db,d.company_id))
        score=result['score']
        rag=None if score is None else (result.get('rag') or ('green' if score>=90 else 'amber' if score>=60 else 'red'))
        output.append({'trip_id':trip.id,'ended_at':trip.ended_at.isoformat() if trip.ended_at else None,
                       'score':score,'rag':rag,'score_model':result.get('score_model','legacy_100'),'score_direction':result.get('score_direction','higher_is_better'),'distance_km':result['distance_km'],
                       'categories':result['categories'],'deductions':result['deductions'],
                       'reason':result.get('reason')})
    return {'trips':output}

@app.get('/api/v1/fleet/safety-score/policy')
def get_score_policy(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    cid=_company_for_policy(db,user,company_id)
    return {'company_id':cid,**score_policy(db,cid)}

@app.put('/api/v1/fleet/safety-score/policy')
def save_score_policy(data:ScorePolicyIn,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=_company_for_policy(db,user,company_id)
    validate_score_policy(data)
    key=f'safety_score_policy:{cid}'; row=db.get(AppSetting,key)
    if row is None:row=AppSetting(key=key,value='{}');db.add(row)
    row.value=json.dumps(data.model_dump());db.commit()
    return {'company_id':cid,**data.model_dump()}

@app.get('/api/v1/fleet/flexible-rag/reports')
def flexible_rag_reports(view:Literal['daily','summary','ytd']='summary',
                         start_date:date|None=None,end_date:date|None=None,
                         year:int|None=None,driver_id:int|None=None,company_id:int|None=None,
                         db:Session=Depends(get_db),user:User=Depends(current_user)):
    cid=_company_for_policy(db,user,company_id)
    policy=flexible_rag_policy(db,cid)
    if not policy['enabled']:
        raise HTTPException(409,'Enable Flexible RAG scoring in Company Safety Configuration first')
    today=datetime.now(timezone.utc).date()
    y=year or today.year
    if not 2020<=y<=2100:raise HTTPException(422,'Invalid year')
    start=start_date or (date(y,1,1) if view=='ytd' else today-timedelta(days=29))
    finish=end_date or (min(today,date(y,12,31)) if view=='ytd' else today)
    if finish<start or (finish-start).days>731:
        raise HTTPException(422,'Date range must be chronological and at most two years')
    drivers=list(db.scalars(select(Driver).where(Driver.company_id==cid,*([Driver.id==driver_id] if driver_id is not None else [])).order_by(Driver.full_name)).all())
    if driver_id is not None and not drivers:raise HTTPException(404,'Driver not found in company')
    from_dt=datetime.combine(start,datetime.min.time(),tzinfo=timezone.utc)
    to_dt=datetime.combine(finish+timedelta(days=1),datetime.min.time(),tzinfo=timezone.utc)
    trips=list(db.scalars(select(Trip).where(Trip.company_id==cid,Trip.status=='completed',Trip.started_at>=from_dt,Trip.started_at<to_dt,*([Trip.driver_id==driver_id] if driver_id is not None else []))).all())
    trip_ids=[t.id for t in trips]
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.trip_id.in_(trip_ids))).all()) if trip_ids else []
    grouped={}
    for t in trips:
        if view=='daily':key=t.started_at.date().isoformat()
        elif view=='ytd':key=t.started_at.strftime('%Y-%m')
        else:key='summary'
        grouped.setdefault((t.driver_id,key),[]).append(t)
    output=[];speed_limit=thresholds(db,cid).speeding_kmh
    for driver in drivers:
        keys=sorted(key for did,key in grouped if did==driver.id)
        if view=='summary' and not keys:keys=['summary']
        for key in keys:
            ts=grouped.get((driver.id,key),[])
            ids={t.id for t in ts}
            ev=[e for e in events if e.trip_id in ids]
            km=sum(max(0.0,t.distance_km or 0) for t in ts)
            result=flexible_rag_score(ev,km,policy,speed_limit,db=db,trips=ts)
            output.append({'driver_id':driver.id,'driver_name':driver.full_name,'period':key,
                           'trips':len(ts),'distance_km':round(km,2),'score':result['score'],
                           'rag':result['rag'],'event_breakdown':result['event_breakdown'],
                           'reason':result.get('reason')})
    return {'company_id':cid,'view':view,'start':start.isoformat(),'end':finish.isoformat(),
            'lower_is_better':True,'score_model':'flexible_rag','policy':policy,'rows':output}

@app.get('/api/v1/fleet/phase4/risk')
def phase4_risk(period:str='weekly',company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    cid=_company_for_policy(db,user,company_id)
    if period not in ('daily','weekly','monthly'):raise HTTPException(422,'Invalid period')
    since=datetime.now(timezone.utc)-timedelta(days={'daily':1,'weekly':7,'monthly':30}[period])
    policy=score_policy(db,cid);output=[]
    speed_limit=thresholds(db,cid).speeding_kmh
    for driver in db.scalars(select(Driver).where(Driver.company_id==cid)).all():
        events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.driver_id==driver.id,DrivingEvent.recorded_at>=since,DrivingEvent.trip_id.in_(select(Trip.id).where(Trip.status=='completed')))).all())
        trips=list(db.scalars(select(Trip).where(Trip.company_id==cid,Trip.driver_id==driver.id,Trip.started_at>=since,Trip.status=='completed')).all())
        km=sum(max(0,t.distance_km or 0) for t in trips)
        result=calculate_safety_score(events,km,policy,speed_limit,db=db,trips=trips,flexible_policy=flexible_rag_policy(db,cid))
        score=result['score'];risk=result['risk']
        output.append({'driver_id':driver.id,'driver_name':driver.full_name,'distance_km':round(km,2),'score':score,'score_model':result.get('score_model','legacy_100'),'risk':risk,'event_count':len(events),'score_breakdown':result})
    return {'company_id':cid,'period':period,'drivers':output}
