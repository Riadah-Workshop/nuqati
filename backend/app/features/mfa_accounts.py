"""Two-step sign-in (TOTP) for dashboard accounts: second step of the sign-in, enrolment, recovery codes, reset.

See app/mfa.py for the settings and what the feature does. Nothing here is reachable in a way that skips the
password: the first step (`POST /api/v1/auth/login`, in auth_accounts.py) answers `mfa_required` or
`mfa_setup_required` with a short-lived token that is not an access token, and only this module accepts it.
"""
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import mfa, mfa_db
from ..api_app import app
from ..audit import audit, audit_commit
from ..auth import allow, current_user, encode_token, security, verify_password
from ..auth_limits import enforce_auth_limit
from ..db import get_db
from ..models import User
from .auth_accounts import _dashboard_account, user_view


class MfaLoginIn(BaseModel):
    mfa_token: str = Field(min_length=20, max_length=2000)
    code: str = Field(min_length=6, max_length=32)


class MfaEnrollIn(BaseModel):
    password: str | None = Field(default=None, max_length=128)
    code: str | None = Field(default=None, max_length=32)


class MfaConfirmIn(BaseModel):
    code: str = Field(min_length=6, max_length=32)


class MfaSecureIn(BaseModel):
    password: str = Field(max_length=128)
    code: str = Field(min_length=6, max_length=32)


def current_user_or_mfa_setup(request: Request, creds=Depends(security), db: Session = Depends(get_db)) -> User:
    """A normal session, or the short-lived setup token a required role gets after its password."""
    if creds is None:
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": "Bearer"})
    claims = mfa.decode_step_token(creds.credentials, ("mfa_setup",))
    if claims is None:
        return current_user(creds, db)  # raises 401 unless it is a valid access token
    user = db.get(User, int(claims["sub"]))
    if not user or not user.is_active or int(claims.get("ver", 0)) != int(getattr(user, "auth_version", 0)):
        raise HTTPException(401, "Invalid or expired session")
    request.state.mfa_setup = True
    return user


def _setup_session(request: Request) -> bool:
    return bool(getattr(request.state, "mfa_setup", False))


def _available():
    if not mfa.enabled():
        raise HTTPException(503, "Two-step sign-in is not switched on on this server")


def _check_password(db: Session, user: User, request: Request, password: str | None):
    enforce_auth_limit(db, request, "dashboard-mfa-manage", f"user:{user.id}")
    if not password or not verify_password(password, user.password_hash):
        audit_commit(db, "auth.mfa_password", outcome="failed", actor=user, request=request, detail={"reason": "password"})
        raise HTTPException(401, "Password is not correct")


def _session_reply(user: User, **extra) -> dict:
    return {"access_token": encode_token(user), "token_type": "bearer", "user": user_view(user), **extra}


@app.post("/api/v1/auth/login/mfa")
def login_mfa(payload: MfaLoginIn, request: Request, db: Session = Depends(get_db)):
    """Second step of the sign-in: the token from the password step plus a 6-digit code or a recovery code."""
    claims = mfa.decode_step_token(payload.mfa_token, ("mfa",))
    user = db.get(User, int(claims["sub"])) if claims else None
    if not user or not user.is_active or int(claims.get("ver", 0)) != int(getattr(user, "auth_version", 0)):
        raise HTTPException(401, "The sign-in expired. Enter your password again.")
    enforce_auth_limit(db, request, "dashboard-mfa", f"user:{user.id}")
    result = mfa_db.verify_second_factor(db, user, payload.code, request)
    audit(db, "auth.login", actor=user, request=request, detail={"second_step": result["method"]})
    db.commit()
    return _session_reply(user, recovery_codes_remaining=result["remaining"], used_recovery_code=result["method"] == "recovery")


@app.get("/api/v1/auth/mfa")
def mfa_status(db: Session = Depends(get_db), user: User = Depends(current_user_or_mfa_setup)):
    _dashboard_account(user)
    enrolled = mfa_db.is_enrolled(db, user.id)
    pending = bool(db.execute(text("SELECT 1 FROM user_mfa WHERE user_id=:id AND pending_secret_enc IS NOT NULL"), {"id": user.id}).first())
    return {"available": mfa.enabled(), "enabled": enrolled, "required": mfa.enabled() and user.role in mfa.required_roles(),
            "pending_setup": pending, "recovery_codes_remaining": mfa_db.recovery_codes_left(db, user.id) if enrolled else 0,
            "issuer": mfa.issuer()}


