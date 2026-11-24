# Nuqati native tracking — integration preview (NOT production ready)

This is the first **native service foundation**, based on `nuqati-main(8).zip`. It is not a drop-in replacement for the existing Flutter tracker.

The Kotlin service independently records GPS fixes and auto-detected trips to `nuqati_native_tracking.db`, detects offline safety events with cached company thresholds, and posts local Android alerts. It does not upload data. The Flutter app's existing GPS engine, scoring, and upload queue are unchanged; enabling both at once would cause duplicate trip/event detection.

## Current integration status

- Native service and local SQLite storage: implemented, not compiled on an Android device.
- Native start/stop/privacy/policy channel: provided through MainActivity.
- GitHub Actions integration: copies Kotlin source and declares service in manifest.
- Flutter-to-native policy synchronization: provided for online policy fetch.
- **Not implemented:** Flutter UI switch to make native service the sole tracking engine, migration of native SQLite trips/events into existing upload schema, native-to-Flutter live updates, native boot restart, release-grade GPS quality tests, per-driver policy isolation, or real-device battery benchmarking.

**Do not enable this native service alongside the existing Flutter tracking engine in production.** It is intentionally not auto-started. To test it independently in a debug harness, invoke MethodChannel `nuqati/native_tracking` method `start` after permissions are granted and the legacy Flutter tracker is stopped. Methods: `start`, `stop`, `privacyOn`, `privacyOff`, `setPolicy` (JSON string), `status`. `status` reports the native SQLite active trip and pending sample/event counts.

## Acceptance gates before replacing current app

1. Android debug APK builds on both GitHub Actions workflows.
2. Locked screen and offline 30-minute drive: native database continues recording.
3. GPS spoofing/indoor tests do not produce false trips or violations.
4. Native policy cached per authenticated company and verified offline after process restart.
5. Single engine only; no duplicate trips or events; native records migrate reliably to existing sync queue.
6. Privacy Mode stops native GPS immediately; logged-out user cannot retain another driver's policy.
7. Compare battery use and event accuracy on Samsung Android 16 against current app.

No APK/AAB or deployment validation was performed here.
