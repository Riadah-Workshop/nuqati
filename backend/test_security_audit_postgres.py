"""Live checks of the security audit trail, dashboard logout, secret rotation and API-docs switch.
Requires a *dedicated* PostgreSQL test database (same rules as test_auth_runtime_postgres.py):

    NUQATI_TEST_DATABASE_URL=postgresql+psycopg2://.../nuqati_test \
    PYTHONPATH=backend pytest -q backend/test_security_audit_postgres.py

Skipped when the variable is not set. Rows written to `security_audit` stay in the disposable test database.
"""
import os
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

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, text  # noqa: E402
from app import migrate  # noqa: E402
assert migrate.main(['upgrade']) == 0, 'migrations failed on the test database'  # the app no longer creates tables
from app.main import app  # noqa: E402
from app.auth import hash_password  # noqa: E402
from app.db import SessionLocal  # noqa: E402
from app.models import Company, Driver, MaintenanceSchedule, OdometerReading, User, Vehicle  # noqa: E402

PASSWORD = 'AuditTestPassword2026'


@pytest.fixture
def world():
    suffix = secrets.token_hex(5)
    with SessionLocal() as db:
        company_a = Company(name='Audit A ' + suffix)
        company_b = Company(name='Audit B ' + suffix)
        db.add_all([company_a, company_b])
        db.flush()

        def make(company, role, tag):
            return User(company_id=company.id, role=role, full_name=f'{tag} {suffix}', email=f'{tag}-{suffix}@test.invalid',
                        password_hash=hash_password(PASSWORD), is_active=True)

        admin_a, admin_b, manager_a = make(company_a, 'company_admin', 'admin-a'), make(company_b, 'company_admin', 'admin-b'), \
            make(company_a, 'fleet_manager', 'manager-a')
        db.add_all([admin_a, admin_b, manager_a])
        db.commit()
        ids = {'a': company_a.id, 'b': company_b.id, 'admin_a': admin_a.id, 'admin_b': admin_b.id, 'manager_a': manager_a.id,
               'admin_a_email': admin_a.email, 'admin_b_email': admin_b.email, 'manager_a_email': manager_a.email, 'suffix': suffix}
    yield ids
    with SessionLocal() as db:
        companies = [ids['a'], ids['b']]
        for model in (MaintenanceSchedule, OdometerReading, Vehicle, Driver):
            db.execute(delete(model).where(model.company_id.in_(companies)))
        db.execute(delete(User).where(User.id.in_([ids['admin_a'], ids['admin_b'], ids['manager_a']])))
        db.execute(delete(Company).where(Company.id.in_(companies)))
        db.commit()


def login(client, email, password=PASSWORD):
    return client.post('/api/v1/auth/login', json={'email': email, 'password': password})


def bearer(response):
    return {'Authorization': 'Bearer ' + response.json()['access_token']}


def audit_rows(**filters):
    clauses = ' AND '.join(f'{column}=:{column}' for column in filters) or 'TRUE'
    with SessionLocal() as db:
        return db.execute(text(f'SELECT * FROM security_audit WHERE {clauses} ORDER BY id'), filters).mappings().all()


def test_login_outcomes_are_audited_and_never_store_the_attempted_identifier(world):
    unknown = 'nobody-' + secrets.token_hex(6) + '@test.invalid'
    with TestClient(app) as client:
        assert login(client, world['admin_a_email']).status_code == 200
        assert login(client, world['admin_a_email'], 'wrong-password-123').status_code == 401
        assert login(client, unknown, 'wrong-password-123').status_code == 401
    outcomes = {row['outcome'] for row in audit_rows(action='auth.login', actor_user_id=world['admin_a'])}
    assert {'ok', 'failed'} <= outcomes
    ok_row = [r for r in audit_rows(action='auth.login', actor_user_id=world['admin_a']) if r['outcome'] == 'ok'][-1]
    assert ok_row['company_id'] == world['a'] and ok_row['actor_role'] == 'company_admin'
    with SessionLocal() as db:
        leaked = db.execute(text('SELECT count(*) FROM security_audit WHERE actor_email=:e OR detail LIKE :like OR target_id LIKE :like'),
                            {'e': unknown, 'like': '%' + unknown + '%'}).scalar()
        newest_unknown = db.execute(text("SELECT outcome, detail FROM security_audit WHERE action='auth.login' AND actor_user_id IS NULL "
                                         'ORDER BY id DESC LIMIT 1')).first()
    assert leaked == 0
    assert newest_unknown.outcome == 'failed' and '"known_account":false' in newest_unknown.detail
    everything = ' '.join(str(dict(r)) for r in audit_rows(actor_user_id=world['admin_a']))
    assert PASSWORD not in everything and 'wrong-password-123' not in everything


def test_logout_revokes_the_token_and_is_audited(world):
    with TestClient(app) as client:
        session = login(client, world['admin_a_email'])
        headers = bearer(session)
        assert client.get('/api/v1/auth/me', headers=headers).status_code == 200
        assert client.post('/api/v1/auth/logout', headers=headers).status_code == 200
        assert client.get('/api/v1/auth/me', headers=headers).status_code == 401
        assert client.post('/api/v1/auth/logout', headers=headers).status_code == 401
        # a new sign-in works again
        assert client.get('/api/v1/auth/me', headers=bearer(login(client, world['admin_a_email']))).status_code == 200
    assert len(audit_rows(action='auth.logout', actor_user_id=world['admin_a'])) >= 1


