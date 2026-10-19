# Nuqati — simplified staging starter (v2)

Driver safety and mileage-based preventive-maintenance reminders. No plate scanning, odometer photo recognition, or workshop integration. See `docs/PRODUCT_SCOPE_V2.md` for agreed scope and implementation status.

Deploy on Coolify using `/compose.staging.yml` (not the legacy `docker-compose.yml`), and follow `DEPLOY_COOLIFY.md`. Existing Postgres volume is retained when updating the same Coolify resource; back it up before changing deployments. The backend uses `create_all` for this starter and does not perform production database migrations. This is NOT production ready: no application authentication or company-level access isolation, no working mobile GPS or push notifications, and no live scoring. Use fictional staging data only behind gateway basic auth.
