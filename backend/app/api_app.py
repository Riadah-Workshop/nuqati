"""FastAPI application object, CORS and the schema bootstrap that must run first.

Kept verbatim from the original top of main.py so that startup order is unchanged.
"""
# ruff: noqa: F401
import math
from fastapi import FastAPI, Depends, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import select, func, delete, text, bindparam
from .config import settings
from .db import Base, engine, get_db
from .models import Company, Driver, Vehicle, OdometerReading, Trip, MaintenanceSchedule, User, DriverMetadata
from .schemas import CompanyCreate, CompanyOut, DriverCreate, DriverOut, VehicleCreate, VehicleOut, OdometerCreate, OdometerOut, MaintenanceScheduleUpsert, MaintenanceScheduleOut
from .auth import current_user, hash_password, verify_password, encode_token, refresh_driver_session, allow, scope
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
import os
from .auth import secret, previous_secret
from .auth_limits import enforce_auth_limit, verify_or_dummy
from .models import AppSetting, AccountInvitation, DriverAccount, DriverDeviceSession, DrivingEvent, DriverLocation, CompanyDrivingSettings, CompanyEventCondition
from datetime import datetime, timedelta, timezone, date
import secrets, hashlib, smtplib, ssl, json, base64
from email.message import EmailMessage
secret()
previous_secret()  # fail fast on a malformed NUQATI_AUTH_SECRET_PREVIOUS
# Tables and columns are created by Alembic revisions (backend/app/migrations), never while this module is imported.
# Interactive API docs expose the full route map; keep them off unless explicitly enabled (local development).
_docs_enabled = os.environ.get('NUQATI_ENABLE_API_DOCS', '').strip().lower() in ('1', 'true', 'yes')
app = FastAPI(title=settings.app_name, version="0.1.0", description="Nuqati fleet and driver performance API",
              docs_url='/docs' if _docs_enabled else None, redoc_url='/redoc' if _docs_enabled else None,
              openapi_url='/openapi.json' if _docs_enabled else None)
from .whatsapp import router as whatsapp_router
app.include_router(whatsapp_router)

origins = [x.strip() for x in settings.cors_origins.split(",") if x.strip()]
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"], expose_headers=["X-Total-Count", "X-Page-Limit"])
