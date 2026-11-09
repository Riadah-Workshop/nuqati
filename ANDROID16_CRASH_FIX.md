# Android 16 foreground-service notification crash fix

Changes:
- Create `nuqati_active_trip` Android notification channel before configuring the background service.
- Add `flutter_local_notifications` dependency for channel creation.
- Generate an explicit drawable resource `ic_bg_service_small.xml` for the foreground-service notification in GitHub Actions.

The fix targets `CannotPostForegroundServiceNotificationException` / `Bad notification for startForeground` observed when Start Trip launches the background service. It has not yet been verified on the affected Samsung device. Build using GitHub Actions, install the new APK, and check Start Trip, notification visibility, background tracking, and Stop Trip. If a crash remains, inspect the exact Android logcat notification error.
