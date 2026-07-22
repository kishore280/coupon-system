# Build Spec — Store-Locked Coupons

Grounded in `CONTEXT.md` + ADR-0001/0002/0003. This is the concrete work. Nothing here is a
phase — it's the full launch surface. Deferred items are listed explicitly at the end.

> **REVISION (2026-07-21) — redemption is REUSED, not rebuilt.** The store-side redemption hooks
> and custom Sales Invoice fields described below were **removed**: `oxifix_multisite_sync` already
> implements the complete redemption (show-balance-by-phone → GL entries for the discount → POST
> `coupon_system.api.redeem` with `site_url = get_url()`) and reverse-on-cancel. Because HQ's
> `redeem()` is now bucket-aware, that unchanged flow spends store-locked points automatically.
> So **the store side of coupon_system is MINTING ONLY** (`store_mint`/`register_cards`), and its
> `hq_client` reads the HQ connection from **`HQ Integration Settings`** (not its own config).
> "F1 (no discount)" is moot — the sync app does the accounting. **Identity:** a store's bucket key
> is `get_url()`, so each store's `host_name` MUST be pinned in site_config, and its `Coupon Store`
> name on HQ must equal that exact value (scheme+host+port).

Terminology: **HQ** = the central site (owns ledger + resolution registry). **Store site** = a
store's own ERPNext (owns its campaigns, its immutable card defs, its reporting; never the ledger).

---

## 0. Design decisions (grounded in established systems — not judgment calls)

- **D1 — Snapshot the value onto the coupon at issuance (gift-card model).**
  A coupon carries a concrete "N points" *value*, so it is a value-bearing instrument, not a live
  discount rule — and every major system freezes such value per-instance: **Square** (gift-card
  balance set at activation, moves only via append-only activity records), **Shopify** (gift cards
  "always set to a monetary amount"; discounts are the thing evaluated live), **Stripe** (the
  `Coupon` value object is immutable — you mint a new one, never revalue issued ones). The governing
  rule: *editing a campaign must never silently revalue coupons already in customers' hands.*
  So a store card's `points_value` is snapshotted at mint; HQ resolves from the snapshot. This also
  keeps replication immutable (ADR-0003). Trade-off (accepted): no retroactive revalue of store
  coupons; campaign still controls value-at-mint + validity + retire.
  Refs: Square Gift Cards API; Shopify gift-card overview; Stripe Coupon object (immutable).

