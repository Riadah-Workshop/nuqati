# Incident response runbook

Use this when you suspect that personal data was seen, changed, lost or taken by someone who should not have had it, or that the system was misused. When in doubt, start the runbook: stopping early costs nothing, starting late can cost the notification deadline.

> **The clock.** Where notification is required, the regulator (SDAIA) must be told **within 72 hours of becoming aware of the breach**, and affected people without undue delay (per public summaries of the PDPL by DLA Piper and Clyde & Co; counsel must confirm when notification is required and how to file). Write down the exact time you became aware: everything below counts from there.

## 1. Contacts (fill in; keep a printed copy)

| Role | Name | Phone | E-mail |
|---|---|---|---|
| Incident lead (decides, owns the log) | | | |
| Technical lead (server, database, deployments) | | | |
| Legal counsel / data protection contact | | | |
| Customer contact at each affected company | see contract | | |
| Hosting provider support | | | |
| SDAIA notification channel | counsel to confirm the current process | | |

## 2. What counts as an incident

| Examples | Severity |
|---|---|
| A password, token secret, database password or signing key was exposed (chat, screenshot, public repository, former staff) | High |
| Unexpected sign-ins, a user you do not recognise, role changes nobody asked for (see `security_audit`) | High |
| One customer saw another customer's data | High |
| Database or server access by an unknown party; a backup was lost or copied | High |
| A report or live-share link went to the wrong person | Medium |
| A lost phone with the Driver or Manager app | Low (release the device session, see 4.3) |
| Service down with no sign of data exposure | Operational, not a breach; still log it |

## 3. First hour: contain and record

1. **Start the log** (section 8): time you became aware, who reported it, what was seen. Keep it factual.
2. **Do not delete anything**: not logs, not accounts, not the database. Deleting destroys the evidence you need. Disable instead.
3. **Contain** with the matching actions in section 4.
4. **Preserve evidence** (section 5) before restarting or redeploying anything.
5. Tell the incident lead and counsel. Do not announce anything to customers or drivers yet.

## 4. Containment actions

### 4.1 A user account is misused or its password is exposed

- Super Admin or Company Admin: deactivate the user (Users page; `PATCH /api/v1/users/{id}/deactivate`). A deactivated account cannot sign in and its existing tokens stop working. Prefer this to deleting the account (`DELETE /api/v1/users/{id}`), which removes it.
- Reset the password and sign out everywhere: the owner of the account changes the password (this ends all their sessions), or sign in as that user and use **Log out**, which also ends every session of that user on all devices.
- Review what the account did: query the audit trail (section 5).

### 4.2 The token-signing secret may be exposed

- Rotate `NUQATI_AUTH_SECRET` **without** setting `NUQATI_AUTH_SECRET_PREVIOUS`. Everyone is signed out at once, including attackers holding forged tokens. Do **not** use the rotation window here: it keeps old tokens valid. Steps in [SECRET_ROTATION.md](SECRET_ROTATION.md).
- Then review the audit trail for the exposure period.

### 4.3 A driver's phone was lost or stolen

- An admin releases the driver's device session: driver page, **Sign out driver's phone** (or `POST /api/v1/drivers/{id}/release-device-session`). The old phone's tokens stop working.
- If the account password may be known, set a new one: **Reset password** on the same page, with "Also sign out the driver's phone" ticked ([OPERATIONS.md](../OPERATIONS.md) section 10).

### 4.4 A live-share link or report went to the wrong person

- Revoke the link (`DELETE /api/v1/fleet/live-shares/{id}`, available in the live-tracking page); links also expire on their own.
- Disable or delete the scheduled report (`PATCH` / `DELETE /api/v1/fleet/report-subscriptions/{id}`). Note what the report contained and who received it.

### 4.5 Database or server access by an unknown party

- Ask the hosting provider to isolate the server if you cannot do it yourself; change SSH keys and the Coolify admin password.
- Rotate `POSTGRES_PASSWORD` (see [SECRET_ROTATION.md](SECRET_ROTATION.md)), then every other secret there.
- Take a **disk snapshot** or `pg_dump` for evidence before any clean-up (section 5).
- Plan a restore from a clean server using the last known-good backup ([BACKUP_RESTORE.md](BACKUP_RESTORE.md)).

