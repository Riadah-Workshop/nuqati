# Nuqati update — 2026-11-23

Source baseline: `nuqati-main(20261123-133801).zip`.

## Updated behavior

1. Privacy Audit now uses a clear six-section navigation similar to Configuration: privacy approvals, device/access events, tracking heartbeat, privacy mode changes, notification changes, and camera observations. Existing audit views and CSV exports remain.
2. Removed the **Hours of Service Reports** and **Mix Sat Reports** category options from Fleet Reports; underlying backend tracking settings and other reports were left untouched.
3. Super Admin selects the company once from the top bar, retained across tabs and browser refresh in this browser/account. Company users operate in their assigned company without duplicate selector controls. Reports, device handover and geofencing use the active context.
4. Removed the generic upper search bar from Fleet Reports and Odometer (specialized filters within those pages remain).
5. Overview time-range controls reorganized with quick presets, clear date/time fields and an Apply button.
6. Live Tracking continues to display the latest valid driver-reported GPS position and its timestamp after a device goes offline, marked as stale. An on-demand fix is preserved if a newer request starts; valid privacy mode still hides location.
7. Compact **Position & Share** expandable actions appear on each Live Tracking vehicle card; they use the existing request and expiring share-link backend endpoints.
8. Increased hierarchy and contrast of section, tab, active navigation and card titles.

## Files to update

Copy the paths from the `nuqati-main/` directory in the changed-files archive into the same paths of the repository. Keep your existing secrets and Coolify variables; none have been changed. For a direct replacement, use the complete updated source archive.

## Validation

- Python syntax compilation of `backend/app/main.py`: passed.
- TypeScript TSX syntax parsing of all changed `.tsx` files: passed.
- Backend regression contract tests: 24 passed (`test_driver_device_session_units.py`, `test_security_runtime_units.py`, `test_safety_counts_trip_number_contract.py`, `test_handover_integration_contract.py`, `test_native_tracking_regression_contract.py`).
- Full backend suite not passing as uploaded: `test_company_one_page_editor.py` expects an `_validate_company_driver_logo` function that is not present in the unmodified baseline source.
- Full production frontend build not executed: npm dependencies were not installed in this environment. Run `npm ci && npm run build` within `web/` in CI/Coolify and verify the deployed interface.

## Manual smoke tests after deployment

- Super Admin: select Company A, change multiple pages, refresh browser; confirm the company persists and reports contain only A. Change to B; verify old reports, vehicle cards and audit rows do not remain.
- Company Admin: check that company selection is not required on any page and only that company's data is displayed.
- Privacy Audit: switch among all six tabs and confirm driver filtering, approval/revoke actions and audit CSV export.
- Live Tracking: select a car, open Position & Share, request GPS and share for 5/15/30/60 minutes. Verify stale GPS remains labelled as an old observation, and privacy-enabled GPS is hidden. Verify share expiry and revocation.
- Reports & Odometer: verify no redundant upper search bar, while report-specific and odometer-specific filters still work.