- **D2 — One codebase, role selected by config (`site_role = HQ | Store`).**
  Universal norm: **Twelve-Factor** (one build, config selects deploy — don't bake roles into the
  artifact), **Odoo / ERPNext** (one codebase, one DB, role/company by permission + switcher, never
  separate binaries). POS vendors split terminal UI vs back-office UI over one shared platform, not
  forked role builds. So: same `coupon_system` app; in Store mode the `Coupon Ledger` is never
  written locally (scan/redeem/balance proxy to HQ, hard guard rejects local ledger writes); the
  local `Coupon Card`/`Coupon Campaign` tables ARE used (the store's authoritative defs).
  Refs: 12factor build/release/run + config; Odoo multi-company; ERPNext single-codebase.

- **D3 — Add a new explicit field; leave the legacy path untouched (overloading is the anti-pattern).**
  Every mature promo engine models restrictions as distinct, typed, composable objects rather than
  widening an existing field: **Medusa** (`PromotionRule`), **Voucherify** (independent validation
  rules), **Stripe** (separated immutable `Coupon` from a distinct `PromotionCode` restrictions
  object). So `owned_by_store` is a *new explicit* field; the existing `allowed_stores` +
  `redeem(code=…)` path stays untouched for launch and is not overloaded to carry the new lock.
  Refs: Medusa PromotionRule; Voucherify validation-rules reference; Stripe Coupon vs PromotionCode.

---

## 1. Component responsibilities

| | HQ site | Store site (Store mode) |
|---|---|---|
| Points ledger (`Coupon Ledger`) | **owns, single writer** | never written; proxies to HQ |
| Card registry (`Coupon Card`) | replica of store defs + central cards | **owns its immutable defs** |
| Campaigns | central campaigns | **owns its campaigns** (`owned_by_store` = self) |
| Minting | central (Work Order / desk) | **local**, namespaced, then `register_cards` → HQ |
| Scan (earn) | **serves** app→HQ | n/a (app talks to HQ) |
| Redeem (spend) | **serves** ledger debit | Sales Invoice hook calls HQ, applies discount |
| Reporting | all coupons (oversight) | its own coupons |

---

## 2. Data model changes

**`Coupon Ledger`** (HQ) — the scoping field:
- `bucket_store` — Link → Coupon Store, nullable. NULL = general; else the store the points are
  locked to. `(phone, bucket_store)` **is the account address** (ADR-0003).

**`Coupon Card`** (both sites):
- `origin` — Select [Central, Store], default Central, search_index.
- `store` — Link → Coupon Store; set when `origin = Store`; **the bucket** the earned points lock
  to (denormalized so HQ resolves a scan without the store's campaign).
- `source_invoice` — Data; optional traceability (which invoice handed it out). Store-side only.

**`Coupon Campaign`** (both sites):
- `owned_by_store` — Link → Coupon Store, nullable. NULL = central → general points. Set → store's
  campaign → its coupons lock to that store. On a store site this defaults to that site's store.

**`Coupon Store`** (HQ; also referenced by store site):
- `code_namespace` — Data, unique, required. The allocated per-store code segment (e.g. `S042`).
- (existing) `service_api_key` / `service_secret` — used store→HQ for register/redeem/reverse.
- (existing) `is_active` — 0 ⇒ store closed ⇒ its bucket points frozen (see §7).

**Sales Invoice** (store site) — custom fields via `ensure_custom_fields`:
- `custom_coupon_given` — Data; scan a pre-generated store coupon being handed out (traceability).
- `custom_coupon_redeem_phone` — Data; the customer redeeming points on this invoice.
- `custom_coupon_redeem_points` — Int; points to spend on this invoice.

---

## 3. HQ API surface (`hq_api.py` / `api.py`)

All gated by role; store→HQ calls authenticated by service creds. Idempotency keys mandatory.

- **`register_cards(store, cards, idempotency_key)`** — NEW. Store calls at mint. Inserts immutable
  defs into HQ `Coupon Card` (`origin=Store`, `store`, `code`, `points_value`, `expiry_date`,
  `campaign` name for trace). Unique index on `code` = the collision/replay backstop; re-register of
  an existing identical code is a no-op success. Rejects a code whose prefix ≠ the store's namespace.

- **`scan(phone, code, full_name=)`** — MODIFY. After resolving the card, credit with
  `bucket_store = card.store if card.origin == "Store" else None`. Value: campaign-live for central,
  `points_value` snapshot for store (D1). Everything else (single-use, lock, savepoint) unchanged.

- **`balance(phone)`** — MODIFY to the dumb-simple app contract (§6). One call, pre-merged.

- **`redeem(phone, amount, store, invoice_no, idempotency_key)`** — MODIFY:
  1. **Lock the `Coupon User` row** (`for_update`) — fixes the current unlocked-overspend race.
  2. `avail = buckets[None] + buckets.get(store, 0)`; reject if `amount > avail`.
  3. Allocate **store-locked first, then general**:
     `from_store = min(amount, buckets.get(store,0))`, `from_gen = amount - from_store`.
  4. Post DEBIT rows: `(from_store, bucket_store=store)` and/or `(from_gen, bucket_store=None)`,
     both carrying `invoice_no` + the redeeming `store` as transaction context.
  5. Idempotent per `(invoice_no, store)`. Returns `amount` so the store hook sets the discount.

- **`reverse_redeem(invoice_no, store)`** — MODIFY: reverse **all** DEBIT rows for that invoice,
  each CREDITed back into **its own** `bucket_store`. (Fixes the single-row reversal bug.)

- **`request_withdrawal(phone, points, …)`** — MODIFY: withdrawable = **general bucket only**
  (`buckets[None]`), excluding store-locked points. (Launch scope; store cash-out deferred.)

- **`generate_cards` / `bulk_generate_cards` / `_generate_batch`** — accept + persist `origin` and
  `store`. On HQ these mint central cards; the store site uses its local generate + `register_cards`.

---

## 4. Ledger scoping helpers (`api.py`)

- **`_buckets(phone)`** → `{None: gen, "<store>": pts, …}` via one GROUP BY on `bucket_store`.
  Single source — collapse the duplicated query in `balance()` into this (fixes the DRY rot).
- `_get_balance(phone)` = `sum(_buckets(phone).values())` (back-compat total).
- `_available_at(phone, store)` = `buckets[None] + buckets.get(store, 0)`.
- `_withdrawable(phone)` = `buckets[None]`.
- `_post_ledger(..., bucket_store=None)` — thread the bucket through the one writer.

---

## 5. Code namespacing (`api.py`)

- Store code = `{brand}-{code_namespace}-{rand}` (e.g. `OXFX-S042-4K7M`). Keep the existing
  unambiguous no-vowel alphabet. Namespace makes independent minting collision-free by construction;
  HQ's unique index is the authoritative backstop (ADR-0003).
- Central code stays `{brand}-{rand}` (or a reserved central segment).
- Luhn/mod-N check char — **optional P1** (reject typos before a DB hit). Not launch-blocking.

---

## 6. App-facing balance contract (dumb-simple, one call)

```
balance(phone) → {
  total,                       # e.g. 110
  general,                     # 100
  restricted: [                # per-store buckets
    { store, store_name, points }   # e.g. {"S042","MG Road",10}
  ],
  # available_here is server-computed ONLY if the caller passes a store context
}
```
App never sums buckets or calls a second server. All merging is server-side (BFF).

---

## 7. Store-side flow (Store mode)

- **Mint:** desk/generate creates local `Coupon Card` defs (namespaced) → calls
  `register_cards(store=self, …, idempotency_key)` to HQ. If HQ unreachable → mint fails cleanly
  (HQ-reachable assumption, ADR-0001).
- **Give (optional):** `custom_coupon_given` on submit → stamp `source_invoice` on the local card
  (traceability). No points move.
- **Redeem:** `custom_coupon_redeem_phone` + `_points` on submit → call `redeem(store=self,
  invoice_no, idempotency_key)`; on success set the invoice `discount_amount` from returned points ×
  rate. Savepoint-isolated; a slow/failed HQ surfaces a clear error and does not silently discount.
- **Cancel:** `on_cancel` → `reverse_redeem(invoice_no, store=self)`.
- **Store closure:** set `Coupon Store.is_active = 0` on HQ → sweep its unused cards to Retired;
  its bucket points are **frozen** (excluded from `_available_at` everywhere) until an admin acts.

---

## 8. Tests (all in the launch pass)

- scan store card → CREDIT lands in `bucket_store=X`; total rises; general unchanged.
- `_available_at(X)` excludes `bucket(Y)`; redeem at Y cannot touch X's points.
- redeem drains store-locked first, then general → two correct DEBIT rows, right buckets.
- insufficient when `amount > general + bucket(X)` even if grand total (incl. Y) is higher.
- reverse_redeem restores **each** debit row into its own bucket (multi-row).
- withdrawal excludes store-locked points (only general withdrawable).
- `register_cards` idempotent per code; rejects wrong-namespace code; replay = no-op.
- redeem idempotent per `(invoice_no, store)`; concurrent redeem on one phone can't overspend (lock).
- balance() returns total + general + per-store breakdown.
- store closure freezes its bucket (not spendable, still shown).
- namespaced code uniqueness across two simulated stores.

---

## 9. Deferred (documented, not built now)

- **Clock B** — banked-points expiry (would become a campaign field).
- **Store-point cash-out** — withdrawal of store-locked points, **funded by that store**.
- **Luhn check digit** on codes (P1 hygiene).
- **Admin tooling** for resolving frozen points after a store closes (convert/write-off).
- **Retroactive revalue** of store coupons (D1 trade-off) — only if business later demands it.
