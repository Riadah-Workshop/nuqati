# Development guide

How to run, test and change Nuqati. For what the system is, read [`ARCHITECTURE.md`](ARCHITECTURE.md) first.

## 1. Prerequisites

| Tool | Version | Needed for |
|---|---|---|
| Docker + Compose v2 | any recent | local PostgreSQL and API (`make up`) |
| Python | 3.12 (same as the Dockerfile) | running tests without Docker |
| Node.js | 22 (same as `web/Dockerfile`) | the web dashboard |
| Flutter | stable | only if you want to analyze the apps locally; CI does it otherwise |

## 2. Run it locally

```bash
make up         # PostgreSQL 16 + API on http://127.0.0.1:8000, interactive API docs at /docs
```

**Use `make up`, not a bare `docker compose up`.** The repository has two Compose files and
Compose prefers `compose.yml`, which is the **production** stack and aborts without production
variables. The local stack is `docker-compose.yml`; the Makefile names it explicitly.

Create the first super admin (interactive prompt, password of 12+ characters):

```bash
docker compose -f docker-compose.yml exec api python -m app.bootstrap_admin
```

Start the dashboard (the API allows `http://localhost:5173` and `http://127.0.0.1:5173` in local mode):

```bash
cd web && npm install && VITE_API_BASE_URL=http://127.0.0.1:8000 npm run dev
```

Set `VITE_MAPTILER_API_KEY` too if you want map tiles; without it the maps show a warning.
Local defaults (database credentials, a development-only auth secret) are in `docker-compose.yml`
and are not secrets. Never reuse them anywhere shared.

## 3. Tests

```bash
make install    # pip install -r backend/requirements-test.txt (use a virtualenv)
make test       # everything that needs no server, about a minute
make hygiene    # only the repository-layout checks, a second
make test-pg    # API integration tests against a throwaway PostgreSQL (below)
```

What the backend test files cover:

| File | Kind | What it protects |
|---|---|---|
| `test_repo_hygiene.py` | layout | no `mobile/` path, no root clutter, no committed bytecode / keystores / `.env` / private keys, Docker inputs exist, workflow paths exist |
| `test_handover_integration_contract.py`, `test_native_tracking_regression_contract.py`, `test_safety_counts_trip_number_contract.py`, `test_driver_vpn_queue_contract.py` | source contracts | assert that Kotlin, Dart, Python and workflows still agree on names and rules (sampling interval, cooldowns, trip numbering, failover rules) |
| `test_company_one_page_editor.py` | source contract | company editor saves in one request |
| `test_security_runtime_units.py`, `test_driver_device_session_units.py` | unit | role checks, auth throttling, driver token / device-lock validation |
| `test_vpn_connection_alerts.py` | unit | 60 s / 5 min / 15 min connectivity alert policy |
| `test_vehicle_handover.py` | API (SQLite) | handover receive / return, flags, authorization |
| `test_concept_reports.py` | API (in-memory SQLite) | report suite queries and Excel / CSV / PDF export |
| `test_auth_runtime_postgres.py` | API (PostgreSQL) | login, scoping, drivers, maintenance; imports `app.main`, so it proves the app boots on PostgreSQL |

**Source-contract tests compare strings in source files on purpose.** They are the only
automated link between the Dart / Kotlin code and the backend today. If you rename something
they pin, change the test in the same pull request and say why.

### PostgreSQL integration tests

```bash
docker run --rm -d --name nuqati-pg-test -p 5433:5432 \
  -e POSTGRES_USER=nuqati -e POSTGRES_PASSWORD=test-only -e POSTGRES_DB=nuqati_test postgres:16-alpine
export NUQATI_TEST_DATABASE_URL=postgresql+psycopg2://nuqati:test-only@localhost:5433/nuqati_test
make test-pg
docker stop nuqati-pg-test
```

The test refuses to run unless the URL is PostgreSQL and the database name contains `test`, so
it cannot touch real data. Never point it at production or staging.

## 4. Continuous integration

| Workflow | Runs on | Jobs |
|---|---|---|
| `ci.yml` | every pull request, pushes to `main` | **Backend tests**, **Web build**, **Docker, compose and Caddy**, **Lint (advisory)** |
| `ci-flutter.yml` | pull requests that touch `driver_app/` or `manager_app/` | **Driver app analyze**, **Manager app analyze** |
| `build-*.yml` | manual (and, for debug APKs, pushes to `main` that touch an app) | release and debug builds; unchanged by Phase 0 apart from folder names |

