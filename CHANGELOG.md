# Changelog

All notable changes to Nuqati. Format follows [Keep a Changelog](https://keepachangelog.com/).
Notes written before this file existed are in [`docs/history/`](docs/history/README.md).

## [Unreleased]

### Phase 4.2: encrypted off-server backup copy (Google Drive)

#### Added
- `ops/backup/offsite.sh`: after every good dump, `db_backup` can copy it to Google Drive (or any folder, `NUQATI_OFFSITE=local`)
  **encrypted on the server first** (rclone `crypt`, two passphrases only the owner holds). The upload is verified against the
  checksum the destination holds for the encrypted file (`rclone cryptcheck`) before it counts; a failed copy is retried every
  hour; copies older than 30 days are deleted (the newest 3 always kept, only dump-named files touched, a failed listing deletes
  nothing). **Off by default**: nothing leaves the server until `NUQATI_OFFSITE` is set.
- Google Drive through a service account on a Shared Drive (Google Workspace) or through the owner's own OAuth client with the
  narrow `drive.file` scope (personal account). Setup guide, key custody and the data-location question for counsel:
  `docs/compliance/BACKUP_RESTORE.md` 2b and `docs/compliance/DATA_INVENTORY.md`.
- `offsite.sh test` (uploads a small file, reads it back, checks it is unreadable at the destination, deletes it),
  `offsite.sh fetch`, `offsite.sh list`, `restore_drill.sh --offsite` (restore from the off-server copy alone, with the
  passphrases from the password manager), `backup.sh offsite-retry`.
- The `db_backup` health status also turns red when the last good off-server copy is older than 50 hours or the off-server
  settings are wrong (local backups continue either way). `backup.sh once` exits 3 when the backup is good but the copy failed.
- The backup image now contains rclone (`apk add rclone`). Twelve optional settings, all empty = off/default
  (`NUQATI_OFFSITE*`, see `.env.example`).
- CI: the job "Backup and restore drill" now also runs the real rclone against a second volume: encrypted upload, verification,
  the stored file shows no plain text, restore from the off-server copy alone, wrong passphrases, a damaged copy detected and
  replaced, retention, a whole cycle, and invalid settings. 62 stand-in tests in `backend/test_ops_offsite.py`.

#### Not covered
- The Google Drive side itself (credentials, quota, token expiry) cannot be tried in CI: it needs real credentials and this
  repository is public. `offsite.sh test` does it on the server.

### Phase 4.1: request limits per user (security finding S9)

#### Added
- `backend/app/rate_limits.py`: in-memory token buckets per user for GPS samples, safety events, tracking heartbeats,
  exports and report screens (nine routes). `NUQATI_RATE_LIMIT_INGEST` (default `log`: only logs what it would refuse)
  and `NUQATI_RATE_LIMIT_REPORTS` (default `enforce`); `off` / `log` / `enforce`. See `docs/OPERATIONS.md` section 7.
- CI job **Load test (GPS ingestion)** (`ops/loadtest/`): the real API container and PostgreSQL with 50, 100, 200 and 400 simulated
  phones, a 20-phone backlog replay (2,000 samples), an abusive client next to 50 normal phones, and exports during ingestion.
  It fails on errors, refused normal phones, lost samples or tracebacks; speed is reported in the job summary, not judged.
- `backend/app/db_pool.py`: the database connection pool is now explicit (`NUQATI_DB_POOL_SIZE` 5, `NUQATI_DB_MAX_OVERFLOW` 10, the
  same numbers as before) and a request is admitted only when a slot is free (`NUQATI_DB_REQUEST_SLOTS`, default 10). See
  `docs/OPERATIONS.md` section 8.
- A refused request answers HTTP 429 with `Retry-After`. The driver app keeps the data and retries; the text never contains the one
  phrase the app uses to drop a GPS point, and a test reads `driver_app/main.dart` to keep it that way.

#### Fixed
- **The API stalled when many requests arrived at once.** The load test (300 phones sending at the same instant, and 400 phones
  at 200 requests per second) made every worker thread wait for a database connection that another waiting request held; the API
  did nothing for 30 seconds, answered the waiting requests with HTTP 500 (`QueuePool limit of size 5 overflow 10 reached`) and
  repeated. It could happen in production when all phones upload their backlog after an API restart. `get_db` is now asynchronous
  and admits only as many requests as the pool can serve (10 of 15 connections; the rest are kept for the readiness check and
  routes that open their own connection), the others wait in the event loop without holding a thread. Phones kept their data
  during the stalls (the app retries), so nothing was lost, but the API was unusable. Measured in CI with 300 phones sending at
  once: before, 600 of 900 requests failed; with the limit switched off in a control run, 731 of 900 failed (107 pool errors);
  after, 0 of 900 failed (p95 1.6 s). 400 phones (140 to 170 requests per second) now complete with a median answer of 2 to 3 s instead
  of failing.

### Phase 4.3: two-step sign-in for dashboard accounts (security finding S4c)

#### Added
- **Two-step sign-in with an authenticator app (TOTP, RFC 6238), optional.** Off until `NUQATI_MFA_KEY` is set; nothing changes for anyone before
  that. Then any dashboard account can switch it on under **My account**; `NUQATI_MFA_REQUIRED_ROLES` (for example `super_admin,company_admin`)
  makes it compulsory: a person in such a role who has not set it up is taken to the setup right after the password and gets a session only when it is done.
- `POST /api/v1/auth/login` answers `mfa_required` (or `mfa_setup_required`) without an access token for such accounts; `POST /api/v1/auth/login/mfa`
  completes the sign-in with a 6-digit code or a recovery code. New routes under `/api/v1/auth/mfa` (status, enroll, confirm, recovery codes, disable) and
  `/api/v1/users/{id}/mfa` (status, reset; super admin). Server command `python -m app.mfa_tools [status|reset] EMAIL` for the case that nobody can reset an account.
- Web: second step on the sign-in screen, forced setup screen for required roles, **Two-step sign-in** panel under My account, reset button on the user page.
  Manager app: asks for the code (setup is done once in the web dashboard).
- Migration `0002`: tables `user_mfa` and `user_mfa_recovery_codes` (the first real revision; additive; removed with the account).
- Dependency: `cryptography` (AES-256-GCM for the stored authenticator secrets).
- Safety: a code works once; 5 wrong codes lock the second step for 15 minutes, then longer (up to 24 hours); the secret is stored encrypted under its own
  key (not the token-signing secret, so an emergency rotation of that does not lock anyone out); an enrolled account is never let in with the password
  alone, not even when the key is lost (it fails closed and the runbook says how to recover); recovery codes are stored as salted hashes; every step is
  in the security audit trail (`auth.login` outcome `pending`, `auth.mfa`, `auth.mfa_enroll`, `auth.mfa_recovery`, `auth.mfa_disable`, `auth.mfa_reset`).
- Tests: `test_mfa_units.py` (RFC 6238 vectors and more, 36 cases), `test_mfa_postgres.py` (14 end-to-end cases); the CI job **Migrations** now proves that a
  pre-Alembic database is adopted and upgraded to `0002` in one start, adding only `0002`'s objects and ending identical to a new database.
- Runbook: `docs/OPERATIONS.md` section 9 (rollout order, lost phone, last super admin, key loss and rotation); `SECRET_ROTATION.md`, `BACKUP_RESTORE.md`
  (the key must be saved with the other secrets), `DATA_INVENTORY.md`, `RETENTION_SCHEDULE.md` R16.

#### Changed
- The Migrations job and `test_migrations.py` expect head revision `0002`; the CI probe revisions are now `0003`.
- The guard tests list the new public route (`/api/v1/auth/login/mfa`, throttled) and three audit helpers that are not routes.

#### Not included
- No QR code (the setup screen shows the key to type and an `otpauth://` link that opens the authenticator app on the same phone); no push or SMS codes;
  drivers are not covered (they sign in with their own flow and a bound device).

### Phase 5.2: no third-party script in the map frames (security finding S5)

#### Changed
- The two map frames (`FleetPositionMap.tsx`, `TripLiveMap.tsx`) no longer load Leaflet from `unpkg.com`. Leaflet 1.9.4 (same version) comes
  from the locked npm package and is written into each frame (`web/src/leafletInline.ts`). A compromised or unreachable CDN can no longer
  read fleet positions or blank the maps, and unpkg no longer sees dashboard users' addresses.
- Content-Security-Policy (`web/Caddyfile`): `unpkg.com` removed from `script-src` and `style-src`; `connect-src` narrowed from
  `'self' https: wss:` to `'self'` (every request the dashboard makes goes to its own origin; map tiles are images).
- The frame HTML is now built by two exported functions (`buildFleetMapHtml`, `buildTripMapHtml`); the markup and script are unchanged.

#### Added
- CI step "Map frames render in a real browser with no network" (`web/scripts/check-map-frames.mjs`): builds both frames with the real
  code, opens them in headless Chrome with every host name unresolvable, counts the drawn vehicles, events and geofences, and runs a
  control without the Leaflet script that must fail the same checks.
- `backend/test_web_csp.py`: the policy allows no script host and `connect-src 'self'`; no `unpkg.com` anywhere in `web/`.

#### Not verified
- How the maps look in the production dashboard (CI renders both frames in Chrome and counts shapes, it does not compare pixels).

### Phase 3.4: the application no longer creates tables itself

#### Changed
- **Alembic is now the only way the schema changes.** The 38 SQL statements and 5 `create_all` calls that ran while the
  application modules were imported (16 modules) are removed. Tables, columns and indexes come from the Alembic
  baseline (`0001`) and later revisions. A test fails if application code contains `CREATE TABLE`, `ALTER TABLE`,
  `CREATE INDEX` or `create_all`.
- **Migrations run by default.** The `api` container applies pending migrations before it starts
  (`NUQATI_RUN_MIGRATIONS` now defaults to `1`; `0` skips it). `python -m app.bootstrap_admin` no longer creates tables;
  it asks you to run `python -m app.migrate` first.
- The integration tests (`test_auth_runtime_postgres.py`, `test_security_audit_postgres.py`) and the CI jobs for backups and
  workers build their database with `python -m app.migrate`.
- CI job **Migrations**: a database built only by migrations; importing the whole application changes nothing in the schema;
  every table and column of the ORM models exists in the migrated schema (`ops/ci/check_models.py`); an existing database
  (the baseline applied without `alembic_version`) is adopted unchanged; incomplete databases are refused; failing and
  good revisions; the container with migrations on by default, failing fast, and switched off (then no table is created).
- A test pins the SHA-256 of `0001_baseline.sql`: a released revision is never edited.

#### Removed
- The one-off backfill of `mobile_trip_numbers` (it ran only while that table was empty, which production has long
  passed; trips get their number when first needed). The temporary baseline tools `ops/ci/schema_dump.sh` and
  `baseline_rewrite.sed`.

#### Upgrade note
- Before merging, set `NUQATI_RUN_MIGRATIONS=1` on the Phase 3.3 deployment and check for `Existing database adopted`
  in the `api` log (`docs/DEPLOY_COOLIFY.md`). A database too old for the baseline can be brought up to date once with commit
  `56c09fe`, the last version that still creates missing tables itself.

### Phase 3.3: database migrations (Alembic)

#### Added
- **Alembic migrations, off by default.** `backend/app/migrations/` (revision `0001` = the schema the application built
  by itself until Phase 3.2, `versions/0001_baseline.sql`) and `python -m app.migrate` (`upgrade`, `status`, `check`,
  `new`). An existing database is adopted: compared with the baseline in a scratch schema that is rolled back and
  then only marked as revision `0001`, nothing changed; a database that lacks tables or columns is refused with a list.
  One run at a time (advisory lock). A failing revision is rolled back completely.
- `NUQATI_RUN_MIGRATIONS` (default `0`): when `1` the `api` container migrates before it starts and stops if that fails.
  With `0` it starts exactly as before.
- CI job **Migrations** on a real PostgreSQL: the committed baseline equals what the application's own code builds; a
  database built only by migrations has an identical schema (columns, defaults, constraints, indexes, sequences) and the
  old start-up SQL changes nothing on it; adoption changes nothing; missing table/column is refused and left alone; a
  failing revision leaves no trace and a good one applies; the container starts with migrations on, fails fast on a bad
  database, and is unchanged with them off.
- `backend/test_migrations.py` (23 tests) including a guard that **freezes the old start-up SQL**: a new
  `CREATE TABLE`, `ALTER TABLE`, `CREATE INDEX` or `create_all` in application code fails the build with
  "add an Alembic revision instead".

#### Changed
- `docs/DEVELOPMENT.md` section 6 (how to make a schema change), `docs/DEPLOY_COOLIFY.md` (turning migrations on),
  `docs/OPERATIONS.md` (symptoms), `docs/ARCHITECTURE.md`.
- `backend/requirements.txt`: `alembic>=1.13,<2`.

### Phase 3.2: worker health checks

#### Added
- **Heartbeat for the background workers.** `backend/app/heartbeat.py` (standard library only). The tracker receiver
  beats every 15 s from its event loop, the report scheduler once per cycle. `compose.yml` gives both services a
  healthcheck (`python -m app.heartbeat <name> <limit>`; limits 90 s and 15 min), so a frozen receiver or a stuck
  scheduler shows as unhealthy in Coolify instead of "running". The optional second-source file
  `hardware-teltonika.compose.yml` gets the same check.
- **Optional watchdog, off by default.** `NUQATI_WORKER_WATCHDOG_SECONDS` (minimum 120): a thread in each worker ends
  the process with exit code 70 when its heartbeat is that old, so `restart: unless-stopped` starts a fresh one.
- CI job **Worker health checks**: the real receiver and scheduler run in containers against PostgreSQL; both report
  healthy, a receiver frozen with SIGSTOP turns unhealthy and recovers after SIGCONT. `backend/test_worker_heartbeat.py`
  adds 37 tests (module, a real process exiting with code 70, and the wiring between `compose.yml` and the workers).

#### Changed
- `docs/OPERATIONS.md`: what the worker checks show and do not show, the watchdog, updated symptom table.

### Phase 3.1: reliability and operations

#### Added
- **Daily database backup.** New `db_backup` service in `compose.yml` (code in `ops/backup/`). It writes one
  `pg_dump` custom-format dump a day (23:00 UTC) into the new volume `nuqati_backups`, reads each dump back with
  `pg_restore --list` before accepting it, writes under a temporary name so a half-written file is never taken for a
  backup, keeps 14 days (never fewer than 3 dumps) and logs a warning when a dump is less than half the size of the
  previous one. Its healthcheck turns red when the last good dump is older than 26 hours. Settings:
  `NUQATI_BACKUP_HOUR_UTC`, `NUQATI_BACKUP_KEEP_DAYS`. The dumps are on the same server; the off-server copy
  stays manual.
- **Restore drill in one command.** `docker exec <db_backup-container> /usr/local/bin/restore_drill.sh` restores the
  newest dump into a throw-away database, compares the main tables with the live database (read-only), prints a
  `RESULT:` line for the drill log and always drops the copy again.
- `docs/OPERATIONS.md`: services and what is monitored, external uptime monitoring on `/api/v1/ready`, weekly checks,
  disk growth, a symptom table and what is not covered yet.
- CI job **Backup and restore drill**: real PostgreSQL with the application's real schema, the backup image built
  through `compose.yml`, a backup, the health signal, a restore drill, and the failure cases (wrong password,
  empty volume). `backend/test_ops_backup_scripts.py` adds 33 fast logic tests with stand-in PostgreSQL programs.

#### Changed
- **Container logs are capped** at 5 files of 10 MB per service (`x-logging` in `compose.yml`). Docker's default has no
  limit and can fill the disk.
- **Database connections** give up after 5 seconds (`connect_timeout`, PostgreSQL only), so `/api/v1/ready` answers
  `503` quickly when the database does not respond instead of waiting for the operating system's default.
- Compliance documents: `BACKUP_RESTORE.md` (automatic on-server dumps, one-command drill), `RETENTION_SCHEDULE.md`
  (R15: 14 days on the server, 30 days off the server), `DATA_INVENTORY.md` (backups row).

#### After merging
The first deployment builds one more image and creates the `nuqati_backups` volume; the first dump is taken a few
minutes after `db_backup` starts. Run the first restore drill and record it in `BACKUP_RESTORE.md` section 6.

### Phase 2.1: security audit trail, hardening and compliance documents

#### Added
- **Security audit trail.** New table `security_audit` (created at API start, like the other tables) and the helper
  `backend/app/audit.py`. One row per event: sign-in successes and failures (dashboard and driver), logout, password
  reset and e-mail-change steps, password change, user / driver / vehicle / company create, edit, deactivate and
  delete, odometer correction, driver device release, invitations, live-share links, threshold, event-policy,
  geofence and branding changes, report exports, and scheduled-report changes. It stores the actor, company,
  target, outcome and the client IP of authentication events; passwords, tokens and coordinates are filtered out;
  a failed sign-in for an unknown account stores no identifier. The handlers' behaviour is unchanged (checked: removing
  the audit calls restores the original code, statement for statement).
