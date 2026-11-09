# Nuqati Phase 3A — Admin CRUD pilot

Based on Phase 2. This is a staging candidate, not a complete implementation of the requested fleet/GPS/mobile product.

## Delivered in this package
- Super Admin-only edit/delete API for users, drivers and vehicles; frontend controls for selected editable fields.
- Super Admin-only deletion of maintenance schedules, with frontend button.
- Existing company edit/delete retained.
- Odometer correction creates a new history record with a required reason; does not erase prior readings. API only in this increment.
- User self-deletion and self-demotion blocked. Deleting vehicles with maintenance/trip/odometer history, and drivers with vehicle/trip links, is blocked. Company deletion remains blocked if any linked records exist.
- Existing Solutions Workshop logo and dark dashboard retained.

## Not delivered yet — do not describe as live
- Full bilingual editable-label CMS and company/workshop branding uploads.
- Driver and vehicle photo storage, media validation, virus scanning and access-controlled delivery.
- Driver app authentication, GPS/background permissions, trips, live map, harsh-event capture, scores and Play Store release.
- Configurable company-specific overspeed thresholds and scoring policy; report generator.
- Production-grade migrations, audit log, comprehensive security/tenant-isolation and restore tests.

## Safe deployment
1. Back up PostgreSQL and verify a restore in a separate environment.
2. Keep the existing `nuqati_staging_pgdata` volume; do not run TRUNCATE or delete/recreate the volume.
3. Upload extracted project contents at GitHub repository root, preferably to a test branch, then deploy the branch in staging.
4. Test with fictional Company A and Company B and verify tenant boundaries, forbidden roles, dependent-delete protection and UI behavior.
5. Keep real clients and live driver location data out until the remaining security and privacy milestones are completed.

## Next architecture milestone
Use Alembic migrations; add scoped branding/settings/media models, driver-device identity, immutable trip and event ingestion, trip aggregation, GPS accuracy filtering, driver opt-in and retention, per-company speed thresholds, explainable versioned scoring, last-seen timestamp on location, role-scoped report export and Flutter signed Android release. Live tracking should never be fabricated from static map points.
