# Operations & gotchas

Hard-won operational knowledge for the `coupon_system` + `oxifix_multisite_sync` coupon stack.
If you're an agent about to **deploy, configure, or debug a live site, read this first** — most of
it cost real hours to learn.

## Roles & topology
- **HQ (central)** — the one points ledger + card registry; runs the gateway (routes scans,
  aggregates balances). `site_role` blank; `hq_url` = itself.
- **HQ-backed store (Mode A)** — registers its immutable card defs to HQ; all points live on HQ.
- **Standalone Store (Mode B)** — its own local ledger. `site_role = "Standalone Store"`. Detection
  is **role-based**, via `coupon_system.hq_client.is_self_contained()` — NOT based on `hq_url`. So
  `hq_url` is free to point at a real upstream HQ.
- **Hybrid** — a Standalone Store can also be a gateway target under an HQ: HQ proxies scans *down*
  to it, and it falls back *up* to HQ for foreign codes (`hq_url` = the real HQ).

## Deployment model — the #1 gotcha
Each site is served by its **own** `bench --site <site> serve --port <NNNN> --noreload` process under
supervisor (there is *not* one shared gunicorn). `--noreload` means **code changes are NOT picked up
until that process restarts**. `bench console` loads fresh code, which is misleading. Classic symptom:
an HTTP call returns `module ... has no attribute X` / a 417, while the console works fine.

- **Deploy code to a site = restart its serve process.** Find the pid with `ss -ltnp | grep :<port>`
  and `kill -TERM <pid>` — supervisor respawns it fresh. `sudo supervisorctl` typically needs a
  password; plain `supervisorctl` hits a socket PermissionError. For a gunicorn (`--preload`) box,
  `SIGHUP` does **not** reload either — kill the master and let supervisor respawn.
- Schema/fixtures still need `bench --site <site> migrate` (per site). A migrate does **not** restart
  the server — do both.
- Run bench as the bench owner (e.g. `sudo -u <owner> bench ...`), not root.

## Scan / QR host (broke us for hours)
The mobile app's `extractCouponCode` only strips the code out of a QR URL when `uri.host == SCAN_HOST`
(a build-time env in `config/env.json`). On a host mismatch it ships the **whole URL** as the "code",
so HQ can't find the namespace segment → **"Card not found"** even though the backend is fine. So:
> `Coupon System Settings.scan_base_url` host **must equal** the app's `SCAN_HOST`.
Set `scan_base_url = https://<SCAN_HOST>/s` (the path segment must be `s`). It's read live at QR-gen
time — no restart needed to change it.

## Secrets
Every secret field is a **`Password`** field (encrypted, masked), read via `doc.get_password("field")`
— never a `Data` field, never accessed as `doc.field`. When migrating an existing `Data` secret to
`Password`: **capture the plaintext BEFORE `migrate`**, run migrate, then re-store it with
`set_encrypted_password(...)` — migrate does not move the value into the encrypted store, so an
unmigrated value would otherwise read back empty.

## Gateway wiring — a standalone store under an HQ
Two server-to-server links, each a **dedicated least-privilege service account** (a non-human API
user — its `api_key`/`api_secret`, with just the role it needs):

| Direction | Purpose | Role needed | Where its key lives |
|---|---|---|---|
| HQ → store | proxy a scan / balance | **Coupon Mobile** only | HQ's `Coupon Store.service_api_key/service_secret` |
| store → HQ | standalone foreign-code fallback + reads | **Coupon Manager** (redeem needs it) | store's `HQ Integration Settings.api_key/api_secret` |

Do **not** overload a Coupon Mobile account with Manager. Extra wiring on HQ: the store's
`Coupon Store` row needs a `code_namespace` + `route_scans = 1` + the broker creds, and the store's
own `get_url()` must **exactly** equal that row's `site_url` (the identity rule — pin `host_name`).

Quick health checks:
- `route_store_for_code("<NS>-XXXX-YYYY")` on HQ → resolves to the store.
- From HQ: `gateway.proxy_balance(<store>, "<dummy phone>")` → `{"success": false, "error": "User not
  found"}` proves *reachable + authed* (a 401 / `store_unreachable` means creds or DNS).
- From the store: `coupon_hooks.get_card_info("<foreign code>")` → returns HQ's answer (not local),
  proving the reverse link.

## Balance semantics (bugs we fixed — keep them)
- `balance()` **aggregates** self-contained stores it routes to (concurrent fan-out, best-effort:
  swallow+log failures, skip self, honor the circuit breaker) and folds each in as a store-locked
  bucket with the store's self-reported name.
- A **store-only customer** (points only at a self-contained store, no HQ ledger) must still get their
  balance — do NOT reject an unknown-to-HQ phone before aggregating; return "User not found" only if
  nothing anywhere.
- `total_earned` / `total_redeemed` must **exclude reversals**: a reversal is a `CREDIT` tagged with
  the reversed `invoice_no` (an earn/scan CREDIT has none); net it out of both, or a cancelled
  redemption leaves earned inflated and redeemed overstated. `points_balance` was always correct.

## Debug flow that works
1. Reproduce over **HTTP** (a barcode scanner / real request), not just `bench console` — the running
   `--noreload` server may have stale code.
2. If HTTP disagrees with console → restart the site's serve process.
3. Check the site's dev-server log (supervisor `*.err.log`) for the request line + status.
