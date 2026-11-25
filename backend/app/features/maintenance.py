"""Maintenance schedules, driver vehicle-care flows, tyre schedules and the smart-oil estimate."""

import math
from datetime import datetime, timezone

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import engine, get_db
from ..models import DriverLocation, MaintenanceSchedule, OdometerReading, Trip, User, Vehicle
from ..schemas import MaintenanceScheduleOut, MaintenanceScheduleUpsert
from .shared import own_driver

SERVICE_TYPES = {"ENGINE_OIL", "SPARK_PLUGS", "TRANSMISSION_OIL", "TYRES"}


def maintenance_view(row: MaintenanceSchedule, vehicle: Vehicle) -> dict:
    due = row.last_service_km + row.interval_km
    current = vehicle.odometer_km
    remaining = None if current is None else due - current
    status = "UNKNOWN" if remaining is None else ("OVERDUE" if remaining <= 0 else ("DUE_SOON" if remaining <= row.warning_before_km else "OK"))
    return {"id": row.id, "company_id": row.company_id, "vehicle_id": row.vehicle_id,
            "service_type": row.service_type, "interval_km": row.interval_km,
            "last_service_km": row.last_service_km, "warning_before_km": row.warning_before_km,
            "next_due_km": due, "current_odometer_km": current,
            "remaining_km": remaining, "status": status}


@app.put("/api/v1/maintenance-schedules", response_model=MaintenanceScheduleOut)
def upsert_maintenance(payload: MaintenanceScheduleUpsert, db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin')
    scope(user,payload.company_id)
    if payload.service_type not in SERVICE_TYPES:
        raise HTTPException(422, "Unsupported service type")
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if not vehicle or vehicle.company_id != payload.company_id:
        raise HTTPException(404, "Vehicle not found for company")
    row = db.scalar(select(MaintenanceSchedule).where(
        MaintenanceSchedule.company_id == payload.company_id,
        MaintenanceSchedule.vehicle_id == payload.vehicle_id,
        MaintenanceSchedule.service_type == payload.service_type))
    if row is None:
        row = MaintenanceSchedule(**payload.model_dump())
        db.add(row)
    else:
        for key, value in payload.model_dump().items():
            setattr(row, key, value)
    db.commit(); db.refresh(row)
    return maintenance_view(row, vehicle)


@app.get('/api/v1/mobile/maintenance-reminders')
def driver_maintenance_reminders(db:Session=Depends(get_db),user:User=Depends(current_user)):
    d=own_driver(db,user)
    v=db.scalar(select(Vehicle).where(Vehicle.assigned_driver_id==d.id,Vehicle.company_id==d.company_id))
    if not v or v.odometer_km is None:return {'vehicle_id':None,'reminders':[]}
    ensure_vehicle_tyre_schedules(db, v.company_id)
    db.commit()
    schedules=db.scalars(select(MaintenanceSchedule).where(MaintenanceSchedule.vehicle_id==v.id,MaintenanceSchedule.company_id==v.company_id)).all()
    out=[]
    for row in schedules:
        due=row.last_service_km+row.interval_km
        remaining=due-v.odometer_km
        stage=None
        if row.service_type=='ENGINE_OIL':
            if remaining<=0:stage='DUE'
            elif remaining<=500:stage='500_LEFT'
            elif remaining<=1000:stage='1000_LEFT'
        elif row.service_type in ('SPARK_PLUGS','TRANSMISSION_OIL'):
            if remaining<=-1000:stage='1000_OVERDUE'
            elif remaining<=0:stage='DUE'
            elif remaining<=1000:stage='1000_LEFT'
        if row.service_type=='TYRES':
            if remaining<=0:stage='DUE'
            elif remaining<=1000:stage='1000_LEFT'
            # The annual tyre reminder is measured from the date this schedule
            # was first registered/last updated, which is reset on tyre service.
            from datetime import datetime, timezone, timedelta
            registered=row.updated_at
            if registered is not None:
                if registered.tzinfo is None:registered=registered.replace(tzinfo=timezone.utc)
                days_left=(registered+timedelta(days=365)-datetime.now(timezone.utc)).days
                if days_left<=0:stage='DUE'
                elif days_left<=30 and stage is None:stage='30_DAYS_LEFT'
        if stage:out.append({'schedule_id':row.id,'service_type':row.service_type,'vehicle_id':v.id,'plate_number':v.plate_number,'due_km':due,'current_km':v.odometer_km,'remaining_km':remaining,'stage':stage,'cycle_key':f'{row.id}:{row.last_service_km}:{row.interval_km}:{row.updated_at.isoformat() if row.service_type=="TYRES" and row.updated_at else ""}'})
    return {'vehicle_id':v.id,'reminders':out}

# Driver maintenance and odometer operations use the authenticated assignment only.
# Keep the existing odometer and maintenance tables so dashboards stay in sync.
def _driver_vehicle(db: Session, user: User):
    driver = own_driver(db, user)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.company_id == driver.company_id, Vehicle.assigned_driver_id == driver.id))
    if not vehicle:
        raise HTTPException(404, 'No vehicle assigned to this driver')
    return driver, vehicle

