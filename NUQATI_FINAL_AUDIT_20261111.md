# Nuqati — November 11, 2026 final ZIP audit & narrowly scoped corrections

**Input:** `nuqati-main(20261111-161648).zip`. These changes are additive/narrowly scoped; they do not remove any source file, tracking module, historical trips, manager app, or web screen.

## Confirmed findings and applied corrections

1. **Critical, APK/AAB build:** `mobile/main.dart` imports `vehicle_handover.dart`, but neither driver Android workflow copied it into the generated Flutter `lib/` folder. Both workflows now assert that the source exists, copy it to `lib/vehicle_handover.dart`, and fail early with a descriptive message if absent. iOS simulator workflow now also copies the real app and handover screen instead of building Flutter's template entry point; it adds a camera usage description.
2. **Critical, assignment return/sync:** After an online return the `/mobile/me` response has no vehicle. Existing `persistRecordingOwner()` sent `vehicle_id: 0` to the Android bridge, which rejects non-positive vehicles. This could leave the old vehicle in native recording state. The app now invokes the existing `clearRecordingOwner` method when the server confirms no assigned vehicle, preserving native trip-start protection.
3. **Onboarding design mismatch:** Driver creation required a vehicle to be assigned by a manager, so newly onboarded drivers could not exercise one-time plate selection in the driver app. The API and web dashboard now allow an **optional** initial vehicle. Existing create-with-vehicle behavior still works unchanged; unassigned drivers select a plate online with the initial vehicle inspection.
4. **Inspection integrity:** The return comparison accepted an item labeled `existing` even when no matching area and damage type appeared in the receipt baseline. Such new/previously unrecorded damage now triggers supervisor review regardless of the driver's label; no automatic driver blame is inferred.
5. **Web data freshness:** Handover lists, pending approvals and details previously updated only after a manual refresh or an action. The handover page now polls the API every 30 seconds while visible, and keeps user notices intact on silent refreshes.
6. **Driver approval freshness:** While the handover screen is open and pending supervisor action, it now checks the API every 20 seconds. An approved online handover triggers the existing verified Flutter/native ownership refresh. Background/force-closed approval delivery is not claimed or implemented.
7. **User confirmation:** A successful online handover previously displayed its success message and then immediately cleared it on `refresh()`. Confirmation is now shown after refreshing; a successful server POST is not mistaken for a failed handover when local identity refresh fails.
8. **Test runner:** Static native-contract test incorrectly resolved the repository root (`parents[2]`); corrected to `parents[1]`.

## Automated checks executed

- Source ZIP CRC test: passed.
- Backend Python compileall: passed.
- Backend tests: **18 passed**, including clean receive/return and second driver, flagged receipts/returns, duplicate active assignments, cross-company authorization, active-trip guard, legacy baseline registration, previously undocumented damage, overview, native trip-number contracts, and new build/identity contracts.
- All GitHub Action YAML files: parse successfully.
- Modified `web/src/App.tsx` and `web/src/VehicleHandover.tsx`: TypeScript transpilation parser reports zero syntax errors.
- Existing `mobile/android_native_tracking/NuqatiNativeTrackingService.kt`, `manager/main.dart`, `web/src/TripLiveMap.tsx`, and `web/src/FleetPositionMap.tsx` are **byte-for-byte unchanged**.
- No original source or other ZIP member has been deleted.

## Not verifiable in this offline environment / next acceptance gates

- **Flutter Android APK/AAB compilation was not run** (Flutter SDK absent). GitHub Actions must prove it compiles; on-device camera, background GPS, initial login without a plate, and release-after-return must be tested.
- **Full Vite / TypeScript production build not run** (web dependencies unavailable); TSX syntax is validated, not comprehensive type checking.
- **PostgreSQL staging migration / true multi-request concurrency was not run.** SQLite API test fixtures do not emulate PostgreSQL row-lock behavior.
- **Live Coolify/Web/API integration, real-time update latency, and database storage load were not verified**. Verify the same deployed commit is used for backend/web/mobile.
- Handover inspection odometer is saved as evidence in the new inspection table; it does **not automatically update** `vehicles.odometer_km` or the existing maintenance mileage source. This preserves maintenance logic but requires a separate verified policy for mileage integration.
- The backend handover dashboard limits assignment rows to the most recent 500; its KPI counts are derived from those 500. This should be improved before a large-scale rollout.
- Approval while the driver app is **closed/backgrounded** is synchronized when the driver next reaches online app/vehicle status; there is no native background push update for assignments. The backend still validates the current plate on new trip uploads.
- Photos currently live as binary rows in PostgreSQL. Monitor backup size, database growth, and memory as vehicle handover volume increases.
- Report PDF has English labels and uses built-in Helvetica; Arabic/Urdu PDF shaping/font support must be separately implemented/tested for localized legal evidence.

## Recommended staged test

1. Deploy backend + web **together from this same corrected commit**, after a tested PostgreSQL backup.
2. Build a debug APK from the patched `build-android.yml` and a signed AAB from the patched `build-driver-release.yml`. Confirm `lib/vehicle_handover.dart` appears during compilation.
3. Onboard Driver A **without** selecting a vehicle. Sign in and confirm no vehicle is assigned and no native trip can start without a valid plate.
4. Online: Driver A receives a company car with eight photos and initial odometer. Verify receipt and plate in web dashboard.
5. Drive and complete a trip. Confirm the trip, GPS, points, and native identity are associated with Driver A and the correct vehicle.
6. Online: Driver A returns car; confirm the native recording owner is cleared and no new trip is started on the returned car. Test supervisor approval for new/previously unrecorded scratch.
7. Online: Driver B receives the same plate and passes inspection. Verify older Driver A trips remain unchanged.
8. Disable mobile internet: neither receipt, return nor photo capture should be accepted. Restore connectivity and reverify.
9. Test supervisor approval on web while driver has the handover page open; expect frontend update within 20 seconds, web dashboard within 30 seconds.
10. On a physical Android device, test camera permission, 8 images, Android background tracking, offline trip queue, and battery conditions. Do not use production until this gate passes.

**Status:** The source-level critical defects listed above have been corrected, but this is a **staging/test candidate**, not a production certification.
