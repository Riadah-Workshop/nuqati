# Nuqati — VPN failover, Driver build repair & dashboard phone-queue visibility

Baseline: `nuqati-main(20261124-104230).zip` (24 November 2026).

## Included changes

1. Fixed the unmatched `)` around original `mobile/main.dart` line ~850 and made `min(300, exponential delay + jitter)` cap the **whole** retry period at 300 seconds.
2. Added a build-time, **optional** HTTPS backup hostname `NUQATI_FALLBACK_API`, protected by an allowlist of `al-riadah.sa` domains and independent per-host request timeouts. Read requests and known receipt-based/idempotent background POST operations may retry. Non-idempotent account/vehicle-handover submission operations are **not automatically replayed** when the first HTTP response could have been lost. No VPN bypass is used.
3. Updated Driver Android GitHub build workflows to copy `mobile/nuqati_network.dart` into generated Flutter `lib/` and run Flutter static analysis ahead of the expensive Android build. The signed release workflow passes the optional fallback repository variable into the AAB.
4. Extended the existing 60-second authenticated heartbeat with `queued_gps_points`, `queued_safety_events`, and `queued_trips` based on phone-local SQLite. Existing older Driver apps can omit these fields. The backend adds nullable columns in PostgreSQL without removing existing rows.
5. Live Tracking now displays a per-driver table with **last seen by server**, connection freshness, and last-reported phone queues. Privacy Audit > Tracking also shows phone queues. When a heartbeat is stale, an asterisk and explanation warn that the queue may have grown; a stale location is **not** interpreted as a stopped trip.

## Configure a real backup hostname (required for automatic failover)

Do **not** enter a made-up or unrelated domain. Provision a domain you control such as an owned `*.al-riadah.sa` hostname, configure DNS and a trusted TLS certificate, and route `/api/v1/*` to **the exact same production API and Postgres database** as `nuqati.al-riadah.sa`. A CDN hostname is suitable only if it preserves authorization, request methods, and `/api/v1/*` paths; do not cache or expose private responses. Verify both endpoints with `https://<your-verified-secondary-host>/api/v1/health` and expect JSON `{"status":"ok","service":"nuqati-api",...}`. Then set the GitHub repository Actions variable `NUQATI_FALLBACK_API=https://<your-verified-secondary-host>` (no path). If no backup is provisioned, leave the variable empty; the app retains single-host behavior.

**Warning:** If a VPN or firewall blocks all of `al-riadah.sa`, this backup host may be blocked too. IT should allow the relevant HTTPS hostname(s) and DNS. Split tunneling for Nuqati is a VPN-provider/IT setting and may be forbidden under corporate policy. The app never binds traffic outside the VPN.

## Validate with an actual Android device

1. Confirm that `https://nuqati.al-riadah.sa/api/v1/health` works in Chrome with the VPN **OFF**, then enable the driver's VPN and try the same URL in Chrome. Save the exact Chrome error. `ERR_NAME_NOT_RESOLVED` suggests DNS; connection timeout/reset suggests VPN firewall/routing; a certificate warning suggests TLS interception. A Chrome success does **not** prove the app route works, so also inspect Nuqati Diagnostics.
2. If the primary fails, visit `https://<verified-secondary-host>/api/v1/health` **on the same VPN**. An alternate host can help only if it is reachable through that VPN.
3. Install the new signed Driver release. While authenticated, record a trip offline and restore the connection. Confirm server receipts and queue counters decreasing after successful uploads; the server must never delete local records solely because of a probe.
4. In Dashboard > Live Tracking, compare “Last seen” and queue counts for this driver, then wait for at least two heartbeat periods with network down and confirm the row displays stale/unknown, **not** stationary. The queue count is the *last successfully transmitted snapshot* and may not equal the phone's current unsent data.
5. Test continuous VPN usage, split tunnel if approved, device restart, private mode, and loss/recovery of both primary and secondary domains. The 15-minute backend connection-alert policy and 60-second health probe remain in place.

## Build/deploy

- Merge the patch into your GitHub repository, preserve existing release secrets and repository vars (`DRIVER_APPLICATION_ID`, `NUQATI_PRODUCTION_API`). Set `NUQATI_FALLBACK_API` only after testing the secondary host.
- In GitHub > Actions, select **Build Nuqati Driver signed AAB (Google Play)** (`build-driver-release.yml`) and click **Run workflow** on the updated branch. Check the **Analyze Driver API and app Dart source** and **Build signed Google Play AAB** steps. The workflow creates a draft release on success.
- Deploy backend first (additive heartbeat column migration), then web, and distribute the new Driver app to testers. Older apps continue to work with null phone-queue fields.

## Verification scope

Local Python/TSX parsing and regression tests are run on the provided source. **No actual Android phone, VPN account, signed Google Play keystore, GitHub Action runner, or production Coolify service is accessible in this workspace.** No live VPN test or signed AAB build is claimed here.
