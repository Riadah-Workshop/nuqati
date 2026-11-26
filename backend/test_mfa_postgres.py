"""Live checks of two-step sign-in (TOTP) on a real PostgreSQL database: enrolment, the second step, recovery codes,
the guessing lock, required roles, changing the authenticator, resets, encrypted storage and fail-closed behaviour.
Requires a *dedicated* PostgreSQL test database (same rules as test_auth_runtime_postgres.py):

    NUQATI_TEST_DATABASE_URL=postgresql+psycopg2://.../nuqati_test \
    PYTHONPATH=backend pytest -q backend/test_mfa_postgres.py

Skipped when the variable is not set. The settings (NUQATI_MFA_*) are changed per test with monkeypatch; the
time step of the authenticator is controlled by a fake clock so one test can sign in several times.
"""
import base64
import os
import re
import secrets
from urllib.parse import urlsplit

import pytest

URL = os.getenv('NUQATI_TEST_DATABASE_URL', '')
if not URL:
    pytest.skip('Set NUQATI_TEST_DATABASE_URL to a disposable PostgreSQL test database', allow_module_level=True)
if not URL.startswith('postgresql+') or 'test' not in urlsplit(URL).path.lower():
    raise RuntimeError('Refusing to run against a URL that is not a PostgreSQL TEST database')

os.environ['DATABASE_URL'] = URL
os.environ.setdefault('NUQATI_AUTH_SECRET', 'security-runtime-test-secret-only-2026-rotate')
for _name in ('NUQATI_MFA_KEY', 'NUQATI_MFA_KEY_PREVIOUS', 'NUQATI_MFA_REQUIRED_ROLES'):
    os.environ.pop(_name, None)  # start without the feature; each test switches on what it needs

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, text  # noqa: E402
from app import migrate  # noqa: E402
assert migrate.main(['upgrade']) == 0, 'migrations failed on the test database'
from app import mfa  # noqa: E402
from app.main import app  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Company, User  # noqa: E402

PASSWORD = 'MfaTestPassword2026'
KEY = 'k' * 40  # fixtures only; low-entropy on purpose so secret scanners do not mistake them for real keys
OTHER_KEY = 'o' * 40


@pytest.fixture
def world():
    suffix = secrets.token_hex(5)
    with SessionLocal() as db:
        company_a, company_b = Company(name='Mfa A ' + suffix), Company(name='Mfa B ' + suffix)
        db.add_all([company_a, company_b])
        db.flush()

        def make(company, role, tag):
            return User(company_id=company.id if company else None, role=role, full_name=f'{tag} {suffix}',
                        email=f'{tag}-{suffix}@test.invalid', password_hash=hash_password(PASSWORD), is_active=True)

        people = {'super': make(None, 'super_admin', 'super'), 'admin_a': make(company_a, 'company_admin', 'admin-a'),
                  'admin_b': make(company_b, 'company_admin', 'admin-b'), 'manager_a': make(company_a, 'fleet_manager', 'manager-a')}
        db.add_all(people.values())
        db.commit()
        world = {name: {'id': person.id, 'email': person.email} for name, person in people.items()}
        world['companies'] = [company_a.id, company_b.id]
    yield world
    with SessionLocal() as db:
        db.execute(delete(User).where(User.id.in_([world[n]['id'] for n in ('super', 'admin_a', 'admin_b', 'manager_a')])))
        db.execute(delete(Company).where(Company.id.in_(world['companies'])))
        db.commit()


@pytest.fixture(autouse=True)
def fresh_throttle():
    """The sign-in throttle counts per address and the test client always has the same one."""
    with SessionLocal() as db:
        db.execute(text('DELETE FROM auth_attempt_buckets'))
        db.commit()


