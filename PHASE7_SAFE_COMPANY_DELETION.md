# Nuqati Phase 7 — Safe Company Deletion (staging first)

## Changes
- Super Admin-only permanent deletion of a selected company and its linked users, driver accounts, invitations, drivers, metadata, vehicles, trips, locations, driving events, maintenance and odometer records.
- Corrects missing `driver_metadata` deletion, a probable cause of foreign-key conflicts in the original endpoint.
- Preview includes all modeled dependent tables.
- Exact company-name confirmation, `DELETE` keyword, final browser confirmation, and verified backup reference.
- Audit table `company_delete_audit` retains company ID/name, admin ID/email, backup reference, counts and timestamp in the SAME database transaction.
- No DB-wide truncate and no existing table drops. No deletion is executed by deployment.

## Critical backup gate — REQUIRED before using deletion
1. On the Coolify VPS, take a PostgreSQL custom-format logical dump (`pg_dump -Fc`) and securely copy it OFF the VPS. Do not put database credentials or dumps into GitHub.
2. Restore that dump into a **separate disposable PostgreSQL database**, verify table counts and record the backup identifier. A file existing is not sufficient proof of recovery.
3. In Coolify for the **API service only**, configure environment variable `NUQATI_VERIFIED_BACKUP_REFERENCE` to that exact backup identifier (e.g. `staging-2026-10-25-verified-001`), then redeploy API. Treat it as a restricted operations value; rotate it for each backup/deletion window. Never put it in Git.
4. In dashboard > Companies, select **Permanently delete company + linked data**, check counts, type exact company name, type `DELETE`, enter matching backup identifier and confirm.
5. Verify the company disappeared, other companies remain, and audit row was created. Retain backup securely according to your retention policy.

**IMPORTANT:** The backend cannot prove the backup was restored; the backup gate enforces operator attestation. Do not set the variable before a successful restore test. The audit log is in the same DB, so also export logs off-server for stronger evidence. Existing access tokens of deleted users might remain valid until expiry if other endpoints only trust token claims; verify `current_user` checks DB on every request.

## Deployment
- Replace `backend/app/main.py` and `web/src/App.tsx` on your `main` branch.
- Allow Coolify to deploy; retain existing PostgreSQL volume and env vars.
- `company_delete_audit` is created with `create_all` on backend startup. Ensure the API DB user has CREATE TABLE privileges or create it via a reviewed migration.
- Confirm `/api/v1/health`, login and read-only company preview before any deletion.
- Test only with a disposable company first; compare unrelated company counts before/after.

## Known limits
- This implementation covers the tables in the supplied source ZIP (dated 21 October 2026). If newer migrations introduced more foreign-key references, the deletion will roll back and return HTTP 409; review the schema before retrying.
- The backend does not automatically create backups. Backups must be generated and verified by an authorized operator.
- `NUQATI_VERIFIED_BACKUP_REFERENCE` is a manual operational safeguard, not a cryptographic proof of backup freshness.
