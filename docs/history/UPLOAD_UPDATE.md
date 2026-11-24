# Updating your existing GitHub repository and Coolify resource

1. Before any redeploy, back up the existing database. Do not delete the Coolify resource or its named PostgreSQL volume.
2. Extract this ZIP. In GitHub repository Riadah-Workshop/nuqati, upload/replace the CONTENTS at the repository root on the existing `main` branch, preserving the folder paths (`backend/`, `web/`, `mobile/`, `docs/`). GitHub's browser uploader may not preserve folder structure: use GitHub Desktop/git if needed. Do not upload the ZIP as a single file.
3. In your existing Coolify staging resource, keep branch `main` and Compose path `/compose.yml`. Keep the same six staging environment variables and web domain. No new secrets are needed. Redeploy after the commit is visible.
4. Verify `/api/v1/health` behind basic auth. In the dashboard, create a fictional company, vehicle and driver; add an odometer reading; open 'تنبيهات الصيانة' and save an oil service interval. Verify near-due status by updating the reading.
5. Existing tables are not deleted. New `maintenance_schedules` table is created on startup in this starter. Before commercial release replace `create_all` with reviewed database migrations and add authentication/tenant isolation.

No photo/plate OCR or WRShah integration. Mobile remains a UI starter and is NOT deployed by Coolify.
