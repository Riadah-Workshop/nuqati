"""Append-only security audit trail: who did what, when, from where.

Stored: actor, action, outcome, target, company, client IP (authentication events only) and a small
`detail` object. Never stored: passwords, tokens, reset links, coordinates, message bodies.

Writing a row must never break the request it describes, so `audit()` runs in a savepoint and logs
instead of raising. `audit_commit()` is for call sites that have already committed their own work.
Retention for this table is part of docs/compliance/RETENTION_SCHEDULE.md.
"""
import json
import logging

from sqlalchemy import text

from .db import engine

log = logging.getLogger(__name__)

with engine.begin() as _audit_conn:
    _audit_conn.execute(text("""CREATE TABLE IF NOT EXISTS security_audit (
        id BIGSERIAL PRIMARY KEY,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
        actor_user_id INTEGER, actor_email VARCHAR(255), actor_role VARCHAR(24),
        company_id INTEGER,
        action VARCHAR(64) NOT NULL, outcome VARCHAR(12) NOT NULL DEFAULT 'ok',
        target_type VARCHAR(32), target_id VARCHAR(64),
        ip VARCHAR(64), detail TEXT
    )"""))
    _audit_conn.execute(text("CREATE INDEX IF NOT EXISTS idx_security_audit_time ON security_audit(created_at DESC)"))
    _audit_conn.execute(text("CREATE INDEX IF NOT EXISTS idx_security_audit_company ON security_audit(company_id, created_at DESC)"))
    _audit_conn.execute(text("CREATE INDEX IF NOT EXISTS idx_security_audit_actor ON security_audit(actor_user_id, created_at DESC)"))

_FORBIDDEN_SUBSTRINGS = ('password', 'token', 'secret', 'authorization', 'latitude', 'longitude', 'photo', 'logo_data')
_FORBIDDEN_EXACT = ('lat', 'lng', 'lon')
_MAX_DETAIL_CHARS = 1000


def client_ip(request) -> str | None:
    """Client address as seen through the trusted proxies (same rule as the login throttle)."""
    if request is None:
        return None
    from .auth_limits import _client_ip
    return _client_ip(request)[:64]


def clean_detail(detail) -> str | None:
    if not detail:
        return None
    safe = {str(k)[:40]: v for k, v in dict(detail).items()
            if str(k).lower() not in _FORBIDDEN_EXACT and not any(part in str(k).lower() for part in _FORBIDDEN_SUBSTRINGS)}
    if not safe:
        return None
    return json.dumps(safe, default=str, ensure_ascii=False, separators=(',', ':'))[:_MAX_DETAIL_CHARS]


def audit(db, action, *, actor=None, outcome='ok', target_type=None, target_id=None, company_id=None,
          request=None, detail=None, actor_email=None):
    """Add one audit row to the caller's transaction. Never raises."""
    try:
        params = {
            'uid': getattr(actor, 'id', None),
            'email': (actor_email or getattr(actor, 'email', None) or None),
            'role': getattr(actor, 'role', None),
            'cid': company_id if company_id is not None else getattr(actor, 'company_id', None),
            'action': str(action)[:64], 'outcome': str(outcome)[:12],
            'ttype': target_type, 'tid': None if target_id is None else str(target_id)[:64],
            'ip': client_ip(request), 'detail': clean_detail(detail),
        }
        if params['email'] and str(params['email']).endswith('@login.nuqati.invalid'):
            params['email'] = None  # internal placeholder address of a driver login, not a real e-mail
        # Savepoint on the connection, not on the ORM session: `Session.begin_nested()` would first flush the
        # caller's pending changes, and a conflict there (which the caller turns into a 409) would be
        # swallowed here and then break the caller's commit. This way only the audit INSERT is isolated.
        conn = db.connection()
        with conn.begin_nested():
            conn.execute(text("""INSERT INTO security_audit
                (actor_user_id,actor_email,actor_role,company_id,action,outcome,target_type,target_id,ip,detail)
                VALUES (:uid,:email,:role,:cid,:action,:outcome,:ttype,:tid,:ip,:detail)"""), params)
    except Exception:  # noqa: BLE001 - the audit trail must not take the application down
        log.exception('security audit write failed (action=%s)', action)


def audit_commit(db, action, **kwargs):
    """`audit()` followed by a commit, for places where the main work is already committed."""
    audit(db, action, **kwargs)
    try:
        db.commit()
    except Exception:  # noqa: BLE001
        db.rollback()
        log.exception('security audit commit failed (action=%s)', action)
