# Coupon System

A loyalty-points system for physical scratch cards placed inside product boxes.
Customers scan a QR code to earn points; branches redeem those points as invoice
discounts. All point data lives on a single central **HQ** site — every branch and the
mobile app talk to HQ over its API, so a customer can earn at one location and spend at
another against one shared balance.

---

## Architecture

```
   Mobile app  ───────────────┐
   (scan / balance)           │
                              ▼
                  HQ site (this app installed here)
                  • Coupon User / Card / Ledger data
                  • points engine (balance = SUM of ledger)
                  • QR scan landing page  /s/<code>
                  • App-Link verification /.well-known/…
                              ▲
   Branch invoice ───────────┘
   redemption (sync app calls HQ API)
```

- **HQ site**: `coupon_system` is installed here. Single source of truth.
- **Branch sites**: do **not** have `coupon_system`. They call the HQ API to
  check/deduct points during Sales Invoice submission.

---

## DocTypes

| DocType | Purpose | Notes |
|---|---|---|
| **Coupon User** | One per customer phone | `phone` is the document name; `points_balance` is virtual (never stored) |
| **Coupon Card** | One physical card | Holds `code` (QR value), `points_value`, `expiry_date`, `is_used` |
| **Coupon Ledger** | Immutable point movements | `type` = CREDIT / DEBIT; balance = SUM(CREDIT) − SUM(DEBIT) |
| **Coupon System Settings** | Single config | `scan_base_url`, `play_store_url`, `app_store_url` |

**Balance is always derived** from the ledger SUM at runtime — it is never stored, so it
can never drift out of sync.

---

## API Endpoints

All under `coupon_system.api.*`. Require a role of `System Manager`, `Coupon Manager`,
or `Coupon Mobile` (enforced per-endpoint).

| Endpoint | Method | Purpose |
|---|---|---|
| `scan(phone, code, full_name=)` | POST | Customer scans a card → CREDIT points, mark card used |
| `balance(phone)` | GET | Returns balance, total earned/redeemed, points expiring soon, last 20 ledger rows |
| `redeem(phone, amount, site_url, invoice_no, code=)` | POST | Branch deducts points against an invoice (idempotent per invoice) |
| `reverse_redeem(invoice_no, site_url)` | POST | Reverses a redemption when an invoice is cancelled |
| `generate_cards(...)` / `bulk_generate_cards(items)` | POST | Admin bulk-creates cards with unique codes |
| `get_card_images(codes, img_type)` | POST | Returns QR/barcode images for printing |

---

## QR Codes, Barcodes & Mobile Deep Links

Each printed card carries **two** codes:

| Code | Scanned by | Encodes |
|---|---|---|
| **QR** | Customer phone camera | Full URL: `{scan_base_url}/<code>` |
| **Barcode (Code128)** | Branch handheld scanner | Just the short code, e.g. `PAINT-00ZJ-R48U` |

Barcodes only hold the short code by design — a full URL makes a Code128 too wide to scan
reliably. QR holds the URL (industry standard for phone-scannable links).

### Android App Links flow

```
Customer scans QR → phone opens {scan_base_url}/<code>
   ├─ App installed   → Android verifies App Link → opens app directly at scan screen
   └─ App NOT installed → loads the /s/<code> web page (download links / "coming soon")
```

- **`/s/<code>` landing page** — `www/s.py` + `www/s.html`. Registered via
  `website_route_rules` in `hooks.py` (run `bench migrate` after changing routes).
- **App Link verification** — `www/.well-known/assetlinks.json` (plain JSON file, served by
  Frappe's www router with `application/json` content-type; no nginx changes needed).
  Fill in your Android package name and the release signing SHA-256.
- **iOS Universal Links** — add `www/.well-known/apple-app-site-association` with your
  Apple Team ID + Bundle ID.

### Settings to configure (Coupon System Settings)

| Field | Value |
|---|---|
| `scan_base_url` | The HTTPS base your QR links point to, e.g. `https://<your-domain>/s` |
| `play_store_url` | Set once the Android app is published (button hidden until then) |
| `app_store_url` | Set once the iOS app is published |

---

## Mobile App Integration

- HQ base URL: your HQ site's HTTPS address.
- Auth: `Authorization: token <api_key>:<api_secret>` header. A dedicated mobile user
  (role `Coupon Mobile`) is created on install with an API key/secret — paste these into
  HQ Integration Settings → Mobile App Credentials.
- The app should parse the card code from the deep link path: `Uri.parse(link).pathSegments.last`.

---

## Installation

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO
bench --site <hq-site> install-app coupon_system
bench --site <hq-site> migrate
```

On install (`after_install`) the app auto-creates the `Coupon Mobile` role and the mobile
API user, and prints the generated API key/secret to the console.

---

## Contributing

This app uses `pre-commit` for formatting/linting (ruff, eslint, prettier, pyupgrade):

```bash
cd apps/coupon_system
pre-commit install
```

### License

mit
