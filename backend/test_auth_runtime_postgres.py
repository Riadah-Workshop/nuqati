"""Live FastAPI integration checks. Requires a *dedicated* PostgreSQL test database.

    NUQATI_TEST_DATABASE_URL=postgresql+psycopg2://.../nuqati_test \
    PYTHONPATH=backend pytest -q backend/test_auth_runtime_postgres.py

No production database is ever used. This module does not modify the main instance.
"""
import os
import re
import secrets
from urllib.parse import urlsplit

import pytest

URL=os.getenv('NUQATI_TEST_DATABASE_URL','')
if not URL:
    pytest.skip('Set NUQATI_TEST_DATABASE_URL to a disposable PostgreSQL test database', allow_module_level=True)
if not URL.startswith('postgresql+') or 'test' not in urlsplit(URL).path.lower():
    raise RuntimeError('Refusing to run against a URL that is not a PostgreSQL TEST database')

os.environ['DATABASE_URL']=URL
os.environ.setdefault('NUQATI_AUTH_SECRET','security-runtime-test-secret-only-2026-rotate')

from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from app import migrate  # noqa: E402
assert migrate.main(['upgrade']) == 0, 'migrations failed on the test database'  # the app no longer creates tables
from app.main import app
from app.auth import hash_password
from app.db import SessionLocal
from app.models import Company, Driver, DriverMetadata, DriverAccount, DriverDeviceSession, User, Vehicle, MaintenanceSchedule, OdometerReading

@pytest.fixture
def sample_accounts():
    suffix=secrets.token_hex(5)
    phone='+9665'+''.join(str(secrets.randbelow(10)) for _ in range(8))
    iqama='1'+''.join(str(secrets.randbelow(10)) for _ in range(9))
    with SessionLocal() as db:
        a=Company(name='Security A '+suffix); b=Company(name='Security B '+suffix)
        db.add_all([a,b]);db.flush()
        d1=Driver(company_id=a.id,full_name='Alice '+suffix,phone=phone,status='active')
        d2=Driver(company_id=b.id,full_name='Bob '+suffix,phone=phone,status='active')
        db.add_all([d1,d2]);db.flush()
        u1=User(company_id=a.id,role='driver',full_name=d1.full_name,email='a-'+suffix+'@test.invalid',password_hash=hash_password('CorrectPasswordForAlice2026'),is_active=True)
        u2=User(company_id=b.id,role='driver',full_name=d2.full_name,email='b-'+suffix+'@test.invalid',password_hash=hash_password('CorrectPasswordForBob2026'),is_active=True)
        admin=User(company_id=a.id,role='company_admin',full_name='Company admin',email='admin-'+suffix+'@test.invalid',password_hash=hash_password('CompanyAdminPassword2026'),is_active=True)
        db.add_all([u1,u2,admin]);db.flush()
        db.add_all([DriverAccount(driver_id=d1.id,user_id=u1.id), DriverAccount(driver_id=d2.id,user_id=u2.id),DriverMetadata(driver_id=d1.id,id_number=iqama,site_name='A'), DriverMetadata(driver_id=d2.id,id_number=iqama,site_name='B')])
        db.commit()
        ids=(a.id,b.id,d1.id,d2.id,u1.id,u2.id,admin.id)
    yield {'phone':phone,'iqama':iqama,'ids':ids,'email':'admin-'+suffix+'@test.invalid'}
    with SessionLocal() as db:
        a,b,d1,d2,u1,u2,admin=ids
        for driver_id in [d1,d2]:
            link=db.scalar(select(DriverAccount).where(DriverAccount.driver_id==driver_id))
            if link:db.delete(link)
            meta=db.get(DriverMetadata,driver_id)
            if meta:db.delete(meta)
        db.flush()
        for id_ in [u1,u2,admin]:
            session=db.get(DriverDeviceSession,id_)
            if session: db.delete(session)
            db.delete(db.get(User,id_))
        db.flush()  # the models declare no relationships, so SQLAlchemy does not order these deletes by foreign key
        for id_ in [d1,d2]:db.delete(db.get(Driver,id_))
        db.flush()  # drivers must be gone before their companies are deleted
        for id_ in [a,b]:db.delete(db.get(Company,id_))
        db.commit()


def test_phone_and_iqama_duplicates_do_not_lock_out_different_passwords(sample_accounts):
    data=sample_accounts
    with TestClient(app) as client:
        for path,identifier in [('driver-phone-login',{'phone':data['phone']}),('driver-iqama-login',{'iqama':data['iqama']})]:
            for pwd in ['CorrectPasswordForAlice2026','CorrectPasswordForBob2026']:
                response=client.post('/api/v1/auth/'+path,json={**identifier,'password':pwd,'device_id':'unit-test-phone-'+pwd})
                assert response.status_code==200,response.text
                assert response.json()['access_token']


