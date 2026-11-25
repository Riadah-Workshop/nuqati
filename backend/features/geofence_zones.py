"""Geofence zones (phase 4 settings) and the geometry helpers that evaluate them."""

import json
import math
import secrets
from datetime import timezone
from typing import Literal

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import get_db
from ..models import AppSetting, Company, DriverLocation, User, Vehicle

# Phase 4: circular, rectangular and polygon geofences and risk policies. Stored per company in existing AppSetting.
# All rules are evaluated server-side on uploaded GPS samples, including delayed offline samples.
class GeoZoneIn(BaseModel):
    name: str = Field(min_length=1,max_length=80)
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    radius_m: float = Field(ge=50,le=20000)
    mode: str = Field(default='restricted',pattern='^(restricted|monitor)$')
    speed_limit_kmh: float | None = Field(default=None,ge=10,le=200)
    vehicle_ids: list[int] | None = None  # None = all vehicles in this company
    shape: Literal['circle','rectangle','polygon'] = 'circle'
    polygon_points: list[list[float]] | None = None  # [[latitude, longitude], ...]

    @model_validator(mode='after')
    def validate_geometry(self):
        if self.shape == 'circle':
            if self.polygon_points:
                raise ValueError('Circle cannot have polygon points')
            self.polygon_points = None
            return self
        points = self.polygon_points or []
        if len(points) < (4 if self.shape == 'rectangle' else 3) or len(points) > 60:
            raise ValueError('Provide 3–60 polygon corners, or 4 rectangle corners')
        if self.shape == 'rectangle' and len(points) != 4:
            raise ValueError('Rectangle requires four corners')
        if any(len(p) != 2 or any(not math.isfinite(v) for v in p) or abs(p[0]) > 90 or abs(p[1]) > 180 for p in points):
            raise ValueError('Invalid latitude/longitude vertices')
        if any(points[i] == points[(i + 1) % len(points)] for i in range(len(points))):
            raise ValueError('Duplicate consecutive vertices')
        # Reject zero-area and self-intersecting boundaries before storing policy.
        xy=[(p[1],p[0]) for p in points]
        area=abs(sum(xy[i][0]*xy[(i+1)%len(xy)][1]-xy[(i+1)%len(xy)][0]*xy[i][1] for i in range(len(xy))))
        if area < 1e-10:
            raise ValueError('Geofence polygon is too small or has no area')
        def crosses(a,b,c,d):
            def orient(u,v,w): return (v[0]-u[0])*(w[1]-u[1])-(v[1]-u[1])*(w[0]-u[0])
            return orient(a,b,c)*orient(a,b,d)<0 and orient(c,d,a)*orient(c,d,b)<0
        for i in range(len(xy)):
            for j in range(i+2,len(xy)):
                if i == 0 and j == len(xy)-1: continue
                if crosses(xy[i],xy[(i+1)%len(xy)],xy[j],xy[(j+1)%len(xy)]):
                    raise ValueError('Geofence polygon must not cross itself')
        return self

class ZoneVehiclesIn(BaseModel):
    vehicle_ids: list[int] | None = None

class Phase4SettingsIn(BaseModel):
    cornering_ms2: float = Field(default=3.5,ge=1.5,le=10)
    min_cornering_speed_kmh: float = Field(default=20,ge=5,le=100)
    risk_medium_below: int = Field(default=85,ge=1,le=100)
    risk_high_below: int = Field(default=70,ge=1,le=99)
    risk_critical_below: int = Field(default=50,ge=0,le=98)

def _setting_json(db,key,default):
    row=db.get(AppSetting,key)
    try: return json.loads(row.value) if row else default
    except (TypeError,ValueError): return default

def phase4_settings(db,cid):
    defaults=Phase4SettingsIn().model_dump()
    values=_setting_json(db,f'phase4_settings:{cid}',{})
    return {**defaults,**{k:v for k,v in values.items() if k in defaults}}

