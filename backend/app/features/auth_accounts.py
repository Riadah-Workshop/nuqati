"""Dashboard and driver authentication: login, password reset, e-mail change, driver phone/Iqama login, refresh, logout, device sessions."""

import base64
import hashlib
import json
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..audit import audit, audit_commit
from ..auth import (
    allow,
    current_user,
    encode_token,
    hash_password,
    refresh_driver_session,
    scope,
    verify_password,
)
from ..auth_limits import enforce_auth_limit, verify_or_dummy
from ..db import engine, get_db
from ..models import AppSetting, Driver, DriverAccount, DriverDeviceSession, DriverMetadata, User

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
def login(payload:LoginIn, request:Request, db:Session=Depends(get_db)):
    email=payload.email.strip().lower()
    enforce_auth_limit(db,request,'dashboard-login',email)
    user=db.scalar(select(User).where(User.email==email))
    if not verify_or_dummy(payload.password,user.password_hash if user and user.is_active else None):
        audit_commit(db,'auth.login',outcome='failed',actor=user,request=request,detail={'known_account':user is not None})
        raise HTTPException(401,'Invalid credentials')
    if user.role=='driver':
        audit_commit(db,'auth.login',outcome='denied',actor=user,request=request,detail={'reason':'driver_account'})
        raise HTTPException(403,'Drivers must sign in through the driver app')
    audit_commit(db,'auth.login',actor=user,request=request)
    return {'access_token':encode_token(user),'token_type':'bearer','user':user_view(user)}