def test_security_audit_endpoint_is_company_scoped_and_admin_only(world):
    with TestClient(app) as client:
        admin_a = bearer(login(client, world['admin_a_email']))
        login(client, world['admin_b_email'])  # leaves an audit row that belongs to company B
        manager = bearer(login(client, world['manager_a_email']))

        assert client.get('/api/v1/security-audit').status_code == 401
        assert client.get('/api/v1/security-audit', headers=manager).status_code == 403

        own = client.get('/api/v1/security-audit', params={'limit': 500}, headers=admin_a)
        assert own.status_code == 200, own.text
        assert own.json() and {row['company_id'] for row in own.json()} == {world['a']}
        # asking for another company's rows does not widen the scope
        other = client.get('/api/v1/security-audit', params={'company_id': world['b'], 'limit': 500}, headers=admin_a)
        assert other.status_code == 200 and {row['company_id'] for row in other.json()} == {world['a']}
        assert client.get('/api/v1/security-audit', params={'limit': 0}, headers=admin_a).status_code == 422
        filtered = client.get('/api/v1/security-audit', params={'action': 'auth.login', 'outcome': 'ok'}, headers=admin_a).json()
        assert filtered and all(row['action'] == 'auth.login' and row['outcome'] == 'ok' for row in filtered)


def test_creating_and_editing_records_is_audited_and_responses_are_intact(world):
    """create_* writes the audit row between the commit and the refresh; the response must still serialize."""
    plate = 'AUD' + world['suffix'].upper()
    with TestClient(app) as client:
        headers = bearer(login(client, world['admin_a_email']))
        # creating drivers is a Super Admin action: a company admin is refused and nothing is recorded as created
        refused = client.post('/api/v1/drivers', json={'company_id': world['a'], 'full_name': 'Audit Driver ' + world['suffix']}, headers=headers)
        assert refused.status_code == 403, refused.text
        vehicle = client.post('/api/v1/vehicles', json={'company_id': world['a'], 'plate_number': plate, 'odometer_km': 1000}, headers=headers)
        assert vehicle.status_code == 201, vehicle.text
        assert vehicle.json()['plate_number'] == plate
        edited = client.patch(f"/api/v1/vehicles/{vehicle.json()['id']}", json={'make_model': 'Audit Model'}, headers=headers)
        assert edited.status_code == 200, edited.text
        assert edited.json()['make_model'] == 'Audit Model'
        # a conflicting edit must still answer 409, not 500 (the audit insert must not disturb the caller's session)
        second = client.post('/api/v1/vehicles', json={'company_id': world['a'], 'plate_number': plate + 'X'}, headers=headers)
        assert second.status_code == 201, second.text
        clash = client.patch(f"/api/v1/vehicles/{second.json()['id']}", json={'plate_number': plate}, headers=headers)
        assert clash.status_code == 409, clash.text
    actions = {row['action'] for row in audit_rows(actor_user_id=world['admin_a'])}
    assert {'vehicle.create', 'vehicle.update'} <= actions and 'driver.create' not in actions
    created = [r for r in audit_rows(action='vehicle.create', actor_user_id=world['admin_a'])][0]
    assert created['target_type'] == 'vehicle' and created['company_id'] == world['a']


def test_previous_secret_keeps_sessions_alive_during_rotation(world, monkeypatch):
    old_secret = os.environ['NUQATI_AUTH_SECRET']
    new_secret = 'rotated-secret-for-the-audit-test-0123456789abcdef'
    monkeypatch.delenv('NUQATI_AUTH_SECRET_PREVIOUS', raising=False)
    with TestClient(app) as client:
        old_headers = bearer(login(client, world['admin_a_email']))
        assert client.get('/api/v1/auth/me', headers=old_headers).status_code == 200

        monkeypatch.setenv('NUQATI_AUTH_SECRET', new_secret)  # rotated without a window
        assert client.get('/api/v1/auth/me', headers=old_headers).status_code == 401

        monkeypatch.setenv('NUQATI_AUTH_SECRET_PREVIOUS', old_secret)  # window open
        assert client.get('/api/v1/auth/me', headers=old_headers).status_code == 200
        new_headers = bearer(login(client, world['admin_a_email']))
        assert client.get('/api/v1/auth/me', headers=new_headers).status_code == 200

        monkeypatch.delenv('NUQATI_AUTH_SECRET_PREVIOUS')  # window closed
        assert client.get('/api/v1/auth/me', headers=old_headers).status_code == 401
        assert client.get('/api/v1/auth/me', headers=new_headers).status_code == 200


def test_api_docs_are_not_served_by_default():
    if os.environ.get('NUQATI_ENABLE_API_DOCS', '').strip().lower() in ('1', 'true', 'yes'):
        pytest.skip('API docs are enabled in this environment on purpose')
    with TestClient(app) as client:
        for path in ('/docs', '/redoc', '/openapi.json'):
            assert client.get(path).status_code == 404, path
