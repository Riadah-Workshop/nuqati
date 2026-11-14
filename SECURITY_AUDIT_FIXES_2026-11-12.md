# Nuqati security audit hardening — 12 November 2026

Source: `nuqati-main(20261112-075855).zip`. This patch is additive/targeted; no mobile, manager, trip detection, native GPS, scoring, notifications or handover code was removed.

## Applied

1. **Authentication throttle**: database-backed rate limiting on dashboard login, phone/Iqama login, password reset request/confirm, and email-change confirmation. Buckets: IP (60/min), identifier (40/5min), and IP+identifier (10/2min). Each bucket temporarily blocks further attempts on excess, returning HTTP 429 and Retry-After. Identifiers are stored only as HMAC digests. Nonexistent account login runs a dummy 600,000-round PBKDF2 verification.
2. **Authorization**: restrict `/companies`, `/drivers`, `/vehicles`, `/odometer-readings`, `/maintenance-schedules` to dashboard/fleet roles. Drivers retain their existing, assigned-driver mobile endpoints.
3. **Tracker**: move all blocking database work into bounded threads. Deployments bind TCP 5027 to loopback by default. For a public bind, `TELTONIKA_ALLOWED_CIDRS` must be set; the server rejects unknown networks. This is transport/network hardening, *not* device cryptographic authentication: Codec 8/8E authenticates only by IMEI.
4. **Driver login**: phone matching now happens in a SQL query rather than downloading all drivers. Phone/Iqama shared by multiple companies is handled using the matching password; optional `company_id` disambiguates if passwords also match. Onboarding rejects a repeated Iqama within the same company.
5. **Deployment**: local compose starts PostgreSQL 16 and injects a local-only authentication secret; production volume defaults to the existing staging volume name but is no longer `external: true`, and supports `NUQATI_PG_VOLUME_NAME` override. Backend image runs as a non-root user.
6. **Fleet lists**: query parameters `limit` (1–500) and `offset` were added to drivers, vehicles, odometer readings, with `X-Total-Count`. Dashboard now fetches successive pages, including filtered odometer history.
7. **Maintenance**: GET is read-only and batch-loads vehicles rather than one DB request per schedule; legacy tyre schedules are backfilled on application startup.
8. **Company admin**: existing role-aware but unreachable create/deactivate-user branches are now reachable for company admins, scoped to their own company, and cannot manage elevated users.
9. **HTTP headers**: HSTS, nosniff, frame protection, limited CSP, referrer and permissions policies. CSP allows current embedded Leaflet maps, so `unsafe-inline` remains (see remaining work).
10. **Build/tests**: versions are pinned in `web/package.json` (no `latest` dependencies), optional `npm ci` on a committed lockfile; backend test dependency file added; runnable security unit tests and PostgreSQL API integration tests added.

## Before deploying to Coolify

- **Back up PostgreSQL** and verify restore on a disposable database. Preserve `NUQATI_PG_VOLUME_NAME` to point to the actual production volume. The provided default is the former staging volume `hskj899cs3voe1lk5gkyyxb8_nuqati-staging-pgdata`. Do not replace it with an empty volume on an existing installation.
- Keep the **same** `NUQATI_AUTH_SECRET` used in the current deployment; changing it invalidates every current session.
- Configure `NUQATI_TRUSTED_PROXIES` to the actual *trusted reverse proxy* source IP/CIDR if Caddy/other proxy passes `X-Forwarded-For`; otherwise the IP bucket can treat all proxied clients as one IP. Never trust arbitrary internet IPs as proxies. The default trusts loopback only.
- TCP tracker: `TELTONIKA_BIND_HOST` defaults to `127.0.0.1`. **If physical remote trackers connect directly to port 5027, they will no longer connect until you explicitly set a secure ingress**. Prefer VPN/private APN. For public-bound deployments explicitly configure `TELTONIKA_BIND_HOST=0.0.0.0`, `TELTONIKA_ALLOWED_CIDRS=<trusted IP/CIDR(s)>`, and firewall rules limiting source IP. Ensure actual cellular carrier source IPs are predictable; otherwise use private APN/VPN. A person within the allowlisted network who knows the IMEI can still spoof points; genuine per-device cryptographic identity requires supported tracker firmware or a secure gateway.
- `NUQATI_TRUSTED_PROXIES`, `TELTONIKA_ALLOWED_CIDRS` and `NUQATI_PG_VOLUME_NAME` are **deployment configuration** values, not credentials for the driver app.
- On shared/public development machines, override all default local-only development credentials in `docker-compose.yml`.

## Test

Basic unit and pre-existing contract checks (run without PostgreSQL):

```bash
cd nuqati-main
python -m pip install -r backend/requirements-test.txt
PYTHONPATH=backend DATABASE_URL=sqlite:////tmp/nuqati_security_units.db \
  python -m pytest -q backend/test_security_runtime_units.py \
  backend/test_vehicle_handover.py backend/test_handover_integration_contract.py \
  backend/test_native_tracking_regression_contract.py backend/test_safety_counts_trip_number_contract.py
```

Actual API integration tests, **only with a dedicated PostgreSQL test database** whose name contains `test`:

```bash
NUQATI_TEST_DATABASE_URL=postgresql+psycopg2://TEST_USER:TEST_PASSWORD@localhost:5432/nuqati_test \
PYTHONPATH=backend python -m pytest -q backend/test_auth_runtime_postgres.py
```

Check build with internet access:

```bash
cd web
npm install --package-lock-only
npm ci
npm run build
# Commit web/package-lock.json to the repository so Docker always uses npm ci.
```

We could not create a valid npm lockfile or run an npm build without network access to the npm registry. The Dockerfile therefore uses `npm install` only until a valid lockfile exists, then automatically uses `npm ci`.

## Remaining work (not claimed fixed)

- True tracker identity verification (vendor TLS/certificate or trusted gateway), refresh-token single-use rotation, and stronger web token storage/CSP refactor.
- Formal versioned database migrations, full backend runtime tests on a live PostgreSQL server, production restore drill and end-to-end Android/manager acceptance tests.
- Hardware/network load tests, response/photo upload size caps, verified offsite backup proof for permanent company deletion, and supply-chain hardening (digest-pinned CI actions, security advisories, lockfile).
- Cleanup of root patch documents, duplicate source copy and stray files remains unmodified rather than risking accidental removal.
