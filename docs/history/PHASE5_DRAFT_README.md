# Phase 5 development draft — NOT deployment-ready

This is a source-code draft based on the uploaded working Nuqati archive. Keep your current GitHub/Coolify deployment unchanged. Python syntax compilation passed; the frontend production build could not be validated because package installation timed out in the isolated environment. Do not deploy without a successful build and staging tests.

Included: additive invitation/branding tables, SMTP invitation sender, pending account activation with 24-hour one-use hashed token, resend, global logo and core navigation/label editing, basic English/Arabic navigation switch, sender identity Nuqati by Al-Riadah Workshop.

Not yet complete: exhaustive translation of every dashboard button/label, password reset, HTML email template, email delivery integration testing, database migrations under a migration framework, image sanitization beyond type/size checks, accessibility and security review. Existing direct password user creation is retained for compatibility and must be retired after full invitation rollout.

New Coolify variables: NUQATI_SMTP_HOST, NUQATI_SMTP_PORT (default 587), NUQATI_SMTP_USER, NUQATI_SMTP_PASSWORD, NUQATI_EMAIL_FROM (default noreply@al-riadah.sa). STAGING_ORIGIN is reused as NUQATI_PUBLIC_ORIGIN. The sender mailbox/domain must be provisioned and SPF/DKIM/DMARC configured with the email provider. Never put credentials in GitHub.

Before deploying: backup database, review code, build `cd web && npm ci && npm run build`, run backend tests, test email in a disposable environment, verify company scope, restore rehearsal and rollback.
