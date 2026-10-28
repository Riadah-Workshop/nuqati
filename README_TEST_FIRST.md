# Nuqati – Offline sessions and separate offline trips
Baseline: nuqati-main(20261028-044621).zip

## Modified files
- backend/app/main.py
- mobile/main.dart

## Deploy order
1. Back up staging PostgreSQL and working Android APK. Do not uninstall the existing APK; SQLite pending trips are stored on-device.
2. Replace backend/app/main.py and deploy API to Coolify; verify /api/v1/health.
3. Replace mobile/main.dart and build APK through the existing GitHub Actions workflow.
4. Install over the existing application, retaining app data.

## Offline sign-in behavior
- Complete one ONLINE login with Remember me selected before disconnecting.
- The driver profile and access token are stored in encrypted storage.
- When app restarts offline, it restores this saved session without calling the API first.
- Fresh accounts, manual logout, or unremembered sessions cannot log in offline.
- When access token expires/revoked, API synchronization requires online reauthentication. Local restoration does not bypass server authorization.

## Test scenarios
A. Online sign-in with Remember me; force-close normal app, disconnect internet, relaunch; confirm profile and auto monitoring appear.
B. Remain offline. Drive Trip A, stop stationary for 2 min; drive Trip B, stop 2 min; repeat Trip C. Confirm 3 local trips; do not enable privacy during these tests.
C. Restore internet; allow service to synchronize; confirm 3 separate dashboard trips, original start/end times, and odometer increases only once per completed trip.
D. Interrupt internet during start request and reconnect. Confirm client trip ID prevents duplicate server trip creation.
E. Enable Full Privacy Mode; confirm no GPS samples recorded, and disabling privacy resumes monitoring.
F. Test revoked/expired token: device can show cached profile, but sync must fail until online login; do not assume server authentication remains valid.
G. Confirm driver with no vehicle assigned cannot create server trips; backend returns 409.

## Important known limitations
- Android force-stop prevents background services until user launches the app again.
- Existing legacy server active trips may need manual reconciliation; the API deliberately returns 409 rather than silently merging two offline journeys.
- This patch does NOT implement new cornering, geofencing, road-specific speed-limit policies, or risk classification. Those need separate design and tests.
- This patch is source-validated for Python only. Flutter toolchain and live PostgreSQL integration were unavailable; staging build and field validation are required.
- Local remembered sessions should be paired with a device-lock policy for shared phones; a stolen unlocked device can expose cached driver data.
