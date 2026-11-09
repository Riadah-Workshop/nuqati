# Nuqati Safety Score v1 — staging patch

## Baseline and contents
Backend is based on the last supplied harsh-cornering Fleet Reports patch, which incorporated the Phase 4 backend. Web is based on the last supplied harsh-cornering Fleet Reports patch, which included the geofence map picker import. **This patch is not a verified snapshot of your live GitHub main branch**. Compare before replacing; especially preserve `web/src/GeofenceMapPicker.tsx`, `web/package.json` and other files from the map picker update.

Modified files: `backend/app/main.py`, `web/src/App.tsx`. No mobile source changes: the driver app should use the same authenticated `/api/v1/fleet/report?period=...` endpoint to display the authoritative score; **the existing mobile UI is not updated in this patch**.

## Calculation
Five weights default to 20% acceleration, 20% braking, 20% cornering, 25% speeding, 15% excessive speeding. Seatbelt excluded. Each speeding event is classified into either ordinary or excessive (not both), based on fleet speeding threshold plus configurable margin (20 km/h default). Per category, events/100 km divided by the configured full-penalty rate (10 events/100 km default) determines fraction of its weight deducted, capped at full weight. Score = round(100 - sum(deductions)). The category results include event counts and deductions. Insufficient distance (<1 km default) gives null, not 100. Risk: low 90–100, mild 75–89, medium 60–74, high 0–59.

**Pilot formula, not Geotab's proprietary implementation.** Event severity other than excessive speed is not used. GPS errors and duplicate violation records can affect scores. Events are included based on their recorded timestamps; distance is from completed trips whose starts fall in the period. This boundary mismatch is a known limitation for trips spanning periods.

## Deploy
1. Backup GitHub working commit and PostgreSQL.
2. Diff these two files against current main before replacing.
3. Deploy backend to Coolify; inspect startup logs.
4. Deploy web to Coolify; ensure TypeScript/Vite build succeeds.
5. Open Reports > Fleet Reports > Driver Safety Score, choose company (super admin), load policy, edit weights to total 100, save, regenerate report.
6. Verify a driver with no completed trips shows score unavailable, and a driver with events shows breakdown via API.
7. Verify API `GET /api/v1/fleet/safety-score/policy`, `PUT` for admins only, `GET /api/v1/fleet/report`, `GET /api/v1/fleet/phase4/risk`.

## Tests run
- Python `py_compile` passed.
- Six isolated scoring assertions passed (zero events, speeding vs excessive, short distance, cornering, braking).
- **No live PostgreSQL integration, full Vite build, or Android device test completed.**

## Next
Expose the score and category breakdown on the Android driver screen by consuming the report endpoint, not by calculating another score locally. Add daily/weekly/monthly per-trip scoring only after validating event and distance windows. Avoid using pilot score for disciplinary decisions without GPS validation and fleet policy review.
