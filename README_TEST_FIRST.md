# Nuqati combined patch — TEST FIRST

Source baseline: nuqati-main(20261027-151259).zip

Modified files only:
- backend/app/main.py
- mobile/main.dart

## Included
- Automatic trip detection in a foreground location service while Nuqati is not visible, after the driver has logged in and enabled tracking. Starts at GPS speed >5 km/h continuously for 5 seconds; stops at <1 km/h for 120 seconds. GPS accuracy must be <=35 m.
- Driver UI Start/Stop Trip button replaced with Full Privacy Mode toggle. Privacy ON stops location capture, movement detection, and scoring. Only manually turning Privacy OFF restarts monitoring. Privacy setting is stored persistently.
- Trip completion notification invites driver to open Nuqati to see score.
- GPS trip distance added to the assigned vehicle odometer once, on server-side trip completion. A manual initial odometer is required; if no initial reading is set, it remains null. Odometer reading history records each trip.
- Maintenance reminders for assigned vehicle: engine oil 1000 km left, 500 km left, due; spark plugs and gear oil 1000 km left, due, 1000 km overdue. One notice per schedule cycle and stage, persisted locally. Driver app checks API every 2 minutes while foreground monitoring service is running and connected.
- No dashboard changes required for the existing maintenance schedule entry: next due km = last_service_km + interval_km. For first-ever service due at 60000, enter last_service_km=0 and interval_km=60000; after servicing update last_service_km and interval.

## Deployment
1. Back up PostgreSQL and save working APK. Do not uninstall app with pending offline trips.
2. Replace these exact paths in your repo; redeploy backend first, then build Android APK.
3. On Android allow notifications, precise location, **Allow all the time** location, and unrestricted battery usage. The existing GitHub Actions Android manifest already declares background location and foreground location service permissions.
4. Sign in and confirm Privacy Mode OFF. Test automatic trip creation/stop, score notice, offline synchronization, and odometer increment exactly once.
5. Test maintenance thresholds with a test vehicle. Check that toggling Privacy ON immediately stops location monitoring; turning OFF explicitly resumes it.

## Known limitations / important
- This patch has NOT been compiled with Flutter or tested on a phone; Python syntax validated only. Run CI and test in staging before production.
- Android can stop background execution for battery policy, and a user force-stop prevents automatic restart until manually opened. Foreground service and boot restart do not guarantee tracking after force-stop. Starting a location foreground service from a background-only context is subject to Android version and permission restrictions.
- While Full Privacy is ON, NO movement reminders are generated, by design. Maintenance notifications are also paused until tracking resumes.
- Maintenance notifications are local, not server push; they require the monitoring service to be alive and connectivity for the reminder API.
- This is an incremental source patch, not a signed APK or production certification.
- Historical trips completed before this patch are not backfilled to odometer. A manually set starting odometer is required.
- GPS distance is estimated, not a certified mechanical odometer; validate accuracy before using for critical maintenance decisions.
