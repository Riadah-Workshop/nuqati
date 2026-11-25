# Data inventory (record of processing)

Built from the database definitions and handlers in the code as of Phase 2.1. It lists what the **system** stores. Purposes, legal bases and recipients are written from how the product works; the owner must confirm them, and counsel must confirm the legal basis for each customer company.

## 1. Whose data

| Group | Examples | How the data arrives |
|---|---|---|
| **Drivers** | Name, phone, Iqama / national ID number, site, vehicle, trips, locations, driving events, scores, device identifier, handover photos | Entered by an admin, then collected by the Driver app while a trip is active |
| **Dashboard users** (staff of Nuqati and of customer companies) | E-mail, name, role, company, password hash, sign-in history | Created by an admin or by invitation |
| **Report recipients** | E-mail address typed into a scheduled report | Entered by a fleet manager or admin |
| **People who open a live-share link** | Their IP address is seen by the web server only; no account | Link created by an admin |
| **Tracker devices** (Teltonika) | IMEI, vehicle, position history | Sent by the device |

## 2. What is stored, where

"Sensitivity": **High** = precise location or identity documents; **Medium** = identifies a person; **Low** = no person involved or only a technical key.

| Data | Tables | Personal fields | Sensitivity | Purpose | Who can read it in the product |
|---|---|---|---|---|---|
| Companies | `companies`, `company_driving_settings`, `company_event_conditions`, `app_settings` (branding, thresholds, geofence zones, severity policy) | Company name, logo | Low | Tenancy and configuration | Admins of that company; super admin |
| Dashboard accounts | `users`, `account_invitations`, `dashboard_account_tokens` | E-mail, full name, role, password hash (PBKDF2), one-time token hashes | Medium | Sign-in and account recovery | The user; admins of that company; super admin (hashes are never shown) |
| Drivers | `drivers`, `driver_metadata`, `driver_accounts`, `driver_device_sessions` | Full name, phone, **ID / Iqama number**, site, installation device id, last login | High | Identify the driver, link phone login, lock one device | Admins and managers of that company |
| Vehicles and service | `vehicles`, `odometer_readings`, `maintenance_schedules`, `driver_service_history` | Plate, model; the assigned driver ties them to a person | Low–Medium | Fleet and maintenance management | Roles of that company |
| Trips | `trips`, `mobile_trip_numbers`, `mobile_trip_client_ids`, `mobile_gps_sample_receipts`, `mobile_safety_event_receipts`, `deleted_mobile_trip_clients` | Driver id, start/end time, distance | Medium | Trip records and scores | Roles of that company |
| **Precise location history** | `driver_locations`, `driving_events` (has coordinates), `telematics_points` (tracker positions), `workshop_assistance_requests` (position of an assistance request) | Latitude, longitude, speed, heading, accuracy, time, driver or vehicle | **High** | Live map, trip route, safety events, geofencing, assistance | Roles of that company; public live-share link shows the current position of one vehicle while a trip is active and Privacy Mode is off |
| Driving behaviour | `driving_events`, `mobile_safety_observation` | Event type, speed, time, driver | Medium | Safety scores and reports | Roles of that company |
| App health | `mobile_tracking_heartbeat`, `mobile_diagnostics`, `mobile_lifecycle_audit`, `mobile_notification_audit`, `driver_connection_alerts` | Driver id, phone state (screen on/off, GPS fix age), error codes, free-text `detail` | Medium | Detect a phone that stopped reporting; support | Admins and managers; workshop staff for diagnostics |
| Privacy Mode | `driver_privacy_requests`, `mobile_privacy_audit` | Driver id, reason, request and decision times | Medium | Honour and record privacy requests | Admins and managers |
| Vehicle handover | `handover_assignments`, `handover_inspections`, `handover_photos` (image bytes stored in PostgreSQL), `handover_audit` | Driver id, inspection notes, **photographs**, review notes | Medium–High | Evidence of vehicle condition at receipt and return | Roles of that company |
| Reports and sharing | `report_email_subscriptions`, `app_settings` (`live_share:*`, hashed token) | **External e-mail address of the recipient**, scope of the report | Medium | Scheduled e-mail reports; live-share links | Admins and managers of that company |
| Security and audit | `security_audit` (new), `company_delete_audit`, `admin_trip_end_audit`, `admin_trip_deletion_audit`, `handover_audit`, `auth_attempt_buckets` | Actor id and e-mail, role, company, action, **client IP address** (authentication events only), HMAC digests of sign-in identifiers | Medium | Accountability, investigations, abuse protection | Admins (`security_audit` of their company); super admin |
| Trackers | `telematics_devices` | IMEI, vehicle | Low–Medium | Receive tracker positions | Admins of that company |
| Database backups | Docker volume `nuqati_backups` (daily dumps by the `db_backup` service) and any off-server copy | Everything in the database, including the fields above | As the data they contain (High) | Recovery after loss or damage | Whoever has access to the server; off-server copies: whoever holds the key (BACKUP_RESTORE.md 2b) |

Not stored: plain-text passwords, plain-text reset or invitation tokens (only SHA-256 hashes), card or payment data, audio, video, contacts, SMS.

## 3. Who receives data outside the system (processors and sub-processors)

| Service | What it receives | Where it runs | To confirm |
|---|---|---|---|
| Server host (VPS managed with Coolify) | Everything: it hosts the database and the application | Provider and country: **fill in** | Hosting country; data-processing terms; whether the host can access disk contents |
| DNS (Hostinger) | The domain name only | — | — |
| SMTP provider | Recipient address, subject, message body (invitations, resets, alerts, scheduled reports, which contain driver names and scores) | **Fill in** | Provider, country, contract |
| Meta (WhatsApp Cloud API) | Webhook calls from Meta to Nuqati; what Nuqati sends back depends on the integration | Meta | Whether any personal data is sent to Meta |
| MapTiler | Map tile requests from the browser and the Manager app: the browser's IP address and the map area viewed (not driver names) | MapTiler | Cross-border transfer review |
| unpkg.com (third-party script CDN) | Browser's IP address when the map pages load Leaflet | Outside the Kingdom (confirm) | Planned to be removed by self-hosting Leaflet (open item S5) |
| GitHub | Source code, CI logs, build secrets. No production personal data. | GitHub | Keep personal data out of issues and logs |

## 4. Cross-border transfers

Transfers outside the Kingdom are governed by PDPL Article 29 and the Transfer Regulations (per public legal summaries). Today the flows to review are: the hosting location, the SMTP provider, MapTiler and unpkg. SDAIA published **draft** amendments in October 2026 proposing data-localisation requirements and stricter breach notification; treat them as drafts until counsel confirms they are in force.

## 5. Impact assessment

Continuous location tracking of employees is the highest-risk processing in the product. A short written assessment (why it is needed, what is minimised, what safeguards exist) should exist for each customer. The safeguards already in the product are: Privacy Mode with an audit record, location only during trips, role- and company-scoped access, expiring and revocable live-share links, and the audit trail. Open: retention limits (see the schedule), a documented process for driver requests, and an assessment document signed off by the owner.

## 6. Open items

1. Fill in hosting provider and country, SMTP provider and country.
2. Confirm for each customer company whether it is the controller and Nuqati the processor (or joint controllers) and put the answer in the contract.
3. Confirm the retention periods ([RETENTION_SCHEDULE.md](RETENTION_SCHEDULE.md)).
4. Decide who may be a scheduled-report recipient (today any address; finding S6).
5. Decide whether to self-host Leaflet (finding S5) and remove unpkg from the list above.
6. Write the impact assessment for location tracking.
