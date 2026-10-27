Nuqati offline tracking / driver notifications — TEST BUILD ONLY

Replace the files at the matching paths in GitHub. This patch is based on the last source ZIP uploaded and the previous Android 16 notification patch; newer unshared GitHub changes may be overwritten.

Changes:
- Start Trip creates a local SQLite trip record without contacting the server.
- Stop Trip marks it ended locally and does not require network.
- The background service attempts to create the server trip, upload queued samples, and finish it in order.
- Speeding, harsh braking and harsh acceleration trigger local Android notifications from the GPS background isolate (12-second cooldown). The thresholds are read from the last cached server driving policy, falling back to defaults.
- Reconnection retries happen in the foreground service and on app resume.

IMPORTANT LIMITATIONS — do not roll out to drivers yet:
- This source has NOT been compiled or device-tested here.
- The backend /trips/start endpoint does not yet support an idempotency key. If the server creates a trip but the response is lost, retries can create duplicate server trips. Backend idempotency must be added before production.
- A previous active trip from the old app version may need to be finished on the server before testing this patch.
- Notifications require Android notification permission; sound/vibration depend on user settings.
- GPS-based acceleration is noisy; thresholds and filtering need real-road validation.
- The current background service may remain active while waiting to sync; review battery and Android background policies.
- If the device is rebooted or Android force-stops the service, automatic recovery is not guaranteed until app launch.
- Background notifications are not the same as reliable violation scoring: backend scoring and local alerts may differ.

TEST PLAN
1. Backup the existing repository and app data. Do not uninstall the app if you have unsynced trips.
2. Build with GitHub Actions, install on test phone, grant location and notification permissions.
3. Start a trip with Wi-Fi and mobile data off; confirm local tracking notification and local GPS capture.
4. Stop while offline; verify Stop succeeds. Restore connectivity and open app to trigger sync.
5. Check server trip count, timestamps, samples and finish status; ensure no duplicate trip.
6. Test alert notifications in controlled/safe conditions, not by intentionally driving dangerously.
7. Repeat with screen locked, connectivity changes, and after app restart.