def test_driver_cannot_enumerate_fleet_lists(sample_accounts):
    a=sample_accounts
    with TestClient(app) as client:
        login=client.post('/api/v1/auth/driver-iqama-login',json={'iqama':a['iqama'],'password':'CorrectPasswordForAlice2026','device_id':'unit-test-scope-phone-Alice-2026'})
        assert login.status_code==200
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        for route in ['companies','drivers','vehicles','odometer-readings','maintenance-schedules']:
            response=client.get('/api/v1/'+route,headers=headers)
            assert response.status_code==403,(route,response.text)


def test_unknown_dashboard_login_and_rate_limiting(sample_accounts):
    with TestClient(app) as client:
        good=client.post('/api/v1/auth/login',json={'email':sample_accounts['email'],'password':'CompanyAdminPassword2026'})
        assert good.status_code==200
        # Separate random identity to avoid cross-test throttling collisions.
        nonexistent='unknown-'+secrets.token_hex(10)+'@test.invalid'
        statuses=[]
        for _ in range(12):
            r=client.post('/api/v1/auth/login',json={'email':nonexistent,'password':'wrong'} )
            statuses.append(r.status_code)
        assert 401 in statuses
        assert 429 in statuses


def test_maintenance_get_does_not_commit_or_create_rows(sample_accounts):
    with TestClient(app) as client:
        login=client.post('/api/v1/auth/login',json={'email':sample_accounts['email'],'password':'CompanyAdminPassword2026'})
        assert login.status_code==200
        with SessionLocal() as db:
            before=db.scalar(select(func.count()).select_from(MaintenanceSchedule))
        response=client.get('/api/v1/maintenance-schedules',headers={'Authorization':'Bearer '+login.json()['access_token']})
        assert response.status_code==200,response.text
        with SessionLocal() as db:
            after=db.scalar(select(func.count()).select_from(MaintenanceSchedule))
        assert before==after


def test_driver_device_lock_logout_revokes_tokens_and_admin_can_release(sample_accounts):
    d=sample_accounts
    first={'iqama':d['iqama'],'password':'CorrectPasswordForAlice2026','device_id':'secure-random-installation-aaaaaaaaaaaa'}
    second={**first,'device_id':'secure-random-installation-bbbbbbbbbbbb'}
    with TestClient(app) as client:
        url='/api/v1/auth/driver-iqama-login'
        a=client.post(url,json=first)
        assert a.status_code==200,a.text
        access=a.json()['access_token']; refresh=a.json()['refresh_token']
        again=client.post(url,json=first)
        assert again.status_code==200,again.text
        assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+access}).status_code==200
        blocked=client.post(url,json=second)
        assert blocked.status_code==409,blocked.text
        assert blocked.json()['detail']=='DRIVER_ALREADY_LOGGED_IN_ON_ANOTHER_DEVICE'
        out=client.post('/api/v1/auth/driver-logout',headers={'Authorization':'Bearer '+access})
        assert out.status_code==200,out.text
        assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+access}).status_code==401
        assert client.post('/api/v1/auth/driver-refresh',json={'refresh_token':refresh}).status_code==401
        b=client.post(url,json=second)
        assert b.status_code==200,b.text
        admin=client.post('/api/v1/auth/login',json={'email':d['email'],'password':'CompanyAdminPassword2026'})
        assert admin.status_code==200,admin.text
        released=client.post(f"/api/v1/drivers/{d['ids'][2]}/release-device-session",
                             headers={'Authorization':'Bearer '+admin.json()['access_token']})
        assert released.status_code==200,released.text
        assert released.json()['had_session'] is True
        assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+b.json()['access_token']}).status_code==401
        assert client.post(url,json=first).status_code==200


IQAMA_URL='/api/v1/auth/driver-iqama-login'

def _admin_headers(client,d):
    admin=client.post('/api/v1/auth/login',json={'email':d['email'],'password':'CompanyAdminPassword2026'})
    assert admin.status_code==200,admin.text
    return {'Authorization':'Bearer '+admin.json()['access_token']}


def _own_ip(monkeypatch):
    """The sign-in throttle also counts per client address, and every test client shares one. Give each of these tests
    its own address so they cannot use up each other's (or the older tests') allowance."""
    ip='198.51.100.'+str(20+secrets.randbelow(200))
    monkeypatch.setattr('app.auth_limits._client_ip',lambda request:ip)


def _alice(d,device,password='CorrectPasswordForAlice2026'):
    return {'iqama':d['iqama'],'password':password,'device_id':'secure-random-installation-'+device*12}


def test_admin_sees_whether_a_phone_holds_the_driver_session(sample_accounts,monkeypatch):
    _own_ip(monkeypatch)
    d=sample_accounts;alice,bob=d['ids'][2],d['ids'][3]
    with TestClient(app) as client:
        headers=_admin_headers(client,d)
        before=client.get(f'/api/v1/drivers/{alice}/device-session',headers=headers)
        assert before.status_code==200,before.text
        assert before.json()['linked'] is True and before.json()['active'] is False and before.json()['since'] is None
        login=client.post(IQAMA_URL,json=_alice(d,'a'))
        assert login.status_code==200,login.text
        during=client.get(f'/api/v1/drivers/{alice}/device-session',headers=headers).json()
        assert during['active'] is True and during['since'] and during['last_login_at']
        assert not ({'device_id','session_id'} & set(during)), 'device identifiers must never be shown'
        assert client.get(f'/api/v1/drivers/{bob}/device-session',headers=headers).status_code==403
        driver_headers={'Authorization':'Bearer '+login.json()['access_token']}
        assert client.get(f'/api/v1/drivers/{alice}/device-session',headers=driver_headers).status_code==403


