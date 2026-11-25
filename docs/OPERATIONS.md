# Operations guide

How to tell that Nuqati is healthy, what to check and when, and what to do when something is not. Written for the person who runs the Coolify server. For security incidents use [compliance/INCIDENT_RESPONSE.md](compliance/INCIDENT_RESPONSE.md); for data recovery use [compliance/BACKUP_RESTORE.md](compliance/BACKUP_RESTORE.md).

## 1. The services

| Service (`compose.yml`) | What it does | Restarted if it crashes | Has a healthcheck |
|---|---|---|---|
| `web` | Serves the dashboard, forwards `/api/*` to the API | yes | no |
| `api` | The application. Creates missing tables at start | yes | **yes**: `GET /api/v1/ready` (needs the database) |
| `db` | PostgreSQL 16 | yes | **yes**: `pg_isready` |
| `db_backup` | One database dump a day into the `nuqati_backups` volume | yes | **yes**: red when the last good dump is older than 26 hours |
| `teltonika` | Receives positions from tracker hardware (port 5027) | yes | **yes**: its event loop writes a heartbeat every 15 s; unhealthy after 90 s without one |
| `report_scheduler` | Sends scheduled e-mail reports | yes | **yes**: one heartbeat per cycle (about every 30 s); unhealthy after 15 minutes without one |

"Restarted if it crashes" is Docker's `restart: unless-stopped`. It restarts a container that **stopped**; it does **not** restart one that is still running but stuck or marked unhealthy. A red healthcheck is a signal for a person (Coolify shows it), not an automatic repair.

**Worker heartbeats (since Phase 3.2).** `teltonika` and `report_scheduler` write a small file (`/tmp/nuqati-<name>.alive`) from the code that must keep running; the healthcheck runs `python -m app.heartbeat <name> <limit>` and fails when the file is older than the limit. A frozen receiver or a stuck scheduler therefore shows as **unhealthy** in Coolify instead of "running". The check proves the worker's loop is alive; it does not prove that trackers are sending data (a quiet night is normal) or that the database is reachable (that is `/api/v1/ready`). If a worker is unhealthy: `docker logs <container> --tail 100`, then restart that service in Coolify.

**Letting a stuck worker restart itself (optional, off by default).** Set `NUQATI_WORKER_WATCHDOG_SECONDS` in Coolify, for example `600` (minimum 120). A small thread inside each worker then ends the process, with exit code 70 and a `CRITICAL ... ending the process` line in the log, when its heartbeat is that old, and `restart: unless-stopped` starts a fresh one. Leave it off until you have watched the heartbeats for a while; a watchdog set too low would restart a healthy worker. A restarted receiver drops its open tracker connections; the devices reconnect and resend what they had not yet delivered.

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
| Vehicles with trackers all offline | Is `teltonika` unhealthy in Coolify? `docker logs <teltonika-container>` | Unhealthy: the receiver is stuck, restart it. Healthy but silent: firewall, `TELTONIKA_ALLOWED_CIDRS`, SIM or APN problem |
| Scheduled reports missing | Is `report_scheduler` unhealthy? `docker logs <report_scheduler-container>` | Unhealthy: stuck worker, restart it. Healthy: mail server settings (`last_error` of the report subscription) |
| Disk nearly full | `docker system df`, section 4 | Old images and build cache: `docker image prune`. Do **not** run `docker volume prune` |

If personal data may have been exposed, switch to [compliance/INCIDENT_RESPONSE.md](compliance/INCIDENT_RESPONSE.md): the 72-hour clock starts when you become aware.

## 6. Not covered yet

- The worker checks show that a worker is alive, not that data is flowing. An alert for "no position from any tracker for N hours" would need a rule that knows what normal looks like for your fleet.
- No metrics, dashboards or automatic alerts from inside the system. The uptime monitor and Coolify notifications above are the alarms.
- Off-server backup copies are manual ([BACKUP_RESTORE.md](compliance/BACKUP_RESTORE.md) 2b).
- Database schema changes are still made by SQL at API start, without versioned migrations (planned: Alembic).
