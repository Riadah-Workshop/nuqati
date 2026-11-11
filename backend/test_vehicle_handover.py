"""Regression for the additive online-only Nuqati vehicle handover API.

Run: DATABASE_URL=sqlite:////tmp/nuqati-handover-test.db pytest -q backend/test_vehicle_handover.py
Tests isolate handover from main.py so legacy fleet API remains untouched.
"""
import base64
import io
import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.db import Base, SessionLocal, engine, get_db
from app.auth import current_user
from app.models import Company, Driver, DriverAccount, Trip, User, Vehicle
from app.vehicle_handover import HandoverAssignment, HandoverInspection, HandoverPhoto, router

app = FastAPI()
app.include_router(router)
identity = {'user': None}
app.dependency_overrides[current_user] = lambda: identity['user']


def session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = session


def photo_data():
    stream = io.BytesIO()
    Image.new('RGB', (8, 8), (20, 140, 150)).save(stream, format='JPEG')
    return base64.b64encode(stream.getvalue()).decode('ascii')


PHOTO = photo_data()
REQUIRED = ['front', 'rear', 'left', 'right', 'cabin_front', 'cabin_rear', 'dashboard', 'odometer']


def payload(vehicle_id=1, km=2000, damage=None, missing=None, **kwargs):
    damage = damage or []
    data = dict(vehicle_id=vehicle_id, odometer_km=km, engine_status='normal', interior_status='normal',
                missing_items=missing or [], dashboard_warnings='', notes='Test condition report', acknowledged=True,
                damage_items=damage,
                photos=[dict(category=category, data_base64=PHOTO, mime_type='image/jpeg') for category in REQUIRED] +
                       [dict(category='damage', data_base64=PHOTO, mime_type='image/jpeg', note=d['area']) for d in damage])
    data.update(kwargs)
    return data


@pytest.fixture(autouse=True)
def seed():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        db.add_all([Company(id=1, name='Fleet A'), Company(id=2, name='Fleet B')])
        db.add_all([Driver(id=1,company_id=1,full_name='Driver A',status='active'),
                    Driver(id=2,company_id=1,full_name='Driver B',status='active'),
                    Driver(id=3,company_id=2,full_name='Other Company Driver',status='active')])
        db.add_all([Vehicle(id=1, company_id=1,plate_number='A-1234',make_model='Test car',odometer_km=1990),
                    Vehicle(id=2, company_id=1,plate_number='A-5678',make_model='Backup car'),
                    Vehicle(id=3, company_id=2,plate_number='B-0001',make_model='Other car')])
        db.add_all([User(id=i, email=f'user{i}@test.invalid',full_name=f'U{i}',password_hash='x',
                         role='driver' if i<=3 else ('fleet_manager' if i==4 else 'super_admin'),
                         company_id=(1 if i in [1,2,4] else 2 if i==3 else None)) for i in range(1,6)])
        db.add_all([DriverAccount(driver_id=i,user_id=i) for i in range(1,4)])
        db.commit()
    identity['user']=None
    yield
    Base.metadata.drop_all(bind=engine)


def act(user_id):
    with SessionLocal() as db:
        user = db.get(User,user_id)
        db.expunge(user)
    identity['user']=user


def test_clean_receipt_and_return_and_next_driver():
    with TestClient(app) as c:
        act(1)
        state=c.get('/api/v1/handover/driver/status')
        assert state.status_code == 200
        assert state.json()['vehicles'][0]['plate_number']=='A-1234'
        r=c.post('/api/v1/handover/driver/receive',json=payload())
        assert r.status_code==201, r.text
        assignment_id=r.json()['assignment_id']
        assert r.json()['status']=='active'
        with SessionLocal() as db:
            assert db.get(Vehicle,1).assigned_driver_id==1
            assert len(db.scalars(select(HandoverPhoto)).all())==8
            assert db.get(HandoverAssignment,assignment_id).receipt_inspection_id is not None
        act(2)
        assert c.post('/api/v1/handover/driver/receive',json=payload()).status_code==409
        act(1)
        assert c.post('/api/v1/handover/driver/receive',json=payload(vehicle_id=2)).status_code==409
        assert c.post('/api/v1/handover/driver/return',json=payload(km=2200)).json()['status']=='closed'
        with SessionLocal() as db: assert db.get(Vehicle,1).assigned_driver_id is None
        act(2)
        assert c.post('/api/v1/handover/driver/receive',json=payload(km=2200)).json()['status']=='active'
        with SessionLocal() as db:
            assert db.get(Vehicle,1).assigned_driver_id==2
            assert len(db.scalars(select(HandoverAssignment).where(HandoverAssignment.vehicle_id==1)).all())==2


