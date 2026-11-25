"""Edit and delete companies, users, drivers, vehicles, odometer corrections; company logo on edit; company deletion audit."""

import json
import os
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import (
    Column,
    DateTime,
    delete,
    func,
    Integer,
    JSON,
    MetaData,
    select,
    String,
    Table,
)
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import engine, get_db
from ..models import (
    AccountInvitation,
    AppSetting,
    Company,
    CompanyDrivingSettings,
    Driver,
    DriverAccount,
    DriverLocation,
    DriverMetadata,
    DrivingEvent,
    MaintenanceSchedule,
    OdometerReading,
    Trip,
    User,
    Vehicle,
)
from ..schemas import CompanyOut, DriverOut, VehicleOut
from .auth_accounts import normalize_phone, user_view
from .shared import _company_logo_setting

def _validate_company_driver_logo(value: str):
    import base64, binascii
    if value:
        valid_prefixes = ('data:image/png;base64,', 'data:image/jpeg;base64,', 'data:image/webp;base64,')
        prefix = next((item for item in valid_prefixes if value.startswith(item)), None)
        if prefix is None:
            raise HTTPException(422, 'Use a PNG, JPEG or WebP logo')
        try:
            image_bytes = base64.b64decode(value[len(prefix):], validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Invalid logo encoding')
        if len(image_bytes) > 220000 or not image_bytes:
            raise HTTPException(422, 'Logo must be under 220 KB')
        # Verify actual file signatures, not just the claimed MIME type.
        valid_image = ((prefix.startswith('data:image/png') and image_bytes.startswith(b'\x89PNG\r\n\x1a\n')) or
                       (prefix.startswith('data:image/jpeg') and image_bytes.startswith(b'\xff\xd8\xff')) or
                       (prefix.startswith('data:image/webp') and image_bytes[:4] == b'RIFF' and image_bytes[8:12] == b'WEBP'))
        if not valid_image:
            raise HTTPException(422, 'Logo format does not match file content')
    return value

class CompanyEdit(BaseModel):
    name: str = Field(min_length=2,max_length=160)
    logo_data: str | None = Field(default=None,max_length=300000)
@app.patch('/api/v1/companies/{company_id}', response_model=CompanyOut)
def edit_company(company_id:int,payload:CompanyEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    row=db.get(Company,company_id)
    if not row: raise HTTPException(404,'Company not found')
    if payload.logo_data is not None:
        value = _validate_company_driver_logo(payload.logo_data)
        key = _company_logo_setting(company_id)
        record = db.get(AppSetting, key)
        if record is None:
            db.add(AppSetting(key=key, value=json.dumps({'logo_data': value})))
        else:
            record.value = json.dumps({'logo_data': value})
    row.name=payload.name.strip();db.commit();db.refresh(row);return row
_delete_audit_metadata = MetaData()
company_delete_audit = Table('company_delete_audit', _delete_audit_metadata,
    Column('id', Integer, primary_key=True),
    Column('company_id', Integer, nullable=False),
    Column('company_name', String(160), nullable=False),
    Column('actor_user_id', Integer, nullable=False),
    Column('actor_email', String(255), nullable=False),
    Column('backup_reference', String(255), nullable=False),
    Column('deleted_counts', JSON, nullable=False),
    Column('deleted_at', DateTime(timezone=True), nullable=False))
_delete_audit_metadata.create_all(bind=engine)

COMPANY_DELETE_MODELS = (AccountInvitation, DriverAccount, DrivingEvent, DriverLocation,
                         Trip, OdometerReading, MaintenanceSchedule, CompanyDrivingSettings,
                         DriverMetadata, Vehicle, Driver, User)

def company_delete_counts(db: Session, company_id: int):
    user_ids = select(User.id).where(User.company_id == company_id)
    driver_ids = select(Driver.id).where(Driver.company_id == company_id)
    filters = {
        AccountInvitation: AccountInvitation.user_id.in_(user_ids),
        DriverAccount: (DriverAccount.driver_id.in_(driver_ids) | DriverAccount.user_id.in_(user_ids)),
        DriverMetadata: DriverMetadata.driver_id.in_(driver_ids),
    }
    counts={model.__tablename__: db.scalar(select(func.count()).select_from(model).where(
        filters[model] if model in filters else model.company_id == company_id
    )) for model in COMPANY_DELETE_MODELS}
    from ..vehicle_handover import company_handover_counts
    counts.update(company_handover_counts(db,company_id))
    return counts

def purge_company_records(db: Session, company_id: int):
    from ..vehicle_handover import purge_handover_company
    purge_handover_company(db,company_id)
    user_ids = select(User.id).where(User.company_id == company_id)
    driver_ids = select(Driver.id).where(Driver.company_id == company_id)
    db.execute(delete(AccountInvitation).where(AccountInvitation.user_id.in_(user_ids)))
    db.execute(delete(DriverAccount).where((DriverAccount.driver_id.in_(driver_ids)) | (DriverAccount.user_id.in_(user_ids))))
    for model in (DrivingEvent, DriverLocation, Trip, OdometerReading, MaintenanceSchedule, CompanyDrivingSettings):
        db.execute(delete(model).where(model.company_id == company_id))
    db.execute(delete(DriverMetadata).where(DriverMetadata.driver_id.in_(driver_ids)))
    # Vehicle assignment references drivers; vehicles must be deleted before drivers.
    db.execute(delete(Vehicle).where(Vehicle.company_id == company_id))
    db.execute(delete(Driver).where(Driver.company_id == company_id))
    db.execute(delete(User).where(User.company_id == company_id))

@app.get('/api/v1/companies/{company_id}/deletion-preview')
def company_deletion_preview(company_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    row=db.get(Company,company_id)
    if not row: raise HTTPException(404,'Company not found')
    return {'company_id':row.id,'company_name':row.name,'counts':company_delete_counts(db,company_id),
            'requires_backup':True,'requires_exact_name':True,'requires_delete_word':True}

class ConfirmCompanyDelete(BaseModel):
    confirm_name: str
    confirm_word: str
    backup_reference: str | None = Field(default=None,max_length=255)

@app.post('/api/v1/companies/{company_id}/permanent-delete')
def permanently_delete_company(company_id:int,data:ConfirmCompanyDelete,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    # Production safety: always require a verified backup reference.
    approved_backup = os.environ.get('NUQATI_VERIFIED_BACKUP_REFERENCE','').strip()
    if not approved_backup or (data.backup_reference or '').strip() != approved_backup:
        raise HTTPException(412,'A verified backup reference must be configured in Coolify and entered exactly')
    audit_backup_reference = approved_backup
    if data.confirm_word != 'DELETE':
        raise HTTPException(422,'Type DELETE to confirm')
    try:
        # PostgreSQL locks prevent concurrent edits to the company row during purge.
        row=db.scalar(select(Company).where(Company.id==company_id).with_for_update())
        if not row: raise HTTPException(404,'Company not found')
        if data.confirm_name != row.name:
            raise HTTPException(422,'Company name confirmation does not match')
        counts=company_delete_counts(db,company_id)
        purge_company_records(db,company_id)
        db.execute(delete(Company).where(Company.id==company_id))
        db.execute(company_delete_audit.insert().values(company_id=company_id,company_name=row.name,
            actor_user_id=user.id,actor_email=user.email,backup_reference=audit_backup_reference,
            deleted_counts=counts,deleted_at=datetime.now(timezone.utc)))
        db.commit()
    except HTTPException:
        db.rollback();raise
    except SQLAlchemyError:
        db.rollback()
        raise HTTPException(409,'Deletion blocked by database relationships or database error. No deletion committed. Review server logs.')
    return {'status':'deleted','company_id':company_id,'deleted_counts':counts,'audit_recorded':True}

@app.delete('/api/v1/companies/{company_id}')
def delete_empty_company(company_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin'); row=db.get(Company,company_id)
    if not row: raise HTTPException(404,'Company not found')
    for model in (User,Driver,Vehicle,Trip,OdometerReading,MaintenanceSchedule,DrivingEvent,DriverLocation,CompanyDrivingSettings):
        if db.scalar(select(func.count()).select_from(model).where(model.company_id==company_id)):
            raise HTTPException(409,'Company has related records. Use deletion preview and permanent delete.')
    from ..vehicle_handover import company_handover_counts
    if any(company_handover_counts(db,company_id).values()):
        raise HTTPException(409,'Company has handover evidence; use verified-backup permanent deletion.')
    db.delete(row);db.commit();return {'status':'deleted'}


# Phase 3: restricted management operations. Permanent deletion is Super Admin only.
class UserEdit(BaseModel):
    full_name: str | None = Field(default=None, min_length=2, max_length=160)
    role: str | None = None
    is_active: bool | None = None
    company_id: int | None = None

@app.patch('/api/v1/users/{user_id}')
def edit_user(user_id:int,payload:UserEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    target=db.get(User,user_id)
    if not target: raise HTTPException(404,'User not found')
    changes=payload.model_dump(exclude_unset=True)
    if 'role' in changes and changes['role'] not in {'super_admin','workshop_staff','company_admin','fleet_manager','representative','driver'}: raise HTTPException(422,'Invalid role')
    if target.id==user.id and (changes.get('is_active') is False or ('role' in changes and changes['role']!='super_admin')): raise HTTPException(409,'Cannot remove your own admin access')
    cid=changes.get('company_id',target.company_id); role=changes.get('role',target.role)
    if role=='super_admin':
        if cid is not None: raise HTTPException(422,'Super Admin cannot belong to a client company')
    elif cid is None or not db.get(Company,cid): raise HTTPException(422,'Valid company required')
    for k,v in changes.items(): setattr(target,k,v)
    db.commit();db.refresh(target);return user_view(target)

@app.delete('/api/v1/users/{user_id}')
def delete_user(user_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin'); target=db.get(User,user_id)
    if not target: raise HTTPException(404,'User not found')
    if target.id==user.id or target.role=='super_admin': raise HTTPException(409,'Cannot delete a Super Admin account')
    db.execute(delete(AccountInvitation).where(AccountInvitation.user_id==user_id))
    db.execute(delete(DriverAccount).where(DriverAccount.user_id==user_id))
    db.delete(target)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Account has other dependent records')
    return {'status':'deleted'}

class DriverEdit(BaseModel):
    full_name: str | None = Field(default=None,min_length=2,max_length=160)
    phone: str | None = Field(default=None,max_length=40)
    status: str | None = None
    id_number: str | None = Field(default=None,min_length=1,max_length=40)
    site_name: str | None = Field(default=None,min_length=1,max_length=160)
    vehicle_id: int | None = None
    company_id: int | None = None

@app.get('/api/v1/drivers/details')
def driver_details(db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager')
    q=select(Driver)
    if user.role!='super_admin':q=q.where(Driver.company_id==user.company_id)
    result={}
    for d in db.scalars(q):
        meta=db.get(DriverMetadata,d.id)
        vehicle=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id))
        result[str(d.id)]={'id_number':meta.id_number if meta else '', 'site_name':meta.site_name if meta else '', 'vehicle_id':vehicle.id if vehicle else None}
    return {'drivers':result}

@app.patch('/api/v1/drivers/{driver_id}',response_model=DriverOut)
def edit_driver(driver_id:int,payload:DriverEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin')
    row=db.get(Driver,driver_id)
    if not row:raise HTTPException(404,'Driver not found')
    changes=payload.model_dump(exclude_unset=True)
    if 'status' in changes and changes['status'] not in ('active','inactive','archived'):raise HTTPException(422,'Invalid status')
    new_company=changes.get('company_id',row.company_id)
    if new_company!=row.company_id:raise HTTPException(422,'Company transfer requires a separate audited workflow; edit within the same company')
    if 'phone' in changes and changes['phone']:
        normalized=normalize_phone(changes['phone'])
        if any(d.id!=row.id and normalize_phone(d.phone)==normalized for d in db.scalars(select(Driver).where(Driver.company_id==row.company_id))):raise HTTPException(409,'Phone already in use')
        changes['phone']=normalized
    if 'id_number' in changes and changes['id_number']:
        id_number=changes['id_number'].strip()
        if db.scalar(select(DriverMetadata).where(DriverMetadata.id_number==id_number,DriverMetadata.driver_id!=driver_id)):raise HTTPException(409,'ID/Iqama already in use')
    meta=db.get(DriverMetadata,driver_id)
    if ('id_number' in changes or 'site_name' in changes) and not meta:
        if not changes.get('id_number') or not changes.get('site_name'):raise HTTPException(422,'ID and site required for legacy drivers')
        meta=DriverMetadata(driver_id=driver_id,id_number=changes['id_number'],site_name=changes['site_name']);db.add(meta)
    if meta:
        for key in ('id_number','site_name'):
            if key in changes:
                if not changes[key] or not changes[key].strip():raise HTTPException(422,f'{key} cannot be empty')
                setattr(meta,key,changes[key].strip())
    if 'vehicle_id' in changes:
        # Once a documented handover is active, require the online return path.
        from ..vehicle_handover import enforce_managed_link
        target_id=changes['vehicle_id']
        current_vehicle=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==driver_id))
        if (current_vehicle.id if current_vehicle else None) != target_id:
            enforce_managed_link(db,driver_id=driver_id,vehicle_id=target_id)
        target=db.get(Vehicle,target_id) if target_id is not None else None
        if target_id is not None and (not target or target.company_id!=row.company_id):raise HTTPException(422,'Select a vehicle in the same company')
        if target and target.assigned_driver_id not in (None,driver_id):raise HTTPException(409,'Vehicle assigned to another driver')
        for v in db.scalars(select(Vehicle).where(Vehicle.assigned_driver_id==driver_id)):
            v.assigned_driver_id=None
        db.flush()
        if target:target.assigned_driver_id=driver_id
    for key in ('full_name','phone','status'):
        if key in changes:setattr(row,key,changes[key])
    if 'full_name' in changes:
        account=db.scalar(select(DriverAccount).where(DriverAccount.driver_id==driver_id))
        if account:
            linked=db.get(User,account.user_id)
            if linked:linked.full_name=row.full_name
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Update conflicts with another record')
    db.refresh(row)
    return row

@app.delete('/api/v1/drivers/{driver_id}')
def delete_driver(driver_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(Driver,driver_id)
    if not row: raise HTTPException(404,'Driver not found')
    if db.scalar(select(func.count()).select_from(Trip).where(Trip.driver_id==driver_id)):
        raise HTTPException(409,'Driver has trip history. Permanently delete their company with explicit confirmation, or archive the driver.')
    from ..vehicle_handover import enforce_managed_link
    enforce_managed_link(db,driver_id=driver_id)
    for v in db.scalars(select(Vehicle).where(Vehicle.assigned_driver_id==driver_id)):v.assigned_driver_id=None
    db.execute(delete(DriverAccount).where(DriverAccount.driver_id==driver_id))
    db.flush();db.delete(row)
    try:db.commit()
    except IntegrityError:db.rollback();raise HTTPException(409,'Driver has other linked history. Archive instead.')
    return {'status':'deleted'}

class VehicleEdit(BaseModel):
    plate_number: str | None = Field(default=None,min_length=1,max_length=40)
    make_model: str | None = Field(default=None,max_length=120)
    year: int | None = Field(default=None,ge=1900,le=2100)
    door_number: str | None = Field(default=None,max_length=40)
    assigned_driver_id: int | None = None
    # Optional: commit an admin-only, audited odometer correction together with the
    # other fields in the same transaction. Existing PATCH clients are unaffected.
    odometer_correction_km: float | None = Field(default=None,ge=0)
    odometer_correction_reason: str | None = Field(default=None,max_length=500)

@app.patch('/api/v1/vehicles/{vehicle_id}',response_model=VehicleOut)
def edit_vehicle(vehicle_id:int,payload:VehicleEdit,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin');row=db.get(Vehicle,vehicle_id)
    if not row: raise HTTPException(404,'Vehicle not found')
    scope(user,row.company_id)
    changes=payload.model_dump(exclude_unset=True)
    correction_km=changes.pop('odometer_correction_km',None)
    correction_reason=changes.pop('odometer_correction_reason',None)
    if correction_km is not None:
        if user.role!='super_admin': raise HTTPException(403,'Only Super Admin may correct the odometer')
        if not correction_reason or len(correction_reason.strip())<5:
            raise HTTPException(422,'Odometer correction reason must be at least 5 characters')
    elif correction_reason is not None:
        raise HTTPException(422,'Odometer correction value is required when a reason is provided')
    if 'assigned_driver_id' in changes and changes['assigned_driver_id'] != row.assigned_driver_id:
        from ..vehicle_handover import enforce_managed_link
        enforce_managed_link(db,driver_id=changes['assigned_driver_id'],vehicle_id=vehicle_id)
    if changes.get('assigned_driver_id') is not None:
        driver=db.get(Driver,changes['assigned_driver_id'])
        if not driver or driver.company_id!=row.company_id: raise HTTPException(422,'Driver must belong to vehicle company')
    for k,v in changes.items(): setattr(row,k,v)
    if correction_km is not None:
        db.add(OdometerReading(company_id=row.company_id,vehicle_id=row.id,
                               reading_km=correction_km,source='ADMIN_CORRECTION',
                               note=correction_reason.strip()))
        row.odometer_km=correction_km
    try: db.commit()
    except IntegrityError: db.rollback();raise HTTPException(409,'Plate number already exists')
    db.refresh(row);return row

@app.delete('/api/v1/vehicles/{vehicle_id}')
def delete_vehicle(vehicle_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(Vehicle,vehicle_id)
    if not row: raise HTTPException(404,'Vehicle not found')
    from ..vehicle_handover import HandoverAssignment
    if db.scalar(select(HandoverAssignment.id).where(HandoverAssignment.vehicle_id==vehicle_id)):
        raise HTTPException(409,'Vehicle has handover history; keep the vehicle archived to preserve evidence.')
    for model in (Trip,OdometerReading,MaintenanceSchedule):
        if db.scalar(select(func.count()).select_from(model).where(model.vehicle_id==vehicle_id)):
            raise HTTPException(409,'Vehicle has trip, odometer or maintenance history. Deletion blocked.')
    db.delete(row);db.commit();return {'status':'deleted'}

class OdometerCorrection(BaseModel):
    reading_km: float = Field(ge=0)
    reason: str = Field(min_length=5,max_length=500)

@app.post('/api/v1/vehicles/{vehicle_id}/odometer-correction')
def correct_odometer(vehicle_id:int,payload:OdometerCorrection,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');v=db.get(Vehicle,vehicle_id)
    if not v: raise HTTPException(404,'Vehicle not found')
    # Preserve the original odometer history. Record a new correction entry instead of rewriting history.
    db.add(OdometerReading(company_id=v.company_id,vehicle_id=v.id,reading_km=payload.reading_km,source='ADMIN_CORRECTION',note=payload.reason))
    v.odometer_km=payload.reading_km;db.commit();return {'status':'corrected','odometer_km':v.odometer_km}

@app.delete('/api/v1/maintenance-schedules/{schedule_id}')
def delete_maintenance(schedule_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin');row=db.get(MaintenanceSchedule,schedule_id)
    if not row: raise HTTPException(404,'Schedule not found')
    db.delete(row);db.commit();return {'status':'deleted'}
