# Data-subject requests (access, correction, deletion)

How to handle a request from a person about their own data: a driver asking what is stored about them, asking to correct it, or asking to have it deleted. The same steps apply to dashboard users.

> **The clock.** Requests must be answered **within 30 days** (per public summaries of the PDPL by Clyde & Co; counsel to confirm). Count from the day the request reached anyone at Nuqati or at the customer company.

**Who answers.** In most cases the customer company decides why driver data is collected (it is the *controller*; Nuqati is its *processor*), so the company answers its drivers and Nuqati helps it do so. Check the contract. If a driver writes to Nuqati directly, acknowledge the request, tell them it was passed to their employer if that is the arrangement, and send it to the company the same day. If Nuqati is the controller (for example, a dashboard user of Nuqati itself), Nuqati answers.

## 1. Steps

| # | Step | Who | Deadline |
|---|---|---|---|
| 1 | **Log** the request in the register (section 6) with the date received and the channel | Whoever receives it | Same day |
| 2 | **Acknowledge** in writing, in the person's language (Arabic or English) | Support | 3 days |
| 3 | **Verify identity**: ask for something only the person has (the phone number and Iqama / ID number on file, confirmed by their employer's HR). Do not send data to an unverified address | Support + company contact | 7 days |
| 4 | **Decide** what is being asked: a copy (access), a correction, or deletion, or an objection to processing | Request owner | 7 days |
| 5 | **Check for a legal hold** (a dispute or investigation about this person or vehicle). If there is one, deletion waits; tell the person that a legal reason applies | Owner / counsel | 10 days |
| 6 | **Collect** (access) or **change** (correction, deletion), section 2 to 4 | Technical lead | 21 days |
| 7 | **Review** the result: a second person checks that nothing about other people is included | Second person | 25 days |
| 8 | **Reply** with the result and the reasons for anything not done; record it | Request owner | 30 days at the latest |

## 2. Finding the person's data

Find the person's ids first: for a driver, `drivers.id` (search by phone or by `driver_metadata.id_number`) and the linked login `driver_accounts.user_id` → `users.id`; for a dashboard user, `users.id` and e-mail.

List every table that holds a driver id (this stays correct as tables are added):

```sql
SELECT table_name FROM information_schema.columns
WHERE table_schema = 'public' AND column_name = 'driver_id' ORDER BY 1;
```

Then count rows per table for the person (read-only):

```sql
SELECT 'trips' AS t, count(*) FROM trips WHERE driver_id = :driver_id
UNION ALL SELECT 'driver_locations', count(*) FROM driver_locations WHERE driver_id = :driver_id
UNION ALL SELECT 'driving_events', count(*) FROM driving_events WHERE driver_id = :driver_id
UNION ALL SELECT 'handover_inspections', count(*) FROM handover_inspections WHERE driver_id = :driver_id;
-- repeat for the other tables returned by the first query (mobile_* tables, workshop_assistance_requests, ...)
```

Other places a person can appear:

| Where | What to look for |
|---|---|
| `users` | E-mail, name, role (driver logins use an internal address ending `@login.nuqati.invalid`, which is not a real e-mail) |
| `driver_device_sessions` | Installation device id, last login |
| `security_audit` | Rows where `actor_user_id` is the person's user id (what they did, from which IP address) |
| `report_email_subscriptions` | The person's e-mail as a report recipient (`recipient`) |
| `handover_photos` | Photos taken during their handovers (image bytes in the database) |
| Backups | Copies expire on the schedule in [BACKUP_RESTORE.md](BACKUP_RESTORE.md); say so in the reply |

## 3. Access (a copy)

1. Export for the person: profile (name, phone, ID number, site), their trips and driving events (time, type, speed, score), their location points if requested, handover inspections and photos, Privacy Mode requests, and the security-audit rows about their own sign-ins.
2. Provide it as CSV files plus the photos, in a password-protected archive; send the password by a different channel.
3. Exclude data about other people (a co-driver, a manager's notes about someone else). If a row mixes people, remove the other person's fields.
4. There is no export tool yet; the technical lead runs the queries above. Writing a small export script is proposed for Phase 2.2.

## 4. Correction

- Name, phone, ID number, site and status: an admin edits the driver in the product (`PATCH /api/v1/drivers/{id}`); the change is recorded in the audit trail.
- Wrong trip or event: an admin can delete a trip or an event with a reason (recorded in the existing deletion audit).
- A correction the product cannot make is done in the database by the technical lead with a second person present, and written into the register.

## 5. Deletion

What the product allows today:

- A driver **without** trip history can be deleted (`DELETE /api/v1/drivers/{id}`, Super Admin).
- A driver **with** trip history cannot be deleted: the call is refused and says to archive. Archive by setting the status to inactive and removing the login (deactivate the user).
- A whole customer company can be permanently deleted with a verified backup reference (`POST /api/v1/companies/{id}/permanent-delete`).

So for a driver who left and asks for erasure, the technical steps are:

1. Confirm there is no legal hold and no obligation to keep the records (for example an open dispute, or a contractual retention duty). If part of the data must be kept, say which part and why.
2. Make a fresh backup and note its reference.
3. **Anonymise** the driver rather than delete trips: replace name, phone and ID number with a neutral label, remove the login and device session, delete location points and photos that are not under a hold. The trip totals stay, so the company's reports remain correct.
4. A second person checks the result with the read-only counts in section 2.
5. Reply: say what was deleted, what was kept and why, and that copies in backups disappear when the backup expires (see [RETENTION_SCHEDULE.md](RETENTION_SCHEDULE.md), R15).

There is no tested anonymisation script yet. **Do not improvise destructive SQL on production.** Until the tool exists, the technical lead writes the statements, tests them on a restored copy (see [BACKUP_RESTORE.md](BACKUP_RESTORE.md)), and runs them with a second person present. Building the tool is proposed for Phase 2.2.

## 6. Request register (copy this table)

| # | Received | Person / company | Type | Identity verified | Legal hold? | Handled by | Replied | Notes |
|---|---|---|---|---|---|---|---|---|
| 1 | | | access / correction / deletion / objection | yes / no | yes / no | | | |

## 7. Reply templates (adapt, Arabic and English)

**Acknowledgement.** "We received your request on [date] about the personal data held about you in Nuqati. We will answer within 30 days, by [date]. We first need to confirm your identity: please [what to send]."

**Completed.** "Attached is [a copy of / the correction made to / confirmation of deletion of] your data. [Summary.] Some information was kept because [reason]. Copies in our backups are removed automatically by [date]. If you are not satisfied, contact [contact], or the Saudi Data and AI Authority (SDAIA)."

**Not possible.** "We cannot [do X] because [specific reason, for example an open legal claim]. We will review this on [date]."

## 8. Open items

1. Decide, with each customer, who answers driver requests and write it in the contract.
2. Appoint the request owner and a second reviewer.
3. Approve building the export and anonymisation tools (Phase 2.2).
4. Counsel to confirm the list of rights and the reply contents.