class DriverPhoneLogin(BaseModel):
    phone: str = Field(min_length=8,max_length=40)
    password: str
    company_id: int | None = Field(default=None,ge=1)
    device_id: str = Field(min_length=20,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')

def normalize_phone(value:str)->str:
    p=''.join(c for c in value if c.isdigit() or c=='+')
    if p.startswith('00'):p='+'+p[2:]
    if p.startswith('05') and len(p)==10:p='+966'+p[1:]
    if p.startswith('966') and len(p)==12:p='+'+p
    return p

# Dashboard account recovery and self-service profile changes.
# All tokens are random, single-use and stored as SHA-256 digests only.

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
def request_dashboard_password_reset(payload:PasswordResetRequest,request:Request,db:Session=Depends(get_db)):
    enforce_auth_limit(db,request,'password-reset-request',payload.email)
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
        audit(db,'auth.password_reset_requested',actor=user,request=request)
        db.commit()
    except HTTPException:
        db.rollback()
        # Do not reveal account existence or mail delivery status to unauthenticated visitors.
    return generic

class PasswordResetConfirm(BaseModel):
    token:str=Field(min_length=30,max_length=200)
    new_password:str=Field(min_length=12,max_length=128)

@app.post('/api/v1/auth/password-reset/confirm')
def confirm_dashboard_password_reset(payload:PasswordResetConfirm,request:Request,db:Session=Depends(get_db)):
    enforce_auth_limit(db,request,'password-reset-confirm',hashlib.sha256(payload.token.encode()).hexdigest())
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
    audit(db,'auth.password_reset_completed',actor=user,request=request)
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
    audit(db,'account.password_changed',actor=user)
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
    audit(db,'account.email_change_requested',actor=user)
    db.commit()
    return {'status':'confirmation_sent'}

class EmailChangeConfirm(BaseModel):
    token:str=Field(min_length=30,max_length=200)

@app.post('/api/v1/auth/email-change/confirm')
def confirm_dashboard_email_change(payload:EmailChangeConfirm,request:Request,db:Session=Depends(get_db)):
    enforce_auth_limit(db,request,'email-change-confirm',hashlib.sha256(payload.token.encode()).hexdigest())
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
    audit(db,'account.email_changed',actor=user,request=request)
    db.commit()
    return {'status':'email_changed','sign_in_again':True}

@app.post('/api/v1/auth/logout')
def dashboard_logout(request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    """Ends every dashboard session of this user: tokens issued before now stop working. Drivers use /auth/driver-logout."""
    _dashboard_account(user)
    db.execute(text('UPDATE users SET auth_version=auth_version+1 WHERE id=:id'),{'id':user.id})
    audit(db,'auth.logout',actor=user,request=request)
    db.commit()
    return {'status':'logged_out'}

# Driver device reservation is serialized by locking the user row. A second
# phone cannot race a concurrent login, even with multiple API workers.
# No lease timeout: a device remains reserved until an authenticated online
# logout or an administrator explicitly releases the lost device.
def reserve_driver_device(db:Session, user:User, device_id:str) -> str:
    db.execute(select(User.id).where(User.id==user.id).with_for_update()).one()
    existing=db.get(DriverDeviceSession,user.id)
    if existing and not secrets.compare_digest(existing.device_id,device_id):
        raise HTTPException(409,'DRIVER_ALREADY_LOGGED_IN_ON_ANOTHER_DEVICE')
    if existing:
        existing.last_login_at=datetime.now(timezone.utc)
        sid=existing.session_id
    else:
        sid=secrets.token_hex(32)
        db.add(DriverDeviceSession(user_id=user.id,device_id=device_id,session_id=sid))
    db.commit()
    return sid

@app.post('/api/v1/auth/driver-phone-login')
def driver_phone_login(payload:DriverPhoneLogin,request:Request,db:Session=Depends(get_db)):
    phone=normalize_phone(payload.phone)
    enforce_auth_limit(db,request,'driver-phone',phone)
    digits=''.join(ch for ch in phone if ch.isdigit())
    variants={digits}
    if digits.startswith('966') and len(digits)==12:
        variants.update({'0'+digits[3:],digits[3:],'00'+digits})
    # DB-side normalization also matches pre-existing formatted phone numbers.
    normalized=func.regexp_replace(Driver.phone,'[^0-9]','','g')
    q=(select(Driver,User).join(DriverAccount,DriverAccount.driver_id==Driver.id)
       .join(User,User.id==DriverAccount.user_id)
       .where(User.role=='driver',User.is_active==True,Driver.status=='active',
              normalized.in_(variants)))
    if payload.company_id is not None: q=q.where(Driver.company_id==payload.company_id)
    candidates=db.execute(q.limit(25)).all()
    matches=[u for d,u in candidates if verify_password(payload.password,u.password_hash)]
    if not candidates: verify_or_dummy(payload.password,None)
    if not matches:
        audit_commit(db,'auth.driver_login',outcome='failed',request=request,detail={'method':'phone','known_account':bool(candidates)})
        raise HTTPException(401,'Invalid phone or password')
    if len(matches)!=1:
        raise HTTPException(409,'Multiple driver accounts match. Provide your company ID to sign in.')
    u=matches[0]
    try: sid=reserve_driver_device(db,u,payload.device_id)
    except HTTPException as exc:
        audit_commit(db,'auth.driver_login',outcome='denied',actor=u,request=request,detail={'reason':str(exc.detail)})
        raise
    audit_commit(db,'auth.driver_login',actor=u,request=request)
    return {'access_token':encode_token(u,session_id=sid),'refresh_token':encode_token(u,refresh=True,session_id=sid),'token_type':'bearer','user':user_view(u)}

class DriverIqamaLogin(BaseModel):
    iqama: str = Field(min_length=10, max_length=10)
    password: str
    company_id: int | None = Field(default=None,ge=1)
    device_id: str = Field(min_length=20,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')

@app.post('/api/v1/auth/driver-iqama-login')
def driver_iqama_login(payload:DriverIqamaLogin,request:Request,db:Session=Depends(get_db)):
    iqama=payload.iqama.strip()
    if not (len(iqama)==10 and iqama.isascii() and iqama.isdigit()): raise HTTPException(422,'Enter a 10-digit Iqama / ID number')
    enforce_auth_limit(db,request,'driver-iqama',iqama)
    q=(select(Driver,User).join(DriverMetadata,DriverMetadata.driver_id==Driver.id)
       .join(DriverAccount,DriverAccount.driver_id==Driver.id).join(User,User.id==DriverAccount.user_id)
       .where(DriverMetadata.id_number==iqama,Driver.status=='active',
              User.role=='driver',User.is_active==True))
    if payload.company_id is not None: q=q.where(Driver.company_id==payload.company_id)
    candidates=db.execute(q.limit(25)).all()
    matches=[u for d,u in candidates if verify_password(payload.password,u.password_hash)]
    if not candidates: verify_or_dummy(payload.password,None)
    if not matches:
        audit_commit(db,'auth.driver_login',outcome='failed',request=request,detail={'method':'iqama','known_account':bool(candidates)})
        raise HTTPException(401,'Invalid Iqama or password')
    if len(matches)!=1: raise HTTPException(409,'Multiple driver accounts match. Provide your company ID to sign in.')
    u=matches[0]
    try: sid=reserve_driver_device(db,u,payload.device_id)
    except HTTPException as exc:
        audit_commit(db,'auth.driver_login',outcome='denied',actor=u,request=request,detail={'reason':str(exc.detail)})
        raise
    audit_commit(db,'auth.driver_login',actor=u,request=request)
    return {'access_token':encode_token(u,session_id=sid),'refresh_token':encode_token(u,refresh=True,session_id=sid),'token_type':'bearer','user':user_view(u)}

class DriverRefreshRequest(BaseModel):
    refresh_token: str

@app.post('/api/v1/auth/driver-refresh')
def driver_refresh(payload:DriverRefreshRequest, db:Session=Depends(get_db)):
    user,sid=refresh_driver_session(payload.refresh_token,db)
    return {'access_token':encode_token(user,session_id=sid),'refresh_token':encode_token(user,refresh=True,session_id=sid),'token_type':'bearer'}

@app.post('/api/v1/auth/driver-logout')
def driver_online_logout(request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'driver')
    # The server revokes both access and refresh tokens before the client
    # deletes its credentials. No offline logout can release this reservation.
    db.execute(select(User.id).where(User.id==user.id).with_for_update()).one()
    locked=db.get(DriverDeviceSession,user.id)
    if not locked: raise HTTPException(401,'Driver session already revoked')
    # Recheck the exact signed session AFTER taking the user row lock. Without
    # this, a logout racing an administrator's release/new phone login could
    # accidentally delete the newly authorized phone's session.
    try:
        bearer=request.headers.get('authorization','').split(' ',1)[1]
        body=bearer.split('.',1)[0]
        submitted=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4))).get('sid')
    except (IndexError,ValueError,TypeError,AttributeError):
        raise HTTPException(401,'Invalid driver session')
    if not submitted or not secrets.compare_digest(locked.session_id,str(submitted)):
        raise HTTPException(401,'Driver session changed; login again')
    link=db.scalar(select(DriverAccount).where(DriverAccount.user_id==user.id))
    driver=db.get(Driver,link.driver_id) if link else None
    if driver:
        # Audit the actual server-side logout, not an offline queued intention.
        db.execute(text('INSERT INTO mobile_lifecycle_audit(event_id,company_id,driver_id,event_type,occurred_at) VALUES (:i,:c,:d,\'logout\',:a)'),
                   {'i':'logout_'+secrets.token_hex(20),'c':driver.company_id,'d':driver.id,'a':datetime.now(timezone.utc)})
    audit(db,'auth.driver_logout',actor=user,request=request)
    db.delete(locked)
    db.commit()
    return {'status':'logged_out'}

@app.post('/api/v1/drivers/{driver_id}/release-device-session')
def admin_release_driver_device(driver_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin')
    driver=db.get(Driver,driver_id)
    if not driver: raise HTTPException(404,'Driver not found')
    scope(user,driver.company_id)
    link=db.scalar(select(DriverAccount).where(DriverAccount.driver_id==driver_id))
    if not link: raise HTTPException(404,'Driver login not linked')
    db.execute(select(User.id).where(User.id==link.user_id).with_for_update()).one()
    locked=db.get(DriverDeviceSession,link.user_id)
    if locked: db.delete(locked)
    audit(db,'driver.device_release',actor=user,target_type='driver',target_id=driver_id,company_id=driver.company_id,detail={'had_session':locked is not None})
    db.commit()
    return {'status':'released','driver_id':driver_id,'had_session':locked is not None}

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
