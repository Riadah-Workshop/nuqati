"""Server-side, location-free driver reachability alerts.

Runs even if a driver's phone is offline. Presence is determined by server receipt
of authenticated tracking heartbeats (not by GPS or VPN heuristics). An active
signed-in device is required; approved *active* Privacy Mode is excluded.
Alerts are deduplicated in PostgreSQL and remain visible on the dashboard even
when SMTP is unavailable. No GPS coordinates or tokens are ever included.
"""
import logging
import os
import smtplib
import ssl
import threading
from datetime import datetime, timezone
from email.message import EmailMessage

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from .db import engine
from .auth import allow, current_user
from .models import User
from .db import get_db

log = logging.getLogger(__name__)
POLL_SECONDS = 60
OFFLINE_SECONDS = 15 * 60
EMAIL_RETRY_SECONDS = 5 * 60

# Each open incident is unique per driver, even if the worker runs in two pods.
SETUP_SQL = (
    """CREATE TABLE IF NOT EXISTS driver_connection_alerts (
      id BIGSERIAL PRIMARY KEY,
      driver_id INTEGER NOT NULL,
      company_id INTEGER NOT NULL,
      last_contact_at TIMESTAMP WITH TIME ZONE NOT NULL,
      detected_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
      resolved_at TIMESTAMP WITH TIME ZONE,
      email_sent_at TIMESTAMP WITH TIME ZONE,
      email_last_attempt_at TIMESTAMP WITH TIME ZONE
    )""",
    "CREATE UNIQUE INDEX IF NOT EXISTS ux_driver_connection_open_alert ON driver_connection_alerts(driver_id) WHERE resolved_at IS NULL",
    "CREATE INDEX IF NOT EXISTS ix_driver_connection_alert_company ON driver_connection_alerts(company_id,detected_at DESC)",
)

# A driver's last confirmed backend contact is their latest authenticated heartbeat
# or successful device login, whichever happened more recently. Do not produce
# alerts for logged-out devices or intentionally active Privacy Mode.
ACTIVE_DRIVER_SQL = """
  SELECT d.id AS driver_id, d.company_id,
     GREATEST(ds.last_login_at, COALESCE(h.received_at,ds.last_login_at)) AS last_contact_at
  FROM driver_accounts da
  JOIN drivers d ON d.id=da.driver_id
  JOIN users u ON u.id=da.user_id AND u.is_active=TRUE
  JOIN driver_device_sessions ds ON ds.user_id=da.user_id
  JOIN mobile_tracking_heartbeat h ON h.driver_id=d.id AND h.connectivity_policy_version>=2
  WHERE NOT EXISTS (
    SELECT 1 FROM driver_privacy_requests p
    WHERE p.driver_id=d.id AND p.status='active'
  )
"""


def is_overdue(last_contact: datetime, now: datetime) -> bool:
    """Exact 15-minute cut-off, timezone-safe for unit testing."""
    if last_contact.tzinfo is None:
        last_contact = last_contact.replace(tzinfo=timezone.utc)
    return (now - last_contact.astimezone(timezone.utc)).total_seconds() >= OFFLINE_SECONDS


