# Coupon System — Domain Glossary

Canonical terms. Pure glossary — no specs, no implementation notes. Update inline as
terms resolve. When two words mean one thing, or one word means two, fix it here first.

## Status legend
- ✅ established (verified in code or confirmed by owner)
- 🚧 proposed / under grilling (not yet confirmed)
- ⚠️ contested (one word doing two jobs — must split)

---

## Prior art (don't reinvent — validated against these)
- Ledger shape → `formancehq/ledger`, `tigerbeetle/tigerbeetle` (single-writer, append-only,
  account-address scoping). Gift-card/value → `Giftbit/lightrail-rothschild`. Coupon-def-vs-
  redemption → Medusa/Saleor/Sylius promotions. Store-locked = **closed-loop restricted value**.
- Immutable-def replication = **event-carried state transfer**; only immutable data is replicated,
  mutable money stays single-writer on HQ. (ADR-0003.)

## Sites & deployment
- **HQ site** ✅ — the site where `coupon_system` is installed today; single source of truth
  for all coupon/points data. Branches call its API.
- **Store site** ✅ — a separate site that holds its own **Sales Invoices** and generates/hands
  out store coupons, but is a **writer** into HQ's single ledger — it does **not** own a points
  pool. (SSOT; see ADR-0001.)
- **SSOT (single source of truth)** ✅ — HQ owns the *one* `Coupon Ledger`. The store posts
  point events into it (bucket-tagged) via **service creds** (not the blocked user-token
  broker). App reads one place → no merge, atomically spendable. (ADR-0001.)
- **Store autonomy** ✅ — **not required.** HQ is assumed reachable at give / earn / redeem.
  This is what makes SSOT viable. (ADR-0001.)
- **Broker** ✅ — HQ mechanism that mints short-lived tokens on a *remote* store so HQ can
  act there without storing passwords. Only relevant when two sites talk. Blocked ~2 months.

## Hard constraints
- **Mobile client stays dumb-simple** ✅ — the app hits **one HQ endpoint** for scan + balance.
  No merging, no "which server", no multi-call logic in the client. All complexity lives
  server-side. (This is why stores must register card definitions to HQ — HQ must resolve any
  code alone.)
- **Infra reality** ✅ — just separate ERPNext servers (HQ + each store). No shared DB, no message
  bus. Sync between them = plain ERPNext-to-ERPNext API calls, only for **immutable** data.

## Data ownership (confirmed: option (a))
- **Store owns**: its campaigns, its card **definitions** (immutable), and its own reporting —
  locally, on its server. Stores **mint locally** and **register definitions up to HQ**.
- **HQ owns**: the single points **ledger** + the **consumed-code** set (the only mutable money
  state; single writer → no double-spend). Plus a replicated read-copy of every store's immutable
  card definitions so it can resolve a scan on its own.

## Actors
- **Customer** ✅ — a person identified by phone; owns a points balance. Uses the mobile app.
- **Cashier / store staff** 🚧 — creates Sales Invoices, hands out and redeems store coupons.

## Business framing (confirmed)
- **First-party store** ✅ — the company was a manufacturer (central boxed-coupon program) and
  has now opened its **own** retail store. The "store" is not a franchise/third party.
- **One app, one account, one wallet** ✅ — every customer uses the single existing app. Central
  and store points live in the same account; the store slice is merely *locked*, not separate.
- **Why store-locked** ✅ — the store funds the reward from its own budget to drive **repeat
  visits to that store**; therefore its points must not be spendable centrally or at other stores.
- **Multi-store from day one** ✅ — first store now, **several more within ~2 months**. Points are
  keyed **per store**; a customer can hold general + multiple independent store buckets at once.
  Each new store: a `Coupon Store` on HQ + thin client + allocated code namespace + service creds.
  (Broker stays irrelevant — SSOT writes use service creds, not the blocked user-token broker.)

## Coupons & cards
- **Coupon Card** ✅ — one physical code. Has `code`, `campaign`, `status`, `points_value`
  (snapshot fallback), `expiry_date`, `is_used`. **Always registered on HQ** (ADR-0002).
- **Thin client** ✅ — the store site. Owns **no** coupon doctypes; calls HQ over service creds
  to generate / give / redeem / reverse. May hold a non-authoritative cached read copy only.
- **Idempotency key** ✅ — required on generate / give / redeem so an invoice-time retry acts
  exactly once (ADR-0002).