class DriverOdometerSubmission(BaseModel):
    reading_km: float = Field(ge=0, le=3000000)

class DriverServiceCompletion(BaseModel):
    confirmed: bool
    reading_km: float = Field(ge=0, le=3000000)

@app.get('/api/v1/mobile/vehicle-care')
def mobile_vehicle_care(db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db, user)
    ensure_vehicle_tyre_schedules(db, vehicle.company_id)
    db.commit()
    schedules = db.scalars(select(MaintenanceSchedule).where(MaintenanceSchedule.company_id == vehicle.company_id, MaintenanceSchedule.vehicle_id == vehicle.id)).all()
    reminders = [maintenance_view(row, vehicle) for row in schedules]
    last_driver_reading = db.scalar(select(OdometerReading).where(OdometerReading.company_id == vehicle.company_id, OdometerReading.vehicle_id == vehicle.id, OdometerReading.source == 'DRIVER_MONTHLY').order_by(OdometerReading.created_at.desc(), OdometerReading.id.desc()).limit(1))
    now = datetime.now(timezone.utc)
    last_month = last_driver_reading.created_at if last_driver_reading else None
    monthly_due = last_month is None or (last_month.year, last_month.month) != (now.year, now.month)
    # A first-login odometer confirmation belongs to the driver, not to a
    # calendar month or a vehicle that may have had other assigned drivers.
    driver_reading = db.scalar(select(OdometerReading.id).where(
        OdometerReading.company_id == vehicle.company_id,
        OdometerReading.vehicle_id == vehicle.id,
        OdometerReading.source == 'DRIVER_MONTHLY',
        OdometerReading.note.like(f'Driver #{driver.id} %')
    ).limit(1))
    first_odometer_due = driver_reading is None
    return {'vehicle_id': vehicle.id, 'plate_number': vehicle.plate_number, 'odometer_km': vehicle.odometer_km,
            'first_odometer_due': first_odometer_due,
            'monthly_odometer_due': monthly_due,
            'last_driver_odometer_at': last_month.isoformat() if last_month else None,
            'maintenance': reminders,
            'initial_history_due': not bool(db.execute(text("SELECT 1 FROM driver_service_history WHERE vehicle_id=:v AND driver_id=:d LIMIT 1"), {'v':vehicle.id,'d':driver.id}).first()),
            'service_history': [dict(row) for row in db.execute(text("SELECT service_type,knowledge,reading_type,reading_km,interval_km,submitted_at FROM driver_service_history WHERE vehicle_id=:v AND driver_id=:d"), {'v':vehicle.id,'d':driver.id}).mappings().all()]}

# Driver-provided service history. Unknown answers are recorded, never guessed.

class DriverHistoryEntry(BaseModel):
    service_type: str
    knowledge: str = Field(pattern='^(KNOWN|UNKNOWN)$')
    reading_type: str | None = Field(default=None, pattern='^(LAST|NEXT)$')
    reading_km: float | None = Field(default=None, ge=0, le=3000000)
    oil_interval_km: int | None = None

