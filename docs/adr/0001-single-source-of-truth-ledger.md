# ADR-0001: HQ is the single source of truth; the store is a writer, not an owner

- **Status:** Accepted
- **Date:** 2026-07-21
- **Deciders:** project owner + engineering

## Context

We are adding **store-issued coupons**: a store pre-generates coupon codes, hands one to a
customer against a Sales Invoice, the customer scans it to earn points, and later redeems those
points as a discount at that store. Points earned this way are **store-locked** (spendable only
at the issuing store); points from the existing **central** program stay **general** (spendable
anywhere). The customer app must show one combined balance (e.g. 100 general + 10 store = 110)
with a breakdown.

The store runs on a **separate site** from HQ (it owns its own Sales Invoices). The cross-site
**broker** that mints HQ→store *user tokens* is unavailable for ~2 months.

The core question: where do the two point pools live, and how are they combined for the app?

We evaluated the full pattern space (researched against microservices.io / Chris Richardson,
Azure Architecture Center, Debezium, and real loyalty/fintech systems):

1. **Client-side composition** — app calls both backends and sums. Rejected: ships business
   logic into an un-hotfixable app, couples it to two topologies, multiplies mobile round-trips.
2. **Server-side aggregator (API Composition / Gateway Aggregation in a BFF)** — one HQ endpoint
   fans out at read time and merges. Rejected as the primary model: a **spendable** balance
   synthesized by summing two independently-mutating databases has **no atomic transaction
   boundary**, so a fan-out race or retry permits **double-spend**. Read-time aggregation is
   acceptable for *display*, dangerous for *spending*.
3. **CQRS materialized view via outbox + CDC** — store keeps its own ledger, streams events to a
   HQ read model. Correct but heavy: eventual consistency, sync infrastructure, reversal
   propagation. Not an emergency build, and unnecessary unless the store must run offline.
4. **Single source of truth** — HQ owns the one ledger; the store is a *writer*. This is what
   airline alliances (credit into one home program) and fintech wallets (one double-entry
   ledger, entries tagged by source) actually do for money-like balances.

The deciding fact: **the store does not need to transact while HQ is unreachable.** HQ is
assumed reachable at the moment a coupon is given, earned, or redeemed. (If that ever stops
being true, revisit toward option 3.)

## Decision

**HQ owns the single `Coupon Ledger`. The store site is a writer into it, not the owner of a
separate points pool.**

- Every point lives in HQ's ledger, tagged with a **bucket**: `general` (central) or a specific
  **store** (store-locked).
- The store site posts point events (give / earn / redeem) to HQ over **service credentials**
  (`Coupon Store.service_api_key` / `service_secret`), which is a plain API-key call — it does
  **not** depend on the blocked user-token broker.
- The customer app reads **one** HQ endpoint. No merge exists anywhere, because there is only
  one owner. The balance is atomically spendable.

## Consequences

**Positive**
- One read path for the app; "one place to see both pools" is free.
- Spending is safe — a single ledger with a real transaction boundary; no cross-DB double-spend.
- No dependency on the blocked broker; no sync/CDC infrastructure to build now.

**Negative / accepted trade-offs**
- The store site depends on HQ being reachable to give / earn / redeem. Accepted (see deciding
  fact). Degraded-mode behavior when HQ is down is out of scope for this build.
- HQ becomes a hard dependency in the store's checkout path — needs sane timeouts and clear
  error surfacing so a slow HQ never wedges an invoice.

## Follow-ups (grilled separately)

- Where the store-coupon **cards** are registered (HQ vs store-mirrored).
- Whether store-locked points are **withdrawable** as cash (leaning: no).
- **Spend allocation** order across buckets (leaning: store-locked first).
- **Reversal** shape when a redemption spans buckets.
- Naming split: `redeemable_at_stores` (campaign) vs `points_locked_to_store` (card).
