# Nuqati staging / Coolify

This is a RESTRICTED TEST build, not a commercial release. The API has no application-level authentication or tenant authorization. Do not enter real customer, driver, or location data. Do not remove the gateway basic authentication.

1. Create a PRIVATE GitHub repo and upload the extracted folder contents (not the ZIP itself). Do not commit any .env, passwords, or SSH keys.
2. Coolify > Nuqati > staging > New Resource > Private Repository (GitHub connection) > Docker Compose. Compose file: /compose.staging.yml; branch: main. If Coolify asks for a service domain, attach it to web (port 80), not API or DB. Do not publish ports 8000 or 5432.
3. Create a long random staging password. Generate a bcrypt hash locally using: docker run --rm caddy:2-alpine caddy hash-password --plaintext 'YOUR_UNIQUE_STAGING_PASSWORD' . Keep the plaintext out of your repo and command history where possible; the command is an illustrative method. Better: run interactively and avoid saving credentials in shell history. Paste the resulting hash into Coolify as STAGING_PASSWORD_HASH.
4. Set Coolify compose environment variables: STAGING_USER (e.g. nuqati-test), STAGING_PASSWORD_HASH, POSTGRES_USER (e.g. nuqati), POSTGRES_PASSWORD (random, avoid $ or URL-reserved characters unless URL-encoded), POSTGRES_DB (e.g. nuqati_staging), STAGING_ORIGIN (https://staging-nuqati.al-riadah.sa). Mark passwords sensitive. Do not put these values in git.
5. Add staging-nuqati.al-riadah.sa A record to VPS IP, only when ready; configure domain on web service and enable HTTPS. Existing root/www DNS records remain untouched. Keep the URL restricted with basic auth; ideally also IP allowlist or VPN.
6. Deploy. Visit https://staging-nuqati.al-riadah.sa/api/v1/health (basic-auth login required). Then visit dashboard and enter only fictitious test data.
7. Configure daily database backups and TEST a restore; monitor logs. Do not enable real drivers or commercial use.

Note: Existing backend uses Base.metadata.create_all, not managed Alembic migrations. Add migrations, application authentication, RBAC/tenant isolation, audit logging, retention and privacy compliance, tests and real mobile background GPS before production. PostgreSQL volume persistence is not itself a backup.