def test_admin_reset_makes_a_temporary_password_signs_the_driver_out_and_can_free_the_phone(sample_accounts,monkeypatch):
    _own_ip(monkeypatch)
    d=sample_accounts;alice,bob=d['ids'][2],d['ids'][3]
    with TestClient(app) as client:
        headers=_admin_headers(client,d)
        first=client.post(IQAMA_URL,json=_alice(d,'a'))
        assert first.status_code==200,first.text
        access=first.json()['access_token'];refresh=first.json()['refresh_token']
        reset=client.post(f'/api/v1/drivers/{alice}/reset-password',json={},headers=headers)
        assert reset.status_code==200,reset.text
        assert reset.headers['cache-control']=='no-store'
        temporary=reset.json()['temporary_password']
        assert re.fullmatch(r'[A-HJ-NP-Za-km-z2-9]{4}(-[A-HJ-NP-Za-km-z2-9]{4}){2}',temporary),temporary
        assert reset.json()['released_device'] is False
        # everything the old session held stops working at once
        assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+access}).status_code==401
        assert client.post('/api/v1/auth/driver-refresh',json={'refresh_token':refresh}).status_code==401
        assert client.post(IQAMA_URL,json=_alice(d,'a')).status_code==401, 'the old password must not work'
        # the phone is still reserved: the same phone signs in with the temporary password, another one cannot yet
        assert client.post(IQAMA_URL,json=_alice(d,'b',temporary)).status_code==409
        assert client.post(IQAMA_URL,json=_alice(d,'a',temporary)).status_code==200
        # an administrator-chosen password, and the lost-phone case: the reservation is freed too
        typed=client.post(f'/api/v1/drivers/{alice}/reset-password',json={'new_password':'ChosenByTheAdmin2026','release_device':True},headers=headers)
        assert typed.status_code==200,typed.text
        assert 'temporary_password' not in typed.json() and typed.json()['released_device'] is True
        assert client.post(IQAMA_URL,json=_alice(d,'b','ChosenByTheAdmin2026')).status_code==200
        # rules: length, company boundary, role
        assert client.post(f'/api/v1/drivers/{alice}/reset-password',json={'new_password':'short'},headers=headers).status_code==422
        assert client.post(f'/api/v1/drivers/{bob}/reset-password',json={},headers=headers).status_code==403
        driver_token={'Authorization':'Bearer '+client.post(IQAMA_URL,json=_alice(d,'b','ChosenByTheAdmin2026')).json()['access_token']}
        assert client.post(f'/api/v1/drivers/{alice}/reset-password',json={},headers=driver_token).status_code==403
        with SessionLocal() as db:
            rows=db.execute(text("SELECT detail::text FROM security_audit WHERE action='driver.password_reset' AND target_id=:t"),{'t':str(alice)}).scalars().all()
        assert len(rows)>=2
        assert not any(temporary in r or 'ChosenByTheAdmin2026' in r for r in rows), 'a password must never reach the audit trail'


def test_driver_changes_their_own_password_in_the_app(sample_accounts,monkeypatch):
    _own_ip(monkeypatch)
    d=sample_accounts
    with TestClient(app) as client:
        login=client.post(IQAMA_URL,json=_alice(d,'a'))
        assert login.status_code==200,login.text
        headers={'Authorization':'Bearer '+login.json()['access_token']}
        url='/api/v1/mobile/change-password'
        old='CorrectPasswordForAlice2026';new='ANewPasswordForAlice2026'
        assert client.post(url,json={'current_password':'not-the-password','new_password':new},headers=headers).status_code==400
        assert client.post(url,json={'current_password':old,'new_password':old},headers=headers).status_code==400
        assert client.post(url,json={'current_password':old,'new_password':'short'},headers=headers).status_code==422
        assert client.post(url,json={'current_password':old,'new_password':new}).status_code==401
        done=client.post(url,json={'current_password':old,'new_password':new},headers=headers)
        assert done.status_code==200,done.text
        # the phone keeps its session; the old password is gone, the new one works
        assert client.get('/api/v1/auth/me',headers=headers).status_code==200
        assert client.post(IQAMA_URL,json=_alice(d,'a',old)).status_code==401
        assert client.post(IQAMA_URL,json=_alice(d,'a',new)).status_code==200
        # administrators use their own dashboard route, not this one
        assert client.post(url,json={'current_password':'CompanyAdminPassword2026','new_password':new},headers=_admin_headers(client,d)).status_code==403