def test_pending_receipt_supervisor_approval_and_flagged_return():
    with TestClient(app) as c:
        act(1)
        old_damage={'area':'front bumper','kind':'scratch','description':'pre-existing scratch','status':'existing'}
        r=c.post('/api/v1/handover/driver/receive',json=payload(damage=[old_damage]))
        assert r.status_code==201, r.text
        assert r.json()['status']=='pending_receipt'
        with SessionLocal() as db: assert db.get(Vehicle,1).assigned_driver_id is None
        receipt_id=r.json()['inspection_id']
        act(4)
        assert c.post(f'/api/v1/handover/inspections/{receipt_id}/review',json={'action':'approve','note':'Checked before use'}).json()['status']=='active'
        act(1)
        new_damage={'area':'right door','kind':'dent','description':'new visible dent','status':'new'}
        r=c.post('/api/v1/handover/driver/return',json=payload(km=2200,damage=[new_damage]))
        assert r.status_code==201, r.text
        assert r.json()['status']=='pending_return'
        return_id=r.json()['inspection_id']
        with SessionLocal() as db: assert db.get(Vehicle,1).assigned_driver_id==1
        act(4)
        assert c.post(f'/api/v1/handover/inspections/{return_id}/review',json={'action':'approve','note':'Damage documented; approve receipt'}).json()['status']=='closed'
        assert c.post(f'/api/v1/handover/inspections/{return_id}/review',json={'action':'approve'}).status_code==409
        with SessionLocal() as db: assert db.get(Vehicle,1).assigned_driver_id is None
        result=c.get('/api/v1/handover/dashboard')
        assert result.status_code==200 and result.json()['closed_count']==1
        doc=c.get(f'/api/v1/handover/assignments/{r.json()["assignment_id"]}/report')
        assert doc.status_code==200 and doc.content.startswith(b'%PDF')


def test_online_inspection_validation_and_company_security():
    with TestClient(app) as c:
        act(1)
        invalid=payload()
        invalid['photos'].pop()
        assert c.post('/api/v1/handover/driver/receive',json=invalid).status_code==422
        wrong_company=payload(vehicle_id=3)
        assert c.post('/api/v1/handover/driver/receive',json=wrong_company).status_code==404
        r=c.post('/api/v1/handover/driver/receive',json=payload())
        photo_id=c.get(f'/api/v1/handover/inspections/{r.json()["inspection_id"]}').json()['photos'][0]['id']
        act(3)
        assert c.get(f'/api/v1/handover/photos/{photo_id}').status_code==403
        assert c.get(f'/api/v1/handover/inspections/{r.json()["inspection_id"]}').status_code==403
        assert c.get('/api/v1/handover/dashboard').status_code==403
        act(4)
        assert c.get(f'/api/v1/handover/photos/{photo_id}').status_code==200


def test_trip_active_blocks_return_and_admin_override_is_audited():
    with TestClient(app) as c:
        act(1)
        assert c.post('/api/v1/handover/driver/receive',json=payload()).status_code==201
        with SessionLocal() as db:
            db.add(Trip(company_id=1, driver_id=1, vehicle_id=1, status='active'))
            db.commit()
        assert c.post('/api/v1/handover/driver/return',json=payload(km=2100)).status_code==409
        act(4)
        assert c.post('/api/v1/handover/vehicles/1/administrative-release',json={'reason':'Vehicle needs reassignment due to leave'}).status_code==409
        with SessionLocal() as db:
            trip=db.scalar(select(Trip))
            trip.status='completed'
            db.commit()
        r=c.post('/api/v1/handover/vehicles/1/administrative-release',json={'reason':'Vehicle needs reassignment due to leave'})
        assert r.status_code==200
        with SessionLocal() as db:
            assert db.get(Vehicle,1).assigned_driver_id is None
            assert db.scalar(select(HandoverAssignment)).status=='administratively_released'


def test_existing_link_can_register_initial_baseline():
    with SessionLocal() as db:
        db.get(Vehicle,1).assigned_driver_id=1
        db.commit()
    with TestClient(app) as c:
        act(1)
        state=c.get('/api/v1/handover/driver/status').json()
        assert state['legacy_vehicle']['plate_number']=='A-1234'
        assert c.post('/api/v1/handover/driver/receive',json=payload()).json()['status']=='active'
        assert c.post('/api/v1/handover/driver/return',json=payload(km=2200)).json()['status']=='closed'
