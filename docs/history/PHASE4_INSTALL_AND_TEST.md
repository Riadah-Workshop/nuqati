# Nuqati linked fleet dashboard + Android pilot

## Scope and limitations
This source package extends Phase 3A. Dashboard: company-scoped daily/weekly/monthly/yearly driver reports, driver filtering, trips and violation details, last-known GPS map link with timestamp, CSV export, speed threshold controls, and Super Admin-only driver account creation. Driver app: linked login, assigned vehicle, explicit foreground trip start/finish, GPS samples while app is open, and daily personal report. The pilot score starts at 100, subtracts 5 per speeding event and 4 per harsh acceleration/braking event, floors at zero; no score when there are no trips. It is illustrative, not a validated safety metric. Weekly/monthly/yearly are rolling 7/30/365-day windows; daily is rolling 24 hours, not calendar periods. Trips are counted by start time. Distance accumulation, road-specific speed limits, background tracking, offline queue, driver photo, vehicle photo, logo upload, translation editor, PDF exports and production-grade telemetry are NOT implemented. Do not represent these as complete.

## Important deployment precautions
1. Back up staging DB and verify archive exists. Also make a PostgreSQL logical pg_dump and test restoring it in a disposable database before real-user deployment.
2. Use a separate Git branch `phase4-pilot`; upload EXTRACTED ZIP contents to repository root. Do not upload ZIP as a single file. Review diffs. Do not delete the persistent PostgreSQL volume.
3. In Coolify confirm Git branch, `/compose.yml`, existing STAGING_USER, STAGING_PASSWORD_HASH, STAGING_ORIGIN, POSTGRES_USER/PASSWORD/DB, NUQATI_AUTH_SECRET. No new secrets are required. The Caddyfile includes the prior fix routing /api/* before basic auth.
4. Deploy to staging only; check `/api/v1/health` and sign in as existing Super Admin. SQLAlchemy `create_all` adds new tables `driver_accounts`, `driving_events`, `driver_locations`, `company_driving_settings` on API startup; it does NOT alter existing tables. Before production, replace `create_all` with reviewed versioned migrations.
5. Test with fictional company and driver. Assign a vehicle to the driver (existing vehicle editing). Open Fleet Reports as Super Admin, select company, configure speed threshold, create linked driver login with an email you control and a unique 12+ character password. The generic Users form's `driver` role does NOT link a driver profile; use the special link form in Fleet Reports. Never share credentials in chat or screenshots.
6. Sign in as company_admin in a separate browser. Fleet Reports should show only own company; verify another company's ID returns HTTP 403. Test reports for all drivers and one driver, each period, CSV, and map timestamp. Driver login should see only their own report. Do not invite real clients until security/privacy tests pass.

## Android build prerequisites
Install Flutter stable, Android Studio with Android SDK and platform tools, accept Android licenses. Check `flutter doctor -v`. The ZIP contains Flutter source but NOT a compiled APK, Android platform scaffold or Google Play release. On a development computer:

```
cd mobile
flutter create --platforms=android --org sa.alriadah .
flutter pub get
```

In `mobile/android/app/src/main/AndroidManifest.xml`, add OUTSIDE the `<application>` element but INSIDE `<manifest>`:

```
<uses-permission android:name="android.permission.INTERNET" />
<uses-permission android:name="android.permission.ACCESS_COARSE_LOCATION" />
<uses-permission android:name="android.permission.ACCESS_FINE_LOCATION" />
```

Do NOT add ACCESS_BACKGROUND_LOCATION for this foreground-only pilot. Set Android app label to `Nuqati Driver`. Use HTTPS endpoint accessible from the phone. Note: the Caddy staging password protects only web routes; API requests go to `/api/*` and use the driver bearer token. For an attached Android phone with USB debugging enabled:

```
flutter devices
flutter run --dart-define=NUQATI_API=https://nuqati.al-riadah.sa
```

To produce a sideloadable test APK:

```
flutter build apk --debug --dart-define=NUQATI_API=https://nuqati.al-riadah.sa
```

Install `mobile/build/app/outputs/flutter-apk/app-debug.apk` on a test device using `adb install -r build/app/outputs/flutter-apk/app-debug.apk` from inside `mobile/`, or transfer it to your own test phone and explicitly permit the install. Do not use a debug APK for Google Play. For Play closed testing, configure your own signing key, app ID, privacy policy, data safety disclosures, foreground location consent and Play Console, then `flutter build appbundle --release ...`; publishing is not automated by this ZIP.

## Pilot test procedure
Create fictional company + driver + vehicle and assign vehicle to driver. In Fleet Reports link the driver to a new login. Install app and log in. Grant foreground location permission. Start trip, keep app visible, move outdoors safely (do not operate the phone while driving), finish trip. Refresh driver and company reports. Test 403 for cross-company access. GPS speed/acceleration derived from a phone is noisy: use the data only for technical validation, not employee discipline. Current app lacks retry/offline persistence, so network errors may drop samples. The latest map pin is last recorded position, not guaranteed live. Set retention, consent, deletion and legal review before collecting real drivers' location data.
