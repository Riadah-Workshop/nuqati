# Secret rotation runbook

Which secrets exist, how often to change them, and the exact steps. The first section is the one that matters most: the token-signing secret has a **zero-downtime rotation window** since Phase 2.1.

## 1. The token-signing secret (`NUQATI_AUTH_SECRET`)

It signs every sign-in token of the dashboard, the Driver app and the Manager app. Lifetimes: access token 8 hours; driver **refresh** token 30 days.

### 1.1 Planned rotation (no one is signed out)

Do this once a year, or when someone who could read the secret leaves.

1. Generate a new secret (at least 32 characters):
   `python -c "import secrets; print(secrets.token_urlsafe(48))"`
2. In Coolify, for the application's environment variables:
   - set `NUQATI_AUTH_SECRET_PREVIOUS` to the **current** value of `NUQATI_AUTH_SECRET`,
   - then set `NUQATI_AUTH_SECRET` to the **new** value.
3. Redeploy. Sessions signed with the old secret keep working; every new sign-in and every refresh is signed with the new one.
4. Check right after the deploy: an already open dashboard tab still works after a page reload; signing in again works; a driver phone that was signed in keeps tracking.
5. **Wait 30 days** (the longest token lifetime). By then every driver app has refreshed its tokens at least once, or its refresh token had expired anyway.
6. Remove `NUQATI_AUTH_SECRET_PREVIOUS` in Coolify and redeploy. Anything still signed with the old secret now stops working, which is the point.
7. Write the date in the rotation log (section 4).

If `NUQATI_AUTH_SECRET_PREVIOUS` is set but shorter than 32 characters the API refuses to start (so a typo is noticed at once). Fix the value and redeploy.

### 1.2 Emergency rotation (the secret may have been seen by someone who should not have it)

Set **only** `NUQATI_AUTH_SECRET` to a new value and make sure `NUQATI_AUTH_SECRET_PREVIOUS` is **empty or absent**, then redeploy. Everyone is signed out immediately, including anyone holding a forged token. Drivers must sign in again; with the one-device rule they need their password and an internet connection. Never use the window in an emergency: it would keep the leaked secret working. Continue with [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md).

### 1.3 What is and is not affected

- Not affected: password-reset links, invitation links, e-mail-change links and live-share links (random values stored as hashes, not signed with this secret).
- Sign-in throttle counters restart after a rotation (their keys are derived from the secret). That is harmless.
- Two-step sign-in: a person who has typed the password but not yet the code at the moment of a planned rotation has to enter the password again (the short-lived step tokens are checked with the current secret only). Stored authenticator secrets are not affected: they use `NUQATI_MFA_KEY` (section 2).
- An individual user can end all of their own sessions with **Log out** (dashboard) or by changing their password; no secret rotation is needed for that.

## 2. Other secrets

| Secret | Where it is set | When to change | Steps | Impact |
|---|---|---|---|---|
| `POSTGRES_PASSWORD` | Coolify | Yearly; after a leaver with server access; after any suspected exposure | **The environment variable alone does not change the password** of an existing database (it only applies when the database is first created). 1) In a database console: `\password <user>` (so the new password stays out of shell history). 2) Update `POSTGRES_PASSWORD` in Coolify. 3) Redeploy so `api`, `report_scheduler` and `teltonika` reconnect. The database is not published to the internet, which limits exposure | A short interruption during the redeploy |
| Two-step sign-in key (`NUQATI_MFA_KEY`) | Coolify, your password manager | Not on a schedule: only if it may have been exposed. Never delete it while accounts are enrolled | Set `NUQATI_MFA_KEY_PREVIOUS` to the old value and `NUQATI_MFA_KEY` to a new one (32+ characters), redeploy. Each person's authenticator secret is re-encrypted at their next sign-in; remove the previous key after everyone signed in once or after 30 days | Without the old key as `PREVIOUS`, every enrolled person is refused at the code step until a super admin resets them (OPERATIONS section 9). The token-signing secret is separate: rotating it, even in an emergency, does not touch this |
| SMTP password (`NUQATI_SMTP_PASSWORD`) | Mail provider, Coolify | Yearly; on exposure | Create a new password at the provider, update Coolify, redeploy `api` and `report_scheduler`, send a test password-reset e-mail, then revoke the old one | E-mails fail between the redeploy and the update if done in the wrong order |
| WhatsApp verify token (`NUQATI_WHATSAPP_VERIFY_TOKEN`) | Meta developer console, Coolify | On exposure | Set the same new value in both places, redeploy, re-verify the webhook in Meta | Webhook verification fails until both match |
| WhatsApp app secret (`NUQATI_WHATSAPP_APP_SECRET`) | Meta developer console, Coolify | On exposure; yearly | Regenerate in Meta, update Coolify at once, redeploy | Webhook calls are refused (signature mismatch) between the two steps |
| MapTiler key (`VITE_MAPTILER_API_KEY`, GitHub secret `MAPTILER_API_KEY`) | MapTiler account, Coolify build variable, GitHub secret | On exposure. The key is visible in the web app by design, so **restrict it to your domain** in MapTiler instead of relying on secrecy | Create a new key, update both places, redeploy the web image, build a new Manager app | Maps stop until the rebuilt web image and apps are out |
| Android signing keys (GitHub secrets `DRIVER_KEYSTORE_BASE64`, `MANAGER_KEYSTORE_BASE64`, `*_KEY_ALIAS`, `*_KEY_PASSWORD`, `*_STORE_PASSWORD`) | GitHub secrets, your encrypted copy | Not on a schedule. Only if lost or exposed | If the app is published with Google Play App Signing, a lost or exposed upload key can be replaced through Play Console support. Otherwise a new key means a new app identity. Decide with care before changing anything | Updates to installed apps can stop |
| GitHub and Coolify accounts, personal access tokens, deploy keys | GitHub, Coolify | After any leaver; yearly review | Turn on two-factor sign-in for every account; remove unused keys and tokens; review who has write access to the repository | — |
| Tracker allow-list (`TELTONIKA_ALLOWED_CIDRS`) | Coolify | When the tracker network changes | Not a secret, but treat it as one: the tracker handshake is the IMEI only | — |

## 3. After someone leaves

For anyone who could read Coolify variables, the GitHub secrets or the server: rotate the token-signing secret (1.2 if their departure was not friendly, otherwise 1.1), the database password, the SMTP password and the Meta secrets; remove their GitHub, Coolify and server access the same day; deactivate their Nuqati account ([INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) 4.1).

## 4. Rotation log (copy for each entry)

| Date (UTC) | Secret | Planned / emergency | Done by | Old value removed on | Checked (how) |
|---|---|---|---|---|---|
| | | | | | |

## 5. Open items

1. Put the rotation reminders (yearly, and 30 days after step 3 of 1.1) in the owner's calendar.
2. Confirm that every Coolify, GitHub and hosting account has two-factor sign-in.
3. Restrict the MapTiler key by domain, if not already done.
4. Keep an encrypted offline copy of the secrets list (names, where set, who knows them), without the values in the repository.
