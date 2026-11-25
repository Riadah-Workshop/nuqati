"""Additive telematics linkage + isolated observations. Does not mutate Trips or odometers."""
from datetime import datetime, timezone
import re
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from .db import get_db, engine
from .auth import current_user, scope
from .models import User, Vehicle

router = APIRouter(prefix='/api/v1/hardware', tags=['GPS Hardware'])

# The tables telematics_devices and telematics_points are created by an Alembic revision (backend/app/migrations).

def _can_manage(user):
    if user.role not in ('super_admin','company_admin','fleet_manager'):
        raise HTTPException(403,'Hardware management permission required')

class DeviceLink(BaseModel):
    vehicle_id: int
    vendor: str = Field(pattern=r'^(teltonika|ruptela)$')
    model: str = Field(min_length=2,max_length=80)
    imei: str = Field(pattern=r'^\d{15}$')

@router.post('/devices')
def link_device(data: DeviceLink, user:User=Depends(current_user), db:Session=Depends(get_db)):
    _can_manage(user)
    vehicle=db.get(Vehicle,data.vehicle_id)
    if not vehicle:raise HTTPException(404,'Vehicle not found')
    scope(user,vehicle.company_id)
    if db.execute(text('SELECT 1 FROM telematics_devices WHERE imei=:imei'), {'imei':data.imei}).first():
        raise HTTPException(409,'IMEI already linked; contact administrator for reassignment')
    result=db.execute(text('''INSERT INTO telematics_devices(company_id,vehicle_id,vendor,model,imei)
        VALUES (:c,:v,:vendor,:model,:imei) RETURNING id'''),
        {'c':vehicle.company_id,'v':vehicle.id,'vendor':data.vendor,'model':data.model,'imei':data.imei})
    device_id=result.scalar_one();db.commit()
    return {'id':device_id,'vehicle_id':vehicle.id,'vendor':data.vendor,'imei':data.imei,'enabled':True,
            'receiver_status':'ready' if data.vendor=='teltonika' else 'pending_protocol_decoder'}

@router.get('/devices')
def list_devices(vehicle_id:int|None=None,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if user.role=='driver':raise HTTPException(403,'Dashboard account required')
    q='SELECT id,company_id,vehicle_id,vendor,model,imei,enabled,last_seen_at FROM telematics_devices WHERE 1=1'
    args={}
    if user.role!='super_admin':q+=' AND company_id=:c';args['c']=user.company_id
    if vehicle_id is not None:q+=' AND vehicle_id=:v';args['v']=vehicle_id
    q+=' ORDER BY id DESC'
    return [dict(r) for r in db.execute(text(q),args).mappings()]

@router.patch('/devices/{device_id}/enabled')
def set_device_status(device_id:int, enabled:bool,user:User=Depends(current_user),db:Session=Depends(get_db)):
    _can_manage(user)
    r=db.execute(text('SELECT company_id FROM telematics_devices WHERE id=:id'),{'id':device_id}).first()
    if not r:raise HTTPException(404,'Device not found')
    scope(user,r[0]);db.execute(text('UPDATE telematics_devices SET enabled=:enabled WHERE id=:id'),{'enabled':enabled,'id':device_id});db.commit()
    return {'id':device_id,'enabled':enabled}

@router.get('/vehicles/{vehicle_id}/latest')
def latest_point(vehicle_id:int,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if user.role=='driver':raise HTTPException(403,'Dashboard account required')
    vehicle=db.get(Vehicle,vehicle_id)
    if not vehicle:raise HTTPException(404,'Vehicle not found')
    scope(user,vehicle.company_id)
    row=db.execute(text('''SELECT recorded_at,latitude,longitude,speed_kmh,heading,satellites,ignition,
            vendor,model,imei FROM telematics_points p JOIN telematics_devices d ON d.id=p.device_id
            WHERE p.vehicle_id=:v ORDER BY recorded_at DESC,p.id DESC LIMIT 1'''),{'v':vehicle_id}).mappings().first()
    return {'vehicle_id':vehicle_id,'latest':dict(row) if row else None}

@router.get('/vehicles/{vehicle_id}/history')
def history(vehicle_id:int,limit:int=1000,user:User=Depends(current_user),db:Session=Depends(get_db)):
    if user.role=='driver':raise HTTPException(403,'Dashboard account required')
    vehicle=db.get(Vehicle,vehicle_id)
    if not vehicle:raise HTTPException(404,'Vehicle not found')
    scope(user,vehicle.company_id)
    limit=max(1,min(limit,2000))
    rows=db.execute(text('''SELECT p.recorded_at,p.latitude,p.longitude,p.speed_kmh,p.heading,p.satellites,p.ignition,d.vendor
        FROM telematics_points p JOIN telematics_devices d ON p.device_id=d.id
        WHERE p.vehicle_id=:v ORDER BY p.recorded_at DESC,p.id DESC LIMIT :lim'''),{'v':vehicle_id,'lim':limit}).mappings()
    return {'vehicle_id':vehicle_id,'points':[dict(r) for r in rows]}
