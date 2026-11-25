"""Fleet overview: motion and daily driving-event summaries."""

import json
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException
from sqlalchemy import bindparam, func, select, text
from sqlalchemy.orm import Session

from ..api_app import app
from ..auth import allow, current_user, scope
from ..db import get_db
from ..models import AppSetting, DriverLocation, DrivingEvent, Trip, User, Vehicle

# Overview uses one consistent company scope for the period charts and live motion.
def _overview_company_scope(user, company_id):
    allow(user, 'super_admin', 'company_admin', 'fleet_manager', 'representative', 'workshop_staff')
    if user.role != 'super_admin':
        if company_id is not None and company_id != user.company_id:
            raise HTTPException(403, 'Company scope')
        company_id = user.company_id
    if company_id is not None:
        scope(user, company_id)
    return company_id


def _overview_utc(dt):
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _overview_motion(db, company_id, now=None):
    """Current, privacy-aware vehicle motion, independent of historical report filters.

    Only GPS samples no more than five minutes old can classify a vehicle.
    An unreported/stale vehicle is unknown, never assumed stationary.
    """
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(minutes=5)
    ceiling = now + timedelta(seconds=30)  # mobile capture timestamps allow 30s clock skew
    vehicle_filter = [Vehicle.company_id == company_id] if company_id is not None else []
    vehicles = list(db.scalars(select(Vehicle).where(*vehicle_filter)).all())
    by_id = {v.id: v for v in vehicles}
    latest = {}
    if vehicles:
        filters = [Trip.company_id == company_id, DriverLocation.company_id == company_id] if company_id is not None else []
        rows = db.execute(select(DriverLocation, Trip.vehicle_id, Trip.driver_id)
                          .join(Trip, Trip.id == DriverLocation.trip_id)
                          .where(Trip.vehicle_id.in_(by_id),
                                 Trip.driver_id == DriverLocation.driver_id,
                                 Trip.company_id == DriverLocation.company_id,
                                 DriverLocation.recorded_at >= since,
                                 DriverLocation.recorded_at <= ceiling,
                                 DriverLocation.accuracy_m >= 0,
                                 DriverLocation.accuracy_m <= 50,
                                 DriverLocation.speed_kmh >= 0,
                                 DriverLocation.speed_kmh <= 180,
                                 *filters)
                          .order_by(DriverLocation.recorded_at.desc(), DriverLocation.id.desc())).all()
        for location, vehicle_id, driver_id in rows:
            vehicle = by_id.get(vehicle_id)
            if vehicle and vehicle.assigned_driver_id == driver_id and vehicle_id not in latest:
                latest[vehicle_id] = (_overview_utc(location.recorded_at), float(location.speed_kmh))

    # The Fleet Live view can also request a fresh, independent device position.
    # Use it only if newer than an ordinary valid GPS sample and for the assigned driver.
    setting_keys = [f'live_request:{vid}' for vid in by_id]
    if setting_keys:
        settings_rows = db.scalars(select(AppSetting).where(AppSetting.key.in_(setting_keys))).all()
        for setting in settings_rows:
            try:
                vehicle_id = int(setting.key.split(':', 1)[1])
                vehicle = by_id[vehicle_id]
                payload = json.loads(setting.value)
                result = payload.get('result') if payload.get('status') == 'completed' else None
                if not isinstance(result, dict) or not vehicle.assigned_driver_id:
                    continue
                if int(result.get('driver_id')) != vehicle.assigned_driver_id:
                    continue
                recorded_at = _overview_utc(datetime.fromisoformat(result['recorded_at']))
                speed = float(result['speed_kmh'])
                accuracy = float(result['accuracy_m'])
                if not (since <= recorded_at <= ceiling and 0 <= speed <= 180 and 0 <= accuracy <= 50):
                    continue
                if vehicle_id not in latest or recorded_at > latest[vehicle_id][0]:
                    latest[vehicle_id] = (recorded_at, speed)
            except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
                continue

    # Do not infer or expose a vehicle's motion while its driver has enabled privacy mode.
    driver_ids = {v.assigned_driver_id for v in vehicles if v.assigned_driver_id is not None}
    private_drivers = set()
    if driver_ids:
        audit_rows = db.execute(text("SELECT driver_id, privacy_enabled FROM mobile_privacy_audit "
            "WHERE driver_id IN :ids ORDER BY selected_at DESC, received_at DESC").bindparams(
                bindparam('ids', expanding=True)), {'ids': sorted(driver_ids)}).all()
        seen_drivers = set()
        for driver_id, enabled in audit_rows:
            if driver_id not in seen_drivers:
                seen_drivers.add(driver_id)
                if enabled:
                    private_drivers.add(driver_id)

    moving = stationary = 0
    for vehicle_id, (_at, speed) in latest.items():
        if by_id[vehicle_id].assigned_driver_id in private_drivers:
            continue
        if speed >= 5:
            moving += 1
        elif speed <= 2:
            stationary += 1
    return {'moving': moving, 'stationary': stationary,
            'unknown': len(vehicles) - moving - stationary,
            'as_of': now.isoformat(), 'freshness_minutes': 5}


