"""Nuqati API entry point: `uvicorn app.main:app`.

This module only assembles the application. Each feature module in `app/features/` registers its own
routes on the shared `app` when imported, so the IMPORT ORDER BELOW IS THE ROUTE REGISTRATION ORDER and
also the order in which startup SQL runs. Do not reorder without checking `docs/ARCHITECTURE.md`.
"""
from .api_app import app  # noqa: F401  (created and configured first)

from .features import mobile_audit  # noqa: F401  (driver-app evidence: privacy, lifecycle, heartbeat, notifications, safety observations)
from .features import health  # noqa: F401  (/health and /ready)
from .features import auth_accounts  # noqa: F401  (login, password reset, e-mail change, driver login)
from .features import mfa_accounts  # noqa: F401  (two-step sign-in: second step, enrolment, recovery codes, reset)
from .features import directory  # noqa: F401  (users, companies, drivers, vehicles, odometer)
from .features import maintenance  # noqa: F401  (maintenance, vehicle care, smart oil)
from .features import admin_records  # noqa: F401  (edit/delete records, company logo on edit)
from .features import driver_accounts  # noqa: F401  (driver accounts, /mobile/me, company logo, branding)
from .features import fleet_settings  # noqa: F401  (thresholds, severity, event policy)
from .features import geofence_zones  # noqa: F401  (geofence zones and geometry)
from .features import scoring  # noqa: F401  (Safety Score, RAG policy, phase 4 risk)
from .features import driving_policy  # noqa: F401  (geofence crossings, driving policy, event conditions)
from .features import trips  # noqa: F401  (trip lifecycle, GPS samples, safety events)
from .features import invitations  # noqa: F401  (user invitations)
from .features import branding  # noqa: F401  (branding and labels)
from .features import monthly_reports  # noqa: F401  (monthly reports and export)
from .features import assistance  # noqa: F401  (roadside/workshop assistance)
from .features import fleet_overview  # noqa: F401  (fleet overview summaries)

# Optional second-source vehicle hardware telemetry (read-only to trip/odometer data).
from .hardware import router as hardware_router
app.include_router(hardware_router)


# Scheduled, company-scoped email report subscriptions.
from .report_subscriptions import install_report_subscriptions
install_report_subscriptions(app)
from .features import live_tracking  # noqa: F401  (live snapshot, position requests, live shares)
from .features import diagnostics  # noqa: F401  (driver-app diagnostics)


# Standalone additive, internet-only vehicle handover module.
from .vehicle_handover import router as handover_router
app.include_router(handover_router)


# Persistent, company-scoped manager alerts for unreachable driver devices.
# The alert is based on missed authenticated heartbeats, not inferred VPN status.
from .connectivity_alerts import install_connection_monitor
install_connection_monitor(app)
from .features import connection_alerts  # noqa: F401  (unreachable-driver alerts)
from .features import security_audit_log  # noqa: F401  (read access to the security audit trail)

# Already imported above, so these lines do not change the registration order.
from .features.fleet_settings import thresholds
from .features.scoring import calculate_safety_score, flexible_rag_policy, score_policy

# Additive reference-inspired daily reports (other reports are unchanged).
from .concept_reports import register_concept_reports
register_concept_reports(app,score_policy=score_policy,flexible_rag_policy=flexible_rag_policy,
                         calculate_safety_score=calculate_safety_score,thresholds=thresholds)
