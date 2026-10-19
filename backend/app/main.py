from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from .config import settings
from .db import Base, engine, get_db
from .models import Company, Driver, Vehicle, OdometerReading, Trip, MaintenanceSchedule, User
from .schemas import CompanyCreate, CompanyOut, DriverCreate, DriverOut, VehicleCreate, VehicleOut, OdometerCreate, OdometerOut, MaintenanceScheduleUpsert, MaintenanceScheduleOut

from .auth import current_user, hash_password, verify_password, encode_token, allow, scope
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError
import os
from .auth import secret
from .models import AppSetting, AccountInvitation
from datetime import datetime, timedelta, timezone
import secrets, hashlib, smtplib, ssl, json
from email.message import EmailMessage
secret()
Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="0.1.0", description="Nuqati fleet and driver performance API")

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "nuqati-api", "version": "0.1.0"}

class LoginIn(BaseModel):
    email: str
    password: str
class UserIn(BaseModel):
    email: str
    full_name: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    role: str
    company_id: int | None = None

def user_view(u):
    return {'id':u.id,'email':u.email,'full_name':u.full_name,'role':u.role,'company_id':u.company_id,'is_active':u.is_active}

@app.post('/api/v1/auth/login')
def login(payload:LoginIn, db:Session=Depends(get_db)):
    user=db.scalar(select(User).where(User.email==payload.email.strip().lower()))
    if not user or not user.is_active or not verify_password(payload.password,user.password_hash):
        raise HTTPException(401,'Invalid credentials')
    return {'access_token':encode_token(user),'token_type':'bearer','user':user_view(user)}

@app.get('/api/v1/auth/me')
def me(user:User=Depends(current_user)):
    return user_view(user)

