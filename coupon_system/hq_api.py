"""HQ broker endpoints for multi-store partner access.

HQ never stores user tokens. For each store the logged-in user partners in, it
asks that store to mint a token (ghost.api.auth.issue_user_token) using the
service credentials on the store's Coupon Store row, and passes the tokens
straight back to the app.

HQ also carries no Sales Partner id: the store already knows who the user is
from the brokered token, so the app resolves the partner from the user's email
on each store (the same way the single-store app always did). Storing it here
would just be a denormalized copy that drifts out of sync.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import partial

import frappe
from frappe import _
from frappe.model import child_table_fields, default_fields, optional_fields
from frappe.utils import get_request_session, now

_ISSUE_PATH = "/api/method/ghost.api.auth.issue_user_token"
_APPLY_PATH = (
	"/api/method/oxifix_multisite_sync.api.sales_partner_application"
	".apply_sales_partner"
)
_UPLOAD_PATH = "/api/method/upload_file"
_TIMEOUT = 10
_MAX_RETRIES = 2

# Private Attach Image fields — copied by moving the file bytes, not the URL.
_IMAGE_FIELDS = ("custom_kyc_pan_image", "custom_kyc_aadhaar_image")

# What NOT to forward when cloning the HQ Sales Partner. Everything else is
# copied verbatim — an exact copy, not an allow-list. We drop only:
#   - Frappe's own managed columns (framework constants, not guessed),
#   - workflow_state + custom_kyc_status — the store's own review state. enroll
#     puts custom_kyc_status back as "Submitted" (HQ's is "Approved", which would
#     skip the store's review); workflow_state the branch sets to Pending,
#   - the KYC images (moved as file bytes, not their HQ URLs).
_SKIP_FIELDS = (
	frozenset(default_fields)
	| frozenset(optional_fields)
	| frozenset(child_table_fields)
	| frozenset(_IMAGE_FIELDS)
	| {"workflow_state", "custom_kyc_status"}
)


@frappe.whitelist()
def get_my_stores():
	"""Return the stores the logged-in user partners in, each with a freshly
	brokered token for that store.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Login required"), frappe.AuthenticationError)

	# Phone-first: a user with no mobile number must not be brokered onto any
	# store (a phoneless account must never be provisioned). Stop here, at HQ,
	# before touching any store.
	mobile_no = frappe.db.get_value("User", user, "mobile_no")
	if not mobile_no:
		frappe.throw(_("Add your mobile number to access your stores."))

	links = frappe.get_all(
		"Partner Store Link",
		filters={"user": user, "status": "Active"},
		fields=["store"],
	)

	# Gather everything that needs DB access here, on the main thread. The worker
	# threads below do HTTP only — never touch frappe/DB (not thread-safe).
	jobs = []
	for link in links:
		store = frappe.get_doc("Coupon Store", link.store)
		if not store.is_active:
			continue
		secret = store.get_password("service_secret", raise_exception=False)
		jobs.append(
			{
				"store": store.name,
				"store_name": store.store_name,
				"site_url": (store.site_url or "").rstrip("/"),
				"api_key": store.service_api_key,
				"secret": secret,
				"user": user,
				"mobile_no": mobile_no,
			}
		)

	if not jobs:
		return {"stores": []}

	# One retrying session (thread-safe) shared across the workers — auto-retries
	# transient failures (connection errors / HTTP 500) before giving up.
	session = get_request_session(max_retries=_MAX_RETRIES)

	# Fan out to all stores in parallel — one slow store can't hold up the rest.
	with ThreadPoolExecutor(max_workers=min(10, len(jobs))) as pool:
		results = list(pool.map(partial(_broker_token, session=session), jobs))

	stores = []
	for job, result in zip(jobs, results):
		entry = {
			"store": job["store"],
			"store_name": job["store_name"],
			"site_url": job["site_url"],
		}
		if result.get("ok"):
			tok = result["tokens"]
			entry.update(
				{
					"access_token": tok.get("access_token"),
					"refresh_token": tok.get("refresh_token"),
					"expires_in": tok.get("expires_in"),
					"token_type": tok.get("token_type", "Bearer"),
				}
			)
		else:
			entry["error"] = "unavailable"
			# Log the real reason neatly to the Error Log doctype (workers don't
			# touch the DB, so we log here on the main thread).
			frappe.log_error(
				title=f"HQ broker failed: {job['store']}"[:140],
				message=(
					f"User: {user}\n"
					f"Store: {job['store']} ({job['site_url']})\n"
					f"Reason: {result.get('error')}"
				),
			)
		stores.append(entry)

	return {"stores": stores}


