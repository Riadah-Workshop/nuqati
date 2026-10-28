import math
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func, delete, text
from .config import settings
from .db import Base, engine, get_db
from .models import Company, Driver, Vehicle, OdometerReading, Trip, MaintenanceSchedule, User, DriverMetadata
from .schemas import CompanyCreate, CompanyOut, DriverCreate, DriverOut, VehicleCreate, VehicleOut, OdometerCreate, OdometerOut, MaintenanceScheduleUpsert, MaintenanceScheduleOut
from .auth import current_user, hash_password, verify_password, encode_token, allow, scope
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import os
from .auth import secret
from .models import AppSetting, AccountInvitation, DriverAccount, DrivingEvent, DriverLocation, CompanyDrivingSettings, CompanyEventCondition
from datetime import datetime, timedelta, timezone
import secrets, hashlib, smtplib, ssl, json
from email.message import EmailMessage
secret()
Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="0.1.0", description="Nuqati fleet and driver performance API")
from .whatsapp import router as whatsapp_router
app.include_router(whatsapp_router)

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

# Privacy evidence: append-only, idempotent, and intentionally location-free.
with engine.begin() as _privacy_conn:
    _privacy_conn.execute(text('''CREATE TABLE IF NOT EXISTS mobile_privacy_audit (
        event_id VARCHAR(90) PRIMARY KEY,
        company_id INTEGER NOT NULL,
        driver_id INTEGER NOT NULL,
        vehicle_id INTEGER,
        privacy_enabled BOOLEAN NOT NULL,
        selected_at TIMESTAMP WITH TIME ZONE NOT NULL,
        received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    )'''))

class PrivacyEvidence(BaseModel):
    event_id: str = Field(min_length=8, max_length=90, pattern=r'^[a-zA-Z0-9_-]+$')
    privacy_enabled: bool
    selected_at: datetime

@app.post('/api/v1/mobile/privacy-evidence')
def record_privacy_evidence(payload: PrivacyEvidence, db: Session=Depends(get_db), user: User=Depends(current_user)):
    driver=own_driver(db,user)
    selected=payload.selected_at
    if selected.tzinfo is None: selected=selected.replace(tzinfo=timezone.utc)
    selected=selected.astimezone(timezone.utc)
    if selected>datetime.now(timezone.utc)+timedelta(minutes=5) or selected<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid privacy selection timestamp')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    existing=db.execute(text('SELECT driver_id, privacy_enabled FROM mobile_privacy_audit WHERE event_id=:id'),{'id':payload.event_id}).first()
    if existing:
        if existing[0]!=driver.id or existing[1]!=payload.privacy_enabled:raise HTTPException(409,'Conflicting privacy event ID')
        return {'accepted':True,'duplicate':True}
    db.execute(text('''INSERT INTO mobile_privacy_audit
        (event_id,company_id,driver_id,vehicle_id,privacy_enabled,selected_at)
        VALUES (:id,:cid,:did,:vid,:enabled,:selected)'''),
        {'id':payload.event_id,'cid':driver.company_id,'did':driver.id,'vid':vehicle.id if vehicle else None,
         'enabled':payload.privacy_enabled,'selected':selected})
    db.commit()
    return {'accepted':True,'duplicate':False}