@app.get('/api/v1/users')
def users(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    q=select(User).order_by(User.id)
    if user.role!='super_admin': q=q.where(User.company_id==user.company_id)
    return [user_view(x) for x in db.scalars(q)]

@app.post('/api/v1/users', status_code=201)
def add_user(payload:UserIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
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
    allow(user,'super_admin')
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

@app.get("/api/v1/drivers", response_model=list[DriverOut])
def list_drivers(db: Session = Depends(get_db), user:User=Depends(current_user)):
    q=select(Driver).order_by(Driver.full_name)
    if user.role!='super_admin': q=q.where(Driver.company_id==user.company_id)
    return list(db.scalars(q.limit(500)).all())

@app.post("/api/v1/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    scope(user,payload.company_id)
    if not db.get(Company, payload.company_id):
        raise HTTPException(404, "Company not found")
    if payload.assigned_driver_id:
        assigned=db.get(Driver,payload.assigned_driver_id)
        if not assigned or assigned.company_id!=payload.company_id: raise HTTPException(422,'Driver must belong to the vehicle company')
    if db.scalar(select(Vehicle).where(Vehicle.plate_number == payload.plate_number)):
        raise HTTPException(409, "Plate number already exists")
    row = Vehicle(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/vehicles", response_model=list[VehicleOut])
def list_vehicles(db: Session = Depends(get_db), user:User=Depends(current_user)):
    q=select(Vehicle).order_by(Vehicle.plate_number)
    if user.role!='super_admin': q=q.where(Vehicle.company_id==user.company_id)
    return list(db.scalars(q.limit(500)).all())

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
def list_odometer_readings(db: Session = Depends(get_db), user:User=Depends(current_user)):
    q=select(OdometerReading).order_by(OdometerReading.created_at.desc())
    if user.role!='super_admin': q=q.where(OdometerReading.company_id==user.company_id)
    return list(db.scalars(q.limit(500)).all())


SERVICE_TYPES = {"ENGINE_OIL", "SPARK_PLUGS", "TRANSMISSION_OIL"}


def maintenance_view(row: MaintenanceSchedule, vehicle: Vehicle) -> dict:
    due = row.last_service_km + row.interval_km
    current = vehicle.odometer_km
    remaining = None if current is None else due - current
    status = "UNKNOWN" if remaining is None else ("OVERDUE" if remaining <= 0 else ("DUE_SOON" if remaining <= row.warning_before_km else "OK"))
    return {"id": row.id, "company_id": row.company_id, "vehicle_id": row.vehicle_id,
            "service_type": row.service_type, "interval_km": row.interval_km,
            "last_service_km": row.last_service_km, "warning_before_km": row.warning_before_km,
            "next_due_km": due, "current_odometer_km": current,
            "remaining_km": remaining, "status": status}


@app.put("/api/v1/maintenance-schedules", response_model=MaintenanceScheduleOut)
def upsert_maintenance(payload: MaintenanceScheduleUpsert, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    scope(user,payload.company_id)
    if payload.service_type not in SERVICE_TYPES:
        raise HTTPException(422, "Unsupported service type")
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if not vehicle or vehicle.company_id != payload.company_id:
        raise HTTPException(404, "Vehicle not found for company")
    row = db.scalar(select(MaintenanceSchedule).where(
        MaintenanceSchedule.company_id == payload.company_id,
        MaintenanceSchedule.vehicle_id == payload.vehicle_id,
        MaintenanceSchedule.service_type == payload.service_type))
    if row is None:
        row = MaintenanceSchedule(**payload.model_dump())
        db.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    db.commit(); db.refresh(row)
    return maintenance_view(row, vehicle)


@app.get("/api/v1/maintenance-schedules", response_model=list[MaintenanceScheduleOut])
def list_maintenance(db: Session = Depends(get_db), user:User=Depends(current_user)):
    q=select(MaintenanceSchedule).order_by(MaintenanceSchedule.vehicle_id, MaintenanceSchedule.service_type)
    if user.role!='super_admin': q=q.where(MaintenanceSchedule.company_id==user.company_id)
    rows = db.scalars(q).all()
    return [maintenance_view(row, db.get(Vehicle, row.vehicle_id)) for row in rows]

class CompanyEdit(BaseModel):
    name: str = Field(min_length=2,max_length=160)
@app.patch('/api/v1/companies/{company_id}', response_model=CompanyOut)
def edit_company(company_id:int,payload:CompanyEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    row=db.get(Company,company_id)
    if not row: raise HTTPException(404,'Company not found')
    row.name=payload.name.strip();db.commit();db.refresh(row);return row
@app.delete('/api/v1/companies/{company_id}')
def delete_empty_company(company_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    row=db.get(Company,company_id)
    if not row: raise HTTPException(404,'Company not found')
    for model in (User,Driver,Vehicle,Trip,OdometerReading,MaintenanceSchedule):
        if db.scalar(select(func.count()).select_from(model).where(model.company_id==company_id)):
            raise HTTPException(409,'Company has related records. Deactivate users or archive records; deletion blocked.')
    db.delete(row);db.commit();return {'status':'deleted'}


# Phase 3: restricted management operations. Permanent deletion is Super Admin only.
class UserEdit(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    role: str | None = None
    is_active: bool | None = None
    company_id: int | None = None

@app.patch('/api/v1/users/{user_id}')
def edit_user(user_id:int,payload:UserEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'User not found')
    changes=payload.model_dump(exclude_unset=True)
    if 'role' in changes and changes['role'] not in {'super_admin','workshop_staff','company_admin','fleet_manager','representative','driver'}: raise HTTPException(422,'Invalid role')
    if target.id==user.id and (changes.get('is_active') is False or ('role' in changes and changes['role']!='super_admin')): raise HTTPException(409,'Cannot remove your own admin access')
    cid=changes.get('company_id',target.company_id); role=changes.get('role',target.role)
    if role=='super_admin':
        if cid is not None: raise HTTPException(422,'Super Admin cannot belong to a client company')
    elif cid is None or not db.get(Company,cid): raise HTTPException(422,'Valid company required')
    for k,v in changes.items(): setattr(target,k,v)
    db.commit();db.refresh(target);return user_view(target)

@app.delete('/api/v1/users/{user_id}')
def delete_user(user_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'User not found')
    if target.id==user.id: raise HTTPException(409,'Cannot delete your own account')
    db.delete(target);db.commit();return {'status':'deleted'}

class DriverEdit(BaseModel):
    full_name: str | None = Field(default=None,min_length=2,max_length=160)
    phone: str | None = Field(default=None,max_length=40)
    status: str | None = None

@app.patch('/api/v1/drivers/{driver_id}',response_model=DriverOut)
def edit_driver(driver_id:int,payload:DriverEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(Driver,driver_id)
    if not row: raise HTTPException(404,'Driver not found')
    changes=payload.model_dump(exclude_unset=True)
    if changes.get('status') not in (None,'active','inactive','archived'): raise HTTPException(422,'Invalid status')
    for k,v in changes.items(): setattr(row,k,v)
    db.commit();db.refresh(row);return row

@app.delete('/api/v1/drivers/{driver_id}')
def delete_driver(driver_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(Driver,driver_id)
    if not row: raise HTTPException(404,'Driver not found')
    if db.scalar(select(func.count()).select_from(Vehicle).where(Vehicle.assigned_driver_id==driver_id)) or db.scalar(select(func.count()).select_from(Trip).where(Trip.driver_id==driver_id)):
        raise HTTPException(409,'Driver has linked vehicles or trips. Unassign/archive instead.')
    db.delete(row);db.commit();return {'status':'deleted'}

class VehicleEdit(BaseModel):
    plate_number: str | None = Field(default=None,min_length=1,max_length=40)
    make_model: str | None = Field(default=None,max_length=120)
    year: int | None = None
    assigned_driver_id: int | None = None

@app.patch('/api/v1/vehicles/{vehicle_id}',response_model=VehicleOut)
def edit_vehicle(vehicle_id:int,payload:VehicleEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(Vehicle,vehicle_id)
    if not row: raise HTTPException(404,'Vehicle not found')
    changes=payload.model_dump(exclude_unset=True)
    if changes.get('assigned_driver_id') is not None:
        driver=db.get(Driver,changes['assigned_driver_id'])
        if not driver or driver.company_id!=row.company_id: raise HTTPException(422,'Driver must belong to vehicle company')
    for k,v in changes.items(): setattr(row,k,v)
    try: db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,'Plate number already exists')
    db.refresh(row);return row

@app.delete('/api/v1/vehicles/{vehicle_id}')
def delete_vehicle(vehicle_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(Vehicle,vehicle_id)
    if not row: raise HTTPException(404,'Vehicle not found')
    for model in (Trip,OdometerReading,MaintenanceSchedule):
        if db.scalar(select(func.count()).select_from(model).where(model.vehicle_id==vehicle_id)):
            raise HTTPException(409,'Vehicle has trip, odometer or maintenance history. Deletion blocked.')
    db.delete(row);db.commit();return {'status':'deleted'}

class OdometerCorrection(BaseModel):
    reading_km: float = Field(ge=0)
    reason: str = Field(min_length=5,max_length=500)

@app.post('/api/v1/vehicles/{vehicle_id}/odometer-correction')
def correct_odometer(vehicle_id:int,payload:OdometerCorrection,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');v=db.get(Vehicle,vehicle_id)
    if not v: raise HTTPException(404,'Vehicle not found')
    # Preserve the original odometer history. Record a new correction entry instead of rewriting history.
    db.add(OdometerReading(company_id=v.company_id,vehicle_id=v.id,reading_km=payload.reading_km,source='ADMIN_CORRECTION',note=payload.reason))
    v.odometer_km=payload.reading_km;db.commit();return {'status':'corrected','odometer_km':v.odometer_km}

@app.delete('/api/v1/maintenance-schedules/{schedule_id}')
def delete_maintenance(schedule_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(MaintenanceSchedule,schedule_id)
    if not row: raise HTTPException(404,'Schedule not found')
    db.delete(row);db.commit();return {'status':'deleted'}


# Phase 4 driver telemetry API. All queries are company scoped on the server.
from datetime import datetime, timezone, timedelta
from sqlalchemy import and_
from .models import DriverAccount, DrivingEvent, DriverLocation, CompanyDrivingSettings
from typing import Literal

class DriverCredentials(BaseModel):
    driver_id: int
    email: str
    full_name: str = Field(min_length=2)
    password: str = Field(min_length=12)

@app.post('/api/v1/driver-accounts', status_code=201)
def create_driver_account(data:DriverCredentials, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    d=db.get(Driver,data.driver_id)
    if not d: raise HTTPException(404,'Driver not found')
    if db.scalar(select(DriverAccount).where(DriverAccount.driver_id==d.id)): raise HTTPException(409,'Driver already has an account')
    u=User(email=data.email.strip().lower(),full_name=data.full_name,password_hash=hash_password(data.password),role='driver',company_id=d.company_id)
    db.add(u)
    try:
        db.flush(); db.add(DriverAccount(driver_id=d.id,user_id=u.id)); db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,'Email already exists')
    return {'driver_id':d.id,'user_id':u.id,'email':u.email}

def own_driver(db,user):
    allow(user,'driver')
    a=db.scalar(select(DriverAccount).where(DriverAccount.user_id==user.id))
    if not a: raise HTTPException(403,'No driver profile linked to this account')
    d=db.get(Driver,a.driver_id)
    if not d or d.company_id!=user.company_id or d.status!='active': raise HTTPException(403,'Driver disabled or invalid')
    return d

@app.get('/api/v1/mobile/me')
def mobile_me(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))
    return {'driver_id':d.id,'full_name':d.full_name,'company_id':d.company_id,'vehicle':{'id':v.id,'plate_number':v.plate_number,'make_model':v.make_model} if v else None}

class Thresholds(BaseModel):
    speeding_kmh: float = Field(ge=20,le=200)
    harsh_accel_ms2: float = Field(ge=1,le=10)
    harsh_brake_ms2: float = Field(ge=1,le=10)

def thresholds(db,cid):
    t=db.get(CompanyDrivingSettings,cid)
    return t or CompanyDrivingSettings(company_id=cid,speeding_kmh=100,harsh_accel_ms2=3,harsh_brake_ms2=3)

@app.get('/api/v1/fleet/settings')
def fleet_settings(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None: raise HTTPException(422,'Choose a company')
    scope(user,cid)
    t=thresholds(db,cid)
    return {'company_id':cid,'speeding_kmh':t.speeding_kmh,'harsh_accel_ms2':t.harsh_accel_ms2,'harsh_brake_ms2':t.harsh_brake_ms2}

@app.put('/api/v1/fleet/settings')
def save_fleet_settings(data:Thresholds,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid): raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    t=db.get(CompanyDrivingSettings,cid)
    if not t: t=CompanyDrivingSettings(company_id=cid);db.add(t)
    for k,v in data.model_dump().items(): setattr(t,k,v)
    db.commit()
    return {'company_id':cid,**data.model_dump()}

@app.post('/api/v1/mobile/trips/start', status_code=201)
def start_mobile_trip(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))
    if not v: raise HTTPException(409,'Assign a vehicle to this driver first')
    existing=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.status=='active'))
    if existing: raise HTTPException(409,'An active trip already exists')
    trip=Trip(company_id=d.company_id,driver_id=d.id,vehicle_id=v.id,status='active')
    db.add(trip);db.commit();db.refresh(trip)
    return {'trip_id':trip.id,'started_at':trip.started_at.isoformat()}

class Sample(BaseModel):
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    accuracy_m: float = Field(ge=0,le=10000)
    speed_kmh: float = Field(ge=0,le=350)
    acceleration_ms2: float = Field(ge=-30,le=30,default=0)

@app.post('/api/v1/mobile/trips/{trip_id}/sample')
def submit_sample(trip_id:int,data:Sample,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id or trip.company_id!=d.company_id or trip.status!='active': raise HTTPException(404,'Active trip not found')
    if data.accuracy_m>50: return {'accepted':False,'reason':'GPS accuracy worse than 50m'}
    now=datetime.now(timezone.utc)
    previous=db.scalar(select(DriverLocation).where(DriverLocation.trip_id==trip.id).order_by(DriverLocation.id.desc()).limit(1))
    if previous and (now-previous.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()<4: raise HTTPException(429,'Sample interval must be at least 4 seconds')
    row=DriverLocation(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,latitude=data.latitude,longitude=data.longitude,accuracy_m=data.accuracy_m,speed_kmh=data.speed_kmh,recorded_at=now)
    db.add(row)
    cfg=thresholds(db,d.company_id); kinds=[]
    if data.speed_kmh>cfg.speeding_kmh: kinds.append(('speeding',data.speed_kmh))
    if data.acceleration_ms2>=cfg.harsh_accel_ms2: kinds.append(('harsh_acceleration',data.acceleration_ms2))
    if data.acceleration_ms2<=-cfg.harsh_brake_ms2: kinds.append(('harsh_braking',abs(data.acceleration_ms2)))
    # One event per category per 30 seconds, to avoid counting every sample as a separate violation.
    for kind,value in kinds:
        latest=db.scalar(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id,DrivingEvent.event_type==kind).order_by(DrivingEvent.id.desc()).limit(1))
        if latest and (now-latest.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()<30: continue
        db.add(DrivingEvent(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,event_type=kind,value=value,latitude=data.latitude,longitude=data.longitude,recorded_at=now))
    db.commit();return {'accepted':True,'events': [x[0] for x in kinds]}

@app.post('/api/v1/mobile/trips/{trip_id}/finish')
def finish_mobile_trip(trip_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id or trip.status!='active': raise HTTPException(404,'Active trip not found')
    trip.ended_at=datetime.now(timezone.utc);trip.status='completed';db.commit()
    return {'trip_id':trip.id,'status':'completed'}

def period_start(period):
    now=datetime.now(timezone.utc)
    if period=='daily': return now-timedelta(days=1)
    if period=='weekly': return now-timedelta(days=7)
    if period=='monthly': return now-timedelta(days=30)
    if period=='yearly': return now-timedelta(days=365)
    raise HTTPException(422,'period must be daily, weekly, monthly or yearly')

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
        events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.driver_id==d.id,DrivingEvent.recorded_at>=since)).all())
        counts={k:sum(e.event_type==k for e in events) for k in ('speeding','harsh_braking','harsh_acceleration')}
        # Pilot scoring formula; tune/validate before commercial decisions.
        score=max(0,100-5*counts['speeding']-4*counts['harsh_braking']-4*counts['harsh_acceleration']) if trips else None
        loc=db.scalar(select(DriverLocation).where(DriverLocation.company_id==cid,DriverLocation.driver_id==d.id).order_by(DriverLocation.id.desc()).limit(1))
        output.append({'driver_id':d.id,'driver_name':d.full_name,'trips':len(trips),'score':score,'violations':counts,'latest_location':{'latitude':loc.latitude,'longitude':loc.longitude,'recorded_at':loc.recorded_at.isoformat(),'accuracy_m':loc.accuracy_m} if loc else None,'trip_details':[{'id':t.id,'vehicle_id':t.vehicle_id,'started_at':t.started_at.isoformat(),'ended_at':t.ended_at.isoformat() if t.ended_at else None,'status':t.status,'violations':[{'type':e.event_type,'value':e.value,'recorded_at':e.recorded_at.isoformat()} for e in events if e.trip_id==t.id]} for t in trips]})
    scores=[x['score'] for x in output if x['score'] is not None]
    return {'company_id':cid,'period':period,'from':since.isoformat(),'driver_count':len(output),'trip_count':sum(x['trips'] for x in output),'average_score':round(sum(scores)/len(scores),1) if scores else None,'drivers':output}


# Phase 5: Additive tables only. Existing user/company/fleet tables are untouched.
Base.metadata.create_all(bind=engine)

class InvitationIn(BaseModel):
    email: str
    full_name: str = Field(min_length=2, max_length=160)
    role: str
    company_id: int | None = None

def send_invitation_email(recipient: str, token: str):
    host=os.environ.get('NUQATI_SMTP_HOST','')
    username=os.environ.get('NUQATI_SMTP_USER','')
    password=os.environ.get('NUQATI_SMTP_PASSWORD','')
    if not host or not username or not password:
        raise HTTPException(503, 'Invitation email is not configured. Set SMTP environment variables in Coolify.')
    origin=os.environ.get('NUQATI_PUBLIC_ORIGIN','').rstrip('/')
    if not origin.startswith('https://'): raise HTTPException(503,'NUQATI_PUBLIC_ORIGIN must be HTTPS')
    msg=EmailMessage()
    msg['Subject']='Welcome to Nuqati by Al-Riadah Workshop | مرحباً بك في نقاطي'
    msg['From']=f'Nuqati by Al-Riadah Workshop <{os.environ.get("NUQATI_EMAIL_FROM", "noreply@al-riadah.sa")}>'
    msg['To']=recipient
    url=origin+'/?invite='+token
    msg.set_content('Welcome to Nuqati by Al-Riadah Workshop. Create your password within 24 hours: '+url+'\n\nمرحباً بك في نقاطي من ورشة حلول الريادة. أنشئ كلمة المرور خلال 24 ساعة: '+url+'\n\nIf you did not expect this invitation, ignore this email.')
    try:
        with smtplib.SMTP(host,int(os.environ.get('NUQATI_SMTP_PORT','587')),timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(username,password)
            smtp.send_message(msg)
    except (OSError,smtplib.SMTPException) as exc:
        raise HTTPException(502,'Email provider rejected the invitation; check SMTP settings') from exc

def issue_invitation(db:Session, target:User):
    token=secrets.token_urlsafe(32)
    row=AccountInvitation(user_id=target.id,token_hash=hashlib.sha256(token.encode()).hexdigest(),expires_at=datetime.now(timezone.utc)+timedelta(hours=24))
    # Send first: a failed SMTP call must not create an apparently successful invitation.
    send_invitation_email(target.email,token)
    for old in db.scalars(select(AccountInvitation).where(AccountInvitation.user_id==target.id,AccountInvitation.used_at.is_(None))):
        old.used_at=datetime.now(timezone.utc)
    db.add(row);db.commit()

@app.post('/api/v1/invitations',status_code=201)
def invite_user(payload:InvitationIn,db:Session=Depends(get_db),admin:User=Depends(current_user)):
    allow(admin,'super_admin')
    allowed={'company_admin','fleet_manager','representative','workshop_staff'}
    if payload.role not in allowed: raise HTTPException(422,'Invalid invitation role')
    cid=payload.company_id
    if payload.role=='workshop_staff': cid=None
    elif cid is None or not db.get(Company,cid): raise HTTPException(422,'Valid company required')
    email=payload.email.strip().lower()
    if db.scalar(select(User).where(User.email==email)): raise HTTPException(409,'Email already exists')
    # Pending users cannot log in before accepting the invitation.
    target=User(email=email,full_name=payload.full_name.strip(),role=payload.role,company_id=cid,password_hash=hash_password(secrets.token_urlsafe(40)),is_active=False)
    db.add(target);db.flush()
    try: issue_invitation(db,target)
    except Exception: db.rollback();raise
    return {'status':'sent','email':email}

@app.post('/api/v1/invitations/{user_id}/resend')
def resend_invitation(user_id:int,db:Session=Depends(get_db),admin:User=Depends(current_user)):
    allow(admin,'super_admin')
    target=db.get(User,user_id)
    if not target or target.is_active: raise HTTPException(409,'Only pending users can be reinvited')
    issue_invitation(db,target)
    return {'status':'sent'}

class AcceptInvitationIn(BaseModel):
    token: str = Field(min_length=30,max_length=200)
    password: str = Field(min_length=12,max_length=128)

@app.post('/api/v1/invitations/accept')
def accept_invitation(payload:AcceptInvitationIn,db:Session=Depends(get_db)):
    token_hash=hashlib.sha256(payload.token.encode()).hexdigest()
    row=db.scalar(select(AccountInvitation).where(AccountInvitation.token_hash==token_hash).with_for_update())
    now=datetime.now(timezone.utc)
    if not row or row.used_at or row.expires_at.replace(tzinfo=timezone.utc) <= now:
        raise HTTPException(400,'Invalid or expired invitation')
    target=db.get(User,row.user_id)
    if not target or target.is_active: raise HTTPException(400,'Invitation no longer valid')
    target.password_hash=hash_password(payload.password);target.is_active=True;row.used_at=now
    db.commit()
    return {'status':'activated'}

DEFAULT_LABELS={
 'overview':['Overview','نظرة عامة'],'companies':['Companies','الشركات'],'users':['Users & Access','المستخدمون والصلاحيات'],
 'vehicles':['Vehicles','السيارات'],'drivers':['Drivers','السائقون'],'odometer':['Odometer','قراءة العداد'],
 'maintenance':['Maintenance Alerts','تنبيهات الصيانة'],'reports':['Fleet Reports','تقارير الأسطول'],
 'refresh':['Refresh','تحديث'],'logout':['Log out','خروج'],'brand':['Nuqati by Al-Riadah Workshop','نقاطي من ورشة حلول الريادة لصيانة السيارات'],
 'save':['Save changes','حفظ التغييرات'],'settings':['Branding & Language','الهوية واللغة']}

@app.get('/api/v1/public/branding')
def public_branding(db:Session=Depends(get_db)):
    row=db.get(AppSetting,'branding')
    return json.loads(row.value) if row else {'logo_data':'','labels':{}}

class BrandingIn(BaseModel):
    logo_data: str = Field(default='',max_length=300000)
    labels: dict[str,dict[str,str]] = Field(default_factory=dict)

@app.put('/api/v1/admin/branding')
def update_branding(payload:BrandingIn,db:Session=Depends(get_db),admin:User=Depends(current_user)):
    allow(admin,'super_admin')
    if payload.logo_data and (not payload.logo_data.startswith(('data:image/png;base64,','data:image/jpeg;base64,','data:image/webp;base64,')) or len(payload.logo_data)>300000):
        raise HTTPException(422,'Use a PNG, JPEG or WebP logo smaller than 220 KB')
    if len(payload.labels)>100: raise HTTPException(422,'Too many labels')
    cleaned={}
    for key,translations in payload.labels.items():
        if key not in DEFAULT_LABELS: raise HTTPException(422,'Unknown label key: '+key)
        cleaned[key]={lang:value.strip() for lang,value in translations.items() if lang in ('en','ar') and isinstance(value,str) and 0<len(value.strip())<=120}
    data=json.dumps({'logo_data':payload.logo_data,'labels':cleaned},ensure_ascii=False)
    row=db.get(AppSetting,'branding')
    if row: row.value=data
    else: db.add(AppSetting(key='branding',value=data))
    db.commit();return {'status':'saved'}

@app.get('/api/v1/public/label-defaults')
def label_defaults():
    return {key:{'en':value[0],'ar':value[1]} for key,value in DEFAULT_LABELS.items()}
