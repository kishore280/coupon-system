# Your first Frappe app — a complete, simple walkthrough

Build a whole Frappe v16 app the way people actually build them: **let the tools generate the
boilerplate, then write the parts that carry real decisions.** The example is small enough to finish
in an hour — a **library**. Books, members, loans. That's it.

Two commands do the typing nobody should be doing by hand:

```bash
bench new-app library                   # the whole app skeleton, in one command
bench --site mysite.local new-doctype  # …or just draw the DocType in the browser
```

What's left after that is the actual work, and it's what this guide is about: **reading** the JSON
the tools generate until you know every key in it, then hand-writing the controllers, the API, the
hooks, the tasks and the tests — the code no generator can write for you.

The example is deliberately boring. The *coverage* is not — by the end you will have touched every
part of a Frappe app that a real one needs:

> schema · controllers · submittable documents · a REST API · hooks into other apps · a scheduler ·
> background jobs · email · custom fields on someone else's DocType · desk UI · a public website
> page · reports · dashboards · print formats · roles and permissions · fixtures · patches · tests ·
> install and uninstall

§22 is a checklist you can run against your own app to see what you're still missing.

> **Looking for the deep version?** [`frappe-app-from-scratch.md`](frappe-app-from-scratch.md) does
> the same tour against this repo's production coupon system — heavier example, more real-world
> edge cases, cross-linked to live source files. This guide is the one to teach from.

