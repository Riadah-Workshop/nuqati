# Nuqati Reference-Inspired Reports — 24 November 2026

## Scope

This is an **additive** feature based on the *concepts* in the four SANAD workbooks supplied with the request. The styling is Nuqati's own navy/lime dashboard identity, not a copied workbook design. Existing report pages, monthly exports, Flexible RAG configurations, APIs, driver apps, GPS tracking and database schema remain unchanged.

### New reports in Fleet Reports → Report Suite

1. **Trip Movement Detail** — one row per completed trip: date, driver, site, vehicle/model/plate/ID, departure/arrival, GPS start/end coordinates, GPS-observed moving/stationary time, elapsed trip duration, distance, GPS max/average speed, next trip and time gap.
2. **Daily Fleet Trips** — one row per day/vehicle/driver: trips, first/last trip, motion time, elapsed time, distance and speed. Engine idle and measured fuel/km/L fields are deliberately blank because Nuqati has no fuel/ignition measurement.
3. **Vehicle Utilization Calendar** — one row per vehicle, with selectable date columns for recorded distance, Friday/Saturday weekend and Sunday–Thursday distance, days with/without trips, and percent of days having trips. Unlike a trip-only view, a whole-company report also displays vehicles with no trips.
4. **Daily Driver Safety & RAG** — one row per driver/day: distance, acceleration/braking/cornering events and rates per 100 km, speeding counts, highest recorded speeding event, GPS-observed speeding intervals, and the **current Nuqati-approved company scoring policy**. Flexible RAG is lower-is-better; the existing 100-point score is higher-is-better. No external score algorithm was imported.

Each report supports Saudi-local dates (up to 31 days inclusive), the existing company context, driver and vehicle filters, on-page preview, and Excel/CSV/PDF download. All report endpoints are company-scoped and have the same reporting-role checks as existing monthly reports. No database migration is required.

## Data interpretation & limits

- Only completed trips are reported. Trips are assigned to the **Saudi date of departure**, including when a trip spans midnight.
- Vehicle distance is the completed-trip distance already stored by Nuqati. It is not calculated again from waypoints.
- **Trip duration** is elapsed time from trip start to end; not ignition time. GPS-observed movement, stationary and speeding time count only consecutive good readings (accuracy <=25 m, speed 0–250 km/h, interval <=10 seconds); gaps are excluded. No entire-trip coverage is implied.
- Start/end points are **latitude/longitude**, not street addresses. GPS-based speed values are sampled measurements, not guaranteed full-trip averages or validated peak speeds.
- Time between vehicle trips is a **gap**, not evidence of standing in the same location.
- Engine idle, measured fuel use and km per litre remain unavailable. These fields must not be populated with guessed numbers.
- Days without recorded trips are **not proof of no vehicle use** (GPS/device outages and privacy settings can suppress records).
- RAG uses the active Nuqati scoring implementation and company policy. For insufficient distance or GPS coverage, the official score can remain unavailable.
- To bound response cost, the report range is **1–31 calendar days** and the query refuses more than **2,500 completed trips**; narrow the filters for larger requests.
- PDF uses English text for compatibility with ReportLab's standard fonts; Excel and CSV report headings and data notes follow the chosen platform language.

## Source files and integration

**Modified (original features retained):**
- `backend/app/main.py` — registers the new endpoints after existing routes.
- `web/src/App.tsx` — mounts the new report workspace in the existing Report Suite.
- `web/src/ReportSuite.tsx` — four additional selectable reports.

**Added:**
- `backend/app/concept_reports.py` — report queries, data limitations, exports.
- `web/src/ConceptFleetReports.tsx` — bilingual, filterable report workspace.
- `web/src/concept-fleet-reports.css` — Nuqati-specific report styling.
- `backend/test_concept_reports.py` — in-memory SQLite regression tests and Excel/PDF/CSV generation smoke tests.

All new endpoints are under `/api/v1/fleet/concept-reports/{kind}` (`kind`: `movement`, `daily-trips`, `utilization`, `daily-rag`). The export route is `/api/v1/fleet/concept-reports/{kind}/export` and accepts `format=xlsx|csv|pdf`, plus optional `lang=en|ar`. Both require `start_date` and `end_date`; optional `company_id`, `driver_id`, `vehicle_id`.

## Verification

Run from the project root:

```bash
PYTHONPATH=backend python -m unittest backend.test_concept_reports -v
python -m py_compile backend/app/concept_reports.py backend/app/main.py
```

Test results: 5 / 5 passed, including group dates, inactive vehicles, RAG, fuel omissions, and all three export formats. TypeScript source syntax transpilation passed for the modified React files. **A full Vite/TypeScript production build could not be run in the analysis environment because npm dependencies were not installed and registry access was unavailable.** Normal Coolify build will install dependencies as configured by the existing web Dockerfile; check the build log and generate each new report with actual data after deployment.

## Deployment

Replace the modified source files (or deploy the complete updated source ZIP) to your GitHub repository, then redeploy the existing Nuqati services using your normal Coolify flow. No env vars, new packages or database changes are required; existing `openpyxl` and `reportlab` dependencies already provide XLSX/PDF export functionality.
