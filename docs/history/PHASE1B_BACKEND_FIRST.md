# Nuqati Phase 1B — Step 1: Backend preparation

Replace `backend/app/main.py` in the GitHub repository, then deploy the API.

This is a backend-only preparation update. It does NOT yet enable Android background recording, SQLite storage or offline synchronization. Those require the next Android update.

Changes:
- Optional `captured_at` ISO 8601 UTC timestamp on `/api/v1/mobile/trips/{id}/sample`.
- Optional `sample_id` unique string for idempotent retry.
- Preserves the GPS capture timestamp on recorded location and driving events.
- Uses captured timestamps for distance and 30-second event cooldown.
- Creates an additive `mobile_gps_sample_receipts` table on API startup to track uploaded IDs.
- Rejects samples more than 14 days old or more than 30 seconds in the future.
- Maintains existing clients that do not send these new fields.

Deployment caution: The API database account must have CREATE TABLE permission. Test on staging and back up PostgreSQL before deploying. This update has been Python syntax-checked but not run against a live database.

Validation: start a trip using existing app, upload a GPS fix, confirm HTTP 200 and no API traceback. The Android update follows only after this passes.