@app.get('/api/v1/privacy-audit')
def list_privacy_audit(limit:int=100,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    limit=max(1,min(limit,500))
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    args={'limit':limit} if user.role=='super_admin' else {'limit':limit,'cid':user.company_id}
    rows=db.execute(text(f'''SELECT event_id,company_id,driver_id,vehicle_id,privacy_enabled,selected_at,received_at
        FROM mobile_privacy_audit {where} ORDER BY received_at DESC LIMIT :limit'''),args).mappings().all()
    return [dict(row) for row in rows]

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

class DriverPhoneLogin(BaseModel):
    phone: str = Field(min_length=8,max_length=40)
    password: str

def normalize_phone(value:str)->str:
    p=''.join(c for c in value if c.isdigit() or c=='+')
    if p.startswith('00'):p='+'+p[2:]
    if p.startswith('05') and len(p)==10:p='+966'+p[1:]
    if p.startswith('966') and len(p)==12:p='+'+p
    return p

@app.post('/api/v1/auth/driver-phone-login')
def driver_phone_login(payload:DriverPhoneLogin,db:Session=Depends(get_db)):
    phone=normalize_phone(payload.phone)
    # Normalize legacy records in Python so existing drivers need no database migration.
    matches=[(d,u) for d,u in db.execute(select(Driver,User).join(DriverAccount,DriverAccount.driver_id==Driver.id).join(User,User.id==DriverAccount.user_id).where(User.role=='driver',User.is_active==True,Driver.status=='active')).all() if normalize_phone(d.phone)==phone]
    if len(matches)!=1 or not verify_password(payload.password,matches[0][1].password_hash):
        raise HTTPException(401,'Invalid phone or password; contact your fleet administrator')
    u=matches[0][1]
    return {'access_token':encode_token(u),'token_type':'bearer','user':user_view(u)}

class DriverIqamaLogin(BaseModel):
    iqama: str = Field(min_length=10, max_length=10)
    password: str

@app.post('/api/v1/auth/driver-iqama-login')
def driver_iqama_login(payload:DriverIqamaLogin,db:Session=Depends(get_db)):
    iqama=payload.iqama.strip()
    if not (len(iqama)==10 and iqama.isascii() and iqama.isdigit()): raise HTTPException(422,'Enter a 10-digit Iqama / ID number')
    matches=db.execute(select(Driver,User).join(DriverMetadata,DriverMetadata.driver_id==Driver.id).join(DriverAccount,DriverAccount.driver_id==Driver.id).join(User,User.id==DriverAccount.user_id).where(DriverMetadata.id_number==iqama,Driver.status=='active',User.role=='driver',User.is_active==True)).all()
    if len(matches)!=1 or not verify_password(payload.password,matches[0][1].password_hash): raise HTTPException(401,'Invalid Iqama or password')
    u=matches[0][1]
    return {'access_token':encode_token(u),'token_type':'bearer','user':user_view(u)}

@app.post('/api/v1/mobile/login-ack')
def driver_login_ack(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'driver')
    link=db.scalar(select(DriverAccount).where(DriverAccount.user_id==user.id))
    if not link: raise HTTPException(403,'Driver account not linked')
    d=db.get(Driver,link.driver_id)
    if not d or d.status!='active': raise HTTPException(403,'Driver inactive')
    timestamp=datetime.now(timezone.utc).isoformat()
    key=f'driver_login_ack:{d.id}'
    entry=db.get(AppSetting,key)
    if entry: entry.value=timestamp
    else: db.add(AppSetting(key=key,value=timestamp))
    db.commit()
    return {'status':'acknowledged','driver_id':d.id,'last_login_at':timestamp}

@app.get('/api/v1/drivers/login-acknowledgments')
def driver_login_acknowledgments(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    drivers=list(db.scalars(select(Driver).where(True if user.role=='super_admin' else Driver.company_id==user.company_id)).all())
    ids={d.id for d in drivers}
    rows=db.scalars(select(AppSetting).where(AppSetting.key.like('driver_login_ack:%'))).all()
    result={}
    for entry in rows:
        try: driver_id=int(entry.key.split(':')[-1])
        except ValueError: continue
        if driver_id in ids: result[str(driver_id)]=entry.value
    return {'last_logins':result}

@app.get('/api/v1/auth/me')
def me(user:User=Depends(current_user)):
    return user_view(user)

@app.get('/api/v1/users')
def users(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
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

# Single transaction: driver, login and vehicle assignment are created together.
class DriverOnboarding(BaseModel):
    company_id: int
    full_name: str = Field(min_length=2,max_length=160)
    phone: str = Field(min_length=8,max_length=40)
    id_number: str = Field(min_length=4,max_length=40)
    site_name: str = Field(min_length=2,max_length=160)
    vehicle_id: int
    initial_password: str = Field(min_length=12,max_length=128)

@app.post('/api/v1/drivers/onboard', status_code=201)
def onboard_driver(data:DriverOnboarding, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    scope(user,data.company_id)
    if not db.get(Company,data.company_id): raise HTTPException(404,'Company not found')
    phone=normalize_phone(data.phone)
    if not phone.startswith('+') or not phone[1:].isdigit() or not 9<=len(phone[1:])<=15: raise HTTPException(422,'Enter an international mobile number, e.g. +9665XXXXXXXX')
    if any(normalize_phone(d.phone)==phone for d in db.scalars(select(Driver).where(Driver.company_id==data.company_id))): raise HTTPException(409,'Phone number already registered in this company')
    v=db.get(Vehicle,data.vehicle_id)
    if not v or v.company_id!=data.company_id: raise HTTPException(422,'Choose a vehicle from the same company')
    if v.assigned_driver_id is not None: raise HTTPException(409,'Vehicle is already assigned to a driver')
    # Internal unique identifier: drivers are never required to provide an email.
    email=f'driver-{secrets.token_hex(16)}@login.nuqati.invalid'
    d=Driver(company_id=data.company_id,full_name=data.full_name.strip(),phone=phone,status='active')
    u=User(company_id=data.company_id,full_name=data.full_name.strip(),email=email,role='driver',password_hash=hash_password(data.initial_password),is_active=True)
    try:
        db.add(d);db.add(u);db.flush()
        db.add(DriverAccount(driver_id=d.id,user_id=u.id));v.assigned_driver_id=d.id
        # ID and site are recorded separately in the driver metadata table.
        db.add(DriverMetadata(driver_id=d.id,id_number=data.id_number.strip(),site_name=data.site_name.strip()))
        db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,'Driver account could not be created; check existing assignments')
    return {'driver_id':d.id,'user_id':u.id,'vehicle_id':v.id,'phone':phone,'status':'ready'}

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


SERVICE_TYPES = {"ENGINE_OIL", "SPARK_PLUGS", "TRANSMISSION_OIL", "TYRES"}


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


@app.get('/api/v1/mobile/maintenance-reminders')
def driver_maintenance_reminders(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))
    if not v or v.odometer_km is None:return {'vehicle_id':None,'reminders':[]}
    schedules=db.scalars(select(MaintenanceSchedule).where(MaintenanceSchedule.vehicle_id==v.id,MaintenanceSchedule.company_id==v.company_id)).all()
    out=[]
    for row in schedules:
        due=row.last_service_km+row.interval_km
        remaining=due-v.odometer_km
        stage=None
        if row.service_type=='ENGINE_OIL':
            if remaining<=0:stage='DUE'
            elif remaining<=500:stage='500_LEFT'
            elif remaining<=1000:stage='1000_LEFT'
        elif row.service_type in ('SPARK_PLUGS','TRANSMISSION_OIL'):
            if remaining<=-1000:stage='1000_OVERDUE'
            elif remaining<=0:stage='DUE'
            elif remaining<=1000:stage='1000_LEFT'
        if row.service_type=='TYRES':
            if remaining<=0:stage='DUE'
            elif remaining<=1000:stage='1000_LEFT'
            # The annual tyre reminder is measured from the date this schedule
            # was first registered/last updated, which is reset on tyre service.
            from datetime import datetime, timezone, timedelta
            registered=row.updated_at
            if registered is not None:
                if registered.tzinfo is None:registered=registered.replace(tzinfo=timezone.utc)
                days_left=(registered+timedelta(days=365)-datetime.now(timezone.utc)).days
                if days_left<=0:stage='DUE'
                elif days_left<=30 and stage is None:stage='30_DAYS_LEFT'
        if stage:out.append({'schedule_id':row.id,'service_type':row.service_type,'vehicle_id':v.id,'plate_number':v.plate_number,'due_km':due,'current_km':v.odometer_km,'remaining_km':remaining,'stage':stage,'cycle_key':f'{row.id}:{row.last_service_km}:{row.interval_km}:{row.updated_at.isoformat() if row.service_type=="TYRES" and row.updated_at else ""}'})
    return {'vehicle_id':v.id,'reminders':out}

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
# Destructive operations are scoped to a single company and committed atomically.
# Audit table is created at startup and survives deletion of company records.
from sqlalchemy import Table, Column, Integer, String, DateTime, JSON, MetaData
_delete_audit_metadata = MetaData()
company_delete_audit = Table('company_delete_audit', _delete_audit_metadata,
    Column('id', Integer, primary_key=True),
    Column('company_id', Integer, nullable=False),
    Column('company_name', String(160), nullable=False),
    Column('actor_user_id', Integer, nullable=False),
    Column('actor_email', String(255), nullable=False),
    Column('backup_reference', String(255), nullable=False),
    Column('deleted_counts', JSON, nullable=False),
    Column('deleted_at', DateTime(timezone=True), nullable=False))
_delete_audit_metadata.create_all(bind=engine)

COMPANY_DELETE_MODELS = (AccountInvitation, DriverAccount, DrivingEvent, DriverLocation,
                         Trip, OdometerReading, MaintenanceSchedule, CompanyDrivingSettings,
                         DriverMetadata, Vehicle, Driver, User)

def company_delete_counts(db: Session, company_id: int):
    user_ids = select(User.id).where(User.company_id == company_id)
    driver_ids = select(Driver.id).where(Driver.company_id == company_id)
    filters = {
        AccountInvitation: AccountInvitation.user_id.in_(user_ids),
        DriverAccount: (DriverAccount.driver_id.in_(driver_ids) | DriverAccount.user_id.in_(user_ids)),
        DriverMetadata: DriverMetadata.driver_id.in_(driver_ids),
    }
    return {model.__tablename__: db.scalar(select(func.count()).select_from(model).where(
        filters[model] if model in filters else model.company_id == company_id
    )) for model in COMPANY_DELETE_MODELS}

def purge_company_records(db: Session, company_id: int):
    user_ids = select(User.id).where(User.company_id == company_id)
    driver_ids = select(Driver.id).where(Driver.company_id == company_id)
    db.execute(delete(AccountInvitation).where(AccountInvitation.user_id.in_(user_ids)))
    db.execute(delete(DriverAccount).where((DriverAccount.driver_id.in_(driver_ids)) | (DriverAccount.user_id.in_(user_ids))))
    for model in (DrivingEvent, DriverLocation, Trip, OdometerReading, MaintenanceSchedule, CompanyDrivingSettings):
        db.execute(delete(model).where(model.company_id == company_id))
    db.execute(delete(DriverMetadata).where(DriverMetadata.driver_id.in_(driver_ids)))
    # Vehicle assignment references drivers; vehicles must be deleted before drivers.
    db.execute(delete(Vehicle).where(Vehicle.company_id == company_id))
    db.execute(delete(Driver).where(Driver.company_id == company_id))
    db.execute(delete(User).where(User.company_id == company_id))

@app.get('/api/v1/companies/{company_id}/deletion-preview')
def company_deletion_preview(company_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    row=db.get(Company,company_id)
    if not row: raise HTTPException(404,'Company not found')
    return {'company_id':row.id,'company_name':row.name,'counts':company_delete_counts(db,company_id),
            'requires_backup':os.environ.get('NUQATI_STAGING_ALLOW_DELETE_WITHOUT_BACKUP','').lower() not in ('true','1'),'requires_exact_name':True,'requires_delete_word':True}

class ConfirmCompanyDelete(BaseModel):
    confirm_name: str
    confirm_word: str
    backup_reference: str | None = Field(default=None,max_length=255)

@app.post('/api/v1/companies/{company_id}/permanent-delete')
def permanently_delete_company(company_id:int,data:ConfirmCompanyDelete,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    # Backup bypass is OFF by default and must be explicitly enabled for staging.
    staging_bypass = os.environ.get('NUQATI_STAGING_ALLOW_DELETE_WITHOUT_BACKUP','').lower() in ('true','1')
    approved_backup = os.environ.get('NUQATI_VERIFIED_BACKUP_REFERENCE','').strip()
    if not staging_bypass and (not approved_backup or (data.backup_reference or '').strip() != approved_backup):
        raise HTTPException(412,'A verified backup reference must be configured in Coolify and entered exactly')
    audit_backup_reference = 'STAGING_NO_BACKUP' if staging_bypass else approved_backup
    if data.confirm_word != 'DELETE':
        raise HTTPException(422,'Type DELETE to confirm')
    try:
        # PostgreSQL locks prevent concurrent edits to the company row during purge.
        row=db.scalar(select(Company).where(Company.id==company_id).with_for_update())
        if not row: raise HTTPException(404,'Company not found')
        if data.confirm_name != row.name:
            raise HTTPException(422,'Company name confirmation does not match')
        counts=company_delete_counts(db,company_id)
        purge_company_records(db,company_id)
        db.execute(delete(Company).where(Company.id==company_id))
        db.execute(company_delete_audit.insert().values(company_id=company_id,company_name=row.name,
            actor_user_id=user.id,actor_email=user.email,backup_reference=audit_backup_reference,
            deleted_counts=counts,deleted_at=datetime.now(timezone.utc)))
        db.commit()
    except HTTPException:
        db.rollback();raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(409,'Deletion blocked by database relationships or database error. No deletion committed. Review server logs.')
    return {'status':'deleted','company_id':company_id,'deleted_counts':counts,'audit_recorded':True}

@app.delete('/api/v1/companies/{company_id}')
def delete_empty_company(company_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin'); row=db.get(Company,company_id)
    if not row: raise HTTPException(404,'Company not found')
    for model in (User,Driver,Vehicle,Trip,OdometerReading,MaintenanceSchedule,DrivingEvent,DriverLocation,CompanyDrivingSettings):
        if db.scalar(select(func.count()).select_from(model).where(model.company_id==company_id)):
            raise HTTPException(409,'Company has related records. Use deletion preview and permanent delete.')
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
    allow(user,'super_admin'); target=db.get(User,user_id)
    if not target: raise HTTPException(404,'User not found')
    if target.id==user.id or target.role=='super_admin': raise HTTPException(409,'Cannot delete a Super Admin account')
    db.execute(delete(AccountInvitation).where(AccountInvitation.user_id==user_id))
    db.execute(delete(DriverAccount).where(DriverAccount.user_id==user_id))
    db.delete(target)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Account has other dependent records')
    return {'status':'deleted'}

class DriverEdit(BaseModel):
    full_name: str | None = Field(default=None,min_length=2,max_length=160)
    phone: str | None = Field(default=None,max_length=40)
    status: str | None = None
    id_number: str | None = Field(default=None,min_length=1,max_length=40)
    site_name: str | None = Field(default=None,min_length=1,max_length=160)
    vehicle_id: int | None = None
    company_id: int | None = None

@app.get('/api/v1/drivers/details')
def driver_details(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    q=select(Driver)
    if user.role!='super_admin':q=q.where(Driver.company_id==user.company_id)
    result={}
    for d in db.scalars(q):
        meta=db.get(DriverMetadata,d.id)
        vehicle=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id))
        result[str(d.id)]={'id_number':meta.id_number if meta else '', 'site_name':meta.site_name if meta else '', 'vehicle_id':vehicle.id if vehicle else None}
    return {'drivers':result}

@app.patch('/api/v1/drivers/{driver_id}',response_model=DriverOut)
def edit_driver(driver_id:int,payload:DriverEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    row=db.get(Driver,driver_id)
    if not row:raise HTTPException(404,'Driver not found')
    changes=payload.model_dump(exclude_unset=True)
    if 'status' in changes and changes['status'] not in ('active','inactive','archived'):raise HTTPException(422,'Invalid status')
    new_company=changes.get('company_id',row.company_id)
    if new_company!=row.company_id:raise HTTPException(422,'Company transfer requires a separate audited workflow; edit within the same company')
    if 'phone' in changes and changes['phone']:
        normalized=normalize_phone(changes['phone'])
        if any(d.id!=row.id and normalize_phone(d.phone)==normalized for d in db.scalars(select(Driver).where(Driver.company_id==row.company_id))):raise HTTPException(409,'Phone already in use')
        changes['phone']=normalized
    if 'id_number' in changes and changes['id_number']:
        id_number=changes['id_number'].strip()
        if db.scalar(select(DriverMetadata).where(DriverMetadata.id_number==id_number,DriverMetadata.driver_id!=driver_id)):raise HTTPException(409,'ID/Iqama already in use')
    meta=db.get(DriverMetadata,driver_id)
    if ('id_number' in changes or 'site_name' in changes) and not meta:
        if not changes.get('id_number') or not changes.get('site_name'):raise HTTPException(422,'ID and site required for legacy drivers')
        meta=DriverMetadata(driver_id=driver_id,id_number=changes['id_number'],site_name=changes['site_name']);db.add(meta)
    if meta:
        for key in ('id_number','site_name'):
            if key in changes:
                if not changes[key] or not changes[key].strip():raise HTTPException(422,f'{key} cannot be empty')
                setattr(meta,key,changes[key].strip())
    if 'vehicle_id' in changes:
        target_id=changes['vehicle_id']
        target=db.get(Vehicle,target_id) if target_id is not None else None
        if target_id is not None and (not target or target.company_id!=row.company_id):raise HTTPException(422,'Select a vehicle in the same company')
        if target and target.assigned_driver_id not in (None,driver_id):raise HTTPException(409,'Vehicle assigned to another driver')
        for v in db.scalars(select(Vehicle).where(Vehicle.assigned_driver_id==driver_id)):
            v.assigned_driver_id=None
        db.flush()
        if target:target.assigned_driver_id=driver_id
    for key in ('full_name','phone','status'):
        if key in changes:setattr(row,key,changes[key])
    if 'full_name' in changes:
        account=db.scalar(select(DriverAccount).where(DriverAccount.driver_id==driver_id))
        if account:
            linked=db.get(User,account.user_id)
            if linked:linked.full_name=row.full_name
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Update conflicts with another record')
    db.refresh(row)
    return row

@app.delete('/api/v1/drivers/{driver_id}')
def delete_driver(driver_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(Driver,driver_id)
    if not row: raise HTTPException(404,'Driver not found')
    if db.scalar(select(func.count()).select_from(Trip).where(Trip.driver_id==driver_id)):
        raise HTTPException(409,'Driver has trip history. Permanently delete their company with explicit confirmation, or archive the driver.')
    for v in db.scalars(select(Vehicle).where(Vehicle.assigned_driver_id==driver_id)):v.assigned_driver_id=None
    db.execute(delete(DriverAccount).where(DriverAccount.driver_id==driver_id))
    db.flush();db.delete(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Driver has other linked history. Archive instead.')
    return {'status':'deleted'}

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
from .models import DriverAccount, DrivingEvent, DriverLocation, CompanyDrivingSettings, CompanyEventCondition
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

class DriverLinkIn(BaseModel):
    user_id: int
    vehicle_id: int | None = None

@app.get('/api/v1/driver-accounts')
def list_driver_links(db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    q=select(DriverAccount,Driver,User).join(Driver,Driver.id==DriverAccount.driver_id).join(User,User.id==DriverAccount.user_id)
    if user.role!='super_admin': q=q.where(Driver.company_id==user.company_id)
    return [{'driver_id':d.id,'user_id':u.id,'email':u.email,'vehicle_id':db.scalar(select(Vehicle.id).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))} for a,d,u in db.execute(q).all()]

@app.put('/api/v1/drivers/{driver_id}/account-link')
def link_existing_driver(driver_id:int, data:DriverLinkIn, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    d=db.get(Driver,driver_id)
    if not d: raise HTTPException(404,'Driver not found')
    scope(user,d.company_id)
    u=db.get(User,data.user_id)
    if not u or u.role!='driver' or not u.is_active or u.company_id!=d.company_id: raise HTTPException(422,'Select an active driver login from the same company')
    existing=db.scalar(select(DriverAccount).where(DriverAccount.driver_id==d.id))
    other=db.scalar(select(DriverAccount).where(DriverAccount.user_id==u.id))
    if other and other.driver_id!=d.id: raise HTTPException(409,'This login is already linked to another driver')
    if existing and existing.user_id!=u.id: raise HTTPException(409,'This driver already has a different login; contact Super Admin')
    v=None
    if data.vehicle_id is not None:
        v=db.get(Vehicle,data.vehicle_id)
        if not v or v.company_id!=d.company_id: raise HTTPException(422,'Vehicle must belong to the same company')
        if v.assigned_driver_id not in (None,d.id): raise HTTPException(409,'Vehicle is assigned to another driver')
        previous=db.scalars(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.id!=v.id)).all()
        if any(db.scalar(select(Trip.id).where(Trip.vehicle_id==old.id,Trip.status=='active')) for old in previous): raise HTTPException(409,'Finish the active trip before changing the vehicle')
        for old in previous: old.assigned_driver_id=None
        v.assigned_driver_id=d.id
    if not existing: db.add(DriverAccount(driver_id=d.id,user_id=u.id))
    try: db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,'Driver or login already linked')
    return {'driver_id':d.id,'user_id':u.id,'vehicle_id':v.id if v else None,'status':'linked'}

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

EVENT_KINDS = ('speeding', 'harsh_acceleration', 'harsh_braking', 'harsh_cornering', 'geofence_entry', 'geofence_exit', 'geofence_restricted')

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

# Phase 4: circular geofences and risk policies. Stored per company in existing AppSetting.
# All rules are evaluated server-side on uploaded GPS samples, including delayed offline samples.
class GeoZoneIn(BaseModel):
    name: str = Field(min_length=1,max_length=80)
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    radius_m: float = Field(ge=50,le=20000)
    mode: str = Field(default='restricted',pattern='^(restricted|monitor)$')
    speed_limit_kmh: float | None = Field(default=None,ge=10,le=200)

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
    zone={'id':secrets.token_hex(8),**data.model_dump()}
    zones.append(zone);key=f'phase4_zones:{cid}';row=db.get(AppSetting,key)
    if row:row.value=json.dumps(zones)
    else:db.add(AppSetting(key=key,value=json.dumps(zones)))
    db.commit();return zone

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
            prior=_distance_m(previous.latitude,previous.longitude,zone['latitude'],zone['longitude'])<=zone['radius_m']
            inside=_distance_m(data.latitude,data.longitude,zone['latitude'],zone['longitude'])<=zone['radius_m']
            if prior!=inside:events.append(('geofence_entry' if inside else 'geofence_exit',float(zone['radius_m'])))
            if inside and zone['mode']=='restricted':events.append(('geofence_restricted',float(zone['radius_m'])))
            if inside and zone.get('speed_limit_kmh') and data.speed_kmh>zone['speed_limit_kmh']:
                events.append(('speeding',data.speed_kmh))
    return events

# Nuqati Safety Score v1: configurable per-company GPS-only scoring.
SCORE_CATEGORIES = ('harsh_acceleration','harsh_braking','harsh_cornering','speeding','excessive_speeding')
DEFAULT_SCORE_WEIGHTS = {'harsh_acceleration':20,'harsh_braking':20,'harsh_cornering':20,'speeding':25,'excessive_speeding':15}

class ScorePolicyIn(BaseModel):
    weights: dict[str,int]
    excessive_speed_margin_kmh: float = Field(default=20,ge=5,le=100)
    events_per_100km_full_penalty: float = Field(default=10,gt=0,le=100)
    minimum_distance_km: float = Field(default=1,ge=0.1,le=100)

def score_policy(db,cid):
    raw=_setting_json(db,f'safety_score_policy:{cid}',{})
    policy={'weights':DEFAULT_SCORE_WEIGHTS.copy(),'excessive_speed_margin_kmh':20.0,'events_per_100km_full_penalty':10.0,'minimum_distance_km':1.0}
    if isinstance(raw,dict):
        try: return ScorePolicyIn(**{**policy,**raw}).model_dump()
        except Exception: pass
    return policy

def validate_score_policy(policy):
    if set(policy.weights)!=set(SCORE_CATEGORIES) or any(type(v)!=int or v<0 or v>100 for v in policy.weights.values()) or sum(policy.weights.values())!=100:
        raise HTTPException(422,'Provide all five integer scoring weights totaling exactly 100')

def calculate_safety_score(events, distance_km, policy, speed_threshold_kmh):
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

@app.get('/api/v1/fleet/phase4/risk')
def phase4_risk(period:str='weekly',company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    cid=_company_for_policy(db,user,company_id)
    if period not in ('daily','weekly','monthly'):raise HTTPException(422,'Invalid period')
    since=datetime.now(timezone.utc)-timedelta(days={'daily':1,'weekly':7,'monthly':30}[period])
    policy=score_policy(db,cid);output=[]
    speed_limit=thresholds(db,cid).speeding_kmh
    for driver in db.scalars(select(Driver).where(Driver.company_id==cid)).all():
        events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.driver_id==driver.id,DrivingEvent.recorded_at>=since)).all())
        trips=list(db.scalars(select(Trip).where(Trip.company_id==cid,Trip.driver_id==driver.id,Trip.started_at>=since,Trip.status=='completed')).all())
        km=sum(max(0,t.distance_km or 0) for t in trips)
        result=calculate_safety_score(events,km,policy,speed_limit)
        score=result['score'];risk=result['risk']
        output.append({'driver_id':driver.id,'driver_name':driver.full_name,'distance_km':round(km,2),'score':score,'risk':risk,'event_count':len(events),'score_breakdown':result})
    return {'company_id':cid,'period':period,'drivers':output}

@app.get('/api/v1/mobile/driving-policy')
def mobile_driving_policy(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);t=thresholds(db,d.company_id)
    return {'speeding_kmh':t.speeding_kmh,'harsh_accel_ms2':t.harsh_accel_ms2,
            'harsh_brake_ms2':t.harsh_brake_ms2,**event_policy(db,d.company_id), 'phase4': phase4_settings(db,d.company_id)}


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

@app.get('/api/v1/mobile/trips/active')
def get_active_mobile_trip(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    trip=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id,Trip.status=='active').order_by(Trip.id.desc()).limit(1))
    if not trip:
        return {'active':False,'trip_id':None}
    return {'active':True,'trip_id':trip.id,'started_at':trip.started_at.isoformat() if trip.started_at else None}

# Stable device trip IDs make retries idempotent and preserve offline trip boundaries.
with engine.begin() as _trip_conn:
    _trip_conn.execute(text('''CREATE TABLE IF NOT EXISTS mobile_trip_client_ids (
        driver_id INTEGER NOT NULL,
        client_trip_id VARCHAR(90) NOT NULL,
        trip_id INTEGER NOT NULL,
        PRIMARY KEY (driver_id, client_trip_id),
        UNIQUE (trip_id)
    )'''))

class OfflineTripStart(BaseModel):
    client_trip_id: str | None = Field(default=None, min_length=8, max_length=90, pattern=r'^[a-zA-Z0-9_-]+$')
    started_at: datetime | None = None

class OfflineTripFinish(BaseModel):
    ended_at: datetime | None = None

def _safe_device_time(value:datetime | None):
    if value is None: return datetime.now(timezone.utc)
    if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
    value=value.astimezone(timezone.utc)
    if value>datetime.now(timezone.utc)+timedelta(minutes=5) or value<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid device trip timestamp')
    return value

@app.post('/api/v1/mobile/trips/start', status_code=201)
def start_mobile_trip(payload:OfflineTripStart | None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))
    if not v: raise HTTPException(409,'Assign a vehicle to this driver first')
    client_id=payload.client_trip_id if payload else None
    started=_safe_device_time(payload.started_at if payload else None)
    if client_id:
        mapping=db.execute(text('SELECT trip_id FROM mobile_trip_client_ids WHERE driver_id=:d AND client_trip_id=:c'),{'d':d.id,'c':client_id}).first()
        if mapping:
            existing=db.get(Trip,mapping[0])
            if not existing: raise HTTPException(409,'Mapped trip missing')
            return {'trip_id':existing.id,'started_at':existing.started_at.isoformat(),'resumed':True}
    existing=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.status=='active'))
    if existing:
        if not client_id:
            return {'trip_id':existing.id,'started_at':existing.started_at.isoformat(),'resumed':True}
        # Prior offline journey must not be merged with the next journey.
        # If this is an old device-created trip, do not auto-finish without its queued samples.
        mapped=db.execute(text('SELECT client_trip_id FROM mobile_trip_client_ids WHERE trip_id=:t'),{'t':existing.id}).first()
        if mapped:
            raise HTTPException(409,'Previous trip must synchronize and finish first')
        raise HTTPException(409,'Legacy active trip must be completed before offline sync')
    trip=Trip(company_id=d.company_id,driver_id=d.id,vehicle_id=v.id,status='active',started_at=started)
    db.add(trip);db.flush()
    if client_id:
        db.execute(text('INSERT INTO mobile_trip_client_ids (driver_id,client_trip_id,trip_id) VALUES (:d,:c,:t)'),
                   {'d':d.id,'c':client_id,'t':trip.id})
    db.commit();db.refresh(trip)
    return {'trip_id':trip.id,'started_at':trip.started_at.isoformat()}