### 4.6 An external service key leaked (SMTP, MapTiler, WhatsApp)

- Revoke and replace the key with the provider; update Coolify and (for MapTiler) the GitHub secret `MAPTILER_API_KEY` and rebuild the web image and mobile apps.

## 5. Evidence and investigation

Read-only queries on the audit trail, run in a database console (`psql`) on the server. Times are stored in UTC.

```sql
-- everything one account did in a period
SELECT created_at, action, outcome, target_type, target_id, ip, detail
FROM security_audit
WHERE actor_user_id = :user_id AND created_at BETWEEN :from AND :to
ORDER BY id;

-- failed sign-ins grouped by address in the last 24 hours (look for spikes)
SELECT ip, count(*) AS failures
FROM security_audit
WHERE action IN ('auth.login','auth.driver_login') AND outcome <> 'ok'
  AND created_at > now() - interval '24 hours'
GROUP BY ip ORDER BY failures DESC LIMIT 20;

-- sign-ins that succeeded from an address that account has never used before
SELECT a.created_at, a.actor_email, a.ip
FROM security_audit a
WHERE a.action = 'auth.login' AND a.outcome = 'ok' AND a.created_at > now() - interval '7 days'
  AND NOT EXISTS (SELECT 1 FROM security_audit b WHERE b.actor_user_id = a.actor_user_id
                  AND b.ip = a.ip AND b.action = 'auth.login' AND b.outcome = 'ok'
                  AND b.created_at < now() - interval '7 days')
ORDER BY a.created_at DESC;

-- data leaving the system: exports and scheduled reports
SELECT created_at, actor_email, company_id, action, target_id, detail
FROM security_audit
WHERE action IN ('report.export','report_subscription.create','live_share.create')
  AND created_at > now() - interval '30 days'
ORDER BY id DESC;
```

Also keep: the web and API container logs from Coolify (download them before redeploying; containers' logs are lost when a container is recreated), the Caddy access log, and the hosting provider's access logs. Save copies outside the server.

The audit trail starts with the release that introduced it; for earlier periods only the older audit tables and container logs exist. State this honestly in any report.

## 6. Decide: is it a notifiable breach?

With counsel, within the first 24 hours:

1. Was **personal data** involved (names, phone, ID numbers, locations, photos, e-mail addresses)? If only technical data, it is not a personal-data breach.
2. Who is the **controller** for this data (the customer company, Nuqati, or both)? The customer company usually must be told promptly so that it can meet its own duty; check the contract for the deadline.
3. Is harm to people likely (for example, precise movement history of named drivers)? That decides whether SDAIA and the individuals must be notified.
4. Record the decision and the reasons, even if the decision is "no notification".

## 7. Notify (when required)

| Step | By when | Content |
|---|---|---|
| Inform the affected customer company | As soon as you know it is their data; contractual deadline if shorter | What happened, which of their data, what you did, what they should do |
| Notify SDAIA | Within **72 hours** of awareness | Nature of the breach; categories and approximate number of people and records; likely consequences; measures taken or planned; contact point. Counsel files it |
| Inform affected people | Without undue delay, where required | Plain language, in Arabic and English: what happened, what data, what to do, who to contact |

If not everything is known at 72 hours, file what you have and say that more will follow.

## 8. Incident log (copy for each incident)

| Time (UTC and Riyadh) | Who | What happened / what was decided / what was done |
|---|---|---|
| | | Aware of the incident |
| | | Contained |
| | | Counsel informed |
| | | Customer(s) informed |
| | | SDAIA decision (notify / not, reasons) |
| | | Closed |

## 9. After the incident (within two weeks)

1. Write a short review: timeline, cause, what worked, what did not.
2. Fix the cause. If it was a secret, rotate it; if a missing check, add a test.
3. Update this runbook, the data inventory and the contact table.
4. Keep the log and the evidence for the period counsel advises.

## 10. Open items

1. Fill in section 1.
2. Counsel to confirm the notification process and any form SDAIA requires.
3. Agree the customer-notification deadline in each contract.
4. Rehearse once a year with a made-up case (a lost phone and an exposed password are good ones).
