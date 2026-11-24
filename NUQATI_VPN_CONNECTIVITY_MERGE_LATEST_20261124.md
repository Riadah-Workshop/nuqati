# VPN connectivity update merged into the latest Nuqati upload

**Authoritative source:** `nuqati-main(20261124-074216).zip` (uploaded on 24 November 2026).  
**Purpose:** Apply the previously requested VPN connectivity policy without rolling back changes in the latest upload.

## What was merged

- Driver app: Nuqati HTTPS health check every **60 seconds when the server is unreachable**; automatic resumption of the existing authenticated heartbeat and acknowledged local trip upload queue when communication returns; exponential retry delay capped at **300 seconds including jitter**.
- Native Android: VPN route diagnostic booleans (`vpn_active`, `internet_capability`, `validated`); `ACCESS_NETWORK_STATE` added in both Android build workflows.
- Backend: authenticated 60-second v2 heartbeat policy, persistent company-scoped disconnected-driver incidents after **15 minutes** of missed heartbeats, incident resolution when service resumes, and SMTP email attempt for company admins and fleet managers.
- Web dashboard: list active connection alerts in the currently selected company; maintain company-based access controls.
- Unsent local GPS data, trip ownership, privacy approval, location collection, and single-device session protections have **not** been removed or bypassed. VPN routes remain controlled by Android / the VPN app.

## Files changed relative to the uploaded ZIP

1. `.github/workflows/build-android.yml`
2. `.github/workflows/build-driver-release.yml`
3. `backend/app/main.py`
4. `backend/app/connectivity_alerts.py` (new)
5. `backend/test_vpn_connection_alerts.py` (new)
6. `mobile/android_camera_activity/MainActivity.kt`
7. `mobile/main.dart`
8. `web/src/App.tsx`
9. `NUQATI_VPN_CONNECTION_RECOVERY_20261124.md` (new)
10. `NUQATI_VPN_CONNECTIVITY_MERGE_LATEST_20261124.md` (new)

All other source files match the uploaded ZIP. A pre-existing `__pycache__/main.cpython-313.pyc` binary was excluded because it is a generated Python cache (not source). No feature source was removed.

## Verification performed

- `24 passed` targeted tests for VPN alert policy, driver sessions, native tracking contracts and security checks.
- Wider backend regression suite: `33 passed, 1 skipped, 5 errors`; the five errors are from the pre-existing `test_company_one_page_editor.py` contract requiring `_validate_company_driver_logo` absent from the supplied upload, not from the VPN patch.
- Python source compile checks passed for the modified backend modules.
- TypeScript JSX syntax parse passed for `web/src/App.tsx`.
- Flutter/Dart compiler and complete npm dependency production build were **not** available locally. These need CI confirmation before rollout.

## Deployment

1. Apply the **modified-files-only** ZIP using its exact directory structure, or use the **complete merged source** ZIP; do not mix versions.
2. Redeploy the **backend and web** in Coolify. Backend uses additive PostgreSQL changes on startup. Ensure its SMTP environment variables are configured if email alerts are needed.
3. Build the **Driver Android** app using GitHub Actions and install the new version on phones. The Manager Android app does not require rebuilding for these email/dashboard alerts.
4. Test an active driver with VPN working, VPN blocking this Nuqati domain, and VPN recovery. A persistent VPN block cannot be bypassed by the app.
5. The 15-minute policy begins after the updated Driver app sends a v2 heartbeat, to avoid false alarms from older idle installations.

See `NUQATI_VPN_CONNECTION_RECOVERY_20261124.md` for detailed test steps and limitations.