def _broker_token(job, session):
	"""HTTP-only. Runs in a worker thread — must NOT call frappe/DB.

	Returns {"ok": True, "tokens": {...}} or {"ok": False, "error": "<reason>"};
	the main thread logs the reason to the Error Log.
	"""
	if not job["api_key"] or not job["secret"]:
		return {"ok": False, "error": "missing service credentials on Coupon Store"}
	url = job["site_url"] + _ISSUE_PATH
	headers = {"Authorization": f"token {job['api_key']}:{job['secret']}"}
	try:
		resp = session.post(
			url,
			headers=headers,
			json={"user": job["user"], "mobile_no": job["mobile_no"]},
			timeout=_TIMEOUT,
		)
		if resp.status_code != 200:
			return {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}
		tokens = resp.json().get("message")
		if not tokens:
			return {"ok": False, "error": "no token in store response"}
		return {"ok": True, "tokens": tokens}
	except Exception as exc:
		return {"ok": False, "error": str(exc)[:200]}


# --- Enrollment --------------------------------------------------------------
#
# HQ is the master: a partner's Sales Partner + KYC live here. Enrolling into a
# store clones that master onto the store in a pending state, over the store's
# OWN apply endpoint (so the store sees a normal user application it can approve
# or reject). HQ keeps only an access index (Partner Store Link); the approval
# ladder lives entirely on the branch, exactly where the app already reads it.


@frappe.whitelist()
def get_available_stores():
	"""Active stores the logged-in user has NOT enrolled in yet — the app's
	"apply" list. Excludes stores they're already linked to (those show up through
	get_my_stores) and stores that aren't broker-ready: without service
	credentials we could never mint a token to enroll, so offering an Apply that's
	guaranteed to fail would just be a dead button.
	"""
	user = _require_user()

	linked = {
		link.store
		for link in frappe.get_all(
			"Partner Store Link", filters={"user": user}, fields=["store"]
		)
	}
	# Broker-readiness is a query filter, not a post-loop: both credentials are
	# real columns on the row. A Password field keeps a dummy "*****" in its
	# column when set (the secret itself lives in __Auth), so `is set` correctly
	# tells configured from empty — no per-store get_doc needed.
	stores = frappe.get_all(
		"Coupon Store",
		filters={
			"is_active": 1,
			"service_api_key": ["is", "set"],
			"service_secret": ["is", "set"],
		},
		fields=["name", "store_name", "site_url"],
	)
	return {
		"stores": [
			{
				"store": s.name,
				"store_name": s.store_name,
				"site_url": (s.site_url or "").rstrip("/"),
			}
			for s in stores
			if s.name not in linked
		]
	}


@frappe.whitelist()
def enroll(store):
	"""Enroll the logged-in user into `store`: clone their HQ Sales Partner + KYC
	onto the store as a pending application, then record the access link.
	"""
	user = _require_user()

	mobile_no = frappe.db.get_value("User", user, "mobile_no")
	if not mobile_no:
		frappe.throw(_("Add your mobile number before enrolling."))

	# Idempotency guard for retries / double-taps. A link may already exist; we
	# don't early-return, because the branch's apply_sales_partner is itself
	# idempotent (returns the existing partner instead of duplicating), so
	# re-running is safe — we just avoid inserting a second link. Rejection is
	# terminal on both sides (no reapply path), so this never resurrects a
	# rejected partner or resets an approved one.
	existing = frappe.db.exists("Partner Store Link", {"user": user, "store": store})

	store_doc = frappe.get_doc("Coupon Store", store)
	if not store_doc.is_active:
		frappe.throw(_("This store isn't accepting partners right now."))

	# The HQ master we clone from. No HQ Sales Partner means there's nothing to
	# copy — HQ apply + KYC are the hard first gates, done before any enrollment.
	hq_partner = _hq_partner(user)
	if not hq_partner:
		frappe.throw(_("Finish your Sales Partner application first."))
	master = frappe.get_doc("Sales Partner", hq_partner)

	fields = _master_payload(master)
	# Ship the KYC in for the store to review — the docs are cloned below, so it's
	# Submitted, not HQ's Approved (which would skip the store's own review).
	fields["custom_kyc_status"] = "Submitted"

	session = get_request_session(max_retries=_MAX_RETRIES)
	site_url = (store_doc.site_url or "").rstrip("/")

	# Same broker the fan-out uses — mint a token so we act AS the user on the
	# branch (its apply endpoint resolves the applicant from the session).
	result = _broker_token(
		{
			"api_key": store_doc.service_api_key,
			"secret": store_doc.get_password("service_secret", raise_exception=False),
			"site_url": site_url,
			"user": user,
			"mobile_no": mobile_no,
		},
		session,
	)
	token = (result.get("tokens") or {}).get("access_token") if result.get("ok") else None
	if not token:
		_fail("issue_user_token", store, result.get("error", "no token"))

	# Create the branch Sales Partner in submitted/pending state via the branch's
	# own apply endpoint — the store approves or rejects it like any application.
	branch_partner = _branch_apply(session, site_url, token, fields)

	# Move the KYC images — every one must land. Any failure throws HERE, before
	# the link is written, so the enrollment is all-or-nothing: HQ records
	# nothing, the store never appears half-provisioned, and retry starts clean.
	for field in _IMAGE_FIELDS:
		file_url = master.get(field)
		if file_url:
			_clone_file(session, site_url, token, branch_partner, field, file_url)

	# Everything landed → record the access link (Active) so get_my_stores brokers
	# a token and the app shows the store as pending → approved. Reapply (link
	# already exists) keeps the same link.
	if not existing:
		frappe.get_doc(
			{
				"doctype": "Partner Store Link",
				"user": user,
				"store": store,
				"status": "Active",
				"enrolled_on": now(),
			}
		).insert(ignore_permissions=True)
		frappe.db.commit()

	return {"ok": True, "store": store}


