import base64, hashlib, hmac, json, os, secrets, time
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, DriverDeviceSession

ROLES = {"super_admin", "workshop_staff", "company_admin", "fleet_manager", "representative", "driver"}
security = HTTPBearer(auto_error=False)
def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 600000)
    return base64.urlsafe_b64encode(salt+dk).decode()
def verify_password(password: str, stored: str) -> bool:
    try:
        raw = base64.urlsafe_b64decode(stored.encode())
        return hmac.compare_digest(raw[16:], hashlib.pbkdf2_hmac('sha256', password.encode(), raw[:16], 600000))
    except (ValueError, TypeError): return False
def secret():
    s = os.environ.get('NUQATI_AUTH_SECRET', '')
    if len(s) < 32: raise RuntimeError('NUQATI_AUTH_SECRET must be at least 32 characters')
    return s.encode()
def encode_token(user: User, *, refresh: bool=False, session_id: str | None=None) -> str:
    lifetime = 30*24*3600 if refresh else 8*3600
    if user.role=='driver' and not session_id: raise ValueError('Driver device session is required')
    claims={'sub':user.id,'exp':int(time.time())+lifetime,'ver':int(getattr(user,'auth_version',0)),'typ':'refresh' if refresh else 'access'}
    if session_id: claims['sid']=session_id
    data = json.dumps(claims, separators=(',',':')).encode()
    body = base64.urlsafe_b64encode(data).rstrip(b'=').decode()
    sig = hmac.new(secret(),body.encode(),hashlib.sha256).hexdigest()
    return body+'.'+sig
def current_user(creds: HTTPAuthorizationCredentials | None = Depends(security), db:Session=Depends(get_db)) -> User:
    if creds is None: raise HTTPException(401, 'Login required', headers={'WWW-Authenticate':'Bearer'})
    try:
        body,sig=creds.credentials.split('.')
        if not hmac.compare_digest(hmac.new(secret(),body.encode(),hashlib.sha256).hexdigest(),sig): raise ValueError()
        payload=json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if payload['exp'] < time.time() or payload.get('typ','access')!='access': raise ValueError()
        user=db.get(User, int(payload['sub']))
        if not user or not user.is_active: raise ValueError()
        if int(payload.get('ver',0))!=int(getattr(user,'auth_version',0)): raise ValueError()
        if user.role=='driver':
            locked=db.get(DriverDeviceSession,user.id)
            if not locked or not payload.get('sid') or not hmac.compare_digest(str(payload['sid']),locked.session_id): raise ValueError()
        return user
    except (ValueError, KeyError, TypeError, json.JSONDecodeError): raise HTTPException(401,'Invalid or expired session')
def allow(user:User, *roles):
    if user.role not in roles: raise HTTPException(403,'Insufficient permissions')
def scope(user:User, company_id:int):
    if user.role != 'super_admin' and user.company_id != company_id: raise HTTPException(403,'Company access denied')


def refresh_driver_session(refresh_token: str, db: Session) -> tuple[User, str]:
    # Refresh credentials are never accepted as API access tokens.
    try:
        body, sig = refresh_token.split('.')
        if not hmac.compare_digest(hmac.new(secret(), body.encode(), hashlib.sha256).hexdigest(), sig): raise ValueError()
        payload = json.loads(base64.urlsafe_b64decode(body+'='*(-len(body)%4)))
        if payload.get('typ') != 'refresh' or payload['exp'] < time.time(): raise ValueError()
        user = db.get(User, int(payload['sub']))
        if not user or not user.is_active or user.role != 'driver': raise ValueError()
        if int(payload.get('ver',0)) != int(getattr(user,'auth_version',0)): raise ValueError()
        locked=db.get(DriverDeviceSession,user.id)
        if not locked or not payload.get('sid') or not hmac.compare_digest(str(payload['sid']),locked.session_id): raise ValueError()
        return user, locked.session_id
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, AttributeError):
        raise HTTPException(401, 'Refresh session expired or revoked')