class DriverHistorySubmission(BaseModel):
    odometer_km: float = Field(ge=0, le=3000000)
    services: list[DriverHistoryEntry] = Field(min_length=4, max_length=4)

@app.post('/api/v1/mobile/vehicle-care/initial-history')
def submit_driver_initial_history(payload: DriverHistorySubmission, db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db,user)
    provided={entry.service_type:entry for entry in payload.services}
    if len(provided)!=4 or set(provided)!=SERVICE_TYPES:
        raise HTTPException(422,'Please answer for all four services')
    if vehicle.odometer_km is not None and payload.odometer_km < vehicle.odometer_km:
        raise HTTPException(422,'Current odometer cannot be lower than recorded mileage')
    existing=db.execute(text('SELECT COUNT(*) FROM driver_service_history WHERE vehicle_id=:v AND driver_id=:d'),
        {'v':vehicle.id,'d':driver.id}).scalar() or 0
    if existing: raise HTTPException(409,'Initial service history already submitted for this driver and vehicle')
    defaults={'ENGINE_OIL':5000,'SPARK_PLUGS':60000,'TRANSMISSION_OIL':80000,'TYRES':60000}
    current_schedules={row.service_type:row for row in db.scalars(select(MaintenanceSchedule).where(MaintenanceSchedule.company_id==vehicle.company_id,MaintenanceSchedule.vehicle_id==vehicle.id)).all()}
    updates=[]
    for service,entry in provided.items():
        interval=(entry.oil_interval_km if service=='ENGINE_OIL' else current_schedules[service].interval_km if service in current_schedules else defaults[service])
        if service=='ENGINE_OIL' and entry.knowledge=='KNOWN' and interval not in (5000,10000):
            raise HTTPException(422,'Select 5,000 or 10,000 km oil interval')
        if entry.knowledge=='KNOWN':
            if entry.reading_type not in ('LAST','NEXT') or entry.reading_km is None:
                raise HTTPException(422,f'Provide last or next mileage for {service}')
            last=entry.reading_km if entry.reading_type=='LAST' else entry.reading_km-interval
            if last<0 or (entry.reading_type=='LAST' and last>payload.odometer_km):
                raise HTTPException(422,f'Invalid service mileage for {service}')
            updates.append((service,last,interval))
    vehicle.odometer_km=payload.odometer_km
    db.add(OdometerReading(company_id=vehicle.company_id,vehicle_id=vehicle.id,reading_km=payload.odometer_km,
        source='DRIVER_MONTHLY',note=f'Driver #{driver.id} initial odometer and service history'))
    for service,entry in provided.items():
        db.execute(text("""INSERT INTO driver_service_history
        (company_id,vehicle_id,driver_id,service_type,knowledge,reading_type,reading_km,interval_km)
        VALUES (:c,:v,:d,:s,:k,:t,:r,:i)"""),
        {'c':vehicle.company_id,'v':vehicle.id,'d':driver.id,'s':service,'k':entry.knowledge,
         't':entry.reading_type if entry.knowledge=='KNOWN' else None,
         'r':entry.reading_km if entry.knowledge=='KNOWN' else None,
         'i':(entry.oil_interval_km if service=='ENGINE_OIL' else current_schedules[service].interval_km if service in current_schedules else defaults[service]) if entry.knowledge=='KNOWN' else None})
    for service,last,interval in updates:
        schedule=db.scalar(select(MaintenanceSchedule).where(MaintenanceSchedule.vehicle_id==vehicle.id,
            MaintenanceSchedule.company_id==vehicle.company_id,MaintenanceSchedule.service_type==service))
        if schedule is None:
            db.add(MaintenanceSchedule(company_id=vehicle.company_id,vehicle_id=vehicle.id,
                service_type=service,interval_km=interval,last_service_km=last,warning_before_km=500 if service=='ENGINE_OIL' else 1000))
        else:
            schedule.last_service_km=last; schedule.interval_km=interval
    db.commit()
    return {'saved':True,'vehicle_id':vehicle.id,'known_services':len(updates),'unknown_services':4-len(updates)}

