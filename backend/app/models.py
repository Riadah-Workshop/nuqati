from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now_utc():
    return datetime.now(timezone.utc)

class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class Driver(Base):
    __tablename__ = "drivers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(20), default="active")

class DriverMetadata(Base):
    __tablename__ = 'driver_metadata'
    driver_id: Mapped[int] = mapped_column(ForeignKey('drivers.id'), primary_key=True)
    id_number: Mapped[str] = mapped_column(String(40), nullable=False)
    site_name: Mapped[str] = mapped_column(String(160), nullable=False)

class Vehicle(Base):
    __tablename__ = "vehicles"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    plate_number: Mapped[str] = mapped_column(String(40), unique=True, nullable=False)
    make_model: Mapped[str] = mapped_column(String(120), default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    door_number: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assigned_driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), nullable=True)
    odometer_km: Mapped[float | None] = mapped_column(Float, nullable=True)

class Trip(Base):
    __tablename__ = "trips"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    distance_km: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")

class OdometerReading(Base):
    __tablename__ = "odometer_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    reading_km: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(30), default="MANUAL")
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class MaintenanceSchedule(Base):
    __tablename__ = "maintenance_schedules"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"), index=True)
    service_type: Mapped[str] = mapped_column(String(32), nullable=False)
    interval_km: Mapped[float] = mapped_column(Float, nullable=False)
    last_service_km: Mapped[float] = mapped_column(Float, nullable=False)
    warning_before_km: Mapped[float] = mapped_column(Float, default=500)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc, onupdate=now_utc)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class DriverAccount(Base):
    __tablename__ = "driver_accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), unique=True, nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), unique=True, nullable=False)

class DrivingEvent(Base):
    __tablename__ = "driving_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class DriverLocation(Base):
    __tablename__ = "driver_locations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), index=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"), index=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"), index=True)
    latitude: Mapped[float] = mapped_column(Float, nullable=False)
    longitude: Mapped[float] = mapped_column(Float, nullable=False)
    accuracy_m: Mapped[float] = mapped_column(Float, nullable=False)
    speed_kmh: Mapped[float] = mapped_column(Float, default=0)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

class CompanyDrivingSettings(Base):
    __tablename__ = "company_driving_settings"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    speeding_kmh: Mapped[float] = mapped_column(Float, default=100)
    harsh_accel_ms2: Mapped[float] = mapped_column(Float, default=3)
    harsh_brake_ms2: Mapped[float] = mapped_column(Float, default=3)


class CompanyEventCondition(Base):
    __tablename__ = "company_event_conditions"
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(40), primary_key=True)
    max_gps_age_seconds: Mapped[float] = mapped_column(Float, default=2)
    max_hdop: Mapped[float | None] = mapped_column(Float, nullable=True)
    min_satellites: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_accuracy_m: Mapped[float] = mapped_column(Float, default=50)


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)

class AccountInvitation(Base):
    __tablename__ = "account_invitations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
