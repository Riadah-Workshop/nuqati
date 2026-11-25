# Changelog

All notable changes to Nuqati. Format follows [Keep a Changelog](https://keepachangelog.com/).
Notes written before this file existed are in [`docs/history/`](docs/history/README.md).

## [Unreleased]

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
