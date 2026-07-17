"""HQ broker endpoints for multi-store partner access.

HQ never stores user tokens. For each store the logged-in user partners in, it
asks that store to mint a token (ghost.api.auth.issue_user_token) using the
service credentials on the store's Coupon Store row, and passes the tokens
straight back to the app.
"""

from concurrent.futures import ThreadPoolExecutor

import frappe
import requests
from frappe import _

_ISSUE_PATH = "/api/method/ghost.api.auth.issue_user_token"
_TIMEOUT = 12


@frappe.whitelist()
def get_my_stores():
	"""Return the stores the logged-in user partners in, each with a freshly
	brokered token for that store.
	"""
	user = frappe.session.user
	if not user or user == "Guest":
		frappe.throw(_("Login required"), frappe.AuthenticationError)

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
		secret = store.get_password("service_secret") if store.service_secret else None
		jobs.append(
			{
				"store": store.name,
				"site_url": (store.site_url or "").rstrip("/"),
				"sales_partner": link.sales_partner,
				"api_key": store.service_api_key,
				"secret": secret,
				"user": user,
			}
		)

	if not jobs:
		return {"stores": []}

	# Fan out to all stores in parallel — one slow store can't hold up the rest.
	with ThreadPoolExecutor(max_workers=min(10, len(jobs))) as pool:
		tokens = list(pool.map(_broker_token, jobs))

	stores = []
	for job, tok in zip(jobs, tokens):
		entry = {
			"store": job["store"],
			"site_url": job["site_url"],
			"sales_partner": job["sales_partner"],
		}
		if tok:
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
			frappe.log_error(
				title="HQ broker: issue_user_token failed",
				message=f"store={job['store']} user={user}",
			)
		stores.append(entry)

	return {"stores": stores}


def _broker_token(job):
	"""HTTP-only. Runs in a worker thread — must NOT call frappe/DB."""
	if not job["api_key"] or not job["secret"]:
		return None
	url = job["site_url"] + _ISSUE_PATH
	headers = {"Authorization": f"token {job['api_key']}:{job['secret']}"}
	try:
		resp = requests.post(url, headers=headers, json={"user": job["user"]}, timeout=_TIMEOUT)
		if resp.status_code != 200:
			return None
		return resp.json().get("message") or None
	except Exception:
		return None
