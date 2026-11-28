# Nuqati Driver app

Flutter app for drivers (Android is the primary target; iOS builds, starts on a simulator in CI and
has a TestFlight workflow, see `docs/IOS.md`). It records trips with GPS, detects safety events (speeding, harsh
acceleration, braking and cornering), keeps an **offline queue** and syncs to the Nuqati API,
shows the driver's score, and runs the online vehicle **handover / inspection** flow.

> Status: pilot. The repository's own audits (see `docs/history/`) state that on-device
> behaviour (background GPS, battery, camera, offline replay) must be verified on physical
> phones before production use.

## What is in this folder

| Path | Purpose |
|---|---|
| `main.dart` | The app: UI, sign-in (phone / Iqama), local SQLite queue, sync, privacy mode |
| `nuqati_network.dart` | HTTPS client wrapper with an optional, domain-pinned backup host (`NUQATI_FALLBACK_API`) |
| `vehicle_handover.dart` | Vehicle receive / return inspection screens (camera, 8 photos, online only) |
| `nuqati_adaptive.dart` | Score ring, tiles and font-size limit that follow the phone's screen and font settings (tested by `test/adaptive_layout_test.dart`) |
| `nuqati_home_test.dart` | Home-screen simulator library (compiled into the app despite its name) |
| `android_camera_activity/MainActivity.kt` | Android entry point, `nuqati/native_tracking` platform channel, camera-activity observer |
| `android_native_tracking/` | Kotlin foreground tracking service and boot receiver (local SQLite) |
| `ios_native_tracking/` | Swift CoreLocation recorder and the UIScene app delegate that installs it (prepared into the generated Xcode project by `ops/ios/prepare_ios_project.py`; see `docs/IOS.md`) |
| `integration_test/` | iOS simulator start-up test run by `.github/workflows/ci-ios.yml` |
| `assets/`, `pubspec.yaml` | Launcher icon and Flutter dependencies |

The folder holds **source files only**. There is no `lib/`, `android/` or `ios/` directory:
CI generates the Flutter platform project with `flutter create`, copies these files into
`lib/` and the Kotlin package folder, and patches the Android manifest and Gradle files.
That logic lives in `.github/workflows/build-driver-release.yml` (signed AAB) and
`build-android.yml` (debug APK). Committing a standard Flutter project instead is a Phase 1
task (see `docs/DEVELOPMENT.md`).

## Build-time configuration

| Setting | Where | Meaning |
|---|---|---|
| `NUQATI_API` | `--dart-define` | API base URL. Default `https://nuqati.al-riadah.sa` |
| `NUQATI_FALLBACK_API` | `--dart-define` (GitHub variable of the same name) | Optional backup HTTPS host. Accepted **only** under `*.al-riadah.sa`, and only used for retry-safe requests |
| `NUQATI_PRODUCTION_API` | GitHub **variable** | API URL baked into the signed release AAB |
| `DRIVER_APPLICATION_ID` | GitHub **variable** | Android `applicationId` of the release build |
| `DRIVER_KEYSTORE_BASE64`, `DRIVER_STORE_PASSWORD`, `DRIVER_KEY_PASSWORD`, `DRIVER_KEY_ALIAS` | GitHub **secrets** | Upload-key signing for the release AAB |

The Kotlin sources still declare `package com.example.nuqati_driver`. That matches the
generated Gradle `namespace`, so it is not a bug, but **do not rename it casually**:
`applicationId` and the Kotlin package are separate things, and changing either affects
installed apps and the native bridge.

## Building

Use the GitHub Actions workflows (Actions → *Run workflow*). They are the only supported way
to produce APK/AAB files until the platform folders are committed. Pull requests that touch
this folder also run `ci-flutter.yml`, which generates the project and runs `flutter analyze`.

`android_native_tracking/README_NATIVE_PREVIEW.md` is an older note written before the native
service was wired into the app; treat it as historical until it is reviewed.
