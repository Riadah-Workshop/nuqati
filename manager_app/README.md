# Nuqati Manager app

Flutter app for company administrators and fleet managers (Android): fleet and vehicle
overview, live positions on a map, trip history, maintenance reminders and driver
performance. It signs in with the **same email and password as the web dashboard**.

## What is in this folder

| Path | Purpose |
|---|---|
| `main.dart` | The whole app (UI, API client, Arabic/English labels, notifications) |
| `pubspec.yaml` | Dependencies (`flutter_map`, `http`, `flutter_secure_storage`, local notifications) |
| `assets/nuqati_icon.png` | Launcher icon |

As with the driver app, only source files are committed. CI runs
`flutter create --platforms=android --project-name nuqati_manager --org sa.alriadah .`,
copies `main.dart` into `lib/` and patches permissions and desugaring.

## Build-time configuration

| Setting | Where | Meaning |
|---|---|---|
| `NUQATI_API` | `--dart-define` | API base URL. Default `https://nuqati.al-riadah.sa` |
| `MAPTILER_API_KEY` | GitHub **secret** → `--dart-define` | Map tiles. Restrict the key to this app in the MapTiler dashboard |
| `MANAGER_KEYSTORE_BASE64`, `MANAGER_STORE_PASSWORD`, `MANAGER_KEY_PASSWORD`, `MANAGER_KEY_ALIAS` | GitHub **secrets** | Upload-key signing for the release AAB |

The release `applicationId` is `sa.alriadah.nuqati.manager`.

## Building

* `build-manager-android.yml`: debug APK, runs on pushes to `main` that touch `manager_app/`.
* `build-manager-release-fixed-version.yml`: signed AAB for Google Play internal testing.
  Run it manually and give a Play `version_code` higher than every previous upload.
* Pull requests that touch this folder also run `ci-flutter.yml` (`flutter analyze`).
