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
    allow(user,'super_admin','company_admin')
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
    q=select(Company).order_by(Company.name)
    if user.role!='super_admin': q=q.where(Company.id==user.company_id)
    return list(db.scalars(q).all())

@app.post("/api/v1/drivers", response_model=DriverOut, status_code=201)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
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
    allow(user,'super_admin','company_admin','fleet_manager')
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
    allow(user,'super_admin','company_admin','fleet_manager')
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
    allow(user,'super_admin','company_admin','fleet_manager')
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
