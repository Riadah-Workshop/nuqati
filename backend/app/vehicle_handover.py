"""Nuqati vehicle condition & driver handover: strictly ONLINE and audit-preserving.

All inspection evidence is posted atomically to the server. There is no offline
queue or mobile draft. Existing trips/driver binding are deliberately untouched.
"""
import base64
import binascii
import hashlib
import io
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
from sqlalchemy import DateTime, Index, Integer, LargeBinary, String, Text, JSON, select, func, text as sqltext
from sqlalchemy.orm import Mapped, Session, mapped_column

from .auth import allow, current_user, scope
from .db import Base, engine, get_db
from .models import Company, Driver, DriverAccount, Trip, User, Vehicle, OdometerReading

router = APIRouter(prefix='/api/v1/handover', tags=['Vehicle handover'])


def utc_now():
    return datetime.now(timezone.utc)


class HandoverAssignment(Base):
    __tablename__ = 'handover_assignments'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    driver_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default='active')
    receipt_inspection_id: Mapped[int | None] = mapped_column(Integer)
    return_inspection_id: Mapped[int | None] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Partial unique index prevents two concurrent open assignments for one vehicle.
    __table_args__ = (
        Index('uq_handover_open_vehicle', 'vehicle_id', unique=True,
              postgresql_where=sqltext("status IN ('active','pending_receipt','pending_return')"),
              sqlite_where=sqltext("status IN ('active','pending_receipt','pending_return')")),
        Index('uq_handover_open_driver', 'driver_id', unique=True,
              postgresql_where=sqltext("status IN ('active','pending_receipt','pending_return')"),
              sqlite_where=sqltext("status IN ('active','pending_receipt','pending_return')")),
    )