- **Central coupon** 🚧 — a card minted centrally (Work Order at manufacturing), inserted in
  product boxes. Points earned from it are **general**.
- **Store coupon** 🚧 — a card pre-generated at a store, handed to a customer at invoice time.
  Points earned from it are **store-locked**.
- **Coupon Campaign** ✅ — the value dial; `points` resolved live at scan, plus `is_active`,
  `end_date`, `allowed_stores`. Governs **Clock A** (coupon shelf-life via `validity_months` →
  card `expiry_date`) — reused as-is for store coupons.
- **Clock A (coupon shelf-life)** ✅ — how long a coupon stays valid *to scan*; campaign-controlled,
  already exists. **Sufficient for launch.**
- **Clock B (banked-points expiry)** 🚧 — points dying N months after being earned. Does **not**
  exist today. **Deferred**; if ever built, add as a campaign field for consistency.

## Points & ledger
- **Coupon Ledger** ✅ — immutable append-only rows; `type` = CREDIT / DEBIT. Balance = SUM.
- **General points** 🚧 — spendable anywhere. Come from central coupons. (proposed bucket = NULL)
- **Store-locked points** ✅ — usable **only at the issuing store**, but the lock is purely
  *locational*: **at** that store they are fully fungible with general points (discount, cash-out,
  combine). Away from it, frozen and shown as "locked to Store X". (bucket = a store)
- **Bucket** ✅ — the scope a point belongs to: general (NULL), or a specific store.
- **Balance (total)** ✅ — SUM(CREDIT) − SUM(DEBIT), all buckets. The number the app shows (e.g. 110).
- **Available-at-store** ✅ — what a customer can transact at store S = general + bucket(S).
  Every operation at S (redeem, withdraw) draws from this pool; **store-locked drained first**
  (engineer's call — business is indifferent to combine-vs-separate). bucket(Y≠S) is excluded.

## Verbs (currently fuzzy — sharpen these)
- **Give** ✅ — a store hands a pre-generated store coupon to a customer **in person, by any
  means** (at purchase, a promo, a counter giveaway — trigger doesn't matter). Store coupons are
  **never shipped in boxes** (that's the central channel). Recording the coupon on a Sales
  Invoice is **optional traceability**, not the mechanism, and does *not* move points.
  Earning still happens at **scan**, identical to the central flow.
- **Earn / Scan** ✅ — customer scans a card → CREDIT points (`scan()` in `api.py`).
- **Redeem** ✅ — spend points → DEBIT, tied to an invoice (`redeem()`), idempotent per invoice+store.
  **Always POS-initiated by store staff** at a store; establishes the store context. The customer
  **cannot self-redeem** in the app (app = scan-to-earn + view balance only). General points
  redeem at any store's POS; store-locked points only at their store's POS. No online/self-serve
  spend channel planned.
- **Reverse** ✅ — undo a redemption on invoice cancel via a compensating CREDIT (`reverse_redeem()`).
- **Withdraw** ✅ — cash out points via Coupon Withdrawal Request (locks, then DEBIT on Paid).
  **At launch, withdrawable = general points only**; store-locked points are excluded (cash-out
  of store points is deferred). When store cash-out ships later, **store X funds it** (cost
  attributed to that store, never central).

## Campaign ownership (confirmed)
- **`owned_by_store`** ✅ — a field on **Coupon Campaign**. NULL = central campaign → earned points
  are **general**. Set to store X → the campaign is store X's; earned points **lock to bucket X**.
  This is the single knob that drives the store-lock, riding on the campaign control model the
  owner already trusts. **Each store runs its own campaigns** (can have several).
- A customer earns **only** from the campaign of the store whose coupon they were physically handed.
- **Store closure** ✅ — when a store is deactivated, points locked to it are **frozen** (unusable,
  still shown as locked) **until an admin decides** their fate. No automatic convert/write-off.

## Resolved: the "store restriction" overload (was contested)
Two genuinely different axes — keep them distinct, never merge:
- **`owned_by_store`** ✅ (campaign) — *whose budget funds it / which bucket points lock to.* NEW, drives the lock.
- **`allowed_stores`** ✅ (campaign, existing) — *where a physical card may be redeemed as a points
  source* (the `redeem(code=…)` path). Different concern. Whether it's still needed under the new
  model is a **design** question, not a naming one — deferred to the design pass.
