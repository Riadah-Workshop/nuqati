# Nuqati Phase 2 — access-controlled staging pilot

Based on uploaded GitHub commit `989bad0`. Preserves existing DB tables and persistent volume. Adds `users` table with SQLAlchemy `create_all`; existing table schema is unchanged. Logo used as provided.

## Before deploying
1. **Backup staging PostgreSQL and test restore**. Never delete volume.
2. In Coolify staging environment add `NUQATI_AUTH_SECRET` as a stable random string of 32+ characters. Generate locally with `python -c "import secrets;print(secrets.token_urlsafe(48))"`; do not put it in Git. Changing it logs everyone out.
3. Upload updated source files to existing GitHub repository (preserve `.git` if using git clone), commit and redeploy `compose.yml` in Coolify. Check logs. The API deliberately refuses to start without the secret.
4. In the **api container** Coolify Terminal, run `python -m app.bootstrap_admin` and enter a unique super admin email, name, and 12+ character password interactively. Do not send credentials to ChatGPT. Do this once only.
5. Open staging site; Caddy basic-auth gate remains in front of the app; then use Nuqati login. Create client company, then company admin user, then sign in with company account and verify other-company data is not accessible even by direct API request.

## Included
- PBKDF2 password hashing; signed expiring 8-hour bearer tokens; disabled-user checks.
- Super-admin-only company creation/edit and delete-if-empty endpoint; company-scoped list and create operations.
- Super admin creates users; company admins may create fleet managers, representatives and drivers within their own company; deactivate controls.
- Branded dark dashboard/login using provided Solutions logo; companies and user access screens.

## Pilot limitations — DO NOT invite real customers yet
- No password reset, invitation/verification flow, rate limiting, audit trail, MFA, token revocation, role-specific driver endpoints, or database migration framework.
- Workshop staff role currently sees only its assigned company (not multiple companies). Driver role is not yet given a driver-specific app API.
- No real-time GPS map, background location, trip scoring or Google Play release; no fake live metrics displayed as real data.
- Browser session token is in sessionStorage (cleared on tab close); use HTTPS and do not expose admin via HTTP.
- Existing data remains in database. Take backups before applying. This is a staging pilot, not a production security certification.
