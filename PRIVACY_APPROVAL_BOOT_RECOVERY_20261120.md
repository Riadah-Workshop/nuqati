# Nuqati privacy approval and boot recovery (2026-11-20)

## Included
- `POST /api/v1/mobile/privacy-request` authenticated driver asks for privacy; request remains pending and GPS continues.
- `GET /api/v1/mobile/privacy-request/status` is checked on app session start, resume and every 30 seconds while UI runs.
- Admins in the Privacy Audit screen can approve/reject requests and revoke active permission. Company scoping is enforced by the API.
- After approval the Driver app verifies there is no local or native active trip, acknowledges activation and only then switches the native tracking service off. Activation never happens while a trip is running.
- Driver can turn Privacy Mode off immediately even offline. A server disable is retried when online.
- Permission reminder checks every five minutes while the app UI is running and when it resumes. Android may require the user to grant Always in system settings; this cannot be silently changed by the application. Warnings are rate-limited.
- Android boot receiver restarts native GPS foreground service when the phone reboots or app is updated **if** an authenticated driver/vehicle owner is stored, privacy is off, and Always location is granted.

## Critical platform limitations
- Android can block starting a location foreground service from BOOT_COMPLETED (especially newer OS versions) or after an explicit force-stop. Manufacturer battery restrictions may also prevent restart. Therefore no Android app can guarantee detection of all trips after every reboot. Check actual behavior on target Samsung/Xiaomi/other devices.
- During complete power-off there is no GPS data; it cannot be reconstructed.
- Administrative approval/revocation is synchronized while the Driver UI runs or is next resumed. No guaranteed background server poll is implemented here: approval does **not** instantly stop recording if the app is never brought to foreground, and revocation likewise takes effect on reconnection. This conservative behavior favors tracking until verified.
- Native privacy approval is protected by an in-process authorization flag but is not a cryptographic signature. Deploying stronger signed approval tokens is advisable for a hardened threat model.

## Deployment
1. Back up Postgres and deploy the updated backend (new table created additively at startup).
2. Deploy the updated web dashboard.
3. Build and roll out a **new Driver AAB** using `.github/workflows/build-driver-release.yml` (or build-android). Native boot receiver changes require a new app build; redeploying the dashboard alone does not update the driver app.
4. No Manager app build is needed for this change.

## Acceptance tests (manual on physical Android phone)
1. Start normal tracking; request privacy. Assert native GPS remains active and no privacy evidence says ON.
2. Company A admin sees company A request; company B cannot approve it; approve and verify driver app activates only after trip ends.
3. Reject and revoke; confirm app resumes tracking when status is synchronized.
4. Disable privacy while offline; immediately resume native monitoring, then reconnect and check server end status.
5. Change permission from Always to While Using and resume: check prompt; restore Always.
6. Restart phone with Wi-Fi/mobile data off and location Always granted: check foreground notification and locally captured trips after unlock. Repeat with phone location disabled, privacy ON, driver logged out, battery saver, and force-stop.
7. Check GPS, scoring, uploads and trip IDs after normal operation; none of their thresholds were intentionally changed.

## Validation performed in this environment
Python backend `py_compile` and `compileall` passed. Web build could not run: npm packages not cached offline. Flutter/Android SDK unavailable; CI build plus on-device testing are necessary before production deployment.
