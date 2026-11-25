"""Users, companies, drivers, vehicles and odometer readings: create and list."""

import secrets
from datetime import datetime

from fastapi import Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, hash_password, scope
from ..db import get_db
from ..models import (
    Company,
    Driver,
    DriverAccount,
    DriverMetadata,
    MaintenanceSchedule,
    OdometerReading,
    Trip,
    User,
    Vehicle,
)
from ..schemas import (
    CompanyCreate,
    CompanyOut,
    DriverCreate,
    DriverOut,
    OdometerCreate,
    OdometerOut,
    VehicleCreate,
    VehicleOut,
)
from .auth_accounts import normalize_phone, user_view, UserIn

@app.get('/api/v1/users')
def users(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    q=select(User).order_by(User.id)
    if user.role!='super_admin': q=q.where(User.company_id==user.company_id)
    return [user_view(x) for x in db.scalars(q)]

@app.post('/api/v1/users', status_code=201)
def add_user(payload:UserIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    role=payload.role
    if role not in {'super_admin','company_admin','fleet_manager','representative','driver','workshop_staff'}: raise HTTPException(422,'Invalid role')
    if user.role=='company_admin' and role not in {'fleet_manager','representative','driver'}: raise HTTPException(403,'Cannot grant this role')
    company_id=payload.company_id if user.role=='super_admin' else user.company_id
    if role=='super_admin': company_id=None
    elif company_id is None or not db.get(Company,company_id): raise HTTPException(422,'Valid company required')
    if user.role!='super_admin': scope(user,company_id)
    row=User(email=payload.email.strip().lower(),full_name=payload.full_name.strip(),password_hash=hash_password(payload.password),role=role,company_id=company_id)
    db.add(row)
    try: db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,'Email already exists')
    db.refresh(row)
    return user_view(row)

@app.patch('/api/v1/users/{user_id}/deactivate')
def deactivate_user(user_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'User not found')
    if target.id==user.id: raise HTTPException(409,'Cannot deactivate yourself')
    if user.role!='super_admin':
        scope(user,target.company_id)
        if target.role in {'super_admin','company_admin','workshop_staff'}: raise HTTPException(403,'Cannot deactivate this role')
    target.is_active=False;db.commit();return {'status':'deactivated'}

@app.get("/api/v1/dashboard")
def dashboard(db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid = None if user.role=='super_admin' else user.company_id
    def count(model, extra=None):
        q=select(func.count()).select_from(model)
        if cid is not None: q=q.where(model.company_id==cid)
        if extra is not None: q=q.where(extra)
        return db.scalar(q) or 0
    return {'companies':count(Company) if cid is None else 1,'drivers':count(Driver),'vehicles':count(Vehicle),'trips_active':count(Trip,Trip.status=='active')}

@app.post("/api/v1/companies", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    row = Company(name=payload.name.strip())
    db.add(row); db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/companies", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    q=select(Company).order_by(Company.name)
    if user.role!='super_admin': q=q.where(Company.id==user.company_id)
    return list(db.scalars(q).all())

@app.post("/api/v1/drivers", response_model=DriverOut, status_code=201)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    scope(user,payload.company_id)
    if not db.get(Company, payload.company_id):
        raise HTTPException(404, "Company not found")
    row = Driver(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return row

# Single transaction: driver, login and vehicle assignment are created together.
class DriverOnboarding(BaseModel):
    company_id: int
    full_name: str = Field(min_length=2,max_length=160)
    phone: str = Field(min_length=8,max_length=40)
    id_number: str = Field(min_length=4,max_length=40)
    site_name: str = Field(min_length=2,max_length=160)
    vehicle_id: int | None = None
    initial_password: str = Field(min_length=12,max_length=128)

@app.post('/api/v1/drivers/onboard', status_code=201)
def onboard_driver(data:DriverOnboarding, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    scope(user,data.company_id)
    if not db.get(Company,data.company_id): raise HTTPException(404,'Company not found')
    phone=normalize_phone(data.phone)
    if not phone.startswith('+') or not phone[1:].isdigit() or not 9<=len(phone[1:])<=15: raise HTTPException(422,'Enter an international mobile number, e.g. +9665XXXXXXXX')
    if any(normalize_phone(d.phone)==phone for d in db.scalars(select(Driver).where(Driver.company_id==data.company_id))): raise HTTPException(409,'Phone number already registered in this company')
    duplicate_id=db.scalar(select(DriverMetadata.driver_id).join(Driver,Driver.id==DriverMetadata.driver_id)
        .where(Driver.company_id==data.company_id,DriverMetadata.id_number==data.id_number.strip()).limit(1))
    if duplicate_id is not None: raise HTTPException(409,'Iqama / ID already registered in this company')
    v=db.get(Vehicle,data.vehicle_id) if data.vehicle_id is not None else None
    if data.vehicle_id is not None:
        if not v or v.company_id!=data.company_id: raise HTTPException(422,'Choose a vehicle from the same company')
        if v.assigned_driver_id is not None: raise HTTPException(409,'Vehicle is already assigned to a driver')
        from ..vehicle_handover import enforce_managed_link
        enforce_managed_link(db,vehicle_id=v.id)
    # Internal unique identifier: drivers are never required to provide an email.
    email=f'driver-{secrets.token_hex(16)}@login.nuqati.invalid'
    d=Driver(company_id=data.company_id,full_name=data.full_name.strip(),phone=phone,status='active')
    u=User(company_id=data.company_id,full_name=data.full_name.strip(),email=email,role='driver',password_hash=hash_password(data.initial_password),is_active=True)
    try:
        db.add(d);db.add(u);db.flush()
        db.add(DriverAccount(driver_id=d.id,user_id=u.id))
        if v is not None: v.assigned_driver_id=d.id
        # ID and site are recorded separately in the driver metadata table.
        db.add(DriverMetadata(driver_id=d.id,id_number=data.id_number.strip(),site_name=data.site_name.strip()))
        db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,'Driver account could not be created; check existing assignments')
    return {'driver_id':d.id,'user_id':u.id,'vehicle_id':v.id if v else None,'phone':phone,'status':'ready'}

@app.get("/api/v1/drivers", response_model=list[DriverOut])
def list_drivers(response:Response,limit:int=500,offset:int=0,db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    q=select(Driver).order_by(Driver.full_name,Driver.id)
    if user.role!='super_admin': q=q.where(Driver.company_id==user.company_id)
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422,'Limit must be 1–500 and offset nonnegative')
    if response is not None:
        response.headers['X-Total-Count']=str(db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0)
        response.headers['X-Page-Limit']=str(limit)
    return list(db.scalars(q.limit(limit).offset(offset)).all())

@app.post("/api/v1/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    scope(user,payload.company_id)
    if not db.get(Company, payload.company_id):
        raise HTTPException(404, "Company not found")
    if payload.assigned_driver_id:
        assigned=db.get(Driver,payload.assigned_driver_id)
        if not assigned or assigned.company_id!=payload.company_id: raise HTTPException(422,'Driver must belong to the vehicle company')
    if db.scalar(select(Vehicle).where(Vehicle.plate_number == payload.plate_number)):
        raise HTTPException(409, "Plate number already exists")
    row = Vehicle(**payload.model_dump())
    db.add(row); db.flush()
    # Default tyre cycle starts at vehicle registration. A later tyre change can
    # reset the odometer baseline using the maintenance-schedule endpoint.
    db.add(MaintenanceSchedule(company_id=row.company_id, vehicle_id=row.id,
        service_type='TYRES', interval_km=60000,
        last_service_km=payload.odometer_km or 0, warning_before_km=1000))
    if payload.odometer_km is not None:
        db.add(OdometerReading(company_id=row.company_id, vehicle_id=row.id, reading_km=payload.odometer_km, source='MANUAL', note='Initial odometer at vehicle registration'))
    db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/vehicles", response_model=list[VehicleOut])
def list_vehicles(response:Response,limit:int=500,offset:int=0,db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    q=select(Vehicle).order_by(Vehicle.plate_number)
    if user.role!='super_admin': q=q.where(Vehicle.company_id==user.company_id)
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422,'Limit must be 1–500 and offset nonnegative')
    if response is not None:
        response.headers['X-Total-Count']=str(db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0)
        response.headers['X-Page-Limit']=str(limit)
    return list(db.scalars(q.limit(limit).offset(offset)).all())

@app.post("/api/v1/odometer-readings", response_model=OdometerOut, status_code=201)
def create_odometer(payload: OdometerCreate, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    scope(user,payload.company_id)
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if not vehicle or vehicle.company_id != payload.company_id:
        raise HTTPException(404, "Vehicle not found for this company")
    if vehicle.odometer_km is not None and payload.source == "MANUAL" and payload.reading_km < vehicle.odometer_km:
        raise HTTPException(422, "Reading cannot be lower than current stored reading without an audited correction")
    row = OdometerReading(**payload.model_dump())
    vehicle.odometer_km = payload.reading_km
    db.add(row); db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/odometer-readings", response_model=list[OdometerOut])
def list_odometer_readings(response:Response,vehicle_id: int | None = None, source: str | None = None,
                           from_time: datetime | None = None, to_time: datetime | None = None,
                           limit:int=500,offset:int=0,
                           db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    if from_time is not None and to_time is not None and from_time > to_time:
        raise HTTPException(422, "Start date/time must be before end date/time")
    q=select(OdometerReading).order_by(OdometerReading.created_at.desc(),OdometerReading.id.desc())
    if user.role!='super_admin': q=q.where(OdometerReading.company_id==user.company_id)
    if vehicle_id is not None: q=q.where(OdometerReading.vehicle_id==vehicle_id)
    if source is not None: q=q.where(OdometerReading.source==source)
    if from_time is not None: q=q.where(OdometerReading.created_at>=from_time)
    if to_time is not None: q=q.where(OdometerReading.created_at<=to_time)
    if not 1 <= limit <= 500 or offset < 0:
        raise HTTPException(422,'Limit must be 1–500 and offset nonnegative')
    if response is not None:
        response.headers['X-Total-Count']=str(db.scalar(select(func.count()).select_from(q.order_by(None).subquery())) or 0)
        response.headers['X-Page-Limit']=str(limit)
    return list(db.scalars(q.limit(limit).offset(offset)).all())
