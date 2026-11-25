"""Database-backed authentication request throttling (multi-worker safe on PostgreSQL).

Limits apply to IP, identifier, and their combination. The identifiers are HMACed;
raw phone numbers, Iqama numbers and emails are not written to this table.
The account-level limit is intentionally softer to reduce attacker-induced lockouts.
"""
import hashlib
import hmac
import ipaddress
import os
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, Request
from sqlalchemy import text
from sqlalchemy.orm import Session
from .auth import secret, hash_password, verify_password
from .db import engine

# The same expensive KDF is executed for nonexistent identifiers.
_DUMMY_PASSWORD_HASH = hash_password('nuqati-nonexistent-account-dummy-password')


def verify_or_dummy(password: str, stored_hash: str | None) -> bool:
    result = verify_password(password, stored_hash or _DUMMY_PASSWORD_HASH)
    return bool(stored_hash) and result


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else 'unknown'
    try:
        source_ip = ipaddress.ip_address(peer)
        trusted = [ipaddress.ip_network(item.strip(), strict=False)
                   for item in os.getenv('NUQATI_TRUSTED_PROXIES', '127.0.0.1/8,::1/128').split(',') if item.strip()]
        if any(source_ip in cidr for cidr in trusted):
            # Only trusted reverse proxies may provide X-Forwarded-For.
            chain = request.headers.get('x-forwarded-for', '').split(',')
            # Walk from the trusted peer toward the client; never trust a caller-added leftmost value.
            for item in reversed(chain):
                if not item.strip():
                    continue
                address = ipaddress.ip_address(item.strip())
                if not any(address in cidr for cidr in trusted):
                    return str(address)
    except ValueError:
        pass
    return peer


def _key(value: str) -> str:
    return hmac.new(secret(), value.encode(), hashlib.sha256).hexdigest()


def enforce_auth_limit(db: Session, request: Request, endpoint: str, identity: str):
    """Count attempts *before* costly password checks. Durable atomic rows under FOR UPDATE."""
    now = datetime.now(timezone.utc)
    ip = _client_ip(request)
    identity = identity.strip().lower()
    buckets = [
        (f'ip:{ip}', 60, 60, 120),
        (f'identity:{endpoint}:{identity}', 40, 300, 300),
        (f'pair:{endpoint}:{ip}:{identity}', 10, 120, 180),
    ]
    blocked_seconds = 0
    for label, maximum, window_seconds, block_seconds in buckets:
        digest = _key(label)
        # Insert-if-absent and lock within the transaction: prevents race-condition bypass.
        db.execute(text('''INSERT INTO auth_attempt_buckets (key_hash,window_start,attempts)
            VALUES (:key,:now,0) ON CONFLICT (key_hash) DO NOTHING'''), {'key':digest,'now':now})
        row = db.execute(text('''SELECT window_start,attempts,blocked_until
            FROM auth_attempt_buckets WHERE key_hash=:key FOR UPDATE'''), {'key':digest}).mappings().one()
        blocked_until = row['blocked_until']
        if blocked_until and blocked_until.tzinfo is None:
            blocked_until = blocked_until.replace(tzinfo=timezone.utc)
        if blocked_until and blocked_until > now:
            blocked_seconds = max(blocked_seconds, int((blocked_until-now).total_seconds())+1)
            continue
        started = row['window_start']
        if started.tzinfo is None: started = started.replace(tzinfo=timezone.utc)
        fresh = now-started >= timedelta(seconds=window_seconds)
        attempts = 1 if fresh else row['attempts']+1
        until = now+timedelta(seconds=block_seconds) if attempts>maximum else None
        db.execute(text('''UPDATE auth_attempt_buckets SET window_start=:start,
            attempts=:attempts,blocked_until=:until WHERE key_hash=:key'''),
            {'key':digest,'start':now if fresh else started,'attempts':attempts,'until':until})
        if until:
            blocked_seconds = max(blocked_seconds, block_seconds)
    db.commit()  # Throttle records must survive failed login HTTP responses.
    if blocked_seconds:
        raise HTTPException(429, 'Too many attempts. Please try again later.',
                            headers={'Retry-After':str(blocked_seconds)})