- `GET /api/v1/security-audit` (new module `features/security_audit_log.py`): newest first, filters `company_id`,
  `action`, `actor_user_id`, `outcome`, `since`, paging. Super admin: all companies. Company admin: own company only.
- `POST /api/v1/auth/logout`: ends every session of the signed-in dashboard user (raises `auth_version`). The web
  **Log out** button calls it after clearing its own session.
- **Secret rotation window.** `NUQATI_AUTH_SECRET_PREVIOUS` is accepted for verifying tokens only, never for
  signing; remove it after 30 days. Without it, behaviour is unchanged. `compose.yml` passes the variable through.
- `.github/workflows/security.yml`: advisory weekly checks (pip-audit, npm audit, CodeQL for Python and
  JavaScript/TypeScript, gitleaks). Every job is `continue-on-error`; nothing blocks a merge or deploy. It also
  attaches `backend-requirements.lock.txt` (today's resolved backend versions) as an artifact.
- Tests: `backend/test_security_guards.py` (the exact list of 15 routes that need no login, SQL text only assembled
  in reviewed places, no unsafe calls, audit calls present and free of secrets, docs off in production),
  `backend/test_security_units.py` (audit helper, rotation window) and `backend/test_security_audit_postgres.py`
  (audit rows, logout, scoping, rotation end to end, docs off; runs in CI against PostgreSQL).
- `docs/compliance/`: data inventory, **proposed** retention schedule, incident-response runbook (72-hour
  notification step), data-subject request procedure (30-day answer), backup and restore runbook, secret-rotation
  runbook. They are operating documents, not legal advice.

#### Changed
- The interactive API docs (`/docs`, `/redoc`, `/openapi.json`) are off unless `NUQATI_ENABLE_API_DOCS=1`. The local
  `docker-compose.yml` sets it; the production `compose.yml` does not. Through the public site they were never
  reachable (Caddy proxies only `/api/*`); this closes the direct container port as well.
- The web app removes `?invite=`, `?reset=` and `?confirm_email=` from the address bar right after reading the
  token, so it stays out of browser history and screenshots. `?live_share=` is untouched.
- Android: `android:allowBackup="false"` is now added by the manifest patch in `build-android.yml`,
  `build-driver-release.yml`, `build-manager-android.yml` and `build-manager-release-fixed-version.yml` (applies to the
  next app builds).
- `ci.yml` and `make test-pg` also run `test_security_audit_postgres.py`.

### Phase 1.1: backend `main.py` split into modules (no application behaviour changed)

#### Changed
- `backend/app/main.py` (about 4,000 lines) is now a 56-line assembly file. Its code moved, statement
  for statement (only ten relative imports inside functions had to change, see Fixed), into `backend/app/api_app.py` (app object, CORS, base schema)
  and 20 modules in `backend/app/features/`. The import order in `main.py` is the route-registration
  and import-time-SQL order of the old file, so all routes keep their precedence. Module map:
  `docs/ARCHITECTURE.md`, section 1a.
- Tests that read code text from `main.py` (`test_company_one_page_editor.py`,
  `test_handover_integration_contract.py`, `test_driver_vpn_queue_contract.py`,
  `test_native_tracking_regression_contract.py`, `test_safety_counts_trip_number_contract.py`) now
  read it through the new `backend/backend_source.py`.

#### Fixed
- Ten relative imports inside functions (`from .vehicle_handover import ...` x9 and `from .db import
  SessionLocal` in the startup hook `initialize_legacy_tyre_schedules`) pointed at `app.features.*` after the
  move and would have failed at startup / on driver, vehicle and company edits. They now use `..`.

#### Added
- `backend/test_repo_hygiene.py`: every relative import (also inside functions) must resolve to a real module and name;
  the modules Docker/compose start must exist; no application code in `backend/` root; `main.py` may only assemble; every feature module that has routes
  must be imported by `main.py`; feature modules must not import `main.py`.
- CI Docker check also asserts that `api_app.py` and the `features/` modules are in the API image.

### Phase 0: repository hygiene and safety net (no application behaviour changed)

#### Added
- `README.md` with architecture diagram, layout and quick start; `docs/ARCHITECTURE.md`,
  `docs/DEVELOPMENT.md`, `CONTRIBUTING.md`, `.env.example`, pull-request template.
- CI: `.github/workflows/ci.yml` (backend tests on SQLite and PostgreSQL, web type-check and
  build, Docker image / compose / Caddyfile checks, advisory Ruff lint) and
  `ci-flutter.yml` (`flutter analyze` for both apps on pull requests).
- `backend/requirements-test.txt` (referenced by the 2026-11-12 security notes but missing).
- `backend/test_repo_hygiene.py`: repository-layout guards.
- `.github/dependabot.yml`, `pyproject.toml` (pytest and Ruff settings), `Makefile`.
- `.gitignore`, `.editorconfig`, `.gitattributes`.

#### Changed
- `mobile/` is now `driver_app/` and `manager/` is now `manager_app/`; workflows and contract
  tests updated. **Existing habits that upload into `mobile/` or `manager/` must change.**
- `download` renamed to `.dockerignore`, so the Coolify build context really is the minimal one
  described in `docs/history/COOLIFY_DOCKER_CONTEXT_FIX_2026-11-14.md`. This is the only change
  that affects a deployed build; revert that single commit if the Coolify build misbehaves.
- The 34 patch notes and audits moved from the repository root to `docs/history/` (unchanged),
  and `DEPLOY_COOLIFY.md` moved to `docs/`.
- Driver README rewritten to describe the real file layout.

#### Removed
- Committed bytecode `backend/app/__pycache__/main.cpython-313.pyc`.
- Root `GeofenceMapPicker.tsx` (byte-identical to `web/src/GeofenceMapPicker.tsx`).
- Two empty placeholder files (`manager/assets/1`, `mobile/android_camera_activity/1`).

#### Known limits
- The new workflows were validated statically only and have not run on GitHub yet.
- Flutter builds still generate their platform projects in CI; no `flutter test` suite exists.
- `web/package-lock.json` is still not committed (CI uploads a generated one).
