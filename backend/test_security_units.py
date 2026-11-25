"""DB-free unit tests for the security audit helper and the secret-rotation window.

No server and no PostgreSQL: the database session is replaced by a recording fake.
"""
import os
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

os.environ.setdefault('NUQATI_AUTH_SECRET', 'test-security-units-secret-which-is-long-enough')
from app import auth as auth_module  # noqa: E402
from app import audit as audit_module  # noqa: E402
from app.auth import current_user, encode_token  # noqa: E402

SECRET_A = 'rotation-test-secret-A-0123456789abcdef0123'
SECRET_B = 'rotation-test-secret-B-0123456789abcdef0123'
SECRET_C = 'rotation-test-secret-C-0123456789abcdef0123'


# ----------------------------------------------------------------------------- audit helper
class FakeConnection:
    def __init__(self, fail=False):
        self.fail = fail
        self.executed = []
        self.savepoints = 0

    def begin_nested(self):
        conn = self

        class Savepoint:
            def __enter__(self):
                conn.savepoints += 1
                return self

            def __exit__(self, *exc):
                return False

        return Savepoint()

    def execute(self, statement, params=None):
        if self.fail:
            raise RuntimeError('insert failed')
        self.executed.append((str(statement), dict(params or {})))


class FakeSession:
    def __init__(self, fail=False, commit_fails=False):
        self.conn = FakeConnection(fail)
        self.commits = 0
        self.rollbacks = 0
        self.commit_fails = commit_fails

    def connection(self):
        return self.conn

    def commit(self):
        if self.commit_fails:
            raise RuntimeError('commit failed')
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


ADMIN = SimpleNamespace(id=7, email='admin@example.test', role='company_admin', company_id=3)


def test_audit_writes_one_row_inside_a_savepoint_with_actor_and_company():
    db = FakeSession()
    audit_module.audit(db, 'vehicle.update', actor=ADMIN, target_type='vehicle', target_id=42)
    assert db.conn.savepoints == 1
    ((sql, params),) = db.conn.executed
    assert 'INSERT INTO security_audit' in sql
    assert (params['uid'], params['email'], params['role'], params['cid']) == (7, 'admin@example.test', 'company_admin', 3)
    assert (params['action'], params['outcome'], params['ttype'], params['tid']) == ('vehicle.update', 'ok', 'vehicle', '42')
    assert params['ip'] is None and params['detail'] is None
    assert db.commits == 0, 'audit() must leave committing to the caller'


def test_explicit_company_overrides_the_actors_company():
    db = FakeSession()
    audit_module.audit(db, 'company.update', actor=ADMIN, company_id=99)
    assert db.conn.executed[0][1]['cid'] == 99


def test_detail_never_keeps_secret_or_location_like_keys():
    detail = {'role': 'fleet_manager', 'plate': 'ABC 123', 'password': 'x', 'new_password': 'x', 'Token': 't',
              'reset_token': 't', 'Authorization': 'Bearer x', 'latitude': 24.7, 'longitude': 46.7, 'lat': 1, 'lng': 2,
              'lon': 3, 'photo_data': 'AAAA', 'logo_data': 'AAAA', 'client_secret': 's'}
    cleaned = audit_module.clean_detail(detail)
    assert cleaned == '{"role":"fleet_manager","plate":"ABC 123"}'


def test_detail_is_none_when_empty_or_fully_filtered_and_is_length_capped():
    assert audit_module.clean_detail(None) is None
    assert audit_module.clean_detail({}) is None
    assert audit_module.clean_detail({'password': 'x'}) is None
    long_value = audit_module.clean_detail({'note': 'x' * 5000})
    assert len(long_value) <= 1000


def test_internal_placeholder_login_email_is_not_stored():
    db = FakeSession()
    driver_user = SimpleNamespace(id=9, email='driver-9@login.nuqati.invalid', role='driver', company_id=3)
    audit_module.audit(db, 'auth.driver_login', actor=driver_user)
    assert db.conn.executed[0][1]['email'] is None
    assert db.conn.executed[0][1]['uid'] == 9


def test_unknown_actor_leaves_identity_empty_and_keeps_the_event():
    db = FakeSession()
    audit_module.audit(db, 'auth.login', outcome='failed', detail={'known_account': False})
    params = db.conn.executed[0][1]
    assert (params['uid'], params['email'], params['role'], params['cid']) == (None, None, None, None)
    assert params['outcome'] == 'failed' and params['detail'] == '{"known_account":false}'


def test_client_ip_comes_from_the_login_throttle_rule(monkeypatch):
    monkeypatch.setattr('app.auth_limits._client_ip', lambda request: '203.0.113.9')
    db = FakeSession()
    audit_module.audit(db, 'auth.login', actor=ADMIN, request=object())
    assert db.conn.executed[0][1]['ip'] == '203.0.113.9'