def phase4_zones(db,cid):
    return _setting_json(db,f'phase4_zones:{cid}',[])

def _company_for_policy(db,user,company_id):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid): raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    return cid

@app.get('/api/v1/fleet/phase4')
def get_phase4(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    cid=_company_for_policy(db,user,company_id)
    return {'company_id':cid,'settings':phase4_settings(db,cid),'zones':phase4_zones(db,cid)}

@app.put('/api/v1/fleet/phase4/settings')
def put_phase4_settings(data:Phase4SettingsIn,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=_company_for_policy(db,user,company_id)
    if not data.risk_critical_below<data.risk_high_below<data.risk_medium_below:
        raise HTTPException(422,'Risk thresholds must be strictly increasing')
    key=f'phase4_settings:{cid}';row=db.get(AppSetting,key)
    if row: row.value=data.model_dump_json()
    else: db.add(AppSetting(key=key,value=data.model_dump_json()))
    db.commit();return {'settings':phase4_settings(db,cid)}

@app.post('/api/v1/fleet/phase4/zones')
def add_phase4_zone(data:GeoZoneIn,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=_company_for_policy(db,user,company_id)
    zones=phase4_zones(db,cid)
    if len(zones)>=100: raise HTTPException(422,'Maximum 100 geofences per company')
    if data.vehicle_ids is not None:
        selected=set(data.vehicle_ids)
        if len(selected)!=len(data.vehicle_ids) or not selected or db.query(Vehicle.id).filter(Vehicle.company_id==cid,Vehicle.id.in_(selected)).count()!=len(selected):
            raise HTTPException(422,'Select valid company vehicles, or use all vehicles')
    zone={'id':secrets.token_hex(8),**data.model_dump()}
    zones.append(zone);key=f'phase4_zones:{cid}';row=db.get(AppSetting,key)
    if row:row.value=json.dumps(zones)
    else:db.add(AppSetting(key=key,value=json.dumps(zones)))
    db.commit();return zone

@app.put('/api/v1/fleet/phase4/zones/{zone_id}/vehicles')
def update_phase4_zone_vehicles(zone_id:str,data:ZoneVehiclesIn,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=_company_for_policy(db,user,company_id)
    selected=data.vehicle_ids
    if selected is not None:
        ids=set(selected)
        if not ids or len(ids)!=len(selected) or db.query(Vehicle.id).filter(Vehicle.company_id==cid,Vehicle.id.in_(ids)).count()!=len(ids):
            raise HTTPException(422,'Invalid vehicle selection')
    zones=phase4_zones(db,cid)
    zone=next((z for z in zones if z['id']==zone_id),None)
    if zone is None:raise HTTPException(404,'Geofence not found')
    zone['vehicle_ids']=selected
    db.get(AppSetting,f'phase4_zones:{cid}').value=json.dumps(zones)
    db.commit()
    return zone

@app.delete('/api/v1/fleet/phase4/zones/{zone_id}')
def delete_phase4_zone(zone_id:str,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=_company_for_policy(db,user,company_id);zones=phase4_zones(db,cid)
    remaining=[z for z in zones if z['id']!=zone_id]
    if len(remaining)==len(zones):raise HTTPException(404,'Geofence not found')
    db.get(AppSetting,f'phase4_zones:{cid}').value=json.dumps(remaining)
    db.commit();return {'deleted':True}

def _distance_m(lat1,lon1,lat2,lon2):
    a1,a2=math.radians(lat1),math.radians(lat2)
    h=math.sin((a2-a1)/2)**2+math.cos(a1)*math.cos(a2)*math.sin(math.radians(lon2-lon1)/2)**2
    return 12742000*math.asin(min(1.0,math.sqrt(max(0,h))))

def _zone_contains(zone, latitude, longitude):
    if zone.get('shape', 'circle') == 'circle':
        return _distance_m(latitude, longitude, zone['latitude'], zone['longitude']) <= zone['radius_m']
    points=zone.get('polygon_points') or []
    if len(points)<3:return False
    # Even/odd ray casting. Coordinates are (latitude, longitude), not GeoJSON order.
    inside=False
    j=len(points)-1
    for i, point in enumerate(points):
        yi,xi=point;yj,xj=points[j]
        if (yi>latitude)!=(yj>latitude):
            crossing=xi+(latitude-yi)*(xj-xi)/(yj-yi)
            if longitude<crossing:inside=not inside
        j=i
    return inside

def _zone_boundary_distance_m(zone, latitude, longitude):
    if zone.get('shape', 'circle') == 'circle':
        return abs(_distance_m(latitude,longitude,zone['latitude'],zone['longitude'])-zone['radius_m'])
    points=zone.get('polygon_points') or []
    if len(points)<3:return float('inf')
    # Equirectangular local projection is sufficiently accurate at GPS precision.
    scale_lon=111320*math.cos(math.radians(latitude));scale_lat=111195
    best=float('inf')
    for i,(a,b) in enumerate(points):
        c,d=points[(i+1)%len(points)]
        x1=(b-longitude)*scale_lon;y1=(a-latitude)*scale_lat
        x2=(d-longitude)*scale_lon;y2=(c-latitude)*scale_lat
        length=(x2-x1)**2+(y2-y1)**2
        t=max(0,min(1,-(x1*(x2-x1)+y1*(y2-y1))/length)) if length else 0
        best=min(best,math.hypot(x1+t*(x2-x1),y1+t*(y2-y1)))
    return best

def _heading_degrees(lat1,lon1,lat2,lon2):
    lat1,lat2=math.radians(lat1),math.radians(lat2);delta=math.radians(lon2-lon1)
    y=math.sin(delta)*math.cos(lat2)
    x=math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(delta)
    return (math.degrees(math.atan2(y,x))+360)%360

def phase4_candidates(db,trip,previous,data,captured):
    events=[];cfg=phase4_settings(db,trip.company_id)
    if data.accuracy_m>25:return events
    points=db.scalars(select(DriverLocation).where(DriverLocation.trip_id==trip.id).order_by(DriverLocation.id.desc()).limit(3)).all()
    # The current sample has been added to this Session; use only previous persisted points.
    if previous and len(points)>=3 and data.speed_kmh>=cfg['min_cornering_speed_kmh']:
        before=points[2];middle=previous
        dt=(captured-middle.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()
        dt0=(middle.recorded_at-before.recorded_at).total_seconds()
        if 1<=dt<=15 and 1<=dt0<=15 and before.accuracy_m<=25 and middle.accuracy_m<=25:
            if _distance_m(before.latitude,before.longitude,middle.latitude,middle.longitude)>=8 and _distance_m(middle.latitude,middle.longitude,data.latitude,data.longitude)>=8:
                h1=_heading_degrees(before.latitude,before.longitude,middle.latitude,middle.longitude)
                h2=_heading_degrees(middle.latitude,middle.longitude,data.latitude,data.longitude)
                change=abs((h2-h1+180)%360-180)
                lateral=(data.speed_kmh/3.6)*math.radians(change)/dt
                if lateral>=cfg['cornering_ms2']:events.append(('harsh_cornering',round(lateral,2)))
    if previous and previous.accuracy_m<=25:
        for zone in phase4_zones(db,trip.company_id):
            if zone.get('vehicle_ids') is not None and trip.vehicle_id not in zone['vehicle_ids']:
                continue
            prior=_zone_contains(zone,previous.latitude,previous.longitude)
            inside=_zone_contains(zone,data.latitude,data.longitude)
            if prior!=inside:events.append(('geofence_entry' if inside else 'geofence_exit',float(zone['radius_m'])))
            if inside and zone['mode']=='restricted':events.append(('geofence_restricted',float(zone['radius_m'])))
            if inside and zone.get('speed_limit_kmh') and data.speed_kmh>zone['speed_limit_kmh']:
                events.append(('speeding',data.speed_kmh))
    return events
