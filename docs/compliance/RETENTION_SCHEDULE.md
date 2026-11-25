# Retention schedule — PROPOSAL

> **Status: proposal. Nothing in this file is in force and no data is deleted automatically today.** The periods are suggested starting points for the owner and legal counsel to change. After they are confirmed, a clean-up job (section 3) will be built to enforce them.

Why this matters: the privacy policy promises that data is kept only as long as needed, and PDPL expects a retention and minimisation policy (per public legal summaries). Today GPS history, diagnostics and audit rows are kept indefinitely.

## 1. Proposed periods

Key: **Ref** = the table names that hold the data (see [DATA_INVENTORY.md](DATA_INVENTORY.md)). "Then" is what the clean-up job would do.

| # | Data | Ref | Proposed period | Why this period | Then |
|---|---|---|---|---|---|
| R1 | Precise GPS points | `driver_locations`, `telematics_points`, `mobile_gps_sample_receipts` | **12 months** after capture | Enough for a year of disputes and seasonal comparison; the most sensitive data in the system | Delete rows |
| R2 | Trip summaries and driving events | `trips`, `driving_events`, `mobile_safety_observation`, `mobile_safety_event_receipts`, `mobile_trip_*` | **24 months** after the trip | Scores, reports and disputes | Delete rows (events carry coordinates, so they follow the longer period only as a compromise: confirm, or strip coordinates after 12 months) |
| R3 | App health and diagnostics | `mobile_tracking_heartbeat`, `mobile_diagnostics`, `mobile_lifecycle_audit`, `mobile_notification_audit`, `driver_connection_alerts` | **90 days** | Only useful for support and connectivity alerts | Delete rows |
| R4 | Privacy Mode requests and audit | `driver_privacy_requests`, `mobile_privacy_audit` | **24 months** | Proof that a driver's choice was honoured | Delete rows |
| R5 | Vehicle handover evidence | `handover_assignments`, `handover_inspections`, `handover_photos`, `handover_audit` | **24 months after the vehicle is returned** | Damage disputes; photos are large | Delete rows and photos |
| R6 | Security audit trail | `security_audit` | **24 months** | Investigations and accountability; short enough to limit stored IP addresses | Delete rows |
| R7 | Other audit records | `company_delete_audit`, `admin_trip_end_audit`, `admin_trip_deletion_audit` | **5 years** | Evidence of administrative deletions; contain no coordinates | Keep (no action) unless counsel advises otherwise |
| R8 | One-time tokens | `dashboard_account_tokens`, `account_invitations` | **30 days** after use or expiry | No value once used | Delete rows |
| R9 | Sign-in throttle counters | `auth_attempt_buckets` | **7 days** | Only needed while a block is active | Delete rows |
| R10 | Live-share links | `app_settings` rows with key `live_share:*` | **7 days** after expiry or revocation | The link is already dead | Delete rows |
| R11 | Scheduled-report subscriptions | `report_email_subscriptions` | Until disabled or deleted by the customer; review yearly | Operational setting that contains an e-mail address | Customer-controlled |
| R12 | Drivers who left | `drivers`, `driver_metadata`, `driver_accounts`, `driver_device_sessions`, `users` (driver role) | Identifiers (name, phone, ID number) removed **12 months** after the driver is deactivated, unless a legal hold applies | Keeps history usable for a year, then removes identity | Replace name/phone/ID with a neutral label and delete the login; keep aggregated trip records |
| R13 | Dashboard users who left | `users` | Deactivate immediately; delete or anonymise **12 months** later | Audit rows keep the actor id | Anonymise the e-mail and name |
| R14 | Customer company ended | all rows of the company | Existing procedure: permanent deletion needs a verified off-server backup reference (`POST /api/v1/companies/{id}/permanent-delete`) | Already implemented | Follow the procedure |
| R15 | Database backups | off-server dumps | **30 days** rolling (see [BACKUP_RESTORE.md](BACKUP_RESTORE.md)) | Limits how long deleted data can still be restored | Delete oldest dumps |

**Backups and deletion.** Rows deleted by the job can still exist in a backup until that backup expires (R15). State this in answers to deletion requests ([DATA_SUBJECT_REQUESTS.md](DATA_SUBJECT_REQUESTS.md)).

**Legal hold.** If a dispute, claim or investigation concerns a driver, vehicle or company, the job must skip those rows until the hold is lifted. The owner records holds in a short register (who, what, why, date); the job reads it. Until the job exists, do not delete anything by hand that is under a hold.

## 2. Decisions needed

| Question | Options | Proposed |
|---|---|---|
| Are 12 months for GPS points right for your customers' contracts? | 6 / 12 / 24 months | 12 |
| Keep event coordinates beyond 12 months? | Keep 24 months / strip the coordinates at 12 months and keep the event | Strip at 12 months (needs a small change in the job) |
| Is 24 months right for the audit trail and Privacy Mode records? | 12 / 24 / 36 months | 24 |
| Can a customer company choose shorter periods for its own data? | No / yes, never longer than the maximum | Yes, never longer |
| Who approves a legal hold? | Owner / counsel | Owner, on counsel's advice |

## 3. What the clean-up job will do (to be built after approval)

- Runs daily at a quiet hour as a separate container, like the report scheduler (`python -m app.<module>`), so an error cannot affect the API.
- **Dry run first:** a mode that only counts what it would delete per rule and writes the counts to the log. The first production run is always a dry run that the owner reviews.
- Deletes in **small batches** (for example 5,000 rows) with a pause between them, so the database stays responsive.
- Writes one `security_audit` row per rule per run: rule id, rows deleted, cut-off date. No personal data in that row.
- Reads its periods from one configuration place (environment or a settings table) so a change needs no code release, and refuses periods shorter than a safe minimum to protect against typing mistakes.
- Skips anything under legal hold (section 1).
- After large deletions, a manual `VACUUM` (or autovacuum catching up) is needed to return space; the runbook will say when.
- Photos (R5) live in PostgreSQL, so deleting them is also what keeps backup size under control.

## 4. Open items

1. Owner and counsel confirm or change section 1.
2. Decide the questions in section 2.
3. Approve building the job (a Phase 2.2 task) and the legal-hold register.
4. Align the public privacy policy wording ("retention varies by record category") with the confirmed periods, and add the periods to the customer contract or data-processing terms.