def _require_user():
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Login required"), frappe.AuthenticationError)
	return user


def _hq_partner(user):
	"""The user's HQ Sales Partner docname via Contact → Dynamic Link, or None."""
	rows = frappe.db.sql(
		"""
		select dl.link_name
		from `tabDynamic Link` dl
		join `tabContact` c on c.name = dl.parent
		where c.user = %s and dl.link_doctype = 'Sales Partner'
		limit 1
		""",
		user,
	)
	return rows[0][0] if rows else None


def _master_payload(master):
	"""An exact copy of the HQ Sales Partner — every field forwarded verbatim,
	minus [_SKIP_FIELDS]. Not an allow-list: any new field on the doctype rides
	along automatically. `None`/`_*` scratch keys are dropped.
	"""
	return {
		key: value
		for key, value in master.as_dict().items()
		if key not in _SKIP_FIELDS and not key.startswith("_") and value is not None
	}


def _branch_apply(session, site_url, token, fields):
	"""Submit the cloned Sales Partner on the branch; return its docname."""
	resp = session.post(
		site_url + _APPLY_PATH,
		headers={"Authorization": f"Bearer {token}"},
		json=fields,
		timeout=_TIMEOUT,
	)
	if resp.status_code != 200:
		_fail("apply_sales_partner", site_url, f"HTTP {resp.status_code}: {resp.text[:500]}")
	msg = (resp.json() or {}).get("message") or {}
	partner = msg.get("partner") or msg.get("name")
	if not partner:
		frappe.throw(_("The store didn't confirm the application. Try again."))
	return partner


def _clone_file(session, site_url, token, docname, fieldname, file_url):
	"""Move one HQ private file onto the branch and attach it to `fieldname`."""
	blob = _hq_file_bytes(file_url)
	if not blob:
		return
	filename, content = blob
	resp = session.post(
		site_url + _UPLOAD_PATH,
		headers={"Authorization": f"Bearer {token}"},
		files={"file": (filename, content)},
		data={
			"doctype": "Sales Partner",
			"docname": docname,
			"fieldname": fieldname,
			"is_private": 1,
		},
		timeout=_TIMEOUT,
	)
	if resp.status_code != 200:
		_fail(f"upload {fieldname}", site_url, f"HTTP {resp.status_code}: {resp.text[:500]}")


def _hq_file_bytes(file_url):
	"""(filename, bytes) for an HQ file_url, or None if the file is missing."""
	name = frappe.db.get_value("File", {"file_url": file_url}, "name")
	if not name:
		return None
	doc = frappe.get_doc("File", name)
	return (doc.file_name or "kyc"), doc.get_content()


def _fail(what, where, detail):
	"""Log the real reason to the Error Log, surface a clean message to the app."""
	frappe.log_error(
		title=f"Enroll failed: {what}"[:140],
		message=f"Store: {where}\n{detail}",
	)
	frappe.throw(_("Enrollment couldn't be completed. Please try again."))