@app.get('/api/v1/fleet/overview/motion')
def fleet_overview_motion(company_id: int | None = None,
                          db: Session = Depends(get_db), user: User = Depends(current_user)):
    cid = _overview_company_scope(user, company_id)
    return _overview_motion(db, cid)


_OVERVIEW_DRIVING_EVENTS = {
    'speeding': ('speeding', 'excessive_speeding'),
    'harsh_braking': ('harsh_braking', 'excessive_harsh_braking'),
    'harsh_acceleration': ('harsh_acceleration', 'excessive_harsh_acceleration'),
    'harsh_cornering': ('harsh_cornering',),
}
_OVERVIEW_DRIVING_TYPES = set().union(*_OVERVIEW_DRIVING_EVENTS.values())


@app.get('/api/v1/fleet/overview/daily')
def fleet_overview_daily(days: int = 7, company_id: int | None = None,
                         from_at: datetime | None = None, to_at: datetime | None = None,
                         db: Session = Depends(get_db), user: User = Depends(current_user)):
    """Recorded trips grouped by UTC trip-start date and driving events by UTC event date.

    The live motion snapshot is always current, even when the date range is historical.
    Geofence notifications and duration-session records are not driving-behavior events.
    """
    company_id = _overview_company_scope(user, company_id)
    days = max(1, min(days, 31))
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    start = end - timedelta(days=days)
    if from_at is not None or to_at is not None:
        if from_at is None or to_at is None:
            raise HTTPException(422, 'Both from_at and to_at are required')
        start = _overview_utc(from_at)
        end = _overview_utc(to_at)
        if end <= start or end - start > timedelta(days=366):
            raise HTTPException(422, 'Invalid overview date range (maximum 366 days)')
        # to_at is exclusive. Midnight of the following day is not a chart day.
        days = ((end - timedelta(microseconds=1)).date() - start.date()).days + 1
    company_filter = [Trip.company_id == company_id] if company_id is not None else []
    trips = list(db.scalars(select(Trip).where(Trip.started_at >= start, Trip.started_at < end,
                                               *company_filter)).all())
    event_filter = [DrivingEvent.company_id == company_id] if company_id is not None else []
    events = list(db.scalars(select(DrivingEvent).where(DrivingEvent.recorded_at >= start,
                                                        DrivingEvent.recorded_at < end,
                                                        DrivingEvent.event_type.in_(_OVERVIEW_DRIVING_TYPES),
                                                        *event_filter)).all())
    vehicle_filter = [Vehicle.company_id == company_id] if company_id is not None else []
    vehicle_count = db.scalar(select(func.count(Vehicle.id)).where(*vehicle_filter)) or 0
    rows = []
    for i in range(days):
        day = datetime.combine(start.date() + timedelta(days=i), datetime.min.time(), tzinfo=timezone.utc)
        next_day = day + timedelta(days=1)
        ts = [t for t in trips if day <= _overview_utc(t.started_at) < next_day]
        ev = [e for e in events if day <= _overview_utc(e.recorded_at) < next_day]
        counts = {name: sum(e.event_type in kinds for e in ev) for name, kinds in _OVERVIEW_DRIVING_EVENTS.items()}
        used = len({t.vehicle_id for t in ts})
        rows.append({'date': day.date().isoformat(), 'trips': len(ts),
                     'distance_km': round(sum(max(0, t.distance_km or 0) for t in ts), 2),
                     'drivers_active': len({t.driver_id for t in ts}),
                     'vehicles_with_trips': used,
                     'vehicles_without_trips': max(0, vehicle_count - used),
                     'violations': len(ev), **counts})
    return {'days': rows, 'vehicle_count': vehicle_count,
            'motion': _overview_motion(db, company_id),
            'totals': {'trips': len(trips),
                       'distance_km': round(sum(max(0, t.distance_km or 0) for t in trips), 2),
                       'drivers_active': len({t.driver_id for t in trips}),
                       'vehicles_with_trips': len({t.vehicle_id for t in trips}),
                       'violations': len(events)}}
