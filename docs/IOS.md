# Nuqati on iOS (driver and manager apps)

This is the working note for putting the two Flutter apps on iPhones. It says what exists, what CI proves, what only a real iPhone
can prove, and exactly what you have to do on the Apple side. Last updated with Phase 5.9 (see `CHANGELOG.md`).

## 1. Where things stand

| Part | State |
|---|---|
| Both apps build for iOS | Yes. `ci-ios.yml` builds the driver and the manager for the iOS simulator on every pull request that touches them. |
| Both apps **start** on iOS | Yes, proven by the same job: it boots an iPhone simulator, starts each app and checks that it reaches its sign-in screen. |
| Driver: tracking channel and plugins | Proven on the simulator: the native recorder answers on its channel, secure storage works, the permission plugin has location permissions compiled in. |
| Driver: tracking itself (GPS in the background, screen locked) | **Written, never run on an iPhone.** A simulator cannot test it. See section 5. |
| Signed build to TestFlight | Workflow written (`release-ios.yml`), **not run**: it needs your Apple account (section 2). |
| App icon | A 1024 x 1024 opaque icon redrawn from the existing mark (`assets/nuqati_icon_ios.png`). Replace it with a designer's artwork when you have one. |
| App Store listing | Not started (section 6). |

Bundle identifiers: `sa.alriadah.nuqati.driver` and `sa.alriadah.nuqati.manager`. Names shown on the phone: *Nuqati Driver*, *Nuqati Manager*.
Override with the GitHub variables `IOS_DRIVER_BUNDLE_ID` / `IOS_MANAGER_BUNDLE_ID` **before the first upload** (a bundle id cannot change afterwards).

## 2. What you have to do on the Apple side (once)

Nothing here can be done by me: it needs your Apple account.

1. **Join the Apple Developer Program** (developer.apple.com/programs/enroll). For a company, choose *Organization*: Apple asks for a
   D-U-N-S number and checks that you can act for the company, which can take days to weeks. An *Individual* account is quick but the
   apps then carry a person's name as the seller. Do this first; everything else waits for it.
2. **Create the app records.** App Store Connect > Apps > **+** > New App: platform iOS; name *Nuqati Driver* (App Store names are
   unique worldwide: if taken, add a word, e.g. *Nuqati Fleet Driver*; this is the store name, the icon label stays *Nuqati Driver*);
   primary language; the bundle id from the list (it appears there after step 3's first run, or register it first under
   developer.apple.com > Certificates, Identifiers & Profiles > Identifiers > **+** > App IDs > App); SKU = any text, e.g. `nuqati-driver`.
   Repeat for the manager.
3. **Create an API key** for GitHub: App Store Connect > Users and Access > Integrations > App Store Connect API > Team Keys > **+**.
   Name: *GitHub Actions*. Access: **Admin** (Xcode needs it to create the signing certificate and profile for you). Download the
   `AuthKey_XXXX.p8` file **now** (Apple shows it once) and note the **Key ID** (shown in the table) and the **Issuer ID** (shown above it).
4. **Find your Team ID:** developer.apple.com > Membership details > Team ID (10 characters).
5. **Give GitHub the four values:** repository > Settings > Secrets and variables > Actions > New repository secret:

   | Secret | Value |
   |---|---|
   | `APPLE_TEAM_ID` | the Team ID |
   | `APPSTORE_KEY_ID` | the Key ID |
   | `APPSTORE_ISSUER_ID` | the Issuer ID |
   | `APPSTORE_API_KEY_P8` | the whole text of the `.p8` file, including the BEGIN/END lines |

   The manager release also uses `MAPTILER_API_KEY`, which already exists for the Android manager release.
   The `.p8` key is a secret. The repository is public: never paste it anywhere else, and revoke it in App Store Connect if it leaks.

## 3. Releasing to TestFlight

Actions > **Release Nuqati iOS to TestFlight** > Run workflow: choose the app and the version (e.g. `1.0.0`). The build number is the run number,
so each upload is higher than the last (Apple rejects a repeat). The workflow builds, signs (automatically, through the API key) and uploads
straight to App Store Connect. Nothing is stored in this public repository. If a secret is missing it stops at the first step and names it.

Apple then processes the build (usually 5 to 30 minutes) and it appears under App Store Connect > your app > **TestFlight**.

* **Internal testers** (people with a role in your App Store Connect team, up to 100): add them to a group; no Apple review. They install
  the *TestFlight* app on the iPhone and accept the invitation. Use this for the pilot.
* **External testers** (anyone, by email or link): the first build of each version goes through Apple's *Beta App Review*.
* TestFlight builds expire after 90 days; upload a new one before that.

For a build you can only test in Xcode on a Mac, *Build Nuqati iOS (simulator and unsigned device)* produces the simulator app and an unsigned
device app (a draft release; not installable by itself).

## 4. What CI checks on every change (`ci-ios.yml`)

On a macOS runner, for the driver and the manager: generate the Xcode project, apply `ops/ios/prepare_ios_project.py`, build for the
simulator, start the app on an iPhone simulator and run `integration_test/ios_smoke_test.dart`. The driver's test checks that plugins are
registered, that the native CoreLocation recorder answers on `nuqati/native_tracking`, that the `permission_handler` location permission is
compiled in, and that the sign-in screen appears. A compile alone proved little here: the first version of this project compiled and would
have started, but its app delegate never installed the tracking channel (Flutter 3.41+ starts iOS apps differently).

`prepare_ios_project.py` refuses a generated project it does not understand, so a future Flutter template change fails the build with a message
instead of shipping an app that starts but does not track.

## 5. What only a real iPhone can prove (do this on the first TestFlight build)