def test_values_are_truncated_to_the_column_sizes():
    db = FakeSession()
    audit_module.audit(db, 'a' * 200, actor=ADMIN, outcome='o' * 50, target_id='9' * 200)
    params = db.conn.executed[0][1]
    assert len(params['action']) == 64 and len(params['outcome']) == 12 and len(params['tid']) == 64


def test_a_failing_insert_never_raises_into_the_request():
    db = FakeSession(fail=True)
    audit_module.audit(db, 'user.create', actor=ADMIN)  # must not raise


def test_audit_commit_commits_and_swallows_commit_errors():
    ok = FakeSession()
    audit_module.audit_commit(ok, 'user.create', actor=ADMIN)
    assert ok.commits == 1 and len(ok.conn.executed) == 1
    broken = FakeSession(commit_fails=True)
    audit_module.audit_commit(broken, 'user.create', actor=ADMIN)  # must not raise
    assert broken.rollbacks == 1


# ----------------------------------------------------------------------------- secret rotation
class FakeDb:
    def __init__(self, user):
        self.user = user

    def get(self, model, key):
        return self.user if self.user.id == key else None


def _dashboard_user():
    return SimpleNamespace(id=5, role='company_admin', auth_version=0, is_active=True, company_id=1)


def _accepts(token, user):
    try:
        current_user(SimpleNamespace(credentials=token), FakeDb(user))
        return True
    except HTTPException as exc:
        assert exc.status_code == 401
        return False


def _use_secrets(monkeypatch, current, previous=None):
    monkeypatch.setenv('NUQATI_AUTH_SECRET', current)
    if previous is None:
        monkeypatch.delenv('NUQATI_AUTH_SECRET_PREVIOUS', raising=False)
    else:
        monkeypatch.setenv('NUQATI_AUTH_SECRET_PREVIOUS', previous)


def test_rotation_window_accepts_old_tokens_only_while_the_previous_secret_is_set(monkeypatch):
    user = _dashboard_user()
    _use_secrets(monkeypatch, SECRET_A)
    old_token = encode_token(user)
    assert _accepts(old_token, user)

    _use_secrets(monkeypatch, SECRET_B)  # rotated without a window: everyone is signed out
    assert not _accepts(old_token, user)

    _use_secrets(monkeypatch, SECRET_B, previous=SECRET_A)  # window open
    assert _accepts(old_token, user)
    new_token = encode_token(user)
    assert _accepts(new_token, user)

    _use_secrets(monkeypatch, SECRET_B)  # window closed again
    assert not _accepts(old_token, user)
    assert _accepts(new_token, user)


def test_new_tokens_are_always_signed_with_the_current_secret(monkeypatch):
    user = _dashboard_user()
    _use_secrets(monkeypatch, SECRET_B, previous=SECRET_A)
    token = encode_token(user)
    _use_secrets(monkeypatch, SECRET_B)  # previous removed: token must still verify, i.e. it used SECRET_B
    assert _accepts(token, user)
    _use_secrets(monkeypatch, SECRET_A)
    assert not _accepts(token, user)


def test_only_one_previous_secret_is_honoured(monkeypatch):
    user = _dashboard_user()
    _use_secrets(monkeypatch, SECRET_A)
    oldest = encode_token(user)
    _use_secrets(monkeypatch, SECRET_C, previous=SECRET_B)  # A is two rotations back
    assert not _accepts(oldest, user)


def test_previous_secret_is_verification_only_and_validated(monkeypatch):
    monkeypatch.delenv('NUQATI_AUTH_SECRET_PREVIOUS', raising=False)
    assert auth_module.previous_secret() is None
    monkeypatch.setenv('NUQATI_AUTH_SECRET_PREVIOUS', '')
    assert auth_module.previous_secret() is None
    monkeypatch.setenv('NUQATI_AUTH_SECRET_PREVIOUS', 'too-short')
    with pytest.raises(RuntimeError):
        auth_module.previous_secret()
    monkeypatch.setenv('NUQATI_AUTH_SECRET_PREVIOUS', SECRET_A)
    assert auth_module.previous_secret() == SECRET_A.encode()


def test_tampered_signature_is_rejected_even_with_a_previous_secret(monkeypatch):
    user = _dashboard_user()
    _use_secrets(monkeypatch, SECRET_B, previous=SECRET_A)
    token = encode_token(user)
    body, sig = token.split('.')
    forged = body + '.' + ('0' if sig[0] != '0' else '1') + sig[1:]
    assert not _accepts(forged, user)


def test_expired_token_is_rejected_regardless_of_which_secret_signed_it(monkeypatch):
    user = _dashboard_user()
    _use_secrets(monkeypatch, SECRET_A)
    token = encode_token(user)
    real_time = time.time
    monkeypatch.setattr(time, 'time', lambda: real_time() + 9 * 3600)
    _use_secrets(monkeypatch, SECRET_B, previous=SECRET_A)
    assert not _accepts(token, user)