# Phase 1B: persist client sample IDs so reconnect retries cannot duplicate GPS points.
# This additive table does not modify existing trip/location schemas.
with engine.begin() as _conn:
    _conn.execute(text('''CREATE TABLE IF NOT EXISTS mobile_gps_sample_receipts (
        trip_id INTEGER NOT NULL,
        sample_id VARCHAR(80) NOT NULL,
        captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (trip_id, sample_id)
    )'''))

class Sample(BaseModel):
    sample_id: str | None = Field(default=None, min_length=8, max_length=80)
    captured_at: datetime | None = None
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    accuracy_m: float = Field(ge=0,le=10000)
    speed_kmh: float = Field(ge=0,le=350)
    acceleration_ms2: float = Field(ge=-30,le=30,default=0)
    gps_age_seconds: float | None = Field(default=None,ge=0,le=3600)
    gps_hdop: float | None = Field(default=None,ge=0,le=100)
    gps_satellites: int | None = Field(default=None,ge=0,le=100)

@app.post('/api/v1/mobile/trips/{trip_id}/sample')
def submit_sample(trip_id:int,data:Sample,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id or trip.company_id!=d.company_id or trip.status!='active': raise HTTPException(404,'Active trip not found')
    if data.accuracy_m>50: return {'accepted':False,'reason':'GPS accuracy worse than 50m'}
    now=datetime.now(timezone.utc)
    captured=data.captured_at or now
    if captured.tzinfo is None: captured=captured.replace(tzinfo=timezone.utc)
    captured=captured.astimezone(timezone.utc)
    if captured>now+timedelta(seconds=30) or captured<now-timedelta(days=14):
        raise HTTPException(422,'GPS capture time outside accepted range')
    if data.sample_id:
        seen=db.execute(text('SELECT 1 FROM mobile_gps_sample_receipts WHERE trip_id=:t AND sample_id=:s'),{'t':trip.id,'s':data.sample_id}).first()
        if seen: return {'accepted':True,'duplicate':True,'events':[],'rejected_events':{}}

    previous=db.scalar(select(DriverLocation).where(DriverLocation.trip_id==trip.id).order_by(DriverLocation.id.desc()).limit(1))
    if previous and (captured-previous.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()<0.7:
        raise HTTPException(429,'Sample interval must be at least 0.7 seconds; upload oldest first')
    row=DriverLocation(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,latitude=data.latitude,longitude=data.longitude,accuracy_m=data.accuracy_m,speed_kmh=data.speed_kmh,recorded_at=captured)
    db.add(row)
    # Accumulate plausible point-to-point distance; ignore GPS jumps and stationary jitter.
    if previous and previous.accuracy_m is not None and previous.accuracy_m<=30 and data.accuracy_m<=30:
        elapsed=(captured-previous.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()
        a1,a2=math.radians(previous.latitude),math.radians(data.latitude)
        da=a2-a1; dl=math.radians(data.longitude-previous.longitude)
        h=math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2
        metres=6371000*2*math.asin(min(1.0,math.sqrt(max(0.0,h))))
        # Avoid counting stationary GPS noise; reject impossible jumps.
        if elapsed>0 and 5<=metres<=min(80*elapsed,1000) and (metres/elapsed)<=max(12.0,data.speed_kmh/3.6+8.0):
            trip.distance_km=(trip.distance_km or 0.0)+metres/1000
    cfg=thresholds(db,d.company_id); policy=event_policy(db,d.company_id); kinds=[]
    if policy['enabled']['speeding'] and data.speed_kmh>cfg.speeding_kmh: kinds.append(('speeding',data.speed_kmh))
    if policy['enabled']['harsh_acceleration'] and data.acceleration_ms2>=cfg.harsh_accel_ms2: kinds.append(('harsh_acceleration',data.acceleration_ms2))
    if policy['enabled']['harsh_braking'] and data.acceleration_ms2<=-cfg.harsh_brake_ms2: kinds.append(('harsh_braking',abs(data.acceleration_ms2)))
    kinds.extend((kind,value) for kind,value in phase4_candidates(db,trip,previous,data,captured) if policy['enabled'].get(kind,False))
    # Fail closed for missing or stale GPS metadata when a condition is enabled.
    # Location history can still be stored; only qualified samples create violations.
    qualified=[];rejected={}
    for kind,value in kinds:
        cond=event_condition_view(db,d.company_id,kind)
        if not policy['enforce_gps_conditions']:
            qualified.append((kind,value))
            continue
        reason=None
        if not gps_compare(data.accuracy_m,cond['accuracy_operator'],cond['max_accuracy_m']): reason='gps_accuracy'
        elif data.gps_age_seconds is None or not gps_compare(data.gps_age_seconds,cond['gps_age_operator'],cond['max_gps_age_seconds']): reason='gps_age_missing_or_stale'
        elif cond['max_hdop'] is not None and (data.gps_hdop is None or not gps_compare(data.gps_hdop,cond['hdop_operator'],cond['max_hdop'])): reason='gps_hdop_missing_or_high'
        elif cond['min_satellites'] is not None and (data.gps_satellites is None or not gps_compare(data.gps_satellites,cond['satellites_operator'],cond['min_satellites'])): reason='gps_satellites_missing_or_low'
        if reason: rejected[kind]=reason
        else: qualified.append((kind,value))
    # One event per category per 30 seconds, to avoid counting every sample as a separate violation.
    for kind,value in qualified:
        latest=db.scalar(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id,DrivingEvent.event_type==kind).order_by(DrivingEvent.id.desc()).limit(1))
        if latest and (captured-latest.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()<30: continue
        db.add(DrivingEvent(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,event_type=kind,value=value,latitude=data.latitude,longitude=data.longitude,recorded_at=captured))
    if data.sample_id:
        db.execute(text('INSERT INTO mobile_gps_sample_receipts (trip_id,sample_id,captured_at) VALUES (:t,:s,:c)'),
                   {'t':trip.id,'s':data.sample_id,'c':captured})
    db.commit();return {'accepted':True,'events': [x[0] for x in qualified], 'rejected_events': rejected}

@app.post('/api/v1/mobile/trips/{trip_id}/finish')
def finish_mobile_trip(trip_id:int,payload:OfflineTripFinish | None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id: raise HTTPException(404,'Trip not found')
    if trip.status=='completed': return {'trip_id':trip.id,'status':'completed','distance_km':trip.distance_km}
    if trip.status!='active': raise HTTPException(409,'Trip cannot be completed')
    # Lock the vehicle to serialize mileage updates from overlapping trip completions.
    vehicle=db.scalar(select(Vehicle).where(Vehicle.id==trip.vehicle_id).with_for_update())
    if not vehicle: raise HTTPException(404,'Vehicle not found')
    trip.ended_at=_safe_device_time(payload.ended_at if payload else None)
    if trip.ended_at<trip.started_at: raise HTTPException(422,'Trip finish precedes trip start')
    trip.status='completed'
    added=max(0.0,trip.distance_km or 0.0)
    if vehicle.odometer_km is not None and added>0:
        vehicle.odometer_km+=added
        db.add(OdometerReading(company_id=vehicle.company_id,vehicle_id=vehicle.id,reading_km=vehicle.odometer_km,source='GPS_TRIP',note=f'Completed trip #{trip.id}: +{added:.3f} km'))
    db.commit()
    return {'trip_id':trip.id,'status':'completed','distance_km':added,'vehicle_odometer_km':vehicle.odometer_km}

def period_start(period):
    now=datetime.now(timezone.utc)
    if period=='daily': return now-timedelta(days=1)
    if period=='weekly': return now-timedelta(days=7)
    if period=='monthly': return now-timedelta(days=30)
    if period=='yearly': return now-timedelta(days=365)
    raise HTTPException(422,'period must be daily, weekly, monthly or yearly')

@app.get('/api/v1/fleet/trips/{trip_id}/route')
def fleet_trip_route(trip_id:int, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff','driver')
    trip=db.get(Trip,trip_id)
    if not trip: raise HTTPException(404,'Trip not found')
    scope(user,trip.company_id)
    if user.role=='driver' and own_driver(db,user).id!=trip.driver_id:
        raise HTTPException(403,'Own trips only')
    points=list(db.scalars(select(DriverLocation).where(DriverLocation.trip_id==trip.id).order_by(DriverLocation.recorded_at,DriverLocation.id).limit(10001)).all())
    truncated=len(points)>10000
    points=points[:10000]
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id).order_by(DrivingEvent.recorded_at)).all())
    def point(p):
        return {'latitude':p.latitude,'longitude':p.longitude,'recorded_at':p.recorded_at.isoformat(),'speed_kmh':p.speed_kmh,'accuracy_m':p.accuracy_m}
    valid=[p for p in points if p.speed_kmh is not None and 0<=p.speed_kmh<=350 and p.accuracy_m is not None and p.accuracy_m<=100]
    return {'trip_id':trip.id,'status':trip.status,'started_at':trip.started_at.isoformat(),
            'ended_at':trip.ended_at.isoformat() if trip.ended_at else None,
            'distance_km':trip.distance_km,'max_speed_kmh':max((p.speed_kmh for p in valid),default=None),
            'points':[point(p) for p in points],'start':point(points[0]) if points else None,
            'end':point(points[-1]) if points else None,'truncated':truncated,
            'violations':[{'id':e.id,'type':e.event_type,'value':e.value,'latitude':e.latitude,
                           'longitude':e.longitude,'recorded_at':e.recorded_at.isoformat()} for e in events if e.latitude is not None and e.longitude is not None]}

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
        counts={k:sum(e.event_type==k for e in events) for k in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')}
        km=sum(max(0,t.distance_km or 0) for t in trips if t.status=='completed')
        breakdown=calculate_safety_score(events,km,score_policy(db,cid),thresholds(db,cid).speeding_kmh)
        score=breakdown['score']
        loc=db.scalar(select(DriverLocation).where(DriverLocation.company_id==cid,DriverLocation.driver_id==d.id).order_by(DriverLocation.id.desc()).limit(1))
        output.append({'driver_id':d.id,'driver_name':d.full_name,'trips':len(trips),'score':score,'risk':breakdown['risk'],'score_breakdown':breakdown,'violations':counts,'latest_location':{'latitude':loc.latitude,'longitude':loc.longitude,'recorded_at':loc.recorded_at.isoformat(),'accuracy_m':loc.accuracy_m} if loc else None,'trip_details':[{'id':t.id,'vehicle_id':t.vehicle_id,'started_at':t.started_at.isoformat(),'ended_at':t.ended_at.isoformat() if t.ended_at else None,'status':t.status,'distance_km':t.distance_km,'max_speed_kmh':db.scalar(select(func.max(DriverLocation.speed_kmh)).where(DriverLocation.trip_id==t.id,DriverLocation.accuracy_m<=100,DriverLocation.speed_kmh>=0,DriverLocation.speed_kmh<=350)),'violations':[{'type':e.event_type,'value':e.value,'recorded_at':e.recorded_at.isoformat()} for e in events if e.trip_id==t.id]} for t in trips]})
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
    if not target: raise HTTPException(404,'User not found')
    if target.role=='driver' or target.email.endswith('@login.nuqati.invalid'):
        raise HTTPException(422,'Driver accounts use Iqama login, not email invitations')
    if target.is_active:
        host=os.environ.get('NUQATI_SMTP_HOST','')
        username=os.environ.get('NUQATI_SMTP_USER','')
        password=os.environ.get('NUQATI_SMTP_PASSWORD','')
        origin=os.environ.get('NUQATI_PUBLIC_ORIGIN','').rstrip('/')
        if not host or not username or not password or not origin.startswith('https://'):
            raise HTTPException(503,'SMTP or HTTPS public origin not configured in Coolify')
        msg=EmailMessage()
        msg['Subject']='Nuqati account sign-in reminder | تذكير بالدخول إلى نقاطي'
        msg['From']=f'Nuqati <{os.environ.get("NUQATI_EMAIL_FROM", "noreply@al-riadah.sa")}> '
        msg['To']=target.email
        msg.set_content('Your Nuqati account is already active. Sign in using your existing credentials: '+origin+'\n\nحسابك في نقاطي مفعل. يمكنك تسجيل الدخول باستخدام بياناتك الحالية: '+origin+'\n\nIf you did not request this, ignore this message.')
        try:
            with smtplib.SMTP(host,int(os.environ.get('NUQATI_SMTP_PORT','587')),timeout=15) as smtp:
                smtp.starttls(context=ssl.create_default_context())
                smtp.login(username,password)
                smtp.send_message(msg)
        except (OSError,smtplib.SMTPException) as exc:
            raise HTTPException(502,'Email delivery failed; check SMTP settings') from exc
        return {'status':'reminder_sent'}
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


# Monthly fleet reporting: calendar-month UTC boundaries; company-scoped and read-only.
from fastapi.responses import StreamingResponse
from io import BytesIO, StringIO
import csv

def _monthly_fleet_data(db, cid, year, month, driver_id=None):
    start=datetime(year,month,1,tzinfo=timezone.utc)
    end=datetime(year+1,1,1,tzinfo=timezone.utc) if month==12 else datetime(year,month+1,1,tzinfo=timezone.utc)
    company=db.get(Company,cid)
    vehicles=list(db.scalars(select(Vehicle).where(Vehicle.company_id==cid).order_by(Vehicle.plate_number)).all())
    drivers=list(db.scalars(select(Driver).where(Driver.company_id==cid,*([Driver.id==driver_id] if driver_id is not None else [])).order_by(Driver.full_name)).all())
    if driver_id is not None and not drivers:raise HTTPException(404,'Driver not found in company')
    all_drivers={d.id:d for d in db.scalars(select(Driver).where(Driver.company_id==cid)).all()}
    trips=list(db.scalars(select(Trip).where(Trip.company_id==cid,Trip.started_at>=start,Trip.started_at<end,Trip.status=='completed')).all())
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.recorded_at>=start,DrivingEvent.recorded_at<end)).all())
    policy=score_policy(db,cid);speed_limit=thresholds(db,cid).speeding_kmh
    vehicle_rows=[]
    for v in vehicles:
        vt=[t for t in trips if t.vehicle_id==v.id]
        ids=sorted({t.driver_id for t in vt})
        assigned=all_drivers.get(v.assigned_driver_id)
        vehicle_rows.append({'vehicle_id':v.id,'plate_number':v.plate_number,'model':v.make_model,'odometer_km':v.odometer_km,'assigned_driver':assigned.full_name if assigned else '', 'assigned_driver_id':v.assigned_driver_id,'monthly_driver_names':', '.join(all_drivers[i].full_name for i in ids if i in all_drivers),'trip_count':len(vt),'distance_km':round(sum(max(0,t.distance_km or 0) for t in vt),2)})
    rows=[]
    for d in drivers:
        dt=[t for t in trips if t.driver_id==d.id]
        ev=[e for e in events if e.driver_id==d.id]
        km=sum(max(0,t.distance_km or 0) for t in dt)
        seconds=sum(max(0,(t.ended_at-t.started_at).total_seconds()) for t in dt if t.ended_at and t.started_at)
        counts={kind:sum(e.event_type==kind for e in ev) for kind in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')}
        score=calculate_safety_score(ev,km,policy,speed_limit)
        counts['excessive_speeding']=score['categories']['excessive_speeding']
        # Excessive speeding is a subset of speeding, not an additional violation.
        rag='Green' if score['score'] is not None and score['score']>=90 else 'Amber' if score['score'] is not None and score['score']>=60 else 'Red' if score['score'] is not None else 'No data'
        by_vehicle=[]
        for v in vehicles:
            subset=[t for t in dt if t.vehicle_id==v.id]
            if subset:by_vehicle.append({'vehicle_id':v.id,'plate_number':v.plate_number,'trips':len(subset),'distance_km':round(sum(max(0,t.distance_km or 0) for t in subset),2),'driving_hours':round(sum(max(0,(t.ended_at-t.started_at).total_seconds()) for t in subset if t.ended_at and t.started_at)/3600,2)})
        rows.append({'driver_id':d.id,'driver_name':d.full_name,'trip_count':len(dt),'distance_km':round(km,2),'driving_hours':round(seconds/3600,2),'active_days':len({t.started_at.date() for t in dt}),'score':score['score'],'rag':rag,'risk':score['risk'],'violations':counts,'total_violations':len(ev),'vehicles':by_vehicle})
    return {'company_id':cid,'company_name':company.name if company else '', 'year':year,'month':month,'month_label':f'{year}-{month:02d}','period_start':start.isoformat(),'period_end_exclusive':end.isoformat(),'vehicles':vehicle_rows,'drivers':rows,'notes':['All times are UTC. Only completed trips are counted for utilization.','Driving hours are elapsed trip durations, not engine-on hours.','Excessive speeding is included in speeding totals and must not be added again.','No score means insufficient distance; no RAG color is assigned.','Vehicle assignment is current; monthly vehicle usage is based on recorded trips.']}

@app.get('/api/v1/fleet/monthly-reports')
def monthly_fleet_reports(year:int,month:int,company_id:int|None=None,driver_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    if year<2020 or year>2100 or month<1 or month>12:raise HTTPException(422,'Invalid year or month')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None:raise HTTPException(422,'Select company')
    scope(user,cid)
    return _monthly_fleet_data(db,cid,year,month,driver_id)

@app.get('/api/v1/fleet/monthly-reports/export')
def monthly_fleet_export(year:int,month:int,format:Literal['pdf','csv','xlsx'],kind:Literal['vehicles','utilization','rag','violations'],company_id:int|None=None,driver_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    data=monthly_fleet_reports(year,month,company_id,driver_id,db,user)
    headers={
      'vehicles':['Plate','Model','Assigned driver','Monthly drivers','Odometer km','Trips','Distance km'],
      'utilization':['Driver','Vehicle','Trips','Distance km','Driving hours','Active days'],
      'rag':['Driver','Score / 100','RAG','Risk','Trips','Distance km'],
      'violations':['Driver','Speeding (includes excessive)','Excessive speeding','Harsh braking','Harsh acceleration','Harsh cornering','Total violations']}
    cols=headers[kind];rows=[]
    if kind=='vehicles':
        rows=[[v['plate_number'],v['model'],v['assigned_driver'],v['monthly_driver_names'],v['odometer_km'],v['trip_count'],v['distance_km']] for v in data['vehicles']]
    elif kind=='utilization':
        rows=[[d['driver_name'],v['plate_number'],v['trips'],v['distance_km'],v['driving_hours'],d['active_days']] for d in data['drivers'] for v in d['vehicles']]
    elif kind=='rag':
        rows=[[d['driver_name'],d['score'],d['rag'],d['risk'],d['trip_count'],d['distance_km']] for d in data['drivers']]
    else:
        rows=[[d['driver_name'],d['violations']['speeding'],d['violations']['excessive_speeding'],d['violations']['harsh_braking'],d['violations']['harsh_acceleration'],d['violations']['harsh_cornering'],d['total_violations']] for d in data['drivers']]
    filename=f"nuqati-{kind}-{data['company_id']}-{data['month_label']}.{format}"
    if format=='csv':
        f=StringIO();w=csv.writer(f);w.writerow(cols);w.writerows(rows)
        payload=('\ufeff'+f.getvalue()).encode('utf-8-sig')
        mime='text/csv; charset=utf-8'
    elif format=='xlsx':
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
        wb=Workbook();ws=wb.active;ws.title=kind.capitalize();ws.append(cols)
        for row in rows:ws.append([v if v is not None else '' for v in row])
        for cell in ws[1]:cell.font=Font(bold=True,color='FFFFFF');cell.fill=PatternFill('solid',fgColor='17324D')
        ws.freeze_panes='A2';ws.auto_filter.ref=ws.dimensions
        for col in ws.columns:
            letter=col[0].column_letter;ws.column_dimensions[letter].width=min(42,max(13,max(len(str(c.value or '')) for c in col)+2))
        f=BytesIO();wb.save(f);payload=f.getvalue()
        mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    else:
        from reportlab.platypus import SimpleDocTemplate,Table,TableStyle,Paragraph,Spacer
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.pagesizes import landscape,A4
        f=BytesIO();doc=SimpleDocTemplate(f,pagesize=landscape(A4),leftMargin=22,rightMargin=22)
        styles=getSampleStyleSheet()
        content=[Paragraph(f"Nuqati | {kind.capitalize()} | {data['company_name']} | {data['month_label']}",styles['Title']),Spacer(1,12)]
        table=Table([[str(c) for c in cols]]+[[str(v if v is not None else '') for v in row] for row in rows],repeatRows=1,hAlign='LEFT')
        table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#17324D')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('FONTSIZE',(0,0),(-1,-1),8),('BOTTOMPADDING',(0,0),(-1,-1),6),('GRID',(0,0),(-1,-1),0.25,colors.lightgrey)]))
        content.append(table);doc.build(content);payload=f.getvalue();mime='application/pdf'
    return StreamingResponse(BytesIO(payload),media_type=mime,headers={'Content-Disposition':f'attachment; filename="{filename}"','Cache-Control':'no-store'})



@app.get('/api/v1/fleet/overview/daily')
def fleet_overview_daily(days:int=7,company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Permission-scoped daily aggregates, based on recorded trip starts and events (UTC)."""
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    days=max(1,min(days,31))
    if user.role!='super_admin':
        if company_id is not None and company_id!=user.company_id: raise HTTPException(403,'Company scope')
        company_id=user.company_id
    if company_id is not None:
        scope(user,company_id)
    end=datetime.now(timezone.utc).replace(hour=0,minute=0,second=0,microsecond=0)+timedelta(days=1)
    start=end-timedelta(days=days)
    company_filter=([Trip.company_id==company_id] if company_id is not None else [])
    trips=list(db.scalars(select(Trip).where(Trip.started_at>=start,Trip.started_at<end,*company_filter)).all())
    event_filter=([DrivingEvent.company_id==company_id] if company_id is not None else [])
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.recorded_at>=start,DrivingEvent.recorded_at<end,*event_filter)).all())
    vehicle_filter=([Vehicle.company_id==company_id] if company_id is not None else [])
    vehicle_count=db.scalar(select(func.count(Vehicle.id)).where(*vehicle_filter)) or 0
    rows=[]
    for i in range(days):
        day=start+timedelta(days=i)
        next_day=day+timedelta(days=1)
        ts=[t for t in trips if day<=t.started_at.astimezone(timezone.utc)<next_day]
        ev=[e for e in events if day<=e.recorded_at.astimezone(timezone.utc)<next_day]
        counts={name:sum(1 for e in ev if e.event_type==name) for name in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')}
        used=len(set(t.vehicle_id for t in ts))
        rows.append({'date':day.date().isoformat(),'trips':len(ts),'distance_km':round(sum(max(0,t.distance_km or 0) for t in ts if t.status=='completed'),2),
                     'drivers_active':len(set(t.driver_id for t in ts)),'vehicles_with_trips':used,'vehicles_without_trips':max(0,vehicle_count-used),
                     'violations':len(ev),**counts})
    return {'days':rows,'vehicle_count':vehicle_count,'totals':{'trips':sum(r['trips'] for r in rows),
        'distance_km':round(sum(r['distance_km'] for r in rows),2),
        'drivers_active':len(set(t.driver_id for t in trips)),
        'violations':len(events)}}
