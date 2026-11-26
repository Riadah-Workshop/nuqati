# Backup and restore runbook

What to back up, how, how often, and — more important — how to prove you can restore it.

> **A backup nobody has restored is only a hope.** No restore drill has been recorded yet. Do the first drill (section 4, one command) before relying on anything below, and write the result in the log (section 6).
>
> **Since Phase 3.1** the `db_backup` service takes a dump every day by itself (section 2a). It keeps the dumps **on the same server**. **Since Phase 4.2** it can also copy each dump, encrypted, to Google Drive (section 2b); that stays **off until you set it up**, so until then the dumps still live on the same machine as the database.

## 1. What must be backed up

| What | Where it lives | Why | How |
|---|---|---|---|
| **PostgreSQL database** | Docker volume used by the `db` service. The volume name is historical (`nuqati_staging_pgdata`, or the value of `NUQATI_PG_VOLUME_NAME`); do not rename it, a new name creates an **empty** database | All business data, audit trails and handover **photographs** (stored in the database) | Daily `pg_dump -Fc` by the `db_backup` service (section 2a), plus a copy off the server (section 2b) |
| **Secrets and settings** | Coolify environment variables of the resource (`NUQATI_AUTH_SECRET`, `NUQATI_MFA_KEY` (without it a restored database cannot check authenticator codes), `POSTGRES_*`, SMTP, WhatsApp, `VITE_MAPTILER_API_KEY`, `NUQATI_PUBLIC_ORIGIN`) | A restored database is useless without the same settings; losing `NUQATI_AUTH_SECRET` only signs everyone out, losing the DB password locks you out of the database | Keep an encrypted copy in a password manager. **Never** put them in the Git repository |
| **Code** | GitHub repository | The application | Already versioned; protect the account with two-factor sign-in |
| **Android signing keys** | GitHub secrets `DRIVER_KEYSTORE_BASE64`, `MANAGER_KEYSTORE_BASE64` and their passwords | Without the key you can no longer publish updates to the same app | Keep an encrypted copy of each keystore and its passwords outside GitHub |
| **Server configuration** | Coolify, DNS | Rebuild after a server loss | Note the domain, DNS records and Coolify settings in the owner's records |

## 2. Routine backup

Proposed (to be confirmed): **daily**, **one copy off the server**, **encrypted**. Recovery point objective: at most 24 hours of data lost. Recovery time objective: 4 hours.

### 2a. On the server: automatic (the `db_backup` service)

`compose.yml` runs a small container, `db_backup` (code in `ops/backup/`), next to the database:

- At start, and then once a day at **23:00 UTC (02:00 in Riyadh)**, it writes `nuqati-<UTC time>.dump` (PostgreSQL custom format, compressed) into the Docker volume `nuqati_backups`, mounted at `/backups`.
- A dump counts only after `pg_restore --list` has read it back. It is written under a temporary name and renamed at the end, so a half-written file is never mistaken for a backup. A failed attempt is logged as `ERROR` and retried every hour; the previous good dump is never touched.
- Dumps older than **14 days** are deleted; the newest 3 are always kept. Change with `NUQATI_BACKUP_KEEP_DAYS` and `NUQATI_BACKUP_HOUR_UTC` in Coolify.
- The container's health status in Coolify turns **unhealthy** when the last successful backup is more than 26 hours old, so a silent failure becomes visible within a day. It also logs a `WARNING` when a dump is less than half the size of the previous one.
- Read what it did: `docker logs <db_backup-container> --tail 50`. List the dumps: `docker exec <db_backup-container> ls -l /backups`.

This protects against deleted or corrupted data and failed upgrades. It does **not** protect against losing the server or the disk: the dumps live on the same machine. That is what 2b is for.

### 2b. Off the server: encrypted copy to Google Drive (automatic once switched on)

The `db_backup` service can copy every new dump to Google Drive, **encrypted on the server first** with rclone's `crypt` layer (NaCl secretbox: XSalsa20 + Poly1305; the key is derived from two passphrases with scrypt). Drive only ever holds files it cannot read. The names of the files stay readable (`nuqati-<UTC time>.dump.bin`, only a timestamp) so you can manage the folder by hand; the contents do not.

