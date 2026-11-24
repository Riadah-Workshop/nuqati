# Nuqati – Online Vehicle Handover, Inspection & Vehicle Assignment
**Pilot patch based on the user's `nuqati-main(20261111-104524).zip` (November 11, 2026)**

## Scope and non-regression policy

All code changes are **additive** or narrow guards on old manual assignment paths. Existing trip detection, GPS collection, native safety events, historical tracking, live tracking, score calculation, authentication, and maintenance workflows were retained. No existing database table was dropped and no previous tracking code was removed.

- Driver app: **My Vehicle · Receive / Return** from the home and Settings pages; company plate selection, eight mandatory camera photos, odometer, engine/cabin state, warnings, missing items, photographed scratch/damage items, driver confirmation, preview of the previous condition, and backend verification.
- Backend: four new tables – `handover_assignments`, `handover_inspections`, `handover_photos`, `handover_audit` – created at application startup. Company-scoped endpoints; atomic condition reports; irreversible photo SHA-256 fingerprints; supervisor approvals; versioned assignment history; PDF including evidence; admin releases with reasons and permanent audit events.
- Web dashboard: **Fleet → Vehicle Handover**, with filters, pending approvals, side-by-side photographs, individual histories, review actions, and authenticated PDF download.
- A driver may use only **one handover-managed vehicle** at a time; concurrent double assignments are prevented by PostgreSQL partial unique indexes and transaction locks. A vehicle may be assigned to only one handover driver at a time.
- Existing driver-to-vehicle links are not erased. Their drivers can establish the **first baseline receipt inspection** for their already-assigned plate before participating in new transfers.

## Strictly online (requested behavior)

**All** vehicle selection, inspection, photo uploads, handover acceptance/return, manager approvals, and exceptional releases require the authenticated API to be reachable. There is **no offline draft, database queue, or deferred upload** for the handover module. If connectivity fails, the handover is not accepted and the user must refresh server status. Image picker can create an OS-owned temporary camera file during capture; Nuqati immediately deletes it after reading into transient RAM. This is not an offline photo store. Nuqati's **existing offline trip tracking remains unchanged**.

A return or vehicle change is blocked while a trip is active **or while local trips have not been fully acknowledged by the backend**, to avoid leaving old trip records under a new plate. Once the server confirms the change, the driver app updates the native tracking owner, offline profile, and visible plate. Data from older trips retain their original driver and vehicle identities.

## Deployment for one-time testing — staging first

1. **Back up your current PostgreSQL database and verify a restore point.** Record the current Git commit and Coolify deployment ID. Do not run the patch initially against your production fleet.
2. Apply the modified-only ZIP **on top of the exact November 11 source** preserving directory paths; or use the complete merged source ZIP. Do **not** use the November 4 snapshot.
3. Deploy backend and web from the same commit using your existing Coolify settings. New handover tables/indexes are created automatically. No existing tables are altered. Confirm `/api/v1/health` and normal overview/live tracking still work.
4. Create a new **Driver signed AAB / APK** with the updated GitHub Action. The workflow now copies `mobile/vehicle_handover.dart` to `mobile/lib/vehicle_handover.dart` and `flutter pub get` resolves `image_picker`.
5. Test with two drivers, one company, and one spare vehicle. Verify receiving photos, odometer, existing scratch approval, one-time plate linking, no active trip during return, return differences, manager approval, and the next driver's new baseline.
6. Disable mobile internet and open My Vehicle: **no handover or photo capture should succeed**. Restore internet, refresh and repeat; verify no offline handover queue is created.
7. Before live rollout, confirm Google Play permissions and Android device camera behavior on the target versions. Rebuild the app and web from the patched commit after review.

## Test matrix

| Scenario | Expected result |
|---|---|
| Receive clean vehicle / eight photos / acknowledgment | Assignment activated online; driver app plate updates |
| Receive with existing scratch, missing equipment or warning | Supervisor approval required; photo evidence retained |
| Receive another driver's active plate | Server HTTP 409; no duplicate assignment |
| Two concurrent receives for same driver or vehicle | Partial unique index enforces single active assignment |
| Receive vehicle already assigned to the same driver (legacy) | First baseline inspection recorded without changing trip history |
| Return during an active or unsynced trip | Blocked (driver app / server active-trip validation) |
| Clean return | Assignment closed; vehicle released for another driver |
| Return with new damage, missing equipment or warning | Pending supervisor review; plate remains linked until approval |
| Return with odometer below receipt/system value | Rejected; server keeps vehicle link unchanged |
| Cross-company photo access | Rejected by API authorization |
| No internet during handover | No backend confirmation, no offline handover storage |
| Exceptional administrative release | Requires reason, prevents active-trip release, creates audit |
| Existing Live/Historical Tracking & safety scoring | Must behave exactly as before patch |

## Automated verification performed in this environment

`14 passed` in the backend handover, overview, native safety/trip contract tests using SQLite test fixtures. Python compilation and TypeScript syntax checks passed. The actual **Flutter/Android build and Vite production build could not be executed here** because the Flutter SDK and web NPM dependencies were not available. The patch is prepared for staging validation, **not certified production-ready**.

## Notes and limitations

- Photo comparison is **visual/manual**, not an automatic computer vision damage claim. The event timeline proves when an issue was documented, not who caused it.
- Supervisor approvals are in the **web management dashboard**; the separate Android Manager app is unchanged.
- Inspection evidence is stored in the **PostgreSQL database** (byte arrays, with hashes), not anonymous public file links. Photo storage growth should be monitored and included in database backups.
- The app requires **8 required inspection images**. Each image is at most 950 KB; each damage item needs its own additional photo. Missing equipment and abnormal engine reports also need evidence photos.
- Only company admins, fleet managers and Super Admin can approve or release. Driver acknowledgment is a server-recorded confirmation with time and authenticated identity, not a legally certified digital signature.
- Legacy manual driver and vehicle assignment screens are preserved, but changing a vehicle involved in an active handover requires the online handover or audited administrative release workflow.
- The normal company permanent-delete workflow will delete associated evidence **only after its existing verified-backup requirement**; this is visible in its deletion preview.
- Keep this as a pilot until a physical Android device and a staging PostgreSQL test have passed.