@pytest.fixture
def mfa_on(monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_KEY', KEY)


class Clock:
    def __init__(self):
        self.step = mfa.current_step()

    def advance(self, steps=1):
        self.step += steps


@pytest.fixture
def clock(monkeypatch):
    fake = Clock()
    monkeypatch.setattr(mfa, 'current_step', lambda now=None: fake.step)
    return fake


def login(client, email, password=PASSWORD):
    return client.post('/api/v1/auth/login', json={'email': email, 'password': password})


def bearer(token):
    return {'Authorization': 'Bearer ' + token}


def code_now(secret, clock, offset=0):
    return mfa.totp_code(secret, clock.step + offset)


def wrong_code(secret, clock):
    near = {mfa.totp_code(secret, clock.step + d) for d in range(-3, 4)}
    return next(c for c in ('%06d' % n for n in range(1, 10 ** 6)) if c not in near)


def enrol(client, email, clock):
    """Signs in with the password only, sets up two-step sign-in and returns (secret, recovery codes)."""
    first = login(client, email)
    assert first.status_code == 200 and 'access_token' in first.json(), first.text
    headers = bearer(first.json()['access_token'])
    started = client.post('/api/v1/auth/mfa/enroll', json={'password': PASSWORD}, headers=headers)
    assert started.status_code == 200, started.text
    secret = base64.b32decode(started.json()['secret'])
    done = client.post('/api/v1/auth/mfa/confirm', json={'code': code_now(secret, clock)}, headers=headers)
    assert done.status_code == 200, done.text
    return secret, done.json()['recovery_codes']


def challenge(client, email):
    reply = login(client, email)
    assert reply.status_code == 200 and reply.json().get('mfa_required') is True, reply.text
    assert 'access_token' not in reply.json()
    return reply.json()['mfa_token']


def second_step(client, token, code):
    return client.post('/api/v1/auth/login/mfa', json={'mfa_token': token, 'code': code})


def audit_rows(**filters):
    clauses = ' AND '.join(f'{column}=:{column}' for column in filters) or 'TRUE'
    with SessionLocal() as db:
        return db.execute(text('SELECT * FROM security_audit WHERE ' + clauses + ' ORDER BY id'), filters).mappings().all()


def stored(user_id):
    with SessionLocal() as db:
        return db.execute(text('SELECT * FROM user_mfa WHERE user_id=:id'), {'id': user_id}).mappings().first()


# --------------------------------------------------------------------------------------------------------------
def test_without_a_key_nothing_changes_for_anyone(world):
    with TestClient(app) as client:
        reply = login(client, world['admin_a']['email'])
        assert reply.status_code == 200 and reply.json()['access_token'] and 'mfa_required' not in reply.json()
        headers = bearer(reply.json()['access_token'])
        status = client.get('/api/v1/auth/mfa', headers=headers).json()
        assert status['available'] is False and status['enabled'] is False and status['required'] is False
        assert client.post('/api/v1/auth/mfa/enroll', json={'password': PASSWORD}, headers=headers).status_code == 503


def test_without_a_key_only_missing_tables_fall_back_to_the_password_alone(world, monkeypatch):
    """The fallback exists for a server whose migrations were switched off (the two-step tables do not exist).
    Any other database error while asking "is this account enrolled?" must stop the sign-in, not open it."""
    from sqlalchemy.exc import OperationalError, ProgrammingError
    from app import mfa_db

    def failing(error):
        def raise_it(db, user_id):
            raise error
        return raise_it

    with TestClient(app, raise_server_exceptions=False) as client:
        monkeypatch.setattr(mfa_db, 'is_enrolled', failing(ProgrammingError('SELECT 1', {}, Exception('relation "user_mfa" does not exist'))))
        missing = login(client, world['admin_a']['email'])
        assert missing.status_code == 200 and missing.json()['access_token']

        monkeypatch.setattr(mfa_db, 'is_enrolled', failing(OperationalError('SELECT 1', {}, Exception('server closed the connection unexpectedly'))))
        broken = login(client, world['admin_a']['email'])
        assert broken.status_code == 500 and 'access_token' not in broken.text


def test_every_two_step_route_needs_a_session(world):
    with TestClient(app) as client:
        for method, path in (('get', '/api/v1/auth/mfa'), ('post', '/api/v1/auth/mfa/enroll'), ('post', '/api/v1/auth/mfa/confirm'),
                             ('post', '/api/v1/auth/mfa/recovery-codes'), ('post', '/api/v1/auth/mfa/disable'),
                             ('get', f"/api/v1/users/{world['admin_a']['id']}/mfa"), ('post', f"/api/v1/users/{world['admin_a']['id']}/mfa/reset")):
            reply = getattr(client, method)(path, **({'json': {'password': 'x', 'code': '123456'}} if method == 'post' else {}))
            assert reply.status_code == 401, (path, reply.status_code)


def test_enrol_confirm_then_sign_in_needs_the_code(world, mfa_on, clock):
    email = world['admin_a']['email']
    with TestClient(app) as client:
        headers = bearer(login(client, email).json()['access_token'])
        assert client.post('/api/v1/auth/mfa/enroll', json={'password': 'wrong-password-123'}, headers=headers).status_code == 401
        assert client.post('/api/v1/auth/mfa/enroll', json={}, headers=headers).status_code == 401
        started = client.post('/api/v1/auth/mfa/enroll', json={'password': PASSWORD}, headers=headers)
        assert started.status_code == 200, started.text
        body = started.json()
        secret = base64.b32decode(body['secret'])
        assert body['otpauth_uri'].startswith('otpauth://totp/Nuqati:') and 'secret=' + body['secret'] in body['otpauth_uri']
        assert body['secret_grouped'].replace(' ', '') == body['secret']
        # not active yet: signing in still needs only the password
        assert client.get('/api/v1/auth/mfa', headers=headers).json()['enabled'] is False
        assert 'access_token' in login(client, email).json()

        assert client.post('/api/v1/auth/mfa/confirm', json={'code': wrong_code(secret, clock)}, headers=headers).status_code == 401
        assert 'access_token' in login(client, email).json(), 'a wrong confirmation changes nothing'
        done = client.post('/api/v1/auth/mfa/confirm', json={'code': code_now(secret, clock)}, headers=headers)
        assert done.status_code == 200, done.text
        codes = done.json()['recovery_codes']
        assert len(codes) == 10 and len(set(codes)) == 10 and all(re.fullmatch(r'[A-Z2-9]{4}(-[A-Z2-9]{4}){2}', c) for c in codes)
        status = client.get('/api/v1/auth/mfa', headers=headers).json()
        assert status['enabled'] is True and status['recovery_codes_remaining'] == 10 and status['pending_setup'] is False

        token = challenge(client, email)
        assert client.get('/api/v1/auth/me', headers=bearer(token)).status_code == 401, 'the challenge is not a session'
        assert second_step(client, token, wrong_code(secret, clock)).status_code == 401
        assert second_step(client, token, code_now(secret, clock)).status_code == 401, 'the step used to confirm cannot be used again'
        clock.advance()
        ok = second_step(client, token, code_now(secret, clock))
        assert ok.status_code == 200, ok.text
        assert ok.json()['user']['email'] == email and ok.json()['used_recovery_code'] is False
        assert client.get('/api/v1/auth/me', headers=bearer(ok.json()['access_token'])).status_code == 200
        assert second_step(client, token, code_now(secret, clock)).status_code == 401, 'and a code works once'

    actions = {(row['action'], row['outcome']) for row in audit_rows(actor_user_id=world['admin_a']['id'])}
    assert {('auth.login', 'pending'), ('auth.login', 'ok'), ('auth.mfa', 'failed'), ('auth.mfa', 'ok'),
            ('auth.mfa_enroll', 'ok'), ('auth.mfa_enroll', 'failed')} <= actions
    everything = ' '.join(str(dict(r)) for r in audit_rows(actor_user_id=world['admin_a']['id']))
    assert body['secret'] not in everything and PASSWORD not in everything and codes[0] not in everything


def test_a_recovery_code_works_once_in_any_notation(world, mfa_on, clock):
    email = world['admin_a']['email']
    with TestClient(app) as client:
        secret, codes = enrol(client, email, clock)
        written = codes[3].lower().replace('-', ' ')
        first = second_step(client, challenge(client, email), written)
        assert first.status_code == 200 and first.json()['used_recovery_code'] is True and first.json()['recovery_codes_remaining'] == 9
        assert second_step(client, challenge(client, email), codes[3]).status_code == 401, 'used already'
        again = second_step(client, challenge(client, email), codes[4])
        assert again.status_code == 200 and again.json()['recovery_codes_remaining'] == 8
        headers = bearer(again.json()['access_token'])
        assert client.get('/api/v1/auth/mfa', headers=headers).json()['recovery_codes_remaining'] == 8

        # new codes replace all old ones, and need the password and a code
        assert client.post('/api/v1/auth/mfa/recovery-codes', json={'password': 'wrong-password-123', 'code': codes[5]}, headers=headers).status_code == 401
        renewed = client.post('/api/v1/auth/mfa/recovery-codes', json={'password': PASSWORD, 'code': codes[5]}, headers=headers)
        assert renewed.status_code == 200, renewed.text
        fresh = renewed.json()['recovery_codes']
        assert len(fresh) == 10 and not set(fresh) & set(codes)
        assert second_step(client, challenge(client, email), codes[6]).status_code == 401, 'the old codes are gone'
        assert second_step(client, challenge(client, email), fresh[0]).status_code == 200
    with SessionLocal() as db:
        rows = db.execute(text('SELECT salt, code_hash FROM user_mfa_recovery_codes WHERE user_id=:id'), {'id': world['admin_a']['id']}).all()
    assert len(rows) == 10
    assert not any(fresh_code.replace('-', '') in (row.code_hash + row.salt) for row in rows for fresh_code in fresh)


def test_wrong_codes_lock_the_second_step_even_for_the_right_code(world, mfa_on, clock):
    email = world['admin_a']['email']
    with TestClient(app) as client:
        secret, _ = enrol(client, email, clock)
        clock.advance()
        token = challenge(client, email)
        for _ in range(5):
            assert second_step(client, token, wrong_code(secret, clock)).status_code == 401
        locked = second_step(client, token, code_now(secret, clock))
        assert locked.status_code == 429 and int(locked.headers['Retry-After']) > 10 * 60, locked.text
        assert stored(world['admin_a']['id'])['failed_count'] == 5
        with SessionLocal() as db:  # the lock runs out
            db.execute(text("UPDATE user_mfa SET locked_until = now() - interval '1 second' WHERE user_id=:id"), {'id': world['admin_a']['id']})
            db.commit()
        ok = second_step(client, token, code_now(secret, clock))
        assert ok.status_code == 200, ok.text
        row = stored(world['admin_a']['id'])
        assert row['failed_count'] == 0 and row['locked_until'] is None
    assert any(r['outcome'] == 'locked' for r in audit_rows(action='auth.mfa', actor_user_id=world['admin_a']['id']))


def test_a_required_role_gets_a_session_only_after_setup(world, mfa_on, clock, monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_REQUIRED_ROLES', 'company_admin')
    email = world['admin_a']['email']
    with TestClient(app) as client:
        reply = login(client, email)
        assert reply.status_code == 200 and reply.json().get('mfa_setup_required') is True and 'access_token' not in reply.json()
        setup = bearer(reply.json()['mfa_token'])
        assert client.get('/api/v1/auth/me', headers=setup).status_code == 401, 'the setup token is not a session'
        assert client.get('/api/v1/users', headers=setup).status_code == 401
        status = client.get('/api/v1/auth/mfa', headers=setup).json()
        assert status['required'] is True and status['enabled'] is False
        started = client.post('/api/v1/auth/mfa/enroll', json={}, headers=setup)
        assert started.status_code == 200, started.text
        secret = base64.b32decode(started.json()['secret'])
        assert client.post('/api/v1/auth/mfa/confirm', json={'code': wrong_code(secret, clock)}, headers=setup).status_code == 401
        done = client.post('/api/v1/auth/mfa/confirm', json={'code': code_now(secret, clock)}, headers=setup)
        assert done.status_code == 200, done.text
        assert len(done.json()['recovery_codes']) == 10 and done.json()['user']['email'] == email
        assert client.get('/api/v1/auth/me', headers=bearer(done.json()['access_token'])).status_code == 200
        # from now on the code is asked for, and the role cannot switch it off
        clock.advance()
        ok = second_step(client, challenge(client, email), code_now(secret, clock))
        assert ok.status_code == 200
        clock.advance()
        refused = client.post('/api/v1/auth/mfa/disable', json={'password': PASSWORD, 'code': code_now(secret, clock)}, headers=bearer(ok.json()['access_token']))
        assert refused.status_code == 403, refused.text
        # roles that are not listed keep signing in with the password
        assert 'access_token' in login(client, world['manager_a']['email']).json()


def test_a_step_token_is_for_its_own_step_only(world, mfa_on, clock, monkeypatch):
    monkeypatch.setenv('NUQATI_MFA_REQUIRED_ROLES', 'company_admin')
    with TestClient(app) as client:
        setup_token = login(client, world['admin_a']['email']).json()['mfa_token']
        assert second_step(client, setup_token, '123456').status_code == 401, 'a setup token is not a sign-in challenge'
        assert second_step(client, 'x' * 40, '123456').status_code == 401
    monkeypatch.delenv('NUQATI_MFA_REQUIRED_ROLES')
    with TestClient(app) as client:
        secret, _ = enrol(client, world['admin_a']['email'], clock)
        challenge_token = challenge(client, world['admin_a']['email'])
        assert client.get('/api/v1/auth/mfa', headers=bearer(challenge_token)).status_code == 401
        assert client.post('/api/v1/auth/mfa/enroll', json={}, headers=bearer(challenge_token)).status_code == 401


def test_changing_the_authenticator_needs_the_password_and_the_current_code(world, mfa_on, clock):
    email = world['admin_a']['email']
    with TestClient(app) as client:
        old_secret, codes = enrol(client, email, clock)
        clock.advance()
        headers = bearer(second_step(client, challenge(client, email), code_now(old_secret, clock)).json()['access_token'])
        assert client.post('/api/v1/auth/mfa/enroll', json={'password': PASSWORD}, headers=headers).status_code == 422
        assert client.post('/api/v1/auth/mfa/enroll', json={'password': PASSWORD, 'code': wrong_code(old_secret, clock)}, headers=headers).status_code == 401
        clock.advance()
        started = client.post('/api/v1/auth/mfa/enroll', json={'password': PASSWORD, 'code': code_now(old_secret, clock)}, headers=headers)
        assert started.status_code == 200, started.text
        new_secret = base64.b32decode(started.json()['secret'])
        assert new_secret != old_secret
        # until the new one is confirmed the old one is the only one that works
        clock.advance()
        assert second_step(client, challenge(client, email), code_now(old_secret, clock)).status_code == 200
        assert client.post('/api/v1/auth/mfa/confirm', json={'code': wrong_code(new_secret, clock)}, headers=headers).status_code == 401
        done = client.post('/api/v1/auth/mfa/confirm', json={'code': code_now(new_secret, clock)}, headers=headers)
        assert done.status_code == 200 and len(done.json()['recovery_codes']) == 10
        clock.advance()
        assert second_step(client, challenge(client, email), code_now(old_secret, clock)).status_code == 401, 'the old authenticator is retired'
        assert second_step(client, challenge(client, email), code_now(new_secret, clock)).status_code == 200
        assert second_step(client, challenge(client, email), codes[0]).status_code == 401, 'and so are the old recovery codes'


def test_a_user_can_switch_it_off_with_password_and_code_and_sessions_end(world, mfa_on, clock):
    email = world['admin_a']['email']
    with TestClient(app) as client:
        secret, _ = enrol(client, email, clock)
        clock.advance()
        token = second_step(client, challenge(client, email), code_now(secret, clock)).json()['access_token']
        headers = bearer(token)
        clock.advance()
        assert client.post('/api/v1/auth/mfa/disable', json={'password': 'wrong-password-123', 'code': code_now(secret, clock)}, headers=headers).status_code == 401
        assert client.post('/api/v1/auth/mfa/disable', json={'password': PASSWORD, 'code': wrong_code(secret, clock)}, headers=headers).status_code == 401
        off = client.post('/api/v1/auth/mfa/disable', json={'password': PASSWORD, 'code': code_now(secret, clock)}, headers=headers)
        assert off.status_code == 200 and off.json()['sign_in_again'] is True, off.text
        assert client.get('/api/v1/auth/me', headers=headers).status_code == 401, 'sessions ended'
        assert 'access_token' in login(client, email).json()
    assert stored(world['admin_a']['id']) is None
    with SessionLocal() as db:
        assert db.execute(text('SELECT count(*) FROM user_mfa_recovery_codes WHERE user_id=:id'), {'id': world['admin_a']['id']}).scalar() == 0
    assert audit_rows(action='auth.mfa_disable', actor_user_id=world['admin_a']['id'])


def test_only_a_super_admin_resets_another_persons_two_step_sign_in(world, mfa_on, clock):
    target = world['admin_a']
    with TestClient(app) as client:
        enrol(client, target['email'], clock)
        super_headers = bearer(login(client, world['super']['email']).json()['access_token'])
        manager_headers = bearer(login(client, world['manager_a']['email']).json()['access_token'])
        other_admin = bearer(login(client, world['admin_b']['email']).json()['access_token'])
        for headers in (manager_headers, other_admin):
            assert client.post(f"/api/v1/users/{target['id']}/mfa/reset", headers=headers).status_code == 403
            assert client.get(f"/api/v1/users/{target['id']}/mfa", headers=headers).status_code == 403
        assert client.get(f"/api/v1/users/{target['id']}/mfa", headers=super_headers).json() == {'available': True, 'enabled': True, 'required': False}
        assert client.post(f"/api/v1/users/{world['super']['id']}/mfa/reset", headers=super_headers).status_code == 409, 'not on yourself'
        assert client.post('/api/v1/users/99999999/mfa/reset', headers=super_headers).status_code == 404
        assert stored(target['id']) is not None, 'refused requests change nothing'
        reset = client.post(f"/api/v1/users/{target['id']}/mfa/reset", headers=super_headers)
        assert reset.status_code == 200, reset.text
        assert stored(target['id']) is None
        assert client.get(f"/api/v1/users/{target['id']}/mfa", headers=super_headers).json()['enabled'] is False
        assert 'access_token' in login(client, target['email']).json(), 'the person can sign in with the password and set it up again'
    row = audit_rows(action='auth.mfa_reset', actor_user_id=world['super']['id'])[-1]
    assert row['target_id'] == str(target['id']) and row['target_type'] == 'user' and row['company_id'] == world['companies'][0]


def test_the_secret_is_stored_encrypted_and_a_key_rotation_re_encrypts_it(world, mfa_on, clock, monkeypatch):
    email, user_id = world['admin_a']['email'], world['admin_a']['id']
    with TestClient(app) as client:
        secret, _ = enrol(client, email, clock)
        row = stored(user_id)
        assert row['secret_enc'].startswith('v1:') and row['pending_secret_enc'] is None
        assert mfa.secret_text(secret) not in row['secret_enc'] and secret not in base64.urlsafe_b64decode(row['secret_enc'][3:])
        assert mfa.decrypt_secret(row['secret_enc'], user_id) == (secret, False)
        before = row['secret_enc']

        # rotation: new key, old one as PREVIOUS -> still works and the secret is stored again under the new key
        monkeypatch.setenv('NUQATI_MFA_KEY', OTHER_KEY)
        monkeypatch.setenv('NUQATI_MFA_KEY_PREVIOUS', KEY)
        clock.advance()
        assert second_step(client, challenge(client, email), code_now(secret, clock)).status_code == 200
        after = stored(user_id)['secret_enc']
        assert after != before
        monkeypatch.delenv('NUQATI_MFA_KEY_PREVIOUS')
        assert mfa.decrypt_secret(after, user_id) == (secret, False)


def test_a_lost_key_fails_closed_and_never_lets_a_password_through(world, mfa_on, clock, monkeypatch):
    email = world['admin_a']['email']
    with TestClient(app) as client:
        secret, codes = enrol(client, email, clock)
        clock.advance()
        monkeypatch.setenv('NUQATI_MFA_KEY', OTHER_KEY)  # the key changed without keeping the old one
        token = challenge(client, email)
        lost = second_step(client, token, code_now(secret, clock))
        assert lost.status_code == 503 and 'access_token' not in lost.json()
        assert second_step(client, token, codes[0]).status_code == 503, 'recovery codes need the key as well'
        # the key is removed altogether: the account is still asked for a code, never let in with the password alone
        monkeypatch.delenv('NUQATI_MFA_KEY')
        assert challenge(client, email)
        monkeypatch.setenv('NUQATI_MFA_KEY', KEY)
        assert second_step(client, challenge(client, email), code_now(secret, clock)).status_code == 200, 'the right key brings it back'
    assert any(r['outcome'] == 'error' for r in audit_rows(action='auth.mfa', actor_user_id=world['admin_a']['id']))


def test_deleting_an_account_removes_its_two_step_data(world, mfa_on, clock):
    target = world['admin_a']
    with TestClient(app) as client:
        enrol(client, target['email'], clock)
        headers = bearer(login(client, world['super']['email']).json()['access_token'])
        # the sign-in of an enrolled admin needs a code: the super admin deletes the account while it is enrolled
        assert client.delete(f"/api/v1/users/{target['id']}", headers=headers).status_code == 200
    assert stored(target['id']) is None
    with SessionLocal() as db:
        assert db.execute(text('SELECT count(*) FROM user_mfa_recovery_codes WHERE user_id=:id'), {'id': target['id']}).scalar() == 0


def test_the_server_command_resets_an_account_nobody_can_reach(world, mfa_on, clock, capsys):
    from app import mfa_tools

    target = world['super']
    with TestClient(app) as client:
        secret, _ = enrol(client, target['email'], clock)
        clock.advance()
        old_session = second_step(client, challenge(client, target['email']), code_now(secret, clock)).json()['access_token']
        assert client.get('/api/v1/auth/me', headers=bearer(old_session)).status_code == 200
        assert mfa_tools.main(['status', target['email'].upper()]) == 0
        assert 'ON' in capsys.readouterr().out
        assert mfa_tools.main(['status', 'nobody-' + secrets.token_hex(4) + '@test.invalid']) == 1
        assert mfa_tools.main(['reset']) == 2 and mfa_tools.main(['wipe', target['email']]) == 2
        assert stored(target['id']) is not None, 'a refused command changes nothing'
        assert mfa_tools.main(['reset', target['email']]) == 0
        assert 'removed' in capsys.readouterr().out
        assert stored(target['id']) is None
        assert client.get('/api/v1/auth/me', headers=bearer(old_session)).status_code == 401, 'sessions ended'
        assert 'access_token' in login(client, target['email']).json()
    row = audit_rows(action='auth.mfa_reset', target_id=str(target['id']))[-1]
    assert row['actor_user_id'] is None and '"via":"server command"' in row['detail']
