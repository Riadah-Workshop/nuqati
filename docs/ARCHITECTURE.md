# Architecture

Describes the code as it stood after Phase 0 and the backend split of Phase 1 (November 2026). Everything here was read
from the source; numbers are what the code does, not what it intends. Sources are named so a
reviewer can check them.

## 1. Components

| Component | Technology | Code | How it runs |
|---|---|---|---|
| API | Python 3.12, FastAPI, SQLAlchemy 2, Pydantic 2 | `backend/app/` (about 140 endpoints in `features/*.py`, assembled by `main.py` (section 1a); routers in `whatsapp.py`, `hardware.py`, `vehicle_handover.py`; report code in `concept_reports.py`, `report_subscriptions.py`) | `api` service, `uvicorn app.main:app` on port 8000, behind Caddy |
| Web dashboard | React 19, TypeScript (strict), Vite, Leaflet | `web/src/` (`App.tsx` is the whole shell) | Built into static files and served by Caddy (`web` service) |
| Reverse proxy | Caddy 2 | `web/Caddyfile` | Serves the SPA, proxies `/api/*` to `api:8000`, sets security headers |
| Driver app | Flutter, Kotlin (Android) and Swift (iOS) tracking | `driver_app/` | Built by GitHub Actions; local SQLite queue; talks to the API over HTTPS |
| Manager app | Flutter, `flutter_map` | `manager_app/` | Built by GitHub Actions; same login as the dashboard |
| Tracker receiver | asyncio TCP server, Teltonika Codec 8 / 8E | `backend/app/teltonika_receiver.py`, `hardware.py` | `teltonika` service, port 5027, bound to `127.0.0.1` unless configured |
| Report scheduler | Python loop | `backend/app/report_subscriptions.py` | `report_scheduler` service; checks for due email reports every 30 seconds |
| Database | PostgreSQL 16 | models in `backend/app/models.py` plus SQL executed at import time | `db` service with a named volume |
| Database backup | POSIX shell on `postgres:16-alpine` | `ops/backup/` (`backup.sh`, `restore_drill.sh`) | `db_backup` service: daily dump into the `nuqati_backups` volume, health goes red when the last good dump is older than 26 hours (see [docs/OPERATIONS.md](OPERATIONS.md)) |

## 1a. Backend module map

`backend/app/main.py` is only an assembly file. The code that used to be in it now lives in
`api_app.py` and `features/`. **The order of the imports in `main.py` is the order in which routes
are registered and in which import-time SQL runs.** FastAPI uses the first route that matches a path,
and several tables are created or altered by SQL at import time, so do not reorder the imports
without a reason; `test_repo_hygiene.py` fails if `main.py` gains code or a route module is not
imported.

| Module | Contains |
|---|---|
| `api_app.py` | the `app` object, CORS, base tables and vehicle schema DDL; everything else imports `app` from here. API docs (`/docs`, `/redoc`, `/openapi.json`) are off unless `NUQATI_ENABLE_API_DOCS` is set |
| `audit.py` | the security audit trail: creates the `security_audit` table at import and offers `audit()` / `audit_commit()`; feature modules import it, it never imports them |
| `features/security_audit_log.py` | `GET /api/v1/security-audit`: reads the audit trail (super admin: all companies; company admin: own company) |
| `features/mobile_audit.py` | driver-app evidence and audit trails: privacy requests, lifecycle, heartbeats, notifications |
| `features/health.py` | `/health` (liveness) and `/ready` (checks the database) |
| `features/auth_accounts.py` | login, logout, password reset, e-mail change, driver login |
| `features/directory.py` | create and list users, companies, drivers, vehicles, odometer readings |
| `features/maintenance.py` | maintenance schedules, vehicle care, tyre schedules, smart-oil estimate |
| `features/admin_records.py` | edit and delete records; company logo on edit |
| `features/driver_accounts.py` | driver accounts, `/mobile/me`, company logo and branding for the driver |
| `features/fleet_settings.py`, `geofence_zones.py` | thresholds and severity settings; geofence zones and geometry |
| `features/scoring.py` | Safety Score v1, score policy, flexible RAG, phase 4 risk |
| `features/driving_policy.py` | geofence crossings, mobile driving policy and acknowledgements, event conditions |
| `features/trips.py` | trip lifecycle and ingestion: start, GPS samples, safety events, finish, force-end |
| `features/invitations.py`, `branding.py`, `monthly_reports.py`, `assistance.py`, `fleet_overview.py` | user invitations; branding and labels; monthly reports and export; roadside assistance; fleet overview |
| `features/live_tracking.py`, `diagnostics.py`, `connection_alerts.py` | live snapshot and shares; driver-app diagnostics; unreachable-driver alerts |
| `features/shared.py` | small helpers used by several features (`own_driver`, company logo setting) |

