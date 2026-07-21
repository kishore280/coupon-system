# Store Mode — Manual Setup Runbook

How to turn an ERPNext site into a **store** that issues its own coupons whose points lock to it,
while HQ keeps the single wallet. Read `docs/adr/0001–0003` for *why*; this is the *how*.

## Model in one paragraph

HQ owns the one points ledger. A **store** mints its own coupons (namespaced codes) and **registers
the immutable definitions to HQ** so a scan resolves there. **Redemption is NOT in this app** — it
reuses `oxifix_multisite_sync`'s Sales Invoice flow (enter phone → it shows the balance → redeem
points → posts the GL discount → `POST coupon_system.api.redeem` with `site_url = get_url()`).
Because HQ's `redeem()` is bucket-aware, that unchanged flow spends store-locked points for free.
So on a store, `coupon_system` does **minting only**.

## Prerequisites

- **HQ site**: `coupon_system` installed (owns the ledger + card registry).
- **Store site**: both `coupon_system` **and** `oxifix_multisite_sync` installed. (coupon_system
  Store mode reads the HQ connection from the sync app's `HQ Integration Settings` — it will error
  clearly if that app is absent.)
- An **HQ user with the `Coupon Manager` role** whose API key/secret the store will authenticate with.

## The identity rule (read this first)

A store's identity is **`get_url()`**, and it must be **identical** everywhere:
the store's `host_name`, its `Coupon Store` name on HQ, and the `card.store` bucket. Different
scheme/host/port = a different bucket = store-locked points not found at redeem.

So **pin `host_name`** on the store so `get_url()` is deterministic (console *and* web):

```bash
bench --site <store-site> set-config host_name http://<store-host-or-ip:port>
```

Everything below uses that exact value — call it `$STORE_URL`.

## On HQ

1. **Coupon Store** named exactly `$STORE_URL`, with a unique `code_namespace` (e.g. `R1`),
   `is_active = 1`.
2. Confirm the API key/secret the store will use (step Store-3) belongs to a **Coupon Manager**.

## On the store site

1. **Site role = Store.** Either set `Coupon System Settings → Site Role = Store`, or (to also skip
   generic seeding from the very first install) `bench --site <store> set-config coupon_site_role Store`
   **before** installing the app.
2. **Pin `host_name`** to `$STORE_URL` (see identity rule above).
3. **`HQ Integration Settings`** (from `oxifix_multisite_sync`): set `hq_url`, `api_key`, `api_secret`
   to the HQ Coupon Manager creds. *(This is the ONE HQ config — coupon_system reuses it, and the
   sync app uses it for redemption.)*
4. **Local `Coupon Store`** named exactly `$STORE_URL` with the **same** `code_namespace` (`R1`).
   *(Required so minted codes are namespaced and `card.store` resolves locally.)*
5. **Store-owned `Coupon Campaign`(s)**: set `owned_by_store = $STORE_URL`, `points`, `is_active`.
6. **Mint stock**: `coupon_system.hq_client.store_mint(quantity, campaign)` — mints locally and
   registers the definitions to HQ. Repeat per campaign for a ready pool.

## Verify

```
get_url() on the store  ==  Coupon Store name on HQ  ==  $STORE_URL   (scheme+host+port)
```
Then: mint → a customer scans (app → HQ) earns points **locked to $STORE_URL** → redeeming at that
store (via the sync's Sales Invoice) spends them → redeeming anywhere else is refused.

## What lives where (so nobody misuses the store)

- **HQ**: the only points ledger; the authoritative card registry; all `redeem`/`scan`/`reverse`.
- **Store**: its campaigns + immutable card defs + minting. It has the `Coupon Ledger` doctype
  installed but a `before_insert` guard makes it **unwritable** in Store mode — all points are HQ's.
- **Redemption + the discount accounting**: `oxifix_multisite_sync`, unchanged.

---

# Standalone (self-contained) store — the OTHER mode

A **`site_role = Standalone Store`** site is a *self-contained* store: its **own local** ledger,
customers, and cards — **no central HQ**, one plain wallet, everything within the store. It's your
coupon app running standalone. Use this when a store/merchant wants to own their own data.

> **Prereq — make the option appear:** the `Standalone Store` value needs the doctype meta on the
> site. Run `bench --site <site> migrate` (or reload the `Coupon System Settings` doctype) once, or
> `Site Role` won't list it in the desk dropdown.

## Desk steps
The **golden rule** is the loopback: `HQ Integration Settings.hq_url`, the `Coupon Store` name, and
the site's own `get_url()` are all the **same value** — the site itself.

1. **`Coupon System Settings`** → `Site Role` = **`Standalone Store`**.
2. **`User`** → create one with **`Coupon Manager`** → Generate Keys → for **redemption** creds.
3. **`User`** → create one with **`Coupon Mobile`** → Generate Keys → for the **mobile app** creds.
4. **`HQ Integration Settings`** → `hq_url` = **this site's own URL** (loopback);
   `api_key`/`api_secret` = the Coupon Manager keys (step 2);
   **`mobile_api_key`/`mobile_api_secret` = the Coupon Mobile keys (step 3)** — the app's
   `get_mobile_config` REQUIRES these, or the app can't scan/see balance.
5. **`Coupon Store`** → `site_url` = the site's own URL, `is_active` ✓. (namespace optional.)
6. **`Coupon Campaign`** → plain campaign; **leave Owned By Store blank** (it's auto-cleared on a
   self-contained store — there's no other store to lock to).
7. Open the campaign → **Generate Cards** → mints **locally** (no HQ).

## How it behaves
- **generate / scan / balance**: all **local** (the ledger guard is off in this role).
- **redemption + reversal**: `oxifix_multisite_sync` detects self-contained (`is_self_contained()`)
  and calls `coupon_system.api.redeem` **directly, in the same transaction** as the Sales Invoice —
  no HTTP round-trip to itself, and atomic with the invoice. *(Requires the coupon_hooks patch in
  `oxifix_multisite_sync`.)*
- **owned_by_store**: cleared on save (a standalone store is one wallet — nothing to lock to).