**Assumes:** you know Python, you've seen a Frappe or ERPNext screen once. Nothing else.
**Needs:** no ERPNext. Plain Frappe is enough.
**Version:** **Frappe v16** throughout — the current release, supported to 2029. Coming from a v15
app? [§24](#24-coming-from-v15) lists what changed.

---

## Table of contents

| # | Section | What it covers |
|---|---|---|
| 0 | [What we're building](#0-what-were-building) | The library, in five DocTypes |
| 1 | [The four words](#1-the-four-words-bench-site-app-doctype) | bench, site, app, DocType |
| 2 | [Getting a bench and a site](#2-getting-a-bench-and-a-site) | Install, developer mode |
| 3 | [Scaffold the app](#3-scaffold-the-app) | `bench new-app`, and what it wrote |
| 4 | [Your first DocType: Book](#4-your-first-doctype-book) | Generate it, then read the JSON |
| 5 | [Member, child table, Settings](#5-member-child-table-settings) | Naming, `istable`, `issingle` |
| 6 | [Loan: a submittable document](#6-loan-a-submittable-document) | `docstatus`, submit, cancel, amend |
| 7 | [Controllers and validation](#7-controllers-and-validation) | The lifecycle, in order |
| 8 | [The API layer](#8-the-api-layer) | `@frappe.whitelist`, roles, locking |
| 9 | [Calling your API](#9-calling-your-api) | API keys, curl, console |
| 10 | [Hooks and the scheduler](#10-hooks-and-the-scheduler) | `doc_events`, daily jobs |
| 11 | [Background jobs and email](#11-background-jobs-and-email) | `enqueue`, `sendmail` |
| 12 | [Custom fields on someone else's DocType](#12-custom-fields-on-someone-elses-doctype) | Install / uninstall |
| 13 | [Desk UI](#13-desk-ui) | Form JS, dialogs, list views |
| 14 | [A public website page](#14-a-public-website-page) | `www/`, routes, Jinja |
| 15 | [Reports and dashboards](#15-reports-and-dashboards) | Script report, chart, number card |
| 16 | [Print formats and PDF](#16-print-formats-and-pdf) | The due-date slip |
| 17 | [Roles, permissions, fixtures](#17-roles-permissions-fixtures) | Who can do what |
| 18 | [Patches](#18-patches) | Data migrations |
| 19 | [Tests](#19-tests) | `FrappeTestCase` |
| 20 | [Workflow](#20-workflow-when-you-need-approvals) | Approvals without code |
| 21 | [Dev workflow and gotchas](#21-dev-workflow-and-gotchas) | What wastes your afternoon |
| 22 | [The completeness checklist](#22-the-completeness-checklist) | **Does my app have everything?** |
| 23 | [Cheat sheet + run-sheet](#23-cheat-sheet-and-run-sheet) | Commands, and how to demo it |
| 24 | [Coming from v15](#24-coming-from-v15) | What changed, if you're porting |

---

## 0. What we're building

A library. Members borrow books. Books come back, sometimes late, and late costs money.

Five DocTypes, and that's the entire application:

```
Book             a title on a shelf: name, authors, ISBN, availability
Book Author      a child row on Book — one author, one role
Library Member   somebody with a card
Loan             one borrowing: member + book + due date        ← submittable
Library Settings a Single: loan period, fine per day, borrow limit
```

Three API endpoints: `issue_book`, `return_book`, `member_summary`.

That's small enough to build live in an hour. Everything else in this guide hangs off it.

---

## 1. The four words: bench, site, app, DocType

**Bench** — a directory holding one virtualenv, some apps, and some sites. Also the CLI (`bench …`).

**Site** — a database + a config file + a files folder, reachable at a hostname. Apps get installed
*into* a site. Two sites on one bench can have completely different apps.

**App** — an ordinary Python package with a handful of files Frappe knows to look for.

**DocType** — the unit of everything. One JSON file gives you all of this at once:

```
tabBook               a database table
/app/book             a desk form + list view, with filters and sorting
/api/resource/Book    a REST endpoint
class Book(Document)  a Python class with lifecycle hooks
                      permissions, naming, search indexes, an audit trail
```

That last point is the one to internalise early: **you don't write an app that has a database. You
write schema, and Frappe hands you the app.**

```
frappe-bench/
├── apps/
│   ├── frappe/          the framework
│   └── library/         ← what we write
├── sites/
│   ├── apps.txt
│   └── mysite.local/
│       └── site_config.json
└── env/                 the virtualenv
```

---

## 2. Getting a bench and a site

Skip if you have one. Otherwise (full docs:
<https://docs.frappe.io/framework/user/en/installation>):

```bash
# v16 needs: python 3.14 (pinned >=3.14,<3.15), node 24+, redis, mariadb 10.6+,
# and Chrome/Chromium for PDF generation
pip install frappe-bench

bench init frappe-bench --frappe-branch version-16
cd frappe-bench

bench new-site mysite.local
bench --site mysite.local add-to-hosts
```

Turn on developer mode **before** you touch a DocType:

```bash
bench --site mysite.local set-config developer_mode 1
bench --site mysite.local clear-cache
```

Developer mode is what makes schema edits in the browser get written back to JSON files in your
app — that is, into git. **Without it, a DocType you create in the UI exists only in that one
database and can never be deployed anywhere.** This is the single setting that turns the browser
into a code generator instead of a dead end. It also gives you real tracebacks.

```bash
bench start          # http://mysite.local:8000 — log in as Administrator
```

---

## 3. Scaffold the app

One command. It asks you a handful of questions (app title, publisher, email, licence) and writes
the whole skeleton:

```bash
cd ~/frappe-bench
bench new-app library
# App Title (default: Library): Library
# App Description: A small library: books, members, loans
# App Publisher: Your Name
# App Email: you@example.com
# App License (default: mit): mit
```

Then install it onto the site:

```bash
bench --site mysite.local install-app library
bench --site mysite.local list-apps
# frappe
# library
```

Done — a working, empty Frappe app. **The rest of this section is about reading what it just
wrote**, because you'll be editing four of these files constantly and the layout confuses everyone
exactly once.

### 3.1 What it generated

`bench new-app` writes about thirty files. Most are optional scaffolding (CI config, linter config,
a JS build entry point). These are the ones that matter — note the **doubled `library`**:

```
library/                    ← repo root
├── pyproject.toml
├── license.txt
├── README.md
└── library/                ← the Python package
    ├── __init__.py         ← must define __version__
    ├── hooks.py            ← the app's contract with the framework
    ├── modules.txt         ← module names this app ships
    ├── patches.txt         ← data migrations
    └── library/            ← the MODULE directory
        ├── __init__.py
        └── doctype/
            └── __init__.py
```

Two levels because **app** and **module** are different things. The app is the package; a module
groups DocTypes *inside* it. (ERPNext ships "Accounts", "Stock", "Manufacturing" — all one app.)
Our app ships one module, named after itself.

Four of those files you will touch constantly, so it's worth knowing what each one is actually for.

### 3.2 `pyproject.toml`

```toml
[project]
name = "library"
authors = [{ name = "Your Name", email = "you@example.com" }]
description = "A small library: books, members, loans"
requires-python = ">=3.10"
readme = "README.md"
dynamic = ["version"]
dependencies = []
# NEVER list frappe here — bench installs and manages it

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

Two things here you'd get wrong if you wrote it yourself:

- **`frappe` is not in `dependencies`.** Bench installs and manages it; pinning it here fights the
  bench. Your app's real dependencies (`qrcode`, `requests`, whatever) do go here.
- **`dynamic = ["version"]`** means flit reads `__version__` from `library/__init__.py`. That file
  contains exactly one line — `__version__ = "0.0.1"` — and Frappe, flit and the Apps screen all
  read it. Bump it when you release.

And tabs, not spaces: that's the ecosystem convention, and what the generated `ruff` config enforces.

### 3.3 `library/hooks.py` — the one you'll live in

This file *is* the contract between your app and the framework. Frappe imports it and looks for
specific module-level names. Nothing registers dynamically — **if it isn't in `hooks.py`, it doesn't
happen.**

`bench new-app` writes it pre-filled with the app metadata and then about 200 lines of *commented-out
examples* — every extension point the framework offers, with its expected shape:

```python
app_name = "library"
app_title = "Library"
app_publisher = "Your Name"
app_description = "A small library: books, members, loans"
app_email = "you@example.com"
app_license = "mit"

# ------------------------------------------------------------------
# everything below here arrives commented out. Uncomment what you need.
# ------------------------------------------------------------------

# app_include_css = "/assets/library/css/library.css"
# app_include_js = "/assets/library/js/library.js"

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# scheduler_events = {
# 	"daily": [
# 		"library.tasks.daily"
# 	],
# }
```

**Read that file top to bottom once.** It's a free catalogue of everything a Frappe app can hook
into, and half of this guide is just uncommenting the right lines. Leave the comments in place —
they're the documentation you'll come back to.

### 3.4 `library/modules.txt`

```
Library
```

One module name per line, **Title Case** — generated from the app title. This creates the
`Module Def` record on install, and it's how a DocType's `"module": "Library"` resolves back to your
app. The directory is the snake_case of it: `library/library/`.

Add a line here if you want a second module, and create the matching directory (with an
`__init__.py`) yourself.

### 3.5 `library/patches.txt`

```
[pre_model_sync]
# Patches added in this section will be executed before doctypes are migrated

[post_model_sync]
# Patches added in this section will be executed after doctypes are migrated
```

Generated empty. §18 fills it in.

### 3.6 The `__init__.py` files

Frappe walks your app with `importlib`, so every package level needs one. `bench new-app` creates
them — but *you* create the next ones, and a missing `__init__.py` is the most common day-one bug by
a wide margin. It produces a `ModuleNotFoundError` on migrate that reads like a framework problem
and isn't.

You'll need to remember this when you hand-create a directory: a new module, `patches/v1_0/`, a
`report/` folder. The DocType generator (§4) handles its own.

### 3.7 What to delete

Scaffolding you're not using is noise in code review. If you're not writing front-end assets, the
`public/` build entry and `.eslintrc` can go. If you're not using GitHub Actions, drop `.github/`.
Keep `pyproject.toml`, `hooks.py`, `modules.txt`, `patches.txt`, `license.txt`, and the
`__init__.py` files — those seven are the app.

### 3.8 What to generate, what to write

The dividing line, and the stance of this whole guide: **generate anything mechanical, write
anything that encodes a decision.**

| Generate it | Write it by hand |
|---|---|
| The app skeleton (`bench new-app`) | `hooks.py` entries — every one is a decision |
| DocType JSON (draw it in the UI) | Controllers: `validate`, `before_submit`, `on_cancel` |
| Child tables, Single settings | `api.py` — role checks, locking, idempotency |
| Report and Web Form scaffolds | Scheduler tasks and background jobs |
| Workspaces, dashboard charts, notifications | `install.py` / `uninstall.py` |
| Print format layouts (or the builder) | Patches |
| — | Tests |

Two consequences worth stating plainly:

- **Every generated file still has to be read.** A DocType JSON you've never opened is a schema you
  don't know — and it's the file that shows up in your code review, not the form you clicked.
- **Nothing generates the interesting half.** No wizard writes "a book can't be issued twice",
  "cancel must reverse submit", or "check the role before you trust the caller". That's the app.

---

## 4. Your first DocType: Book

**Don't type this one either.** With developer mode on, you draw a DocType in the browser and Frappe
writes the JSON into your app, ready to commit:

> `/app/doctype/new` → Name: `Book`, Module: `Library`, add fields, **Save**

That writes `apps/library/library/library/doctype/book/book.json` plus a stub `book.py` and an
`__init__.py`. Same result from the CLI if you prefer:

```bash
bench --site mysite.local new-doctype "Book" --module Library
```

So why does the rest of this section walk through the JSON key by key? Because **the file is the
source of truth, not the form.** You'll be reading it in code review, editing it in a merge
conflict, and reaching for properties the form makes hard to find. And a handful of things — bulk
reordering fields, `depends_on` expressions, permission rows — are genuinely faster to type than to
click.

The workflow that works: **draw the rough shape in the UI, then open the JSON and finish it.**

A DocType is a directory of up to four files:

```
library/library/doctype/book/
├── __init__.py     (empty)
├── book.json       the schema            ← required
├── book.py         the controller        ← required (may be nearly empty)
└── book.js         desk form behaviour   ← optional
```

Directory and file names are the **snake_case of the DocType name**. `Library Member` →
`library_member/library_member.py`. Get it wrong and Frappe won't find your controller — quietly,
in some code paths.

### 4.1 `book.json` — the file the form wrote

Here's the finished article. Draw roughly this in the UI, then open the file and reconcile it
against what follows.

```json
{
 "actions": [],
 "allow_rename": 1,
 "autoname": "naming_series:",
 "creation": "2026-01-01 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "naming_series",
  "title",
  "isbn",
  "status",
  "column_break_1",
  "shelf",
  "published_on",
  "is_reference_only",
  "section_break_authors",
  "authors",
  "section_break_notes",
  "summary"
 ],
 "fields": [
  {
   "fieldname": "naming_series",
   "fieldtype": "Select",
   "label": "Series",
   "options": "BK-.#####",
   "reqd": 1,
   "set_only_once": 1,
   "no_copy": 1,
   "print_hide": 1
  },
  {
   "fieldname": "title",
   "fieldtype": "Data",
   "label": "Title",
   "reqd": 1,
   "in_list_view": 1,
   "in_standard_filter": 1
  },
  {
   "fieldname": "isbn",
   "fieldtype": "Data",
   "label": "ISBN",
   "unique": 1,
   "in_list_view": 1,
   "description": "13 digits, no dashes. Unique across the library."
  },
  {
   "default": "Available",
   "fieldname": "status",
   "fieldtype": "Select",
   "label": "Status",
   "options": "Available\nOn Loan\nLost\nWithdrawn",
   "in_list_view": 1,
   "in_standard_filter": 1,
   "search_index": 1,
   "description": "Maintained by the Loan flow — don't edit it by hand."
  },
  {
   "fieldname": "column_break_1",
   "fieldtype": "Column Break"
  },
  {
   "fieldname": "shelf",
   "fieldtype": "Data",
   "label": "Shelf",
   "description": "Where it physically lives, e.g. A-14"
  },
  {
   "fieldname": "published_on",
   "fieldtype": "Date",
   "label": "Published On"
  },
  {
   "default": "0",
   "fieldname": "is_reference_only",
   "fieldtype": "Check",
   "label": "Reference Only",
   "description": "Reference books can be read in the library but never issued."
  },
  {
   "fieldname": "section_break_authors",
   "fieldtype": "Section Break",
   "label": "Authors"
  },
  {
   "fieldname": "authors",
   "fieldtype": "Table",
   "label": "Authors",
   "options": "Book Author"
  },
  {
   "fieldname": "section_break_notes",
   "fieldtype": "Section Break"
  },
  {
   "fieldname": "summary",
   "fieldtype": "Small Text",
   "label": "Summary"
  }
 ],
 "links": [
  {
   "link_doctype": "Loan",
   "link_fieldname": "book"
  }
 ],
 "modified": "2026-01-01 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Library",
 "name": "Book",
 "naming_rule": "By \"Naming Series\" field",
 "owner": "Administrator",
 "permissions": [
  {
   "role": "System Manager",
   "create": 1, "read": 1, "write": 1, "delete": 1,
   "email": 1, "export": 1, "print": 1, "report": 1, "share": 1
  }
 ],
 "search_fields": "title,isbn",
 "sort_field": "creation",
 "sort_order": "DESC",
 "title_field": "title",
 "track_changes": 1
}
```

Read it as five groups.

**Identity.** `"doctype": "DocType"` — this JSON is itself a document, of type DocType. Frappe is
self-describing all the way down. `"module"` must match `modules.txt`.

**`field_order` + `fields`.** `fields` defines them; `field_order` lays them out. Layout elements
(`Section Break`, `Column Break`, `Tab Break`) are real entries in *both* lists — that's how you
build a form without writing any HTML. Keep the two in sync or the form silently drops a field.

**Field anatomy.** The keys you'll use constantly:

| Key | Effect |
|---|---|
| `fieldname` | the DB column. snake_case, and stable forever — renaming later needs a patch |
| `fieldtype` | `Data`, `Int`, `Float`, `Currency`, `Check`, `Select`, `Date`, `Datetime`, `Link`, `Table`, `Table MultiSelect`, `Small Text`, `Text Editor`, `Password`, `Attach`, `HTML`, … |
| `options` | `Link` → target DocType; `Select` → newline-separated values; `Table` → child DocType |
| `reqd` | required |
| `unique` | unique index — the only duplicate check that can't race |
| `default` | always a string, even for numbers (`"0"`, `"14"`) |
| `in_list_view` | show as a column in the list view |
| `in_standard_filter` | show as a filter dropdown above the list |
| `search_index` | index it. Add to anything you filter on once the table gets big |
| `read_only` / `hidden` | display control |
| `depends_on` | show conditionally: `"eval:doc.status=='Lost'"` |
| `set_only_once` | writable on create, frozen after |
| `description` | the grey helper text under the field. **Use it** — cheapest documentation you'll ever write, and it appears exactly where someone is confused |

**Naming.** `autoname` + `naming_rule` decide the primary key (`name`). Full table in §5.1.

**Permissions.** A list of role rows. No row for a role = that role sees nothing at all. `System
Manager` is not automatic — leave `permissions` empty and only Administrator gets in.

Three extras worth knowing: `title_field` makes the list show the title instead of `BK-00001`;
`search_fields` decides what the awesomebar and Link dropdowns match on; `links` renders a
"Connections" tab (here, every Loan of this book); `track_changes: 1` records every field edit in
the Version doctype — a free audit trail.

### 4.2 `book.py`

```python
import frappe
from frappe import _
from frappe.model.document import Document


class Book(Document):
	def validate(self):
		if self.isbn:
			self.isbn = self.isbn.replace("-", "").strip()
			if not self.isbn.isdigit() or len(self.isbn) != 13:
				frappe.throw(_("ISBN must be 13 digits"))
```

Class name = **PascalCase of the DocType name, spaces removed**. `Library Member` →
`LibraryMember`. Frappe resolves it by convention, so a typo means your controller is simply never
called.

`validate()` runs on every insert and every save. `frappe.throw()` aborts the transaction and shows
the message. Wrap user-facing strings in `_()` so they can be translated.

### 4.3 Sync it

Saving in the UI already synced the database. If you edited the JSON by hand, or pulled someone
else's changes, run:

```bash
bench --site mysite.local migrate
```

`migrate` reads every DocType JSON in every installed app and reconciles the database to it —
creating tables, adding columns, adding indexes, running patches. It's idempotent, and it is how
*all* schema change happens in Frappe. There are no Alembic-style migration files for schema: the
JSON **is** the migration.

**The loop, in practice:** edit in the UI → the JSON changes on disk → `git diff` to see exactly
what you did → commit. Or edit the JSON → `migrate` → refresh. Both directions work, and the file
is the truth either way. That is why reading it matters.

Open <http://mysite.local:8000/app/book/new>. You have a form with validation, a list view
with filters, a REST endpoint, permissions and an audit trail — from one JSON file and six lines of
Python.

> **Demo tip:** stop here for a second. Add a book, then open
> `/api/resource/Book` in another tab. Nothing else in this guide lands as hard.

---

## 5. Member, child table, Settings

### 5.1 Naming rules

Every DocType needs a primary key strategy:

| `autoname` | `naming_rule` | Result |
|---|---|---|
| `naming_series:` | `By "Naming Series" field` | user picks a series from a `naming_series` field |
| `BK-.#####` | `Expression (old style)` | `BK-00001`, auto-incrementing |
| `LN-.YYYY.-.#####` | `Expression (old style)` | `LN-2026-00001`, resets per year |
| `field:email` | `By fieldname` | `name` = the email. Natural keys |
| `format:{title}-{###}` | `Expression` | a template over field values |
| `hash` | `Random` | a random hash |
| `Prompt` | `Set by user` | the user types it |

Rule of thumb: if a natural, stable, unique identity exists (an email, a phone number), name by it —
you save yourself a join forever. Otherwise use a series.

### 5.2 `library_member/library_member.json`

```json
{
 "actions": [],
 "autoname": "field:email",
 "creation": "2026-01-01 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "field_order": [
  "full_name",
  "email",
  "phone",
  "column_break_1",
  "joined_on",
  "membership_expiry",
  "is_active",
  "section_break_stats",
  "books_on_loan",
  "outstanding_fine"
 ],
 "fields": [
  {"fieldname": "full_name", "fieldtype": "Data", "label": "Full Name", "reqd": 1, "in_list_view": 1},
  {"fieldname": "email", "fieldtype": "Data", "label": "Email", "options": "Email", "reqd": 1, "unique": 1, "in_list_view": 1},
  {"fieldname": "phone", "fieldtype": "Data", "label": "Phone", "options": "Phone"},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "joined_on", "fieldtype": "Date", "label": "Joined On"},
  {"fieldname": "membership_expiry", "fieldtype": "Date", "label": "Membership Expiry", "in_list_view": 1},
  {"default": "1", "fieldname": "is_active", "fieldtype": "Check", "label": "Is Active", "in_list_view": 1},
  {"fieldname": "section_break_stats", "fieldtype": "Section Break", "label": "Right now"},
  {
   "fieldname": "books_on_loan",
   "fieldtype": "Int",
   "is_virtual": 1,
   "label": "Books On Loan",
   "read_only": 1
  },
  {
   "fieldname": "outstanding_fine",
   "fieldtype": "Currency",
   "is_virtual": 1,
   "label": "Outstanding Fine",
   "read_only": 1
  }
 ],
 "links": [
  {"link_doctype": "Loan", "link_fieldname": "member"}
 ],
 "modified": "2026-01-01 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Library",
 "name": "Library Member",
 "naming_rule": "By fieldname",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "create": 1, "read": 1, "write": 1, "delete": 1, "email": 1, "export": 1, "print": 1, "report": 1, "share": 1}
 ],
 "search_fields": "full_name,phone",
 "sort_field": "creation",
 "sort_order": "DESC",
 "title_field": "full_name",
 "track_changes": 1
}
```

Two things to point out:

**`"options": "Email"` on a `Data` field** gives you format validation and a `mailto:` link for
free. `Phone`, `URL` and `Name` work the same way. People miss this and hand-write validators.

**`is_virtual: 1` creates no column.** The value is computed when the form loads:

```python
import frappe
from frappe.model.document import Document


class LibraryMember(Document):
	def onload(self):
		self.set_onload("books_on_loan", frappe.db.count(
			"Loan", {"member": self.name, "docstatus": 1, "status": ["!=", "Returned"]}
		))
		# Aggregates go through the dict form, not a "sum(...)" string — see the note below.
		fine_row = frappe.db.get_all(
			"Loan",
			filters={"member": self.name, "docstatus": 1, "fine_paid": 0},
			fields=[{"SUM": "fine_amount", "as": "total"}],
		)
		# SUM over zero rows still returns one row, with total = None — hence the `or 0`.
		self.set_onload("outstanding_fine", (fine_row[0].total if fine_row else 0) or 0)
```

> **Aggregates are dict syntax now.** `frappe.get_all` / `frappe.db.get_all` run on the query-builder
> backend, and a raw SQL function passed as a string is rejected:
>
> ```
> SQL functions are not allowed as strings in SELECT: sum(fine_amount).
> Use dict syntax like {'COUNT': '*'}
> ```
>
> So `fields=["sum(fine_amount)"]` becomes `fields=[{"SUM": "fine_amount", "as": "total"}]`, and you
> read the aliased column off the row. Same for `COUNT`, `AVG`, `MIN`, `MAX`. Two things that catch
> people: the result is a **list of rows**, not a scalar — and `SUM` over zero matching rows returns
> one row whose value is `None`, not `0`. `frappe.db.count()` is unaffected; it's a dedicated API,
> not a field expression.

This is a habit worth forming early: **derive, don't store.** A counter you keep in a column will
eventually disagree with the rows it's meant to summarise. A `COUNT(*)` never does. Store a
computed value only when you've measured that computing it is too slow — and then treat it as a
cache you can rebuild.

### 5.3 A child table: `book_author/book_author.json`

`"istable": 1` means rows can't exist on their own — they always belong to a parent. Frappe adds
`parent`, `parenttype`, `parentfield` and `idx` columns for you.

```json
{
 "actions": [],
 "creation": "2026-01-01 00:00:00.000000",
 "doctype": "DocType",
 "editable_grid": 1,
 "engine": "InnoDB",
 "istable": 1,
 "field_order": ["author_name", "role"],
 "fields": [
  {"fieldname": "author_name", "fieldtype": "Data", "label": "Author", "reqd": 1, "in_list_view": 1},
  {"default": "Author", "fieldname": "role", "fieldtype": "Select", "label": "Role",
   "options": "Author\nCo-author\nEditor\nTranslator\nIllustrator", "in_list_view": 1}
 ],
 "modified": "2026-01-01 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Library",
 "name": "Book Author",
 "owner": "Administrator",
 "permissions": [],
 "sort_field": "creation",
 "sort_order": "DESC"
}
```

`"permissions": []` is correct — a child table inherits its parent's permissions, and giving it its
own does nothing.

Using it from Python:

```python
book = frappe.get_doc("Book", "BK-00001")
book.append("authors", {"author_name": "Ursula K. Le Guin", "role": "Author"})
book.save()

for row in book.authors:
	print(row.idx, row.author_name, row.role)

# read rows without loading the parent:
names = frappe.get_all("Book Author", filters={"parent": "BK-00001"}, pluck="author_name")
```

> **`Table` vs `Table MultiSelect`.** Same child DocType mechanism, different UI. `Table` gives a
> full editable grid — use it when rows carry several fields, as here. `Table MultiSelect` renders
> as chips and only works when the child has essentially one `Link` field — good for tagging
> (`"options": "Book Genre"` where `Book Genre` is a child with a single `Link` to `Genre`).

### 5.4 A Single: `library_settings/library_settings.json`

`"issingle": 1` means exactly one of these exists, forever. No list view, no `name`, no table — the
values live in `tabSingles` as key/value pairs. Every app ships one.

```json
{
 "actions": [],
 "creation": "2026-01-01 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "issingle": 1,
 "field_order": [
  "loan_period_days",
  "max_books_per_member",
  "column_break_1",
  "fine_per_day",
  "currency",
  "section_break_web",
  "enable_public_catalogue",
  "library_name"
 ],
 "fields": [
  {"default": "14", "fieldname": "loan_period_days", "fieldtype": "Int", "label": "Loan Period (Days)", "reqd": 1},
  {"default": "5", "fieldname": "max_books_per_member", "fieldtype": "Int", "label": "Max Books Per Member", "reqd": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"default": "2", "fieldname": "fine_per_day", "fieldtype": "Currency", "label": "Fine Per Day",
   "description": "Snapshotted onto each Loan when it's issued — changing it never revalues an existing loan."},
  {"default": "USD", "fieldname": "currency", "fieldtype": "Link", "label": "Currency", "options": "Currency"},
  {"fieldname": "section_break_web", "fieldtype": "Section Break", "label": "Public catalogue"},
  {"default": "1", "fieldname": "enable_public_catalogue", "fieldtype": "Check", "label": "Enable Public Catalogue",
   "description": "Master switch for the /catalogue page. Off = 404 for the public."},
  {"default": "The Library", "fieldname": "library_name", "fieldtype": "Data", "label": "Library Name"}
 ],
 "modified": "2026-01-01 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Library",
 "name": "Library Settings",
 "owner": "Administrator",
 "permissions": [
  {"role": "System Manager", "create": 1, "read": 1, "write": 1, "delete": 0}
 ],
 "sort_field": "creation",
 "sort_order": "DESC",
 "track_changes": 1
}
```

Reading one is a cached one-liner:

```python
period = frappe.db.get_single_value("Library Settings", "loan_period_days")
```

Note `"delete": 0` even for System Manager. You can't meaningfully delete a Single, so don't offer
the button.

---

## 6. Loan: a submittable document

This is the piece the library actually runs on, and it's where Frappe's most distinctive idea shows
up.

Add `"is_submittable": 1` to a DocType and every document gets a `docstatus`:

| `docstatus` | State | Means |
|---|---|---|
| `0` | Draft | freely editable, doesn't count for anything |
| `1` | Submitted | **immutable**, and it's now real |
| `2` | Cancelled | reversed, kept forever for the audit trail |

The desk grows Submit and Cancel buttons automatically. Submitted documents can't be edited — except
fields you explicitly mark `allow_on_submit: 1` — and can't be deleted. Cancelling never removes a
row; it flips it to `2`. To "fix" a cancelled document you **amend** it, which copies it to a new
draft carrying `amended_from`.

Every ERPNext transaction — invoice, stock entry, payment — works exactly this way. Reach for it any
time a record represents *something that happened*, and rebuild it out of a `Select` field never.

### 6.1 `loan/loan.json`

```json
{
 "actions": [],
 "autoname": "LN-.YYYY.-.#####",
 "creation": "2026-01-01 00:00:00.000000",
 "doctype": "DocType",
 "engine": "InnoDB",
 "is_submittable": 1,
 "field_order": [
  "member",
  "book",
  "status",
  "column_break_1",
  "issue_date",
  "due_date",
  "return_date",
  "section_break_fine",
  "fine_per_day",
  "fine_amount",
  "column_break_2",
  "fine_paid",
  "amended_from"
 ],
 "fields": [
  {"fieldname": "member", "fieldtype": "Link", "label": "Member", "options": "Library Member",
   "reqd": 1, "in_list_view": 1, "search_index": 1},
  {"fieldname": "book", "fieldtype": "Link", "label": "Book", "options": "Book",
   "reqd": 1, "in_list_view": 1, "search_index": 1},
  {"default": "Issued", "fieldname": "status", "fieldtype": "Select", "label": "Status",
   "options": "Issued\nReturned\nOverdue\nLost",
   "in_list_view": 1, "in_standard_filter": 1, "search_index": 1,
   "allow_on_submit": 1, "read_only": 1},
  {"fieldname": "column_break_1", "fieldtype": "Column Break"},
  {"fieldname": "issue_date", "fieldtype": "Date", "label": "Issue Date", "reqd": 1, "in_list_view": 1},
  {"fieldname": "due_date", "fieldtype": "Date", "label": "Due Date", "reqd": 1, "in_list_view": 1, "search_index": 1},
  {"fieldname": "return_date", "fieldtype": "Date", "label": "Return Date",
   "allow_on_submit": 1, "read_only": 1},
  {"fieldname": "section_break_fine", "fieldtype": "Section Break", "label": "Fine"},
  {"fieldname": "fine_per_day", "fieldtype": "Currency", "label": "Fine Per Day (snapshot)", "read_only": 1,
   "description": "Copied from Library Settings when the loan was issued."},
  {"fieldname": "fine_amount", "fieldtype": "Currency", "label": "Fine Amount", "read_only": 1,
   "allow_on_submit": 1},
  {"fieldname": "column_break_2", "fieldtype": "Column Break"},
  {"default": "0", "fieldname": "fine_paid", "fieldtype": "Check", "label": "Fine Paid", "allow_on_submit": 1},
  {"fieldname": "amended_from", "fieldtype": "Link", "label": "Amended From", "options": "Loan",
   "no_copy": 1, "print_hide": 1, "read_only": 1}
 ],
 "links": [],
 "modified": "2026-01-01 00:00:00.000000",
 "modified_by": "Administrator",
 "module": "Library",
 "name": "Loan",
 "naming_rule": "Expression (old style)",
 "owner": "Administrator",
 "permissions": [
  {
   "role": "System Manager",
   "create": 1, "read": 1, "write": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
   "email": 1, "export": 1, "print": 1, "report": 1, "share": 1
  }
 ],
 "sort_field": "creation",
 "sort_order": "DESC",
 "track_changes": 1
}
```

Three requirements that are easy to miss and annoying to debug:

1. **`amended_from`** — a submittable DocType must have this exact field, `Link` to itself,
   `no_copy` and `read_only`. Amend breaks without it.
2. **`allow_on_submit: 1`** on everything that legitimately changes *after* submission — here
   `status`, `return_date`, `fine_amount`, `fine_paid`. A return would otherwise be impossible.
3. **`submit` / `cancel` / `amend`** in the permission rows. Without them the buttons never appear,
   even for System Manager.

### 6.2 `loan/loan.py`

```python
import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, date_diff, flt, getdate, today


class Loan(Document):
	def validate(self):
		settings = frappe.get_cached_doc("Library Settings")

		if not self.issue_date:
			self.issue_date = today()
		if not self.due_date:
			self.due_date = add_days(self.issue_date, settings.loan_period_days or 14)
		if getdate(self.due_date) < getdate(self.issue_date):
			frappe.throw(_("Due date can't be before the issue date"))

		# Snapshot the rate. Changing the setting later must never revalue an
		# existing loan — the borrower agreed to today's terms.
		if not self.fine_per_day:
			self.fine_per_day = flt(settings.fine_per_day)

	def before_submit(self):
		"""Everything that must be TRUE before this loan becomes real."""
		book = frappe.get_doc("Book", self.book)

		if book.is_reference_only:
			frappe.throw(_("{0} is reference only and can't be issued").format(book.title))
		if book.status != "Available":
			frappe.throw(_("{0} is currently {1}").format(book.title, book.status))

		member = frappe.get_doc("Library Member", self.member)
		if not member.is_active:
			frappe.throw(_("{0}'s membership is not active").format(member.full_name))
		if member.membership_expiry and getdate(member.membership_expiry) < getdate(today()):
			frappe.throw(_("{0}'s membership expired on {1}").format(
				member.full_name, member.membership_expiry))

		settings = frappe.get_cached_doc("Library Settings")
		open_loans = frappe.db.count("Loan", {
			"member": self.member, "docstatus": 1, "status": ["!=", "Returned"],
		})
		if open_loans >= (settings.max_books_per_member or 5):
			frappe.throw(_("{0} already has {1} books out — the limit is {2}").format(
				member.full_name, open_loans, settings.max_books_per_member))

	def on_submit(self):
		"""The loan is now real: the book leaves the shelf."""
		self.db_set("status", "Issued")
		frappe.db.set_value("Book", self.book, "status", "On Loan")

	def on_cancel(self):
		"""Cancelling a loan un-issues the book. Reverse every effect of on_submit."""
		if self.status != "Returned":
			frappe.db.set_value("Book", self.book, "status", "Available")
		self.db_set("status", "Issued")     # leave a clean state on the cancelled doc

	def mark_returned(self, return_date=None):
		"""Called by the API and by the desk button. Not a lifecycle hook — a method
		on the document, which is where behaviour belongs."""
		if self.docstatus != 1:
			frappe.throw(_("Only a submitted loan can be returned"))
		if self.status == "Returned":
			frappe.throw(_("This loan is already returned"))

		return_date = getdate(return_date or today())
		days_late = date_diff(return_date, getdate(self.due_date))
		fine = flt(self.fine_per_day) * days_late if days_late > 0 else 0

		self.db_set({
			"status": "Returned",
			"return_date": return_date,
			"fine_amount": fine,
		})
		frappe.db.set_value("Book", self.book, "status", "Available")
		return fine
```

Four patterns worth naming out loud:

**`before_submit` is your gate.** Everything that must be true for this thing to *become real* goes
there — availability, membership, borrowing limits. `validate` runs on every save including drafts;
`before_submit` runs once, at the moment of commitment.

**`on_cancel` mirrors `on_submit`, exactly.** Every effect the submit had, the cancel undoes. If you
can't write the mirror, your submit is doing too much.

**`db_set` inside a lifecycle hook, never `save()`.** `self.save()` inside `validate` or `on_update`
is infinite recursion. `db_set` writes the field directly and skips the lifecycle. It also works on
a submitted document, which `save()` won't.

**Behaviour lives on the document.** `mark_returned()` is a method on `Loan`, so the API endpoint,
the desk button and a future import script all share one implementation. Endpoints should be thin.

Run `bench --site mysite.local migrate` and all five tables exist.

---

## 7. Controllers and validation

Frappe calls these on your class, in this order:

| Method | When | Use it for |
|---|---|---|
| `before_insert` | new doc, before the first write | defaults, structural guards |
| `validate` | every insert **and** every save | validation, computed fields |
| `before_save` | after validate | last-moment adjustments |
| `after_insert` | row exists | side effects that are creation-only |
| `on_update` | after any save | side effects, syncing |
| `before_submit` / `on_submit` | `docstatus` 0 → 1 | the commitment gate, and its effects |
| `before_cancel` / `on_cancel` | `docstatus` 1 → 2 | reversal |
| `on_update_after_submit` | a save that only touched `allow_on_submit` fields | post-submit edits |
| `on_trash` / `after_delete` | delete | cleanup, blocking deletes |
| `onload` | doc loaded into a form | virtual / derived display values |

Five rules that save real debugging time:

- **`validate` runs on every save.** Guard create-only logic with `if self.is_new():`.
- **Never `self.save()` in a hook.** Use `self.db_set(...)`.
- **To detect a change, compare against the database**, not against `self` — `self` is already
  mutated:
  ```python
  previous = frappe.db.get_value(self.doctype, self.name, "status")
  if self.status != previous:
      ...
  ```
  (`self.get_doc_before_save()` gives you the whole previous document, when you need more than one
  field.)
- **`get_cached_doc` for settings and other rarely-changing records**, `get_doc` for anything you're
  about to write.
- **Block a delete in `on_trash`**, not with permissions:
  ```python
  def on_trash(self):
      if frappe.db.exists("Loan", {"book": self.name, "docstatus": 1}):
          frappe.throw(_("This book has loan history and can't be deleted. Set it to Withdrawn."))
  ```

---

## 8. The API layer

A whitelisted function is callable over HTTP:

```
POST /api/method/library.api.issue_book
```

The dotted path *is* the module path. There's no router and no URL config — put the decorator on
the function and it's an endpoint. Which is exactly why the rules below matter: **whitelisting is
the security boundary of your app.**

Create `library/api.py`:

```python
import frappe
from frappe import _
from frappe.utils import add_days, cint, flt, today


@frappe.whitelist()
def issue_book(member, book, due_date=None):
	"""Issue a book to a member. Returns the new loan, or a clean error."""
	try:
		# 1. AUTHORISE. Whitelisted means "reachable", never "allowed".
		if not ({"System Manager", "Librarian"} & set(frappe.get_roles())):
			frappe.throw(_("Not permitted"))

		# 2. VALIDATE INPUT. Every argument arrives from HTTP as a string.
		if not frappe.db.exists("Library Member", member):
			frappe.throw(_("Unknown member"))
		if not frappe.db.exists("Book", book):
			frappe.throw(_("Unknown book"))

		# 3. LOCK THE ROW before reading availability, so two librarians at two
		#    desks can't both issue the same copy in the same second.
		frappe.db.sql("SELECT name FROM `tabBook` WHERE name = %s FOR UPDATE", book)

		loan = frappe.new_doc("Loan")
		loan.member = member
		loan.book = book
		loan.issue_date = today()
		if due_date:
			loan.due_date = due_date
		loan.insert()
		loan.submit()          # before_submit does the real checking

		return {
			"success": True,
			"loan": loan.name,
			"due_date": str(loan.due_date),
		}
	except frappe.ValidationError as e:
		# 4. A STABLE SHAPE the caller can rely on — not an HTML traceback.
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def return_book(loan=None, book=None, return_date=None):
	"""Return a book, by loan name or by book. Idempotent: returning twice is
	reported, not double-charged."""
	try:
		if not ({"System Manager", "Librarian"} & set(frappe.get_roles())):
			frappe.throw(_("Not permitted"))

		if not loan:
			if not book:
				frappe.throw(_("Pass either a loan or a book"))
			loan = frappe.db.get_value(
				"Loan", {"book": book, "docstatus": 1, "status": ["!=", "Returned"]}, "name"
			)
			if not loan:
				return {"success": False, "reason": "not_on_loan",
						"error": _("That book isn't currently on loan")}

		doc = frappe.get_doc("Loan", loan, for_update=True)
		if doc.status == "Returned":
			# Stable machine-readable reason, so a retrying client can tell
			# "already done" from "failed" without matching translated prose.
			return {"success": False, "reason": "already_returned",
					"error": _("That loan is already closed")}

		fine = doc.mark_returned(return_date)

		return {
			"success": True,
			"loan": doc.name,
			"returned_on": str(doc.return_date),
			"fine": flt(fine),
			"was_late": fine > 0,
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def member_summary(member):
	"""What a member currently has out, and what they owe."""
	try:
		if not ({"System Manager", "Librarian"} & set(frappe.get_roles())):
			frappe.throw(_("Not permitted"))
		if not frappe.db.exists("Library Member", member):
			frappe.throw(_("Unknown member"))

		loans = frappe.get_all(
			"Loan",
			filters={"member": member, "docstatus": 1, "status": ["!=", "Returned"]},
			fields=["name", "book", "issue_date", "due_date", "status"],
			order_by="due_date asc",
			limit_page_length=50,        # always bound a list a client will render
		)
		# One query for the titles, instead of one per loan.
		titles = dict(frappe.get_all(
			"Book", filters={"name": ["in", [l.book for l in loans] or [""]]},
			fields=["name", "title"], as_list=True,
		))
		for l in loans:
			l["title"] = titles.get(l.book, l.book)
			l["overdue"] = str(l.due_date) < today()

		fine_row = frappe.db.get_all(
			"Loan",
			filters={"member": member, "docstatus": 1, "fine_paid": 0},
			fields=[{"SUM": "fine_amount", "as": "total"}],
		)
		fine = (fine_row[0].total if fine_row else 0) or 0

		return {
			"success": True,
			"member": member,
			"full_name": frappe.db.get_value("Library Member", member, "full_name"),
			"on_loan": loans,
			"outstanding_fine": flt(fine),
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
```

### 8.1 The five habits

**Whitelist ≠ authorise.** `@frappe.whitelist()` makes a function reachable by *any logged-in
user*. Add `allow_guest=True` and it's reachable by the entire internet. The role check is yours,
and it belongs on the first line. (`frappe.only_for(["Librarian"])` is the shorthand when you don't
need a custom message.)

**Everything arrives as a string.** HTTP has no types. `cint()`, `flt()`, `getdate()` on every
numeric or date argument; `json.loads()` for lists and dicts. Never trust a caller's types.

**Lock before a read-then-write.** Without `FOR UPDATE`, two requests read "Available" in the same
millisecond and both issue the book. `frappe.get_doc(dt, name, for_update=True)` is the friendlier
form and is what `return_book` uses.

**Be idempotent where it matters.** Clients retry after timeouts — often *after* the server already
committed. Detect the replay, and return a stable `reason` code so the caller can branch on it
without string-matching a translated message.

**Return a shape, not a traceback.** `frappe.throw` raises `ValidationError`; catching it at the
boundary gives every caller one predictable envelope.

### 8.2 The four ways to touch the database

Picking the right one is most of what "idiomatic Frappe" means:

```python
# 1. Document API — validation, hooks, permissions, versions. Business writes.
doc = frappe.get_doc("Book", name)
doc.status = "Lost"
doc.save()

# 2. frappe.db — direct SQL, no hooks, no validation. Fast. Derived/bulk updates.
frappe.db.set_value("Book", name, "status", "Available")
frappe.db.get_value("Library Settings", None, "fine_per_day")
frappe.db.exists("Loan", {"book": book, "docstatus": 1})
frappe.db.count("Loan", {"member": member, "docstatus": 1})

# 3. Query Builder (pypika) — composable, DB-portable, injection-safe. Aggregates.
L = frappe.qb.DocType("Loan")
frappe.qb.from_(L).select(L.member, Count(L.name)).groupby(L.member).run(as_dict=True)

# 4. Raw SQL — the escape hatch. Parameterise every value.
frappe.db.sql("UPDATE `tabLoan` SET status='Overdue' WHERE due_date < %s", today())
```

Rules of thumb:

- **One business write → `get_doc` + `save`.** You want the hooks to fire.
- **Ten thousand rows → SQL or `frappe.db.bulk_insert`.** Ten thousand `save()` calls run every
  hook ten thousand times.
- **Aggregates → query builder.** Reads better than string SQL, survives a DB change.
- **`%s` parameters, always.** Interpolate table and column names if you must; never values.

---

## 9. Calling your API

### 9.1 An API user

```bash
bench --site mysite.local console
```

```python
>>> import secrets
>>> user = frappe.new_doc("User")
>>> user.email = "desk-terminal@library.local"
>>> user.first_name = "Desk Terminal"
>>> user.user_type = "System User"
>>> user.send_welcome_email = 0
>>> user.new_password = secrets.token_urlsafe(24)
>>> user.append("roles", {"role": "Librarian"})
>>> user.insert(ignore_permissions=True)
>>> user.api_key = secrets.token_hex(16)
>>> user.api_secret = secrets.token_hex(16)
>>> user.save(ignore_permissions=True)
>>> frappe.db.commit()                       # ← the console does NOT auto-commit
>>> print(user.api_key, user.api_secret)
```

Forgetting `frappe.db.commit()` in the console, then wondering why the desk shows nothing, is a
rite of passage. Conversely, in *request* code you almost never call it — Frappe commits when the
request succeeds, and a manual commit mid-request throws away your ability to roll back.

### 9.2 curl

```bash
KEY=xxxx; SECRET=yyyy
AUTH="Authorization: token $KEY:$SECRET"
SITE=http://mysite.local:8000

curl -s -X POST "$SITE/api/method/library.api.issue_book" \
     -H "$AUTH" -d "member=ada@example.com" -d "book=BK-00001" | jq
# {"message": {"success": true, "loan": "LN-2026-00001", "due_date": "2026-01-15"}}

curl -s -X POST "$SITE/api/method/library.api.return_book" \
     -H "$AUTH" -d "book=BK-00001" | jq

curl -s "$SITE/api/method/library.api.member_summary?member=ada@example.com" -H "$AUTH" | jq

# the free REST API every DocType gets, with no code written:
curl -s "$SITE/api/resource/Book?filters=[[\"status\",\"=\",\"Available\"]]&fields=[\"name\",\"title\"]&limit_page_length=5" \
     -H "$AUTH" | jq
```

A whitelisted method's return value is always wrapped in `{"message": ...}`. Client developers
forget this constantly.

### 9.3 `bench execute`

```bash
bench --site mysite.local execute library.api.issue_book \
      --kwargs "{'member': 'ada@example.com', 'book': 'BK-00001'}"
```

Runs any dotted path in a site context. The fastest way to try a function without an HTTP round
trip, and you'll use it every day.

---

## 10. Hooks and the scheduler

This is where an app stops being CRUD. You can attach behaviour to *any* DocType in *any* installed
app without touching its code.

In `hooks.py`:

```python
doc_events = {
	"User": {
		"after_insert": "library.events.create_member_for_user",
	},
	"Book": {
		"on_trash": "library.events.block_book_delete_with_history",
	},
}

scheduler_events = {
	"daily": [
		"library.tasks.flag_overdue_loans",
		"library.tasks.send_due_reminders",
	],
}
```

`library/events.py`:

```python
import frappe
from frappe import _
from frappe.utils import today


def create_member_for_user(doc, method=None):
	"""Every new website user automatically gets a library card.

	Hook handlers always take (doc, method=None).
	"""
	# Cheap exits first — this runs on EVERY user created on the site,
	# including system users, guests being upgraded, and imports.
	if doc.user_type != "Website User":
		return
	if frappe.db.exists("Library Member", doc.email):
		return

	member = frappe.new_doc("Library Member")
	member.full_name = doc.full_name or doc.first_name or doc.email
	member.email = doc.email
	member.joined_on = today()
	member.is_active = 1
	member.insert(ignore_permissions=True)


def block_book_delete_with_history(doc, method=None):
	if frappe.db.exists("Loan", {"book": doc.name, "docstatus": 1}):
		frappe.throw(_("{0} has loan history and can't be deleted. Set it to Withdrawn instead.")
					 .format(doc.title))
```

### 10.1 The etiquette of hooking someone else's DocType

Worth a slide of its own, because this is what people get wrong:

- **Your side effect must not break their transaction.** If your code can fail in a way that isn't
  the user's fault, wrap it in a savepoint and let their save succeed:

  ```python
  frappe.db.savepoint("library_member_sync")
  try:
      ...
  except Exception:
      frappe.db.rollback(save_point="library_member_sync")
      frappe.log_error(frappe.get_traceback(), "Member auto-create failed")
  ```

  A savepoint gives you "either all of my writes or none of them, but *don't* kill the whole
  request".

- **Fail fast when it isn't your business.** The two early `return`s above run on every `User`
  insert on the site. Cheap exits first, queries only once you know there's work.
- **Batch your queries.** One `get_all` with `["in", ids]` beats one lookup per row.
- **Be idempotent.** Handlers get re-run: retries, imports, amendments.
- **Long work goes to a queue.** See §11.

### 10.2 The scheduler

`library/tasks.py`:

```python
import frappe
from frappe.utils import add_days, flt, today


def flag_overdue_loans():
	"""Daily: mark overdue loans and accrue the fine so far.

	Two statements, not ten thousand save() calls — a sweep over the whole table
	is exactly where the Document API is the wrong tool.
	"""
	frappe.db.sql(
		"""
		UPDATE `tabLoan`
		SET status = 'Overdue'
		WHERE docstatus = 1 AND status = 'Issued' AND due_date < %s
		""",
		today(),
	)
	frappe.db.sql(
		"""
		UPDATE `tabLoan`
		SET fine_amount = fine_per_day * DATEDIFF(%s, due_date)
		WHERE docstatus = 1 AND status = 'Overdue' AND fine_paid = 0
		""",
		today(),
	)


def send_due_reminders():
	"""Daily: email anyone whose book is due in two days."""
	target = add_days(today(), 2)
	loans = frappe.get_all(
		"Loan",
		filters={"docstatus": 1, "status": "Issued", "due_date": target},
		fields=["name", "member", "book", "due_date"],
	)
	if not loans:
		return

	titles = dict(frappe.get_all(
		"Book", filters={"name": ["in", [l.book for l in loans]]},
		fields=["name", "title"], as_list=True,
	))
	for loan in loans:
		frappe.sendmail(
			recipients=[loan.member],           # member is named by email
			subject=f"Due in 2 days: {titles.get(loan.book, loan.book)}",
			message=(
				f"<p>Hello,</p>"
				f"<p><b>{titles.get(loan.book, loan.book)}</b> is due back on "
				f"<b>{loan.due_date}</b>.</p>"
			),
			reference_doctype="Loan",
			reference_name=loan.name,
		)
```

Available buckets: `all` (roughly every 4 minutes), `hourly`, `daily`, `weekly`, `monthly`, plus
`cron` for anything else:

```python
scheduler_events = {
	"cron": {
		"0 6 * * *": ["library.tasks.send_due_reminders"],
	},
}
```

Two set-up gotchas that waste an hour each:

- **The scheduler is disabled on new sites.** `bench --site mysite.local enable-scheduler`.
- **It runs in a worker**, so `bench start` must be running. Don't wait for a tick to test — call
  the function directly with `bench execute`.

---

## 11. Background jobs and email

Anything slow — a report over the whole table, a bulk import, an external API call — must not run
inside a user's save. Push it to a worker:

```python
frappe.enqueue(
	"library.tasks.rebuild_catalogue_cache",
	queue="long",           # "short" (default), "default", "long"
	timeout=1500,
	job_name="catalogue-rebuild",
	now=frappe.in_test,         # run inline during tests so assertions can see the result
	member=member,              # any extra kwargs are passed to the function
)
```

Things worth knowing before you rely on it:

- **The job runs in a *different* transaction**, after your request commits. Don't enqueue a job
  that reads a row you haven't committed yet.
- **Pass IDs, not documents.** Arguments are serialised; send `loan="LN-2026-00001"` and let the
  job load it fresh.
- **Watch them at `/app/rq-job`.** Failures land in the Error Log, not in your terminal.
- **`now=True`** runs it inline — the standard trick for tests.

Email is itself a queue. `frappe.sendmail()` writes an Email Queue row and returns immediately; a
background job does the sending.

```python
frappe.sendmail(
	recipients=["ada@example.com"],
	subject="Your library account",
	message="<p>Hello!</p>",           # HTML
	reference_doctype="Loan",          # links the email into the doc's timeline
	reference_name="LN-2026-00001",
	now=False,                         # True = send synchronously (tests, or a real 'send now')
)
```

For anything a user might want to edit, use a template instead of a Python string: create an
**Email Template** record, then

```python
frappe.sendmail(
	recipients=[member],
	subject=frappe.render_template(tmpl.subject, context),
	message=frappe.render_template(tmpl.response_html, context),
)
```

In dev, nothing is actually sent unless an outgoing Email Account is configured — inspect
`/app/email-queue` to see what *would* have gone out.

> **Notifications without code.** The **Notification** DocType sends an email/system alert on a
> document event ("Loan is overdue", "new Member created") with conditions set in the UI, no Python
> at all. Build it in the desk, then ship it as a fixture (§17). Reach for it before writing a hook.

---

## 12. Custom fields on someone else's DocType

We want a link from Frappe's `User` to our `Library Member`. We can't edit the `User` DocType — it
belongs to the framework, and any change would be wiped on upgrade. Custom Fields are the supported
answer, and shipping them in code is what makes them exist on every site rather than just yours.

In `hooks.py`:

```python
after_install = "library.install.after_install"
after_migrate = "library.install.after_migrate"
before_uninstall = "library.uninstall.before_uninstall"
```

`library/install.py`:

```python
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

CUSTOM_FIELDS = {
	"User": [
		{
			"fieldname": "custom_library_member",
			"fieldtype": "Link",
			"label": "Library Member",
			"options": "Library Member",
			"insert_after": "user_type",
			"read_only": 1,
			"description": "Created automatically when a website user signs up.",
		}
	]
}


def after_install():
	ensure_custom_fields()
	ensure_roles()
	seed_settings()


def after_migrate():
	# after_migrate runs on EVERY deploy, on every site. Keep it cheap and re-runnable.
	ensure_custom_fields()
	ensure_roles()


def ensure_custom_fields():
	create_custom_fields(CUSTOM_FIELDS, ignore_validate=True)


def ensure_roles():
	for role_name in ("Librarian", "Library Member"):
		if not frappe.db.exists("Role", role_name):
			role = frappe.new_doc("Role")
			role.role_name = role_name
			role.desk_access = 1 if role_name == "Librarian" else 0
			role.insert(ignore_permissions=True)


def seed_settings():
	"""Give the Single sensible values on a fresh site — but never overwrite
	an admin's edits on a re-run."""
	settings = frappe.get_doc("Library Settings")
	if not settings.loan_period_days:
		settings.loan_period_days = 14
		settings.max_books_per_member = 5
		settings.fine_per_day = 2
		settings.library_name = "The Library"
		settings.save(ignore_permissions=True)
```

Four rules for this pattern:

1. **Prefix with `custom_`.** Marks the field as yours and avoids colliding with a future upstream
   field of the same name.
2. **Idempotent, always.** `after_migrate` runs on every deploy. `create_custom_fields` updates
   rather than duplicating, but any extra logic you add must survive re-running.
3. **Be careful with `insert_after`.** Pointing at a fieldname from an app you don't control is a
   time bomb across upgrades. Anchor to something stable, or compute the anchor at runtime from
   `frappe.get_meta("User").fields`.
4. **Clean up on uninstall.** This is the step everyone skips:

`library/uninstall.py`:

```python
import frappe


def before_uninstall():
	"""`bench uninstall-app` removes records the app OWNS — its DocTypes, its Module Def.
	A Custom Field living on `User` is not owned by us, so it survives — and a Link
	pointing at the now-deleted `Library Member` breaks every User form with
	"Missing DocType". Remove it explicitly.
	"""
	if frappe.db.exists("Custom Field", "User-custom_library_member"):
		frappe.delete_doc("Custom Field", "User-custom_library_member",
						  ignore_permissions=True, force=True)
	frappe.clear_cache(doctype="User")
```

> **Custom Field vs Property Setter.** A Custom Field *adds* a field. To change something about an
> *existing* field — make it mandatory, hide it, relabel it — you want a Property Setter, created
> the same way via `frappe.make_property_setter(...)`. Both are how you customise another app
> without forking it.

---

## 13. Desk UI

Frappe's desk is a JS app you extend with small event handlers. No build step, no framework, no
imports — the files are served as-is.

### 13.1 Form script

A DocType's `.js` file next to its `.json` is loaded automatically on that form.

`library/library/doctype/book/book.js`:

```javascript
frappe.ui.form.on("Book", {
	refresh(frm) {
		if (frm.is_new()) return;

		// A button that only makes sense in one state
		if (frm.doc.status === "Available" && !frm.doc.is_reference_only) {
			frm.add_custom_button(__("Issue Book"), () => issue_dialog(frm));
		}

		if (frm.doc.status === "On Loan") {
			frm.add_custom_button(__("Return Book"), () => {
				frappe.call({
					method: "library.api.return_book",
					args: { book: frm.doc.name },
					freeze: true,
					freeze_message: __("Checking the book in…"),
					callback(r) {
						const m = r.message;
						if (m && m.success) {
							frappe.show_alert({
								message: m.was_late
									? __("Returned — fine of {0}", [format_currency(m.fine)])
									: __("Returned, on time"),
								indicator: m.was_late ? "orange" : "green",
							});
							frm.reload_doc();
						} else {
							frappe.msgprint((m && m.error) || __("Could not return that book"));
						}
					},
				});
			});

			frm.dashboard.set_headline(
				__("This copy is currently out on loan.")
			);
		}
	},

	// fires when one field changes
	is_reference_only(frm) {
		if (frm.doc.is_reference_only && frm.doc.status === "On Loan") {
			frappe.msgprint(__("This copy is out on loan — it can't be made reference-only yet."));
			frm.set_value("is_reference_only", 0);
		}
	},
});

function issue_dialog(frm) {
	const d = new frappe.ui.Dialog({
		title: __("Issue {0}", [frm.doc.title]),
		fields: [
			{
				fieldname: "member",
				label: __("Member"),
				fieldtype: "Link",
				options: "Library Member",
				reqd: 1,
				// only offer members who can actually borrow
				get_query: () => ({ filters: { is_active: 1 } }),
			},
			{
				fieldname: "due_date",
				label: __("Due Date"),
				fieldtype: "Date",
				description: __("Leave blank to use the standard loan period."),
			},
		],
		primary_action_label: __("Issue"),
		primary_action(values) {
			frappe.call({
				method: "library.api.issue_book",
				args: { member: values.member, book: frm.doc.name, due_date: values.due_date },
				freeze: true,
				callback(r) {
					const m = r.message;
					if (m && m.success) {
						d.hide();
						frappe.show_alert({
							message: __("Issued — due {0}", [m.due_date]),
							indicator: "green",
						});
						frm.reload_doc();
					} else {
						frappe.msgprint((m && m.error) || __("Could not issue that book"));
					}
				},
			});
		},
	});
	d.show();
}
```

The API you'll use 90% of the time:

| Call | Does |
|---|---|
| `frm.add_custom_button(label, fn, group)` | button in the top-right menu |
| `frm.set_value(field, val)` | change data (fires the field's handler) |
| `frm.set_df_property(field, "reqd", 1)` | change the *field*, at runtime |
| `frm.toggle_display(field, bool)` | show/hide |
| `frm.set_query(field, fn)` | filter what a Link offers |
| `frm.dashboard.set_headline(html)` / `.add_section(html, title)` | custom blocks on the form |
| `frappe.call({method, args, callback, freeze})` | call a whitelisted method |
| `frappe.msgprint` / `show_alert` / `confirm` / `prompt` | user interaction |
| `new frappe.ui.Dialog({...})` | a form in a modal |
| `frm.reload_doc()` | re-fetch after a server-side change |
| `__("text")` | translate — wrap every user-visible string |

Notice that a dialog's `fields` use the exact same fieldtype vocabulary as a DocType JSON. Learn
the schema once, use it in three places.

### 13.2 List view script

List scripts live in `public/js/` and get wired in `hooks.py`:

```python
doctype_list_js = {"Loan": "public/js/loan_list.js"}
```

`library/public/js/loan_list.js`:

```javascript
frappe.listview_settings["Loan"] = {
	add_fields: ["status", "due_date"],

	// colour the status column — state you can read at a glance
	get_indicator(doc) {
		const map = {
			Issued: "blue",
			Returned: "green",
			Overdue: "red",
			Lost: "grey",
		};
		return [__(doc.status), map[doc.status] || "grey", "status,=," + doc.status];
	},

	onload(listview) {
		listview.page.add_inner_button(__("Overdue only"), () => {
			listview.filter_area.add([["Loan", "status", "=", "Overdue"]]);
		});
	},
};
```

After touching anything under `public/`:

```bash
bench build --app library      # or `bench watch` while developing
```

then hard-refresh. "My JS didn't apply" is almost always a missing `bench build` or a cached bundle.

### 13.3 The rest of the desk, for free

Three things you configure rather than code, then export as fixtures (§17):

- **Workspace** — the landing page for your module: shortcuts, charts, links. `/app/library`.
- **Kanban / Calendar / Gantt views** — a Kanban needs only a `Select` field to group by; add a
  `calendar.js` next to your DocType for a calendar view.
- **Form Tour / Onboarding** — guided first-run walkthroughs.

---

## 14. A public website page

Anything under `library/www/` becomes a public URL. `www/catalogue.html` → `/catalogue`. No routing
config needed; a `.py` file of the same name supplies the context.

`library/www/catalogue.py`:

```python
import frappe

no_cache = 1


def get_context(context):
	if not frappe.db.get_single_value("Library Settings", "enable_public_catalogue"):
		raise frappe.DoesNotExistError        # renders the standard 404

	search = (frappe.form_dict.get("q") or "").strip()

	filters = {"status": ["!=", "Withdrawn"]}
	or_filters = None
	if search:
		or_filters = {"title": ["like", f"%{search}%"], "isbn": ["like", f"%{search}%"]}

	context.books = frappe.get_all(
		"Book",
		filters=filters,
		or_filters=or_filters,
		fields=["name", "title", "isbn", "status", "shelf"],
		order_by="title asc",
		limit_page_length=60,          # always bound a public query
	)
	context.search = search
	context.library_name = frappe.db.get_single_value("Library Settings", "library_name")
	context.title = f"{context.library_name} — Catalogue"
	context.no_breadcrumbs = True
```

`library/www/catalogue.html`:

```html
{% extends "templates/web.html" %}

{% block title %}{{ library_name }} — Catalogue{% endblock %}

{% block page_content %}
<h1>{{ library_name }}</h1>

<form method="get" class="mb-4">
  <input type="text" name="q" value="{{ search or '' }}"
         class="form-control" placeholder="Search by title or ISBN">
</form>

{% if not books %}
  <p class="text-muted">Nothing matched “{{ search }}”.</p>
{% else %}
  <table class="table">
    <thead>
      <tr><th>Title</th><th>Shelf</th><th>Status</th></tr>
    </thead>
    <tbody>
      {% for book in books %}
      <tr>
        <td>{{ book.title }}</td>
        <td>{{ book.shelf or "—" }}</td>
        <td>
          {% if book.status == "Available" %}
            <span class="indicator green">Available</span>
          {% else %}
            <span class="indicator orange">{{ book.status }}</span>
          {% endif %}
        </td>
      </tr>
      {% endfor %}
    </tbody>
  </table>
{% endif %}
{% endblock %}
```

Extending `templates/web.html` inherits the site's nav, theme and mobile viewport.

**Every `www/` page is world-readable.** That's the point here, but it's also the single most likely
place for an app to leak data. If a page shouldn't be public, say so on the first line:

```python
def get_context(context):
	frappe.only_for(["Librarian", "System Manager"])
```

### 14.1 Pretty URLs

For `/book/9780441013593`, add a route rule in `hooks.py`:

```python
website_route_rules = [
	{"from_route": "/book/<isbn>", "to_route": "book"},
]
```

The `<isbn>` lands in `frappe.form_dict` for `www/book.py` to read.

### 14.2 Jinja methods

To call your own Python from any template or Print Format, register it:

```python
jinja = {
	"methods": ["library.utils.availability_badge"],
}
```

`library/utils.py`:

```python
def availability_badge(status):
	colour = {"Available": "green", "On Loan": "orange", "Lost": "red"}.get(status, "grey")
	return f'<span class="indicator {colour}">{status}</span>'
```

```html
{{ availability_badge(book.status) }}
```

### 14.3 Web Forms

For public *input* — a membership application, a book request — don't hand-write a form and a POST
handler. Create a **Web Form** record pointed at a DocType; you get a themed, validated, permissioned
public form with an optional login requirement and a list view for the submitter. Build it in the
desk, then ship it as a fixture.

---

## 15. Reports and dashboards

### 15.1 The three kinds of report

- **Report Builder** — user-configured, no code. Free with every DocType.
- **Query Report** — one SQL string, stored in the database. Quick, but it lives in a site, not in
  git.
- **Script Report** — Python, in your app, versioned. This is what you write.

```
library/library/report/overdue_loans/
├── __init__.py
├── overdue_loans.json
└── overdue_loans.py
```

`overdue_loans.json`:

```json
{
 "add_total_row": 1,
 "creation": "2026-01-01 00:00:00.000000",
 "disabled": 0,
 "docstatus": 0,
 "doctype": "Report",
 "idx": 0,
 "is_standard": "Yes",
 "module": "Library",
 "name": "Overdue Loans",
 "owner": "Administrator",
 "modified": "2026-01-01 00:00:00.000000",
 "modified_by": "Administrator",
 "prepared_report": 0,
 "ref_doctype": "Loan",
 "report_name": "Overdue Loans",
 "report_type": "Script Report",
 "roles": [{"role": "Librarian"}, {"role": "System Manager"}]
}
```

`"is_standard": "Yes"` is what makes it load from your app's files rather than from the database.

`overdue_loans.py` — one function returning `(columns, rows)`:

```python
import frappe
from frappe import _
from frappe.utils import today


def execute(filters=None):
	filters = filters or {}

	conditions = ["l.docstatus = 1", "l.status != 'Returned'", "l.due_date < %(today)s"]
	values = {"today": today()}

	if filters.get("member"):
		conditions.append("l.member = %(member)s")
		values["member"] = filters["member"]

	# Structure from your own constants; values always bound as parameters.
	where = " AND ".join(conditions)

	rows = frappe.db.sql(
		f"""
		SELECT
			l.name              AS loan,
			l.member            AS member,
			m.full_name         AS member_name,
			b.title             AS book_title,
			l.due_date          AS due_date,
			DATEDIFF(%(today)s, l.due_date) AS days_late,
			l.fine_amount       AS fine
		FROM `tabLoan` l
		JOIN `tabLibrary Member` m ON m.name = l.member
		JOIN `tabBook` b          ON b.name = l.book
		WHERE {where}
		ORDER BY l.due_date ASC
		""",
		values,
		as_dict=True,
	)

	columns = [
		{"label": _("Loan"), "fieldname": "loan", "fieldtype": "Link", "options": "Loan", "width": 130},
		{"label": _("Member"), "fieldname": "member", "fieldtype": "Link", "options": "Library Member", "width": 180},
		{"label": _("Name"), "fieldname": "member_name", "fieldtype": "Data", "width": 160},
		{"label": _("Book"), "fieldname": "book_title", "fieldtype": "Data", "width": 240},
		{"label": _("Due"), "fieldname": "due_date", "fieldtype": "Date", "width": 100},
		{"label": _("Days Late"), "fieldname": "days_late", "fieldtype": "Int", "width": 100},
		{"label": _("Fine"), "fieldname": "fine", "fieldtype": "Currency", "width": 110},
	]

	return columns, rows
```

Give a column `"fieldtype": "Link"` and the report renders it as a clickable link to the record —
free navigation from a report row into the document.

Optional third and fourth return values add a message and a chart:

```python
	chart = {
		"data": {
			"labels": [r.member_name for r in rows[:10]],
			"datasets": [{"name": _("Fine"), "values": [r.fine for r in rows[:10]]}],
		},
		"type": "bar",
	}
	return columns, rows, None, chart
```

Add a `overdue_loans.js` next to it to declare filters:

```javascript
frappe.query_reports["Overdue Loans"] = {
	filters: [
		{
			fieldname: "member",
			label: __("Member"),
			fieldtype: "Link",
			options: "Library Member",
		},
	],
};
```

### 15.2 Dashboard charts and number cards

Two DocTypes you configure rather than code:

- **Dashboard Chart** — point it at a DocType, pick a field, an aggregate and a time span. Add it to
  your Workspace.
- **Number Card** — one big figure ("Books on loan", "Fines outstanding") with a filter behind it.

Build them in the desk with developer mode on, then export as fixtures so they ship with the app.

---

## 16. Print formats and PDF

Every document can print. Frappe generates a default layout from the form, and
`/api/method/frappe.utils.print_format.download_pdf?doctype=Loan&name=LN-2026-00001` gives you a PDF
of it with no work at all.

For something custom — a due-date slip to tuck into the book — you have three options:

1. **Print Format Builder** — drag fields around in the UI. Fine for simple layouts.
2. **A custom HTML print format** — a `Print Format` record with `"print_format_type": "Jinja"` and
   your own HTML. This is what you want for anything with a real layout.
3. **`frappe.render_template` into your own endpoint** — when it isn't really a document print.

The Jinja version, created in the desk and then exported into your app at
`library/library/print_format/due_date_slip/due_date_slip.json`:

```html
<div style="font-family: monospace; width: 60mm; padding: 6mm; border: 1px dashed #999;">
  <div style="font-size: 11px; letter-spacing: 1px; text-transform: uppercase;">
    {{ frappe.db.get_single_value("Library Settings", "library_name") }}
  </div>
  <h3 style="margin: 4px 0;">{{ frappe.db.get_value("Book", doc.book, "title") }}</h3>
  <p style="margin: 2px 0;">Issued to: <b>{{ doc.member }}</b></p>
  <p style="margin: 2px 0;">Issued on: {{ frappe.format(doc.issue_date, {"fieldtype": "Date"}) }}</p>
  <p style="margin: 8px 0; font-size: 16px;">
    DUE: <b>{{ frappe.format(doc.due_date, {"fieldtype": "Date"}) }}</b>
  </p>
  <p style="font-size: 10px; color: #666;">
    Late returns are charged {{ frappe.format(doc.fine_per_day, {"fieldtype": "Currency"}) }} per day.
  </p>
</div>
```

Inside a print format, `doc` is the document and `frappe.format(value, df)` renders a value the way
the framework would (dates, currency, links). Anything you registered under `jinja.methods` (§14.2)
is available here too.

To generate a PDF from Python:

```python
from frappe.utils.pdf import get_pdf

html = frappe.get_print("Loan", loan_name, print_format="Due Date Slip")
pdf = get_pdf(html)
```

---

## 17. Roles, permissions, fixtures

### 17.1 The five layers

1. **Role permissions** — the `permissions` block of a DocType JSON. Per role, per operation
   (`read`/`write`/`create`/`delete`/`submit`/`cancel`/`amend`/`report`/`export`/`share`/`email`/`print`),
   optionally per `permlevel` for field-level control.
2. **User permissions** — records restricting a user to specific documents ("only the West Branch").
3. **`permission_query_conditions`** — a hook returning a SQL `WHERE` fragment injected into every
   list query for a DocType.
4. **`has_permission`** — a hook for per-document Python logic.
5. **Your own role check** at the top of every whitelisted method.

Layer 5 is not optional, and here's why: **the framework's permission system does not run inside
your whitelisted method.** And `ignore_permissions=True` — which you need constantly, because a
member shouldn't have write access to `Loan` just to borrow a book — bypasses layers 1–4 entirely.

Layer 3 is how you'd let members see only their own loans in the portal:

```python
# hooks.py
permission_query_conditions = {
	"Loan": "library.permissions.loan_query_conditions",
}
```

```python
# library/permissions.py
import frappe


def loan_query_conditions(user=None):
	user = user or frappe.session.user
	if "Librarian" in frappe.get_roles(user) or "System Manager" in frappe.get_roles(user):
		return ""                                  # no restriction
	return f"`tabLoan`.member = {frappe.db.escape(user)}"
```

### 17.2 Full permission rows

Once you have roles, spell them out in the DocType JSON:

```json
 "permissions": [
  {
   "role": "System Manager",
   "create": 1, "read": 1, "write": 1, "delete": 1, "submit": 1, "cancel": 1, "amend": 1,
   "email": 1, "export": 1, "print": 1, "report": 1, "share": 1
  },
  {
   "role": "Librarian",
   "create": 1, "read": 1, "write": 1, "delete": 0, "submit": 1, "cancel": 1, "amend": 1,
   "email": 1, "export": 1, "print": 1, "report": 1, "share": 1
  },
  {
   "role": "Library Member",
   "read": 1
  }
 ]
```

Note the librarian can't `delete` — loans are records of things that happened. Cancel, don't delete.

### 17.3 Fixtures

Roles, Workspaces, Dashboard Charts, Notifications, Print Formats, Web Forms and Email Templates are
all *records*, not files. Ship them as **fixtures**: exported to JSON in your app and re-imported on
every migrate.

```python
# hooks.py
fixtures = [
	{"dt": "Role", "filters": [["role_name", "in", ["Librarian", "Library Member"]]]},
	{"dt": "Print Format", "filters": [["module", "=", "Library"]]},
	{"dt": "Notification", "filters": [["module", "=", "Library"]]},
]
```

```bash
bench --site mysite.local export-fixtures --app library
```

That writes `library/fixtures/role.json` and friends. Commit them, and every future `bench migrate`
on every site creates them.

Fixtures are right for reference data you *own*. They're wrong for anything users edit — the next
migrate overwrites their changes.

---

## 18. Patches

DocType JSON handles *schema*. Patches handle *data* — backfilling a new column, renaming a value,
fixing what a bug wrote.

`library/patches/v1_0/set_default_book_status.py`:

```python
import frappe


def execute():
	# Books that predate the status field. Only touches unset rows, so it's
	# safe to re-run on a restored backup.
	frappe.db.sql("""
		UPDATE `tabBook`
		SET status = 'Available'
		WHERE status IS NULL OR status = ''
	""")
```

Register it in `patches.txt`:

```
[pre_model_sync]
# fixes that must happen BEFORE the schema changes

[post_model_sync]
library.patches.v1_0.set_default_book_status
```

Rules:

- **`__init__.py` in every patch directory** (`patches/`, `patches/v1_0/`).
- **A patch runs once per site, ever.** Frappe records the dotted path in the Patch Log table. To
  re-run in dev: `bench --site … execute library.patches.v1_0.set_default_book_status.execute`, or
  delete its Patch Log row.
- **Write them re-runnable anyway.** You'll eventually run one against a restored backup.
- **`pre` vs `post`:** if your patch reads a column the *new* schema adds, it's `post`. If it must
  clean up data that would break the schema change itself — duplicates about to get a unique index —
  it's `pre`.
- **Never delete a shipped patch file.** Sites that haven't migrated yet still need it.
- **Renaming a field** is `rename_field("Book", "old", "new")` from
  `frappe.model.utils.rename_field`, in a `pre_model_sync` patch, *plus* the JSON change. Doing only
  the JSON change drops the column and its data.

---

## 19. Tests

Frappe ships a runner over `unittest`. Tests run against a real site and a real database, inside a
transaction that's rolled back after each test.

`library/library/doctype/loan/test_loan.py`:

```python
import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import add_days, today

from library.api import issue_book, member_summary, return_book


def make_book(title="Test Book", isbn=None, reference=0):
	book = frappe.new_doc("Book")
	book.title = title
	book.isbn = isbn
	book.is_reference_only = reference
	book.status = "Available"
	book.insert(ignore_permissions=True)
	return book


def make_member(email="test.member@example.com", active=1):
	if frappe.db.exists("Library Member", email):
		frappe.delete_doc("Library Member", email, ignore_permissions=True, force=True)
	member = frappe.new_doc("Library Member")
	member.full_name = "Test Member"
	member.email = email
	member.is_active = active
	member.joined_on = today()
	member.insert(ignore_permissions=True)
	return member


class TestLoan(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.member = make_member()
		self.book = make_book()

	def test_issue_marks_book_on_loan(self):
		res = issue_book(member=self.member.name, book=self.book.name)

		self.assertTrue(res["success"])
		self.assertEqual(frappe.db.get_value("Book", self.book.name, "status"), "On Loan")

	def test_cannot_issue_the_same_copy_twice(self):
		issue_book(member=self.member.name, book=self.book.name)
		other = make_member(email="second@example.com")

		res = issue_book(member=other.name, book=self.book.name)

		self.assertFalse(res["success"])
		self.assertIn("on loan", res["error"].lower())

	def test_reference_books_never_leave(self):
		ref = make_book(title="Big Dictionary", reference=1)

		res = issue_book(member=self.member.name, book=ref.name)

		self.assertFalse(res["success"])
		self.assertIn("reference only", res["error"].lower())

	def test_borrow_limit_is_enforced(self):
		frappe.db.set_single_value("Library Settings", "max_books_per_member", 2)
		for i in range(2):
			issue_book(member=self.member.name, book=make_book(title=f"B{i}").name)

		res = issue_book(member=self.member.name, book=make_book(title="One too many").name)

		self.assertFalse(res["success"])
		self.assertIn("limit", res["error"].lower())

	def test_late_return_charges_a_fine(self):
		issue_book(member=self.member.name, book=self.book.name)
		loan = frappe.db.get_value("Loan", {"book": self.book.name, "docstatus": 1}, "name")
		# force the due date into the past
		frappe.db.set_value("Loan", loan, "due_date", add_days(today(), -3))
		frappe.db.set_value("Loan", loan, "fine_per_day", 2)

		res = return_book(loan=loan)

		self.assertTrue(res["success"])
		self.assertEqual(res["fine"], 6)                 # 3 days x 2
		self.assertTrue(res["was_late"])
		self.assertEqual(frappe.db.get_value("Book", self.book.name, "status"), "Available")

	def test_returning_twice_is_reported_not_double_charged(self):
		issue_book(member=self.member.name, book=self.book.name)
		loan = frappe.db.get_value("Loan", {"book": self.book.name, "docstatus": 1}, "name")
		return_book(loan=loan)

		res = return_book(loan=loan)

		self.assertFalse(res["success"])
		self.assertEqual(res["reason"], "already_returned")

	def test_cancelling_a_loan_puts_the_book_back(self):
		issue_book(member=self.member.name, book=self.book.name)
		loan = frappe.get_doc("Loan", {"book": self.book.name, "docstatus": 1})

		loan.cancel()

		self.assertEqual(frappe.db.get_value("Book", self.book.name, "status"), "Available")
```

> **Which base class?** `IntegrationTestCase` for anything that creates, queries or saves a
> document — which is nearly everything, including tests that only make an empty DocType stub.
> `UnitTestCase` is for pure in-memory logic that never touches the database. (The old
> `frappe.tests.utils.FrappeTestCase` still imports on v16 but is deprecated and disappears in v17 —
> don't start new tests on it.)

Running them:

```bash
bench --site mysite.local run-tests --app library
bench --site mysite.local run-tests --doctype "Loan"
bench --site mysite.local run-tests --module library.library.doctype.loan.test_loan
```

Notes that matter:

- **`IntegrationTestCase` wraps each test in a transaction and rolls back**, so tests don't pollute
  each other. Still clean up explicitly for anything created in `setUpClass` — and if you override
  `setUpClass`, **call `super().setUpClass()`** or the harness never starts.
- **Declaring test dependencies** is `EXTRA_TEST_RECORD_DEPENDENCIES` at module level (and
  `IGNORE_TEST_RECORD_DEPENDENCIES` to opt out). The v15 names `test_dependencies` / `test_ignore`
  are gone.
- **Call your API functions directly.** They're plain Python — no HTTP needed.
- **Test the invariants, not the getters.** Every test above is a rule that would cost real money
  or real trust if it broke: can't double-issue, can't exceed the limit, fines are right, retries
  don't double-charge, cancel reverses cleanly. That's the bar.
- **`frappe.set_user(...)`** switches the acting user, which is how you test permissions.
- **Mock the network.** Never let a test make a real HTTP call —
  `unittest.mock.patch("library.api.some_client")`.
- Frappe also auto-creates fixtures from a `test_records.json` next to a DocType — handy, though
  explicit factory functions like `make_book()` read better.

---

## 20. Workflow: when you need approvals

If a document needs *approval* rather than just a status field, don't build it — configure a
**Workflow**. States, transitions, and which role can make each one. It manages a
`workflow_state` field and puts the action buttons on the form.

You can build it in the UI, but shipping it in `after_install` means every site gets it:

```python
def ensure_membership_workflow():
	"""Draft -> Approved / Rejected for membership applications. Idempotent —
	never overwrites an existing Workflow doc."""
	if frappe.db.exists("Workflow", "Library Member Approval"):
		return

	for state in ("Pending", "Approved", "Rejected"):
		if not frappe.db.exists("Workflow State", state):
			frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": state}).insert(
				ignore_permissions=True)

	wf = frappe.new_doc("Workflow")
	wf.workflow_name = "Library Member Approval"
	wf.document_type = "Library Member"
	wf.workflow_state_field = "status"     # reuse the doctype's own Select field
	wf.is_active = 1

	for state in ("Pending", "Approved", "Rejected"):
		wf.append("states", {"state": state, "doc_status": "0", "allow_edit": "Librarian"})

	wf.append("transitions", {
		"state": "Pending", "action": "Approve", "next_state": "Approved",
		"allowed": "Librarian", "allow_self_approval": 1,
	})
	wf.append("transitions", {
		"state": "Pending", "action": "Reject", "next_state": "Rejected",
		"allowed": "Librarian", "allow_self_approval": 1,
	})

	wf.insert(ignore_permissions=True)
```

Two details: pointing `workflow_state_field` at a `Select` field you already have avoids a second,
duplicate status to keep in sync (Workflow only auto-creates a field if none by that name exists).
And `allow_self_approval` is a real control — turn it off when the requester must not be the
approver.

---

## 21. Dev workflow and gotchas

### 21.1 The loop

```bash
# terminal 1
bench start

# terminal 2 — after ANY .json or hooks.py change
bench --site mysite.local migrate

# after a public/ (js, css) change
bench build --app library

# when something is stale and you can't explain it
bench --site mysite.local clear-cache
bench --site mysite.local clear-website-cache
```

### 21.2 The gotchas

**`hooks.py` is cached.** A new hook needs a `migrate`, or at minimum `clear-cache`. Editing
`doc_events` and seeing nothing happen is almost always this.

**Python changes need a process restart when the reloader is off.** `bench start` auto-reloads;
production and anything started with `--noreload` does not. Your edit is on disk and the worker is
still running the old bytecode.

**`bench migrate` runs `after_migrate` for every installed app.** An expensive or non-idempotent
`after_migrate` slows down — or breaks — every deploy on every site.

**Missing `__init__.py`** → `ModuleNotFoundError` on migrate. Check the module dir, the doctype
dirs, the patches dirs.

**DocType name ↔ folder ↔ file ↔ class** must all agree: `Library Member` →
`library_member/library_member.py` → `class LibraryMember`.

**Nothing shows in the desk** → check the DocType's `permissions`. Empty means Administrator only.

**Nothing commits in the console** → `frappe.db.commit()`. And never in request code.

**Submit button missing** → `"submit": 1` in the permission row, and `is_submittable: 1` on the
DocType.

**Can't edit a field after submit** → it needs `allow_on_submit: 1`.

**Amend crashes** → you're missing the `amended_from` field.

**Secrets in a `Data` field** → use the `Password` fieldtype. It's stored encrypted in `__Auth`, and
read with `get_decrypted_password("Doctype", name, "fieldname")`. `doc.the_field` gives you a
placeholder, not the secret.

**A bare `python script.py`** has no site context. It needs `frappe.init(site=...)` then
`frappe.connect()`. `bench execute` and `bench console` do this for you.

**`bench init` fails with a dependency mess** → you're not on Python 3.14. v16 pins
`>=3.14,<3.15`; 3.12 and 3.13 both fail, and the error names a package rather than the interpreter.

**A list came back in the wrong order** → v16 sorts by `creation desc` by default, not `modified`.
Pass `order_by` explicitly.

**`SQL functions are not allowed as strings in SELECT`** → you passed `"sum(x)"` or `"count(*)"` as
a field. Use `fields=[{"SUM": "x", "as": "total"}]`. `frappe.db.count()` still works as-is.

**A `has_permission` hook stopped granting access** → it must `return True` now. Returning `None`
denies.

### 21.3 Where to look when it breaks

| Symptom | Look at |
|---|---|
| Endpoint 500s | `/app/error-log` |
| Scheduled job didn't run | `/app/scheduled-job-type`, then `bench … enable-scheduler` |
| Background job vanished | `/app/rq-job`, `bench doctor` |
| Email never arrived | `/app/email-queue` |
| Any request | the `bench start` terminal, and `logs/` in the bench directory |
| "It worked yesterday" | `/app/version/…` — `track_changes` recorded who changed what |

---

## 22. The completeness checklist

Run this against your own app. Anything unchecked is either deliberately not needed, or a gap.

**Structure**

- [ ] `pyproject.toml`, `__init__.py` with `__version__`, `hooks.py`, `modules.txt`, `patches.txt`
- [ ] `__init__.py` at every package level
- [ ] `license.txt` and a `README.md` that says what the app is for
- [ ] The app installs cleanly onto a *fresh* site — test it, don't assume it

**Data**

- [ ] Every DocType has a deliberate `autoname` / `naming_rule`
- [ ] `search_index` on every field you filter or join on at scale
- [ ] `unique` on anything that must not duplicate — not just an application-level check
- [ ] `title_field` and `search_fields` set, so lists and Link dropdowns are usable
- [ ] Transactions are **submittable**, with `amended_from` and `allow_on_submit` where needed
- [ ] `description` on every non-obvious field
- [ ] Derived values are derived, not stored in a column that can drift

**Logic**

- [ ] Validation in `validate`; commitment checks in `before_submit`
- [ ] `on_cancel` exactly reverses `on_submit`
- [ ] Behaviour lives on the Document; endpoints are thin
- [ ] No `self.save()` inside a lifecycle hook

**API**

- [ ] A role check as the first line of every `@frappe.whitelist()` function
- [ ] `cint`/`flt`/`getdate`/`json.loads` on every argument
- [ ] Row locking anywhere you read-then-write
- [ ] Idempotency, with a stable machine-readable `reason`, on anything that moves value
- [ ] Every list response is bounded by a `limit_page_length`
- [ ] Errors return a shape, not a traceback

**Integration**

- [ ] `doc_events` handlers exit cheaply when it isn't their business
- [ ] Slow work is enqueued, not run inline
- [ ] Emails are queued, and linked to their document via `reference_doctype`
- [ ] Custom Fields on other apps' DocTypes are created in `after_install` **and** `after_migrate`
- [ ] `before_uninstall` removes everything your app doesn't own

**Interface**

- [ ] Desk buttons appear only in states where they make sense
- [ ] List views have a `get_indicator` so state reads at a glance
- [ ] Every user-visible string is wrapped in `__()` / `_()`
- [ ] Public `www/` pages either *should* be public or call `frappe.only_for` on line one
- [ ] At least one report, and a Workspace so the module has a front door
- [ ] A print format for anything that gets printed or emailed as PDF

**Operations**

- [ ] Roles created on install; permission rows on every DocType
- [ ] Fixtures for records the app owns, committed to git
- [ ] Patches for every data change, `__init__.py` present, never deleted once shipped
- [ ] Tests covering the invariants that would cost money if they broke
- [ ] `bench --site … run-tests --app <yours>` passes on a fresh site
- [ ] No secrets in `Data` fields, no credentials in git

---

## 23. Cheat sheet and run-sheet

### 23.1 Commands

```bash
# bench / site
bench init frappe-bench --frappe-branch version-16
bench new-site mysite.local
bench --site mysite.local set-config developer_mode 1
bench --site mysite.local add-to-hosts
bench --site mysite.local enable-scheduler
bench start

# apps
bench get-app apps/library                 # local path, or a git URL
bench --site mysite.local install-app library
bench --site mysite.local uninstall-app library
bench --site mysite.local list-apps

# the daily loop
bench --site mysite.local migrate     # sync doctypes, run patches, after_migrate
bench build --app library                  # rebuild JS/CSS
bench watch                                # rebuild on change
bench --site mysite.local clear-cache
bench restart                              # production / --noreload

# running code
bench --site mysite.local console
bench --site mysite.local execute library.tasks.flag_overdue_loans
bench --site mysite.local run-tests --app library
bench --site mysite.local mariadb

# data
bench --site mysite.local export-fixtures --app library
bench --site mysite.local backup --with-files
bench --site mysite.local restore <path-to-sql.gz>
```

### 23.2 Python API

```python
# read
frappe.get_doc(dt, name)                     # full document, with child tables
frappe.get_cached_doc(dt, name)              # …from cache — settings, masters
frappe.db.get_value(dt, name_or_filters, field_or_list, as_dict=True)
frappe.db.get_single_value(dt, field)        # Single doctype
frappe.db.exists(dt, name_or_filters)
frappe.db.count(dt, filters)
frappe.get_all(dt, filters=…, or_filters=…, fields=…, order_by=…,
               limit_page_length=0, pluck="title", as_list=True)
frappe.get_all(dt, filters=…, fields=[{"SUM": "amount", "as": "total"}])   # aggregates: dict, not "sum(x)"

# write
doc = frappe.new_doc(dt); doc.x = 1; doc.insert(ignore_permissions=True)
doc.save() / doc.submit() / doc.cancel() / doc.delete()
doc.append("child_table", {...})
doc.db_set("field", value)                   # targeted write, skips the lifecycle
frappe.db.set_value(dt, name, field, value)
frappe.db.set_single_value(dt, field, value)
frappe.db.bulk_insert(dt, fields=[...], values=[[...], ...])
frappe.rename_doc(dt, old, new)

# transactions
frappe.db.savepoint("x") / frappe.db.rollback(save_point="x")
frappe.db.commit()                           # console/scripts only, never request code
frappe.get_doc(dt, name, for_update=True)    # SELECT … FOR UPDATE

# context
frappe.session.user, frappe.get_roles(), frappe.only_for([...])
frappe.form_dict, frappe.local.site, frappe.conf.get("key")
frappe.utils.get_url(), frappe.in_test

# feedback / errors
frappe.throw(_("...")), frappe.msgprint(_("..."), indicator="green", alert=True)
frappe.log_error(frappe.get_traceback(), "title")

# async / mail
frappe.enqueue("library.tasks.thing", queue="long", timeout=1500, **kwargs)
frappe.sendmail(recipients=[...], subject=..., message=..., reference_doctype=..., reference_name=...)

# utils you'll reach for hourly
from frappe.utils import (
	today, now_datetime, getdate, add_days, add_months, date_diff,
	cint, flt, cstr, get_url, format_date,
)
```

### 23.3 A 60-minute demo

Each block ends with something visibly working, so nobody takes the payoff on faith.

| # | Min | Block | Ends with |
|---|---|---|---|
| 1 | 0–7 | §1 four words + tour an existing DocType in the desk | Everyone knows what bench/site/app/DocType mean |
| 2 | 7–13 | §3 `bench new-app`, `install-app`, then **read** `hooks.py` together | Their app exists; they've seen the catalogue of hooks |
| 3 | 13–25 | §4 draw `Book` in the UI — then open the JSON it wrote, side by side | The generated file, explained key by key |
| 4 | 25–32 | §5 Member + child + Settings, narrating naming / `istable` / `issingle` | Four tables |
| 5 | 32–43 | §6 `Loan` — submittable, `before_submit`, `on_submit`, `on_cancel` | Issue a book in the desk; the Book flips to On Loan |
| 6 | 43–52 | §8–9 `issue_book` / `return_book`, then curl them | The same operation over HTTP, from outside |
| 7 | 52–60 | §13 the "Issue Book" button, or §14 the public catalogue | A librarian-usable screen, or a public page |

**Set up before you start:** a bench and a site, developer mode on, `bench start` already running,
your editor open at the app directory (with the file tree visible — the point of block 3 is watching
the JSON appear), and a second terminal ready for `bench migrate`.

**The move that sells it:** in block 3, keep the browser and the editor side by side. Add a field in
the form, hit Save, and let them watch `book.json` change on disk. That's the moment developer mode
stops being a setting and starts being the thing that makes Frappe deployable.

**If you have to cut, land these three:**

1. **Schema is the app.** One JSON file bought a table, a form, a list, an API, permissions and an
   audit log — and you drew it in a browser. Time spent on DocType design pays back ten times over;
   time spent typing boilerplate pays back nothing.
2. **Submittable documents are the framework's spine.** Draft → submitted → cancelled, with
   `on_cancel` mirroring `on_submit`, is how every serious Frappe app models things that happened.
3. **Whitelisted is not authorised.** `@frappe.whitelist()` is a public door. The role check on the
   first line is the lock, and it's yours to fit.

---

## Where to next

- **The deep version of this guide** — the same tour against a production app, with the real-world
  edge cases left in: [`frappe-app-from-scratch.md`](frappe-app-from-scratch.md).
- **Official docs** — <https://docs.frappe.io/framework>.
- **Read the framework.** `apps/frappe/frappe/` is a readable codebase, and every DocType JSON in it
  is an example of the file you just learned to write.

---

## 24. Coming from v15

This guide is v16 throughout. If you have a v15 app to port, or v15 habits to unlearn, here's what
actually changed. The framework's shape did not: DocTypes, hooks, controllers, whitelisting, the
query builder and the desk API all work the same.

**Environment**

| | v15 | v16 |
|---|---|---|
| Python | 3.10+ | **3.14**, pinned `>=3.14,<3.15` |
| Node | 18+ | **24+** |
| PDF | wkhtmltopdf | Chrome/Chromium, selectable in Print Settings |

The Python pin is the one that bites: v16 will not install on 3.12 or 3.13, and the failure looks
like an unrelated dependency conflict. Set up 3.14 first.

**Renames you'll hit immediately**

| v15 | v16 |
|---|---|
| `frappe.tests.utils.FrappeTestCase` | `frappe.tests.IntegrationTestCase` / `UnitTestCase` |
| `test_dependencies` | `EXTRA_TEST_RECORD_DEPENDENCIES` |
| `test_ignore` | `IGNORE_TEST_RECORD_DEPENDENCIES` |
| `frappe.flags.in_test` | `frappe.in_test` |
| `has_permission(..., raise_exception=…)` | `print_logs=…` |
| `/app` | `/desk` (`/app` redirects; the `/apps` page is gone) |

**Behaviour changes — these are the dangerous ones**

- **Default sort flipped to `creation desc`.** In v15, list views and the query APIs implicitly
  sorted by `modified`. In v16 `frappe.get_all`, `frappe.get_list`, `frappe.db.get_value`,
  `frappe.db.get_values` and `frappe.qb.get_query` all default to `creation desc`. Anything that
  quietly relied on "most recently touched first" now returns something else. Pass
  `order_by="modified desc"` wherever you meant it.
- **SQL functions as strings are rejected.** `get_all`/`get_list` now run on the query-builder
  backend, so `fields=["sum(fine_amount)"]` raises
  `SQL functions are not allowed as strings in SELECT`. Use
  `fields=[{"SUM": "fine_amount", "as": "total"}]` and read the aliased column. Applies to `COUNT`,
  `AVG`, `MIN`, `MAX` too, and to the `fieldname` argument of `frappe.db.get_value`. This one is
  easy to miss because it only fires on the code path that runs the query.
- **`has_permission` hooks must return `True` explicitly.** Returning `None` no longer grants
  permission. Audit every one — this fails closed and silently.
- **`frappe.db.commit()` is unsupported inside document hooks.** It was always wrong (§9); now it's
  enforced.
- **`frappe.sendmail(..., now=True)` no longer commits** the transaction.
- **`get_doc(doctype, name, field=value)`** no longer sets those values implicitly.
- **`frappe.db.get_value` casts** single-DocType results to real types instead of returning strings.
- **`override_doctype` classes** must now inherit from the class they override.
- **These endpoints require POST**: `logout`, `web_logout`, `upload_file`,
  `frappe.www.login.send_login_link`.

**Moved or removed**

Energy Points, Newsletter, Blog and Backup Integrations are standalone apps now — install them if
you depend on them. GeoIP and the Transaction Log DocType are gone. System Console is
Administrator-only by default. Report / Dashboard Chart / Page JS is evaluated as an IIFE, so
top-level `var` no longer leaks globally.

**Workspaces.** Rebuilt in v16, and **modified standard workspaces are overwritten on migrate** —
back yours up before upgrading. Your own module workspace, shipped as a fixture, is fine.

The official migration guide is the authority, and worth reading in full before porting a live site:
<https://github.com/frappe/frappe/wiki/Migrating-to-version-16>.
