# Nuqati | One-page vehicle editor (18 November 2026)

## What changed
- **Vehicles**: click any vehicle row, plate number, or **Edit all fields** to open the same dedicated edit page.
- Bilingual English/Arabic, current Nuqati dark-blue/lime design, grouped layout and vehicle card inspired by the supplied asset-editor screenshot.
- All *currently supported vehicle fields* are editable on one page: plate, make/model, year, fleet/door number, and driver assignment. Company and internal vehicle ID are displayed read-only.
- Current odometer is displayed. Super Admin can correct it **with a required reason** in the same Save action.
- **One Save all changes** call updates vehicle details and, when authorized, records a new odometer history correction in the **same database transaction**.
- **Companies > vehicle details** now opens the exact same editor instead of maintaining another editable copy.
- Existing features retained: adding vehicles, deleting them (Super Admin only), hardware devices widget, odometer recording/history, service reminders, handovers, reports, tracking and all Android apps.

## Data protection
- `PATCH /api/v1/vehicles/{id}` remains backward compatible. New optional fields are `odometer_correction_km` and `odometer_correction_reason`.
- An admin-only correction is written as a new `OdometerReading` with source `ADMIN_CORRECTION`; old history is never overwritten.
- Backend role and company access checks, existing handover restrictions, and driver-company checks remain enforced.
- Only changed vehicle fields are submitted. The company cannot be reassigned from the editor.
- No schema migration and no added columns are required.

## Not included
- The reference screenshot contains additional fields (VIN, engine number, fuel type/tank/costs, etc.) that this Nuqati vehicle database/API does **not** currently store. This redesign does not introduce dummy fields or unpersisted values.

## Deployment and testing
1. Commit the provided project files to the current Nuqati GitHub repository.
2. Redeploy the **web and backend** services together in Coolify. Preserve the current database, storage, keys and volumes.
3. Log in as Super Admin or Company Admin, open **Vehicles**, click a plate, edit several details, then click **Save all changes** once.
4. For Super Admin, change the odometer and enter a reason; confirm a new entry appears on the existing Odometer history page.
5. Confirm driver assignments obey active handover restrictions and other-company drivers are not available.
6. Check **Companies > expanded company > vehicle** uses the same editor; check add, delete and hardware views remain available.
7. Check Arabic and mobile layouts. No Android app rebuild is needed.

## Verification performed
- Python backend syntax compile passed.
- TypeScript/TSX parser checks passed for the changed components.
- Isolated execution checks of the actual backend endpoint logic passed for legacy PATCH, multi-field one-commit update, admin correction history, rejection of insufficient permissions, and rejection of too-short correction reasons.
- Full Vite build / browser integration could not be run in this container because frontend node dependencies were unavailable for installation. Build and smoke-test on your normal Coolify/GitHub environment before using production vehicle records.
