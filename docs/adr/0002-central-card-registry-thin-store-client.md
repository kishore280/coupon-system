# ADR-0002: HQ owns the ledger + a resolution registry; stores own their immutable defs

- **Status:** Accepted, then **revised** (see "Revision" below) by the data-ownership grilling
- **Date:** 2026-07-21
- **Deciders:** project owner + engineering
- **Extends:** ADR-0001 (single source of truth); **see also** ADR-0003 (ledger scoping + replication)

> **Revision (2026-07-21):** the original "store is a *bare* thin client that owns no coupon
> doctypes" was too aggressive. Business requires each store to **own its campaigns, its card
> definitions, and its own reporting** locally. Refined model: stores own their **immutable**
> card/campaign data and **register (replicate) definitions up to HQ**; HQ holds the replica so
> it can resolve any scan alone (keeps the mobile client dumb-simple). The store is a thin client
> **for the ledger only** — it is **never** a ledger/points writer. Mutable money state stays
> solely on HQ. See ADR-0003.

## Context

ADR-0001 made HQ the single owner of the points **ledger**. This ADR settles where the coupon
**cards/codes** live, and what runs on the separate store site. There is **no** pre-existing
store minting process to accommodate (confirmed with owner — earlier assumption was wrong).

A coupon card is one aggregate: identity (code) + balance/points + lifecycle. Research
(Square, Stripe, Adyen, microservices.io single-writer / database-per-service) is consistent:
the code registry lives **centrally with the ledger**, and the point-of-sale terminal is a
**thin client** calling a central API. The decisive real-world tell: Square queues ordinary
card payments offline but **refuses to redeem gift cards offline**, because code+balance
authority is central and cannot be validated without connectivity.

A store-side *authoritative* mirror would reintroduce double-issue, double-redeem, and
reconciliation — the very split-brain SSOT eliminated — and buys nothing while HQ is reachable.

## Decision

1. **Cards live on HQ.** A store coupon is a `Coupon Card` row on HQ with `origin = Store` and
   `points_locked_to_store = X`. HQ owns cards *and* points — one writer for the whole aggregate.
2. **The store site is a thin client.** It owns **no** coupon doctypes (no local `Coupon Card`,
   no local `Coupon Ledger`). It calls HQ over service credentials to generate / give / redeem /
   reverse. At most it keeps a **non-authoritative cached read copy** for display — never a writer.
3. **Idempotency keys are mandatory** on generate, give, and redeem, so an invoice-time retry
   hands out one card and burns points once — not twice.

## Consequences

**Positive**
- Single writer for the whole card+points aggregate; no cross-registry double-spend.
- Store footprint is tiny → fast to ship.
- Retriable, exactly-once issue/redeem via idempotency keys.

**Negative / accepted**
- Store give/redeem require HQ reachable (already accepted in ADR-0001).
- HQ sits in the store checkout path → needs timeouts + clear error surfacing so a slow HQ
  never wedges an invoice.

## Open (grilled next)

- **Packaging** of the thin client: same `coupon_system` app in a "Store mode" that ignores its
  local tables, vs a separate minimal companion app with no coupon doctypes at all.
