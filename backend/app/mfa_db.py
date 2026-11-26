"""Storage side of two-step sign-in: who is enrolled, checking a second factor, recovery codes, reset.

Used by the sign-in route, the account routes (features/mfa_accounts.py) and the server command (mfa_tools.py).
All SQL uses bound parameters. A wrong code is counted and committed before the error is raised, so a refused
request still counts; concurrent guesses are serialised by the row lock on `user_mfa`.
"""
import logging
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError

from . import mfa
from .audit import audit, audit_commit

log = logging.getLogger(__name__)


def _aware(value):
    return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


def is_enrolled(db, user_id: int) -> bool:
    row = db.execute(text("SELECT 1 FROM user_mfa WHERE user_id=:id AND confirmed_at IS NOT NULL AND secret_enc IS NOT NULL"),
                     {"id": user_id}).first()
    return row is not None


def recovery_codes_left(db, user_id: int) -> int:
    return int(db.execute(text("SELECT count(*) FROM user_mfa_recovery_codes WHERE user_id=:id AND used_at IS NULL"),
                          {"id": user_id}).scalar() or 0)


def login_step(db, user) -> str:
    """What the sign-in does after a correct password: 'none' (a session), 'code' (ask for the second factor) or
    'setup' (the role requires two-step sign-in and the account has none yet).

    An enrolled account is asked for its code even if the key was removed from the settings (it then fails
    closed: the code cannot be checked). Only when the tables do not exist yet (migrations switched off) and no
    key is set, the password alone is enough, as before this feature. "Do not exist" means PostgreSQL's
    undefined-table error (a ProgrammingError); a lost connection, a lock timeout or any other database error
    is not an answer to "is this account enrolled?", so it stops the sign-in instead of letting a password through."""
    if mfa.enabled():
        enrolled = is_enrolled(db, user.id)
    else:
        try:
            with db.begin_nested():
                enrolled = is_enrolled(db, user.id)
        except ProgrammingError:
            log.warning("two-step sign-in tables are not available; signing in with the password only")
            enrolled = False
    if enrolled:
        return "code"
    if mfa.enabled() and user.role in mfa.required_roles():
        return "setup"
    return "none"


def _use_recovery_code(db, user_id: int, code: str) -> bool:
    now = datetime.now(timezone.utc)
    rows = db.execute(text("SELECT id,salt,code_hash FROM user_mfa_recovery_codes WHERE user_id=:id AND used_at IS NULL ORDER BY id"),
                      {"id": user_id}).mappings().all()
    matched = None
    for row in rows:  # all of them, so the time does not show which one matched
        if mfa.recovery_code_matches(code, row["salt"], row["code_hash"]) and matched is None:
            matched = row["id"]
    if matched is None:
        return False
    db.execute(text("UPDATE user_mfa_recovery_codes SET used_at=:now WHERE id=:rid AND used_at IS NULL"), {"now": now, "rid": matched})
    return True


def verify_second_factor(db, user, code: str, request) -> dict:
    """Checks a 6-digit code or a recovery code for an enrolled account. Returns {'method', 'remaining'}.
    On success the caller commits (together with what it audits); on failure this commits the counters and raises."""
    row = db.execute(text("SELECT secret_enc,last_step,failed_count,locked_until,confirmed_at FROM user_mfa WHERE user_id=:id FOR UPDATE"),
                     {"id": user.id}).mappings().first()
    if not row or not row["secret_enc"] or not row["confirmed_at"]:
        db.rollback()
        raise HTTPException(409, "Two-step sign-in is not set up for this account")
    now = datetime.now(timezone.utc)
    locked_until = _aware(row["locked_until"])
    if locked_until and locked_until > now:
        db.rollback()
        audit_commit(db, "auth.mfa", outcome="locked", actor=user, request=request)
        raise HTTPException(429, "Too many wrong codes. Try again later.", headers={"Retry-After": str(int((locked_until - now).total_seconds()) + 1)})
    try:
        secret, reencrypt = mfa.decrypt_secret(row["secret_enc"], user.id)
    except mfa.MfaKeyError as exc:
        log.error("two-step sign-in secret of user %s cannot be read: %s", user.id, exc)
        db.rollback()
        audit_commit(db, "auth.mfa", outcome="error", actor=user, request=request, detail={"reason": "key"})
        raise HTTPException(503, "Two-step sign-in is unavailable on the server. Ask your administrator.") from exc

    method, step = None, None
    if mfa.looks_like_totp(code):
        step = mfa.verify_totp(secret, code, last_step=row["last_step"])
        method = "totp" if step is not None else None
    elif mfa.looks_like_recovery(code):
        method = "recovery" if _use_recovery_code(db, user.id, code) else None

    if method is None:
        failures = int(row["failed_count"] or 0) + 1
        seconds = mfa.lock_seconds(failures)
        db.execute(text("UPDATE user_mfa SET failed_count=:n, locked_until=:until, updated_at=:now WHERE user_id=:id"),
                   {"n": failures, "until": now + timedelta(seconds=seconds) if seconds else None, "now": now, "id": user.id})
        audit(db, "auth.mfa", outcome="failed", actor=user, request=request, detail={"locked_seconds": seconds} if seconds else None)
        db.commit()
        raise HTTPException(401, "That code is not right. Check the time on your phone and try the next code.")

    db.execute(text("""UPDATE user_mfa SET failed_count=0, locked_until=NULL, last_step=COALESCE(:step,last_step),
                       secret_enc=COALESCE(:enc,secret_enc), updated_at=:now WHERE user_id=:id"""),
               {"step": step, "enc": mfa.encrypt_secret(secret, user.id) if reencrypt else None, "now": now, "id": user.id})
    audit(db, "auth.mfa", actor=user, request=request, detail={"method": method})
    return {"method": method, "remaining": recovery_codes_left(db, user.id)}


def issue_recovery_codes(db, user_id: int) -> list[str]:
    """Replaces every recovery code of the account with new ones and returns them in clear (shown once)."""
    db.execute(text("DELETE FROM user_mfa_recovery_codes WHERE user_id=:id"), {"id": user_id})
    codes = [mfa.new_recovery_code() for _ in range(mfa.RECOVERY_CODE_COUNT)]
    for code in codes:
        salt, digest = mfa.hash_recovery_code(code)
        db.execute(text("INSERT INTO user_mfa_recovery_codes (user_id,salt,code_hash) VALUES (:id,:salt,:hash)"),
                   {"id": user_id, "salt": salt, "hash": digest})
    return codes


def reset(db, user_id: int) -> None:
    """Removes the enrolment and the recovery codes and ends the account's sessions (auth_version + 1)."""
    db.execute(text("DELETE FROM user_mfa_recovery_codes WHERE user_id=:id"), {"id": user_id})
    db.execute(text("DELETE FROM user_mfa WHERE user_id=:id"), {"id": user_id})
    db.execute(text("UPDATE users SET auth_version=auth_version+1 WHERE id=:id"), {"id": user_id})