Routers that were already separate (`whatsapp.py`, `hardware.py`, `vehicle_handover.py`,
`concept_reports.py`, `report_subscriptions.py`, `connectivity_alerts.py`) are attached from `main.py`
after the feature modules, as before. A feature module starts with `from ..api_app import app` and
must never import `main.py` (it would be circular). **Relative imports inside functions are one level
deeper than they were in the old `main.py`:** write `from ..db import SessionLocal`, not
`from .db import ...`; a wrong one only fails when the function runs (for the startup hook, at
startup). `test_repo_hygiene.py` resolves every relative import, including those inside functions. Tests that check code text use
`backend/backend_source.py`, which reads all of these files as one text.

## 2. Request path and the main data flow

```mermaid
sequenceDiagram
  participant App as Driver app
  participant API as FastAPI
  participant DB as PostgreSQL
  App->>App: detect a trip and store GPS points and events in local SQLite
  App->>API: POST /api/v1/mobile/trips/start with client_trip_id
  API->>DB: map client_trip_id to a trip (idempotent, resumes if known)
  loop every GPS sample, oldest first
    App->>API: POST /api/v1/mobile/trips/{id}/sample with sample_id
    API->>DB: drop duplicates and poor fixes, add distance, derive events
  end
  App->>API: POST /api/v1/mobile/trips/{id}/safety-event with event_id
  App->>API: POST /api/v1/mobile/trips/{id}/finish
```

What the server does with each sample (`submit_sample` in `features/trips.py`):

- Rejects fixes with accuracy worse than 50 m, capture times more than 30 s in the future or
  14 days in the past, and samples older than the newest accepted one (the client must upload
  oldest first).
- Stores a receipt per `(trip_id, sample_id)`, so a retry after a lost response never double
  counts. Samples closer than 0.7 s to the previous one are acknowledged but ignored.
- Adds point-to-point distance only when both fixes have accuracy of 30 m or better and the step is
  between 5 m and `min(80 m/s x elapsed, 1000 m)` and speed-plausible. This filters stationary
  jitter and GPS jumps.
- Detects speeding (company threshold, plus an "excessive" margin), harsh acceleration and
  braking (the reported acceleration must agree within 2 m/s2 with the speed change between
  consecutive GPS points, otherwise it is discarded), harsh cornering (heading change over three
  points) and geofence events.
- Applies per-company GPS-quality conditions (accuracy, fix age, HDOP, satellites). When
  enforcement is on and metadata is missing, the event is **not** recorded (fails closed) but the
  location is still stored.
- Records at most one event per type per trip every 30 seconds.

## 3. Identity and access

- **Roles:** `super_admin`, `workshop_staff`, `company_admin`, `fleet_manager`, `representative`,
  `driver` (`backend/app/auth.py`). Company scoping is enforced on the server (`scope()`), not in the UI.
- **Dashboard login:** email and password. Passwords use PBKDF2-SHA256 with 600,000 rounds; a
  dummy hash is verified for unknown accounts so timing does not reveal them. The access token
  is an HMAC-SHA256 signed `body.signature` token valid for 8 hours, kept in `sessionStorage`.
- **Driver login:** phone or Iqama number plus password plus an app-install `device_id`. Each
  driver is locked to **one device session** (`driver_device_sessions`); logging in elsewhere
  or a manager's "release" revokes the old one. Driver tokens carry the session id; refresh
  tokens last 30 days.
- **Brute-force protection:** database-backed rate limits on login, reset and email-change
  endpoints (`auth_limits.py`); identifiers are stored only as HMAC digests.
- **Secrets:** `NUQATI_AUTH_SECRET` (at least 32 characters) signs every token. Changing it
  signs everyone out, unless the old value is put in `NUQATI_AUTH_SECRET_PREVIOUS` for the
  rotation window: that value is accepted for verifying only, never for signing
  (`auth.signature_valid`). Runbook: `docs/compliance/SECRET_ROTATION.md`.
- **Logout:** `POST /api/v1/auth/logout` raises the user's `auth_version`, so every token the
  user holds, in every browser, stops working. The web app's **Log out** button calls it
  (best effort) after clearing its own session.
- **Audit trail:** `audit.py` writes one row per security-relevant event to `security_audit`:
  sign-in successes and failures, password and e-mail changes, user, driver, vehicle and company
  changes, device releases, invitations, live-share links, settings, report exports and scheduled
  reports. Rows hold the actor, company, target, outcome, client IP (authentication events only)
  and a small `detail` object; passwords, tokens and coordinates are filtered out. The insert runs
  in a connection-level savepoint and never raises, so a failure to audit cannot fail a request.
  `test_security_guards.py` lists which handlers must audit.

## 4. Data model

- **ORM models** (`models.py`): companies, drivers (+ metadata), vehicles, trips, odometer
  readings, maintenance schedules, users, driver accounts and device sessions, driving events,
  driver locations, per-company driving settings and event conditions, app settings,
  account invitations.
- **Tables created by raw SQL at import time** (`CREATE TABLE IF NOT EXISTS` in `api_app.py`, the
  `features/` modules, `hardware.py`, `report_subscriptions.py`): audit and evidence tables (privacy requests and
  audit, lifecycle, notification, tracking heartbeat, safety observations, admin trip actions),
  trip numbering and client-ID / sample / event receipts, driver service history, dashboard
  account tokens, workshop assistance requests, mobile diagnostics, telematics devices and
  points, report email subscriptions, the security audit trail (`audit.py`) and the auth
  rate-limit table (`auth_limits.py`).
  `vehicle_handover.py` defines its own ORM tables, including photos stored as binary rows.
