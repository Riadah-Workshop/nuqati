import math
from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func, delete, text
from .config import settings
from .db import Base, engine, get_db
from .models import Company, Driver, Vehicle, OdometerReading, Trip, MaintenanceSchedule, User, DriverMetadata
from .schemas import CompanyCreate, CompanyOut, DriverCreate, DriverOut, VehicleCreate, VehicleOut, OdometerCreate, OdometerOut, MaintenanceScheduleUpsert, MaintenanceScheduleOut
from .auth import current_user, hash_password, verify_password, encode_token, refresh_driver_session, allow, scope
from pydantic import BaseModel, Field
from typing import Literal
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import os
from .auth import secret
from .models import AppSetting, AccountInvitation, DriverAccount, DrivingEvent, DriverLocation, CompanyDrivingSettings, CompanyEventCondition
from datetime import datetime, timedelta, timezone, date
import secrets, hashlib, smtplib, ssl, json
from email.message import EmailMessage
secret()
Base.metadata.create_all(bind=engine)
# Additive migration: existing vehicles and trip histories are unchanged.
with engine.begin() as _vehicle_schema_connection:
    _vehicle_schema_connection.execute(text('ALTER TABLE vehicles ADD COLUMN IF NOT EXISTS door_number VARCHAR(40)'))
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

# Non-location device lifecycle and preference audit (separate from Privacy Mode selection).
with engine.begin() as _lifecycle_conn:
    _lifecycle_conn.execute(text("""CREATE TABLE IF NOT EXISTS mobile_lifecycle_audit (
      event_id VARCHAR(90) PRIMARY KEY, company_id INTEGER NOT NULL, driver_id INTEGER NOT NULL,
      event_type VARCHAR(40) NOT NULL, occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
      received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP)"""))
class MobileLifecycleEvent(BaseModel):
    event_id: str = Field(min_length=8,max_length=90,pattern=r'^[a-zA-Z0-9_-]+$')
    event_type: Literal['first_authenticated_launch','camera_monitoring_disabled','camera_monitoring_enabled','login','logout']
    occurred_at: datetime

