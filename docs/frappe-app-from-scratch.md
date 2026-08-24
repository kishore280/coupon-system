# Building a Frappe app from scratch — a hands-on guide

A complete walkthrough of building a real Frappe v16 app, file by file. In practice you'd run
`bench new-app` and draw DocTypes in the browser — and you should; nobody hand-types boilerplate.
But the generator writes files you then have to *own*, so this guide walks every one of them as if
it were typed, because reading them is the part that makes you fluent.

The app we build is **`coupon_system`** — the same app this repo contains. We build its core from
zero (campaigns → cards → a points ledger → an API a mobile app calls), then point at the real
files where the production version goes further. So the demo is not a toy: at the end you have a
working loyalty-points backend, and every concept has a real counterpart in this codebase.

> **Teaching from this?** [`frappe-first-app-tutorial.md`](frappe-first-app-tutorial.md) runs the
> same tour against a deliberately tiny example app (a library) instead of a production system, is
> organised around the real generate-then-edit workflow, and covers a few things this guide doesn't
> need (submittable documents, background jobs, email, print formats, workflow). **Use that one to
> teach.** Use this one to understand how the app in this repo actually works.

**Version:** **Frappe v16** throughout. The app in this repo currently runs on v15, so a few of the
linked source files still use v15-era APIs — those are called out where they appear, and
[§22](#22-coming-from-v15) is the full list.

**Audience:** developers who know Python and have seen an ERPNext screen, but have never written a
Frappe app.
**Format:** works as a ~90-minute live demo (see [§21 Demo run-sheet](#21-demo-run-sheet)) or as
self-paced reading.

---

## Table of contents

| # | Section | What you learn |
|---|---|---|
| 0 | [What we're building](#0-what-were-building) | The scope of the demo |
| 1 | [The mental model](#1-the-mental-model-bench-site-app-doctype) | bench / site / app / DocType |
| 2 | [Prerequisites](#2-prerequisites-bench-and-a-site) | Getting a bench + site running |
| 3 | [The app skeleton](#3-the-app-skeleton) | `bench new-app`, and the 7 files that matter |
| 4 | [Your first DocType, by hand](#4-your-first-doctype-by-hand-coupon-campaign) | DocType JSON, field by field |
| 5 | [The rest of the data model](#5-the-rest-of-the-data-model) | Naming rules, Single, child tables, virtual fields |
| 6 | [The ledger pattern](#6-the-ledger-pattern-never-store-a-balance) | Derived balances, query builder |
| 7 | [The API layer](#7-the-api-layer-frappewhitelist) | `@frappe.whitelist`, locking, idempotency |
| 8 | [Calling your API](#8-calling-your-api-for-real) | API keys, curl, `bench console` |
| 9 | [Controllers and document lifecycle](#9-controllers-and-the-document-lifecycle) | `validate`, `on_update`, hooks |
| 10 | [Hooking into other apps](#10-hooking-into-other-apps-doc_events-and-scheduler) | `doc_events`, scheduler, ERPNext |
| 11 | [Extending a standard DocType](#11-extending-a-standard-doctype-custom-fields-in-code) | Custom fields in code, idempotent install |
| 12 | [Desk UI](#12-desk-ui-form-js-and-list-js) | Form JS, dialogs, list actions |
| 13 | [Website pages](#13-website-pages-www) | `www/`, route rules, Jinja methods |
| 14 | [Reports](#14-reports) | Script Report |
| 15 | [Roles, permissions, fixtures](#15-roles-permissions-and-fixtures) | Who can do what, shipping records |
| 16 | [Patches (data migrations)](#16-patches-data-migrations) | `patches.txt` |
| 17 | [Tests](#17-tests) | `IntegrationTestCase`, running them |
| 18 | [Dev workflow and gotchas](#18-dev-workflow-and-the-gotchas-that-cost-hours) | The things that waste your afternoon |
| 19 | [Talking to another site over HTTP](#19-bonus-talking-to-another-site-over-http) | Service creds, `Password` fields |
| 20 | [Command cheat sheet](#20-command-cheat-sheet) | Everything in one place |
| 21 | [Demo run-sheet](#21-demo-run-sheet) | How to present this live |
| 22 | [Coming from v15](#22-coming-from-v15) | What changed, if you're porting |

---

## 0. What we're building

Physical scratch cards go inside product boxes. Each card has a unique code and a QR. A customer
scans it in a mobile app and earns points; later a branch redeems those points as an invoice
discount. One central site holds the truth.

The core we hand-write in this guide:

```
Coupon Campaign   the dial: how many points a card is worth, how long it lives
Coupon Card       one physical card: code, campaign, lifecycle status
Coupon User       one customer, keyed by phone number
Coupon Ledger     immutable CREDIT / DEBIT rows — the only place points exist
Coupon System Settings   a Single doctype for config
```

and three API endpoints the mobile app calls: `scan`, `balance`, `redeem`.

Everything else in this repo (store-locked point "buckets", the HQ scan gateway, withdrawal
requests) is a layer on top of exactly these pieces — see `CONTEXT.md` and `docs/adr/`.

---

## 1. The mental model: bench, site, app, DocType

Four words carry the whole framework. Get these right and everything else follows.

**Bench** — a working directory holding one Python virtualenv, a set of apps, and a set of sites.
It is also the CLI (`bench ...`). One bench, many sites.

**Site** — a database plus a config file plus a files directory, reachable at a hostname. Apps are
installed *into* a site. Two sites on one bench can have different apps installed.

**App** — a normal Python package with a few extra files Frappe looks for. It ships DocTypes, code,
pages, and hooks.

**DocType** — the unit of everything. One DocType gives you, from a single JSON file:

- a database table (`tabCoupon Card`)
- a desk form and a list view
- a REST endpoint (`/api/resource/Coupon Card`)
- a Python class you can hook lifecycle methods onto
- permissions, naming, validation, search indexes, an audit trail

```
frappe-bench/
├── apps/
│   ├── frappe/            the framework
│   ├── erpnext/           optional; we hook into it in §10
│   └── coupon_system/     ← what we write
├── sites/
│   ├── apps.txt           apps available on this bench
│   └── hq.localhost/      a site
│       ├── site_config.json
│       └── private/files/
└── env/                   the virtualenv
```

A useful reframe for the demo: **you are not writing an app that has a database. You are writing
schema, and Frappe hands you an app.**

---

## 2. Prerequisites: bench and a site

If you already have a bench with a site, skip ahead. Otherwise, briefly (full install docs:
<https://docs.frappe.io/framework/user/en/installation>):

```bash
# v16 needs: python 3.14 (pinned >=3.14,<3.15), node 24+, redis, mariadb 10.6+,
# and Chrome/Chromium for PDF generation
pip install frappe-bench

bench init frappe-bench --frappe-branch version-16
cd frappe-bench

bench new-site hq.localhost
bench --site hq.localhost add-to-hosts        # so http://hq.localhost:8000 resolves

# optional but this guide's §10 hooks into ERPNext's Work Order
bench get-app erpnext --branch version-16
bench --site hq.localhost install-app erpnext
```

Then turn on developer mode — **do this before you touch a DocType**:

```bash
bench --site hq.localhost set-config developer_mode 1
bench --site hq.localhost clear-cache
```

Developer mode is what makes DocType changes you make in the UI get *written back to JSON files in
your app*. Without it, your schema lives only in the database and is not in git. We are
hand-writing the JSON anyway, but you still want it on: it also gives you better tracebacks and
lets `bench migrate` sync your files into the DB.

Start the dev server:

```bash
bench start
# http://hq.localhost:8000 — log in as Administrator
```

---

## 3. The app skeleton

In real life this is one command:

```bash
cd ~/frappe-bench
bench new-app coupon_system     # asks for title, publisher, email, licence
```

It writes ~30 files. Seven of them *are* the app; the rest is CI and linter scaffolding you can
delete. Below is what those seven contain and why — read it as an annotated tour of what the
generator just handed you, not as a typing exercise.

The layout — note the **doubled app name**, which trips up everyone on day one:

```
coupon_system/                  ← repo root
├── pyproject.toml
├── license.txt
├── README.md
└── coupon_system/              ← the Python package
    ├── __init__.py             ← must define __version__
    ├── hooks.py                ← the app's contract with the framework
    ├── modules.txt             ← module names this app ships
    ├── patches.txt             ← data migrations
    └── coupon_system/          ← the MODULE directory (name from modules.txt)
        ├── __init__.py
        └── doctype/
            └── __init__.py
```

Two levels of `coupon_system` because **app** and **module** are different things. The app is the
package; a module is a grouping of DocTypes *inside* it (ERPNext has "Accounts", "Stock",
"Manufacturing"…). Our app ships one module, and we happen to name it after the app.

### 3.1 `pyproject.toml`

```toml
[project]
name = "coupon_system"
authors = [{ name = "Your Name", email = "you@example.com" }]
description = "Coupon loyalty points system"
requires-python = ">=3.10"
readme = "README.md"
dynamic = ["version"]
dependencies = [
    # "frappe~=15.0.0"  # NOT listed — bench installs and manages frappe itself
    "qrcode[pil]",
    "python-barcode[images]",
]

[build-system]
requires = ["flit_core >=3.4,<4"]
build-backend = "flit_core.buildapi"

[tool.ruff]
line-length = 110
target-version = "py310"

[tool.ruff.lint]
select = ["F", "E", "W", "I", "UP", "B", "RUF"]
ignore = ["E501", "F401", "B904", "W191", "E101"]

[tool.ruff.format]
quote-style = "double"
indent-style = "tab"
```

Two things worth saying out loud in a demo:

- `dynamic = ["version"]` means flit reads `__version__` from `coupon_system/__init__.py`. That's
  why the next file is not optional.
- **Never** list `frappe` as a dependency. Bench owns it; pinning it here will fight the bench.
- Tabs, not spaces, for Python. That's the Frappe ecosystem convention and what `ruff format` is
  configured to enforce here.

### 3.2 `coupon_system/__init__.py`

```python
__version__ = "0.0.1"
```

That's the entire file. Frappe reads it (`frappe.get_app_version`), flit reads it, and the Apps
screen shows it.

### 3.3 `coupon_system/hooks.py`

`hooks.py` is the whole contract between your app and the framework. Frappe imports it and looks
for specific module-level names. Nothing is registered dynamically — if it's not in `hooks.py`,
it doesn't happen. Start minimal:

```python
app_name = "coupon_system"
app_title = "Coupon System"
app_publisher = "Your Name"
app_description = "Coupon loyalty points system"
app_email = "you@example.com"
app_license = "mit"
```

We add to this file in almost every later section. The real one is
[`coupon_system/hooks.py`](../coupon_system/hooks.py) — and it's worth reading top to bottom once,
because the generated comments are a free catalogue of every extension point the framework offers.

### 3.4 `coupon_system/modules.txt`

```
Coupon System
```

One module name per line, in **Title Case**. This is what creates the `Module Def` record on
install, and it's how a DocType JSON's `"module": "Coupon System"` resolves back to your app. The
directory name is the snake_case of it: `coupon_system/coupon_system/`.

### 3.5 `coupon_system/patches.txt`

```
[pre_model_sync]
# runs before doctypes are migrated

[post_model_sync]
# runs after doctypes are migrated
```

Empty for now; §16 fills it in.

### 3.6 The `__init__.py` files

Frappe walks directories with `importlib`. Every package level needs one:

```bash
touch coupon_system/coupon_system/__init__.py
touch coupon_system/coupon_system/doctype/__init__.py
```

A forgotten `__init__.py` produces a `ModuleNotFoundError` on migrate that reads like a framework
bug and is not one. This is the single most common day-one mistake.

### 3.7 Install it

```bash
cd ~/frappe-bench
bench get-app apps/coupon_system          # pip install -e + register in sites/apps.txt
bench --site hq.localhost install-app coupon_system
```

`bench get-app` on a local path does three things: `pip install -e` into the bench venv, add the
name to `sites/apps.txt`, and build assets. `install-app` then creates the `Module Def`, syncs
DocTypes, and runs your `after_install` hook.

Verify:

```bash
bench --site hq.localhost list-apps
# frappe
# erpnext
# coupon_system
```

You now have a working (empty) Frappe app — seven files that matter, and you know what each is for.

---

## 4. Your first DocType, by hand: Coupon Campaign

With developer mode on you'd normally create this at `/app/doctype/new` (or
`bench --site hq.localhost new-doctype "Coupon Campaign" --module "Coupon System"`) and let Frappe
write the JSON. Read on anyway: the file is the source of truth, it's what shows up in code review,
and a few properties are faster to type than to click.

A DocType is a directory of up to four files:

```
coupon_system/coupon_system/doctype/coupon_campaign/
├── __init__.py                  (empty)
├── coupon_campaign.json         the schema           ← required
├── coupon_campaign.py           the controller       ← required (may be near-empty)
└── coupon_campaign.js           desk form behaviour  ← optional
```

The directory name and file names are the **snake_case of the DocType name**. `Coupon Campaign` →
`coupon_campaign`. Get this wrong and Frappe won't find the controller — silently, in some paths.

### 4.1 The schema

`coupon_campaign.json`:

```json
{
 "actions": [],
 "allow_rename": 1,
 "autoname": "field:campaign_name",
 "creation": "2026-06-23 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "campaign_name",
  "audience",
  "is_active",
  "column_break_1",
  "points",
  "validity_months",
  "end_date",
  "section_break_desc",
  "description"
 ],
 "fields": [
  {
   "fieldname": "campaign_name",
   "fieldtype": "Data",
   "label": "Campaign Name",
   "reqd": 1,
   "unique": 1,
   "in_list_view": 1,
   "description": "e.g. Plumber 10, Painter 20"
  },
  {
   "fieldname": "audience",
   "fieldtype": "Link",
   "label": "Audience",
   "options": "Customer Group",
   "in_list_view": 1
  },
  {
   "default": "1",
   "fieldname": "is_active",
   "fieldtype": "Check",
   "label": "Is Active",
   "in_list_view": 1,
   "description": "When unchecked, cards of this campaign cannot be scanned."
  },
  {
   "fieldname": "column_break_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "points",
   "fieldtype": "Int",
   "label": "Points",
   "reqd": 1,
   "in_list_view": 1,
   "description": "The live point value. Change anytime — applies to every unscanned card."
  },
  {
   "default": "12",
   "fieldname": "validity_months",
   "fieldtype": "Int",
   "label": "Validity (Months)"
  },
  {
   "fieldname": "end_date",
   "fieldtype": "Date",
   "label": "Campaign End Date"
  },
  {
   "fieldname": "section_break_desc",
   "fieldtype": "Section Break"
  },
  {
   "fieldname": "description",
   "fieldtype": "Small Text",
   "label": "Description"
  }
 ],
 "links": [
  {
   "link_doctype": "Coupon Card",
   "link_fieldname": "campaign"
  }
 ],
 "modified": "2026-06-23 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Coupon System",
 "name": "Coupon Campaign",
 "naming_rule": "By fieldname",
 "owner": "Administrator",
 "permissions": [
  {
   "role": "System Manager",
   "create": 1, "read": 1, "write": 1, "delete": 1,
   "email": 1, "export": 1, "print": 1, "report": 1, "share": 1
  }
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "states": [],
 "track_changes": 1
}
```

Read it as five groups:

**Identity** — `"doctype": "DocType"` (this JSON *is* a document, of type DocType — Frappe is
self-describing), `"name"`, `"module"`. The module must match `modules.txt`.

**`field_order` + `fields`** — `fields` defines them, `field_order` lays them out. Layout fields
(`Section Break`, `Column Break`, `Tab Break`) are real entries in both lists; that's how you build
a form without writing HTML. Keep both in sync or the form quietly drops a field.

**Field anatomy** — the ones you'll use constantly:

| Key | Effect |
|---|---|
| `fieldname` | the DB column; snake_case, stable forever (renaming = a patch) |
| `fieldtype` | `Data`, `Int`, `Float`, `Check`, `Select`, `Date`, `Datetime`, `Link`, `Table`, `Table MultiSelect`, `Small Text`, `Text Editor`, `Password`, `HTML`, `Attach` … |
| `options` | for `Link` → target DocType; for `Select` → newline-separated values; for `Table` → child DocType |
| `reqd` | required |
| `unique` | unique index |
| `default` | string, even for numbers (`"1"`, `"12"`) |
| `in_list_view` | show as a column in the list |
| `search_index` | index it — add this to anything you filter on at scale |
| `read_only` / `hidden` | display control |
| `depends_on` | show conditionally: `"eval:doc.origin=='Store'"` |
| `description` | the grey helper text under the field. **Use it.** It is the cheapest documentation you will ever write and it shows up exactly where someone is confused |

**Naming** — `autoname` + `naming_rule` decide the primary key (`name`). Options in §5.1.

**Permissions** — a list of role rows. No row for a role = that role sees nothing. `System Manager`
is not automatic; if you leave `permissions` empty, only Administrator gets in.

Also worth knowing: `links` renders the "Connections" tabs on the form (here: this campaign's
cards), and `track_changes: 1` records every field edit in the Version doctype — free audit trail.

### 4.2 The controller

`coupon_campaign.py`:

```python
import frappe
from frappe import _
from frappe.model.document import Document


class CouponCampaign(Document):
	def validate(self):
		if self.points is not None and int(self.points) <= 0:
			frappe.throw(_("Points must be greater than 0"))
		if self.validity_months is not None and int(self.validity_months) < 0:
			frappe.throw(_("Validity (Months) cannot be negative"))
```

The class name is the **PascalCase of the DocType name with spaces removed**: `Coupon Campaign` →
`CouponCampaign`. Frappe resolves it by convention. `validate()` runs on every insert and every
save; `frappe.throw()` aborts the transaction and shows the message to the user. Wrap user-facing
strings in `_()` so they're translatable.

### 4.3 Sync it

```bash
bench --site hq.localhost migrate
```

`migrate` reads every DocType JSON in every installed app and reconciles the database to it —
creating tables, adding columns, adding indexes. It is idempotent and it is how *all* schema change
happens in Frappe. There are no Alembic-style migration files for schema; the JSON is the
migration.

Now open <http://hq.localhost:8000/app/coupon-campaign/new> and you have a working form with
validation, list view, filters, sorting, permissions, a REST endpoint, and an audit trail — from
one JSON file and eight lines of Python.

> **Demo tip:** this is the moment to pause. Create "Plumber 10" with 10 points, then hit
> `/api/resource/Coupon Campaign` in a browser tab. Nothing else in the guide lands as hard.

---

## 5. The rest of the data model

Four more DocTypes, each teaching one new thing.

### 5.1 Coupon User — naming by field, and a virtual field

Naming rules, since we need one here:

| `autoname` | `naming_rule` | Result |
|---|---|---|
| `field:phone` | `By fieldname` | `name` = the phone value. Natural keys. |
| `CWR-.YYYY.-.#####` | `Expression (old style)` | `CWR-2026-00001`, auto-incrementing |
| `naming_series:` | `By "Naming Series" field` | user picks the series from a `naming_series` field |
| `hash` | `Random` | a random hash |
| `Prompt` | `Set by user` | the user types the name |
| `format:{campaign}-{###}` | `Expression` | template over field values |

We name the customer by their phone number — the phone *is* the identity, so there's no reason for
a surrogate key:

`coupon_user/coupon_user.json`:

```json
{
 "actions": [],
 "autoname": "field:phone",
 "creation": "2026-06-16 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["phone", "full_name", "points_balance"],
 "fields": [
  {"fieldname": "phone", "fieldtype": "Data", "label": "Phone", "reqd": 1, "unique": 1},
  {"fieldname": "full_name", "fieldtype": "Data", "label": "Full Name"},
  {
   "fieldname": "points_balance",
   "fieldtype": "Float",
   "is_virtual": 1,
   "label": "Points Balance",
   "read_only": 1
  }
 ],
 "links": [
  {"link_doctype": "Coupon Ledger", "link_fieldname": "phone"},
  {"link_doctype": "Coupon Card", "link_fieldname": "used_by_phone"}
 ],
 "modified": "2026-06-16 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Coupon System",
 "name": "Coupon User",
 "naming_rule": "By fieldname",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "create": 1, "read": 1, "write": 1, "delete": 1, "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}
 ],
 "sort_field": "modified",
 "sort_order": "DESC",
 "track_changes": 1
}
```

`is_virtual: 1` is the important bit: **no column is created**. The value is computed when the form
loads:

`coupon_user/coupon_user.py`:

```python
import frappe
from frappe.model.document import Document

from coupon_system.api import _get_balance


class CouponUser(Document):
	def onload(self):
		self.set_onload("points_balance", _get_balance(self.phone))
```

This is the discipline the whole app is built on and it's worth stating explicitly to an audience:
**a balance is a question you ask the ledger, never a number you keep.** A stored counter can drift
from its transactions; a derived one cannot. See
[`docs/adr/0001-single-source-of-truth-ledger.md`](adr/0001-single-source-of-truth-ledger.md).

### 5.2 Coupon Ledger — an append-only table

`coupon_ledger/coupon_ledger.json` (fields abbreviated; full file
[here](../coupon_system/coupon_system/doctype/coupon_ledger/coupon_ledger.json)):

```json
{
 "autoname": "CL-.YYYY.-.#####",
 "naming_rule": "Expression (old style)",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": ["phone", "type", "points", "timestamp", "column_break_1", "site_url", "invoice_no", "description"],
 "fields": [
  {"fieldname": "phone", "fieldtype": "Link", "options": "Coupon User", "label": "Phone", "reqd": 1, "in_list_view": 1, "search_index": 1},
  {"fieldname": "type", "fieldtype": "Select", "options": "CREDIT\nDEBIT", "label": "Type", "reqd": 1, "in_list_view": 1},
  {"fieldname": "points", "fieldtype": "Int", "label": "Points", "reqd": 1, "in_list_view": 1},
  {"fieldname": "timestamp", "fieldtype": "Datetime", "label": "Timestamp", "in_list_view": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "site_url", "fieldtype": "Link", "options": "Coupon Store", "label": "Site URL"},
  {"fieldname": "invoice_no", "fieldtype": "Data", "label": "Invoice No"},
  {"fieldname": "description", "fieldtype": "Data", "label": "Description"}
 ],
 "module": "Coupon System",
 "name": "Coupon Ledger",
 "permissions": [
  {"role": "System Manager", "read": 1, "report": 1, "export": 1, "print": 1, "email": 1, "share": 1,
   "create": 0, "write": 0, "delete": 0}
 ],
 "sort_field": "timestamp",
 "sort_order": "DESC",
 "track_changes": 0
}
```

Look at those permissions: `read: 1` but `create/write/delete: 0`, **for System Manager**. Nobody
edits the ledger from the desk — not even an admin. Rows are written only by our own code via
`insert(ignore_permissions=True)`. Enforcing immutability through the permission model rather than
through good intentions costs one line and removes an entire class of "who changed this balance"
incident.

The controller is a stub, and that's fine — most DocTypes have no behaviour of their own:

```python
import frappe
from frappe.model.document import Document


class CouponLedger(Document):
	pass
```

> **Type stubs.** Set `export_python_type_annotations = True` in `hooks.py` and `bench migrate`
> writes an auto-generated `if TYPE_CHECKING:` block of field types into each controller (you can
> see them in `coupon_ledger.py` and `coupon_store.py` here). Free editor autocomplete on
> `self.<field>`. Never edit inside the `# begin/end: auto-generated types` markers.

### 5.3 Coupon Card — Select lifecycle and a naming series

The key fields (full file
[here](../coupon_system/coupon_system/doctype/coupon_card/coupon_card.json)):

```json
{
 "autoname": "naming_series:",
 "naming_rule": "By \"Naming Series\" field",
 "fields": [
  {"fieldname": "naming_series", "fieldtype": "Select", "label": "Series",
   "options": "CC-.YYYY.-.#####", "reqd": 1, "set_only_once": 1, "no_copy": 1, "print_hide": 1},
  {"fieldname": "code", "fieldtype": "Data", "label": "Code", "reqd": 1, "unique": 1, "in_list_view": 1},
  {"fieldname": "campaign", "fieldtype": "Link", "options": "Coupon Campaign", "label": "Campaign",
   "search_index": 1, "in_list_view": 1,
   "description": "Decides the live point value at scan time."},
  {"default": "Active", "fieldname": "status", "fieldtype": "Select", "label": "Status",
   "options": "Generated\nActive\nRedeemed\nExpired\nRetired\nVoid",
   "search_index": 1, "in_list_view": 1},
  {"fieldname": "points_value", "fieldtype": "Int", "label": "Points Value (snapshot)",
   "description": "Snapshot at generation. Live value comes from the campaign; this is a fallback."},
  {"fieldname": "expiry_date", "fieldtype": "Date", "label": "Expiry Date", "reqd": 1, "search_index": 1},
  {"default": "0", "fieldname": "is_used", "fieldtype": "Check", "label": "Is Used", "in_list_view": 1},
  {"fieldname": "used_by_phone", "fieldtype": "Link", "options": "Coupon User", "label": "Used By Phone", "read_only": 1},
  {"fieldname": "scanned_at", "fieldtype": "Datetime", "label": "Scanned At", "read_only": 1},
  {"fieldname": "qr_preview", "fieldtype": "HTML", "label": "QR / Barcode"}
 ]
}
```

Three teaching points:

- **`unique: 1` on `code`** is the real defence against duplicate coupons. Application-level checks
  race; a unique index does not. §7.5 shows how to catch the resulting `IntegrityError` and turn it
  into a friendly response instead of a 500.
- **A `Select` field is a state machine.** One `status` field, read by the desk, the API and the
  reports, beats three booleans that can disagree with each other.
- **`points_value` is a snapshot, `campaign.points` is live.** A card stores what it was worth when
  printed, but a *central* card resolves its value from the campaign at scan time — so raising a
  campaign from 10 to 20 points instantly revalues every unscanned card, with no reprint. That
  design dial is the whole reason `Coupon Campaign` exists. (Store-minted cards deliberately do the
  opposite and keep the snapshot — a gift card whose value changes after you hand it over is a bug;
  see `_resolve_card_points` in [`api.py`](../coupon_system/api.py).)
- **`HTML` fieldtype** stores nothing. It's a slot your form JS fills with rendered markup (§12).

### 5.4 Coupon System Settings — a Single DocType

`"issingle": 1` means "exactly one of these exists, forever". No list view, no `name`, no table of
rows — values live in `tabSingles` as key/value pairs. It's how every app ships its settings page.

`coupon_system_settings/coupon_system_settings.json`:

```json
{
 "actions": [],
 "creation": "2026-06-16 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "issingle": 1,
 "field_order": ["scan_base_url", "code_prefix", "section_break_withdrawals", "enable_withdrawals", "points_to_currency_rate"],
 "fields": [
  {"fieldname": "scan_base_url", "fieldtype": "Data", "label": "QR Scan Base URL", "reqd": 1,
   "default": "https://example.com/s",
   "description": "Base URL encoded into each QR. Card code is appended: /s/<code>"},
  {"fieldname": "code_prefix", "fieldtype": "Data", "label": "Card Code Prefix",
   "description": "Optional brand prefix, e.g. OXFX → OXFX-7K9M-4P2T. Letters/digits only."},
  {"fieldname": "section_break_withdrawals", "fieldtype": "Section Break", "label": "Withdrawals"},
  {"default": "0", "fieldname": "enable_withdrawals", "fieldtype": "Check", "label": "Enable Withdrawals",
   "description": "Master switch — a kill switch for the whole feature."},
  {"default": "1", "fieldname": "points_to_currency_rate", "fieldtype": "Float", "label": "Points to Currency Rate"}
 ],
 "module": "Coupon System",
 "name": "Coupon System Settings",
 "owner": "Administrator",
 "modified": "2026-06-16 00:00:00.000000",
 "modified_by": "Administrator",
 "permissions": [
  {"role": "System Manager", "create": 1, "read": 1, "write": 1, "delete": 0}
 ],
 "sort_field": "modified",
 "sort_order": "DESC"
}
```

Reading a Single is a one-liner, and it's cached:

```python
rate = frappe.db.get_single_value("Coupon System Settings", "points_to_currency_rate")
```

### 5.5 A child table

A DocType with `"istable": 1` cannot exist on its own — rows always belong to a parent. Frappe adds
`parent`, `parenttype`, `parentfield`, `idx` columns for you.

`coupon_campaign_store/coupon_campaign_store.json`:

```json
{
 "actions": [],
 "creation": "2026-07-14 00:00:00.000000",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "istable": 1,
 "field_order": ["store"],
 "fields": [
  {"fieldname": "store", "fieldtype": "Link", "options": "Coupon Store", "label": "Store", "reqd": 1, "in_list_view": 1}
 ],
 "module": "Coupon System",
 "name": "Coupon Campaign Store",
 "owner": "Administrator",
 "modified": "2026-07-14 00:00:00.000000",
 "modified_by": "Administrator",
 "permissions": [],
 "sort_field": "modified",
 "sort_order": "DESC"
}
```

Note `"permissions": []` — a child table inherits its parent's permissions; giving it its own is
meaningless.

Use it from the parent with a `Table` field (full grid) or `Table MultiSelect` (chips):

```json
{
 "fieldname": "allowed_stores",
 "fieldtype": "Table MultiSelect",
 "label": "Allowed Stores",
 "options": "Coupon Campaign Store",
 "description": "Empty = any store. If set, only these stores may redeem."
}
```

And in Python:

```python
camp = frappe.get_doc("Coupon Campaign", "Plumber 10")
camp.append("allowed_stores", {"store": "https://store-a.example.com"})
camp.save()

# reading rows without loading the parent doc:
stores = frappe.get_all("Coupon Campaign Store", filters={"parent": "Plumber 10"}, pluck="store")
```

Run `bench --site hq.localhost migrate` and all five tables exist.

---

## 6. The ledger pattern: never store a balance

Now the core logic. Everything lives in `coupon_system/api.py`. Start with the private helpers —
the functions no HTTP caller can reach.

```python
import frappe
from frappe.query_builder.functions import Sum
from frappe.utils import cint, now_datetime


def _get_balance(phone):
	"""Balance is a SUM over the ledger, computed on demand. Never a stored counter."""
	CL = frappe.qb.DocType("Coupon Ledger")
	rows = (
		frappe.qb.from_(CL)
		.select(CL.type, Sum(CL.points).as_("total"))
		.where(CL.phone == phone)
		.groupby(CL.type)
		.run(as_dict=True)
	)
	balance = 0
	for r in rows:
		balance += cint(r.total) * (1 if r.type == "CREDIT" else -1)
	return balance


def _post_ledger(phone, entry_type, points, description, site_url=None, invoice_no=None):
	"""The ONE place that writes a Coupon Ledger row."""
	entry = frappe.new_doc("Coupon Ledger")
	entry.phone = phone
	entry.type = entry_type
	entry.points = points
	entry.description = description
	entry.site_url = site_url
	entry.invoice_no = invoice_no
	entry.timestamp = now_datetime()
	entry.insert(ignore_permissions=True)
	return entry


def _get_or_create_user(phone, full_name=None):
	if frappe.db.exists("Coupon User", phone):
		return frappe.get_doc("Coupon User", phone)
	user = frappe.new_doc("Coupon User")
	user.phone = phone
	user.full_name = full_name or ""
	user.insert(ignore_permissions=True)
	return user
```

### 6.1 The four ways to touch the database

Frappe gives you a ladder, and picking the right rung is most of what "writing idiomatic Frappe"
means:

```python
# 1. Document API — validation, hooks, permissions, versions. Use for business writes.
doc = frappe.get_doc("Coupon Card", name)
doc.status = "Redeemed"
doc.save()

# 2. frappe.db — direct SQL, no hooks, no validation. Fast; use for bulk/derived updates.
frappe.db.set_value("Coupon Card", name, "status", "Redeemed")
frappe.db.get_value("Coupon Campaign", campaign, ["points", "is_active"], as_dict=True)
frappe.db.exists("Coupon User", phone)
frappe.db.count("Coupon Card", {"campaign": campaign})

# 3. Query Builder (pypika) — composable, DB-portable, injection-safe. Use for aggregates.
CC = frappe.qb.DocType("Coupon Card")
frappe.qb.from_(CC).select(CC.code).where(CC.status == "Active").limit(50).run(as_dict=True)

# 4. Raw SQL — escape hatch. Always parameterise; never f-string user input.
frappe.db.sql("UPDATE `tabCoupon Card` SET status='Expired' WHERE expiry_date < %s", today())
```

Rules of thumb that hold up in production:

- **A single business write → `get_doc` + `save`.** You want the hooks to fire.
- **Ten thousand rows → SQL or `frappe.db.bulk_insert`.** Ten thousand `save()` calls will run
  every hook ten thousand times and take minutes. `expire_cards()` in
  [`coupon_auto.py`](../coupon_system/coupon_auto.py) is two `UPDATE` statements for exactly this
  reason.
- **Aggregates → query builder.** It reads better than string SQL and survives a DB migration.
- **`%s` parameters, always.** Table/column names can be interpolated; values never.

---

## 7. The API layer: `@frappe.whitelist()`

A whitelisted function is callable over HTTP:

```
POST /api/method/coupon_system.api.scan
```

The dotted path *is* the module path. There's no router, no URL config, no decorator argument —
put the decorator on the function and it's an endpoint. Which is exactly why the rules below
matter: **whitelisting is the security boundary of your app.**

### 7.1 `scan` — earn points from a card

```python
from frappe import _
from frappe.utils import getdate, today


@frappe.whitelist()
def scan(phone, code, full_name=None):
	try:
		# 1. AUTHORISE. Whitelisting only means "reachable" — never "allowed".
		roles = frappe.get_roles()
		if not ({"System Manager", "Coupon Manager", "Coupon Mobile"} & set(roles)):
			frappe.throw(_("Not permitted"))

		# 2. VALIDATE INPUT. Every argument arrives as a string from HTTP.
		if not phone or not str(phone).strip():
			frappe.throw(_("phone is required"))

		card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
		if not card_name:
			frappe.throw(_("Card not found"))

		# 3. LOCK THE ROW before reading it, so two concurrent scans of the same
		#    card can't both see is_used = 0 and both credit points.
		frappe.db.sql("SELECT name FROM `tabCoupon Card` WHERE name = %s FOR UPDATE", card_name)
		card = frappe.get_doc("Coupon Card", card_name)

		_assert_card_scannable(card)

		# 4. Resolve the LIVE value now, then freeze it into the ledger forever.
		points = _resolve_card_points(card)

		# 5. SAVEPOINT: make the multi-write section atomic on its own.
		frappe.db.savepoint("coupon_scan")
		try:
			_get_or_create_user(phone, full_name)

			card.is_used = 1
			card.status = "Redeemed"
			card.used_by_phone = phone
			card.scanned_at = now_datetime()
			card.save(ignore_permissions=True)

			_post_ledger(phone, "CREDIT", points, f"Card {code} scanned")
		except Exception:
			frappe.db.rollback(save_point="coupon_scan")
			raise

		# 6. A STABLE RESPONSE SHAPE the mobile app can rely on.
		return {
			"success": True,
			"points_added": points,
			"new_balance": _get_balance(phone),
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
```

Six habits worth teaching one at a time:

**1 — Whitelist ≠ authorise.** `@frappe.whitelist()` makes a function reachable by *any logged-in
user*. Add `allow_guest=True` and it's reachable by the internet. The role check is yours to write.
Do it as the first statement in the function, every time. (`frappe.only_for(["Coupon Manager"])` is
the shorthand when you don't need a custom message.)

**2 — Everything is a string.** HTTP has no types. `amount` arrives as `"50"`, a JSON list arrives
as a string you must `json.loads`. Use `cint()` / `flt()` / `getdate()` on every numeric or date
argument rather than trusting the caller.

**3 — `SELECT … FOR UPDATE` before a read-then-write.** Without the lock, two scans of the same
card in the same millisecond both read `is_used = 0` and both credit points. Frappe also offers
`frappe.get_doc("Coupon User", phone, for_update=True)`, which is what `redeem()` uses to stop a
customer double-spending a balance from two tills at once.

**4 — Savepoints for partial rollback.** A Frappe request is one transaction. If you need "either
all three of these writes or none, but *don't* kill the whole request", that's
`frappe.db.savepoint(name)` / `frappe.db.rollback(save_point=name)`. §10 shows the version of this
that matters most: letting a coupon failure roll back only itself, never the Work Order that
triggered it.

**5 — One place writes the ledger.** Every credit and debit in this app goes through
`_post_ledger`. When the invariant lives in one function, you can change it in one function.

**6 — Return a shape, don't leak a traceback.** `frappe.throw` raises `ValidationError`; catching it
at the boundary and returning `{"success": False, "error": ...}` gives the mobile client one
predictable envelope instead of a 417 with an HTML body. For conditions the client must *branch*
on, add a stable machine-readable `reason` — `redeem()` returns `reason: "already_redeemed"` so a
POS retry can tell "you already did this" from "this failed", without matching on translated
prose.

### 7.2 The guard clause

```python
def _assert_card_scannable(card):
	"""Raise if a card can't be scanned right now. One function, one truth."""
	if card.get("status") == "Void":
		frappe.throw(_("Card has been voided"))
	if card.get("status") == "Generated":
		frappe.throw(_("Card is not active yet"))
	if card.get("status") == "Redeemed" or card.get("is_used"):
		frappe.throw(_("Card already redeemed"))
	if card.get("status") == "Retired":
		frappe.throw(_("This campaign has ended"))
	if card.get("status") == "Expired" or getdate(card.expiry_date) < getdate(today()):
		frappe.throw(_("Card expired"))


def _resolve_card_points(card):
	"""Live value from the campaign, snapshot as fallback."""
	if card.get("campaign"):
		camp = frappe.db.get_value(
			"Coupon Campaign", card.campaign, ["points", "is_active", "end_date"], as_dict=True
		)
		if camp:
			if not camp.is_active:
				frappe.throw(_("This campaign is not active"))
			if camp.end_date and getdate(camp.end_date) < getdate(today()):
				frappe.throw(_("This campaign has ended"))
			return cint(camp.points)
	return cint(card.get("points_value"))
```

### 7.3 `redeem` — spend points, idempotently

```python
@frappe.whitelist()
def redeem(phone, amount, site_url, invoice_no):
	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		amount = cint(amount)
		if amount <= 0:
			frappe.throw(_("Redemption amount must be greater than 0"))

		# IDEMPOTENCY: a POS that retries on a timeout must not double-charge.
		# The invoice number is the natural idempotency key.
		if frappe.db.exists("Coupon Ledger",
							{"invoice_no": invoice_no, "site_url": site_url, "type": "DEBIT"}):
			return {"success": False, "reason": "already_redeemed",
					"error": _("Already redeemed for this invoice")}

		if not frappe.db.exists("Coupon User", phone):
			frappe.throw(_("User not found"))

		# Lock the customer row: two tills must not both read the same balance.
		frappe.get_doc("Coupon User", phone, for_update=True)

		if _get_balance(phone) < amount:
			frappe.throw(_("Insufficient balance"))

		_post_ledger(phone, "DEBIT", amount, "Redeemed",
					 site_url=site_url, invoice_no=invoice_no)

		return {"success": True, "redeemed": amount, "new_balance": _get_balance(phone)}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
```

**Idempotency is not optional for money.** Any endpoint that moves value gets an idempotency key
from the caller — here the invoice number, which the POS already has. Networks time out *after* the
server committed; the retry must be a no-op, and it must say so distinguishably.

The mirror image is `reverse_redeem()` ([api.py](../coupon_system/api.py)): when an invoice is
cancelled, we don't delete the DEBIT — we post a compensating CREDIT tagged with the same invoice.
An append-only ledger reverses by adding, never by editing. The audit trail stays intact and the
reversal is itself idempotent (a CREDIT with that invoice number already present = already
reversed).

### 7.4 `balance` — read the wallet

```python
from frappe.query_builder import Order


@frappe.whitelist()
def balance(phone):
	try:
		roles = frappe.get_roles()
		if not ({"System Manager", "Coupon Manager", "Coupon Mobile"} & set(roles)):
			frappe.throw(_("Not permitted"))

		if not frappe.db.exists("Coupon User", phone):
			return {"success": False, "error": _("User not found")}

		CL = frappe.qb.DocType("Coupon Ledger")
		ledger = (
			frappe.qb.from_(CL)
			.select(CL.type, CL.points, CL.description, CL.invoice_no, CL.timestamp)
			.where(CL.phone == phone)
			.orderby(CL.timestamp, order=Order.desc)
			.limit(20)                     # a wallet screen shows recent activity, not all of history
			.run(as_dict=True)
		)

		return {
			"success": True,
			"phone": phone,
			"full_name": frappe.db.get_value("Coupon User", phone, "full_name") or phone,
			"points_balance": _get_balance(phone),
			"ledger": ledger,
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
```

Always bound a list an app will render. The production `balance()` also returns `total_earned` /
`total_redeemed` and a per-store breakdown — same shape, more `Case()` expressions.

### 7.5 Unique codes at volume

Generating a hundred thousand cards without collisions, without loading every existing code into
memory:

```python
import secrets

# Crockford base32 minus vowels: no 0/O or 1/I/L to misread on a printed card,
# no vowels so a code can never spell a real (or offensive) word.
_CODE_CHARS = "23456789BCDFGHJKMNPQRSTVWXZ"


def _generate_code(prefix=""):
	part1 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
	part2 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
	body = f"{part1}-{part2}"
	return f"{prefix}-{body}" if prefix else body


def _unique_codes(quantity, seen=None, code_prefix=None):
	"""Generate `quantity` unique codes. O(quantity) memory regardless of table size:
	we check CANDIDATES against the DB, never load the DB into Python."""
	if seen is None:
		seen = set()
	prefix = code_prefix if code_prefix is not None else _code_prefix()
	result = []
	CC = frappe.qb.DocType("Coupon Card")

	while len(result) < quantity:
		# Overshoot 3× to minimise round-trips; 27^8 ≈ 282 billion combinations,
		# so the collision rate is negligible.
		candidates = list({_generate_code(prefix) for _ in range((quantity - len(result)) * 3)})
		candidates = [c for c in candidates if c not in seen]
		if not candidates:
			continue

		taken = {
			r[0] for r in frappe.qb.from_(CC).select(CC.code).where(CC.code.isin(candidates)).run()
		}
		fresh = [c for c in candidates if c not in taken]
		batch = fresh[: quantity - len(result)]
		result.extend(batch)
		seen.update(batch)

	return result
```

And the bulk insert — this is the difference between 2 seconds and 4 minutes for 10,000 cards:

```python
from frappe.model.naming import make_autoname
from frappe.utils import add_months


def _campaign_snapshot(campaign):
	"""Campaign → (points_snapshot, expiry_date). Raises if missing, inactive or ended."""
	camp = frappe.db.get_value(
		"Coupon Campaign", campaign,
		["points", "validity_months", "is_active", "end_date"], as_dict=True,
	)
	if not camp:
		frappe.throw(_("Campaign {0} not found").format(campaign))
	if not camp.is_active:
		frappe.throw(_("Campaign {0} is not active").format(campaign))
	if camp.end_date and getdate(camp.end_date) < getdate(today()):
		frappe.throw(_("Campaign {0} has ended").format(campaign))
	points = cint(camp.points)
	if points <= 0:
		frappe.throw(_("Campaign {0} has no point value set").format(campaign))
	return points, add_months(today(), cint(camp.validity_months) or 12)


def _insert_cards(codes, campaign, points_value, expiry_date, naming_series="CC-.YYYY.-.#####",
				  work_order=""):
	"""bulk_insert bypasses the Document API entirely: no hooks, no validation,
	one INSERT. You are responsible for every column, including the bookkeeping ones."""
	now = now_datetime()
	user = frappe.session.user
	fields = [
		"name", "naming_series", "code", "campaign", "status",
		"points_value", "expiry_date", "work_order",
		"is_used", "docstatus", "creation", "modified", "owner", "modified_by",
	]
	values = [
		[make_autoname(naming_series), naming_series, code, campaign, "Active",
		 points_value, expiry_date, work_order,
		 0, 0, now, now, user, user]
		for code in codes
	]
	frappe.db.bulk_insert("Coupon Card", fields=fields, values=values)
	return {"success": True, "count": len(codes), "codes": codes}


def _generate_batch(quantity, campaign, points_value, expiry_date, work_order=""):
	"""Mint codes, then insert them. Kept separate from _insert_cards so the pure-DB
	write can run right after (never across) any slow work."""
	codes = _unique_codes(quantity)
	return _insert_cards(codes, campaign, points_value, expiry_date, work_order=work_order)


@frappe.whitelist()
def generate_cards(quantity, campaign):
	try:
		frappe.only_for(["System Manager", "Coupon Manager"])
		qty = cint(quantity)
		if qty <= 0:
			frappe.throw(_("quantity must be a positive integer"))
		if qty > 10_000:
			frappe.throw(_("quantity cannot exceed 10,000 per call"))

		points, expiry = _campaign_snapshot(campaign)
		return _generate_batch(qty, campaign, points, expiry)
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
	except Exception:
		# e.g. a unique-code IntegrityError under concurrent generation —
		# return a clean retryable error instead of a 500.
		frappe.log_error(frappe.get_traceback(), "Coupon generate_cards failed")
		return {"success": False, "error": _("Card generation failed — please retry")}
```

Two things to point out in a demo: the **upper bound** on `quantity` (an unbounded loop behind an
HTTP endpoint is a denial-of-service button), and `frappe.log_error()` — which writes to the Error
Log doctype, visible at `/app/error-log`, and is where every "it failed silently" investigation
starts.

---

## 8. Calling your API for real

### 8.1 Make an API user

Rather than clicking through the desk, do it in code — this is `install.py` in the real app
([source](../coupon_system/install.py)):

```python
import secrets

import frappe


def _create_mobile_user():
	email = "coupon-mobile@system.local"
	if frappe.db.exists("User", email):
		return

	user = frappe.new_doc("User")
	user.email = email
	user.first_name = "Coupon Mobile"
	user.user_type = "System User"
	user.send_welcome_email = 0
	user.new_password = secrets.token_urlsafe(24)
	user.append("roles", {"role": "Coupon Mobile"})
	user.insert(ignore_permissions=True)

	api_key = secrets.token_hex(16)
	api_secret = secrets.token_hex(16)
	user.api_key = api_key
	user.api_secret = api_secret
	user.save(ignore_permissions=True)
	frappe.db.commit()

	print(f"API Key: {api_key}\nAPI Secret: {api_secret}")
```

Run it:

```bash
bench --site hq.localhost execute coupon_system.install._create_mobile_user
```

`bench execute` runs any dotted path in a site context. It is the fastest way to try a function
without an HTTP round trip, and you will use it constantly.

### 8.2 curl

```bash
KEY=xxxxxxxx
SECRET=yyyyyyyy
AUTH="Authorization: token $KEY:$SECRET"
SITE=http://hq.localhost:8000

# whitelisted method
curl -s -X POST "$SITE/api/method/coupon_system.api.scan" \
     -H "$AUTH" -d "phone=9876543210" -d "code=7K9M-4P2T" | jq

# {"message": {"success": true, "points_added": 10, "new_balance": 10}}

curl -s "$SITE/api/method/coupon_system.api.balance?phone=9876543210" -H "$AUTH" | jq

# the free REST API every DocType gets, no code written:
curl -s "$SITE/api/resource/Coupon Card?filters=[[\"status\",\"=\",\"Active\"]]&fields=[\"code\"]&limit_page_length=5" \
     -H "$AUTH" | jq
```

Note the envelope: a whitelisted method's return value is always wrapped in `{"message": ...}`.
Mobile clients forget this constantly.

### 8.3 `bench console`

```bash
bench --site hq.localhost console
```

```python
>>> from coupon_system.api import _get_balance, scan
>>> scan(phone="9876543210", code="7K9M-4P2T")
{'success': True, 'points_added': 10, 'new_balance': 10}
>>> _get_balance("9876543210")
10
>>> frappe.get_all("Coupon Ledger", filters={"phone": "9876543210"}, fields=["type", "points"])
[{'type': 'CREDIT', 'points': 10}]
>>> frappe.db.commit()      # ← the console does NOT auto-commit
```

**`frappe.db.commit()` in the console.** Forgetting it, then wondering why the desk doesn't show
your row, is a rite of passage. (Conversely, in *request* code you almost never call `commit()`
yourself — Frappe commits the transaction when the request succeeds, and a manual commit
mid-request throws away your ability to roll back.)

---

## 9. Controllers and the document lifecycle

A controller is where behaviour attaches to data. Frappe calls these methods on your class, in this
order:

| Method | When | Typical use |
|---|---|---|
| `before_insert` | new doc, before first write | defaults, structural guards |
| `validate` | every insert **and** every save | validation, computed fields |
| `before_save` | after validate | last-moment adjustments |
| `after_insert` | new doc committed to the table | side effects for creation only |
| `on_update` | after any save | side effects, sync |
| `before_submit` / `on_submit` | `docstatus` 0 → 1 | submittable docs only |
| `on_cancel` | `docstatus` 1 → 2 | reversals |
| `on_trash` / `after_delete` | delete | cleanup |
| `onload` | doc loaded into a form | virtual/derived display values |

Two rules that save real debugging time:

- **`validate` runs on every save, not just on create.** Guard create-only logic with
  `if self.is_new():`.
- **Never `self.save()` inside `validate` or `on_update`.** That's infinite recursion. Use
  `self.db_set("field", value)` for a targeted write that skips the lifecycle.

Here's a real controller doing a status transition — `Coupon Withdrawal Request`
([source](../coupon_system/coupon_system/doctype/coupon_withdrawal_request/coupon_withdrawal_request.py)):

```python
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class CouponWithdrawalRequest(Document):
	def validate(self):
		if not self.points or self.points <= 0:
			frappe.throw(_("points must be a positive integer"))
		if not self.payout_details or not str(self.payout_details).strip():
			frappe.throw(_("payout_details is required"))

		if self.is_new():
			self.status = "Pending"
			self.requested_on = now_datetime()
			# Snapshot the rate at creation. Changing the setting later must never
			# revalue a request that's already been made.
			if not self.amount:
				rate = flt(frappe.db.get_single_value(
					"Coupon System Settings", "points_to_currency_rate")) or 1
				self.amount = flt(self.points) * rate
		else:
			# Compare against the DB, not against self — self is already mutated.
			previous_status = frappe.db.get_value(self.doctype, self.name, "status")
			if self.status != previous_status:
				self._handle_status_transition(previous_status)

	def _handle_status_transition(self, previous_status):
		if previous_status != "Pending":
			frappe.throw(_("Only a Pending request can change status"))

		if self.status == "Paid":
			from coupon_system.api import _post_ledger
			# The ledger DEBIT happens HERE and only here — exactly once,
			# at the moment staff actually pays out.
			_post_ledger(self.phone, "DEBIT", self.points, f"Withdrawal {self.name}")
			self.paid_on = now_datetime()
		elif self.status == "Rejected":
			self.rejected_on = now_datetime()
		else:
			frappe.throw(_("Invalid status transition"))
```

Three patterns in twenty lines: **snapshot volatile config at creation**, **read the previous value
from the DB to detect a transition**, and **make the state machine explicit** so no path invents a
transition you didn't intend.

> **Submittable documents.** Add `"is_submittable": 1` to a DocType JSON and you get the
> draft → submitted → cancelled (`docstatus` 0/1/2) workflow, with submitted docs immutable except
> for fields marked `allow_on_submit`. That's how every ERPNext transaction works. We don't need it
> for coupons — but if you're modelling something accounting-shaped, reach for it rather than
> rebuilding it out of a `Select`.

---

## 10. Hooking into other apps: doc_events and scheduler

This is where a Frappe app stops being a CRUD app. You can attach behaviour to *any* DocType in
*any* installed app without touching its code.

Our rule: when a Work Order (ERPNext manufacturing) is submitted, generate the coupon cards its BOM
calls for, so the crew can print and insert them during packing.

In `hooks.py`:

```python
doc_events = {
	"Work Order": {
		"on_submit": "coupon_system.coupon_auto.generate_on_work_order",
		"on_cancel": "coupon_system.coupon_auto.void_on_work_order_cancel",
	},
	# A structural guard — see §10.2
	"Coupon Ledger": {
		"before_insert": "coupon_system.guards.block_local_ledger_in_store_mode",
	},
}

scheduler_events = {
	"daily": [
		"coupon_system.coupon_auto.expire_cards",
	],
}
```

`coupon_system/coupon_auto.py` (trimmed from
[the real file](../coupon_system/coupon_auto.py)):

```python
import frappe
from frappe import _
from frappe.utils import cint, flt


def generate_on_work_order(doc, method=None):
	"""Hook handlers always take (doc, method=None)."""
	# An amendment re-fires on_submit on a NEW doc (WO-x → WO-x-1). The original run's
	# cards already exist, so generating again would double the batch. Skip amendments.
	if doc.get("amended_from"):
		return

	rows = doc.get("required_items") or []
	if not rows:
		return

	# ONE query for all coupon components, not a lookup per row. This hook runs on
	# every Work Order submit on the site — including ones with no coupons at all.
	item_codes = list({r.item_code for r in rows if r.item_code})
	if not item_codes:
		return
	coupon_items = {
		i.name: i
		for i in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes], "custom_coupon_campaign": ["is", "set"]},
			fields=["name", "custom_coupon_campaign", "custom_coupon_enabled"],
		)
	}
	if not coupon_items:
		return

	from coupon_system.api import _campaign_snapshot, _generate_batch

	seen_campaigns = set()
	for req in rows:
		item = coupon_items.get(req.item_code)
		if not item:
			continue
		if item.custom_coupon_enabled is not None and not cint(item.custom_coupon_enabled):
			continue
		campaign = item.custom_coupon_campaign
		if campaign in seen_campaigns:
			continue

		qty = int(round(flt(req.required_qty)))   # round, don't truncate: 9.9999 must not lose a card
		if qty <= 0:
			continue

		# Idempotency again: never double-generate for the same WO + campaign.
		if frappe.db.exists("Coupon Card", {"work_order": doc.name, "campaign": campaign}):
			seen_campaigns.add(campaign)
			continue

		# THE IMPORTANT PART: a coupon failure must never roll back the Work Order.
		frappe.db.savepoint("coupon_gen")
		try:
			points, expiry = _campaign_snapshot(campaign)
			_generate_batch(qty, campaign, points, expiry, work_order=doc.name)
			seen_campaigns.add(campaign)
			frappe.msgprint(
				_("Generated {0} '{1}' coupon card(s) — ready to print").format(qty, campaign),
				indicator="green", alert=True,
			)
		except Exception:
			frappe.db.rollback(save_point="coupon_gen")
			frappe.log_error(frappe.get_traceback(), f"Coupon generation failed for WO {doc.name}")
			frappe.msgprint(
				_("Could not generate '{0}' coupon cards — generate them manually. "
				  "(Production was not affected.)").format(campaign),
				indicator="orange", alert=True,
			)
```

### 10.1 The etiquette of hooking someone else's DocType

This is the part people get wrong, and it's worth a slide of its own:

- **Your side effect must not break their transaction.** Production must not halt because a coupon
  table was locked. Savepoint your own work, roll back only that, log, warn, carry on.
- **Fail fast when it isn't your business.** The four early `return`s above run on every Work Order
  on the site. Cheap exits first, queries only once you know there's work.
- **Batch your queries.** One `get_all` with `["in", item_codes]`, not one lookup per BOM line.
- **Be idempotent.** Submits get retried; amendments re-fire `on_submit` on a *new* document.
- **Long work belongs in a queue.** `frappe.enqueue("app.module.fn", queue="long", **kwargs)` moves
  it to a background worker so the user's save returns immediately.

### 10.2 Structural guards

`guards.py` is small and worth reading as a design idea rather than as code
([source](../coupon_system/guards.py)):

```python
"""Structural guards that make an invariant impossible to violate by accident."""

import frappe
from frappe import _


def block_local_ledger_in_store_mode(doc, method=None):
	"""In Store mode the local Coupon Ledger must never be written — points live on HQ.

	This is the SINGLE backstop for every local points path: earn, redeem and payout all
	go through a Coupon Ledger insert, so blocking the insert makes the whole class of
	local-wallet misuse impossible. A stray hook or a curious admin can't create a second,
	divergent wallet.
	"""
	from coupon_system.hq_client import is_store

	if is_store():
		frappe.throw(_("This site is in Store mode — points are held on HQ, not written locally."))
```

Find the one chokepoint every path must pass through, and enforce the invariant *there*. One hook
on `before_insert` retires an entire category of bug — and it keeps working when someone adds a
feature next year that you never anticipated.

### 10.3 The scheduler

```python
def expire_cards():
	"""Daily sweep: retire unused cards past their expiry, or whose campaign has ended."""
	from frappe.utils import today

	t = today()

	frappe.db.sql(
		"""
		UPDATE `tabCoupon Card`
		SET status = 'Expired'
		WHERE status IN ('Active', 'Generated') AND is_used = 0 AND expiry_date < %s
		""",
		t,
	)

	frappe.db.sql(
		"""
		UPDATE `tabCoupon Card` cc
		JOIN `tabCoupon Campaign` camp ON camp.name = cc.campaign
		SET cc.status = 'Retired'
		WHERE cc.status IN ('Active', 'Generated') AND cc.is_used = 0
		  AND camp.end_date IS NOT NULL AND camp.end_date < %s
		""",
		t,
	)
```

Available buckets: `all` (every ~4 min), `hourly`, `daily`, `weekly`, `monthly`, plus `cron` for
arbitrary expressions:

```python
scheduler_events = {
	"cron": {
		"0 3 * * *": ["coupon_system.coupon_auto.expire_cards"],
	},
}
```

Two set-up gotchas: the scheduler is **disabled on new sites** (`bench --site hq.localhost
enable-scheduler`), and it runs in a worker process, so `bench start` must be running. Test the
function directly with `bench execute` rather than waiting for a tick.

---

## 11. Extending a standard DocType: custom fields in code

We need two fields on ERPNext's `Item`: is this a coupon component, and which campaign. You *could*
add them by hand in the UI — and then they exist on your laptop and nowhere else. Instead, ship
them in `after_install` / `after_migrate` so every site gets them from git.

In `hooks.py`:

```python
after_install = "coupon_system.install.after_install"
after_migrate = "coupon_system.install.after_migrate"
before_uninstall = "coupon_system.uninstall.before_uninstall"
```

`coupon_system/install.py` (trimmed from [the real file](../coupon_system/install.py)):

```python
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

_OWN_FIELDS = ("custom_coupon_tab", "custom_coupon_enabled", "custom_coupon_campaign")


def _item_custom_fields(anchor):
	return {
		"Item": [
			{
				"fieldname": "custom_coupon_tab",
				"fieldtype": "Tab Break",
				"label": "Coupon Cards",
				"insert_after": anchor,
			},
			{
				"fieldname": "custom_coupon_enabled",
				"fieldtype": "Check",
				"label": "Coupon Generation Enabled",
				"default": "0",
				"insert_after": "custom_coupon_tab",
				"description": "Off by default — a normal item is not a coupon.",
			},
			{
				"fieldname": "custom_coupon_campaign",
				"fieldtype": "Link",
				"label": "Coupon Campaign",
				"options": "Coupon Campaign",
				"insert_after": "custom_coupon_enabled",
				"depends_on": "custom_coupon_enabled",
				"mandatory_depends_on": "custom_coupon_enabled",
			},
		]
	}


def after_install():
	ensure_custom_fields()


def after_migrate():
	ensure_custom_fields()


def ensure_custom_fields():
	# Anchor our tab to the form's CURRENT last field, ignoring our own fields so
	# re-runs don't chain onto themselves. Never hard-code an ERPNext fieldname as
	# the anchor — it will be renamed in a version you don't control.
	anchor = None
	for field in reversed(frappe.get_meta("Item").fields):
		if field.fieldname not in _OWN_FIELDS:
			anchor = field.fieldname
			break

	create_custom_fields(_item_custom_fields(anchor), ignore_validate=True)
```

Four rules for this pattern:

1. **Prefix with `custom_`.** It marks the field as yours and avoids colliding with a future
   upstream field of the same name.
2. **Idempotent, always.** `after_migrate` runs on *every* deploy. `create_custom_fields` updates
   rather than duplicating, but any extra logic you add must tolerate re-running — note how the
   anchor computation skips its own fields, or each migrate would nest the tab one level deeper.
3. **Anchor dynamically.** `insert_after` pointing at an ERPNext fieldname is a time bomb across
   version upgrades.
4. **Clean up on uninstall.** `bench uninstall-app` removes records the app *owns*. A Custom Field
   living on ERPNext's `Item` is not owned by you, so it survives — and a `Link` pointing at your
   now-deleted `Coupon Campaign` breaks every Item form with "Missing DocType". Remove them
   explicitly ([uninstall.py](../coupon_system/uninstall.py)):

```python
import frappe


def before_uninstall():
	for docname in ("Item-custom_coupon_tab", "Item-custom_coupon_enabled",
					"Item-custom_coupon_campaign"):
		if frappe.db.exists("Custom Field", docname):
			frappe.delete_doc("Custom Field", docname, ignore_permissions=True, force=True)

	frappe.clear_cache(doctype="Item")
```

### 11.1 Seeding data on install

Same file, same idempotency rule — never overwrite what's already there:

```python
_DEFAULT_CAMPAIGNS = [
	{"campaign_name": "Plumber 5", "audience": "Plumber", "points": 5},
	{"campaign_name": "Plumber 10", "audience": "Plumber", "points": 10},
]


def seed_campaigns():
	for c in _DEFAULT_CAMPAIGNS:
		if frappe.db.exists("Coupon Campaign", c["campaign_name"]):
			continue          # never overwrite an admin's edits
		doc = frappe.new_doc("Coupon Campaign")
		doc.campaign_name = c["campaign_name"]
		doc.points = c["points"]
		doc.validity_months = 12
		doc.is_active = 1
		if frappe.db.exists("Customer Group", c["audience"]):   # link only if it exists
			doc.audience = c["audience"]
		doc.insert(ignore_permissions=True)
		print(f"[coupon_system] Seeded campaign: {c['campaign_name']}")
```

The real `install.py` also builds an approval `Workflow` in code (`ensure_withdrawal_workflow`) —
worth a look if you want states and transitions with approval rules without writing a UI.

---

## 12. Desk UI: form JS and list JS

Frappe's desk is a JS app you extend with small event handlers. No build step, no framework, no
imports — the files are served as-is.

### 12.1 Form script

A DocType's `.js` file next to its `.json` is loaded automatically on that form.

`coupon_campaign/coupon_campaign.js` (trimmed from
[the real file](../coupon_system/coupon_system/doctype/coupon_campaign/coupon_campaign.js)):

```javascript
frappe.ui.form.on("Coupon Campaign", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(__("Generate Cards"), () => {
			const d = new frappe.ui.Dialog({
				title: __("Generate Cards — {0}", [frm.doc.campaign_name]),
				fields: [
					{
						fieldname: "quantity",
						label: __("Quantity"),
						fieldtype: "Int",
						reqd: 1,
						default: 100,
						description: __("Cards are minted Active, ready to print."),
					},
					{
						fieldname: "item_code",
						label: __("Item (optional, for traceability)"),
						fieldtype: "Link",
						options: "Item",
					},
				],
				primary_action_label: __("Generate"),
				primary_action(values) {
					frappe.call({
						method: "coupon_system.api.generate_cards",
						args: { quantity: values.quantity, campaign: frm.doc.name },
						freeze: true,
						freeze_message: __("Generating cards…"),
						callback(r) {
							const m = r.message;
							if (m && m.success) {
								frappe.show_alert({
									message: __("{0} cards generated", [m.count]),
									indicator: "green",
								});
								d.hide();
							} else {
								frappe.msgprint((m && m.error) || __("Generation failed"));
							}
						},
					});
				},
			});
			d.show();
		});

		if (!frm.doc.is_active) {
			frm.dashboard.set_headline(
				__("This campaign is inactive — its cards cannot be scanned.")
			);
		}

		render_card_stats(frm);
	},

	// fires when a specific field changes
	points(frm) {
		if (frm.doc.points > 1000) {
			frappe.msgprint(__("That's a lot of points — double-check the value."));
		}
	},
});

function render_card_stats(frm) {
	frappe.call({
		method: "coupon_system.api.campaign_card_counts",
		args: { campaign: frm.doc.name },
		callback(r) {
			const s = r.message;
			if (!s) return;
			const tile = (label, val, color) => `
				<div style="flex:1; min-width:90px; text-align:center; padding:12px 8px;
							border:1px solid var(--border-color); border-radius:8px;">
					<div style="font-size:22px; font-weight:700; color:${color || "inherit"};">${val}</div>
					<div class="text-muted" style="font-size:11px; text-transform:uppercase;">${label}</div>
				</div>`;
			frm.dashboard.add_section(
				`<div style="display:flex; gap:10px; flex-wrap:wrap; margin:8px 0 4px;">
					${tile(__("Total"), s.total)}
					${tile(__("Active"), s.active, "#2563eb")}
					${tile(__("Redeemed"), s.redeemed, "#16a34a")}
					${tile(__("Expired"), s.expired, "#a16207")}
				</div>`,
				__("Card Lifecycle")
			);
		},
	});
}
```

The API surface you'll use 90% of the time:

| Call | Does |
|---|---|
| `frm.add_custom_button(label, fn, group)` | button in the top-right menu |
| `frm.set_value(field, val)` / `frm.set_df_property(field, "hidden", 1)` | change data / change the field |
| `frm.toggle_display(field, bool)`, `frm.set_query(field, fn)` | show/hide, filter a Link's options |
| `frm.dashboard.add_section(html, title)` / `.set_headline(html)` | custom blocks on the form |
| `frappe.call({method, args, callback, freeze})` | call a whitelisted method |
| `frappe.msgprint`, `frappe.show_alert`, `frappe.confirm`, `frappe.prompt` | user interaction |
| `new frappe.ui.Dialog({...})` | a form in a modal, using the same fieldtypes as a DocType |
| `__("text")` | translate — wrap every user-visible string |

Note that a dialog's `fields` use the exact same fieldtype vocabulary as a DocType JSON. Learn the
schema once, use it in three places.

### 12.2 List view script

List scripts live in `public/js/` and are wired up in `hooks.py`:

```python
doctype_list_js = {
	"Coupon Card": "public/js/coupon_card_list.js"
}
```

`coupon_system/public/js/coupon_card_list.js`:

```javascript
frappe.listview_settings["Coupon Card"] = {
	// colour the status column automatically
	get_indicator(doc) {
		const map = {
			Active: "blue", Redeemed: "green", Expired: "orange",
			Retired: "grey", Void: "red", Generated: "light-blue",
		};
		return [__(doc.status), map[doc.status] || "grey", "status,=," + doc.status];
	},

	onload(listview) {
		// appears in the Actions dropdown when rows are checked
		listview.page.add_actions_menu_item(__("Print Selected Cards"), () => {
			const names = listview.get_checked_items(true);
			if (!names.length) {
				frappe.msgprint(__("Select at least one card."));
				return;
			}
			const filters = [["Coupon Card", "name", "in", names]];
			const params = new URLSearchParams({ filters: JSON.stringify(filters) });
			window.open(`/print_cards?${params}`, "_blank");
		});

		// always-visible button in the page header
		listview.page.add_inner_button(__("Print Filtered Cards"), () => {
			const filters = listview.get_filters_for_args();
			const params = new URLSearchParams({ filters: JSON.stringify(filters) });
			window.open(`/print_cards?${params}`, "_blank");
		});
	},
};
```

After touching anything under `public/`:

```bash
bench build --app coupon_system      # or `bench watch` while developing
```

…then a hard refresh. "My JS change didn't apply" is almost always a missing `bench build` or a
cached bundle.

---

## 13. Website pages: `www/`

Anything under `coupon_system/www/` becomes a public URL. `www/s.html` → `/s`. No routing config
needed; a `.py` file of the same name supplies the context.

We need it because the QR on each card points at `https://.../s/<code>` — a URL that opens the
mobile app if installed, and otherwise shows a "get the app" page.

`hooks.py`:

```python
website_route_rules = [
	{"from_route": "/s/<code>", "to_route": "s"},
]
```

`coupon_system/www/s.py`:

```python
import frappe

no_cache = 1


def get_context(context):
	# A bare /s/ (Play Console App Links validation hits it) must still return 200,
	# so render the generic landing page rather than throwing.
	code = frappe.form_dict.get("code") or ""

	context.code = code
	context.play_store_url = frappe.db.get_single_value("Coupon System Settings", "play_store_url") or "#"
	context.app_store_url = frappe.db.get_single_value("Coupon System Settings", "app_store_url") or "#"
	context.no_breadcrumbs = True
	context.title = "Open in App"
```

`coupon_system/www/s.html`:

```html
{% extends "templates/web.html" %}

{% block title %}Open in the App{% endblock %}

{% block page_content %}
<div class="scan-wrap">
  <div class="scan-card">
    <h2>Open in the App</h2>
    <p class="sub">Download the app to scan this coupon card and collect your points.</p>

    {% if play_store_url != "#" %}
      <a class="badge" href="{{ play_store_url }}">Get it on Google Play</a>
    {% else %}
      <div class="coming-soon">🎁 The app is launching soon!</div>
    {% endif %}

    {% if code %}<div class="scan-code">Card code: <b>{{ code }}</b></div>{% endif %}
  </div>
</div>
{% endblock %}
```

Jinja, extending the framework's `templates/web.html` so you inherit the site's nav, theme and
mobile viewport. `<code>` from the route rule arrives in `frappe.form_dict`.

### 13.1 Jinja methods

To use your own Python inside any template or Print Format, register it:

```python
jinja = {
	"methods": ["coupon_system.utils.get_coupon_qr", "coupon_system.utils.get_coupon_barcode"]
}
```

`coupon_system/utils.py`:

```python
import base64
from io import BytesIO

import frappe
import qrcode


def get_coupon_qr(code):
	base_url = frappe.db.get_single_value("Coupon System Settings", "scan_base_url")
	if not base_url:
		frappe.throw(frappe._("Coupon System Settings: scan_base_url is not configured"))
	url = f"{base_url.rstrip('/')}/{code}"
	img = qrcode.make(url)
	buffer = BytesIO()
	img.save(buffer, format="PNG")
	encoded = base64.b64encode(buffer.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"      # inline — no file, no static hosting


def get_coupon_barcode(code):
	import barcode
	from barcode.writer import ImageWriter

	bar = barcode.get("code128", code, writer=ImageWriter())
	buffer = BytesIO()
	bar.write(buffer, options={"write_text": False, "quiet_zone": 2, "module_height": 10})
	encoded = base64.b64encode(buffer.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"
```

Then anywhere in a template:

```html
<img src="{{ get_coupon_qr(card.code) }}" width="120">
```

Returning a `data:` URI rather than writing a file means the print sheet has no dependency on the
filesystem, no cleanup job, and works offline in a saved HTML page.

### 13.2 A print sheet

`www/print_cards.py` — a page whose whole job is to render an A4 grid of cards for the print room:

```python
import json

import frappe


def get_context(context):
	frappe.only_for(["System Manager", "Coupon Manager"])   # a www page is PUBLIC by default
	context.no_cache = 1
	context.full_width = 1

	raw_filters = json.loads(frappe.form_dict.get("filters", "[]"))

	filters = {}
	for f in raw_filters:
		if len(f) == 4:
			field, op, value = f[1], f[2], f[3]
			if op == "=":
				filters[field] = value
			elif op == "in":
				filters[field] = ["in", value]

	cards = frappe.get_all(
		"Coupon Card",
		filters=filters,
		fields=["name", "code", "points_value", "expiry_date"],
		order_by="creation asc",
		limit_page_length=0,          # 0 = no limit; default is 20
	)
	if not cards:
		frappe.throw("No cards found for the selected filters.")

	context.cards = cards
	context.total = len(cards)
```

**`frappe.only_for()` on the first line.** Every `www/` page is world-readable unless you say
otherwise. This is the single most likely place for a Frappe app to leak data, and it's the list JS
from §12.2 that links here with the user's current filters — the same filter vocabulary flowing
from list view → URL → `get_all`.

---

## 14. Reports

Three kinds: **Query Report** (one SQL string, stored in the DB), **Script Report** (Python, lives
in your app, versioned in git), and **Report Builder** (user-configured, no code). Script Report is
what you write in an app.

```
coupon_system/coupon_system/report/coupon_card_traceability/
├── __init__.py
├── coupon_card_traceability.json
└── coupon_card_traceability.py
```

`coupon_card_traceability.json`:

```json
{
 "add_total_row": 1,
 "creation": "2026-06-23 00:00:00.000000",
 "disabled": 0,
 "docstatus": 0,
 "doctype": "Report",
 "idx": 0,
 "is_standard": "Yes",
 "module": "Coupon System",
 "name": "Coupon Card Traceability",
 "owner": "Administrator",
 "modified": "2026-06-23 00:00:00.000000",
 "modified_by": "Administrator",
 "prepared_report": 0,
 "ref_doctype": "Coupon Card",
 "report_name": "Coupon Card Traceability",
 "report_type": "Script Report",
 "roles": [{"role": "System Manager"}, {"role": "Coupon Manager"}]
}
```

`"is_standard": "Yes"` is what makes it load from your app's files rather than from the database.

`coupon_card_traceability.py` — one function, returning `(columns, rows)`:

```python
import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}

	conditions = []
	values = {}
	if filters.get("campaign"):
		conditions.append("campaign = %(campaign)s")
		values["campaign"] = filters["campaign"]
	if filters.get("item_code"):
		conditions.append("item_code = %(item_code)s")
		values["item_code"] = filters["item_code"]

	where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

	# One row per campaign × item, with a count column per lifecycle state.
	rows = frappe.db.sql(
		f"""
		SELECT
			campaign,
			item_code,
			SUM(status = 'Generated') AS generated,
			SUM(status = 'Active')    AS active,
			SUM(status = 'Redeemed')  AS redeemed,
			SUM(status = 'Expired')   AS expired,
			COUNT(*)                  AS total
		FROM `tabCoupon Card`
		{where}
		GROUP BY campaign, item_code
		ORDER BY campaign, item_code
		""",
		values,
		as_dict=True,
	)

	columns = [
		{"label": _("Campaign"), "fieldname": "campaign", "fieldtype": "Link",
		 "options": "Coupon Campaign", "width": 150},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link",
		 "options": "Item", "width": 160},
		{"label": _("Generated"), "fieldname": "generated", "fieldtype": "Int", "width": 100},
		{"label": _("Active"), "fieldname": "active", "fieldtype": "Int", "width": 90},
		{"label": _("Redeemed"), "fieldname": "redeemed", "fieldtype": "Int", "width": 100},
		{"label": _("Expired"), "fieldname": "expired", "fieldtype": "Int", "width": 90},
		{"label": _("Total"), "fieldname": "total", "fieldtype": "Int", "width": 90},
	]

	return columns, rows
```

Notice the f-string builds only the **`WHERE` clause skeleton** from a fixed set of literals, while
every *value* goes through `%(name)s` parameters. That's the safe shape for dynamic SQL: structure
interpolated from your own constants, values always bound.

Give a column `"fieldtype": "Link"` and the report renders it as a clickable link to the record —
free navigation from a report row to the document.

---

## 15. Roles, permissions and fixtures

### 15.1 The permission layers

1. **Role permissions** — the `permissions` block of a DocType JSON. Per role, per operation
   (`read`/`write`/`create`/`delete`/`submit`/`cancel`/`report`/`export`/`share`/`email`/`print`),
   optionally per `permlevel` for field-level control.
2. **User permissions** — records restricting a user to specific documents ("only Store A").
3. **`permission_query_conditions`** — a hook returning a SQL `WHERE` fragment injected into every
   list query for a DocType. This is how you say "an agent sees only their own leads".
4. **`has_permission`** — a hook for per-document Python logic.
5. **Your own code** — the `frappe.get_roles()` check at the top of every whitelisted method (§7).

Layers 1–4 are the framework's. Layer 5 is yours, and it is not optional: **the framework's
permission system does not run inside your whitelisted method.** `ignore_permissions=True` — which
you need constantly, because a mobile user should be able to earn points without write access to
the ledger — bypasses layers 1–4 completely. That's precisely why the role check has to be the
first line.

### 15.2 Defining a role in code

Roles aren't DocTypes you write JSON for — they're *records*. Ship them as **fixtures**: records
exported to JSON in your app and re-imported on every migrate.

`hooks.py`:

```python
fixtures = [
	{"dt": "Role", "filters": [["role_name", "in", ["Coupon Manager", "Coupon Mobile"]]]},
]
```

Create the roles once in the desk (or in `after_install`), then:

```bash
bench --site hq.localhost export-fixtures --app coupon_system
```

which writes `coupon_system/fixtures/role.json`:

```json
[
 {
  "desk_access": 1,
  "disabled": 0,
  "docstatus": 0,
  "doctype": "Role",
  "name": "Coupon Manager",
  "role_name": "Coupon Manager",
  "two_factor_auth": 0
 }
]
```

Commit that file, and every future `bench migrate` on every site creates the role. Fixtures are the
right tool for reference data you *own* — roles, custom print formats, workflow states, category
lists. They're the wrong tool for anything users edit, because the next migrate overwrites their
changes.

Note `desk_access: 0` for a pure API role like `Coupon Mobile`: the mobile app's user can call
methods but can't log into the desk UI at all. Cheap defence in depth.

---

## 16. Patches (data migrations)

DocType JSON handles *schema*. Patches handle *data* — backfilling a new column, renaming a value,
fixing what a bug wrote.

`coupon_system/patches/v1_0/backfill_coupon_card_naming_series.py`:

```python
import frappe


def execute():
	frappe.db.sql("""
		UPDATE `tabCoupon Card`
		SET naming_series = 'CC-.YYYY.-.#####'
		WHERE naming_series IS NULL OR naming_series = ''
	""")
```

Register it in `patches.txt`:

```
[pre_model_sync]
# runs BEFORE doctypes are migrated — for fixing data that would block a schema change

[post_model_sync]
# runs AFTER doctypes are migrated — the usual case: the column now exists
coupon_system.patches.v1_0.backfill_coupon_card_naming_series
```

Rules:

- **`__init__.py` in every patch directory** (`patches/`, `patches/v1_0/`).
- **A patch runs once per site, ever.** Frappe records the dotted path in the `Patch Log` table. To
  re-run in dev: `bench --site hq.localhost execute path.to.patch.execute`, or delete its Patch Log
  row.
- **Write patches to be re-runnable anyway.** The `WHERE naming_series IS NULL` above touches only
  unset rows. You will eventually need to re-run one on a restored backup.
- **`pre_model_sync` vs `post_model_sync`:** if your patch reads a column the *new* schema adds,
  it's `post`. If it must clean up data that would break the schema change itself (a duplicate
  value about to get a unique index), it's `pre`.
- **Never delete a patch file** once it's shipped — sites that haven't migrated yet still need it.
- **Renaming a field** is `frappe.model.rename_doc.rename_field("Coupon Card", "old", "new")` in a
  `pre_model_sync` patch, *plus* the JSON change. Doing only the JSON change drops the column and
  its data.

---

## 17. Tests

Frappe ships a test runner over `unittest`. Tests run against a real site with a real database, in
a transaction that's rolled back after each test.

`coupon_system/coupon_system/doctype/coupon_card/test_coupon_card.py`:

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from coupon_system.api import balance, generate_cards, redeem, scan

_TEST_CAMPAIGN = "TEST Plumber 50"


def ensure_test_campaign(points=50, is_active=1, end_date=None):
	if frappe.db.exists("Coupon Campaign", _TEST_CAMPAIGN):
		frappe.db.set_value("Coupon Campaign", _TEST_CAMPAIGN,
							{"points": points, "is_active": is_active, "end_date": end_date})
	else:
		doc = frappe.new_doc("Coupon Campaign")
		doc.campaign_name = _TEST_CAMPAIGN
		doc.points = points
		doc.validity_months = 12
		doc.is_active = is_active
		doc.end_date = end_date
		doc.insert(ignore_permissions=True)
	return _TEST_CAMPAIGN


def make_card(code, points_value=100, days_ahead=30, campaign=None, status="Active"):
	frappe.db.delete("Coupon Card", {"code": code})
	doc = frappe.new_doc("Coupon Card")
	doc.code = code
	doc.points_value = points_value
	doc.expiry_date = add_days(today(), days_ahead)
	doc.status = status
	doc.campaign = campaign
	doc.insert(ignore_permissions=True)
	return doc


def cleanup_user(phone):
	frappe.db.delete("Coupon Ledger", {"phone": phone})
	if frappe.db.exists("Coupon User", phone):
		frappe.delete_doc("Coupon User", phone, ignore_permissions=True, force=True)


class TestCouponCard(IntegrationTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.campaign = ensure_test_campaign(points=50)

	def setUp(self):
		self.phone = "9990001111"
		cleanup_user(self.phone)

	def test_scan_credits_live_campaign_value(self):
		make_card("TEST-AAAA-1111", points_value=10, campaign=self.campaign)   # snapshot says 10

		res = scan(phone=self.phone, code="TEST-AAAA-1111")

		self.assertTrue(res["success"])
		self.assertEqual(res["points_added"], 50)      # campaign wins over the snapshot
		self.assertEqual(res["new_balance"], 50)

	def test_scan_twice_is_rejected(self):
		make_card("TEST-AAAA-2222", campaign=self.campaign)
		scan(phone=self.phone, code="TEST-AAAA-2222")

		res = scan(phone=self.phone, code="TEST-AAAA-2222")

		self.assertFalse(res["success"])
		self.assertIn("already redeemed", res["error"].lower())

	def test_expired_card_is_rejected(self):
		make_card("TEST-AAAA-3333", days_ahead=-1, campaign=self.campaign)

		res = scan(phone=self.phone, code="TEST-AAAA-3333")

		self.assertFalse(res["success"])
		self.assertIn("expired", res["error"].lower())

	def test_redeem_is_idempotent_per_invoice(self):
		make_card("TEST-AAAA-4444", campaign=self.campaign)
		scan(phone=self.phone, code="TEST-AAAA-4444")           # +50

		first = redeem(phone=self.phone, amount=20, site_url="https://s.example.com",
					   invoice_no="INV-001")
		second = redeem(phone=self.phone, amount=20, site_url="https://s.example.com",
						invoice_no="INV-001")

		self.assertTrue(first["success"])
		self.assertFalse(second["success"])
		self.assertEqual(second["reason"], "already_redeemed")   # machine-readable, not prose
		self.assertEqual(balance(phone=self.phone)["points_balance"], 30)

	def test_cannot_overspend(self):
		make_card("TEST-AAAA-5555", campaign=self.campaign)
		scan(phone=self.phone, code="TEST-AAAA-5555")           # +50

		res = redeem(phone=self.phone, amount=999, site_url="https://s.example.com",
					 invoice_no="INV-002")

		self.assertFalse(res["success"])
		self.assertIn("insufficient", res["error"].lower())
```

Running them:

```bash
bench --site hq.localhost run-tests --app coupon_system
bench --site hq.localhost run-tests --module coupon_system.tests.test_store_buckets
bench --site hq.localhost run-tests --doctype "Coupon Card"
```

Notes that matter:

- **`IntegrationTestCase` wraps each test in a transaction and rolls back.** You still clean up
  explicitly for anything crossing a test boundary (`setUpClass` fixtures, `frappe.db.delete` in
  `setUp`) — see `cleanup_user` above. If you override `setUpClass`, call `super().setUpClass()`.
  (The test files in this repo still use the v15 `FrappeTestCase`; it imports on v16 but is removed
  in v17, so they need this swap when the site moves.)
- **Test the API functions directly**, not over HTTP. They're plain Python; call them.
- **Test the invariants, not the getters.** The five tests above are: live value beats snapshot,
  double-scan rejected, expiry enforced, redeem idempotent, no overspend. Every one of them is a
  rule that would cost real money if it broke — that's the bar for what's worth a test.
- **Mock the network.** `coupon_system/tests/test_store_buckets.py` uses
  `unittest.mock.patch` on the gateway proxy so cross-site tests never make a real HTTP call.
- Frappe also picks up `test_records.json` next to a DocType to auto-create fixtures — handy, but
  explicit factory functions like `make_card()` read better in a demo.

---

## 18. Dev workflow and the gotchas that cost hours

### 18.1 The loop

```bash
# terminal 1
bench start

# terminal 2 — after ANY .json / hooks.py change
bench --site hq.localhost migrate

# after a public/ (js, css) change
bench build --app coupon_system

# when something is stale and you can't explain it
bench --site hq.localhost clear-cache
bench --site hq.localhost clear-website-cache
```

### 18.2 The gotchas

**Python changes need a process restart when the reloader is off.** `bench start` normally
auto-reloads. Production, and any site started with `--noreload`, does not — your edit is on disk
and the running worker is still executing the old bytecode. This repo's sites run `--noreload`
deliberately (see [`docs/operations.md`](operations.md)): **restart the process after a code
change**, or you will debug a fix that was never loaded.

**`hooks.py` is cached.** A new hook needs `bench --site … migrate` or at least `clear-cache`.
Editing `doc_events` and seeing nothing happen is almost always this.

**`bench migrate` runs `after_migrate` for every installed app.** So an expensive or non-idempotent
`after_migrate` slows down, or breaks, every deploy on every site. Keep it cheap and re-runnable.

**Missing `__init__.py`** → `ModuleNotFoundError` on migrate. Check the module dir, the doctype
dir, the patches dirs.

**DocType name ↔ file name ↔ class name** must all agree:
`Coupon Card` → `coupon_card/coupon_card.py` → `class CouponCard`.

**Nothing shows in the desk** → check the DocType's `permissions` block. An empty block means only
Administrator.

**Nothing commits in the console** → `frappe.db.commit()`. And conversely, don't call it inside
request code.

**`frappe.get_doc` on a Single** → use `frappe.db.get_single_value` (or `frappe.get_cached_doc`) —
`get_doc("Coupon System Settings")` works but re-reads the key/value table.

**Passwords.** A `Password` fieldtype is stored encrypted in `__Auth`, not in your table. Read it
with `get_decrypted_password("Coupon Store", name, "service_secret")` — `doc.service_secret` gives
you a placeholder. Never use a `Data` field for a secret. (This repo's rule, in `CLAUDE.md`.)

**Site context in scripts.** `bench execute` and `bench console` give you `frappe.local` bound to a
site. A bare `python script.py` does not — it needs
`frappe.init(site=...); frappe.connect()`.

### 18.3 Where to look when it breaks

| Symptom | Look at |
|---|---|
| Endpoint 500s | `bench --site … console` → `frappe.get_all("Error Log", …)`, or `/app/error-log` |
| Scheduled job didn't run | `/app/scheduled-job-type`, and `bench --site … enable-scheduler` |
| Background job vanished | `/app/rq-job`, `bench doctor` |
| Emails/queue stuck | `bench --site … show-pending-jobs` |
| Any request | `bench start` terminal, and `logs/` in the bench dir |
| "It worked yesterday" | `/app/version/…` — `track_changes` recorded who changed which field |

---

## 19. Bonus: talking to another site over HTTP

Frappe apps often span sites — a central HQ and per-store sites. The pattern from
[`hq_client.py`](../coupon_system/hq_client.py), trimmed:

```python
import frappe
from frappe import _
from frappe.utils import get_request_session, get_url

_TIMEOUT = 15


def call_hq(method, **params):
	"""POST to a whitelisted method on another site and return its `message` dict."""
	base, key, secret = _conf()
	url = f"{base}/api/method/coupon_system.api.{method}"

	session = get_request_session()          # requests session with Frappe's retry policy
	try:
		resp = session.post(
			url,
			headers={"Authorization": f"token {key}:{secret}"},
			data=params,
			timeout=_TIMEOUT,                 # ALWAYS set a timeout
		)
		resp.raise_for_status()
	except Exception as e:
		frappe.throw(_("Could not reach HQ ({0}): {1}").format(method, e))

	try:
		return resp.json().get("message") or {}
	except ValueError:
		frappe.throw(_("HQ returned a non-JSON response (status {0})").format(resp.status_code))
```

The design decisions worth naming:

- **A transport failure raises; a business `{"success": False}` is returned.** They're different
  kinds of event and the caller must handle them differently — "the network broke" is retryable,
  "already redeemed" is not.
- **Always a timeout.** A hung upstream site must not hold a worker forever.
- **Credentials come from a DocType, not from code**, and secrets are `Password` fields read via
  `get_decrypted_password`.
- **The identity of a site is `get_url()`**, and it must match the registry row on the other side
  exactly — trailing slashes included. This repo has a rule about it in `CLAUDE.md` for good
  reason.
- **Guard against self-calls and recursion.** [`gateway.py`](../coupon_system/gateway.py) skips any
  store whose URL equals this site's own, adds a per-store circuit breaker, a fan-out cap, and a
  shorter timeout for balance reads than for scans. Fan-out to N sites on a user-facing request is
  where a system learns about tail latency.

Full design: [`docs/api-scan-gateway.md`](api-scan-gateway.md) and
[`docs/adr/0002-central-card-registry-thin-store-client.md`](adr/0002-central-card-registry-thin-store-client.md).

---

## 20. Command cheat sheet

```bash
# ── bench / site
bench init frappe-bench --frappe-branch version-16
bench new-site hq.localhost
bench --site hq.localhost set-config developer_mode 1
bench --site hq.localhost add-to-hosts
bench start
bench --site hq.localhost enable-scheduler

# ── apps
bench get-app apps/coupon_system            # local path, or a git URL
bench --site hq.localhost install-app coupon_system
bench --site hq.localhost uninstall-app coupon_system
bench --site hq.localhost list-apps

# ── the daily loop
bench --site hq.localhost migrate           # sync doctypes, run patches, after_migrate
bench build --app coupon_system             # rebuild JS/CSS
bench watch                                 # rebuild on change
bench --site hq.localhost clear-cache
bench restart                               # production / --noreload

# ── running code
bench --site hq.localhost console
bench --site hq.localhost execute coupon_system.api.generate_cards --kwargs "{'quantity': 10, 'campaign': 'Plumber 10'}"
bench --site hq.localhost run-tests --app coupon_system
bench --site hq.localhost mariadb

# ── data
bench --site hq.localhost export-fixtures --app coupon_system
bench --site hq.localhost backup --with-files
bench --site hq.localhost restore <path-to-sql.gz>
```

Python API you'll use every day:

```python
# read
frappe.get_doc(dt, name)                    # full document, with child tables
frappe.get_cached_doc(dt, name)             # …from cache
frappe.db.get_value(dt, name_or_filters, fieldname_or_list, as_dict=True)
frappe.db.get_single_value(dt, field)       # Single doctype
frappe.db.exists(dt, name_or_filters)
frappe.db.count(dt, filters)
frappe.get_all(dt, filters=…, fields=…, order_by=…, limit_page_length=0, pluck="code")

# write
doc = frappe.new_doc(dt); doc.x = 1; doc.insert(ignore_permissions=True)
doc.save() / doc.submit() / doc.cancel() / doc.delete()
doc.append("child_table", {...})
doc.db_set("field", value)                  # targeted write, skips the lifecycle
frappe.db.set_value(dt, name, fieldname, value)
frappe.db.bulk_insert(dt, fields=[...], values=[[...], ...])
frappe.rename_doc(dt, old, new)

# transactions
frappe.db.savepoint("x") / frappe.db.rollback(save_point="x")
frappe.db.commit()                          # console/scripts only, not request code
frappe.get_doc(dt, name, for_update=True)   # SELECT … FOR UPDATE

# context
frappe.session.user, frappe.get_roles(), frappe.only_for([...])
frappe.form_dict, frappe.request, frappe.local.site
frappe.utils.get_url(), frappe.conf.get("key")

# user feedback / errors
frappe.throw(_("...")), frappe.msgprint(_("..."), indicator="green", alert=True)
frappe.log_error(frappe.get_traceback(), "title")

# async
frappe.enqueue("coupon_system.api.slow_thing", queue="long", timeout=1500, **kwargs)
```

---

## 21. Demo run-sheet

A 90-minute version. Each block ends with something visibly working, so nobody has to take the
payoff on faith.

| # | Minutes | Block | Ends with |
|---|---|---|---|
| 1 | 0–10 | §1 mental model + tour of an existing DocType in the desk | Everyone knows what bench/site/app/DocType mean |
| 2 | 10–20 | §3 type the 7 skeleton files, `get-app`, `install-app` | `bench list-apps` shows your app |
| 3 | 20–35 | §4 hand-write `Coupon Campaign`, `migrate` | A working form, list and REST endpoint from one JSON |
| 4 | 35–45 | §5 the other four DocTypes (paste these; narrate the naming rules, `issingle`, `istable`, `is_virtual`) | Five tables |
| 5 | 45–60 | §6–7 `_post_ledger`, `_get_balance`, `scan` | Live in `bench console`: scan a card, watch the balance move |
| 6 | 60–70 | §8 API user + curl the same call | The same result over HTTP, from outside |
| 7 | 70–80 | §12 add the "Generate Cards" button | Generate 100 cards from the desk in front of them |
| 8 | 80–90 | §10 the Work Order hook, or §13 the QR page | A coupon minted by an unrelated ERPNext document |

**Set up before you start:** bench + a site with ERPNext, developer mode on, `bench start` already
running, an `Item` and a `Customer Group` existing, this repo open in a second window to jump to
the production versions.

**The three points worth landing**, if the demo runs long and you have to cut:

1. **Schema is the app.** One JSON file bought you a table, a form, a list, an API, permissions and
   an audit log. Time spent on DocType design is worth ten times the same time spent on code.
2. **Derive, don't store.** The ledger is the truth; the balance is a question. Every "our numbers
   don't match" bug is a stored aggregate that drifted from its transactions.
3. **Whitelisted is not authorised.** `@frappe.whitelist()` is a public door. The role check on the
   first line of the function is the lock, and it's yours to fit.

---

## Where to go next in this repo

Once the core makes sense, the production app extends it in three directions — each documented:

- **Store-locked points (buckets).** A store mints its own coupons whose points lock to that store,
  alongside the central spend-anywhere program. The account is the `(phone, bucket_store)` pair;
  a redemption drains the store bucket first so locked points never get stranded.
  → [`docs/adr/0003-ledger-scoping-and-immutable-def-replication.md`](adr/0003-ledger-scoping-and-immutable-def-replication.md),
  [`docs/store-coupons-build-spec.md`](store-coupons-build-spec.md)
- **The HQ scan gateway.** A code carries its store's namespace, so HQ can route a scan it can't
  resolve locally to the owning site and relay the answer — the mobile app makes exactly one call
  and never learns the other site exists.
  → [`docs/api-scan-gateway.md`](api-scan-gateway.md), [`coupon_system/gateway.py`](../coupon_system/gateway.py)
- **Running it.** Deployment model, the gateway service-account wiring, balance semantics, and the
  gotchas that cost hours on a live site.
  → [`docs/operations.md`](operations.md), [`docs/store-mode-setup.md`](store-mode-setup.md)

Official docs: <https://docs.frappe.io/framework>.

---

## 22. Coming from v15

This guide is v16 throughout. The app in this repo still runs on v15, so if you're reading its source
alongside, these are the places the two diverge — and the list you'd work through to move a real app
across. The framework's shape is unchanged: DocTypes, hooks, controllers, whitelisting, the query
builder and the desk API all behave as described here.

**Environment**

| | v15 | v16 |
|---|---|---|
| Python | 3.10+ | **3.14**, pinned `>=3.14,<3.15` |
| Node | 18+ | **24+** |
| PDF | wkhtmltopdf | Chrome/Chromium, selectable in Print Settings |
| Desk route | `/app` | `/desk` (`/app` redirects; `/apps` deprecated) |

**What this codebase would need**

- **§17 tests.** `coupon_system/tests/*` and the per-DocType `test_*.py` files import
  `FrappeTestCase` from `frappe.tests.utils`. On v16 that's `from frappe.tests import
  IntegrationTestCase` (everything here touches the database, so it's `IntegrationTestCase`, not
  `UnitTestCase`). Module-level `test_dependencies` → `EXTRA_TEST_RECORD_DEPENDENCIES`; any
  `setUpClass` override must call `super().setUpClass()`.
- **Implicit ordering.** v16 defaults `frappe.get_all`, `get_list`, `db.get_value`, `db.get_values`
  and `qb.get_query` to `creation desc` instead of `modified desc`. The ledger read in `balance()`
  already passes an explicit `.orderby(CL.timestamp, order=Order.desc)` — that's the pattern to
  copy. Audit every other list read for a silent dependency on `modified`.
- **DocType `sort_field`.** The JSONs here set `"sort_field": "modified"` explicitly, so their list
  views keep v15 behaviour on v16. That's a decision to make deliberately, not a default to inherit.
- **`has_permission` hooks must return `True` explicitly** — `None` no longer grants permission.
  This app doesn't use that hook, but anything you've bolted on beside it might.
- **`frappe.db.commit()` inside a document hook is unsupported.** `install.py::_create_mobile_user`
  commits, which is fine — it runs from an install hook, not a document hook — but audit the
  distinction rather than assuming.
- **`frappe.flags.in_test`** → `frappe.in_test`.
- **`frappe.sendmail(..., now=True)`** no longer commits.
- **`override_doctype` classes** must inherit from the class they override.
- **POST now required** for `logout`, `web_logout`, `upload_file`, `send_login_link`.

**Unaffected**

The gateway and store-mode machinery (§19) needs nothing: it's plain HTTP with token auth via
`get_request_session`, and none of that changed. The `Password` fieldtype and
`get_decrypted_password` are unchanged. `frappe.qb` is unchanged. The scan/redeem/ledger logic is
pure application code.

**Also moved out of core in v16:** Energy Points, Newsletter, Blog, Backup Integrations are separate
apps now. GeoIP and the Transaction Log DocType are gone. Modified *standard* workspaces get
overwritten on migrate — back them up first.

The official migration guide is the authority:
<https://github.com/frappe/frappe/wiki/Migrating-to-version-16>.
