# Nuqati Phase 4 – staging deployment and test plan

## Baseline
Based on the 2026-10-28 Nuqati source ZIP with the tested Offline Login & Separate Trips patch overlaid. Only `backend/app/main.py` and `web/src/App.tsx` are replacements.

## Included in this iteration
- Company-scoped circular geofences (restricted/monitor), entry/exit and restricted-zone event detection from GPS samples.
- Optional geofence speed-limit policy, applied when the GPS sample is inside the zone.
- Experimental harsh-cornering detection using three GPS points and estimated lateral acceleration.
- Risk score endpoint using distance-normalized driving events and four risk tiers.
- English/Arabic dashboard page: Safety & Geofences, geofence creation/deletion, cornering/risk thresholds and risk table.
- Existing offline GPS sample queue and privacy mode are preserved in the mobile source (not replaced).

## Not yet included / limitations
- **No new driver-phone push notifications** for geofence/cornering events. These are server-side events detected after samples upload; if offline, they appear only after sync.
- No polygon geofences, road-map speed limits, Urdu translation, or consolidated mobile UI yet.
- GPS-only cornering is approximate and needs controlled validation. Do not use for punitive decisions without review.
- No changes to Flutter; the existing APK should continue working.
- A full web build could not be run here because node dependencies are not installed; run the Coolify/Vite build.

## Deploy
1. Back up PostgreSQL and save the current working GitHub commit.
2. Replace `backend/app/main.py` and `web/src/App.tsx` from this ZIP in the matching repository paths.
3. Commit, redeploy API first, then the web dashboard.
4. Open Safety & Geofences. Super Admin must select a company; company admin uses their own company.
5. Add a test circle using known coordinates and radius >= 50 m. Start with `monitor` mode.
6. Use a safe recorded GPS trace crossing the boundary; verify one entry and one exit event.
7. Configure a zone speed limit, test a synthetic or safely recorded trace, and inspect Fleet Reports and the risk table.
8. Enable Privacy Mode and confirm no GPS sample or geofence events are generated while enabled.
9. Test three separate offline trips, reconnect, and verify the existing odometer updates once per completed trip.
10. Check all roles for company isolation and verify old driver app still uploads GPS normally.

## Rollback
Restore the two files from your saved commit and redeploy; this patch stores policy settings in existing `app_settings` rows and does not delete existing data.
