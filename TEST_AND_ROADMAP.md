# Nuqati: privacy evidence patch (staging)

Baseline: nuqati-main(20261027-153646).zip.

## What this patch actually implements
- Append-only server privacy evidence for driver toggles, including event ID, driver/company/assigned vehicle, selected timestamp and server received timestamp.
- Local SQLite queue for privacy events, with retry on app resume/login and after a toggle. It works offline and deduplicates by event ID.
- Scoped read API: GET /api/v1/privacy-audit for authorized company roles (super_admin can see all).
- Privacy evidence contains no GPS coordinates, routes, or speed. Full Privacy Mode behavior remains from the supplied baseline.

## Deployment
1. Back up database and current working APK.
2. Replace backend/app/main.py and mobile/main.dart from this ZIP, keeping their relative paths.
3. Deploy backend first; verify health and POST /api/v1/mobile/privacy-evidence with a driver token.
4. Build Android APK with your existing GitHub Actions workflow, then install as an update (do not uninstall with unsynced trips).
5. Enable privacy online, disable privacy online, enable privacy offline, disable privacy offline, reconnect and reopen app. Confirm four unique events via GET /api/v1/privacy-audit under an authorized account.
6. Verify no GPS samples are recorded while privacy is enabled, including after reboot. Confirm tracking resumes only after manual disable.

## Limits / not yet implemented
- This is not a verified APK build: Flutter SDK/device/backend database are not available in this environment.
- This patch does NOT implement cornering detection, geofencing or zone-specific speed limits, or new risk classification logic. The baseline already contains global company speed limits, English/Arabic UI and SAFE/CAUTION/HIGH RISK score labels. These should be designed and tested in a separate patch before being counted as delivered.
- Audit is proof that the authenticated app recorded a toggle; it is not cryptographic proof of physical driving, GPS absence, or user intent. A compromised phone can affect client timestamps. Server received_at is independent.
- A pending privacy audit only uploads when the signed-in app reconnects; device data deletion before synchronization loses pending events.
