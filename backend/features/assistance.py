"""Roadside/workshop assistance requests and contacts."""

import json
from datetime import date

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import engine, get_db
from ..models import AppSetting, User, Vehicle
from .shared import own_driver

# Workshop assistance: company-scoped ticketing and configurable workshop contacts.
with engine.begin() as _assist_connection:
    _assist_connection.execute(text("""CREATE TABLE IF NOT EXISTS workshop_assistance_requests (
      id BIGSERIAL PRIMARY KEY, company_id INTEGER NOT NULL, driver_id INTEGER NOT NULL,
      vehicle_id INTEGER, category VARCHAR(32) NOT NULL, description TEXT NOT NULL,
      latitude DOUBLE PRECISION, longitude DOUBLE PRECISION, location_accuracy_m DOUBLE PRECISION,
      status VARCHAR(32) NOT NULL DEFAULT 'new', resolution_note TEXT NOT NULL DEFAULT '',
      created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    )"""))

ASSISTANCE_TYPES={'manager','mechanic','electrician','towing'}
class AssistanceCreate(BaseModel):
    category: str
    description: str = Field(min_length=3,max_length=2000)
    latitude: float | None = Field(default=None,ge=-90,le=90)
    longitude: float | None = Field(default=None,ge=-180,le=180)
    location_accuracy_m: float | None = Field(default=None,ge=0,le=100000)

class AssistanceUpdate(BaseModel):
    status: str
    resolution_note: str = Field(default='',max_length=2000)

class AssistanceContacts(BaseModel):
    manager: str = Field(default='',max_length=24)
    mechanic: str = Field(default='',max_length=24)
    electrician: str = Field(default='',max_length=24)
    towing: str = Field(default='',max_length=24)

def assistance_contacts(db):
    setting=db.get(AppSetting,'workshop_assistance_phones')
    try: saved=json.loads(setting.value) if setting else {}
    except (TypeError,ValueError): saved={}
    return {key:str(saved.get(key,'')).strip() for key in ASSISTANCE_TYPES}

@app.get('/api/v1/mobile/assistance/contacts')
def get_assistance_contacts(db:Session=Depends(get_db),user:User=Depends(current_user)):
    own_driver(db,user)
    return assistance_contacts(db)

@app.get('/api/v1/workshop/assistance/contacts')
def workshop_get_contacts(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','workshop_staff','company_admin','fleet_manager','representative')
    return assistance_contacts(db)

@app.put('/api/v1/workshop/assistance/contacts')
def workshop_save_contacts(payload:AssistanceContacts,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    data=payload.model_dump()
    import re
    for value in data.values():
        if value and not re.fullmatch(r'\+?[0-9 ()-]{7,24}',value):raise HTTPException(422,'Use a valid phone number')
    setting=db.get(AppSetting,'workshop_assistance_phones')
    if setting: setting.value=json.dumps(data)
    else: db.add(AppSetting(key='workshop_assistance_phones',value=json.dumps(data)))
    db.commit()
    return data

@app.post('/api/v1/mobile/assistance/requests')
def create_assistance(payload:AssistanceCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    if payload.category not in ASSISTANCE_TYPES:raise HTTPException(422,'Unsupported assistance category')
    if (payload.latitude is None)!=(payload.longitude is None):raise HTTPException(422,'Coordinates must be provided together')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    row=db.execute(text("""INSERT INTO workshop_assistance_requests
      (company_id,driver_id,vehicle_id,category,description,latitude,longitude,location_accuracy_m)
      VALUES (:cid,:did,:vid,:cat,:descr,:lat,:lon,:acc) RETURNING id"""),
      {'cid':driver.company_id,'did':driver.id,'vid':vehicle.id if vehicle else None,
       'cat':payload.category,'descr':payload.description,'lat':payload.latitude,
       'lon':payload.longitude,'acc':payload.location_accuracy_m}).scalar_one()
    db.commit()
    return {'id':row,'status':'new','delivered':True}

@app.get('/api/v1/mobile/assistance/requests')
def own_assistance_requests(db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    return [dict(v) for v in db.execute(text("""SELECT id,category,description,status,resolution_note,created_at
        FROM workshop_assistance_requests WHERE driver_id=:did AND company_id=:cid
        ORDER BY id DESC LIMIT 50"""),{'did':driver.id,'cid':driver.company_id}).mappings().all()]

@app.get('/api/v1/workshop/assistance/requests')
def workshop_assistance_requests(company_id:int|None=None,from_date:date|None=None,to_date:date|None=None,
                                 db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','workshop_staff','company_admin','fleet_manager','representative')
    # Preserve the existing company security scope. Dates are inclusive Saudi-local days.
    cid=company_id if user.role in ('super_admin','workshop_staff') else user.company_id
    if user.role not in ('super_admin','workshop_staff') and company_id is not None and company_id!=user.company_id:
        raise HTTPException(403,'Company access denied')
    if from_date and to_date and from_date>to_date:
        raise HTTPException(422,'From date must be on or before to date')
    predicates=[]
    args={}
    if cid is not None:
        predicates.append('a.company_id=:cid')
        args['cid']=cid
    if from_date is not None:
        predicates.append("(a.created_at AT TIME ZONE 'Asia/Riyadh')::date>=:from_date")
        args['from_date']=from_date
    if to_date is not None:
        predicates.append("(a.created_at AT TIME ZONE 'Asia/Riyadh')::date<=:to_date")
        args['to_date']=to_date
    where='WHERE '+' AND '.join(predicates) if predicates else ''
    return [dict(v) for v in db.execute(text(f"""SELECT a.*,d.full_name AS driver_name,v.plate_number
      FROM workshop_assistance_requests a LEFT JOIN drivers d ON d.id=a.driver_id
      LEFT JOIN vehicles v ON v.id=a.vehicle_id {where} ORDER BY a.id DESC LIMIT 500"""),args).mappings().all()]

@app.patch('/api/v1/workshop/assistance/requests/{request_id}')
def update_assistance_request(request_id:int,payload:AssistanceUpdate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','workshop_staff','company_admin','fleet_manager')
    if payload.status not in ('new','assigned','in_progress','awaiting_parts','at_workshop','resolved','cancelled'):
        raise HTTPException(422,'Unsupported status')
    company=db.execute(text('SELECT company_id FROM workshop_assistance_requests WHERE id=:id'),{'id':request_id}).scalar_one_or_none()
    if company is None:raise HTTPException(404,'Request not found')
    if user.role not in ('super_admin','workshop_staff'):scope(user,company)
    db.execute(text("""UPDATE workshop_assistance_requests SET status=:status,resolution_note=:note,
      updated_at=CURRENT_TIMESTAMP WHERE id=:id"""),{'id':request_id,'status':payload.status,
      'note':payload.resolution_note})
    db.commit()
    return {'id':request_id,'status':payload.status}
