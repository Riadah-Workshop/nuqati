"""Driver accounts and links, `/mobile/me`, company driver logo and branding for the driver app."""

import json

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..api_app import app
from ..audit import audit
from ..auth import allow, current_user, hash_password, scope
from ..db import get_db
from ..models import AppSetting, Company, Driver, DriverAccount, Trip, User, Vehicle
from .admin_records import _validate_company_driver_logo
from .shared import _company_logo_setting, own_driver

class DriverCredentials(BaseModel):
    driver_id: int
    email: str
    full_name: str = Field(min_length=2)
    password: str = Field(min_length=12)

@app.post('/api/v1/driver-accounts', status_code=201)
def create_driver_account(data:DriverCredentials, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    d=db.get(Driver,data.driver_id)
    if not d: raise HTTPException(404,'Driver not found')
    if db.scalar(select(DriverAccount).where(DriverAccount.driver_id==d.id)): raise HTTPException(409,'Driver already has an account')
    u=User(email=data.email.strip().lower(),full_name=data.full_name,password_hash=hash_password(data.password),role='driver',company_id=d.company_id)
    db.add(u)
    try:
        db.flush(); db.add(DriverAccount(driver_id=d.id,user_id=u.id))
        audit(db,'driver_account.create',actor=user,target_type='driver',target_id=d.id,company_id=d.company_id)
        db.commit()
    except IntegrityError:
        db.rollback(); raise HTTPException(409,'Email already exists')
    return {'driver_id':d.id,'user_id':u.id,'email':u.email}

class DriverLinkIn(BaseModel):
    user_id: int
    vehicle_id: int | None = None

@app.get('/api/v1/driver-accounts')
def list_driver_links(db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    q=select(DriverAccount,Driver,User).join(Driver,Driver.id==DriverAccount.driver_id).join(User,User.id==DriverAccount.user_id)
    if user.role!='super_admin': q=q.where(Driver.company_id==user.company_id)
    return [{'driver_id':d.id,'user_id':u.id,'email':u.email,'vehicle_id':db.scalar(select(Vehicle.id).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))} for a,d,u in db.execute(q).all()]

@app.put('/api/v1/drivers/{driver_id}/account-link')
def link_existing_driver(driver_id:int, data:DriverLinkIn, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    d=db.get(Driver,driver_id)
    if not d: raise HTTPException(404,'Driver not found')
    scope(user,d.company_id)
    u=db.get(User,data.user_id)
    if not u or u.role!='driver' or not u.is_active or u.company_id!=d.company_id: raise HTTPException(422,'Select an active driver login from the same company')
    existing=db.scalar(select(DriverAccount).where(DriverAccount.driver_id==d.id))
    other=db.scalar(select(DriverAccount).where(DriverAccount.user_id==u.id))
    if other and other.driver_id!=d.id: raise HTTPException(409,'This login is already linked to another driver')
    if existing and existing.user_id!=u.id: raise HTTPException(409,'This driver already has a different login; contact Super Admin')
    v=None
    if data.vehicle_id is not None:
        from ..vehicle_handover import enforce_managed_link
        current_vehicle=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id))
        if not current_vehicle or current_vehicle.id!=data.vehicle_id:
            enforce_managed_link(db,driver_id=d.id,vehicle_id=data.vehicle_id)
        v=db.get(Vehicle,data.vehicle_id)
        if not v or v.company_id!=d.company_id: raise HTTPException(422,'Vehicle must belong to the same company')
        if v.assigned_driver_id not in (None,d.id): raise HTTPException(409,'Vehicle is assigned to another driver')
        previous=db.scalars(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.id!=v.id)).all()
        if any(db.scalar(select(Trip.id).where(Trip.vehicle_id==old.id,Trip.status=='active')) for old in previous): raise HTTPException(409,'Finish the active trip before changing the vehicle')
        for old in previous: old.assigned_driver_id=None
        v.assigned_driver_id=d.id
    if not existing: db.add(DriverAccount(driver_id=d.id,user_id=u.id))
    audit(db,'driver_account.link',actor=user,target_type='driver',target_id=d.id,company_id=d.company_id,detail={'vehicle_id':v.id if v else None})
    try: db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,'Driver or login already linked')
    return {'driver_id':d.id,'user_id':u.id,'vehicle_id':v.id if v else None,'status':'linked'}

@app.get('/api/v1/mobile/me')
def mobile_me(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))
    return {'driver_id':d.id,'full_name':d.full_name,'company_id':d.company_id,'company_name':db.get(Company,d.company_id).name if db.get(Company,d.company_id) else '', 'vehicle':{'id':v.id,'plate_number':v.plate_number,'make_model':v.make_model,'year':v.year,'door_number':v.door_number} if v else None}

# Company driver-app logos: keep one setting per company without altering fleet data.
# Dashboard and mobile clients already depend on these routes.
class CompanyDriverLogoIn(BaseModel):
    logo_data: str = Field(default='', max_length=300000)

def _company_driver_logo(db: Session, company_id: int) -> str:
    row = db.get(AppSetting, _company_logo_setting(company_id))
    if not row:
        return ''
    # Existing records may store a simple data URL or an object.
    value = row.value or ''
    if value.startswith('data:image/'):
        return value
    try:
        return str(json.loads(value).get('logo_data', ''))
    except (ValueError, TypeError, AttributeError):
        return ''

@app.get('/api/v1/companies/{company_id}/driver-logo')
def get_company_driver_logo(company_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager', 'representative', 'workshop_staff')
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, 'Company not found')
    if user.role != 'super_admin' and user.company_id != company_id:
        raise HTTPException(403, 'Company access denied')
    return {'company_id': company_id, 'logo_data': _company_driver_logo(db, company_id)}

@app.put('/api/v1/companies/{company_id}/driver-logo')
def put_company_driver_logo(company_id: int, payload: CompanyDriverLogoIn,
                            db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, 'super_admin', 'company_admin')
    company = db.get(Company, company_id)
    if not company:
        raise HTTPException(404, 'Company not found')
    if user.role != 'super_admin' and user.company_id != company_id:
        raise HTTPException(403, 'Company access denied')
    value = payload.logo_data
    _validate_company_driver_logo(value)
    key = _company_logo_setting(company_id)
    record = db.get(AppSetting, key)
    if record is None:
        db.add(AppSetting(key=key, value=json.dumps({'logo_data': value})))
    else:
        record.value = json.dumps({'logo_data': value})
    audit(db,'company.driver_logo_update',actor=user,target_type='company',target_id=company_id,company_id=company_id)
    db.commit()
    return {'company_id': company_id, 'status': 'saved', 'logo_data': value}

@app.get('/api/v1/mobile/branding')
def mobile_company_branding(db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver = own_driver(db, user)
    company = db.get(Company, driver.company_id)
    return {'company_id': driver.company_id,
            'company_name': company.name if company else '',
            'logo_data': _company_driver_logo(db, driver.company_id)}
