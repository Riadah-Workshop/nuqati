# Compliance pack

Working documents for running Nuqati as a service that handles driver location and employee data in the Kingdom of Saudi Arabia (Personal Data Protection Law, "PDPL").

**These are operating procedures, not legal advice.** Where a document states a legal deadline or duty it says where it came from; have your legal counsel confirm each one, and confirm who is the *controller* and who is the *processor* for each customer company (that depends on your contracts).

| Document | What it is for | Status |
|---|---|---|
| [DATA_INVENTORY.md](DATA_INVENTORY.md) | What personal data the system holds, where, why, and who can see it (the record of processing). | Draft from the code. Owner must confirm purposes and recipients. |
| [RETENTION_SCHEDULE.md](RETENTION_SCHEDULE.md) | How long each kind of data should be kept, and what the future clean-up job will do. | **Proposal.** The periods are suggestions, not decisions. |
| [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) | What to do in the first hour, the first day and before the 72-hour notification deadline. | Ready to use. Fill in the contact table. |
| [DATA_SUBJECT_REQUESTS.md](DATA_SUBJECT_REQUESTS.md) | How to answer access, correction and deletion requests within 30 days. | Ready to use. Some steps are manual until tooling exists. |
| [BACKUP_RESTORE.md](BACKUP_RESTORE.md) | Backup routine, restore drill, and what to record. | Ready to use. **No restore drill has been recorded yet.** |
| [SECRET_ROTATION.md](SECRET_ROTATION.md) | How and when to change each secret, including the zero-downtime window for the token secret. | Ready to use. |

## Where the evidence comes from

- **Security audit trail.** Since Phase 2.1 the API records who signed in (and who failed to), password and e-mail changes, user, driver, vehicle and company changes, report exports, scheduled-report changes, live-share links and settings changes in the table `security_audit`. Company admins can read their own company's rows at `GET /api/v1/security-audit`; super admins can read all of them. It stores no passwords, tokens, coordinates or message text. Its retention is in the retention schedule.
- **Older audit tables** remain as they were: company deletion, trip and event deletion, privacy-mode changes, vehicle handover actions, mobile lifecycle events.

## Review rhythm

| When | What |
|---|---|
| Every 3 months | Read the "Open items" list at the end of each document; update the contact table in the incident runbook. |
| Every 6 months | Run a restore drill and record it ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)). |
| Every 12 months, and whenever a secret may have been seen by someone who should not have it | Rotate secrets ([SECRET_ROTATION.md](SECRET_ROTATION.md)). |
| When a new external service, a new data field, or a new country of hosting is added | Update the data inventory first. |
