# Nuqati — Company and Driver one-page editors (18 November 2026)

Based on the uploaded `nuqati-main(20261118-100525).zip`; the existing one-page Vehicle editor is unchanged.

## Companies (Super Admin)

- Click a company row/name or **Edit all fields**. An editor opens on the same Companies tab, with the familiar vehicle-editor header, two-column fields, sidebar and one Save action.
- Edit the **company name** and **Android driver-app logo** (PNG/JPEG/WebP, maximum 220,000 bytes). Preview the image, replace it, or remove it before saving.
- Existing `PATCH /api/v1/companies/{id}` now accepts an **optional `logo_data`** in addition to the required `name`, retaining compatibility with old name-only clients. The existing `/driver-logo` GET/PUT endpoints still work; image signature checks are shared.
- Name and optional logo are written in a **single database transaction**, so validation failures reject the entire edit. Company ID is read-only. Drivers, vehicles and users remain managed on their own screens and are counted in the editor.
- The company list still supports **add**, **expand related records**, **open linked driver/vehicle/user edits**, and **permanent delete** (with the original confirmation/backup logic).

## Drivers (Super Admin)

- Click a driver row/name or **Edit all fields** to open a single editor in the Drivers tab.
- Edit full name, phone, ID/Iqama, site/branch, status, and available vehicle assignment; company and driver ID are read-only. Last app login acknowledgment is read-only.
- Save submits changed fields together to the **existing** `PATCH /api/v1/drivers/{id}` endpoint, which commits one transaction and continues to enforce company scope, duplicate checks and documented handover restrictions.
- The editor fetches fresh driver metadata first, to avoid replacing existing identity fields with stale or blank form values.
- Company transfer and account password reset remain separate secure workflows. Other roles have **not** gained driver-edit permissions.
- The existing **add driver / enable login**, app acknowledgment refresh, delete action and company-related driver links are retained.

## UI

- Reuses existing `vehicle-editor.css` and dark-blue/lime Nuqati styling; RTL Arabic and English supported.
- Header and footer save buttons perform the same single save; unsaved-change warning on Cancel/Back; disabled Save until a field changes.
- Add forms are organized as expandable panels, consistent with the Vehicles page.
- Existing driver/vehicle app workflows, fleet tracking, handover, maintenance and reports were not modified.

## Deployment

1. Upload the complete project files to the existing Nuqati GitHub repository; preserve secrets and the database.
2. Redeploy the **web** and **backend** together in Coolify. No Android rebuild and no DB migration required.
3. Super Admin: open a company, change name and logo, Save; refresh and verify both values and app branding. Verify the old logo PUT endpoint still works.
4. Super Admin: open a driver, change several fields, Save; check name, phone, site, status and assignment after reload. Verify active handover restrictions remain enforced.
5. Test Arabic, smaller screens, Cancel/discard, add/delete, company expanded records and the existing Vehicles editor.

## Validation in preparation environment

- Python backend module compiles.
- TypeScript/TSX parse diagnostics: zero for App, both new editors and the existing Vehicle editor.
- Five isolated contract tests pass for company legacy patch, name + logo one-commit update, clear-logo update, invalid image rejection, and Super Admin authorization.
- **Not verified:** full production `vite build` and authenticated end-to-end browser tests because web npm dependencies were unavailable in this environment. Confirm in the GitHub/Coolify build before production use.