@app.post('/api/v1/mobile/lifecycle-event')
def mobile_lifecycle_event(payload:MobileLifecycleEvent,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    at=payload.occurred_at
    if at.tzinfo is None:at=at.replace(tzinfo=timezone.utc)
    at=at.astimezone(timezone.utc)
    if at>datetime.now(timezone.utc)+timedelta(minutes=5) or at<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid event time')
    row=db.execute(text('SELECT driver_id,event_type FROM mobile_lifecycle_audit WHERE event_id=:id'),{'id':payload.event_id}).first()
    if row:
        if row[0]!=driver.id or row[1]!=payload.event_type:raise HTTPException(409,'Conflicting event ID')
        return {'accepted':True,'duplicate':True}
    db.execute(text('INSERT INTO mobile_lifecycle_audit(event_id,company_id,driver_id,event_type,occurred_at) VALUES (:i,:c,:d,:t,:a)'),
      {'i':payload.event_id,'c':driver.company_id,'d':driver.id,'t':payload.event_type,'a':at})
    db.commit();return {'accepted':True,'duplicate':False}

@app.get('/api/v1/fleet/lifecycle-audit')
def fleet_lifecycle_audit(limit:int=100,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    args={'limit':max(1,min(limit,500))}
    where=''
    if user.role!='super_admin':where='WHERE company_id=:cid';args['cid']=user.company_id
    rows=db.execute(text(f'SELECT * FROM mobile_lifecycle_audit {where} ORDER BY received_at DESC LIMIT :limit'),args).mappings().all()
    return [dict(r) for r in rows]

@app.get('/api/v1/privacy-audit')
def list_privacy_audit(limit:int=100,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    limit=max(1,min(limit,500))
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    args={'limit':limit} if user.role=='super_admin' else {'limit':limit,'cid':user.company_id}
    rows=db.execute(text(f'''SELECT event_id,company_id,driver_id,vehicle_id,privacy_enabled,selected_at,received_at
        FROM mobile_privacy_audit {where} ORDER BY received_at DESC LIMIT :limit'''),args).mappings().all()
    return [dict(row) for row in rows]

# Latest device heartbeat (no coordinates). Updated by the background location service.
with engine.begin() as _heartbeat_conn:
    _heartbeat_conn.execute(text("""CREATE TABLE IF NOT EXISTS mobile_tracking_heartbeat (
        driver_id INTEGER PRIMARY KEY, company_id INTEGER NOT NULL, vehicle_id INTEGER,
        screen_state VARCHAR(12) NOT NULL, trip_active BOOLEAN NOT NULL,
        gps_fix_age_s INTEGER, captured_at TIMESTAMP WITH TIME ZONE NOT NULL,
        received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    )"""))

class TrackingHeartbeatIn(BaseModel):
    screen_state: Literal['locked','unlocked','unknown']
    trip_active: bool
    gps_fix_age_s: int | None = Field(default=None, ge=0, le=86400)
    captured_at: datetime

@app.post('/api/v1/mobile/tracking-heartbeat')
def mobile_tracking_heartbeat(payload: TrackingHeartbeatIn, db: Session=Depends(get_db), user: User=Depends(current_user)):
    driver=own_driver(db,user)
    captured=payload.captured_at
    if captured.tzinfo is None: captured=captured.replace(tzinfo=timezone.utc)
    captured=captured.astimezone(timezone.utc)
    if abs((datetime.now(timezone.utc)-captured).total_seconds())>300:
        raise HTTPException(422,'Invalid heartbeat time')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    db.execute(text("""INSERT INTO mobile_tracking_heartbeat
      (driver_id,company_id,vehicle_id,screen_state,trip_active,gps_fix_age_s,captured_at,received_at)
      VALUES (:did,:cid,:vid,:screen,:active,:age,:at,CURRENT_TIMESTAMP)
      ON CONFLICT (driver_id) DO UPDATE SET
        company_id=EXCLUDED.company_id,vehicle_id=EXCLUDED.vehicle_id,
        screen_state=EXCLUDED.screen_state,trip_active=EXCLUDED.trip_active,
        gps_fix_age_s=EXCLUDED.gps_fix_age_s,captured_at=EXCLUDED.captured_at,
        received_at=CURRENT_TIMESTAMP"""),
      {'did':driver.id,'cid':driver.company_id,'vid':vehicle.id if vehicle else None,
       'screen':payload.screen_state,'active':payload.trip_active,
       'age':payload.gps_fix_age_s,'at':captured})
    db.commit()
    return {'accepted':True}

@app.get('/api/v1/tracking-heartbeats')
def list_tracking_heartbeats(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    args={} if user.role=='super_admin' else {'cid':user.company_id}
    rows=db.execute(text(f"""SELECT driver_id,company_id,vehicle_id,screen_state,
        trip_active,gps_fix_age_s,captured_at,received_at
        FROM mobile_tracking_heartbeat {where} ORDER BY received_at DESC LIMIT 500"""),args).mappings().all()
    return [dict(row) for row in rows]

# Driver alert preferences: separate from GPS privacy, append-only and location-free.
with engine.begin() as _alerts_conn:
    _alerts_conn.execute(text('''CREATE TABLE IF NOT EXISTS mobile_notification_audit (
        event_id VARCHAR(90) PRIMARY KEY, company_id INTEGER NOT NULL,
        driver_id INTEGER NOT NULL, vehicle_id INTEGER,
        notifications_enabled BOOLEAN NOT NULL,
        selected_at TIMESTAMP WITH TIME ZONE NOT NULL,
        received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    )'''))

class NotificationEvidence(BaseModel):
    event_id: str = Field(min_length=8,max_length=90,pattern=r'^[a-zA-Z0-9_-]+$')
    notifications_enabled: bool
    selected_at: datetime

@app.post('/api/v1/mobile/notification-evidence')
def record_notification_evidence(payload: NotificationEvidence,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    selected=payload.selected_at
    if selected.tzinfo is None: selected=selected.replace(tzinfo=timezone.utc)
    selected=selected.astimezone(timezone.utc)
    if selected>datetime.now(timezone.utc)+timedelta(minutes=5) or selected<datetime.now(timezone.utc)-timedelta(days=90):
        raise HTTPException(422,'Invalid notification preference timestamp')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    existing=db.execute(text('SELECT driver_id,notifications_enabled FROM mobile_notification_audit WHERE event_id=:id'),{'id':payload.event_id}).first()
    if existing:
        if existing[0]!=driver.id or existing[1]!=payload.notifications_enabled: raise HTTPException(409,'Conflicting notification event ID')
        return {'accepted':True,'duplicate':True}
    db.execute(text('''INSERT INTO mobile_notification_audit
        (event_id,company_id,driver_id,vehicle_id,notifications_enabled,selected_at)
        VALUES (:id,:cid,:did,:vid,:enabled,:selected)'''),
        {'id':payload.event_id,'cid':driver.company_id,'did':driver.id,
         'vid':vehicle.id if vehicle else None,'enabled':payload.notifications_enabled,'selected':selected})
    db.commit()
    return {'accepted':True,'duplicate':False}

@app.get('/api/v1/notification-audit')
def list_notification_audit(limit:int=500,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    limit=max(1,min(limit,500))
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    args={'limit':limit} if user.role=='super_admin' else {'limit':limit,'cid':user.company_id}
    rows=db.execute(text(f'''SELECT event_id,company_id,driver_id,vehicle_id,notifications_enabled,selected_at,received_at
        FROM mobile_notification_audit {where} ORDER BY received_at DESC LIMIT :limit'''),args).mappings().all()
    return [dict(row) for row in rows]

# Camera activity: metadata only, never audio, photographs or video.
with engine.begin() as _camera_conn:
    _camera_conn.execute(text("""CREATE TABLE IF NOT EXISTS mobile_safety_observation (
        event_id VARCHAR(90) PRIMARY KEY, company_id INTEGER NOT NULL,
        driver_id INTEGER NOT NULL, vehicle_id INTEGER,
        event_type VARCHAR(50) NOT NULL, speed_kmh FLOAT,
        observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
        received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    )"""))

class SafetyObservation(BaseModel):
    event_id: str = Field(min_length=8,max_length=90,pattern=r'^[a-zA-Z0-9_-]+$')
    event_type: str
    speed_kmh: float | None = None
    observed_at: datetime

@app.post('/api/v1/mobile/safety-observation')
def record_safety_observation(payload:SafetyObservation,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    # This only reports camera-in-use observations, NOT confirmed video calls.
    if payload.event_type!='possible_camera_use_driving':
        raise HTTPException(422,'Unsupported observation type')
    if payload.speed_kmh is None or not math.isfinite(payload.speed_kmh) or not 30<=payload.speed_kmh<=250:
        raise HTTPException(422,'Invalid speed')
    when=payload.observed_at
    if when.tzinfo is None:when=when.replace(tzinfo=timezone.utc)
    when=when.astimezone(timezone.utc)
    if not datetime.now(timezone.utc)-timedelta(days=7)<=when<=datetime.now(timezone.utc)+timedelta(minutes=5):
        raise HTTPException(422,'Invalid observation timestamp')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    existing=db.execute(text('SELECT driver_id FROM mobile_safety_observation WHERE event_id=:id'),{'id':payload.event_id}).first()
    if existing:
        if existing[0]!=driver.id:raise HTTPException(409,'Conflicting observation id')
        return {'accepted':True,'duplicate':True}
    db.execute(text("""INSERT INTO mobile_safety_observation (event_id,company_id,driver_id,vehicle_id,event_type,speed_kmh,observed_at)
      VALUES (:id,:company,:driver,:vehicle,:kind,:speed,:observed)"""),
      {'id':payload.event_id,'company':driver.company_id,'driver':driver.id,'vehicle':vehicle.id if vehicle else None,
       'kind':payload.event_type,'speed':payload.speed_kmh,'observed':when})
    db.commit()
    return {'accepted':True,'duplicate':False}

@app.get('/api/v1/safety-observations')
def list_safety_observations(limit:int=100,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    where='' if user.role=='super_admin' else 'WHERE company_id=:cid'
    params={'limit':max(1,min(500,limit))}
    if user.role!='super_admin':params['cid']=user.company_id
    return [dict(row) for row in db.execute(text(f"""SELECT event_id,company_id,driver_id,vehicle_id,event_type,speed_kmh,observed_at,received_at
      FROM mobile_safety_observation {where} ORDER BY received_at DESC LIMIT :limit"""),params).mappings()]

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

# Dashboard account recovery and self-service profile changes.
# All tokens are random, single-use and stored as SHA-256 digests only.
with engine.begin() as _account_conn:
    _account_conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_version INTEGER NOT NULL DEFAULT 0"))
    _account_conn.execute(text("""CREATE TABLE IF NOT EXISTS dashboard_account_tokens (
        id BIGSERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        purpose VARCHAR(24) NOT NULL, token_hash VARCHAR(64) NOT NULL UNIQUE,
        new_email VARCHAR(255), expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
        used_at TIMESTAMP WITH TIME ZONE, created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP
    )"""))
    _account_conn.execute(text("CREATE INDEX IF NOT EXISTS idx_dashboard_account_tokens_user ON dashboard_account_tokens(user_id, purpose, created_at)"))

def _dashboard_account(u:User):
    if u.role=='driver' or u.email.endswith('@login.nuqati.invalid'):
        raise HTTPException(403,'Dashboard account required')

def _send_account_mail(to_address:str,subject:str,body:str):
    host=os.environ.get('NUQATI_SMTP_HOST','')
    username=os.environ.get('NUQATI_SMTP_USER','')
    password=os.environ.get('NUQATI_SMTP_PASSWORD','')
    if not host or not username or not password:
        raise HTTPException(503,'Email delivery is not configured')
    msg=EmailMessage()
    msg['Subject']=subject
    msg['From']=f'Nuqati <{os.environ.get("NUQATI_EMAIL_FROM", "noreply@al-riadah.sa")}> '
    msg['To']=to_address
    msg.set_content(body)
    try:
        with smtplib.SMTP(host,int(os.environ.get('NUQATI_SMTP_PORT','587')),timeout=15) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            smtp.login(username,password)
            smtp.send_message(msg)
    except (OSError,smtplib.SMTPException) as exc:
        raise HTTPException(502,'Email delivery is unavailable. Please try later.') from exc

def _account_origin():
    origin=os.environ.get('NUQATI_PUBLIC_ORIGIN','').rstrip('/')
    if not origin.startswith('https://'):
        raise HTTPException(503,'Secure public dashboard URL is not configured')
    return origin

def _create_account_token(db:Session,user_id:int,purpose:str,new_email:str|None=None,minutes:int=30):
    raw=secrets.token_urlsafe(40)
    now=datetime.now(timezone.utc)
    db.execute(text("""UPDATE dashboard_account_tokens SET used_at=:now
        WHERE user_id=:uid AND purpose=:purpose AND used_at IS NULL"""),
        {'now':now,'uid':user_id,'purpose':purpose})
    db.execute(text("""INSERT INTO dashboard_account_tokens
        (user_id,purpose,token_hash,new_email,expires_at) VALUES (:uid,:purpose,:hash,:email,:expires)"""),
        {'uid':user_id,'purpose':purpose,'hash':hashlib.sha256(raw.encode()).hexdigest(),
         'email':new_email,'expires':now+timedelta(minutes=minutes)})
    return raw

class PasswordResetRequest(BaseModel):
    email:str=Field(min_length=3,max_length=255)

@app.post('/api/v1/auth/password-reset/request')
def request_dashboard_password_reset(payload:PasswordResetRequest,db:Session=Depends(get_db)):
    generic={'message':'If an eligible account exists, a reset link will be emailed.'}
    email=payload.email.strip().lower()
    user=db.scalar(select(User).where(User.email==email,User.is_active==True,User.role!='driver'))
    if not user:return generic
    latest=db.execute(text("""SELECT created_at FROM dashboard_account_tokens
      WHERE user_id=:uid AND purpose='password_reset' ORDER BY id DESC LIMIT 1"""),{'uid':user.id}).scalar()
    if latest:
        if latest.tzinfo is None:latest=latest.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc)-latest<timedelta(minutes=2):return generic
    origin=_account_origin()
    try:
        token=_create_account_token(db,user.id,'password_reset')
        from urllib.parse import quote
        url=origin+'/?reset='+quote(token)
        _send_account_mail(user.email,'Nuqati password reset | إعادة تعيين كلمة المرور',
            'A password reset was requested for your Nuqati dashboard account.\n'
            'Use this one-time link within 30 minutes: '+url+'\n\n'
            'If you did not request it, ignore this email.\n\n'
            'طلب إعادة تعيين كلمة مرور نقاطي. الرابط صالح لمدة 30 دقيقة: '+url)
        db.commit()
    except HTTPException:
        db.rollback()
        # Do not reveal account existence or mail delivery status to unauthenticated visitors.
    return generic

class PasswordResetConfirm(BaseModel):
    token:str=Field(min_length=30,max_length=200)
    new_password:str=Field(min_length=12,max_length=128)

@app.post('/api/v1/auth/password-reset/confirm')
def confirm_dashboard_password_reset(payload:PasswordResetConfirm,db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc)
    token_hash=hashlib.sha256(payload.token.encode()).hexdigest()
    row=db.execute(text("""SELECT id,user_id,expires_at,used_at FROM dashboard_account_tokens
      WHERE token_hash=:hash AND purpose='password_reset' FOR UPDATE"""),{'hash':token_hash}).mappings().first()
    if not row or row['used_at'] or (row['expires_at'].replace(tzinfo=timezone.utc) if row['expires_at'].tzinfo is None else row['expires_at'])<=now:
        raise HTTPException(400,'Invalid or expired reset link')
    user=db.get(User,row['user_id'])
    if not user or not user.is_active or user.role=='driver':raise HTTPException(400,'Invalid or expired reset link')
    user.password_hash=hash_password(payload.new_password)
    db.execute(text('UPDATE users SET auth_version=auth_version+1 WHERE id=:id'),{'id':user.id})
    db.execute(text('UPDATE dashboard_account_tokens SET used_at=:now WHERE user_id=:uid AND used_at IS NULL'),{'now':now,'uid':user.id})
    db.commit()
    return {'status':'password_changed'}

class ChangePasswordIn(BaseModel):
    current_password:str
    new_password:str=Field(min_length=12,max_length=128)

@app.post('/api/v1/account/password')
def change_dashboard_password(payload:ChangePasswordIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    _dashboard_account(user)
    if not verify_password(payload.current_password,user.password_hash):raise HTTPException(400,'Current password is incorrect')
    if verify_password(payload.new_password,user.password_hash):raise HTTPException(400,'Choose a different password')
    user.password_hash=hash_password(payload.new_password)
    now=datetime.now(timezone.utc)
    db.execute(text('UPDATE users SET auth_version=auth_version+1 WHERE id=:id'),{'id':user.id})
    db.execute(text('UPDATE dashboard_account_tokens SET used_at=:now WHERE user_id=:uid AND used_at IS NULL'),{'now':now,'uid':user.id})
    db.commit()
    return {'status':'password_changed','sign_in_again':True}

class EmailChangeRequest(BaseModel):
    current_password:str
    new_email:str=Field(min_length=3,max_length=255)

@app.post('/api/v1/account/email/request')
def request_dashboard_email_change(payload:EmailChangeRequest,db:Session=Depends(get_db),user:User=Depends(current_user)):
    _dashboard_account(user)
    if not verify_password(payload.current_password,user.password_hash):raise HTTPException(400,'Current password is incorrect')
    target=payload.new_email.strip().lower()
    if '@' not in target or target.startswith('@') or target.endswith('@') or ' ' in target:
        raise HTTPException(422,'Enter a valid email address')
    if target==user.email:raise HTTPException(400,'Email is unchanged')
    if db.scalar(select(User).where(User.email==target)):raise HTTPException(409,'Email already in use')
    now=datetime.now(timezone.utc)
    latest=db.execute(text("""SELECT created_at FROM dashboard_account_tokens
      WHERE user_id=:uid AND purpose='email_change' ORDER BY id DESC LIMIT 1"""),{'uid':user.id}).scalar()
    if latest:
        if latest.tzinfo is None:latest=latest.replace(tzinfo=timezone.utc)
        if now-latest<timedelta(minutes=2):raise HTTPException(429,'Please wait before requesting another email change')
    origin=_account_origin()
    token=_create_account_token(db,user.id,'email_change',target)
    from urllib.parse import quote
    url=origin+'/?confirm_email='+quote(token)
    try:
        _send_account_mail(target,'Verify your new Nuqati email | تأكيد البريد الجديد',
            'Please confirm this email address for your Nuqati account within 30 minutes: '+url+'\n'
            'If you did not request this, ignore this email.\n\n'
            'يرجى تأكيد بريد حساب نقاطي الجديد خلال 30 دقيقة: '+url)
    except HTTPException:
        db.rollback();raise
    db.commit()
    return {'status':'confirmation_sent'}

class EmailChangeConfirm(BaseModel):
    token:str=Field(min_length=30,max_length=200)

@app.post('/api/v1/auth/email-change/confirm')
def confirm_dashboard_email_change(payload:EmailChangeConfirm,db:Session=Depends(get_db)):
    now=datetime.now(timezone.utc)
    row=db.execute(text("""SELECT id,user_id,new_email,expires_at,used_at FROM dashboard_account_tokens
      WHERE token_hash=:hash AND purpose='email_change' FOR UPDATE"""),
      {'hash':hashlib.sha256(payload.token.encode()).hexdigest()}).mappings().first()
    if not row or row['used_at'] or (row['expires_at'].replace(tzinfo=timezone.utc) if row['expires_at'].tzinfo is None else row['expires_at'])<=now:
        raise HTTPException(400,'Invalid or expired confirmation link')
    user=db.get(User,row['user_id'])
    if not user or not user.is_active or user.role=='driver':raise HTTPException(400,'Invalid confirmation link')
    if db.scalar(select(User).where(User.email==row['new_email'])):raise HTTPException(409,'Email already in use')
    user.email=row['new_email']
    db.execute(text('UPDATE users SET auth_version=auth_version+1 WHERE id=:id'),{'id':user.id})
    db.execute(text('UPDATE dashboard_account_tokens SET used_at=:now WHERE user_id=:uid AND used_at IS NULL'),{'now':now,'uid':user.id})
    db.commit()
    return {'status':'email_changed','sign_in_again':True}

@app.post('/api/v1/auth/driver-phone-login')
def driver_phone_login(payload:DriverPhoneLogin,db:Session=Depends(get_db)):
    phone=normalize_phone(payload.phone)
    # Normalize legacy records in Python so existing drivers need no database migration.
    matches=[(d,u) for d,u in db.execute(select(Driver,User).join(DriverAccount,DriverAccount.driver_id==Driver.id).join(User,User.id==DriverAccount.user_id).where(User.role=='driver',User.is_active==True,Driver.status=='active')).all() if normalize_phone(d.phone)==phone]
    if len(matches)!=1 or not verify_password(payload.password,matches[0][1].password_hash):
        raise HTTPException(401,'Invalid phone or password; contact your fleet administrator')
    u=matches[0][1]
    return {'access_token':encode_token(u),'refresh_token':encode_token(u,refresh=True),'token_type':'bearer','user':user_view(u)}

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
    return {'access_token':encode_token(u),'refresh_token':encode_token(u,refresh=True),'token_type':'bearer','user':user_view(u)}

class DriverRefreshRequest(BaseModel):
    refresh_token: str

@app.post('/api/v1/auth/driver-refresh')
def driver_refresh(payload:DriverRefreshRequest, db:Session=Depends(get_db)):
    user=refresh_driver_session(payload.refresh_token,db)
    return {'access_token':encode_token(user),'refresh_token':encode_token(user,refresh=True),'token_type':'bearer'}

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
def list_odometer_readings(vehicle_id: int | None = None, source: str | None = None,
                           from_time: datetime | None = None, to_time: datetime | None = None,
                           db: Session = Depends(get_db), user:User=Depends(current_user)):
    if from_time is not None and to_time is not None and from_time > to_time:
        raise HTTPException(422, "Start date/time must be before end date/time")
    q=select(OdometerReading).order_by(OdometerReading.created_at.desc())
    if user.role!='super_admin': q=q.where(OdometerReading.company_id==user.company_id)
    if vehicle_id is not None: q=q.where(OdometerReading.vehicle_id==vehicle_id)
    if source is not None: q=q.where(OdometerReading.source==source)
    if from_time is not None: q=q.where(OdometerReading.created_at>=from_time)
    if to_time is not None: q=q.where(OdometerReading.created_at<=to_time)
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
    ensure_vehicle_tyre_schedules(db, v.company_id)
    db.commit()
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

# Driver maintenance and odometer operations use the authenticated assignment only.
# Keep the existing odometer and maintenance tables so dashboards stay in sync.
def _driver_vehicle(db: Session, user: User):
    driver = own_driver(db, user)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.company_id == driver.company_id, Vehicle.assigned_driver_id == driver.id))
    if not vehicle:
        raise HTTPException(404, 'No vehicle assigned to this driver')
    return driver, vehicle

class DriverOdometerSubmission(BaseModel):
    reading_km: float = Field(ge=0, le=3000000)

class DriverServiceCompletion(BaseModel):
    confirmed: bool
    reading_km: float = Field(ge=0, le=3000000)

@app.get('/api/v1/mobile/vehicle-care')
def mobile_vehicle_care(db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db, user)
    ensure_vehicle_tyre_schedules(db, vehicle.company_id)
    db.commit()
    schedules = db.scalars(select(MaintenanceSchedule).where(MaintenanceSchedule.company_id == vehicle.company_id, MaintenanceSchedule.vehicle_id == vehicle.id)).all()
    reminders = [maintenance_view(row, vehicle) for row in schedules]
    last_driver_reading = db.scalar(select(OdometerReading).where(OdometerReading.company_id == vehicle.company_id, OdometerReading.vehicle_id == vehicle.id, OdometerReading.source == 'DRIVER_MONTHLY').order_by(OdometerReading.created_at.desc(), OdometerReading.id.desc()).limit(1))
    now = datetime.now(timezone.utc)
    last_month = last_driver_reading.created_at if last_driver_reading else None
    monthly_due = last_month is None or (last_month.year, last_month.month) != (now.year, now.month)
    # A first-login odometer confirmation belongs to the driver, not to a
    # calendar month or a vehicle that may have had other assigned drivers.
    driver_reading = db.scalar(select(OdometerReading.id).where(
        OdometerReading.company_id == vehicle.company_id,
        OdometerReading.vehicle_id == vehicle.id,
        OdometerReading.source == 'DRIVER_MONTHLY',
        OdometerReading.note.like(f'Driver #{driver.id} %')
    ).limit(1))
    first_odometer_due = driver_reading is None
    return {'vehicle_id': vehicle.id, 'plate_number': vehicle.plate_number, 'odometer_km': vehicle.odometer_km,
            'first_odometer_due': first_odometer_due,
            'monthly_odometer_due': monthly_due,
            'last_driver_odometer_at': last_month.isoformat() if last_month else None,
            'maintenance': reminders,
            'initial_history_due': not bool(db.execute(text("SELECT 1 FROM driver_service_history WHERE vehicle_id=:v AND driver_id=:d LIMIT 1"), {'v':vehicle.id,'d':driver.id}).first()),
            'service_history': [dict(row) for row in db.execute(text("SELECT service_type,knowledge,reading_type,reading_km,interval_km,submitted_at FROM driver_service_history WHERE vehicle_id=:v AND driver_id=:d"), {'v':vehicle.id,'d':driver.id}).mappings().all()]}

# Driver-provided service history. Unknown answers are recorded, never guessed.
with engine.begin() as _history_conn:
    _history_conn.execute(text("""CREATE TABLE IF NOT EXISTS driver_service_history (
        vehicle_id INTEGER NOT NULL, driver_id INTEGER NOT NULL, company_id INTEGER NOT NULL,
        service_type VARCHAR(32) NOT NULL, knowledge VARCHAR(12) NOT NULL,
        reading_type VARCHAR(12), reading_km DOUBLE PRECISION, interval_km DOUBLE PRECISION,
        submitted_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(vehicle_id,driver_id,service_type))"""))

class DriverHistoryEntry(BaseModel):
    service_type: str
    knowledge: str = Field(pattern='^(KNOWN|UNKNOWN)$')
    reading_type: str | None = Field(default=None, pattern='^(LAST|NEXT)$')
    reading_km: float | None = Field(default=None, ge=0, le=3000000)
    oil_interval_km: int | None = None

class DriverHistorySubmission(BaseModel):
    odometer_km: float = Field(ge=0, le=3000000)
    services: list[DriverHistoryEntry] = Field(min_length=4, max_length=4)

@app.post('/api/v1/mobile/vehicle-care/initial-history')
def submit_driver_initial_history(payload: DriverHistorySubmission, db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db,user)
    provided={entry.service_type:entry for entry in payload.services}
    if len(provided)!=4 or set(provided)!=SERVICE_TYPES:
        raise HTTPException(422,'Please answer for all four services')
    if vehicle.odometer_km is not None and payload.odometer_km < vehicle.odometer_km:
        raise HTTPException(422,'Current odometer cannot be lower than recorded mileage')
    existing=db.execute(text('SELECT COUNT(*) FROM driver_service_history WHERE vehicle_id=:v AND driver_id=:d'),
        {'v':vehicle.id,'d':driver.id}).scalar() or 0
    if existing: raise HTTPException(409,'Initial service history already submitted for this driver and vehicle')
    defaults={'ENGINE_OIL':5000,'SPARK_PLUGS':60000,'TRANSMISSION_OIL':80000,'TYRES':60000}
    current_schedules={row.service_type:row for row in db.scalars(select(MaintenanceSchedule).where(MaintenanceSchedule.company_id==vehicle.company_id,MaintenanceSchedule.vehicle_id==vehicle.id)).all()}
    updates=[]
    for service,entry in provided.items():
        interval=(entry.oil_interval_km if service=='ENGINE_OIL' else current_schedules[service].interval_km if service in current_schedules else defaults[service])
        if service=='ENGINE_OIL' and entry.knowledge=='KNOWN' and interval not in (5000,10000):
            raise HTTPException(422,'Select 5,000 or 10,000 km oil interval')
        if entry.knowledge=='KNOWN':
            if entry.reading_type not in ('LAST','NEXT') or entry.reading_km is None:
                raise HTTPException(422,f'Provide last or next mileage for {service}')
            last=entry.reading_km if entry.reading_type=='LAST' else entry.reading_km-interval
            if last<0 or (entry.reading_type=='LAST' and last>payload.odometer_km):
                raise HTTPException(422,f'Invalid service mileage for {service}')
            updates.append((service,last,interval))
    vehicle.odometer_km=payload.odometer_km
    db.add(OdometerReading(company_id=vehicle.company_id,vehicle_id=vehicle.id,reading_km=payload.odometer_km,
        source='DRIVER_MONTHLY',note=f'Driver #{driver.id} initial odometer and service history'))
    for service,entry in provided.items():
        db.execute(text("""INSERT INTO driver_service_history
        (company_id,vehicle_id,driver_id,service_type,knowledge,reading_type,reading_km,interval_km)
        VALUES (:c,:v,:d,:s,:k,:t,:r,:i)"""),
        {'c':vehicle.company_id,'v':vehicle.id,'d':driver.id,'s':service,'k':entry.knowledge,
         't':entry.reading_type if entry.knowledge=='KNOWN' else None,
         'r':entry.reading_km if entry.knowledge=='KNOWN' else None,
         'i':(entry.oil_interval_km if service=='ENGINE_OIL' else current_schedules[service].interval_km if service in current_schedules else defaults[service]) if entry.knowledge=='KNOWN' else None})
    for service,last,interval in updates:
        schedule=db.scalar(select(MaintenanceSchedule).where(MaintenanceSchedule.vehicle_id==vehicle.id,
            MaintenanceSchedule.company_id==vehicle.company_id,MaintenanceSchedule.service_type==service))
        if schedule is None:
            db.add(MaintenanceSchedule(company_id=vehicle.company_id,vehicle_id=vehicle.id,
                service_type=service,interval_km=interval,last_service_km=last,warning_before_km=500 if service=='ENGINE_OIL' else 1000))
        else:
            schedule.last_service_km=last; schedule.interval_km=interval
    db.commit()
    return {'saved':True,'vehicle_id':vehicle.id,'known_services':len(updates),'unknown_services':4-len(updates)}

@app.get('/api/v1/maintenance/driver-history')
def dashboard_driver_history(vehicle_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    where='WHERE h.company_id=:company' if user.role!='super_admin' else 'WHERE 1=1'
    params={'company':user.company_id} if user.role!='super_admin' else {}
    if vehicle_id is not None:
        where+=' AND h.vehicle_id=:vehicle';params['vehicle']=vehicle_id
    rows=db.execute(text(f"""SELECT h.*,v.plate_number,d.full_name AS driver_name
        FROM driver_service_history h JOIN vehicles v ON v.id=h.vehicle_id
        JOIN drivers d ON d.id=h.driver_id {where} ORDER BY h.submitted_at DESC"""),params).mappings().all()
    return [dict(r) for r in rows]

@app.post('/api/v1/mobile/vehicle-care/odometer')
def mobile_driver_odometer(payload: DriverOdometerSubmission, db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db, user)
    if vehicle.odometer_km is not None and payload.reading_km < vehicle.odometer_km:
        raise HTTPException(422, 'Odometer cannot be lower than recorded mileage. Ask an administrator for an audited correction.')
    reading = OdometerReading(company_id=vehicle.company_id, vehicle_id=vehicle.id,
        reading_km=payload.reading_km, source='DRIVER_MONTHLY',
        note=f'Driver #{driver.id} monthly odometer confirmation')
    vehicle.odometer_km = payload.reading_km
    db.add(reading)
    db.commit()
    return {'saved': True, 'odometer_km': vehicle.odometer_km, 'reading_id': reading.id}

@app.post('/api/v1/mobile/vehicle-care/maintenance/{schedule_id}/complete')
def mobile_driver_service_complete(schedule_id: int, payload: DriverServiceCompletion, db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db, user)
    if not payload.confirmed:
        raise HTTPException(422, 'Driver confirmation required')
    schedule = db.scalar(select(MaintenanceSchedule).where(MaintenanceSchedule.id == schedule_id,
        MaintenanceSchedule.company_id == vehicle.company_id, MaintenanceSchedule.vehicle_id == vehicle.id))
    if schedule is None:
        raise HTTPException(404, 'Maintenance schedule not found for assigned vehicle')
    if vehicle.odometer_km is not None and payload.reading_km < vehicle.odometer_km:
        raise HTTPException(422, 'Service odometer cannot be lower than recorded vehicle mileage')
    previous = schedule.last_service_km
    schedule.last_service_km = payload.reading_km
    schedule.updated_at = datetime.now(timezone.utc)
    vehicle.odometer_km = payload.reading_km
    db.add(OdometerReading(company_id=vehicle.company_id, vehicle_id=vehicle.id,
        reading_km=payload.reading_km, source='SERVICE_COMPLETE',
        note=f'Driver #{driver.id} confirmed {schedule.service_type} service; previous baseline {previous:g} km; schedule #{schedule.id}'))
    db.commit()
    return {'saved': True, 'service_type': schedule.service_type, 'next_due_km': schedule.last_service_km + schedule.interval_km}

def ensure_vehicle_tyre_schedules(db: Session, company_id: int | None = None) -> None:
    """Create missing tyre schedules for existing vehicles, preserving every existing replacement record."""
    q = select(Vehicle)
    if company_id is not None:
        q = q.where(Vehicle.company_id == company_id)
    vehicles = list(db.scalars(q).all())
    if not vehicles:
        return
    ids = [vehicle.id for vehicle in vehicles]
    existing = set(db.scalars(select(MaintenanceSchedule.vehicle_id).where(
        MaintenanceSchedule.vehicle_id.in_(ids), MaintenanceSchedule.service_type == 'TYRES')).all())
    for vehicle in vehicles:
        if vehicle.id not in existing:
            # Registration is the best available tyre-age baseline for legacy vehicles.
            record = MaintenanceSchedule(company_id=vehicle.company_id, vehicle_id=vehicle.id,
                service_type='TYRES', interval_km=60000,
                last_service_km=vehicle.odometer_km or 0, warning_before_km=1000)
            first_reading = db.scalar(select(OdometerReading.created_at).where(
                OdometerReading.vehicle_id == vehicle.id).order_by(OdometerReading.created_at.asc()).limit(1))
            if first_reading is not None:
                record.updated_at = first_reading
            db.add(record)
    if len(existing) < len(vehicles):
        db.flush()


# Smart Oil Life Estimator: independent, read-only advisory.
# Never updates odometers, schedules, scores, or driver settings.
# The phone observes stationary GPS intervals, not actual ignition/engine hours.
@app.get('/api/v1/maintenance/smart-oil/{vehicle_id}')
def smart_oil_estimate(vehicle_id:int, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager', 'representative', 'workshop_staff')
    return _smart_oil_calculation(vehicle_id, db, user)

@app.get('/api/v1/mobile/smart-oil')
def driver_smart_oil(db:Session=Depends(get_db), user:User=Depends(current_user)):
    _, vehicle = _driver_vehicle(db, user)
    return _smart_oil_calculation(vehicle.id, db, user)

def _smart_oil_calculation(vehicle_id:int, db:Session, user:User):
    vehicle=db.get(Vehicle, vehicle_id)
    if not vehicle: raise HTTPException(404,'Vehicle not found')
    scope(user,vehicle.company_id)
    service=db.scalar(select(MaintenanceSchedule).where(
        MaintenanceSchedule.vehicle_id==vehicle.id,
        MaintenanceSchedule.company_id==vehicle.company_id,
        MaintenanceSchedule.service_type=='ENGINE_OIL'))
    basic={'vehicle_id':vehicle.id, 'plate_number':vehicle.plate_number,
           'make_model':vehicle.make_model, 'year':vehicle.year,
           'advisory_only':True, 'manufacturer_interval_verified':False,
           'manufacturer_guidance':'Confirm interval using the exact market-specific owner/warranty manual, engine, and oil grade.',
           'engine_hours_measured':False, 'driver_action_required':False}
    if not service or service.interval_km<=0 or vehicle.odometer_km is None:
        return {**basic,'status':'needs_existing_oil_schedule',
                'note':'An existing engine-oil schedule and odometer are needed; no schedule was created or changed.'}
    used_km=max(0., float(vehicle.odometer_km)-float(service.last_service_km))
    interval=float(service.interval_km)
    # Capped investigation scope; does not mutate data or alter trip processing.
    # Select newest trips first until we can approximate the distance since service.
    recent=db.scalars(select(Trip).where(Trip.vehicle_id==vehicle.id,
        Trip.company_id==vehicle.company_id,Trip.status=='completed',Trip.ended_at.is_not(None))
        .order_by(Trip.ended_at.desc(),Trip.id.desc()).limit(500)).all()
    selected=[]
    reconstructed_km=0.
    for t in recent:
        if reconstructed_km >= used_km+0.01: break
        d=max(0.,float(t.distance_km or 0))
        if d<0.01: continue
        fraction=min(1.,max(0.,used_km-reconstructed_km)/d)
        if fraction<=0:break
        selected.append((t.id,fraction,d))
        reconstructed_km+=d*fraction
    coverage=min(1.,reconstructed_km/used_km) if used_km>0 else 1.
    ids=[t[0] for t in selected]
    fractions={trip_id:part for trip_id,part,_ in selected}
    # Bound worst-case historical-data work. A truncated sample is identified as partial.
    points=[]
    if ids:
        points=db.scalars(select(DriverLocation).where(DriverLocation.trip_id.in_(ids),
            DriverLocation.company_id==vehicle.company_id)
            .order_by(DriverLocation.trip_id,DriverLocation.recorded_at,DriverLocation.id).limit(30001)).all()
    truncated=len(points)>30000
    points=points[:30000]
    idle_seconds=0.
    evaluated_seconds=0.
    valid_samples=0
    previous={}
    for p in points:
        if (p.accuracy_m is None or p.accuracy_m>20 or
            p.speed_kmh is None or p.speed_kmh<0 or p.speed_kmh>180):
            previous.pop(p.trip_id,None)
            continue
        valid_samples+=1
        before=previous.get(p.trip_id)
        previous[p.trip_id]=p
        if before is None:continue
        t1=before.recorded_at;t2=p.recorded_at
        if t1.tzinfo is None:t1=t1.replace(tzinfo=timezone.utc)
        if t2.tzinfo is None:t2=t2.replace(tzinfo=timezone.utc)
        dt=(t2-t1).total_seconds()
        if not (5<=dt<=90):continue
        scale=fractions.get(p.trip_id,0.)
        evaluated_seconds+=dt*scale
        if p.speed_kmh<=3 and before.speed_kmh<=3:
            # Short-range displacement check rejects obvious GPS jumps at zero speed.
            a1=math.radians(before.latitude);a2=math.radians(p.latitude)
            da=a2-a1;dl=math.radians(p.longitude-before.longitude)
            hav=math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2
            displaced=6371000.*2*math.asin(min(1.,math.sqrt(max(0.,hav))))
            if displaced<=max(20.,min(50.,dt*.8)):
                idle_seconds+=dt*scale
    # Conversion is a pilot assumption, not a dealer-approved engine-hour equivalence.
    factor=40.
    additional_km=round(idle_seconds/3600*factor,1)
    equivalent_km=round(used_km+additional_km,1)
    advisory_remaining=round(interval-equivalent_km,1)
    distance_coverage=round(coverage*100.,1)
    sufficient=bool(used_km<=0 or (coverage>=.8 and valid_samples>=10 and evaluated_seconds>=60 and not truncated))
    return {**basic,'status':'estimate_available' if sufficient else 'limited_data',
            'last_service_km':float(service.last_service_km),
            'current_odometer_km':float(vehicle.odometer_km),
            'configured_interval_km':interval,
            'original_next_due_km':float(service.last_service_km)+interval,
            'distance_since_service_km':round(used_km,1),
            'gps_stationary_hours':round(idle_seconds/3600,2),
            'gps_observed_hours':round(evaluated_seconds/3600,2),
            'gps_sample_count':valid_samples,
            'trip_distance_coverage_pct':distance_coverage,
            'history_truncated':truncated or len(recent)==500 and coverage<1.,
            'pilot_equivalent_km_per_stationary_hour':factor,
            'pilot_extra_usage_km':additional_km,
            'pilot_equivalent_usage_km':equivalent_km,
            'pilot_allowance_remaining_km':advisory_remaining,
            'pilot_advisory':'Possible early oil service review' if sufficient and advisory_remaining<=float(service.warning_before_km) else 'Monitoring / insufficient data' if not sufficient else 'No earlier review indicated',
            'note':'GPS-observed stationary time can include engine-off stops and excludes idling outside recorded trips. Estimates are not actual engine hours or validated oil-life measurements.'}

@app.get("/api/v1/maintenance-schedules", response_model=list[MaintenanceScheduleOut])
def list_maintenance(db: Session = Depends(get_db), user:User=Depends(current_user)):
    q=select(MaintenanceSchedule).order_by(MaintenanceSchedule.vehicle_id, MaintenanceSchedule.service_type)
    if user.role!='super_admin': q=q.where(MaintenanceSchedule.company_id==user.company_id)
    ensure_vehicle_tyre_schedules(db, None if user.role=='super_admin' else user.company_id)
    db.commit()
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
    year: int | None = Field(default=None,ge=1900,le=2100)
    door_number: str | None = Field(default=None,max_length=40)
    assigned_driver_id: int | None = None

@app.patch('/api/v1/vehicles/{vehicle_id}',response_model=VehicleOut)
def edit_vehicle(vehicle_id:int,payload:VehicleEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin');row=db.get(Vehicle,vehicle_id)
    if not row: raise HTTPException(404,'Vehicle not found')
    scope(user,row.company_id)
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
    return {'driver_id':d.id,'full_name':d.full_name,'company_id':d.company_id,'company_name':db.get(Company,d.company_id).name if db.get(Company,d.company_id) else '', 'vehicle':{'id':v.id,'plate_number':v.plate_number,'make_model':v.make_model,'year':v.year,'door_number':v.door_number} if v else None}

# Company driver-app logos: keep one setting per company without altering fleet data.
# Dashboard and mobile clients already depend on these routes.
class CompanyDriverLogoIn(BaseModel):
    logo_data: str = Field(default='', max_length=300000)

def _company_logo_setting(company_id: int) -> str:
    return f'company_driver_logo:{company_id}'

def _company_driver_logo(db: Session, company_id: int) -> str:
    row = db.get(AppSetting, _company_logo_setting(company_id))
    if not row:
        return ''
    # Existing records may store a simple data URL or an object.
    value = row.value or ''
    if value.startswith('data:image/'):
        return value
    try:
        return str(json.loads(value).get('logo_data', ''))
    except (ValueError, TypeError, AttributeError):
        return ''

@app.get('/api/v1/companies/{company_id}/driver-logo')
def get_company_driver_logo(company_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager', 'representative', 'workshop_staff')
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, 'Company not found')
    if user.role != 'super_admin' and user.company_id != company_id:
        raise HTTPException(403, 'Company access denied')
    return {'company_id': company_id, 'logo_data': _company_driver_logo(db, company_id)}

@app.put('/api/v1/companies/{company_id}/driver-logo')
def put_company_driver_logo(company_id: int, payload: CompanyDriverLogoIn,
                            db: Session = Depends(get_db), user: User = Depends(current_user)):
    import base64, binascii
    allow(user, 'super_admin', 'company_admin')
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, 'Company not found')
    if user.role != 'super_admin' and user.company_id != company_id:
        raise HTTPException(403, 'Company access denied')
    value = payload.logo_data
    if value:
        valid_prefixes = ('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')
        prefix = next((item for item in valid_prefixes if value.startswith(item)), None)
        if prefix is None:
            raise HTTPException(422, 'Use a PNG, JPEG or WebP logo')
        try:
            image_bytes = base64.b64decode(value[len(prefix):], validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Invalid logo encoding')
        if len(image_bytes) > 220000 or not image_bytes:
            raise HTTPException(422, 'Logo must be under 220 KB')
        # Verify actual file signatures, not just the claimed MIME type.
        valid_image = ((prefix.startswith('data:image/png') and image_bytes.startswith(b'\x89PNG\r\n\x1a\n')) or
                       (prefix.startswith('data:image/jpeg') and image_bytes.startswith(b'\xff\xd8\xff')) or
                       (prefix.startswith('data:image/webp') and image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP'))
        if not valid_image:
            raise HTTPException(422, 'Logo format does not match file content')
    key = _company_logo_setting(company_id)
    record = db.get(AppSetting, key)
    if record is None:
        db.add(AppSetting(key=key, value=json.dumps({'logo_data': value})))
    else:
        record.value = json.dumps({'logo_data': value})
    db.commit()
    return {'company_id': company_id, 'status': 'saved', 'logo_data': value}

@app.get('/api/v1/mobile/branding')
def mobile_company_branding(db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver = own_driver(db, user)
    company = db.get(Company, driver.company_id)
    return {'company_id': driver.company_id,
            'company_name': company.name if company else '',
            'logo_data': _company_driver_logo(db, driver.company_id)}

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
    vehicle_ids: list[int] | None = None  # None = all vehicles in this company

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

# Driver-only, per-vehicle geofence policy for on-device coaching.
def _driver_geofence_rules(db, driver):
    vehicle=db.scalar(select(Vehicle).where(Vehicle.company_id==driver.company_id,Vehicle.assigned_driver_id==driver.id))
    if vehicle is None:
        return []
    return [{'id':z['id'],'name':z['name'],'latitude':z['latitude'],'longitude':z['longitude'],
             'radius_m':z['radius_m'],'mode':z.get('mode','normal'),'speed_limit_kmh':z.get('speed_limit_kmh')}
            for z in phase4_zones(db,driver.company_id)
            if z.get('vehicle_ids') is None or vehicle.id in z['vehicle_ids']]

@app.get('/api/v1/fleet/geofence-crossings')
def geofence_crossings(company_id:int|None=None,driver_id:int|None=None,zone_id:str|None=None,
                       start_at:datetime|None=None,end_at:datetime|None=None,limit:int=500,
                       db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=_company_for_policy(db,user,company_id)
    end=end_at or datetime.now(timezone.utc)
    start=start_at or end-timedelta(days=7)
    if start.tzinfo is None or end.tzinfo is None: raise HTTPException(422,'Use timezone-aware dates')
    if start>=end or end-start>timedelta(days=31):raise HTTPException(422,'Choose a valid range up to 31 days')
    if driver_id is not None and not db.scalar(select(Driver.id).where(Driver.company_id==cid,Driver.id==driver_id)):
        raise HTTPException(404,'Driver not found in company')
    zones=[z for z in phase4_zones(db,cid) if zone_id is None or z['id']==zone_id]
    if zone_id is not None and not zones:raise HTTPException(404,'Geofence not found')
    limit=max(1,min(limit,2000))
    # Reconstruct named crossings from persisted GPS samples. Do not infer crossings across GPS gaps.
    query=select(DriverLocation).where(DriverLocation.company_id==cid,DriverLocation.recorded_at>=start,
                    DriverLocation.recorded_at<=end,DriverLocation.accuracy_m>0,DriverLocation.accuracy_m<=25)
    if driver_id is not None:query=query.where(DriverLocation.driver_id==driver_id)
    samples=list(db.scalars(query.order_by(DriverLocation.driver_id,DriverLocation.trip_id,DriverLocation.recorded_at,DriverLocation.id).limit(60001)).all())
    truncated=len(samples)>60000
    if truncated:samples=samples[:60000]
    sample_trip_ids={x.trip_id for x in samples}
    trips={t.id:t for t in db.scalars(select(Trip).where(Trip.company_id==cid,Trip.id.in_(sample_trip_ids))).all()} if sample_trip_ids else {}
    driver_names={d.id:d.full_name for d in db.scalars(select(Driver).where(Driver.company_id==cid)).all()}
    plates={v.id:v.plate_number for v in db.scalars(select(Vehicle).where(Vehicle.company_id==cid)).all()}
    result=[];prev={}
    for point in samples:
        key=(point.driver_id,point.trip_id)
        before=prev.get(key);prev[key]=point
        if before is None:continue
        elapsed=(point.recorded_at-before.recorded_at).total_seconds()
        if elapsed<=0 or elapsed>120:continue
        trip=trips.get(point.trip_id)
        if trip is None:continue
        for z in zones:
            if z.get('vehicle_ids') is not None and trip.vehicle_id not in z['vehicle_ids']:continue
            was=_distance_m(before.latitude,before.longitude,z['latitude'],z['longitude'])<=z['radius_m']
            now=_distance_m(point.latitude,point.longitude,z['latitude'],z['longitude'])<=z['radius_m']
            if was==now:continue
            result.append({'event':'entry' if now else 'exit','zone_id':z['id'],'zone_name':z['name'],
                           'driver_id':point.driver_id,'driver_name':driver_names.get(point.driver_id,'—'),
                           'vehicle_id':trip.vehicle_id,'plate_number':plates.get(trip.vehicle_id,'—'),
                           'trip_id':point.trip_id,'time':point.recorded_at.isoformat(),
                           'speed_kmh':round(point.speed_kmh,1),'latitude':point.latitude,'longitude':point.longitude,
                           'speed_limit_kmh':z.get('speed_limit_kmh')})
    result.sort(key=lambda r:r['time'],reverse=True)
    return {'events':result[:limit],'truncated':truncated or len(result)>limit,'sample_count':len(samples),
            'start_at':start.isoformat(),'end_at':end.isoformat(),'reconstruction':True}

@app.get('/api/v1/mobile/driving-policy')
def mobile_driving_policy(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);t=thresholds(db,d.company_id)
    payload={'company_id':d.company_id,'speeding_kmh':t.speeding_kmh,'harsh_accel_ms2':t.harsh_accel_ms2,
            'harsh_brake_ms2':t.harsh_brake_ms2,'excessive_speed_margin_kmh':score_policy(db,d.company_id)['excessive_speed_margin_kmh'],**severity_settings(db,d.company_id),**event_policy(db,d.company_id), 'phase4': phase4_settings(db,d.company_id), 'geofence_speed_zones': _driver_geofence_rules(db,d)}
    payload['policy_version']=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()[:20]
    return payload

class MobilePolicyAckIn(BaseModel):
    policy_version: str = Field(min_length=20,max_length=20,pattern=r'^[0-9a-f]{20}$')

@app.post('/api/v1/mobile/driving-policy/ack')
def acknowledge_mobile_driving_policy(data:MobilePolicyAckIn,db:Session=Depends(get_db),user:User=Depends(current_user)):
    driver=own_driver(db,user)
    current=mobile_driving_policy(db,user)
    if data.policy_version!=current['policy_version']:
        raise HTTPException(409,'Policy has changed; refresh before acknowledging')
    key=f'driving_policy_ack:{driver.company_id}:{driver.id}'
    row=db.get(AppSetting,key)
    if row is None:
        row=AppSetting(key=key,value='{}');db.add(row)
    row.value=json.dumps({'version':data.policy_version,'received_at':datetime.now(timezone.utc).isoformat()})
    db.commit()
    return {'acknowledged':True,'policy_version':data.policy_version}

@app.get('/api/v1/fleet/driving-policy/ack')
def driving_policy_ack_status(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None or not db.get(Company,cid):raise HTTPException(422,'Choose a valid company')
    scope(user,cid)
    policy_version=None
    # Use the same policy serialization as the mobile endpoint, without a driver login.
    t=thresholds(db,cid)
    payload={'speeding_kmh':t.speeding_kmh,'harsh_accel_ms2':t.harsh_accel_ms2,
             'harsh_brake_ms2':t.harsh_brake_ms2,**event_policy(db,cid),'phase4':phase4_settings(db,cid)}
    policy_version=hashlib.sha256(json.dumps(payload,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()[:20]
    rows=[]
    for driver in db.scalars(select(Driver).where(Driver.company_id==cid)).all():
        record=db.get(AppSetting,f'driving_policy_ack:{cid}:{driver.id}')
        try: ack=json.loads(record.value) if record else {}
        except (ValueError,TypeError):ack={}
        rows.append({'driver_id':driver.id,'driver_name':driver.full_name,
                     'acknowledged_version':ack.get('version'), 'received_at':ack.get('received_at'),
                     'status':'received' if ack.get('version')==policy_version else 'pending'})
    return {'company_id':cid,'policy_version':policy_version,'drivers':rows}



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

@app.get('/api/v1/mobile/trips/sync-state')
def mobile_trip_sync_state(db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Authoritative driver-scoped trip state. IDs are allocated only by PostgreSQL."""
    d=own_driver(db,user)
    latest=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id).order_by(Trip.id.desc()).limit(1))
    active=db.scalar(select(Trip).where(Trip.driver_id==d.id,Trip.company_id==d.company_id,Trip.status=='active').order_by(Trip.id.desc()).limit(1))
    return {'latest_trip_id':latest.id if latest else None,
            'latest_trip_status':latest.status if latest else None,
            'active_trip_id':active.id if active else None,
            'server_assigns_trip_ids':True}

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
    if not trip or trip.driver_id!=d.id or trip.company_id!=d.company_id: raise HTTPException(404,'Trip not found')
    if trip.status not in ('active','completed'): raise HTTPException(409,'Trip is not eligible for GPS samples')
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

    if trip.status=='completed':
        # Historical uploads must belong to this completed journey, not a newer trip.
        # Keep the trip, score, distance and already-posted odometer unchanged.
        def as_utc(value):
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
        if not trip.ended_at or captured<as_utc(trip.started_at)-timedelta(seconds=30) or captured>as_utc(trip.ended_at)+timedelta(seconds=30):
            raise HTTPException(422,'GPS capture time outside completed trip interval')
        # Legacy samples without IDs cannot be reliably deduplicated on retry.
        # Require stable IDs for completed-trip uploads to avoid duplicate history.
        if not data.sample_id:
            raise HTTPException(422,'sample_id required for completed trip replay')
        db.add(DriverLocation(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,
            latitude=data.latitude,longitude=data.longitude,accuracy_m=data.accuracy_m,
            speed_kmh=data.speed_kmh,recorded_at=captured))
        db.execute(text('INSERT INTO mobile_gps_sample_receipts (trip_id,sample_id,captured_at) VALUES (:t,:s,:c)'),
            {'t':trip.id,'s':data.sample_id,'c':captured})
        db.commit()
        return {'accepted':True,'historical':True,'events':[],'rejected_events':{}}

    previous=db.scalar(select(DriverLocation).where(DriverLocation.trip_id==trip.id).order_by(DriverLocation.id.desc()).limit(1))
    if previous:
        previous_at = previous.recorded_at.replace(tzinfo=timezone.utc) if previous.recorded_at.tzinfo is None else previous.recorded_at.astimezone(timezone.utc)
        elapsed_since_previous = (captured - previous_at).total_seconds()
        if elapsed_since_previous < 0:
            raise HTTPException(422, 'GPS sample older than latest accepted sample; upload oldest first')
        if elapsed_since_previous < 0.7:
            # A sub-700ms sample is a redundant GPS fix, not a transient HTTP rate limit.
            # Acknowledge its stable ID without double-counting distance or events.
            if data.sample_id:
                db.execute(text('INSERT INTO mobile_gps_sample_receipts (trip_id,sample_id,captured_at) VALUES (:t,:s,:c) ON CONFLICT (trip_id,sample_id) DO NOTHING'),
                           {'t':trip.id,'s':data.sample_id,'c':captured})
                db.commit()
            return {'accepted':True,'duplicate':True,'filtered_short_interval':True,'events':[],'rejected_events':{}}
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
    # Confirm accelerometer-like GPS speed delta independently; a single GPS speed
    # glitch or a large gap must not deduct driver points.
    if previous:
        delta=(captured-previous.recorded_at.replace(tzinfo=timezone.utc)).total_seconds()
        prev_speed=previous.speed_kmh or 0.0
        if 0.7 <= delta <= 5 and previous.accuracy_m <= 20 and data.accuracy_m <= 20 and max(prev_speed,data.speed_kmh)>=15:
            derived=(data.speed_kmh-prev_speed)/3.6/delta
            kinds=[(kind,value) for kind,value in kinds if kind not in ('harsh_braking','harsh_acceleration') or (kind=='harsh_braking' and derived<=-cfg.harsh_brake_ms2 and abs(derived-data.acceleration_ms2)<=2.0) or (kind=='harsh_acceleration' and derived>=cfg.harsh_accel_ms2 and abs(derived-data.acceleration_ms2)<=2.0)]
        else:
            kinds=[(kind,value) for kind,value in kinds if kind not in ('harsh_braking','harsh_acceleration')]
    else:
        kinds=[(kind,value) for kind,value in kinds if kind not in ('harsh_braking','harsh_acceleration')]
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

# Stable receipts for locally detected events. Each receipt is scoped to the authenticated driver.
with engine.begin() as _conn:
    _conn.execute(text("""CREATE TABLE IF NOT EXISTS mobile_safety_event_receipts (
        driver_id INTEGER NOT NULL, event_id VARCHAR(160) NOT NULL,
        trip_id INTEGER NOT NULL, PRIMARY KEY(driver_id,event_id))"""))

class LocalSafetyEvent(BaseModel):
    event_id: str = Field(min_length=8,max_length=160)
    event_type: str
    recorded_at: datetime
    value: float | None = None

@app.post('/api/v1/mobile/trips/{trip_id}/safety-event')
def sync_mobile_safety_event(trip_id:int,data:LocalSafetyEvent,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user);trip=db.get(Trip,trip_id)
    if not trip or trip.driver_id!=d.id or trip.company_id!=d.company_id:
        raise HTTPException(404,'Trip not found')
    kinds={'speeding','excessive_speeding','harsh_braking','excessive_harsh_braking',
           'harsh_acceleration','excessive_harsh_acceleration','harsh_cornering'}
    if data.event_type not in kinds:raise HTTPException(422,'Unsupported safety event')
    captured=data.recorded_at
    if captured.tzinfo is None:captured=captured.replace(tzinfo=timezone.utc)
    captured=captured.astimezone(timezone.utc)
    if captured>datetime.now(timezone.utc)+timedelta(seconds=30) or captured<datetime.now(timezone.utc)-timedelta(days=14):
        raise HTTPException(422,'Event timestamp outside sync window')
    if captured<trip.started_at.replace(tzinfo=timezone.utc)-timedelta(seconds=30):
        raise HTTPException(422,'Event before trip')
    receipt=db.execute(text('SELECT 1 FROM mobile_safety_event_receipts WHERE driver_id=:d AND event_id=:e'),{'d':d.id,'e':data.event_id}).first()
    if receipt:return {'accepted':True,'duplicate':True}
    # Only accept events anchored to actual GPS data already uploaded by this driver.
    point=db.scalar(select(DriverLocation).where(DriverLocation.trip_id==trip.id,
        DriverLocation.recorded_at>=captured-timedelta(seconds=5),
        DriverLocation.recorded_at<=captured+timedelta(seconds=5)).order_by(DriverLocation.id.desc()).limit(1))
    if point is None:raise HTTPException(422,{'code':'GPS_ANCHOR_MISSING','message':'No matching GPS sample within 5 seconds','event_id':data.event_id})
    base=data.event_type.removeprefix('excessive_')
    settings=thresholds(db,d.company_id)
    if base=='speeding' and point.speed_kmh<=settings.speeding_kmh:
        # Acknowledge the mobile observation without adding an invalid backend violation.
        # Prevents a permanently unmatchable speed event from blocking all later uploads.
        db.execute(text('INSERT INTO mobile_safety_event_receipts(driver_id,event_id,trip_id) VALUES (:d,:e,:t)'),
                   {'d':d.id,'e':data.event_id,'t':trip.id})
        db.commit()
        return {'accepted':True,'recorded':False,'reason':'SPEED_BELOW_SERVER_THRESHOLD'}
    if base=='harsh_cornering' and point.speed_kmh<phase4_settings(db,d.company_id)['min_cornering_speed_kmh']:
        raise HTTPException(422,'Cornering below minimum speed')
    if data.value is not None and (not math.isfinite(data.value) or data.value<0 or data.value>350):
        raise HTTPException(422,'Invalid event value')
    # A backend-derived event in the same 30-second window is the same incident.
    existing=db.scalar(select(DrivingEvent).where(DrivingEvent.trip_id==trip.id,
        DrivingEvent.event_type==base,
        DrivingEvent.recorded_at>=captured-timedelta(seconds=15),
        DrivingEvent.recorded_at<=captured+timedelta(seconds=15)).order_by(DrivingEvent.id.desc()).limit(1))
    if not existing:
        db.add(DrivingEvent(company_id=d.company_id,driver_id=d.id,trip_id=trip.id,
            event_type=base,value=data.value or 0.0,latitude=point.latitude,
            longitude=point.longitude,recorded_at=captured))
    db.execute(text('INSERT INTO mobile_safety_event_receipts(driver_id,event_id,trip_id) VALUES (:d,:e,:t)'),
               {'d':d.id,'e':data.event_id,'t':trip.id})
    db.commit()
    return {'accepted':True,'matched_existing':bool(existing)}

# Administrative recovery: does not fabricate GPS data or restart the driver's device.
class AdminTripEnd(BaseModel):
    reason: str = Field(min_length=8,max_length=500)

with engine.begin() as _force_end_conn:
    _force_end_conn.execute(text("""CREATE TABLE IF NOT EXISTS admin_trip_end_audit (
      id BIGSERIAL PRIMARY KEY, trip_id INTEGER NOT NULL, company_id INTEGER NOT NULL,
      performed_by INTEGER NOT NULL, reason TEXT NOT NULL,
      performed_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP)"""))

@app.post('/api/v1/fleet/trips/{trip_id}/force-end')
def force_end_fleet_trip(trip_id:int,payload:AdminTripEnd,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    trip=db.scalar(select(Trip).where(Trip.id==trip_id).with_for_update())
    if not trip:raise HTTPException(404,'Trip not found')
    if user.role!='super_admin' and trip.company_id!=user.company_id:
        raise HTTPException(403,'Trip belongs to another company')
    if trip.status!='active':raise HTTPException(409,'Only active trips may be force-ended')
    vehicle=db.scalar(select(Vehicle).where(Vehicle.id==trip.vehicle_id).with_for_update())
    if not vehicle:raise HTTPException(404,'Vehicle not found')
    now=datetime.now(timezone.utc)
    trip.ended_at=max(now,trip.started_at.replace(tzinfo=timezone.utc))
    trip.status='completed'
    added=max(0.0,trip.distance_km or 0.0)
    if vehicle.odometer_km is not None and added>0:
        vehicle.odometer_km+=added
        db.add(OdometerReading(company_id=vehicle.company_id,vehicle_id=vehicle.id,reading_km=vehicle.odometer_km,source='GPS_TRIP',note=f'Admin-ended trip #{trip.id}: +{added:.3f} km'))
    db.execute(text('INSERT INTO admin_trip_end_audit(trip_id,company_id,performed_by,reason) VALUES (:t,:c,:u,:r)'),
      {'t':trip.id,'c':trip.company_id,'u':user.id,'r':payload.reason.strip()})
    db.commit()
    return {'trip_id':trip.id,'status':'completed','ended_by_admin':True,'distance_km':added,
            'warning':'This does not remotely stop the Android GPS service. The driver must reconcile server trip state.'}

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

# Precise historical search uses server-side company authorization and UTC timestamps.
@app.get('/api/v1/fleet/trips/search')
def search_fleet_trips(start_at:datetime,end_at:datetime,company_id:int|None=None,driver_id:int|None=None,vehicle_id:int|None=None,limit:int=500,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff','driver')
    cid=company_id if user.role=='super_admin' else user.company_id
    if cid is None: raise HTTPException(422,'Select a company')
    scope(user,cid)
    if start_at.tzinfo is None or end_at.tzinfo is None:raise HTTPException(422,'Timezone offsets required')
    start_at=start_at.astimezone(timezone.utc);end_at=end_at.astimezone(timezone.utc)
    if end_at<=start_at or end_at-start_at>timedelta(days=366):raise HTTPException(422,'Select a positive interval of at most 366 days')
    if driver_id is not None:
        driver=db.get(Driver,driver_id)
        if not driver or driver.company_id!=cid:raise HTTPException(404,'Driver not found')
    if vehicle_id is not None:
        vehicle=db.get(Vehicle,vehicle_id)
        if not vehicle or vehicle.company_id!=cid:raise HTTPException(404,'Vehicle not found')
    if user.role=='driver':
        own=own_driver(db,user)
        if driver_id is not None and driver_id!=own.id:raise HTTPException(403,'Own trips only')
        driver_id=own.id
    limit=max(1,min(limit,2000))
    query=select(Trip).where(Trip.company_id==cid,Trip.started_at>=start_at,Trip.started_at<=end_at)
    if driver_id is not None:query=query.where(Trip.driver_id==driver_id)
    if vehicle_id is not None:query=query.where(Trip.vehicle_id==vehicle_id)
    rows=list(db.scalars(query.order_by(Trip.started_at.asc(),Trip.id.asc()).limit(limit+1)).all())
    truncated=len(rows)>limit
    rows=rows[:limit]
    names={d.id:d.full_name for d in db.scalars(select(Driver).where(Driver.company_id==cid)).all()}
    # Historical event counts are scoped to the already-authorized trip IDs.
    # Do not infer violations from speed samples or from the report period.
    trip_ids=[t.id for t in rows]
    event_counts={}
    if trip_ids:
        for tid,count in db.execute(select(DrivingEvent.trip_id,func.count(DrivingEvent.id)).where(DrivingEvent.trip_id.in_(trip_ids)).group_by(DrivingEvent.trip_id)):
            event_counts[tid]=count
    return {'company_id':cid,'start_at':start_at.isoformat(),'end_at':end_at.isoformat(),'truncated':truncated,'trips':[{'id':t.id,'driver_id':t.driver_id,'driver_name':names.get(t.driver_id,'Unknown'),'vehicle_id':t.vehicle_id,'started_at':t.started_at.isoformat(),'ended_at':t.ended_at.isoformat() if t.ended_at else None,'status':t.status,'distance_km':t.distance_km,'event_count':event_counts.get(t.id,0)} for t in rows]}

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
        events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.driver_id==d.id,DrivingEvent.recorded_at>=since,DrivingEvent.trip_id.in_(select(Trip.id).where(Trip.status=='completed')))).all())
        counts={k:sum(e.event_type==k for e in events) for k in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')}
        km=sum(max(0,t.distance_km or 0) for t in trips if t.status=='completed')
        breakdown=calculate_safety_score(events,km,score_policy(db,cid),thresholds(db,cid).speeding_kmh,db=db,trips=[t for t in trips if t.status=='completed'],flexible_policy=flexible_rag_policy(db,cid))
        score=breakdown['score']
        loc=db.scalar(select(DriverLocation).where(DriverLocation.company_id==cid,DriverLocation.driver_id==d.id).order_by(DriverLocation.id.desc()).limit(1))
        output.append({'driver_id':d.id,'driver_name':d.full_name,'trips':len(trips),'score':score,'score_model':breakdown.get('score_model','legacy_100'),'risk':breakdown['risk'],'score_breakdown':breakdown,'violations':counts,'latest_location':{'latitude':loc.latitude,'longitude':loc.longitude,'recorded_at':loc.recorded_at.isoformat(),'accuracy_m':loc.accuracy_m} if loc else None,'trip_details':[{'id':t.id,'vehicle_id':t.vehicle_id,'started_at':t.started_at.isoformat(),'ended_at':t.ended_at.isoformat() if t.ended_at else None,'status':t.status,'distance_km':t.distance_km,'max_speed_kmh':db.scalar(select(func.max(DriverLocation.speed_kmh)).where(DriverLocation.trip_id==t.id,DriverLocation.accuracy_m<=100,DriverLocation.speed_kmh>=0,DriverLocation.speed_kmh<=350)),'violations':[{'type':e.event_type,'value':e.value,'recorded_at':e.recorded_at.isoformat()} for e in events if e.trip_id==t.id]} for t in trips]})
    scores=[x['score'] for x in output if x['score'] is not None]
    return {'company_id':cid,'period':period,'from':since.isoformat(),'driver_count':len(output),'trip_count':sum(x['trips'] for x in output),'average_score':round(sum(scores)/len(scores),2) if scores else None,'score_model':'flexible_rag' if flexible_rag_policy(db,cid)['enabled'] else 'legacy_100','drivers':output}


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
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.company_id==cid,DrivingEvent.recorded_at>=start,DrivingEvent.recorded_at<end,DrivingEvent.trip_id.in_(select(Trip.id).where(Trip.status=='completed')))).all())
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
        score=calculate_safety_score(ev,km,policy,speed_limit,db=db,trips=dt,flexible_policy=flexible_rag_policy(db,cid))
        counts['excessive_speeding']=score['categories']['excessive_speeding']
        # Excessive speeding is a subset of speeding, not an additional violation.
        rag=score.get('rag','').capitalize() if score['score'] is not None and score.get('score_model')=='flexible_rag' else ('Green' if score['score'] is not None and score['score']>=90 else 'Amber' if score['score'] is not None and score['score']>=60 else 'Red' if score['score'] is not None else 'No data')
        by_vehicle=[]
        for v in vehicles:
            subset=[t for t in dt if t.vehicle_id==v.id]
            if subset:by_vehicle.append({'vehicle_id':v.id,'plate_number':v.plate_number,'trips':len(subset),'distance_km':round(sum(max(0,t.distance_km or 0) for t in subset),2),'driving_hours':round(sum(max(0,(t.ended_at-t.started_at).total_seconds()) for t in subset if t.ended_at and t.started_at)/3600,2)})
        rows.append({'driver_id':d.id,'driver_name':d.full_name,'trip_count':len(dt),'distance_km':round(km,2),'driving_hours':round(seconds/3600,2),'active_days':len({t.started_at.date() for t in dt}),'score':score['score'],'rag':rag,'score_model':score.get('score_model','legacy_100'),'score_breakdown':score,'risk':score['risk'],'violations':counts,'total_violations':len(ev),'vehicles':by_vehicle})
    return {'company_id':cid,'company_name':company.name if company else '', 'year':year,'month':month,'month_label':f'{year}-{month:02d}','period_start':start.isoformat(),'period_end_exclusive':end.isoformat(),'score_model':'flexible_rag' if flexible_rag_policy(db,cid)['enabled'] else 'legacy_100','vehicles':vehicle_rows,'drivers':rows,'notes':['All times are UTC. Only completed trips are counted for utilization.','Driving hours are elapsed trip durations, not engine-on hours.','Excessive speeding is included in speeding totals and must not be added again.','No score means insufficient distance; no RAG color is assigned.','Vehicle assignment is current; monthly vehicle usage is based on recorded trips.']}

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
      'rag':['Driver','Official score (lower better)' if data.get('score_model')=='flexible_rag' else 'Score / 100','RAG','Risk','Trips','Distance km'],
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
def workshop_assistance_requests(company_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','workshop_staff','company_admin','fleet_manager','representative')
    # Workshop staff can dispatch requests across companies, not change company records.
    cid=company_id if user.role in ('super_admin','workshop_staff') else user.company_id
    if user.role not in ('super_admin','workshop_staff') and company_id is not None and company_id!=user.company_id:
        raise HTTPException(403,'Company access denied')
    where='WHERE a.company_id=:cid' if cid is not None else ''
    args={'cid':cid} if cid is not None else {}
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


@app.get('/api/v1/fleet/overview/daily')
def fleet_overview_daily(days:int=7,company_id:int|None=None,from_at:datetime|None=None,to_at:datetime|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
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
    if from_at is not None or to_at is not None:
        if from_at is None or to_at is None: raise HTTPException(422,'Both from_at and to_at are required')
        start=from_at.replace(tzinfo=timezone.utc) if from_at.tzinfo is None else from_at.astimezone(timezone.utc)
        end=to_at.replace(tzinfo=timezone.utc) if to_at.tzinfo is None else to_at.astimezone(timezone.utc)
        if end<start or end-start>timedelta(days=366): raise HTTPException(422,'Invalid overview date range (maximum 366 days)')
        # Group by UTC calendar date; first and last dates may be partial.
        days=(end.date()-start.date()).days+1
    company_filter=([Trip.company_id==company_id] if company_id is not None else [])
    trips=list(db.scalars(select(Trip).where(Trip.started_at>=start,Trip.started_at<end,*company_filter)).all())
    event_filter=([DrivingEvent.company_id==company_id] if company_id is not None else [])
    events=list(db.scalars(select(DrivingEvent).where(DrivingEvent.recorded_at>=start,DrivingEvent.recorded_at<end,*event_filter)).all())
    vehicle_filter=([Vehicle.company_id==company_id] if company_id is not None else [])
    vehicle_count=db.scalar(select(func.count(Vehicle.id)).where(*vehicle_filter)) or 0
    # Motion snapshot at the selected range end (rather than counting trips as movement).
    # Driver app telemetry only; hardware integration remains a separate source.
    motion_window_start=max(start,end-timedelta(minutes=5))
    location_filter=([DriverLocation.company_id==company_id] if company_id is not None else [])
    recent_locations=db.execute(select(DriverLocation,Trip.vehicle_id).join(Trip,Trip.id==DriverLocation.trip_id).where(
        DriverLocation.recorded_at>=motion_window_start,
        DriverLocation.recorded_at<end,
        DriverLocation.accuracy_m<=50,
        DriverLocation.speed_kmh>=0,
        DriverLocation.speed_kmh<=180,
        *location_filter
    ).order_by(DriverLocation.recorded_at.desc(),DriverLocation.id.desc())).all()
    latest_vehicle_speeds={}
    for location,vehicle_id in recent_locations:
        if vehicle_id not in latest_vehicle_speeds:
            latest_vehicle_speeds[vehicle_id]=float(location.speed_kmh)
    moving=sum(speed>=5 for speed in latest_vehicle_speeds.values())
    stationary=sum(speed<=2 for speed in latest_vehicle_speeds.values())
    # 2-5 km/h is inconclusive and is not assigned to either segment.
    unknown=max(0,int(vehicle_count)-moving-stationary)
    rows=[]
    for i in range(days):
        day=datetime.combine(start.date()+timedelta(days=i),datetime.min.time(),tzinfo=timezone.utc)
        next_day=day+timedelta(days=1)
        ts=[t for t in trips if day<=t.started_at.astimezone(timezone.utc)<next_day]
        ev=[e for e in events if day<=e.recorded_at.astimezone(timezone.utc)<next_day]
        counts={name:sum(1 for e in ev if e.event_type==name) for name in ('speeding','harsh_braking','harsh_acceleration','harsh_cornering')}
        used=len(set(t.vehicle_id for t in ts))
        rows.append({'date':day.date().isoformat(),'trips':len(ts),'distance_km':round(sum(max(0,t.distance_km or 0) for t in ts if t.status=='completed'),2),
                     'drivers_active':len(set(t.driver_id for t in ts)),'vehicles_with_trips':used,'vehicles_without_trips':max(0,vehicle_count-used),
                     'violations':len(ev),**counts})
    return {'days':rows,'vehicle_count':vehicle_count,'motion':{'moving':moving,'stationary':stationary,'unknown':unknown},'totals':{'trips':sum(r['trips'] for r in rows),
        'distance_km':round(sum(r['distance_km'] for r in rows),2),
        'drivers_active':len(set(t.driver_id for t in trips)),
        'violations':len(events)}}

# Optional second-source vehicle hardware telemetry (read-only to trip/odometer data).
from .hardware import router as hardware_router, ensure_tables as ensure_hardware_tables
ensure_hardware_tables()
app.include_router(hardware_router)


# Scheduled, company-scoped email report subscriptions.
from .report_subscriptions import install_report_subscriptions
install_report_subscriptions(app)


# Fleet live telemetry: dedicated company-scoped snapshot, separate from the
# period-based score reports. No location is invented when the GPS is stale.
@app.get('/api/v1/fleet/live-snapshot')
def fleet_live_snapshot(company_id: int | None = None, minutes: int = 30,
                        db: Session = Depends(get_db), user: User = Depends(current_user)):
    cid = _company_for_policy(db, user, company_id)
    minutes = max(1, min(minutes, 180))
    now = datetime.now(timezone.utc)
    zones = phase4_zones(db, cid)
    vehicles = list(db.scalars(select(Vehicle).where(Vehicle.company_id == cid).order_by(Vehicle.plate_number)).all())
    drivers = {d.id: d for d in db.scalars(select(Driver).where(Driver.company_id == cid)).all()}
    positions = []
    for vehicle in vehicles:
        loc = None
        trip = None
        if vehicle.assigned_driver_id:
            loc = db.scalar(select(DriverLocation).where(
                DriverLocation.company_id == cid,
                DriverLocation.driver_id == vehicle.assigned_driver_id,
                DriverLocation.trip_id.in_(select(Trip.id).where(Trip.vehicle_id == vehicle.id))
            ).order_by(DriverLocation.recorded_at.desc(), DriverLocation.id.desc()).limit(1))
            if loc:
                trip = db.get(Trip, loc.trip_id)
        # A completed on-demand request can provide a fresher snapshot than
        # the normal trip samples. Keep the result separate from trip mileage.
        requested = _setting_json(db, f'live_request:{vehicle.id}', {})
        request_result = requested.get('result') if requested.get('status') == 'completed' else None
        if request_result and request_result.get('driver_id') == vehicle.assigned_driver_id:
            try:
                requested_at = datetime.fromisoformat(request_result['recorded_at'])
                existing_at = (loc.recorded_at.replace(tzinfo=timezone.utc) if loc and loc.recorded_at.tzinfo is None else loc.recorded_at) if loc else None
                if (not existing_at or requested_at > existing_at) and (now - requested_at).total_seconds() <= 300:
                    from types import SimpleNamespace
                    loc = SimpleNamespace(latitude=request_result['latitude'],longitude=request_result['longitude'],
                                          speed_kmh=request_result['speed_kmh'],accuracy_m=request_result['accuracy_m'],
                                          recorded_at=requested_at)
                    trip = None
            except (KeyError,ValueError,TypeError): pass
        driver = drivers.get(vehicle.assigned_driver_id)
        age = max(0, (now - (loc.recorded_at.replace(tzinfo=timezone.utc) if loc.recorded_at.tzinfo is None else loc.recorded_at)).total_seconds()) if loc else None
        privacy_on = False
        if vehicle.assigned_driver_id:
            audit = db.execute(text('''SELECT privacy_enabled FROM mobile_privacy_audit
                WHERE driver_id=:did ORDER BY selected_at DESC LIMIT 1'''),
                {'did':vehicle.assigned_driver_id}).first()
            privacy_on = bool(audit and audit[0])
        accurate = bool(not privacy_on and loc and loc.accuracy_m is not None and 0 <= loc.accuracy_m <= 100)
        recent = bool(accurate and age is not None and age <= 300)
        speed = float(loc.speed_kmh or 0) if loc else None
        state = ('moving' if speed is not None and speed >= 5 else
                 'stationary' if speed is not None and speed <= 2 else 'uncertain') if recent else 'stale'
        if privacy_on: state = 'privacy'
        memberships = []
        if loc and accurate:
            for zone in zones:
                if zone.get('vehicle_ids') is not None and vehicle.id not in zone['vehicle_ids']:
                    continue
                distance = _distance_m(loc.latitude, loc.longitude, zone['latitude'], zone['longitude'])
                # An accuracy overlap at the zone boundary is uncertain, not a confirmed entry.
                if abs(distance - zone['radius_m']) <= max(5, float(loc.accuracy_m or 0)):
                    membership = 'boundary_uncertain'
                else:
                    membership = 'inside' if distance < zone['radius_m'] else 'outside'
                memberships.append({'id':zone['id'],'name':zone['name'],'status':membership,
                                    'speed_limit_kmh':zone.get('speed_limit_kmh')})
        positions.append({'vehicle_id':vehicle.id,'plate':vehicle.plate_number,'make_model':vehicle.make_model,
                          'driver_id':driver.id if driver else None,'driver_name':driver.full_name if driver else None,
                          'latitude':loc.latitude if loc and accurate else None,
                          'longitude':loc.longitude if loc and accurate else None,
                          'speed_kmh':speed if accurate else None,'accuracy_m':loc.accuracy_m if accurate else None,
                          'recorded_at':loc.recorded_at.isoformat() if loc and not privacy_on else None,
                          'age_seconds':round(age) if age is not None and not privacy_on else None,
                          'state':state,'trip_active':bool(trip and trip.status == 'active'),
                          'geofences':memberships})
    since = now - timedelta(minutes=minutes)
    active_kinds = _setting_json(db, f'live_active_event_kinds:{cid}',
                                 ['speeding','geofence_entry','geofence_exit','geofence_restricted'])
    # A passive event is always retained for history, never promoted into live scoring.
    recent_events = list(db.scalars(select(DrivingEvent).where(
        DrivingEvent.company_id == cid, DrivingEvent.recorded_at >= since,
        DrivingEvent.latitude.is_not(None), DrivingEvent.longitude.is_not(None)
    ).order_by(DrivingEvent.recorded_at.desc()).limit(300)).all())
    may_view_passive = user.role in ('super_admin','company_admin','fleet_manager')
    events = [{'id':e.id,'type':e.event_type,'driver_id':e.driver_id,
               'recorded_at':e.recorded_at.isoformat(),'latitude':e.latitude,'longitude':e.longitude,
               'value':e.value,'layer':'active' if e.event_type in active_kinds else 'passive'}
              for e in recent_events if e.event_type in active_kinds or may_view_passive]
    return {'company_id':cid,'generated_at':now.isoformat(),'positions':positions,
            'zones':zones,'events':events,'active_event_kinds':active_kinds}

class LiveActiveEventsIn(BaseModel):
    event_types: list[str]

@app.put('/api/v1/fleet/live-active-events')
def update_live_active_events(payload: LiveActiveEventsIn, company_id:int | None = None,
                              db:Session = Depends(get_db),user:User = Depends(current_user)):
    allow(user,'super_admin','company_admin')
    cid = _company_for_policy(db,user,company_id)
    supported = set(EVENT_KINDS)
    if len(payload.event_types) != len(set(payload.event_types)) or any(k not in supported for k in payload.event_types):
        raise HTTPException(422,'Invalid event types')
    key = f'live_active_event_kinds:{cid}'
    row = db.get(AppSetting,key)
    if row: row.value = json.dumps(payload.event_types)
    else: db.add(AppSetting(key=key,value=json.dumps(payload.event_types)))
    db.commit()
    return {'active_event_kinds':payload.event_types}

# On-demand position requests use a short-lived command; a driver app must
# actually return a fresh fix. No device can be remotely forced to enable GPS.
class LivePositionReply(BaseModel):
    request_id: str = Field(min_length=12,max_length=80)
    latitude: float = Field(ge=-90,le=90)
    longitude: float = Field(ge=-180,le=180)
    accuracy_m: float = Field(ge=0,le=1000)
    speed_kmh: float = Field(ge=0,le=350)
    recorded_at: datetime

@app.post('/api/v1/fleet/live-position-request/{vehicle_id}')
def request_live_position(vehicle_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    vehicle=db.get(Vehicle,vehicle_id)
    if not vehicle:raise HTTPException(404,'Vehicle not found')
    scope(user,vehicle.company_id)
    if not vehicle.assigned_driver_id:raise HTTPException(422,'Vehicle has no assigned driver')
    key=f'live_request:{vehicle_id}'
    old=_setting_json(db,key,{})
    now=datetime.now(timezone.utc)
    if old.get('requested_at'):
        try:
            elapsed=(now-datetime.fromisoformat(old['requested_at'])).total_seconds()
            if elapsed<30:raise HTTPException(429,'Wait 30 seconds between position requests')
        except ValueError: pass
    data={'request_id':secrets.token_urlsafe(18),'vehicle_id':vehicle_id,
          'driver_id':vehicle.assigned_driver_id,'requested_at':now.isoformat(),
          'expires_at':(now+timedelta(minutes=2)).isoformat(),'status':'pending'}
    row=db.get(AppSetting,key)
    if row:row.value=json.dumps(data)
    else:db.add(AppSetting(key=key,value=json.dumps(data)))
    db.commit()
    return {'request_id':data['request_id'],'status':'pending','expires_at':data['expires_at']}

@app.get('/api/v1/mobile/live-position-request')
def mobile_live_position_request(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.company_id==d.company_id,Vehicle.assigned_driver_id==d.id))
    if not v:return {'status':'none'}
    data=_setting_json(db,f'live_request:{v.id}',{})
    if not data or data.get('driver_id')!=d.id or data.get('status')!='pending':return {'status':'none'}
    try:
        if datetime.fromisoformat(data['expires_at'])<datetime.now(timezone.utc):return {'status':'expired'}
    except (ValueError,KeyError):return {'status':'none'}
    return {'status':'pending','request_id':data['request_id']}

@app.post('/api/v1/mobile/live-position-reply')
def mobile_live_position_reply(payload:LivePositionReply,db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.company_id==d.company_id,Vehicle.assigned_driver_id==d.id))
    if not v:raise HTTPException(404,'Assigned vehicle missing')
    key=f'live_request:{v.id}'
    data=_setting_json(db,key,{})
    now=datetime.now(timezone.utc)
    if data.get('driver_id')!=d.id or data.get('request_id')!=payload.request_id or data.get('status')!='pending':
        raise HTTPException(409,'Position request is no longer pending')
    if datetime.fromisoformat(data['expires_at'])<now:raise HTTPException(410,'Position request expired')
    at=payload.recorded_at.replace(tzinfo=timezone.utc) if payload.recorded_at.tzinfo is None else payload.recorded_at.astimezone(timezone.utc)
    if abs((now-at).total_seconds())>90:raise HTTPException(422,'A fresh GPS fix is required')
    if payload.accuracy_m>100:raise HTTPException(422,'GPS accuracy too low')
    result={'latitude':payload.latitude,'longitude':payload.longitude,'recorded_at':at.isoformat(),
            'accuracy_m':payload.accuracy_m,'speed_kmh':payload.speed_kmh,'vehicle_id':v.id,'driver_id':d.id}
    data['status']='completed';data['result']=result
    db.get(AppSetting,key).value=json.dumps(data)
    db.commit()
    return {'accepted':True}

@app.get('/api/v1/fleet/live-position-request/{vehicle_id}')
def live_position_request_status(vehicle_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    v=db.get(Vehicle,vehicle_id)
    if not v:raise HTTPException(404,'Vehicle not found')
    scope(user,v.company_id)
    data=_setting_json(db,f'live_request:{vehicle_id}',{})
    if not data:return {'status':'none'}
    status=data.get('status','none')
    if data.get('expires_at') and datetime.fromisoformat(data['expires_at'])<datetime.now(timezone.utc) and status=='pending':status='expired'
    return {'status':status,'requested_at':data.get('requested_at'),'result':data.get('result') if status=='completed' else None}

# Private per-creator links. Public route only exposes a fresh position of
# one explicitly selected vehicle; never shares historical trails or identities.
class LiveShareCreate(BaseModel):
    vehicle_id: int
    expiry_minutes: int = Field(default=15,ge=1,le=60)

@app.post('/api/v1/fleet/live-shares')
def create_live_share(payload:LiveShareCreate,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    v=db.get(Vehicle,payload.vehicle_id)
    if not v:raise HTTPException(404,'Vehicle not found')
    scope(user,v.company_id)
    token=secrets.token_urlsafe(32)
    digest=hashlib.sha256(token.encode()).hexdigest()
    record={'creator_id':user.id,'vehicle_id':v.id,'company_id':v.company_id,
            'created_at':datetime.now(timezone.utc).isoformat(),
            'expires_at':(datetime.now(timezone.utc)+timedelta(minutes=payload.expiry_minutes)).isoformat(),
            'revoked':False}
    db.add(AppSetting(key=f'live_share:{digest}',value=json.dumps(record)))
    db.commit()
    return {'share_id':digest,'token':token,'expires_at':record['expires_at']}

@app.get('/api/v1/fleet/live-shares')
def list_live_shares(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    rows=db.scalars(select(AppSetting).where(AppSetting.key.like('live_share:%'))).all()
    items=[]
    for row in rows:
        try:data=json.loads(row.value)
        except (TypeError,ValueError):continue
        if data.get('creator_id')==user.id:
            items.append({'share_id':row.key.split(':',1)[1],**data})
    return items

@app.delete('/api/v1/fleet/live-shares/{share_id}')
def revoke_live_share(share_id:str,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    if len(share_id)!=64 or any(c not in '0123456789abcdef' for c in share_id):raise HTTPException(404,'Not found')
    row=db.get(AppSetting,f'live_share:{share_id}')
    if not row:raise HTTPException(404,'Not found')
    data=json.loads(row.value)
    if data.get('creator_id')!=user.id:raise HTTPException(404,'Not found')
    data['revoked']=True;row.value=json.dumps(data);db.commit()
    return {'revoked':True}

@app.get('/api/v1/public/live-share/{token}')
def read_live_share(token:str,db:Session=Depends(get_db)):
    if len(token)<32 or len(token)>120:raise HTTPException(404,'Link unavailable')
    row=db.get(AppSetting,'live_share:'+hashlib.sha256(token.encode()).hexdigest())
    if not row:raise HTTPException(404,'Link unavailable')
    data=json.loads(row.value)
    if data.get('revoked') or datetime.fromisoformat(data['expires_at'])<datetime.now(timezone.utc):
        raise HTTPException(410,'Link expired')
    v=db.get(Vehicle,data['vehicle_id'])
    if not v or v.company_id!=data['company_id'] or not v.assigned_driver_id:
        raise HTTPException(404,'Vehicle unavailable')
    loc=db.scalar(select(DriverLocation).where(DriverLocation.company_id==v.company_id,
        DriverLocation.driver_id==v.assigned_driver_id,
        DriverLocation.trip_id.in_(select(Trip.id).where(Trip.vehicle_id==v.id)))
        .order_by(DriverLocation.recorded_at.desc()).limit(1))
    if not loc:return {'status':'unavailable','expires_at':data['expires_at']}
    at=loc.recorded_at.replace(tzinfo=timezone.utc) if loc.recorded_at.tzinfo is None else loc.recorded_at
    age=(datetime.now(timezone.utc)-at).total_seconds()
    privacy=db.execute(text('''SELECT privacy_enabled,selected_at FROM mobile_privacy_audit
      WHERE driver_id=:did ORDER BY selected_at DESC LIMIT 1'''),{'did':v.assigned_driver_id}).first()
    if privacy and privacy[0]:return {'status':'unavailable','expires_at':data['expires_at']}
    trip=db.get(Trip,loc.trip_id)
    if not trip or trip.status!='active' or age<0 or age>120 or loc.accuracy_m is None or loc.accuracy_m>100:
        return {'status':'unavailable','expires_at':data['expires_at']}
    return {'status':'available','plate':v.plate_number,'latitude':loc.latitude,'longitude':loc.longitude,
            'speed_kmh':loc.speed_kmh,'recorded_at':at.isoformat(),'expires_at':data['expires_at']}


# Location-free mobile diagnostic telemetry; authenticated and company scoped.
with engine.begin() as _diag_conn:
    _diag_conn.execute(text("""CREATE TABLE IF NOT EXISTS mobile_diagnostics (
      event_id VARCHAR(64) PRIMARY KEY, company_id INTEGER NOT NULL,
      driver_id INTEGER NOT NULL, vehicle_id INTEGER,
      occurred_at TIMESTAMP WITH TIME ZONE NOT NULL,
      received_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
      severity VARCHAR(12) NOT NULL, category VARCHAR(24) NOT NULL,
      code VARCHAR(100) NOT NULL, detail VARCHAR(450) NOT NULL
    )"""))
    _diag_conn.execute(text('CREATE INDEX IF NOT EXISTS idx_mobile_diagnostics_company_time ON mobile_diagnostics(company_id,received_at DESC)'))

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