class HandoverInspection(Base):
    __tablename__ = 'handover_inspections'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    odometer_km: Mapped[float] = mapped_column(nullable=False)
    engine_status: Mapped[str] = mapped_column(String(20), nullable=False)
    interior_status: Mapped[str] = mapped_column(String(20), nullable=False)
    dashboard_warnings: Mapped[str] = mapped_column(Text, nullable=False, default='')
    missing_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default='')
    damage_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    discrepancies: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    driver_acknowledged: Mapped[bool] = mapped_column(nullable=False, default=True)
    driver_id: Mapped[int] = mapped_column(Integer, nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default='accepted', nullable=False)
    reviewer_id: Mapped[int | None] = mapped_column(Integer)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default='')
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class HandoverPhoto(Base):
    __tablename__ = 'handover_photos'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inspection_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[str] = mapped_column(String(240), default='', nullable=False)
    mime_type: Mapped[str] = mapped_column(String(24), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class HandoverAudit(Base):
    __tablename__ = 'handover_audit'
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    assignment_id: Mapped[int | None] = mapped_column(Integer)
    actor_user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String(48), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


# Additive tables only: no alteration or removal of pre-existing fleet data.
Base.metadata.create_all(bind=engine, tables=[HandoverAssignment.__table__, HandoverInspection.__table__,
                                              HandoverPhoto.__table__, HandoverAudit.__table__])

REQUIRED_PHOTOS = {'front', 'rear', 'left', 'right', 'cabin_front', 'cabin_rear', 'dashboard', 'odometer'}
PHOTO_KINDS = REQUIRED_PHOTOS | {'damage', 'engine', 'equipment', 'other'}
MAX_PHOTOS = 20
MAX_PHOTO_BYTES = 950_000


class PhotoInput(BaseModel):
    category: str
    data_base64: str = Field(max_length=1_300_000)
    mime_type: Literal['image/jpeg', 'image/png'] = 'image/jpeg'
    note: str = Field(default='', max_length=240)


class DamageInput(BaseModel):
    area: str = Field(min_length=2, max_length=100)
    kind: Literal['scratch', 'dent', 'accident', 'broken', 'missing', 'other']
    description: str = Field(min_length=3, max_length=500)
    status: Literal['existing', 'new']


class InspectionInput(BaseModel):
    vehicle_id: int | None = None
    odometer_km: float = Field(ge=0, le=20_000_000)
    engine_status: Literal['normal', 'warning', 'problem', 'unknown']
    interior_status: Literal['normal', 'damaged', 'dirty']
    dashboard_warnings: str = Field(default='', max_length=500)
    missing_items: list[str] = Field(default_factory=list, max_length=25)
    notes: str = Field(default='', max_length=2000)
    damage_items: list[DamageInput] = Field(default_factory=list, max_length=10)
    photos: list[PhotoInput] = Field(min_length=8, max_length=MAX_PHOTOS)
    acknowledged: bool


class ReviewInput(BaseModel):
    action: Literal['approve', 'reject']
    note: str = Field(default='', max_length=1500)


class ReleaseInput(BaseModel):
    reason: str = Field(min_length=12, max_length=1500)


def driver_of(db: Session, user: User) -> Driver:
    allow(user, 'driver')
    account = db.scalar(select(DriverAccount).where(DriverAccount.user_id == user.id))
    d = db.get(Driver, account.driver_id) if account else None
    if not d or d.status != 'active' or user.company_id != d.company_id:
        raise HTTPException(403, 'Active driver account required')
    return d


def authorized_company(user: User, company_id: int) -> None:
    if user.role == 'driver':
        if user.company_id != company_id:
            raise HTTPException(403, 'Company access denied')
    else:
        allow(user, 'super_admin', 'company_admin', 'fleet_manager')
        scope(user, company_id)


def log_action(db: Session, company_id: int, vehicle_id: int, assignment_id: int | None, user: User, action: str, detail: str = ''):
    db.add(HandoverAudit(company_id=company_id, vehicle_id=vehicle_id, assignment_id=assignment_id,
                         actor_user_id=user.id, action=action, detail=detail))


def pending_trip(db: Session, driver_id: int) -> bool:
    return db.scalar(select(Trip.id).where(Trip.driver_id == driver_id, Trip.status == 'active').limit(1)) is not None


def open_assignment(db: Session, *, vehicle_id: int | None = None, driver_id: int | None = None):
    q = select(HandoverAssignment).where(HandoverAssignment.status.in_(['active', 'pending_receipt', 'pending_return']))
    if vehicle_id is not None:
        q = q.where(HandoverAssignment.vehicle_id == vehicle_id)
    if driver_id is not None:
        q = q.where(HandoverAssignment.driver_id == driver_id)
    return db.scalar(q.order_by(HandoverAssignment.id.desc()).limit(1))


def inspection_view(x: HandoverInspection, db: Session):
    photos = db.scalars(select(HandoverPhoto).where(HandoverPhoto.inspection_id == x.id).order_by(HandoverPhoto.id)).all()
    return {'id': x.id, 'assignment_id': x.assignment_id, 'company_id': x.company_id, 'kind': x.kind,
            'odometer_km': x.odometer_km, 'engine_status': x.engine_status,
            'interior_status': x.interior_status, 'dashboard_warnings': x.dashboard_warnings,
            'missing_items': x.missing_items or [], 'notes': x.notes,
            'damage_items': x.damage_items or [], 'discrepancies': x.discrepancies or [],
            'driver_acknowledged': x.driver_acknowledged, 'driver_id': x.driver_id,
            'review_status': x.review_status, 'review_note': x.review_note,
            'created_at': x.created_at, 'reviewed_at': x.reviewed_at,
            'photos': [{'id': p.id, 'category': p.category, 'note': p.note,
                        'sha256': p.sha256, 'url': f'/api/v1/handover/photos/{p.id}'} for p in photos]}


def serialize_assignment(db: Session, a: HandoverAssignment):
    v = db.get(Vehicle, a.vehicle_id)
    d = db.get(Driver, a.driver_id)
    return {'id': a.id, 'company_id': a.company_id, 'vehicle_id': a.vehicle_id,
            'plate_number': v.plate_number if v else 'Removed vehicle',
            'vehicle_model': v.make_model if v else '', 'driver_id': a.driver_id,
            'driver_name': d.full_name if d else 'Removed driver', 'status': a.status,
            'receipt_inspection_id': a.receipt_inspection_id, 'return_inspection_id': a.return_inspection_id,
            'started_at': a.started_at, 'ended_at': a.ended_at}


def parse_photos(photos: list[PhotoInput], damage_count: int):
    categories = [p.category for p in photos]
    if any(c not in PHOTO_KINDS for c in categories):
        raise HTTPException(422, 'Invalid inspection photo category')
    missing = REQUIRED_PHOTOS - set(categories)
    if missing:
        raise HTTPException(422, f'Missing required photos: {", ".join(sorted(missing))}')
    if categories.count('damage') < damage_count:
        raise HTTPException(422, 'Photograph every reported damage item')
    result = []
    for p in photos:
        try:
            data = base64.b64decode(p.data_base64, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(422, 'Invalid photo encoding')
        if not 0 < len(data) <= MAX_PHOTO_BYTES:
            raise HTTPException(413, 'Each photo must be under 950 KB; reduce camera image quality')
        if p.mime_type == 'image/jpeg' and not (data.startswith(b'\xff\xd8\xff') and data.endswith(b'\xff\xd9')):
            raise HTTPException(422, 'Photo format does not match JPEG')
        if p.mime_type == 'image/png' and not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise HTTPException(422, 'Photo format does not match PNG')
        result.append((p, data))
    return result


def create_inspection(db: Session, a: HandoverAssignment, d: Driver, payload: InspectionInput,
                      kind: str, discrepancies: list[str], parsed_photos):
    x = HandoverInspection(assignment_id=a.id, company_id=d.company_id, kind=kind,
        driver_id=d.id, odometer_km=payload.odometer_km, engine_status=payload.engine_status,
        interior_status=payload.interior_status, dashboard_warnings=payload.dashboard_warnings.strip(),
        missing_items=[str(v).strip()[:100] for v in payload.missing_items if str(v).strip()],
        notes=payload.notes, damage_items=[item.model_dump() for item in payload.damage_items],
        discrepancies=discrepancies, driver_acknowledged=True,
        review_status='pending' if discrepancies else 'accepted')
    db.add(x)
    db.flush()
    for photo, data in parsed_photos:
        db.add(HandoverPhoto(inspection_id=x.id, company_id=d.company_id, category=photo.category,
                             note=photo.note, mime_type=photo.mime_type, data=data,
                             sha256=hashlib.sha256(data).hexdigest()))
    return x


def require_ack(payload: InspectionInput):
    if not payload.acknowledged:
        raise HTTPException(422, 'Driver must review and acknowledge the condition report')


def reject_active_trip(db: Session, d: Driver):
    if pending_trip(db, d.id):
        raise HTTPException(409, 'End and synchronize your active trip before vehicle handover')


@router.get('/driver/status')
def driver_status(db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = driver_of(db, user)
    current = db.scalar(select(Vehicle).where(Vehicle.company_id == d.company_id, Vehicle.assigned_driver_id == d.id))
    own = open_assignment(db, driver_id=d.id)
    available = db.scalars(select(Vehicle).where(Vehicle.company_id == d.company_id).order_by(Vehicle.plate_number)).all()
    return {'online_verified': True,
            'driver_id': d.id, 'company_id': d.company_id,
            'active_assignment': serialize_assignment(db, own) if own else None,
            'legacy_vehicle': {'id': current.id, 'plate_number': current.plate_number,
                               'make_model': current.make_model} if current and not own else None,
            'vehicles': [{'id': v.id, 'plate_number': v.plate_number, 'make_model': v.make_model,
                          'odometer_km': v.odometer_km,
                          'available': (v.assigned_driver_id is None or v.assigned_driver_id == d.id)
                                       and (open_assignment(db, vehicle_id=v.id) is None or
                                            open_assignment(db, vehicle_id=v.id).driver_id == d.id),
                          'assigned_to_me': v.assigned_driver_id == d.id} for v in available]}


@router.post('/driver/receive', status_code=201)
def receive(payload: InspectionInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = driver_of(db, user)
    require_ack(payload)
    reject_active_trip(db, d)
    if payload.vehicle_id is None:
        raise HTTPException(422, 'Select a company vehicle plate')
    # Lock this row to serialize concurrent receipts and prevent double assignment.
    v = db.scalar(select(Vehicle).where(Vehicle.id == payload.vehicle_id).with_for_update())
    if not v or v.company_id != d.company_id:
        raise HTTPException(404, 'Company vehicle not found')
    my_existing = db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id == d.id, Vehicle.id != v.id))
    if my_existing or (open_assignment(db, driver_id=d.id) and open_assignment(db, driver_id=d.id).vehicle_id != v.id):
        raise HTTPException(409, 'Return your current vehicle before receiving another')
    if v.assigned_driver_id not in (None, d.id):
        raise HTTPException(409, 'This plate is held by another driver')
    if open_assignment(db, vehicle_id=v.id):
        raise HTTPException(409, 'This vehicle already has a handover record in progress')
    if v.odometer_km is not None and payload.odometer_km + 1 < float(v.odometer_km):
        raise HTTPException(422, 'Receipt odometer cannot be below the vehicle recorded reading')
    parsed = parse_photos(payload.photos, len(payload.damage_items))
    if payload.missing_items and not ({'equipment', 'damage'} & {p.category for p in payload.photos}):
        raise HTTPException(422, 'Missing equipment must be photographed')
    if payload.engine_status in ('warning', 'problem') and 'engine' not in {p.category for p in payload.photos}:
        raise HTTPException(422, 'Photograph the engine warning or visible damage')
    discrepancies = []
    if payload.damage_items or payload.missing_items or payload.engine_status in ('warning', 'problem') or payload.interior_status != 'normal' or payload.dashboard_warnings.strip():
        discrepancies.append('Driver reported vehicle condition requiring supervisor review')
    a = HandoverAssignment(company_id=d.company_id, vehicle_id=v.id, driver_id=d.id,
                           status='pending_receipt' if discrepancies else 'active')
    db.add(a)
    try:
        db.flush()
        x = create_inspection(db, a, d, payload, 'receipt', discrepancies, parsed)
        db.flush()
        a.receipt_inspection_id = x.id
        if not discrepancies:
            v.assigned_driver_id = d.id
        # Do not modify vehicle.odometer_km: existing maintenance/trip estimation owns this.
        log_action(db, d.company_id, v.id, a.id, user, 'receipt_submitted', 'Review required' if discrepancies else 'Accepted online')
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Vehicle or driver already has an active handover')
    except Exception:
        db.rollback()
        raise
    return {'status': a.status, 'assignment_id': a.id, 'inspection_id': x.id,
            'requires_supervisor': bool(discrepancies), 'vehicle_linked': not discrepancies}


def compare_return(db: Session, a: HandoverAssignment, payload: InspectionInput):
    baseline = db.get(HandoverInspection, a.receipt_inspection_id)
    if not baseline:
        raise HTTPException(409, 'Missing initial receipt condition report')
    if payload.odometer_km + 1 < baseline.odometer_km:
        raise HTTPException(422, 'Return odometer cannot be below receipt odometer')
    problems = []
    if any(item.status == 'new' for item in payload.damage_items): problems.append('New damage reported')
    # A reported return defect that did not exist in the receiving baseline
    # requires review even if the driver marks its status as 'existing'.
    documented = {(str(item.get('area', '')).strip().casefold(), str(item.get('kind', '')).strip().casefold())
                  for item in (baseline.damage_items or []) if isinstance(item, dict)}
    if any((item.area.strip().casefold(), item.kind.strip().casefold()) not in documented
           for item in payload.damage_items):
        problems.append('Previously undocumented damage requires comparison')
    if set(payload.missing_items) - set(baseline.missing_items or []): problems.append('New missing equipment')
    if baseline.engine_status == 'normal' and payload.engine_status != 'normal': problems.append('Engine status changed')
    if baseline.interior_status == 'normal' and payload.interior_status != 'normal': problems.append('Interior condition changed')
    if payload.dashboard_warnings.strip() and payload.dashboard_warnings.strip() != baseline.dashboard_warnings:
        problems.append('New dashboard warning noted')
    return problems


@router.post('/driver/return', status_code=201)
def return_vehicle(payload: InspectionInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    d = driver_of(db, user)
    require_ack(payload)
    reject_active_trip(db, d)
    a = open_assignment(db, driver_id=d.id)
    if not a or a.status != 'active':
        raise HTTPException(409, 'No approved active handover to return')
    v = db.scalar(select(Vehicle).where(Vehicle.id == a.vehicle_id).with_for_update())
    if not v or v.company_id != d.company_id or v.assigned_driver_id != d.id:
        raise HTTPException(409, 'Active plate does not match backend assignment')
    if payload.vehicle_id is not None and payload.vehicle_id != v.id:
        raise HTTPException(422, 'Return plate does not match your assignment')
    parsed = parse_photos(payload.photos, len(payload.damage_items))
    if payload.missing_items and not ({'equipment', 'damage'} & {p.category for p in payload.photos}):
        raise HTTPException(422, 'Missing equipment must be photographed')
    if payload.engine_status in ('warning', 'problem') and 'engine' not in {p.category for p in payload.photos}:
        raise HTTPException(422, 'Photograph the engine warning or visible damage')
    discrepancies = compare_return(db, a, payload)
    if v.odometer_km is not None and payload.odometer_km + 1 < float(v.odometer_km):
        raise HTTPException(422, 'Return odometer is below the latest system reading')
    x = create_inspection(db, a, d, payload, 'return', discrepancies, parsed)
    db.flush()
    a.return_inspection_id = x.id
    if discrepancies:
        a.status = 'pending_return'
    else:
        a.status = 'closed'
        a.ended_at = utc_now()
        v.assigned_driver_id = None
    log_action(db, d.company_id, v.id, a.id, user, 'return_submitted', '; '.join(discrepancies) or 'Accepted online')
    db.commit()
    return {'status': a.status, 'assignment_id': a.id, 'inspection_id': x.id,
            'requires_supervisor': bool(discrepancies), 'vehicle_released': not discrepancies}


@router.get('/dashboard')
def dashboard(company_id: int | None = None, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager')
    if user.role != 'super_admin':
        company_id = user.company_id
    if company_id is not None:
        scope(user, company_id)
    q = select(HandoverAssignment).order_by(HandoverAssignment.id.desc()).limit(500)
    if company_id is not None:
        q = q.where(HandoverAssignment.company_id == company_id)
    assignments = [serialize_assignment(db, a) for a in db.scalars(q).all()]
    pending = [a for a in assignments if a['status'] in ('pending_receipt', 'pending_return')]
    return {'assignments': assignments, 'pending_count': len(pending),
            'active_count': sum(a['status'] == 'active' for a in assignments),
            'closed_count': sum(a['status'] == 'closed' for a in assignments)}


@router.get('/vehicles/{vehicle_id}/history')
def vehicle_history(vehicle_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    v = db.get(Vehicle, vehicle_id)
    if not v: raise HTTPException(404, 'Vehicle not found')
    authorized_company(user, v.company_id)
    assignments = db.scalars(select(HandoverAssignment).where(HandoverAssignment.vehicle_id == v.id).order_by(HandoverAssignment.id.desc())).all()
    return {'vehicle_id': v.id, 'plate_number': v.plate_number,
            'assignments': [serialize_assignment(db, a) for a in assignments],
            'audit': [{'id': e.id, 'created_at': e.created_at, 'actor_user_id': e.actor_user_id,
                       'action': e.action, 'detail': e.detail} for e in db.scalars(
                       select(HandoverAudit).where(HandoverAudit.vehicle_id == v.id).order_by(HandoverAudit.id.desc()).limit(200)).all()]}


@router.get('/inspections/{inspection_id}')
def inspection_detail(inspection_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    x = db.get(HandoverInspection, inspection_id)
    if not x: raise HTTPException(404, 'Inspection not found')
    authorized_company(user, x.company_id)
    return inspection_view(x, db)


@router.get('/photos/{photo_id}')
def photo_data(photo_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    p = db.get(HandoverPhoto, photo_id)
    if not p: raise HTTPException(404, 'Photo not found')
    authorized_company(user, p.company_id)
    return Response(p.data, media_type=p.mime_type, headers={'Cache-Control': 'private, no-store',
                                                              'X-Content-Type-Options': 'nosniff',
                                                              'Content-Disposition': f'inline; filename="handover-{p.id}.jpg"'})


@router.post('/inspections/{inspection_id}/review')
def review(inspection_id: int, payload: ReviewInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager')
    x = db.get(HandoverInspection, inspection_id)
    if not x: raise HTTPException(404, 'Inspection not found')
    scope(user, x.company_id)
    a = db.scalar(select(HandoverAssignment).where(HandoverAssignment.id == x.assignment_id).with_for_update())
    v = db.scalar(select(Vehicle).where(Vehicle.id == a.vehicle_id).with_for_update())
    if x.review_status != 'pending' or (x.kind == 'receipt' and a.status != 'pending_receipt') or (x.kind == 'return' and a.status != 'pending_return'):
        raise HTTPException(409, 'No pending review for this inspection')
    if payload.action == 'reject' and len(payload.note.strip()) < 8:
        raise HTTPException(422, 'Explain why the inspection is rejected (8+ characters)')
    if payload.action == 'approve' and pending_trip(db, a.driver_id):
        raise HTTPException(409, 'Driver has an active trip; finish it before approving a transfer')
    x.review_status = 'approved' if payload.action == 'approve' else 'rejected'
    x.review_note = payload.note
    x.reviewer_id = user.id
    x.reviewed_at = utc_now()
    if x.kind == 'receipt':
        if payload.action == 'approve':
            if v.assigned_driver_id not in (None, a.driver_id):
                raise HTTPException(409, 'Vehicle already assigned to another driver')
            v.assigned_driver_id = a.driver_id
            a.status = 'active'
        else:
            a.status = 'rejected'
            a.ended_at = utc_now()
    else:
        if payload.action == 'approve':
            if v.assigned_driver_id != a.driver_id:
                raise HTTPException(409, 'Vehicle assignment changed unexpectedly')
            v.assigned_driver_id = None
            a.status = 'closed'
            a.ended_at = utc_now()
        else:
            a.status = 'active'
            a.return_inspection_id = None
    log_action(db, a.company_id, a.vehicle_id, a.id, user, f'{x.kind}_{payload.action}', payload.note)
    db.commit()
    return {'status': a.status, 'inspection_id': x.id, 'review_status': x.review_status}


@router.post('/vehicles/{vehicle_id}/administrative-release')
def administrative_release(vehicle_id: int, payload: ReleaseInput, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager')
    v = db.scalar(select(Vehicle).where(Vehicle.id == vehicle_id).with_for_update())
    if not v: raise HTTPException(404, 'Vehicle not found')
    scope(user, v.company_id)
    if v.assigned_driver_id and pending_trip(db, v.assigned_driver_id):
        raise HTTPException(409, 'Finish active trip before administrative release')
    a = open_assignment(db, vehicle_id=v.id)
    if not a and not v.assigned_driver_id: raise HTTPException(409, 'Vehicle is already available')
    if a:
        a.status = 'administratively_released'
        a.ended_at = utc_now()
    v.assigned_driver_id = None
    log_action(db, v.company_id, v.id, a.id if a else None, user, 'administrative_release', payload.reason)
    db.commit()
    return {'status': 'released', 'vehicle_id': v.id}


@router.get('/assignments/{assignment_id}/report')
def pdf_report(assignment_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager')
    a = db.get(HandoverAssignment, assignment_id)
    if not a: raise HTTPException(404, 'Assignment not found')
    scope(user, a.company_id)
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader
    stream = io.BytesIO()
    pdf = Canvas(stream, pagesize=(595, 842))
    v, d = db.get(Vehicle, a.vehicle_id), db.get(Driver, a.driver_id)
    pdf.setTitle('Nuqati vehicle handover evidence')
    pdf.setFont('Helvetica-Bold', 17); pdf.drawString(35, 800, 'NUQATI | Vehicle Handover Evidence')
    pdf.setFont('Helvetica', 10)
    pdf.drawString(35, 777, f'Assignment #{a.id} | {v.plate_number if v else a.vehicle_id} | Driver {d.id if d else a.driver_id}')
    pdf.drawString(35, 760, f'Status: {a.status} | Created: {a.started_at.isoformat() if a.started_at else "-"}')
    y = 737
    for kind, xid in [('RECEIPT', a.receipt_inspection_id), ('RETURN', a.return_inspection_id)]:
        x = db.get(HandoverInspection, xid) if xid else None
        if not x: continue
        if y < 290: pdf.showPage(); y = 795
        pdf.setFont('Helvetica-Bold', 12); pdf.drawString(35, y, f'{kind}: #{x.id} | {x.review_status} | {x.created_at.isoformat()}'); y -= 20
        pdf.setFont('Helvetica', 9)
        for line in [f'Odometer: {x.odometer_km:.1f} km | Engine: {x.engine_status} | Interior: {x.interior_status}',
                     f'Warnings: {x.dashboard_warnings[:95] or "None"}',
                     f'Missing items: {", ".join(x.missing_items or [])[:95] or "None"}',
                     f'Comparison flags: {", ".join(x.discrepancies or [])[:95] or "None"}',
                     f'Driver confirmed: {x.driver_acknowledged} | Reviewer: {x.reviewer_id or "-"}']:
            pdf.drawString(35, y, line); y -= 15
        photos = db.scalars(select(HandoverPhoto).where(HandoverPhoto.inspection_id == x.id).order_by(HandoverPhoto.id)).all()
        for p in photos:
            if y < 140: pdf.showPage(); y = 790
            try:
                pdf.drawImage(ImageReader(io.BytesIO(p.data)), 35, y - 70, width=115, height=65,
                              preserveAspectRatio=True, anchor='c')
            except Exception: pass
            pdf.drawString(160, y - 17, f'{p.category} | photo #{p.id} | SHA256: {p.sha256[:32]}...')
            y -= 78
        y -= 12
    audit = db.scalars(select(HandoverAudit).where(HandoverAudit.assignment_id == a.id).order_by(HandoverAudit.id)).all()
    if y < 130: pdf.showPage(); y = 790
    pdf.setFont('Helvetica-Bold', 11); pdf.drawString(35, y, 'Audit history'); y -= 18
    pdf.setFont('Helvetica', 9)
    for item in audit:
        if y < 60: pdf.showPage(); y = 790
        pdf.drawString(35, y, f'{item.created_at.isoformat()} | user #{item.actor_user_id} | {item.action}')
        y -= 14
    pdf.save()
    return Response(stream.getvalue(), media_type='application/pdf',
                    headers={'Content-Disposition': f'attachment; filename="nuqati-handover-{a.id}.pdf"',
                             'Cache-Control': 'private, no-store'})


def enforce_managed_link(db: Session, *, driver_id: int | None = None, vehicle_id: int | None = None):
    """Legacy edit screens remain functional for un-managed links, but cannot
    silently bypass a handover once the first condition report exists."""
    q = select(HandoverAssignment.id).where(HandoverAssignment.status.in_(
        ['active', 'pending_receipt', 'pending_return']))
    if driver_id is not None and vehicle_id is not None:
        q = q.where((HandoverAssignment.driver_id == driver_id) |
                    (HandoverAssignment.vehicle_id == vehicle_id))
    elif driver_id is not None:
        q = q.where(HandoverAssignment.driver_id == driver_id)
    elif vehicle_id is not None:
        q = q.where(HandoverAssignment.vehicle_id == vehicle_id)
    else:
        return
    if db.scalar(q.limit(1)) is not None:
        raise HTTPException(409, 'Active handover exists. Complete the online return or use audited administrative release.')


def company_handover_counts(db: Session, company_id: int) -> dict:
    return {model.__tablename__: db.scalar(select(func.count()).select_from(model).where(model.company_id == company_id))
            for model in (HandoverAssignment, HandoverInspection, HandoverPhoto, HandoverAudit)}


def purge_handover_company(db: Session, company_id: int):
    """Called only in existing permanent-delete workflow after verified backup."""
    from sqlalchemy import delete
    for model in (HandoverPhoto, HandoverInspection, HandoverAudit, HandoverAssignment):
        db.execute(delete(model).where(model.company_id == company_id))