What it does, in this order, after each good dump (and again every hour until it works if the copy failed):

1. Uploads the newest dump through the encryption layer.
2. **Verifies** it: reads back the checksum Google holds for the encrypted file and compares it with the local dump encrypted the same way (`rclone cryptcheck`). Only then is the copy recorded as good.
3. Deletes copies older than **30 days** at the destination (`NUQATI_OFFSITE_KEEP_DAYS`); the newest 3 are always kept (`NUQATI_OFFSITE_MIN_KEEP`) and only files named like a dump are ever touched. If the listing fails, nothing is deleted. Google keeps deleted files in the Drive trash for up to 30 days; they still count against the storage quota until then.
4. The `db_backup` health status in Coolify turns **unhealthy** when the last good off-server copy is older than 50 hours (`NUQATI_OFFSITE_MAX_AGE_HOURS`), or when the off-server settings are wrong. Local dumps continue either way.

**Nothing leaves the server until `NUQATI_OFFSITE` is set.** Merging and deploying this feature changes nothing by itself.

**Decide first (not a technical question).** Google stores data in its own data centres, which can be outside the Kingdom. The files are encrypted before they leave, so Google cannot read them, but whether sending encrypted personal data abroad counts as a transfer under PDPL article 29 and the transfer regulations is a question for your legal counsel ([DATA_INVENTORY.md](DATA_INVENTORY.md) section 4; SDAIA's October 2026 draft amendments on data localisation are still drafts). If the answer is no, use a destination in the Kingdom instead: `NUQATI_OFFSITE=local` writes to any folder you mount into the container (for example a share on a second server), with the same encryption.

#### Set it up (about 20 minutes, once)

**Step 1: the encryption key. Do this first, and keep it safe.** Make two *different* random passphrases of at least 16 characters each (your password manager's generator, or `openssl rand -base64 24` twice). Save both in your password manager as one entry, "Nuqati off-server backup key", **outside this server**. **If you lose them, every off-server copy is unreadable, by everyone, forever.** They go into Coolify as `NUQATI_OFFSITE_PASSWORD` and `NUQATI_OFFSITE_PASSWORD2`. Never put them (or any value below) in GitHub.

**Step 2: the Google side. Choose one.**

*Path A: Google Workspace (recommended: no expiry, the files belong to the organisation).*
1. In the [Google Cloud Console](https://console.cloud.google.com/) create a project (for example "nuqati-backup") and enable the **Google Drive API**.
2. IAM & Admin, Service accounts: create one (for example `nuqati-backup`), then Keys, Add key, Create new key, **JSON**. A file downloads. (If creation of keys is blocked by an organisation policy, use Path B or ask the Workspace administrator.)
3. In Google Drive create a **Shared Drive** ("Shared drives", New), for example "Nuqati backups", and add the service account's e-mail address (it ends in `iam.gserviceaccount.com`) as a member with the role **Content manager**. Open the Shared Drive: the last part of the address (`.../drive/folders/<ID>`) is its id.
4. In Coolify set `NUQATI_OFFSITE=drive`, `NUQATI_OFFSITE_DRIVE_SHARED_DRIVE_ID=<ID>` and `NUQATI_OFFSITE_DRIVE_SERVICE_ACCOUNT_JSON=` the key file **on one line**. To turn the file into one line: `python3 -c "import json,sys; print(json.dumps(json.load(open(sys.argv[1]))))" key.json`. Delete the downloaded file afterwards.

*Path B: a personal Google account (your own OAuth client).* A service account cannot store files in a personal Drive (it has no storage of its own), so this path uses a token for your own account, limited to the narrow `drive.file` scope: it can only see files it created itself, never the rest of your Drive.
1. In the Google Cloud Console create a project and enable the **Google Drive API**. (rclone's shared client id is being retired during 2026, so use your own.)
2. Google Auth platform (OAuth consent screen): user type **External**, fill in the name and your e-mail, and **publish the app ("In production")**. If you leave it in "Testing", Google expires the token after **7 days** and the copy silently stops working until you repeat step 4 (the health status turns red when that happens). While signing in, Google may warn that the app is unverified: that is your own app; continue.
3. Credentials, Create credentials, OAuth client ID, type **Desktop app**. Copy the client id and the client secret.
4. On your own computer [install rclone](https://rclone.org/downloads/) and run `rclone config`: New remote, name `gdrive`, storage `drive`, paste the client id and secret, scope **`drive.file`** ("Files created or opened by the app"), leave the service account blank, answer No to advanced config and Yes to auto config. A browser opens: sign in with the Google account that should hold the backups and allow. Then run `rclone config show gdrive` and copy the `token = {...}` JSON.
5. In Coolify set `NUQATI_OFFSITE=drive`, `NUQATI_OFFSITE_DRIVE_CLIENT_ID`, `NUQATI_OFFSITE_DRIVE_CLIENT_SECRET` and `NUQATI_OFFSITE_DRIVE_TOKEN` (the JSON on one line). Do **not** create the backup folder by hand: with this narrow scope rclone can only see folders it created, so the first copy creates `nuqati-backups` (change the name with `NUQATI_OFFSITE_PATH`).

**Step 3: redeploy and prove it works.** Redeploy so the `db_backup` image is rebuilt (it now contains rclone). Then, on the server:

```bash
docker exec <db_backup-container> /usr/local/bin/offsite.sh check-config   # "the off-server copy settings look fine"
docker exec <db_backup-container> /usr/local/bin/offsite.sh test           # TEST OK: uploaded, read back identical, unreadable at the destination, deleted
docker exec <db_backup-container> /usr/local/bin/offsite.sh push           # copies the newest dump now (it also happens by itself after every backup)
docker exec <db_backup-container> /usr/local/bin/backup.sh health          # "ok: last off-server copy 0 hours ago"
docker exec <db_backup-container> /usr/local/bin/offsite.sh list           # size and name of every copy at the destination
```

`test` is the quickest way to find a wrong credential, a missing Shared Drive membership or a blocked folder, because it prints what failed. It also checks that what sits at Google is not the plain text.

**Step 4: the drill that matters: restore from the off-server copy with the passphrases from your password manager** (not copied from the server), because that is what you would have after losing the server. Start the command with a space so the shell does not keep the passphrases in its history:

```bash
 docker exec -e NUQATI_OFFSITE_PASSWORD='<first passphrase>' -e NUQATI_OFFSITE_PASSWORD2='<second passphrase>' <db_backup-container> /usr/local/bin/restore_drill.sh --offsite
```

It downloads the newest copy, decrypts it, restores it into the throw-away database like section 4a, prints `RESULT: OK | dump=... | source=off-server`, and deletes the download and the restored copy. Record it in section 6.

#### Day to day

- Read what it did: `docker logs <db_backup-container> --tail 50 | grep offsite`.
- Failure messages name the cause: `ERROR the upload of ... failed: ...` (destination or credentials), `could not be verified at the destination` (the upload was damaged: it is retried), `invalid settings: ...` (a setting is missing or malformed).
- Storage: each copy is about the size of a dump (`ls -l /backups` in the container) and 30 of them are kept. A free personal Google account has 15 GB. Lower `NUQATI_OFFSITE_KEEP_DAYS` or the handover-photo retention (R5) if you approach the limit.
- Rotating the key (for example if a passphrase may have leaked): set new passphrases, copy; the old copies stay readable only with the **old** passphrases, so keep those until the old copies have expired.
- Revoking access: delete the service account key (Path A) or revoke the app under your Google account's security settings (Path B), then set `NUQATI_OFFSITE=` to switch the copy off.

#### If the server is lost

Deploy Nuqati on a new server with the same Coolify settings (the passphrases and the Google credentials are among them, and in your password manager), start `db_backup`, then:

```bash
docker exec <db_backup-container> /usr/local/bin/offsite.sh fetch latest /tmp/restore   # prints the path of the decrypted dump
docker cp <db_backup-container>:/tmp/restore/nuqati-<stamp>.dump .
```

and continue with section 3 from step 3. `fetch` refuses a download that `pg_restore` cannot read, so a wrong passphrase or a damaged copy is reported instead of restored. Delete `/tmp/restore` and the copy afterwards: it holds personal data.

#### Without Google Drive (manual fallback)

Any encrypted copy to another provider satisfies the same goal, for example `age -r <public-key> -o nuqati-<stamp>.dump.age nuqati-<stamp>.dump` and a copy to storage of your choice, scheduled by the host's cron. Why encrypt: the dump contains driver names, ID numbers, precise locations and photographs. An unencrypted copy on another service is a data breach waiting to happen ([INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)).

**What this does not do.** It does not copy the secrets and settings (section 1), and a stolen Google credential plus the passphrases would give access to the data: keep both out of reach of the same person or system where you can. The Drive path could not be tested in the automated checks (they would need real credentials, and this repository is public); the encryption, the verification, the retention and the restore are tested against a real rclone with a local folder as the destination, and `offsite.sh test` tests the Drive side on your server.

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
5. Start `api`. Before the API starts, the container runs the database migrations (`python -m app.migrate`): a dump taken after the migrations were switched on is brought up to date to the newest revision; a dump taken earlier (no `alembic_version` table) is checked against the baseline schema and, if it matches, adopted. If the log says `NOT adopting this database` with a list, the dump is too old for this release (it lacks tables or columns): restore it, start the last version that still did this (commit `56c09fe`, the merge of Phase 3.3) once (it adds what is missing by itself), then deploy the current release again.
6. Check: `GET /api/v1/ready` answers, dashboard login works, a company's vehicles and last trips are present, the newest `security_audit` row is from the expected time.
7. Start the other services; tell users what period of data was lost (anything after the dump).
8. Write the incident log. If the cause was an attack, follow [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) before bringing the system back online.

If the **volume was lost** and a new one was created empty, do not run the API against it for long: it will start normally and look like a fresh install. Restore first.

## 4. Restore drill (do the first one now, then every 6 months)

### 4a. Quick drill on the server: one command

```bash
docker exec <db_backup-container> /usr/local/bin/restore_drill.sh
```

It restores the newest dump into a **throw-away database** (`nuqati_restore_drill`) on the same PostgreSQL server, compares row counts of the main tables with the live database (the live database is only read), prints a `RESULT: OK | dump=... | restore_seconds=... | tables=...` line, and **drops the copy again**, because it holds real personal data. Run it outside working hours: the restore uses CPU and disk. `RESULT: FAILED` (exit code 1) means the dump could not be restored or core tables are missing: treat that as an incident, take a fresh dump with `backup.sh once` and look at the log.

The restored copy having fewer rows than live is normal (the dump is up to a day old). More rows than live, or a missing `companies` / `users` table, is not.

Paste the `RESULT:` line into the log in section 6. This proves the dump is restorable on this server; it does not prove that the off-server copy is intact or that the API runs against the restored data. For the off-server copy run `restore_drill.sh --offsite` (section 2b, step 4); for the API, do 4b once.

### 4b. Full drill on a separate machine (once, then yearly)

Do this on a **separate machine or a throwaway container, never on production**.

1. Pick the newest dump from the off-server storage (this also proves the copy works): `offsite.sh fetch latest <folder>` from section 2b gives you the decrypted dump.
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

1. Switch on the off-server copy (2b): decide the data-location question with counsel, create the key and the Google side, run `offsite.sh test`, then the drill with `--offsite`. The code exists since Phase 4.2; it is off until you set `NUQATI_OFFSITE`.
2. Do the first restore drill (4a, then 4b) and record it.
3. Confirm the retention (14 days on the server, 30 days off the server) and the objectives (24 h / 4 h).
4. Decide about `NUQATI_VERIFIED_BACKUP_REFERENCE` (section 5).
5. Store an encrypted copy of both Android keystores outside GitHub, if not already done.
