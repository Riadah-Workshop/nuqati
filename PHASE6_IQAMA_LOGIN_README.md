# Phase 6 — Iqama login without WhatsApp OTP

This update changes Android driver sign-in to **Saudi ID/Iqama number + password**. WhatsApp API/OTP is not required. Existing phone login remains available for backwards compatibility; company admin web login remains email/password.

## What changed
- `backend/app/main.py`: `POST /api/v1/auth/driver-iqama-login`, `POST /api/v1/drivers/{driver_id}/iqama-credentials`, `POST /api/v1/mobile/change-password`. Existing driver metadata stores the Iqama; no database schema change is required.
- `web/src/App.tsx`: Drivers table action **Generate / Reset Password**. Enter Iqama; one-time temporary password is shown in the admin UI. This action resets an existing driver's password.
- `mobile/lib/main.dart`: Android login uses Iqama/password, with a change-password form after login.

## Deploy carefully
1. Commit these changes to the **existing** `Riadah-Workshop/nuqati` repo, `main` branch. Do not create a new Coolify application.
2. Back up PostgreSQL and confirm restore capability before deploying. Keep existing `.env`, `NUQATI_AUTH_SECRET`, domain, and persistent DB volume.
3. Redeploy the existing Coolify staging stack. Verify `/api/v1/health` and the admin login.
4. In **Drivers**, locate a driver who already has a linked driver login. Click **Generate / Reset Password**, enter the driver's 10-digit Saudi ID/Iqama, then copy the generated password once. **This immediately invalidates the driver's previous password.** If a driver has no linked account, link/create it using the existing admin workflow first.
5. Rebuild the Android pilot APK with the existing GitHub Actions workflow and install the new APK. Old APK versions still use phone login.
6. On Android sign in with Iqama and generated password, then change password. Test a trip and check Fleet Reports.

## Limitations and security
- No SMS, WhatsApp, or OTP verification is used. Treat this as a limited pilot, not identity verification.
- Iqama is sensitive personal data. Use fictional/test IDs for initial testing, obtain driver consent, restrict admin access, and never share credentials in public chats or screenshots.
- The 10-digit validation checks format only, **not** the official Saudi ID checksum or the user's legal identity.
- Existing legacy metadata may contain duplicate Iqama values; such records cannot log in until corrected. The new admin endpoint prevents new duplicates in normal sequential use, but no DB unique index is added in this migration-free pilot.
- The generated password is returned once and stored only as a PBKDF2 hash in the DB. It is not automatically marked as requiring a change at first login; the driver should change it immediately in the app.
- Current app GPS is foreground-only. Do not treat it as background tracking.
- Before production: rate limiting/login lockout, auditing, verified ID uniqueness, secure credential distribution, session revocation and privacy/security review are required.
