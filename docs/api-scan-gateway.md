# API Spec — Single-call scan (HQ gateway scan-router)

**Audience:** the mobile app team and any client that scans coupons.
**One-line contract:** the client makes **exactly one** call — `POST coupon_system.api.scan` on
**HQ** — for *every* code, no matter which store owns it. HQ figures out the rest.

Read `docs/adr/0001–0003` and `gateway.py` for *why*; this is the *what the client sees*.

---

## Why one call

A code can resolve three ways, and the client must not have to know which:

1. **Central / HQ-backed coupon** — the card is registered on HQ. HQ handles it locally.
2. **Self-contained store coupon** — the card lives only on that store's own site. HQ **proxies**
   the scan to the owning store (server-to-server, with creds HQ holds) and relays the result.
3. **Unknown** — no card, no owning store. HQ returns "Card not found".

The client hits **one endpoint** and gets **one response shape** for all three. It never learns a
store was involved (API Gateway + Gateway Routing + Gateway Offloading).

```
 app ──POST scan──▶ HQ ──local card?──▶ yes ─▶ credit HQ ledger ─▶ result
                     │                    no
                     └─ namespace owns a routable store? ─ yes ─▶ POST store.scan ─▶ relay result
                                                            no  ─▶ {success:false, "Card not found"}
```

---

## Endpoint

```
POST /api/method/coupon_system.api.scan
Host: <HQ base url>
Authorization: token <mobile_api_key>:<mobile_api_secret>
Content-Type: application/x-www-form-urlencoded
```

The mobile creds come from `get_mobile_config` (unchanged). Caller must carry one of
`System Manager` / `Coupon Manager` / `Coupon Mobile` — the mobile creds are `Coupon Mobile`.

### Request

| field       | type   | required | notes                                             |
|-------------|--------|----------|---------------------------------------------------|
| `phone`     | string | yes      | customer phone (the wallet identity)              |
| `code`      | string | yes      | the scanned code, e.g. `R1-4F2A-9BQ7`             |
| `full_name` | string | no       | used to create the `Coupon User` on first scan    |

### Response — `200` with a Frappe `message` envelope

Frappe wraps the return value: `{ "message": { ... } }`. The client reads `.message`.

**Success (local *or* proxied — identical shape):**
```json
{
  "success": true,
  "points_added": 10,
  "locked_to_store": "http://store-a:8020",
  "new_balance": 40
}
```
- `locked_to_store` — `null` for a general/central coupon; the store URL when the points are
  locked to a store (both HQ-backed store coupons and proxied self-contained ones).
- `new_balance` — the customer's **total** balance *as known to the site that credited it*.
  For a proxied self-contained store this is that store's local wallet balance. (Cross-store
  aggregation of balances is a separate, later feature — out of scope here.)

**Not found / not routable:**
```json
{ "success": false, "error": "Card not found" }
```

**Store temporarily unreachable (proxy failed / circuit breaker open):**
```json
{ "success": false, "reason": "store_unreachable", "error": "Could not reach the store, please retry" }
```
Other proxy `reason` values the client may see: `store_unavailable` (breaker open, fail-fast),
`store_misconfigured` (no routing creds on HQ — operator error), `bad_response`.

### Client handling rules

- **Only branch on `success`.** Show `error` to the user verbatim when `false`.
- Treat any `success:false` with a `reason` field as **retryable** (transient upstream) — offer a
  retry; don't tell the user the card is invalid.
- `Card not found` (no `reason`) is **terminal** — the code is bad or unknown.
- The client does **not** send anything different for stores. No store URLs, no second call, no
  per-store client. One endpoint, one shape. (No dual paths.)

---

## What changed on the backend (for reviewers)

- `coupon_system/gateway.py` — `route_store_for_code(code)` and `proxy_scan(...)` + circuit breaker.
- `coupon_system/api.py::scan()` — on a local card miss, route by namespace and proxy; else throw
  `Card not found` (previous behavior for truly unknown codes is preserved).
- `Coupon Store.route_scans` (Check, default `0`) — only self-contained stores opt in as proxy
  targets. HQ-backed stores keep `0`; their cards resolve on HQ.

## Resilience contract (server-side, invisible to the client)

- **Timeout** 10s per proxied scan; **1 retry** on the HTTP session.
- **Circuit breaker** per store: a failed proxy trips a 30s cooldown (`coupon_gw_cb:<store>` in
  cache); during cooldown HQ fails fast with `store_unavailable` instead of hanging every scan on a
  dead upstream (bulkhead — one dead store can't stall scans for the others).
- **Auth to the store** uses the per-store `service_api_key` + encrypted `service_secret` on the
  `Coupon Store` row — the same broker creds HQ already uses for token issuance.
