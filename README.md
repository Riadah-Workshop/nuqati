# Nuqati – Harsh Cornering in Fleet Reports

Replace only `backend/app/main.py` and `web/src/App.tsx` with these files. This patch is based on the Phase 4 backend and the map-based simplified dashboard frontend.

Changes:
- Adds `harsh_cornering` count to each driver's `violations` object returned by Fleet Reports API.
- Adds a bilingual Harsh Cornering column to Fleet Reports.
- Includes Harsh Cornering in CSV export.
- Preserves the existing pilot score formula; does not silently change scores.

Deployment: back up current working files and database; deploy backend first, then web. Generate Fleet Report for a period containing known cornering events and verify the count and CSV. Zero means no matching detected events for that driver/period.

Validation: Python syntax checked. Full web build and runtime tests not performed. If your deployed GitHub version has changed since the provided patches, compare changes before replacing files.