@app.post("/api/v1/auth/mfa/enroll")
def mfa_enroll(payload: MfaEnrollIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user_or_mfa_setup)):
    """Starts the setup (or a device change): a new secret that is not active until a code from it is confirmed."""
    _dashboard_account(user)
    _available()
    enrolled = mfa_db.is_enrolled(db, user.id)
    if _setup_session(request):
        if enrolled:
            raise HTTPException(409, "Two-step sign-in is already set up. Sign in with your code.")
    else:
        _check_password(db, user, request, payload.password)
        if enrolled:  # changing the authenticator needs the current one
            if not payload.code:
                raise HTTPException(422, "Enter a code from your current authenticator to change it")
            mfa_db.verify_second_factor(db, user, payload.code, request)
    raw = mfa.new_secret()
    db.execute(text("""INSERT INTO user_mfa (user_id, pending_secret_enc) VALUES (:id, :enc)
                       ON CONFLICT (user_id) DO UPDATE SET pending_secret_enc=EXCLUDED.pending_secret_enc, updated_at=:now"""),
               {"id": user.id, "enc": mfa.encrypt_secret(raw, user.id), "now": datetime.now(timezone.utc)})
    audit(db, "auth.mfa_enroll", actor=user, request=request, detail={"change": enrolled})
    db.commit()
    return {"secret": mfa.secret_text(raw), "secret_grouped": mfa.grouped(mfa.secret_text(raw)),
            "otpauth_uri": mfa.otpauth_uri(raw, user.email), "issuer": mfa.issuer(), "account": user.email,
            "digits": mfa.TOTP_DIGITS, "period": mfa.TOTP_PERIOD}


@app.post("/api/v1/auth/mfa/confirm")
def mfa_confirm(payload: MfaConfirmIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user_or_mfa_setup)):
    """Finishes the setup with a code from the new authenticator; returns the recovery codes (shown once)."""
    _dashboard_account(user)
    _available()
    enforce_auth_limit(db, request, "dashboard-mfa-manage", f"user:{user.id}")
    row = db.execute(text("SELECT pending_secret_enc FROM user_mfa WHERE user_id=:id FOR UPDATE"), {"id": user.id}).mappings().first()
    if not row or not row["pending_secret_enc"]:
        db.rollback()
        raise HTTPException(409, "Start the setup first")
    try:
        raw, _ = mfa.decrypt_secret(row["pending_secret_enc"], user.id)
    except mfa.MfaKeyError as exc:
        db.rollback()
        raise HTTPException(503, "Two-step sign-in is unavailable on the server. Ask your administrator.") from exc
    step = mfa.verify_totp(raw, payload.code)
    if step is None:
        db.rollback()
        audit_commit(db, "auth.mfa_enroll", outcome="failed", actor=user, request=request, detail={"stage": "confirm"})
        raise HTTPException(401, "That code is not right. Check the time on your phone and try the next code.")
    codes = mfa_db.issue_recovery_codes(db, user.id)
    db.execute(text("""UPDATE user_mfa SET secret_enc=pending_secret_enc, pending_secret_enc=NULL, confirmed_at=:now,
                       last_step=:step, failed_count=0, locked_until=NULL, updated_at=:now WHERE user_id=:id"""),
               {"now": datetime.now(timezone.utc), "step": step, "id": user.id})
    audit(db, "auth.mfa_enroll", actor=user, request=request, detail={"stage": "confirmed"})
    reply = {"status": "enabled", "recovery_codes": codes}
    if _setup_session(request):
        audit(db, "auth.login", actor=user, request=request, detail={"second_step": "setup"})
        reply.update(_session_reply(user))
    db.commit()
    return reply


@app.post("/api/v1/auth/mfa/recovery-codes")
def mfa_new_recovery_codes(payload: MfaSecureIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Replaces all recovery codes (the old ones stop working)."""
    _dashboard_account(user)
    _available()
    _check_password(db, user, request, payload.password)
    mfa_db.verify_second_factor(db, user, payload.code, request)
    codes = mfa_db.issue_recovery_codes(db, user.id)
    audit(db, "auth.mfa_recovery", actor=user, request=request, detail={"count": len(codes)})
    db.commit()
    return {"recovery_codes": codes}


@app.post("/api/v1/auth/mfa/disable")
def mfa_disable(payload: MfaSecureIn, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Turns two-step sign-in off for the signed-in account (not possible for a role that requires it)."""
    _dashboard_account(user)
    if mfa.enabled() and user.role in mfa.required_roles():
        raise HTTPException(403, "Two-step sign-in is required for your role. You can change your authenticator instead.")
    _check_password(db, user, request, payload.password)
    mfa_db.verify_second_factor(db, user, payload.code, request)
    mfa_db.reset(db, user.id)
    audit(db, "auth.mfa_disable", actor=user, request=request)
    db.commit()
    return {"status": "disabled", "sign_in_again": True}


@app.get("/api/v1/users/{user_id}/mfa")
def admin_mfa_status(user_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, "super_admin")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    return {"available": mfa.enabled(), "enabled": mfa_db.is_enrolled(db, target.id),
            "required": mfa.enabled() and target.role in mfa.required_roles()}


@app.post("/api/v1/users/{user_id}/mfa/reset")
def admin_reset_mfa(user_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Lost phone and no recovery codes: removes the person's two-step sign-in and ends their sessions."""
    allow(user, "super_admin")
    target = db.get(User, user_id)
    if not target:
        raise HTTPException(404, "User not found")
    if target.id == user.id:
        raise HTTPException(409, "Use the change-authenticator option for your own account")
    mfa_db.reset(db, target.id)
    audit(db, "auth.mfa_reset", actor=user, request=request, target_type="user", target_id=target.id, company_id=target.company_id,
          detail={"role": target.role})
    db.commit()
    return {"status": "reset"}
