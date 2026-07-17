"""HQ broker endpoints for multi-store partner access.

HQ never stores user tokens. For each store the logged-in user partners in, it
asks that store to mint a token (ghost.api.auth.issue_user_token) using the
service credentials on the store's Coupon Store row, and passes the tokens
straight back to the app.
"""

from concurrent.futures import ThreadPoolExecutor
from functools import partial

import frappe
from frappe import _
from frappe.utils import get_request_session

_ISSUE_PATH = "/api/method/ghost.api.auth.issue_user_token"
_TIMEOUT = 10
_MAX_RETRIES = 2


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
		fields=["store", "sales_partner"],
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
				"site_url": (store.site_url or "").rstrip("/"),
				"sales_partner": link.sales_partner,
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
			"site_url": job["site_url"],
			"sales_partner": job["sales_partner"],
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