Notes:

- **First run.** `ci.yml` and `ci-flutter.yml` were validated statically but had not run on
  GitHub when they were added. If the first run is red, read the log: it is either a typo in a
  workflow or a real problem the old process never checked (for example a TypeScript error the
  production Docker build would also have hit). Fix forward in a small pull request.
- **Web lockfile.** `web/package-lock.json` is not committed, so CI uses `npm install` and
  uploads the generated lockfile as the artifact `web-package-lock`. Download it from the first
  green run and commit it; from then on CI and the Docker build use `npm ci`.
- **Lint is advisory.** Ruff runs with a minimal rule set (syntax errors, undefined names). To make
  it blocking, delete `continue-on-error: true` in the `lint` job once a run is clean.
- **Flutter checks are not "required".** Path-filtered workflows are skipped on other pull
  requests, and a skipped required check blocks merging.

## 5. Branches, reviews, releases

Rules are in [`../CONTRIBUTING.md`](../CONTRIBUTING.md). Settings to apply once in GitHub
(Settings → Branches → add rule for `main`):

- Require a pull request before merging, with at least 1 approval
- Require status checks: **Backend tests**, **Web build**, **Docker, compose and Caddy**
- Do not allow force pushes or deletion of `main`
- Do not allow bypassing the rule (including administrators), except for a documented hotfix

Apply them after the first green CI run, because a status check can only be selected once it has
reported at least once.

Mobile releases: run the signed-build workflows manually. Backend and web must be deployed from
the **same commit**; installed phones keep the API URL they were built with.

## 6. Changing the database

There is no migration tool yet (Phase 1). Until there is:

- Changes must be additive and idempotent: `CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`
  (see existing blocks in `main.py`). Never drop or rename a column that production data uses.
- Test on PostgreSQL (`make test-pg`); SQLite does not understand all of the SQL.
- Back up first (`pg_dump -Fc`) and keep the same `NUQATI_PG_VOLUME_NAME` as the running stack.
  The default volume name is the historical staging name on purpose, because pointing Compose at
  a new name creates an empty database. See [`DEPLOY_COOLIFY.md`](DEPLOY_COOLIFY.md).

## 7. Mobile apps

The apps are built by CI from source files; see `driver_app/README.md` and
`manager_app/README.md` for the file map, the build-time settings and the secrets each workflow
needs. To work on them locally, generate a project the way CI does:

```bash
cd driver_app
flutter create --platforms=android --project-name nuqati_driver .
mkdir -p lib && cp main.dart nuqati_network.dart vehicle_handover.dart nuqati_home_test.dart lib/
flutter pub get && flutter analyze --no-pub --no-fatal-infos --no-fatal-warnings lib/main.dart
```

Do not commit the generated `android/`, `ios/` and `lib/` folders from that run (and do not
rename the Kotlin package or `applicationId`) until the Phase 1 task below is done deliberately.

## 8. What Phase 0 did *not* do

Phase 0 is hygiene and a safety net. It deliberately did not touch application behaviour, so
these remain open and are the content of Phase 1 and later:

| Next | Why it is not in Phase 0 |
|---|---|
| Commit real Flutter projects with proper app IDs | Needs the Flutter SDK and device tests; changing `applicationId` or the Kotlin package affects installed apps |
| Split `main.py` into routers, `App.tsx` into pages, `main.dart` into files | Large, behaviour-sensitive refactors that should be reviewed on top of this safety net |
| Alembic migrations instead of import-time DDL | Needs a plan for the existing production schema |
| Run formatters once (Ruff / Black, Prettier, `dart format`) in a single commit, then add its hash to a `.git-blame-ignore-revs` file | Would rewrite lines of 300+ characters and bury real changes; do it alone |
| Make Ruff blocking; add ESLint / Prettier for `web/`; add real Dart tests (`flutter test`) | Needs the formatting commit and new dev dependencies (and a lockfile) first |
| Commit `web/package-lock.json` | Generated by the first CI run (see section 4) |
| Retention job, structured logging, a health check that tests the database | Behaviour changes with their own review |
