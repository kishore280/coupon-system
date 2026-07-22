# ADR-0003: Point scoping by account-address; immutable definitions replicated to HQ

- **Status:** Accepted
- **Date:** 2026-07-21
- **Deciders:** project owner + engineering
- **Extends:** ADR-0001 (single ledger on HQ), ADR-0002 (store owns immutable defs)

## Context

We need "general" points (spend anywhere) and "store-locked" points (spend only at store X) in
one wallet, across multiple stores each on its own ERPNext server, with a dumb-simple mobile
client and no shared DB / message bus. We validated the shape against established systems
(Formance Ledger, TigerBeetle, Lightrail Rothschild, Medusa/Saleor promotions). Two of their
conventions sharpened our first-cut design:

1. Restricted funds are modeled as **distinct ledger accounts** (account-address scoping), not a
   flag on otherwise-mingled entries. (Formance escrow-named accounts; TigerBeetle per-code accounts.)
2. Global code uniqueness comes from **namespaced prefixes** (collision-free by construction), but
   the authoritative "registered / consumed" state must be a **central constraint on HQ**.

Store-locked points are the well-known **closed-loop restricted-value** pattern (gift cards
scoped to a merchant, HSA/FSA, multi-currency wallets).

## Decision

1. **Scope by account identity.** A customer's balance is partitioned into accounts keyed by
   `(phone, bucket)` where `bucket` = `general` (NULL) or a specific store. "Available at store X"
   = `general + store-X` accounts. Spending at X is a *routing* decision (which accounts the POS
   may debit), not a per-row filter. In the Frappe ledger this is the `bucket_store` field on each
   `Coupon Ledger` row — the `(phone, bucket_store)` pair *is* the account address.

2. **Immutable definitions replicate store→HQ (event-carried state transfer).** Stores mint
   coupons locally with a store-namespaced code prefix and register the immutable card definitions
   to HQ over service creds, at mint time. HQ keeps the replica so a scan (app→HQ) resolves value /
   store / expiry without calling the store. Because definitions never mutate, replication is
   conflict-free — this is NOT the mutable-ledger replication we rejected in ADR-0001.

3. **HQ is the uniqueness + consumption authority.** A UNIQUE index on `code` at registration and
   the append-only ledger (a code can be credited once) are the real backstop. Prefixes are hygiene;
   HQ is the law.

4. **Never a per-store ledger.** A store minting a *code* does not create *value*; value is always
   an HQ ledger write. Stores hold immutable defs + reporting, never a points balance.

## Consequences

**Positive**
- Matches battle-tested ledgers; nothing invented.
- One wallet, one read path, dumb-simple mobile client (BFF).
- Double-spend impossible — single writer for all mutable money state.
- Stores fully own and report on their coupons; central oversees all.
- Immutable-only sync fits "just separate ERPNext servers" — no CDC/bus needed.

**Negative / accepted**
- HQ must be reachable at mint (to register) and at scan/redeem (already accepted, ADR-0001/0002).
- A store's local defs and HQ's replica are two copies — safe only because defs are immutable;
  any future mutable field on a card would break this and must instead live on HQ.

## Reference implementations to study
`github.com/formancehq/ledger` · `github.com/tigerbeetle/tigerbeetle` ·
`github.com/Giftbit/lightrail-rothschild` · Medusa/Saleor/Sylius promotion modules.
