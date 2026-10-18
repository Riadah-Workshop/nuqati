from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from .config import settings
from .db import Base, engine, get_db
from .models import Company, Driver, Vehicle, OdometerReading, Trip, MaintenanceSchedule
from .schemas import CompanyCreate, CompanyOut, DriverCreate, DriverOut, VehicleCreate, VehicleOut, OdometerCreate, OdometerOut, MaintenanceScheduleUpsert, MaintenanceScheduleOut

Base.metadata.create_all(bind=engine)
app = FastAPI(title=settings.app_name, version="0.1.0", description="Nuqati fleet and driver performance API")

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/api/v1/health")
def health():
    return {"status": "ok", "service": "nuqati-api", "version": "0.1.0"}

@app.get("/api/v1/dashboard")
def dashboard(db: Session = Depends(get_db)):
    return {
        "companies": db.scalar(select(func.count()).select_from(Company)) or 0,
        "drivers": db.scalar(select(func.count()).select_from(Driver)) or 0,
        "vehicles": db.scalar(select(func.count()).select_from(Vehicle)) or 0,
        "trips_active": db.scalar(select(func.count()).select_from(Trip).where(Trip.status == "active")) or 0,
        "note": "Pilot data only; authentication and company-level authorization are required before production."
    }

@app.post("/api/v1/companies", response_model=CompanyOut, status_code=201)
def create_company(payload: CompanyCreate, db: Session = Depends(get_db)):
    row = Company(name=payload.name.strip())
    db.add(row); db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/companies", response_model=list[CompanyOut])
def list_companies(db: Session = Depends(get_db)):
    return list(db.scalars(select(Company).order_by(Company.name)).all())

@app.post("/api/v1/drivers", response_model=DriverOut, status_code=201)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db)):
    if not db.get(Company, payload.company_id):
        raise HTTPException(404, "Company not found")
    row = Driver(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/drivers", response_model=list[DriverOut])
def list_drivers(db: Session = Depends(get_db)):
    return list(db.scalars(select(Driver).order_by(Driver.full_name)).all())

@app.post("/api/v1/vehicles", response_model=VehicleOut, status_code=201)
def create_vehicle(payload: VehicleCreate, db: Session = Depends(get_db)):
    if not db.get(Company, payload.company_id):
        raise HTTPException(404, "Company not found")
    if payload.assigned_driver_id and not db.get(Driver, payload.assigned_driver_id):
        raise HTTPException(404, "Driver not found")
    if db.scalar(select(Vehicle).where(Vehicle.plate_number == payload.plate_number)):
        raise HTTPException(409, "Plate number already exists")
    row = Vehicle(**payload.model_dump())
    db.add(row); db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/vehicles", response_model=list[VehicleOut])
def list_vehicles(db: Session = Depends(get_db)):
    return list(db.scalars(select(Vehicle).order_by(Vehicle.plate_number)).all())

@app.post("/api/v1/odometer-readings", response_model=OdometerOut, status_code=201)
def create_odometer(payload: OdometerCreate, db: Session = Depends(get_db)):
    vehicle = db.get(Vehicle, payload.vehicle_id)
    if not vehicle or vehicle.company_id != payload.company_id:
        raise HTTPException(404, "Vehicle not found for this company")
    if vehicle.odometer_km is not None and payload.source == "MANUAL" and payload.reading_km < vehicle.odometer_km:
        raise HTTPException(422, "Reading cannot be lower than current stored reading without an audited correction")
    row = OdometerReading(**payload.model_dump())
    vehicle.odometer_km = payload.reading_km
    db.add(row); db.commit(); db.refresh(row)
    return row

@app.get("/api/v1/odometer-readings", response_model=list[OdometerOut])
def list_odometer_readings(db: Session = Depends(get_db)):
    return list(db.scalars(select(OdometerReading).order_by(OdometerReading.created_at.desc()).limit(500)).all())


SERVICE_TYPES = {"ENGINE_OIL", "SPARK_PLUGS", "TRANSMISSION_OIL"}


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
def upsert_maintenance(payload: MaintenanceScheduleUpsert, db: Session = Depends(get_db)):
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


@app.get("/api/v1/maintenance-schedules", response_model=list[MaintenanceScheduleOut])
def list_maintenance(db: Session = Depends(get_db)):
    rows = db.scalars(select(MaintenanceSchedule).order_by(MaintenanceSchedule.vehicle_id, MaintenanceSchedule.service_type)).all()
    return [maintenance_view(row, db.get(Vehicle, row.vehicle_id)) for row in rows]
