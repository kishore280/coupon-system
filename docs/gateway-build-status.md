# Gateway scan-router — build status & handoff

Single-call HQ gateway: the app makes **one** `scan()` call to HQ; HQ resolves locally or proxies
to the owning self-contained store. Built autonomously during the `/loop` break.

## Done ✅

| Area | What | Where |
|------|------|-------|
| Router | `route_store_for_code`, `proxy_scan`, `_proxy` + per-store circuit breaker | `coupon_system/gateway.py` |
| Wiring | `scan()` routes+proxies on a local card miss, else "Card not found" | `coupon_system/api.py` |
| Schema | `Coupon Store.route_scans` Check (default off) — only self-contained stores opt in | `.../doctype/coupon_store/coupon_store.json` |
| Tests | route match, non-routable ignored, proxy on unknown code, unknown-no-route→not-found | `coupon_system/tests/test_store_buckets.py` |
| Spec | client-facing contract (one endpoint, one shape, retry reasons, resilience) | `docs/api-scan-gateway.md` |
| PR | commits on `feat/store-locked-coupons` → PR #13 (comment added) | github |
| App PR | store-locked breakdown + scan lock badge; `flutter analyze` clean | influlync_grozfy #41 |

## Linus-level review — fixed
- **Non-idempotent retry**: dropped `max_retries` 1→0 on the proxy POST — a retry after the store
  commits could double-credit or surface a false "already used". One attempt; breaker + client retry
  cover transients. (commit `320cf7f`)

### Reviewed & accepted (no change)
- **Namespace match** uses `code_namespace IN <all hyphen segments>` filtered to `route_scans=1,
  is_active=1`. A random code segment colliding with a real namespace is possible but harmless: the
  wrongly-routed store won't hold the card and returns `Card not found` — same outcome as no route.
  `code_namespace` is unique, so no two stores contend.
- **Relay**: store `ValidationError` comes back as HTTP 200 `{success:false,...}` and is relayed
  as-is; only transport/5xx failures trip the breaker.

## BLOCKED — needs the user (server ops, auto-mode classifier denied while away) ⛔

Running the tests needs the `route_scans` column on the site, i.e. a migrate of the shared HQ
site — denied as a production deploy I wasn't authorized to run unattended. Run when back:

```bash
ssh oxifix
cd ~/frappe-bench
bench --site oxifixprivateltd.com migrate                     # picks up route_scans
bench --site oxifixprivateltd.com run-tests \
  --module coupon_system.tests.test_store_buckets             # the 4 new gateway tests + rest
```

Then a live end-to-end (HQ `oxifixprivateltd.com` → self-contained `oxifixretail1.com`):
1. On HQ, set the `Coupon Store` row for `oxifixretail1.com`: `route_scans = 1`, and confirm
   `service_api_key`/`service_secret` are a Coupon Mobile/Manager user **on the store**.
2. Mint a card on the store (namespaced code, e.g. `R1-…`).
3. Call HQ `scan(phone, "<that code>")` with the **mobile** creds → expect the store's result
   relayed (`success:true`, `locked_to_store = http://…retail1…`).
4. Stop the store site → scan again → expect `{success:false, reason:"store_unreachable"}`, and a
   fast-fail `store_unavailable` within the 30s breaker window.

## Deferred (as agreed)
Cross-store **balance aggregation** — the app currently shows each site's own wallet total. Next up.
