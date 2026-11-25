"""Driver-app diagnostics ingestion and reading."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import Depends
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user
from ..db import engine, get_db
from ..models import User, Vehicle
from .shared import own_driver

# Location-free mobile diagnostic telemetry; authenticated and company scoped.

class MobileDiagnostic(BaseModel):
    event_id: str = Field(min_length=12,max_length=64,pattern=r'^[a-f0-9]{64}$')
    occurred_at: datetime
    severity: Literal['INFO','WARNING','ERROR','CRASH']
    category: Literal['GPS','TRIP','APP','SYNC','PERMISSION','OTHER']
    code: str = Field(min_length=2,max_length=100,pattern=r'^[A-Z0-9_]+$')
    detail: str = Field(default='',max_length=450)

class MobileDiagnosticBatch(BaseModel):
    events: list[MobileDiagnostic] = Field(max_length=100)

@app.post('/api/v1/mobile/diagnostics')
def ingest_mobile_diagnostics(payload:MobileDiagnosticBatch,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    count=0
    for event in payload.events:
        occurred=event.occurred_at if event.occurred_at.tzinfo else event.occurred_at.replace(tzinfo=timezone.utc)
        if not datetime.now(timezone.utc)-timedelta(days=14)<=occurred<=datetime.now(timezone.utc)+timedelta(minutes=5):continue
        result=db.execute(text("""INSERT INTO mobile_diagnostics
          (event_id,company_id,driver_id,vehicle_id,occurred_at,severity,category,code,detail)
          VALUES (:id,:cid,:did,:vid,:at,:severity,:category,:code,:detail)
          ON CONFLICT (event_id) DO NOTHING"""),dict(id=event.event_id,cid=driver.company_id,did=driver.id,
          vid=vehicle.id if vehicle else None,at=occurred,severity=event.severity,
          category=event.category,code=event.code,detail=event.detail))
        count+=result.rowcount
    db.commit()
    return {'accepted':count}

@app.get('/api/v1/maintenance/mobile-diagnostics')
def read_mobile_diagnostics(plate:str='',driver:str='',severity:str='',category:str='',limit:int=200,
                            db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','workshop_staff')
    filters=['1=1'];params={'limit':max(1,min(limit,500))}
    if user.role!='super_admin':filters.append('d.company_id=:company');params['company']=user.company_id
    if plate:filters.append('v.plate_number ILIKE :plate');params['plate']='%'+plate[:40]+'%'
    if driver:filters.append('dr.full_name ILIKE :driver');params['driver']='%'+driver[:80]+'%'
    if severity:filters.append('d.severity=:severity');params['severity']=severity[:12]
    if category:filters.append('d.category=:category');params['category']=category[:24]
    rows=db.execute(text("""SELECT d.event_id,d.occurred_at,d.received_at,d.severity,d.category,d.code,d.detail,
      dr.full_name AS driver_name,v.plate_number FROM mobile_diagnostics d
      LEFT JOIN drivers dr ON dr.id=d.driver_id LEFT JOIN vehicles v ON v.id=d.vehicle_id
      WHERE """+' AND '.join(filters)+' ORDER BY d.occurred_at DESC LIMIT :limit'),params).mappings().all()
    return [dict(row) for row in rows]
