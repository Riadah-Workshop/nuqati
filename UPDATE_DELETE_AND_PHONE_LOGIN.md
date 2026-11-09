# Nuqati staging update — delete controls and driver phone login

## Before deployment
1. Take a verified PostgreSQL backup/snapshot in Coolify. Test on staging only.
2. Preserve existing environment variables, domain, volumes and database. No reset or reinitialization.
3. Replace source files in the existing GitHub repository, including `.github/workflows/build-android.yml`, then deploy staging.
4. Do not remove your existing GitHub Actions workflows if already configured differently; compare before merging.

## Changes
- Super Admin user deletion now removes linked invitations and login association in one transaction. It never deletes the logged-in admin or any Super Admin.
- Driver deletion unassigns vehicles and removes account association. Historical trip records block individual driver deletion with HTTP 409 instead of HTTP 500. Use `status=archived` or the explicit company purge.
- Company deletion previews counts and requires typing the exact company name. The purge removes only that company's users, vehicles, drivers, trips, GPS locations, driving events, maintenance and readings, then the company. It is permanent.
- Android login uses driver phone + the existing private password. The driver must have a unique phone across active linked driver profiles. Saudi 05..., 9665..., and +9665... forms normalize to +9665... . No email required in the Android UI. Existing admin email login remains.
- Plate numbers are NOT automatically accepted as passwords: they are public identifiers and expose driver location. Assign each driver a private password via existing linked-account creation. A secure temporary-password/reset flow is a future enhancement.

## Validation
- Delete a pending invited user; verify no HTTP 500 and that no other accounts changed.
- Create an unused driver, link a login and vehicle, delete the driver, verify vehicle remains but unassigned.
- Verify a driver with trips cannot be individually deleted (409). Archive instead.
- Preview a disposable test company, type its exact name, delete it, verify other companies and Super Admin remain intact.
- With a linked active driver, set their phone in Drivers and use that phone and their existing password in the rebuilt Android APK.
- Rebuild APK via GitHub Actions > Build Nuqati Android APK > Run workflow. Download artifact and extract app-debug.apk.
- Do not test destructive deletion on real customer data without a verified restore.

## Not included
WhatsApp OTP and reminders are not activated; Meta Cloud API/coexistence setup and approved templates remain separate. Production hardening needs login rate limiting, audit logging, database migration tooling and tested recovery procedures.
