"""User invitations: send, resend, accept."""

import hashlib
import os
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api_app import app
from ..audit import audit, audit_commit
from ..auth import allow, current_user, hash_password
from ..db import Base, engine, get_db
from ..models import AccountInvitation, Company, User

# Phase 5: Additive tables only. Existing user/company/fleet tables are untouched.

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
    audit_commit(db,'invitation.send',actor=admin,target_type='user',target_id=target.id,company_id=cid,detail={'role':payload.role})
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
    audit_commit(db,'invitation.resend',actor=admin,target_type='user',target_id=target.id,company_id=target.company_id)
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
    audit(db,'invitation.accept',actor=target,target_type='user',target_id=target.id,company_id=target.company_id)
    db.commit()
    return {'status':'activated'}
