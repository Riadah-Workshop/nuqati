# Changelog

All notable changes to Nuqati. Format follows [Keep a Changelog](https://keepachangelog.com/).
Notes written before this file existed are in [`docs/history/`](docs/history/README.md).

## [Unreleased]

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
