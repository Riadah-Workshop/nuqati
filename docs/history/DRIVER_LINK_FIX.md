# Driver account linking hotfix

This patch adds a dashboard control under Drivers to associate an existing driver-role login with an existing driver profile and optionally assign a same-company vehicle. It uses the existing `driver_accounts` and `vehicles.assigned_driver_id` columns. It does not delete or recreate database records and does not require a new APK.

1. Back up your staging PostgreSQL database before deployment.
2. Replace the repository files with this patch, commit to `main`, then redeploy the existing staging Coolify service. Preserve existing environment variables, domains and persistent Postgres volume.
3. Sign in as Super Admin or Company Admin. Open Drivers, choose the existing login and vehicle for the correct driver, and click Save link. If a login is already linked to another driver or a vehicle is assigned to someone else, the API rejects the request rather than silently reassigning it.
4. Close and reopen the current Android pilot APK; sign in with the same driver credentials. The driver name and assigned plate should appear.

This patch deliberately does NOT enable WhatsApp OTP or remove driver email login. Those changes require verified official API onboarding, approved authentication templates and a separately tested migration.