- **No migration tool.** The schema is "whatever the code creates at startup". The SQL uses
  PostgreSQL features (`BIGSERIAL`, `ON CONFLICT`, `ADD COLUMN IF NOT EXISTS`), so SQLite works
  only for a subset of tests.
- **Settings as JSON:** per-company policies and live-share tokens live in `app_settings` under
  keys such as `safety_score_policy:{company_id}`, `flexible_rag_policy:{company_id}` and
  `live_share:{sha256(token)}`.

## 5. Scoring

- **Safety score v1** (`score_policy`): five event categories with integer weights that must
  total 100 (defaults: acceleration 20, braking 20, cornering 20, speeding 25, excessive
  speeding 15), measured as events per 100 km. Below the minimum distance (20 km by default) the
  API returns `score: null` with `reason: insufficient_distance` (`calculate_safety_score`) instead
  of a number, so a driver with almost no driving is never shown 100.
- **Flexible RAG** is opt-in per company and lower-is-better; it is never converted to the
  100-point scale.
- **Reports:** monthly reports, a report suite (trip movement, daily trips, utilisation, daily
  RAG) with Excel / CSV / PDF export (`concept_reports.py`), and scheduled email reports.
  Fuel and engine-idle fields are intentionally empty because no source exists for them.

## 6. Background work

| Job | Where | Cadence |
|---|---|---|
| Connection monitor (offline drivers, email alerts) | thread inside the API process (`connectivity_alerts.py`) | every 60 s; a driver is overdue after 15 min without a heartbeat; failed emails retry after 5 min |
| Scheduled email reports | `report_scheduler` service | polls every 30 s |
| Tracker ingestion | `teltonika` service | continuous TCP |
| Database backup | `db_backup` service | daily at 23:00 UTC; prunes dumps older than 14 days |
| Legacy tyre-schedule backfill | API startup hook | once per start |

## 7. Privacy features

- **Privacy Mode:** a driver requests it (tracking continues while the request is pending), an
  admin approves or rejects it in the Privacy Audit screen, and the app switches native tracking
  off only after approval **and** only when no trip is running. Approval reaches the phone while
  the app UI is running or next resumes; there is no background push (see
  `docs/history/PRIVACY_APPROVAL_BOOT_RECOVERY_20261120.md`). Every toggle is written to an
  append-only audit that contains no coordinates.
- **Live-share links:** random token stored only as a hash, with expiry and revocation. The
  public endpoint returns a position only if the trip is active, the fix is under 120 s old with
  accuracy of 100 m or better, and Privacy Mode is off.
- **Retention:** the privacy policy and `docs/PRIVACY_SECURITY.md` talk about retention, but no
  automatic deletion job exists yet (see section 9). A proposed schedule is in
  `docs/compliance/RETENTION_SCHEDULE.md`; the data inventory is `docs/compliance/DATA_INVENTORY.md`.

## 8. External services

| Service | Used for | Configuration |
|---|---|---|
| SMTP | Invitations, password reset, alerts, scheduled reports | `NUQATI_SMTP_*`, `NUQATI_EMAIL_FROM` |
| Meta WhatsApp | Webhook verification (`/api/v1/whatsapp/webhook`) | `NUQATI_WHATSAPP_VERIFY_TOKEN`, `NUQATI_WHATSAPP_APP_SECRET` |
| MapTiler | Map tiles in web and Manager app | `VITE_MAPTILER_API_KEY` (build time), `MAPTILER_API_KEY` (Manager) |
| unpkg | Leaflet loaded inside the map iframes | allowed in the Caddy CSP |

## 9. Known constraints

These are the reasons the roadmap continues after Phase 0; none is a regression.

1. **Monoliths:** `web/src/App.tsx` (about 1,700 lines, 200+ `useState`) and `driver_app/main.dart`
   (about 2,900 lines), with some lines over 300 characters. The backend `main.py` was split into
   `api_app.py` and `features/*.py` in Phase 1 (section 1a); those modules still hold the old long lines.
2. **Schema by import side effect:** DDL runs when the module loads, in three services, with no
   versioning or rollback.
3. **One HTTP request per GPS sample**, each doing several policy lookups; one Uvicorn process.
4. **Photos in PostgreSQL** (handover inspections): backup size and memory grow with usage.
5. **Custom token format** (rotation works through a single previous-secret window); dashboard token
   in `sessionStorage` while the CSP still allows inline scripts; no second factor for admin roles.
6. **Tracker authentication is IMEI-only**; the network allow-list or a private APN / VPN is the
   real protection.
7. **No automatic data-retention or deletion job** for GPS history.
8. **Health check is shallow:** `/api/v1/health` always answers `ok` and does not touch the database.
9. **PDF exports are English-only** (built-in Helvetica); Arabic shaping needs an embedded font.
10. **Flutter projects are generated in CI**, not committed, so the Android package is still
    `com.example.nuqati_driver` and builds depend on patch scripts inside the workflows.
