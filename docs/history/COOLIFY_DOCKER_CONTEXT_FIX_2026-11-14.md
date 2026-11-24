# Nuqati Coolify build-context correction — 14 November 2026

## Failure confirmed in uploaded deployment log

Coolify pulled commit `07c29836d7348d1d56153f2da49fc3e2e00d9211` from `Riadah-Workshop/nuqati`, then Docker BuildKit failed on `report_scheduler` at `COPY requirements.txt .`, reporting `"/requirements.txt": not found`. The error happened during build; the log does not identify any database or Android runtime failure.

The previous full Nuqati project archive **does contain** `backend/requirements.txt`. We could not confirm that this file was present in the *actual GitHub commit* deployed by Coolify. A missing Git-tracked file would produce the same error.

## Fix in this archive

- `compose.yml`: `api`, `teltonika` and `report_scheduler` each use the same explicit repository-root build context and `backend/Dockerfile`.
- `backend/Dockerfile`: source paths are unambiguous (`COPY backend/requirements.txt` and `COPY backend/app`). Python version, dependencies, command and non-root user stay the same.
- `docker-compose.yml` and `hardware-teltonika.compose.yml`: keep local and optional hardware deployment consistent with that Dockerfile.
- `.dockerignore`: prevents Flutter, frontend, artifacts and unrelated files from bloating the backend image context. It explicitly includes the Python app and its requirements.
- `backend/requirements.txt`: included in the **patch-only** bundle even though its content is unchanged, in case GitHub is missing it.

No Python, Flutter, scoring, GPS receiver, dashboard, API, data model or database volume code was modified by this patch.

## GitHub/Coolify checks before redeployment

1. Confirm branch `main` has **both** `backend/Dockerfile` and `backend/requirements.txt`; if either is absent, commit it. In a clone, run:

   ```bash
   git ls-files backend/requirements.txt backend/Dockerfile
   git add compose.yml docker-compose.yml hardware-teltonika.compose.yml backend/Dockerfile backend/requirements.txt .dockerignore
   git commit -m "Fix backend Docker build context for Coolify" 
   git push origin main
   ```

2. Keep the existing Coolify application/resource and existing environment variables. Verify the Docker Compose file path is `/compose.yml` (as configured in the production resource).
3. Back up PostgreSQL and confirm `NUQATI_PG_VOLUME_NAME` points to the **current production database volume**. Do not delete or recreate the database or application resource.
4. Redeploy the new GitHub commit. Check that the image-build stages for `api`, `teltonika` and `report_scheduler` complete, and then inspect startup logs for any separate errors.

## Local build verification

From repo root with Docker Compose installed and Coolify variables defined:

```bash
docker compose -f compose.yml config --quiet
docker compose -f compose.yml build api teltonika report_scheduler
```

A full Docker/Coolify build was **not** executed in the patching environment (Docker CLI/daemon unavailable). This change corrects path/context consistency and includes the missing file, but a new Coolify log is required to confirm end-to-end deployment.
