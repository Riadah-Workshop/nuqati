# Nuqati simple onboarding update

Source: latest supplied vehicle-fields package. Replaces separate driver registration/login with one transactional form. Company Users creation is limited to company_admin and fleet_manager (Vehicle Supervisor). Existing records are retained. Driver ID and site are stored in new `driver_metadata` table; SQLAlchemy create_all creates this table on backend startup. No existing tables are dropped. Driver email is an internal non-deliverable unique identifier, never requested from the driver.

IMPORTANT: A vehicle plate is public information and is not a safe login password. This build requires a private 12+ character temporary password. WhatsApp OTP and first-login password-change enforcement are not implemented. Driver phone login is supported by the existing Android source; rebuild the APK only if updating its source.

Back up PostgreSQL before deployment. Replace source files in GitHub with this package, keep Coolify environment and persistent volume unchanged, redeploy backend then web. Test creating a new vehicle, driver, mobile login, trip and company admin/supervisor creation. Do not create drivers from Users.
