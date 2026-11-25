# Changelog

All notable changes to Nuqati. Format follows [Keep a Changelog](https://keepachangelog.com/).
Notes written before this file existed are in [`docs/history/`](docs/history/README.md).

## [Unreleased]

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
