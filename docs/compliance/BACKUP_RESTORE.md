# Backup and restore runbook

What to back up, how, how often, and — more important — how to prove you can restore it.

> **A backup nobody has restored is only a hope.** No restore drill has been recorded yet. Do the first drill (section 4) before relying on anything below, and write the result in the log (section 6).

## 1. What must be backed up

| What | Where it lives | Why | How |
|---|---|---|---|
| **PostgreSQL database** | Docker volume used by the `db` service. The volume name is historical (`nuqati_staging_pgdata`, or the value of `NUQATI_PG_VOLUME_NAME`); do not rename it, a new name creates an **empty** database | All business data, audit trails and handover **photographs** (stored in the database) | `pg_dump -Fc` (section 2), copied off the server |
| **Secrets and settings** | Coolify environment variables of the resource (`NUQATI_AUTH_SECRET`, `POSTGRES_*`, SMTP, WhatsApp, `VITE_MAPTILER_API_KEY`, `NUQATI_PUBLIC_ORIGIN`) | A restored database is useless without the same settings; losing `NUQATI_AUTH_SECRET` only signs everyone out, losing the DB password locks you out of the database | Keep an encrypted copy in a password manager. **Never** put them in the Git repository |
| **Code** | GitHub repository | The application | Already versioned; protect the account with two-factor sign-in |
| **Android signing keys** | GitHub secrets `DRIVER_KEYSTORE_BASE64`, `MANAGER_KEYSTORE_BASE64` and their passwords | Without the key you can no longer publish updates to the same app | Keep an encrypted copy of each keystore and its passwords outside GitHub |
| **Server configuration** | Coolify, DNS | Rebuild after a server loss | Note the domain, DNS records and Coolify settings in the owner's records |

## 2. Routine backup

Proposed (to be confirmed): **daily**, kept **30 days**, **one copy off the server**, **encrypted**. Recovery point objective: at most 24 hours of data lost. Recovery time objective: 4 hours.

On the server (the `db` container name is shown in Coolify; list it with `docker ps`):

```bash
# 1. dump (custom format, compressed). Run as the user that has Docker access.
docker exec -t <db-container> pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > nuqati-$(date -u +%Y%m%dT%H%M%SZ).dump

# 2. encrypt before it leaves the server (example with age; any tool you trust works)
age -r <public-key> -o nuqati-<stamp>.dump.age nuqati-<stamp>.dump && shred -u nuqati-<stamp>.dump

# 3. copy to storage on a different provider or location, then delete dumps older than 30 days
```

Schedule it with the host's cron or a Coolify scheduled task, and have it e-mail you on failure. A dump that is suddenly much smaller than yesterday's is a warning sign: check the size in the log.

Why encrypt: the dump contains driver names, ID numbers, precise locations and photographs. An unencrypted copy on another service is a data breach waiting to happen ([INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)).

Photographs live in the database, so backup size grows with every handover. If dumps become too large, the retention job for handover photos ([RETENTION_SCHEDULE.md](RETENTION_SCHEDULE.md), R5) is the main lever.

## 3. Restoring

Use this for a real recovery. For practice, use section 4 instead.

1. Decide **what to restore from**: the newest dump taken before the damage.
2. Stop the application so nothing writes during the restore: in Coolify, stop the `api` (and `teltonika`, `report_scheduler`) services; leave `db` running.
3. Copy the dump to the server and decrypt it.
4. Restore into an **empty** database. For an empty replacement database:
   ```bash
   docker exec -i <db-container> pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --exit-on-error < nuqati-<stamp>.dump
   ```
   To overwrite a damaged but non-empty database add `--clean --if-exists`, **after** taking a dump of the current state, however damaged.
5. Start `api`. The application adds any missing tables or columns by itself at start-up (`CREATE TABLE IF NOT EXISTS` / `ADD COLUMN IF NOT EXISTS`), so a dump taken from an older version is brought up to date when the API starts.
6. Check: `GET /api/v1/ready` answers, dashboard login works, a company's vehicles and last trips are present, the newest `security_audit` row is from the expected time.
7. Start the other services; tell users what period of data was lost (anything after the dump).
8. Write the incident log. If the cause was an attack, follow [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) before bringing the system back online.

If the **volume was lost** and a new one was created empty, do not run the API against it for long: it will start normally and look like a fresh install. Restore first.

## 4. Restore drill (do the first one now, then every 6 months)

Do this on a **separate machine or a throwaway container, never on production**.

1. Pick the newest dump from the off-server storage (this also proves the copy works).
2. Start a disposable PostgreSQL 16:
   ```bash
   docker run -d --name nuqati-restore-test -e POSTGRES_PASSWORD=drill -e POSTGRES_DB=nuqati_drill -p 127.0.0.1:55432:5432 postgres:16-alpine
   ```
3. Restore: `docker exec -i nuqati-restore-test pg_restore -U postgres -d nuqati_drill --no-owner < nuqati-<stamp>.dump`
4. Compare against production, read-only: row counts of `companies`, `users`, `drivers`, `vehicles`, `trips`, `handover_photos`, and the newest timestamp in `driver_locations` and `security_audit`.
5. Optional but valuable: start the API against the drill database (`DATABASE_URL=postgresql+psycopg2://postgres:drill@127.0.0.1:55432/nuqati_drill`) and sign in.
6. Record the result (section 6): date, which dump, how long it took, what you compared, problems found.
7. Remove the container: `docker rm -f nuqati-restore-test`. It holds real personal data until you do.

A drill restored copy is also where to test any risky change to personal data before running it in production (for example the anonymisation steps in [DATA_SUBJECT_REQUESTS.md](DATA_SUBJECT_REQUESTS.md)).

## 5. Permanent company deletion needs a backup reference

The permanent-delete function refuses to run unless the caller types the exact value of the environment variable `NUQATI_VERIFIED_BACKUP_REFERENCE` (see `docs/history/PHASE7_SAFE_COMPANY_DELETION.md`). Set it to the identifier of a **restore-tested** dump taken just before the deletion. Observation: `compose.yml` does not pass this variable to the `api` service, so unless it reaches the container another way the function answers "A verified backup reference must be configured". If you need the function, add `NUQATI_VERIFIED_BACKUP_REFERENCE: ${NUQATI_VERIFIED_BACKUP_REFERENCE:-}` under the `api` environment, set the value in Coolify, and remove it again afterwards. (Not changed in this release: it enables a destructive action and should be a deliberate decision.)

## 6. Backup and drill log (copy for each entry)

| Date (UTC) | Type (routine / drill / restore) | Dump name and size | Stored where | Restored and checked by | Duration | Result / problems |
|---|---|---|---|---|---|---|
| | | | | | | |

## 7. Open items

1. Set up the daily encrypted off-server backup and its failure alert.
2. Do the first restore drill and record it.
3. Confirm the 30-day backup retention and the objectives (24 h / 4 h).
4. Decide about `NUQATI_VERIFIED_BACKUP_REFERENCE` (section 5).
5. Store an encrypted copy of both Android keystores outside GitHub, if not already done.
