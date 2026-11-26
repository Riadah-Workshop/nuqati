"""Rate limits on the real application and a real PostgreSQL (Phase 4.1, finding S9).

    NUQATI_TEST_DATABASE_URL=postgresql+psycopg2://.../nuqati_test \
    PYTHONPATH=backend pytest -q backend/test_rate_limits_postgres.py

The limiter's own behaviour is covered in test_rate_limits.py. Here: the routes really answer 429 with Retry-After in
enforce mode, let everything through in log and off mode, count per user and per scope, run after authentication, and
a refused request does no database work.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit

import pytest

URL = os.getenv('NUQATI_TEST_DATABASE_URL', '')
if not URL:
    pytest.skip('Set NUQATI_TEST_DATABASE_URL to a disposable PostgreSQL test database', allow_module_level=True)
if not URL.startswith('postgresql+') or 'test' not in urlsplit(URL).path.lower():
    raise RuntimeError('Refusing to run against a URL that is not a PostgreSQL TEST database')

os.environ['DATABASE_URL'] = URL
os.environ.setdefault('NUQATI_AUTH_SECRET', 'security-runtime-test-secret-only-2026-rotate')

from fastapi.testclient import TestClient
from sqlalchemy import text
from app import migrate  # noqa: E402
assert migrate.main(['upgrade']) == 0, 'migrations failed on the test database'
from app.main import app
from app import rate_limits as rl
from app.auth import encode_token
from app.db import SessionLocal
from app.models import Company, Driver, DriverAccount, DriverDeviceSession, Trip, User, Vehicle

DROP_PHRASE = 'Sample interval must be at least 0.7 seconds'


@pytest.fixture(autouse=True)
def fresh_limiter(monkeypatch):
    rl.LIMITER.reset()
    for name in rl.GROUP_ENV.values():
        monkeypatch.delenv(name, raising=False)
    yield
    rl.LIMITER.reset()


@pytest.fixture
def world():
    suffix = secrets.token_hex(5)
    with SessionLocal() as db:
        company = Company(name='RateLimit ' + suffix)
        db.add(company)
        db.flush()
        drivers = []
        for i in range(2):
            driver = Driver(company_id=company.id, full_name=f'Rate driver {i} {suffix}', phone='', status='active')
            db.add(driver)
            db.flush()
            user = User(company_id=company.id, role='driver', full_name=driver.full_name, is_active=True,
                        email=f'rl{i}-{suffix}@test.invalid', password_hash='not-a-real-hash-' + suffix)
            db.add(user)
            db.flush()
            session_id = secrets.token_hex(16)
            db.add_all([DriverAccount(driver_id=driver.id, user_id=user.id),
                        DriverDeviceSession(user_id=user.id, device_id='rl-' + suffix, session_id=session_id)])
            vehicle = Vehicle(company_id=company.id, plate_number=f'RL-{suffix}-{i}', assigned_driver_id=driver.id)
            db.add(vehicle)
            db.flush()
            trip = Trip(company_id=company.id, driver_id=driver.id, vehicle_id=vehicle.id, status='active',
                        started_at=datetime.now(timezone.utc) - timedelta(hours=1))
            db.add(trip)
            db.flush()
            drivers.append({'token': encode_token(user, session_id=session_id), 'trip_id': trip.id, 'user_id': user.id})
        admin = User(company_id=company.id, role='company_admin', full_name='Rate admin ' + suffix, is_active=True,
                     email=f'rladmin-{suffix}@test.invalid', password_hash='not-a-real-hash-' + suffix)
        db.add(admin)
        db.flush()
        data = {'company_id': company.id, 'drivers': drivers, 'admin': {'token': encode_token(admin), 'user_id': admin.id},
                'suffix': suffix}
        db.commit()
    yield data
    with SessionLocal() as db:
        cid = data['company_id']
        trip_ids = [d['trip_id'] for d in data['drivers']]
        db.execute(text('DELETE FROM mobile_gps_sample_receipts WHERE trip_id = ANY(:t)'), {'t': trip_ids})
        for table in ('driving_events', 'driver_locations', 'mobile_tracking_heartbeat', 'trips'):
            db.execute(text(f'DELETE FROM {table} WHERE company_id=:c'), {'c': cid})
        db.execute(text('UPDATE vehicles SET assigned_driver_id=NULL WHERE company_id=:c'), {'c': cid})
        db.execute(text('DELETE FROM vehicles WHERE company_id=:c'), {'c': cid})
        user_ids = [d['user_id'] for d in data['drivers']] + [data['admin']['user_id']]
        db.execute(text('DELETE FROM driver_device_sessions WHERE user_id = ANY(:u)'), {'u': user_ids})
        db.execute(text('DELETE FROM driver_accounts WHERE user_id = ANY(:u)'), {'u': user_ids})
        db.execute(text('DELETE FROM security_audit WHERE company_id=:c'), {'c': cid})
        db.execute(text('DELETE FROM users WHERE id = ANY(:u)'), {'u': user_ids})
        db.execute(text('DELETE FROM drivers WHERE company_id=:c'), {'c': cid})
        db.execute(text('DELETE FROM companies WHERE id=:c'), {'c': cid})
        db.commit()


def auth(token):
    return {'Authorization': 'Bearer ' + token}


def heartbeat_payload():
    return {'screen_state': 'unlocked', 'trip_active': True, 'gps_fix_age_s': 3,
            'captured_at': datetime.now(timezone.utc).isoformat()}


def sample_payload(world_data, driver_index, n):
    return {'sample_id': f'rl-{world_data["suffix"]}-{driver_index}-{n:04d}',
            'captured_at': (datetime.now(timezone.utc) - timedelta(seconds=60 - n)).isoformat(),
            'latitude': 24.7 + n * 0.0003, 'longitude': 46.7, 'accuracy_m': 5, 'speed_kmh': 50}


def receipts(trip_id):
    with SessionLocal() as db:
        return db.execute(text('SELECT count(*) FROM mobile_gps_sample_receipts WHERE trip_id=:t'), {'t': trip_id}).scalar()


def tiny(monkeypatch, scope, capacity):
    monkeypatch.setitem(rl.RULES, scope, rl.Rule(capacity, 0.0001, rl.RULES[scope].group))


def test_enforce_answers_429_with_retry_after_and_a_text_the_phone_does_not_treat_as_a_dropped_point(world, monkeypatch):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_INGEST', 'enforce')
    tiny(monkeypatch, 'heartbeat', 2)
    with TestClient(app) as client:
        codes = [client.post('/api/v1/mobile/tracking-heartbeat', json=heartbeat_payload(),
                             headers=auth(world['drivers'][0]['token'])) for _ in range(3)]
    assert [r.status_code for r in codes] == [200, 200, 429]
    refused = codes[2]
    assert int(refused.headers['Retry-After']) >= 1
    assert 'Too many requests' in refused.json()['detail']
    assert DROP_PHRASE not in refused.text


def test_gps_samples_are_refused_before_any_database_write(world, monkeypatch):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_INGEST', 'enforce')
    tiny(monkeypatch, 'gps_sample', 1)
    first = world['drivers'][0]
    with TestClient(app) as client:
        url = f'/api/v1/mobile/trips/{first["trip_id"]}/sample'
        ok = client.post(url, json=sample_payload(world, 0, 1), headers=auth(first['token']))
        assert ok.status_code == 200 and ok.json()['accepted'] is True, ok.text
        assert receipts(first['trip_id']) == 1
        refused = client.post(url, json=sample_payload(world, 0, 2), headers=auth(first['token']))
        assert refused.status_code == 429
        assert receipts(first['trip_id']) == 1, 'a refused sample must not be stored'
        # the other driver has a bucket of their own
        second = world['drivers'][1]
        other = client.post(f'/api/v1/mobile/trips/{second["trip_id"]}/sample', json=sample_payload(world, 1, 1),
                            headers=auth(second['token']))
        assert other.status_code == 200, other.text


def test_log_mode_lets_everything_through(world, monkeypatch, caplog):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_INGEST', 'log')
    tiny(monkeypatch, 'heartbeat', 1)
    with TestClient(app) as client:
        codes = [client.post('/api/v1/mobile/tracking-heartbeat', json=heartbeat_payload(),
                             headers=auth(world['drivers'][0]['token'])).status_code for _ in range(5)]
    assert codes == [200] * 5
    assert 'WOULD_REFUSE' in caplog.text


def test_off_mode_lets_everything_through_and_counts_nothing(world, monkeypatch):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_INGEST', 'off')
    tiny(monkeypatch, 'heartbeat', 1)
    with TestClient(app) as client:
        codes = [client.post('/api/v1/mobile/tracking-heartbeat', json=heartbeat_payload(),
                             headers=auth(world['drivers'][0]['token'])).status_code for _ in range(5)]
    assert codes == [200] * 5
    assert rl.LIMITER.size() == 0


def test_ingestion_defaults_to_log_mode_so_a_new_release_cannot_refuse_a_phone(world, monkeypatch):
    tiny(monkeypatch, 'heartbeat', 1)  # no environment variable set
    with TestClient(app) as client:
        codes = [client.post('/api/v1/mobile/tracking-heartbeat', json=heartbeat_payload(),
                             headers=auth(world['drivers'][0]['token'])).status_code for _ in range(4)]
    assert codes == [200] * 4


def test_exports_are_enforced_by_default_and_counted_apart_from_report_screens(world, monkeypatch):
    tiny(monkeypatch, 'export', 1)
    admin = auth(world['admin']['token'])
    export = {'year': 2026, 'month': 11, 'format': 'csv', 'kind': 'rag'}
    with TestClient(app) as client:
        assert client.get('/api/v1/fleet/monthly-reports/export', params=export, headers=admin).status_code == 200
        refused = client.get('/api/v1/fleet/monthly-reports/export', params=export, headers=admin)
        assert refused.status_code == 429 and int(refused.headers['Retry-After']) >= 1
        # the report screen has its own bucket
        assert client.get('/api/v1/fleet/monthly-reports', params={'year': 2026, 'month': 11}, headers=admin).status_code == 200


def test_the_limit_applies_per_user_not_per_company(world, monkeypatch):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_REPORTS', 'enforce')
    tiny(monkeypatch, 'report', 1)
    params = {'year': 2026, 'month': 11}
    with TestClient(app) as client:
        assert client.get('/api/v1/fleet/monthly-reports', params=params, headers=auth(world['admin']['token'])).status_code == 200
        assert client.get('/api/v1/fleet/monthly-reports', params=params, headers=auth(world['admin']['token'])).status_code == 429
        # a driver of the same company is a different user (403 from the route itself, but not 429)
        other = client.get('/api/v1/fleet/monthly-reports', params=params, headers=auth(world['drivers'][0]['token']))
        assert other.status_code != 429


def test_requests_without_a_valid_login_are_answered_401_and_create_no_bucket(world, monkeypatch):
    monkeypatch.setenv('NUQATI_RATE_LIMIT_REPORTS', 'enforce')
    tiny(monkeypatch, 'export', 1)
    with TestClient(app) as client:
        for _ in range(5):
            assert client.get('/api/v1/fleet/monthly-reports/export',
                              params={'year': 2026, 'month': 11, 'format': 'csv', 'kind': 'rag'}).status_code == 401
            assert client.get('/api/v1/fleet/monthly-reports/export',
                              params={'year': 2026, 'month': 11, 'format': 'csv', 'kind': 'rag'},
                              headers=auth('garbage.token')).status_code == 401
    assert rl.LIMITER.size() == 0
