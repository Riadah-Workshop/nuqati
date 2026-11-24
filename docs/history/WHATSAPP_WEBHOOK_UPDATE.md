# Nuqati Meta WhatsApp webhook — staging update

This update adds the webhook handshake and validates incoming Meta HMAC-SHA256 signatures. It does NOT yet send OTPs, maintenance reminders, or automatically link a driver to a plate. Those features must be developed and tested separately. The existing driver phone/password login remains in place.

1. Back up PostgreSQL. Upload these files to the existing GitHub repository (preserve `.git`, Coolify settings, domain, database volume, and all existing secrets). Redeploy the staging stack.
2. In Coolify add two **new** environment variables to the stack: `NUQATI_WHATSAPP_VERIFY_TOKEN` (generate a long random string, at least 32 characters) and `NUQATI_WHATSAPP_APP_SECRET` (the Meta Developer App Secret from App Settings > Basic). Do not confuse the App Secret with the temporary access token. Keep both values private. Redeploy after saving.
3. Test that `https://nuqati.al-riadah.sa/api/v1/health` works. The callback endpoint is `https://nuqati.al-riadah.sa/api/v1/whatsapp/webhook` (the Caddy `/api/*` proxy already bypasses staging Basic Auth).
4. In Meta Developer App > WhatsApp > Configuration, paste that callback URL and the SAME verify token stored in Coolify, then click Verify and save. The backend echoes Meta's `hub.challenge` only if mode and token match.
5. Subscribe to the `messages` webhook field for future message status events. Note Meta's warning about production events while the app is unpublished. This code currently acknowledges signed events but does not persist or act on them.
6. The previously shared temporary API access token appeared in a screenshot: revoke/replace it before using the API. Never put tokens or secrets in GitHub, the APK, screenshots, or messages.
7. Keep the existing workshop WhatsApp Business number untouched. A Meta test number is sufficient for webhook verification. Do not migrate or register your production number without confirming app coexistence eligibility.

Security: GET verification returns HTTP 403 on mismatch. POST requires `X-Hub-Signature-256` using Meta App Secret, and rejects invalid payloads. No Iqama number is used for authentication.
