# Nuqati production deployment — nuqati.al-riadah.sa

## Before changing the live domain

1. Back up PostgreSQL with `pg_dump -Fc` and validate that the backup can be restored. Preserve your current Coolify resource, secrets, persistent volumes, and database. Do **not** delete/re-create the application or database resource.
2. In Hostinger DNS, create/update an **A** record for `nuqati` pointing to your VPS public IPv4 (and an **AAAA** record only if IPv6 is configured and reachable). Keep the other `al-riadah.sa` records unchanged. DNS changes may take time.
3. In the **existing** Coolify Docker Compose resource, change the compose file path from `/compose.staging.yml` to `/compose.yml`. Use the same Git branch, service identities, Docker Compose project, and persistent PostgreSQL volume. If Coolify proposes recreating the database under a new name, stop and verify its volume mapping before deploying.
4. Set `NUQATI_PUBLIC_ORIGIN=https://nuqati.al-riadah.sa`. Remove the old `STAGING_ORIGIN`, `STAGING_USER`, and `STAGING_PASSWORD_HASH` values after confirming they are no longer needed. Keep all other credentials, SMTP, WhatsApp, MapTiler, and signing secrets unchanged. For CORS, the Compose file uses `NUQATI_PUBLIC_ORIGIN`.
5. Attach **only** `https://nuqati.al-riadah.sa` to Coolify's `web` service (internal port 80). Enable HTTPS and wait for a valid TLS certificate. The API runs behind the same origin at `/api/*`; do not publish database or private API container ports to the Internet. The current Caddyfile has no staging Basic Auth.
6. Redeploy the existing stack, then verify `https://nuqati.al-riadah.sa/api/v1/health`, dashboard login, fleet/trip history, live tracking, email invitations, WhatsApp verification, maps and the privacy policy endpoint. Confirm existing data survived.
7. In GitHub Actions repository **Variables**, set `NUQATI_PRODUCTION_API=https://nuqati.al-riadah.sa` for the signed Driver AAB workflow. Rebuild and roll out a new **Driver** AAB and a new signed **Manager** AAB. Already-installed mobile apps embed the previous URL and do not update when DNS changes.
8. In Meta's WhatsApp Developer configuration, set the callback to `https://nuqati.al-riadah.sa/api/v1/whatsapp/webhook` and use the existing verification token. Update any external webhook, app listing, privacy-policy, or integration links that point to the old host.
9. Only after both mobile app updates are installed and all integrations are checked should you remove the old staging-domain DNS record and Coolify domain binding. Otherwise, old app versions will stop synchronizing. Optionally use a temporary HTTPS redirect/reverse proxy on the old hostname during migration.

**Data safety:** This production file deliberately retains the historical Docker volume key `nuqati_staging_pgdata`; changing that key can cause Compose to create an empty volume. It is an internal volume identifier, not a public staging endpoint. Production permanent company deletion always requires a verified off-server backup reference.

## Backups and monitoring (since Phase 3.1)

- `compose.yml` now also runs `db_backup`: one database dump a day into the volume `nuqati_backups` (kept 14 days). It needs
  no extra settings in Coolify (an encrypted copy to Google Drive is available but **off** until you set `NUQATI_OFFSITE`: [BACKUP_RESTORE.md](compliance/BACKUP_RESTORE.md) 2b); `NUQATI_BACKUP_HOUR_UTC` and `NUQATI_BACKUP_KEEP_DAYS` are optional. The first deployment
  builds one more small image and creates the volume.
- The dumps are on the same server. Copy them off the server and run a restore drill: [compliance/BACKUP_RESTORE.md](compliance/BACKUP_RESTORE.md).
- Add an external uptime monitor on `https://nuqati.al-riadah.sa/api/v1/ready` and read [OPERATIONS.md](OPERATIONS.md).

## Database migrations (Phase 3.3 and 3.4)

Since Phase 3.4 the `api` container applies pending migrations before it starts, and the application no longer creates tables itself. Nothing is needed in Coolify.

**The first deployment of Phase 3.4 on the existing database**, once:

1. Check that a recent backup exists (Coolify: `db_backup` healthy; `docker exec <db_backup-container> ls -l /backups`), or take one: `docker exec <db_backup-container> /usr/local/bin/backup.sh once`.
2. **Before** merging Phase 3.4, set `NUQATI_RUN_MIGRATIONS=1` in Coolify on the Phase 3.3 version and redeploy. The `api` log must show `Existing database adopted: recorded as revision 0001; nothing was changed.` followed by `Uvicorn running`. That proves the real database matches the baseline while the old safety net (the application creating missing tables by itself) is still there.
3. Merge Phase 3.4 and redeploy. Later starts print nothing about migrations until a new revision exists.
4. If the log says `NOT adopting this database` with a list, nothing was changed: see [OPERATIONS.md](OPERATIONS.md) section 5 (deploy commit `56c09fe` once).

`NUQATI_RUN_MIGRATIONS=0` skips the migration step (only for a database you manage by hand). The extra `alembic_version` table is harmless.