Use one iPhone, a driver account, and a short drive. Keep the phone's *Settings > Nuqati* open to compare.

1. First launch: the location questions appear; choose *Allow While Using*, then when asked choose **Change to Always Allow**. Notifications: Allow.
2. Settings > Nuqati: Location = **Always**, Precise Location = On, Background App Refresh = On. (*Check tracking permissions* in the app shows the same.)
3. Start driving with the screen **locked** for 10 minutes. A blue bar / pill shows that Nuqati uses location in the background.
4. Open the app afterwards: the trip is there with a track and points; in the web dashboard the trip appears with its points.
5. Force-quit the app (swipe it away) and drive again: **iOS does not restart a force-quit app**; tracking resumes only when the driver opens it.
   This is an iOS rule, not a bug. Drivers must be told not to swipe the app away.
6. Handover: take the 8 photos (camera permission appears the first time).
7. Arabic and Urdu: text is right-to-left and the score ring, tiles and buttons fit (the layout fixes in Phase 5.8 apply to iOS too).
8. App Diagnostics (bug icon): send it after the drive; the `GPS_NATIVE_*` / `TRIP_NATIVE_*` lines show what the phone recorded (`docs/OPERATIONS.md` section 11).

Send me the diagnostics and screenshots of anything odd. iOS background behaviour differs by model and iOS version, so expect a round or two of fixes.

## 6. App Store review and distribution (when you go beyond TestFlight)

* **Distribution choices**: a normal public App Store listing; *Unlisted App Distribution* (only people with the link); *Custom Apps* through
  Apple Business Manager (private to named organizations); or TestFlight only. A fleet app for your own customers' drivers usually fits
  *unlisted* or *custom*; decide before filling the listing.
* **Review needs a demo login.** Apple tests the app with real credentials: prepare a demo company and driver account that stays valid and
  put the Iqama/ID and password in *App Review Information*. Without it the app is rejected.
* **Why the app asks for Always location** (paste into *App Review Information > Notes*, adjust as needed): *"Nuqati Driver is used by drivers of
  fleet companies. It records each driving trip automatically, including with the screen locked, to calculate driving-safety points and show the
  fleet manager the trip route. Location is used only while the driver is signed in, and only for the fleet company he works for. The driver can ask
  for Privacy Mode, which pauses tracking when the fleet company approves it."*
* **A privacy policy page with a public URL** is required for the listing. `docs/PRIVACY_SECURITY.md` is internal; the policy must be published on
  a web page.
* **App Privacy ("nutrition label") answers** to start from, to be confirmed with your policy: Precise Location (collected, linked to the user,
  not used for tracking, purpose App Functionality); Photos (vehicle handover photos: same answers); Contact/Identifier info (name, Iqama/ID,
  phone as used for sign-in); Diagnostics (App Diagnostics, if uploaded). The app does not track users across other companies' apps or websites.
* **Account deletion.** Apple requires in-app account deletion only for apps where people create accounts in the app. Here managers create the
  driver accounts, so it is not triggered; if you add self-registration it will be.
* **Encryption export question**: answered by `ITSAppUsesNonExemptEncryption = false` in the app (only standard HTTPS is used).
* Apple requires builds made with the current Xcode / iOS SDK (the GitHub macOS runner image provides it) and, from iOS 27 builds on, the UIScene
  lifecycle, which this project already uses.

## 7. Known limits and what is not verified

* **Never run on a real iPhone.** CI proves build, start-up and wiring on a simulator (section 4). Background tracking, the permission
  dialogs on a real device, camera and notifications are unproven until section 5 is done.
* **`release-ios.yml` has not run** (no Apple account yet). Its first run is its first test; the usual first-time failures are a wrong Team ID,
  an API key without *Admin* access, or a bundle id that is not registered. The error text from Apple is printed in the log.
* **No relaunch after the system ends the app.** The recorder keeps the app alive with continuous location updates, which is the supported
  way for a trip-recording app; iOS may still end it under memory pressure. Adding *significant-location-change* monitoring would let iOS
  relaunch it; not done because it cannot be tested without a device. A force-quit app is never relaunched by iOS.
* **No remote push notifications** (APNs): alerts are local notifications generated on the phone, as on Android.
* **Google Play in-app updates are Android only**; iOS updates come through TestFlight / the App Store.
* The icon is a redraw of the existing mark; the screenshots, description, keywords and age rating for a store listing do not exist yet.

## 8. How the pieces fit

| Path | Purpose |
|---|---|
| `ops/ios/prepare_ios_project.py` | Prepares a freshly generated Xcode project (plist, bundle id, Podfile macros, app delegate, privacy manifest). Tested in `backend/test_ios_prepare_project.py` against the real generated files in `ops/ios/fixtures/`. |
| `.github/actions/ios-project/action.yml` | The one place that generates and prepares the project; used by all three iOS workflows. |
| `.github/workflows/ci-ios.yml` | Pull-request check: build and start both apps on a simulator. |
| `.github/workflows/build-ios.yml` | Manual: simulator app and unsigned device app (driver or manager). |
| `.github/workflows/release-ios.yml` | Manual: signed build to TestFlight. |
| `driver_app/ios_native_tracking/` | The Swift CoreLocation recorder and the app delegate that installs it. |
| `driver_app/integration_test/`, `manager_app/integration_test/` | The simulator start-up tests. |
| `ops/ios/make_ios_icon.py`, `*/assets/nuqati_icon_ios.png` | The 1024 px opaque icon (Apple rejects transparency). |
| `ops/ios/PrivacyInfo.driver.xcprivacy` | Apple's privacy manifest for the driver (location and photos collected, UserDefaults reason). |
