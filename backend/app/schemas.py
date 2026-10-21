from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

class CompanyCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)

class CompanyOut(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)

class DriverCreate(BaseModel):
    company_id: int
    full_name: str = Field(min_length=2, max_length=160)
    phone: str = ""

class DriverOut(BaseModel):
    id: int
    company_id: int
    full_name: str
    phone: str
    status: str
    model_config = ConfigDict(from_attributes=True)

class VehicleCreate(BaseModel):
    company_id: int
    plate_number: str = Field(min_length=1, max_length=40)
    make_model: str = ""
    year: int | None = None
    assigned_driver_id: int | None = None
    odometer_km: float | None = Field(default=None, ge=0)

class VehicleOut(BaseModel):
    id: int
    company_id: int
    plate_number: str
    make_model: str
    year: int | None
    assigned_driver_id: int | None
    odometer_km: float | None
    model_config = ConfigDict(from_attributes=True)

class OdometerCreate(BaseModel):
    company_id: int
    vehicle_id: int
    reading_km: float = Field(ge=0)
    source: str = "MANUAL"
    note: str = ""

class OdometerOut(BaseModel):
    id: int
    company_id: int
    vehicle_id: int
    reading_km: float
    source: str
    note: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class MaintenanceScheduleUpsert(BaseModel):
    company_id: int
    vehicle_id: int
    service_type: str
    interval_km: float = Field(gt=0, le=200000)
    last_service_km: float = Field(ge=0)
    warning_before_km: float = Field(default=500, ge=0, le=20000)

class MaintenanceScheduleOut(BaseModel):
    id: int
    company_id: int
    vehicle_id: int
    service_type: str
    interval_km: float
    last_service_km: float
    warning_before_km: float
    next_due_km: float
    current_odometer_km: float | None
    remaining_km: float | None
    status: str
