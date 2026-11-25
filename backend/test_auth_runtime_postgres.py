"""Live FastAPI integration checks. Requires a *dedicated* PostgreSQL test database.

    NUQATI_TEST_DATABASE_URL=postgresql+psycopg2://.../nuqati_test \
    PYTHONPATH=backend pytest -q backend/test_auth_runtime_postgres.py

No production database is ever used. This module does not modify the main instance.
"""
import os
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
from sqlalchemy import func, select
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
