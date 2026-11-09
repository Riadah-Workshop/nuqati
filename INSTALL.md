# Nuqati mobile GitHub Actions builds

Upload the two workflow files to the exact repository paths:
- `.github/workflows/build-android.yml`
- `.github/workflows/build-ios.yml`

Use the `main` branch and keep the `.github` folder at repository root, NOT inside `mobile`.

Go to GitHub > Actions > Build Nuqati Android APK > Run workflow > Run workflow. Once green, open the run and download the `nuqati-android-iqama-pilot` artifact. Extract `app-debug.apk` and install on a test Android device.

For iOS, GitHub > Actions > Build Nuqati iOS Simulator > Run workflow. Download `nuqati-ios-simulator-iqama-pilot`. This produces a macOS Xcode Simulator app, NOT an installable iPhone IPA. A physical iPhone build/TestFlight needs an Apple Developer account, signing certificate, provisioning profile, bundle identifier and appropriate distribution setup.

The app needs the updated Phase 6 backend deployed before Iqama login can work. It tracks location only while the app is active, not in the background. Do not delete the existing database or Coolify volumes.
