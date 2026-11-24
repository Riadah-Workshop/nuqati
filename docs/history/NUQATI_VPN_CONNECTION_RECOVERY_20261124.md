# Nuqati Driver VPN connectivity / recovery — 2026-11-24

## Implemented policy

- **Network check:** every **60 seconds when Nuqati becomes unreachable**, using `GET /api/v1/health` over the phone's currently configured HTTPS network route. A VPN is **not disabled or bypassed**.
- **Upload retry:** exponential backoff with a **strict 300-second maximum**, including jitter. Native Android remains the GPS/trip producer; the existing SQLite import, immutable driver/vehicle ownership, idempotent sample IDs and server acknowledgements are unchanged.
- **Recovery:** on a successful heartbeat or successful Nuqati API health probe, clear the local retry delay, import native GPS records, and resume the existing upload queue; an authenticated heartbeat is requested again.
- **Heartbeat:** v2 Driver app sends authenticated heartbeats **every 60 seconds even while idle**, instead of once per hour. Existing Privacy Mode behavior is respected.
- **Manager notification:** after **15 minutes without authenticated server contact**, the backend creates a persistent company-scoped incident, displays it in the dashboard, and attempts **one email per incident** to the company's active company admins and fleet managers. SMTP attempts retry at least 5 minutes apart if delivery fails. Alert closes after communication resumes or the driver session is revoked / active privacy starts.
- **VPN state diagnostics:** the Android UI reports only whether the active route uses a VPN, has internet capability and is validated. It does not read VPN app names or credentials. The Dart background task can check Nuqati reachability without accessing the UI channel.

## Deployment sequence

1. Replace the changed files from `nuqati-vpn-modified-only-20261124.zip` in the same repository paths, or use the full updated project ZIP. **Do not upload both into each other.**
2. Commit to GitHub and redeploy the **backend and web dashboard in Coolify**. Startup creates `driver_connection_alerts` and adds `connectivity_policy_version` to the heartbeat table (additive PostgreSQL migrations).
3. Confirm the existing `NUQATI_SMTP_HOST`, `NUQATI_SMTP_PORT`, `NUQATI_SMTP_USER`, `NUQATI_SMTP_PASSWORD`, and `NUQATI_EMAIL_FROM` Coolify environment variables are valid. Without SMTP, dashboard incidents still appear, but **emails will not be delivered**.
4. Run the **Driver Android signed AAB** GitHub Actions workflow (`build-driver-release.yml`), upload the new version to your Google Play testing track, then **install the updated Driver app** on test phones. No Manager APK rebuild is required for the dashboard/email alerts.
5. **Rollout safety:** older app installations have hourly idle heartbeats and are **not** eligible for the new 15-minute alert until they have sent a heartbeat containing `connectivity_policy_version=2`. This avoids false positives. A brand-new installation becomes eligible after its first successful v2 heartbeat.

## Test on a dedicated test company/driver

- With VPN on and Nuqati domain permitted: login, drive, confirm live GPS + 60-second heartbeat and no manager alert.
- Block `nuqati.al-riadah.sa` through VPN DNS/network policy while keeping location permission and tracking enabled: observe diagnostics `NETWORK_UNREACHABLE_HEARTBEAT` / `TRACKING_HEARTBEAT_FAILED`. Confirm native GPS still records locally. After at least 15 minutes (plus up to ~60 seconds scan delay), verify the dashboard alert and manager email (if SMTP is configured).
- Restore VPN's network access: within the next available health check, expect `NETWORK_RECOVERED_SERVER_HEALTH` or `NETWORK_RECOVERED_FROM_HEARTBEAT`, queued sample uploads, a fresh heartbeat, and alert removal from the dashboard on the next backend scan/dashboard refresh.
- Test GPS privacy mode with admin approval and logged-out users: no unauthorized location sharing and no alert for inactive sessions/active Privacy Mode.
- Restart the phone with tracking permissions enabled; verify native tracking starts again, and check device battery policy. A mobile OS may delay the background isolate or 60-second timers; **no client app can guarantee real-time execution while killed or heavily battery-restricted**.

## Constraints and safety notes

- If a VPN's firewall or DNS continuously blocks the Nuqati domain, the app **cannot force a network bypass**. Corporate IT must allow HTTPS/DNS or explicitly configure per-app split tunneling.
- The manager alert reports **missed heartbeats**, not proof of a VPN failure or stopped GPS. The manager may see the last uploaded position only.
- Email is the active out-of-app notification path. **Push notifications to the separate Manager app are not implemented** (they require an additional push infrastructure / device registration).
- `GET /api/v1/health` proves the API is reachable; it does not prove the driver's session is valid. Authentication failures remain distinct, logged and must be resolved separately.
- The existing backend currently rejects GPS samples captured **more than 14 days ago**, so extremely long VPN outages may require a separately reviewed offline-retention/replay policy; this patch does not weaken that server-side acceptance rule.
- Existing GPS/trip detection, scoring, privacy approvals, single-device login, session scoping, handover, dashboard reports and driver app screens are not changed by this policy.

## Validation

- Python compile: `backend/app/main.py` and `backend/app/connectivity_alerts.py`.
- New tests cover the exact 15-minute threshold, company scoping and recipient confidentiality.
- 23 targeted regression tests passed, with wider suite also passing 33 tests and 1 skipped. Five older company-editor contract tests remain broken in the **original uploaded source** (`_validate_company_driver_logo` missing); they are unrelated to this patch.
- TypeScript `App.tsx` syntax parsing passed. **A full Flutter/Android release build and frontend dependency-resolved production build were not available locally** and must be verified using GitHub Actions/Coolify.