def scan_connection_alerts() -> None:
    """Create/resolve incidents atomically; send emails outside the DB transaction."""
    now = datetime.now(timezone.utc)
    with engine.begin() as db:
        active = db.execute(text(ACTIVE_DRIVER_SQL)).mappings().all()
        stale = {int(r['driver_id']): r for r in active if is_overdue(r['last_contact_at'], now)}
        # Close alerts immediately after a new heartbeat/login or when the
        # session was revoked/privacy approved. No redundant repeat alerts.
        open_alerts = db.execute(text('SELECT id,driver_id FROM driver_connection_alerts WHERE resolved_at IS NULL')).mappings().all()
        for alert in open_alerts:
            if int(alert['driver_id']) not in stale:
                db.execute(text('UPDATE driver_connection_alerts SET resolved_at=:now WHERE id=:id AND resolved_at IS NULL'), {'now':now,'id':alert['id']})
        for driver_id, row in stale.items():
            db.execute(text('''INSERT INTO driver_connection_alerts
                (driver_id,company_id,last_contact_at,detected_at)
                VALUES (:driver,:company,:last,:now) ON CONFLICT DO NOTHING'''),
                {'driver':driver_id,'company':row['company_id'],'last':row['last_contact_at'],'now':now})
        # Reserve an email attempt for five minutes, so repeated workers/restarts
        # do not continuously resend while SMTP is unavailable.
        pending = db.execute(text('''UPDATE driver_connection_alerts
            SET email_last_attempt_at=:now
            WHERE id IN (
              SELECT id FROM driver_connection_alerts
              WHERE resolved_at IS NULL AND email_sent_at IS NULL
                AND (email_last_attempt_at IS NULL OR email_last_attempt_at<:cutoff)
              ORDER BY detected_at ASC LIMIT 30 FOR UPDATE SKIP LOCKED
            ) RETURNING id,driver_id,company_id,last_contact_at'''),
            {'now':now,'cutoff':datetime.fromtimestamp(now.timestamp()-EMAIL_RETRY_SECONDS,timezone.utc)}).mappings().all()

    for alert in pending:
        try:
            with engine.begin() as db:
                # A heartbeat may have arrived while the email was queued.
                # Never notify about an incident already resolved by another scan.
                active = db.execute(text('SELECT resolved_at FROM driver_connection_alerts WHERE id=:id'),
                                    {'id':alert['id']}).first()
                if active is None or active[0] is not None:
                    continue
                details = db.execute(text('''SELECT d.full_name AS driver_name,
                    COALESCE(v.plate_number,'') AS plate
                    FROM drivers d LEFT JOIN vehicles v ON v.assigned_driver_id=d.id AND v.company_id=d.company_id
                    WHERE d.id=:did AND d.company_id=:cid LIMIT 1'''),
                    {'did':alert['driver_id'],'cid':alert['company_id']}).mappings().first()
                users = db.execute(text('''SELECT DISTINCT email FROM users
                    WHERE company_id=:cid AND role IN ('company_admin','fleet_manager')
                      AND is_active=TRUE AND email NOT LIKE '%@login.nuqati.invalid' '''),
                    {'cid':alert['company_id']}).scalars().all()
            if not users:
                continue  # Remain visible on dashboard; retry when a manager exists.
            driver = details['driver_name'] if details else f"#{alert['driver_id']}"
            plate = details['plate'] if details else ''
            last = alert['last_contact_at']
            if isinstance(last, datetime):
                last = last.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
            body = (f"Nuqati has not received a heartbeat from {driver} ({plate}) for at least 15 minutes.\n"
                    f"Last successful contact: {last}.\n"
                    "This indicates loss of communication, not necessarily a VPN issue or stopped GPS recording.\n"
                    "Open the Nuqati dashboard to review Live Tracking and Mobile Diagnostics.\n\n"
                    f"نقاطي: لا يوجد اتصال من السائق {driver} منذ 15 دقيقة على الأقل.\n"
                    f"آخر اتصال بالخادم: {last}.\n")
            _send_manager_email(users, 'Nuqati: driver connection lost | انقطاع اتصال السائق', body)
            with engine.begin() as db:
                db.execute(text('''UPDATE driver_connection_alerts SET email_sent_at=CURRENT_TIMESTAMP
                    WHERE id=:id AND resolved_at IS NULL AND email_sent_at IS NULL'''),{'id':alert['id']})
        except Exception:
            # Never let SMTP, DNS or one missing user terminate the monitoring loop.
            log.exception('NUQATI_MANAGER_CONNECTION_EMAIL_FAILED alert_id=%s',alert['id'])


def _send_manager_email(recipients: list[str], subject: str, body: str) -> None:
    host = os.environ.get('NUQATI_SMTP_HOST','')
    username = os.environ.get('NUQATI_SMTP_USER','')
    password = os.environ.get('NUQATI_SMTP_PASSWORD','')
    if not (host and username and password):
        raise RuntimeError('Nuqati manager alert email requires the existing SMTP configuration')
    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = f'Nuqati <{os.environ.get("NUQATI_EMAIL_FROM","noreply@al-riadah.sa")}>'
    msg['To'] = 'undisclosed-recipients:;'
    msg.set_content(body)
    with smtplib.SMTP(host,int(os.environ.get('NUQATI_SMTP_PORT','587')),timeout=15) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(username,password)
        smtp.send_message(msg,to_addrs=list(recipients))


def list_connection_alerts(db: Session, user: User, company_id: int | None = None):
    allow(user,'super_admin','company_admin','fleet_manager','representative','workshop_staff')
    # The server, never caller-supplied query parameters, scopes company users.
    cid = company_id if user.role=='super_admin' else user.company_id
    if user.role=='super_admin' and cid is None:
        return []  # Require explicit company context to avoid cross-company disclosure.
    query = text('''SELECT a.id,a.driver_id,a.company_id,d.full_name AS driver_name,
        a.last_contact_at,a.detected_at,a.resolved_at,a.email_sent_at,
        COALESCE(v.plate_number,'') AS plate_number
        FROM driver_connection_alerts a
        JOIN drivers d ON d.id=a.driver_id AND d.company_id=a.company_id
        LEFT JOIN vehicles v ON v.company_id=a.company_id AND v.assigned_driver_id=d.id
        WHERE a.company_id=:cid AND a.resolved_at IS NULL
        ORDER BY a.detected_at DESC LIMIT 100''')
    return [dict(r) for r in db.execute(query, {'cid':cid}).mappings().all()]


_monitor_stop = threading.Event()
_monitor_thread = None

def install_connection_monitor(app) -> None:
    global _monitor_thread
    with engine.begin() as db:
        for statement in SETUP_SQL:
            db.execute(text(statement))

    def poll_forever():
        # First scan on boot; then every 60 seconds. The DB survives restarts.
        while not _monitor_stop.is_set():
            try:
                scan_connection_alerts()
            except Exception:
                log.exception('NUQATI_CONNECTION_MONITOR_FAILED')
            if _monitor_stop.wait(POLL_SECONDS):
                break

    def startup():
        global _monitor_thread
        _monitor_stop.clear()
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(target=poll_forever,daemon=True,name='nuqati-connection-monitor')
            _monitor_thread.start()

    def shutdown():
        _monitor_stop.set()
        if _monitor_thread is not None:
            _monitor_thread.join(timeout=2)

    app.add_event_handler('startup',startup)
    app.add_event_handler('shutdown',shutdown)
