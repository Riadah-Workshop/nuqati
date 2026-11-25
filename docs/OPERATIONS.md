# Operations guide

How to tell that Nuqati is healthy, what to check and when, and what to do when something is not. Written for the person who runs the Coolify server. For security incidents use [compliance/INCIDENT_RESPONSE.md](compliance/INCIDENT_RESPONSE.md); for data recovery use [compliance/BACKUP_RESTORE.md](compliance/BACKUP_RESTORE.md).

## 1. The services

| Service (`compose.yml`) | What it does | Restarted if it crashes | Has a healthcheck |
|---|---|---|---|
| `web` | Serves the dashboard, forwards `/api/*` to the API | yes | no |
| `api` | The application. Creates missing tables at start | yes | **yes**: `GET /api/v1/ready` (needs the database) |
| `db` | PostgreSQL 16 | yes | **yes**: `pg_isready` |
| `db_backup` | One database dump a day into the `nuqati_backups` volume | yes | **yes**: red when the last good dump is older than 26 hours |
| `teltonika` | Receives positions from tracker hardware (port 5027) | yes | no |
| `report_scheduler` | Sends scheduled e-mail reports | yes | no |

"Restarted if it crashes" is Docker's `restart: unless-stopped`. It restarts a container that **stopped**; it does **not** restart one that is still running but stuck or marked unhealthy. A red healthcheck is a signal for a person (Coolify shows it), not an automatic repair.

`teltonika` and `report_scheduler` have no healthcheck yet, so a stuck worker looks "running". Signs: vehicles with tracker hardware all go offline at once; scheduled reports stop arriving. Check `docker logs <container> --tail 100`, then restart that service in Coolify.

## 2. Health signals you can read from outside

| URL | Meaning | Answers |
|---|---|---|
| `https://<your-domain>/api/v1/health` | The API process is up. Does not touch the database | `200 {"status":"ok",...}` |
| `https://<your-domain>/api/v1/ready` | The API **and** the database answer | `200 {"status":"ready"}`, or `503` if the database does not answer (the API gives up connecting after 5 seconds) |

Neither shows any data. **Point an external uptime monitor at `/api/v1/ready`** (any service that checks a URL every 1 to 5 minutes and e-mails or messages you; most have a free tier). Alert on anything other than `200`. This is the one alarm that still works when the whole server is down, which nothing running on the server can tell you.

Also in Coolify: enable its notifications (e-mail, Telegram or similar, where your version offers them) for failed deployments and stopped or unhealthy containers.

## 3. What to check, and when

| When | What | How |
|---|---|---|
| Every working day (1 minute) | Dashboard opens, map shows recent positions | Browser |
| Weekly | All services healthy in Coolify, including `db_backup` | Coolify |
| Weekly | The latest backups exist and are not shrinking | `docker exec <db_backup-container> ls -l /backups`. A `WARNING ... less than half the size` in `docker logs <db_backup-container>` means a dump was much smaller than the one before |
| Weekly | Disk space | `df -h` on the server (see section 4) |
| Weekly | Failed sign-ins and other unusual security events | Dashboard API `GET /api/v1/security-audit?outcome=failed` as a super admin |
| After every merge to `main` | Coolify finished, `/api/v1/ready` answers, you can sign in | |
| Monthly | The latest **Security checks** run (Actions tab): new findings, Dependabot pull requests | GitHub |
| Every 6 months | A **restore drill** and an entry in the drill log | [BACKUP_RESTORE.md](compliance/BACKUP_RESTORE.md) section 4 |

## 4. Disk space: what grows

| What | Where | Growth | Limit |
|---|---|---|---|
| Database | volume of the `db` service | Locations, trips, events and handover photos grow with every vehicle and every day | None until the retention job exists ([compliance/RETENTION_SCHEDULE.md](compliance/RETENTION_SCHEDULE.md)) |
| Backups | volume `nuqati_backups` | About 14 dumps (one per day), each roughly the size of the compressed database | 14 days (`NUQATI_BACKUP_KEEP_DAYS`) |
| Container logs | Docker's log files | Capped | 5 files of 10 MB per container |

Database size and the biggest tables:

```bash
docker exec <db-container> psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT pg_size_pretty(pg_database_size(current_database()))"
docker exec <db-container> psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "SELECT relname, pg_size_pretty(pg_total_relation_size(oid)) FROM pg_class WHERE relkind='r' AND relnamespace='public'::regnamespace ORDER BY pg_total_relation_size(oid) DESC LIMIT 10"
```

Plan for the disk to hold the database **plus room for about 15 dumps** (14 days plus the one being written). If the disk is more than 70 percent full, act before it reaches 90.

## 5. When something is wrong

| Symptom | First look | Usual cause and action |
|---|---|---|
| Dashboard shows an error page | Coolify: is `web` running? `docker logs <web>` | Restart `web`; if the build just changed, check the deployment log |
| Sign-in fails for everyone, `/api/v1/ready` answers `503` | `docker ps`, `docker logs <db-container>` | Database stopped or out of disk. Free disk space, start `db`. Do not delete the database volume |
| `/api/v1/ready` is `200` but the app misbehaves | `docker logs <api-container> --tail 200` | An error in the API; copy the last lines to the developer |
| Coolify says "api unhealthy" after a deployment | Deployment log, then `docker logs <api-container>` | A missing file or bad import in the new version (this happened once, in the Phase 1 incident): redeploy the previous commit |
| `db_backup` unhealthy | `docker logs <db_backup-container> --tail 50` | `ERROR pg_dump failed`: the database is down or the password changed. Fix it, then `docker exec <db_backup-container> /usr/local/bin/backup.sh once` |
| Vehicles with trackers all offline | `docker logs <teltonika-container>` | Receiver stuck or blocked by the firewall; restart it. Check `TELTONIKA_ALLOWED_CIDRS` |
| Scheduled reports missing | `docker logs <report_scheduler-container>` | Mail server settings or a stuck worker; restart it |
| Disk nearly full | `docker system df`, section 4 | Old images and build cache: `docker image prune`. Do **not** run `docker volume prune` |

If personal data may have been exposed, switch to [compliance/INCIDENT_RESPONSE.md](compliance/INCIDENT_RESPONSE.md): the 72-hour clock starts when you become aware.

## 6. Not covered yet

- No healthcheck for `teltonika` and `report_scheduler` (section 1). Adding one needs a small change inside each worker, so it is planned separately.
- No metrics, dashboards or automatic alerts from inside the system. The uptime monitor and Coolify notifications above are the alarms.
- Off-server backup copies are manual ([BACKUP_RESTORE.md](compliance/BACKUP_RESTORE.md) 2b).
- Database schema changes are still made by SQL at API start, without versioned migrations (planned: Alembic).