@app.get('/api/v1/maintenance/driver-history')
def dashboard_driver_history(vehicle_id:int|None=None,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    where='WHERE h.company_id=:company' if user.role!='super_admin' else 'WHERE 1=1'
    params={'company':user.company_id} if user.role!='super_admin' else {}
    if vehicle_id is not None:
        where+=' AND h.vehicle_id=:vehicle';params['vehicle']=vehicle_id
    rows=db.execute(text(f"""SELECT h.*,v.plate_number,d.full_name AS driver_name
        FROM driver_service_history h JOIN vehicles v ON v.id=h.vehicle_id
        JOIN drivers d ON d.id=h.driver_id {where} ORDER BY h.submitted_at DESC"""),params).mappings().all()
    return [dict(r) for r in rows]

@app.post('/api/v1/mobile/vehicle-care/odometer')
def mobile_driver_odometer(payload: DriverOdometerSubmission, db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db, user)
    if vehicle.odometer_km is not None and payload.reading_km < vehicle.odometer_km:
        raise HTTPException(422, 'Odometer cannot be lower than recorded mileage. Ask an administrator for an audited correction.')
    reading = OdometerReading(company_id=vehicle.company_id, vehicle_id=vehicle.id,
        reading_km=payload.reading_km, source='DRIVER_MONTHLY',
        note=f'Driver #{driver.id} monthly odometer confirmation')
    vehicle.odometer_km = payload.reading_km
    db.add(reading)
    db.commit()
    return {'saved': True, 'odometer_km': vehicle.odometer_km, 'reading_id': reading.id}

@app.post('/api/v1/mobile/vehicle-care/maintenance/{schedule_id}/complete')
def mobile_driver_service_complete(schedule_id: int, payload: DriverServiceCompletion, db: Session = Depends(get_db), user: User = Depends(current_user)):
    driver, vehicle = _driver_vehicle(db, user)
    if not payload.confirmed:
        raise HTTPException(422, 'Driver confirmation required')
    schedule = db.scalar(select(MaintenanceSchedule).where(MaintenanceSchedule.id == schedule_id,
        MaintenanceSchedule.company_id == vehicle.company_id, MaintenanceSchedule.vehicle_id == vehicle.id))
    if schedule is None:
        raise HTTPException(404, 'Maintenance schedule not found for assigned vehicle')
    if vehicle.odometer_km is not None and payload.reading_km < vehicle.odometer_km:
        raise HTTPException(422, 'Service odometer cannot be lower than recorded vehicle mileage')
    previous = schedule.last_service_km
    schedule.last_service_km = payload.reading_km
    schedule.updated_at = datetime.now(timezone.utc)
    vehicle.odometer_km = payload.reading_km
    db.add(OdometerReading(company_id=vehicle.company_id, vehicle_id=vehicle.id,
        reading_km=payload.reading_km, source='SERVICE_COMPLETE',
        note=f'Driver #{driver.id} confirmed {schedule.service_type} service; previous baseline {previous:g} km; schedule #{schedule.id}'))
    db.commit()
    return {'saved': True, 'service_type': schedule.service_type, 'next_due_km': schedule.last_service_km + schedule.interval_km}

def ensure_vehicle_tyre_schedules(db: Session, company_id: int | None = None) -> None:
    """Create missing tyre schedules for existing vehicles, preserving every existing replacement record."""
    q = select(Vehicle)
    if company_id is not None:
        q = q.where(Vehicle.company_id == company_id)
    vehicles = list(db.scalars(q).all())
    if not vehicles:
        return
    ids = [vehicle.id for vehicle in vehicles]
    existing = set(db.scalars(select(MaintenanceSchedule.vehicle_id).where(
        MaintenanceSchedule.vehicle_id.in_(ids), MaintenanceSchedule.service_type == 'TYRES')).all())
    for vehicle in vehicles:
        if vehicle.id not in existing:
            # Registration is the best available tyre-age baseline for legacy vehicles.
            record = MaintenanceSchedule(company_id=vehicle.company_id, vehicle_id=vehicle.id,
                service_type='TYRES', interval_km=60000,
                last_service_km=vehicle.odometer_km or 0, warning_before_km=1000)
            first_reading = db.scalar(select(OdometerReading.created_at).where(
                OdometerReading.vehicle_id == vehicle.id).order_by(OdometerReading.created_at.asc()).limit(1))
            if first_reading is not None:
                record.updated_at = first_reading
            db.add(record)
    if len(existing) < len(vehicles):
        db.flush()


@app.on_event('startup')
def initialize_legacy_tyre_schedules():
    # One-time-per-startup idempotent backfill; GET maintenance remains read-only.
    from ..db import SessionLocal
    with SessionLocal() as db:
        ensure_vehicle_tyre_schedules(db)
        db.commit()


# Smart Oil Life Estimator: independent, read-only advisory.
# Never updates odometers, schedules, scores, or driver settings.
# The phone observes stationary GPS intervals, not actual ignition/engine hours.
@app.get('/api/v1/maintenance/smart-oil/{vehicle_id}')
def smart_oil_estimate(vehicle_id:int, db:Session=Depends(get_db), user:User=Depends(current_user)):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager', 'representative', 'workshop_staff')
    return _smart_oil_calculation(vehicle_id, db, user)

@app.get('/api/v1/mobile/smart-oil')
def driver_smart_oil(db:Session=Depends(get_db), user:User=Depends(current_user)):
    _, vehicle = _driver_vehicle(db, user)
    return _smart_oil_calculation(vehicle.id, db, user)

def _smart_oil_calculation(vehicle_id:int, db:Session, user:User):
    vehicle=db.get(Vehicle, vehicle_id)
    if not vehicle: raise HTTPException(404,'Vehicle not found')
    scope(user,vehicle.company_id)
    service=db.scalar(select(MaintenanceSchedule).where(
        MaintenanceSchedule.vehicle_id==vehicle.id,
        MaintenanceSchedule.company_id==vehicle.company_id,
        MaintenanceSchedule.service_type=='ENGINE_OIL'))
    basic={'vehicle_id':vehicle.id, 'plate_number':vehicle.plate_number,
           'make_model':vehicle.make_model, 'year':vehicle.year,
           'advisory_only':True, 'manufacturer_interval_verified':False,
           'manufacturer_guidance':'Confirm interval using the exact market-specific owner/warranty manual, engine, and oil grade.',
           'engine_hours_measured':False, 'driver_action_required':False}
    if not service or service.interval_km<=0 or vehicle.odometer_km is None:
        return {**basic,'status':'needs_existing_oil_schedule',
                'note':'An existing engine-oil schedule and odometer are needed; no schedule was created or changed.'}
    used_km=max(0., float(vehicle.odometer_km)-float(service.last_service_km))
    interval=float(service.interval_km)
    # Capped investigation scope; does not mutate data or alter trip processing.
    # Select newest trips first until we can approximate the distance since service.
    recent=db.scalars(select(Trip).where(Trip.vehicle_id==vehicle.id,
        Trip.company_id==vehicle.company_id,Trip.status=='completed',Trip.ended_at.is_not(None))
        .order_by(Trip.ended_at.desc(),Trip.id.desc()).limit(500)).all()
    selected=[]
    reconstructed_km=0.
    for t in recent:
        if reconstructed_km >= used_km+0.01: break
        d=max(0.,float(t.distance_km or 0))
        if d<0.01: continue
        fraction=min(1.,max(0.,used_km-reconstructed_km)/d)
        if fraction<=0:break
        selected.append((t.id,fraction,d))
        reconstructed_km+=d*fraction
    coverage=min(1.,reconstructed_km/used_km) if used_km>0 else 1.
    ids=[t[0] for t in selected]
    fractions={trip_id:part for trip_id,part,_ in selected}
    # Bound worst-case historical-data work. A truncated sample is identified as partial.
    points=[]
    if ids:
        points=db.scalars(select(DriverLocation).where(DriverLocation.trip_id.in_(ids),
            DriverLocation.company_id==vehicle.company_id)
            .order_by(DriverLocation.trip_id,DriverLocation.recorded_at,DriverLocation.id).limit(30001)).all()
    truncated=len(points)>30000
    points=points[:30000]
    idle_seconds=0.
    evaluated_seconds=0.
    valid_samples=0
    previous={}
    for p in points:
        if (p.accuracy_m is None or p.accuracy_m>20 or
            p.speed_kmh is None or p.speed_kmh<0 or p.speed_kmh>180):
            previous.pop(p.trip_id,None)
            continue
        valid_samples+=1
        before=previous.get(p.trip_id)
        previous[p.trip_id]=p
        if before is None:continue
        t1=before.recorded_at;t2=p.recorded_at
        if t1.tzinfo is None:t1=t1.replace(tzinfo=timezone.utc)
        if t2.tzinfo is None:t2=t2.replace(tzinfo=timezone.utc)
        dt=(t2-t1).total_seconds()
        if not (5<=dt<=90):continue
        scale=fractions.get(p.trip_id,0.)
        evaluated_seconds+=dt*scale
        if p.speed_kmh<=3 and before.speed_kmh<=3:
            # Short-range displacement check rejects obvious GPS jumps at zero speed.
            a1=math.radians(before.latitude);a2=math.radians(p.latitude)
            da=a2-a1;dl=math.radians(p.longitude-before.longitude)
            hav=math.sin(da/2)**2+math.cos(a1)*math.cos(a2)*math.sin(dl/2)**2
            displaced=6371000.*2*math.asin(min(1.,math.sqrt(max(0.,hav))))
            if displaced<=max(20.,min(50.,dt*.8)):
                idle_seconds+=dt*scale
    # Conversion is a pilot assumption, not a dealer-approved engine-hour equivalence.
    factor=40.
    additional_km=round(idle_seconds/3600*factor,1)
    equivalent_km=round(used_km+additional_km,1)
    advisory_remaining=round(interval-equivalent_km,1)
    distance_coverage=round(coverage*100.,1)
    sufficient=bool(used_km<=0 or (coverage>=.8 and valid_samples>=10 and evaluated_seconds>=60 and not truncated))
    return {**basic,'status':'estimate_available' if sufficient else 'limited_data',
            'last_service_km':float(service.last_service_km),
            'current_odometer_km':float(vehicle.odometer_km),
            'configured_interval_km':interval,
            'original_next_due_km':float(service.last_service_km)+interval,
            'distance_since_service_km':round(used_km,1),
            'gps_stationary_hours':round(idle_seconds/3600,2),
            'gps_observed_hours':round(evaluated_seconds/3600,2),
            'gps_sample_count':valid_samples,
            'trip_distance_coverage_pct':distance_coverage,
            'history_truncated':truncated or len(recent)==500 and coverage<1.,
            'pilot_equivalent_km_per_stationary_hour':factor,
            'pilot_extra_usage_km':additional_km,
            'pilot_equivalent_usage_km':equivalent_km,
            'pilot_allowance_remaining_km':advisory_remaining,
            'pilot_advisory':'Possible early oil service review' if sufficient and advisory_remaining<=float(service.warning_before_km) else 'Monitoring / insufficient data' if not sufficient else 'No earlier review indicated',
            'note':'GPS-observed stationary time can include engine-off stops and excludes idling outside recorded trips. Estimates are not actual engine hours or validated oil-life measurements.'}

@app.get("/api/v1/maintenance-schedules", response_model=list[MaintenanceScheduleOut])
def list_maintenance(db: Session = Depends(get_db), user:User=Depends(current_user)):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    q=select(MaintenanceSchedule).order_by(MaintenanceSchedule.vehicle_id, MaintenanceSchedule.service_type)
    if user.role!='super_admin': q=q.where(MaintenanceSchedule.company_id==user.company_id)
    rows = db.scalars(q).all()
    vehicle_ids={row.vehicle_id for row in rows}
    vehicles={v.id:v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(vehicle_ids))).all()} if vehicle_ids else {}
    return [maintenance_view(row, vehicles[row.vehicle_id]) for row in rows if row.vehicle_id in vehicles]
