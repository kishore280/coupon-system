# coupon_system — agent guide

Single-source-of-truth loyalty coupons for the oxifix ERPNext estate: one points ledger,
store-locked "buckets", and a single-call HQ **gateway** that routes/proxies scans to
self-contained stores. This file is only the map — the knowledge lives in the linked docs.

**New here? Read in this order:**

## Design (why it's shaped this way)
- [docs/adr/0001-single-source-of-truth-ledger.md](docs/adr/0001-single-source-of-truth-ledger.md) — one ledger.
- [docs/adr/0002-central-card-registry-thin-store-client.md](docs/adr/0002-central-card-registry-thin-store-client.md) — HQ card registry, thin store client.
- [docs/adr/0003-ledger-scoping-and-immutable-def-replication.md](docs/adr/0003-ledger-scoping-and-immutable-def-replication.md) — bucket scoping + namespaced codes.
- [docs/store-coupons-build-spec.md](docs/store-coupons-build-spec.md) — the store-locked build spec.

## How scan/balance work across sites (the gateway)
- [docs/api-scan-gateway.md](docs/api-scan-gateway.md) — the single-call scan contract the mobile app relies on.
- [docs/gateway-build-status.md](docs/gateway-build-status.md) — what's built + e2e verification notes.

## Running / operating a site — **read before touching a server**
- [docs/store-mode-setup.md](docs/store-mode-setup.md) — make a site an HQ-backed store or a Standalone Store.
- [docs/operations.md](docs/operations.md) — **deployment model, the gotchas that cost hours, gateway
  service-account wiring, and balance semantics. Read this before deploying or debugging a live site.**

## Rules of thumb
- Secrets are **`Password`** fields, read with `get_password(...)` — never plaintext `Data`.
- A store's identity = its `get_url()` and MUST equal its `Coupon Store` row on HQ, everywhere.
- Per-site dev servers run `--noreload` → **restart the process** after a code change (see operations.md).
- Never commit creds or site inventory to git — those live in ops notes, not here.
