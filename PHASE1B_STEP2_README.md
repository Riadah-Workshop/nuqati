# Nuqati Phase 1B — Step 2 (Android pilot)

## Files to replace
- `mobile/main.dart`
- `mobile/pubspec.yaml`
- `.github/workflows/build-android.yml`

## Prerequisite
Deploy and test the Phase 1B Step 1 backend update first. It accepts `sample_id` and `captured_at` and permits ~1-second samples. Do not deploy this Android update against the old backend.

## What this pilot does
- Uses a foreground location service to receive GPS updates with 0 m distance filter, targeting approximately one per second when Android provides them.
- Saves each valid fix in SQLite before uploading, with a stable sample ID and GPS capture time.
- Retries queued samples in chronological order on connectivity recovery, 30 records per pass, every five seconds.
- Preserves the Phase 1A Remember Me login and uses encrypted token storage for service uploads.
- Stops a trip only when its queued samples have synced; otherwise displays a message to reconnect.

## Permissions
Android may require you to manually enable **Allow all the time** location access in App Info > Permissions > Location. Also allow notifications and disable restrictive battery optimization for this pilot. On Android 13+ notification permission may need an explicit user grant in system settings. The workflow adds manifest permissions, but the app does not yet provide an in-app permission wizard.

## Known limitations — important
- Flutter/Android APK build has NOT been executed here. Test in GitHub Actions before field rollout.
- GPS delivery is OS-dependent; exactly 1 fix every second cannot be guaranteed.
- This foreground service can be terminated by Android, battery restrictions or user Force Stop; it is not tamper-proof.
- Queued data remains on device until successfully uploaded; no cleanup policy or server-side bulk endpoint yet.
- A trip cannot be finished offline in this pilot. This protects against dropping queued data, but offline stop is a later enhancement.
- If Remember Me is unchecked, restarting the entire app may require re-login; the current active service can continue during the session.
- No locked-screen violation notification or automatic service recovery after device reboot in this update.
- This is an experimental pilot. Test on at least two Android versions with airplane mode, locked screen, app swiping, reconnect and trip finish.

## Test sequence
1. Back up your database and deploy backend Step 1.
2. Upload these three files to GitHub; run Android workflow; resolve any build issues before installing.
3. On a spare test phone, grant location and notification permissions.
4. Start trip outdoors, lock screen for 3 minutes, unlock; verify new GPS points on Fleet Reports.
5. Repeat in airplane mode for 2 minutes, reconnect and wait for synchronization.
6. Check that timestamps and distances remain correct and no duplicate points appear.
7. Stop trip only after queue has emptied.
