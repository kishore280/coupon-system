"""HQ scan gateway — route a scan by the code's namespace (API Gateway + Gateway Routing +
Gateway Offloading).

When a scanned code isn't a card HQ holds (HQ-backed stores register their cards here, so those
resolve locally), the code may belong to a **self-contained** store whose coupons live only on that
store. HQ then proxies the scan server-to-server to the owning store using the service creds it
already holds on the `Coupon Store` row, and relays the result — so the mobile client makes exactly
ONE call to HQ and never learns the store exists.

Only stores flagged `route_scans` are proxied to (self-contained ones). HQ-backed stores are never
proxied — their cards are on HQ and resolve locally.
"""

import hashlib

import frappe
from frappe import _
from frappe.utils import get_request_session
from frappe.utils.password import get_decrypted_password

_TIMEOUT = 10
_CB_COOLDOWN = 30  # seconds a store stays "tripped" after a failure (lightweight circuit breaker)


def route_store_for_code(code):
	"""The routable (self-contained) store whose code_namespace appears in `code`, or None.

	A code looks like `[BRAND-]<NS>-XXXX-YYYY`; the namespace is one hyphen-delimited segment.
	"""
	segments = [s for s in (code or "").split("-") if s]
	if not segments:
		return None
	return frappe.db.get_value(
		"Coupon Store",
		{"code_namespace": ["in", segments], "route_scans": 1, "is_active": 1},
		["name", "site_url", "code_namespace"],
		as_dict=True,
	)


def proxy_scan(store, phone, code, full_name=None):
	"""Proxy a scan to a self-contained store and relay its response."""
	return _proxy(store, "scan", {"phone": phone, "code": code, "full_name": full_name or ""})


def _cb_key(store_name):
	# The store id is a URL (contains `://` and `:port`). Frappe's redis cache mishandles keys
	# with those characters — get_value returns None even though the key is set — so the breaker
	# would silently never engage. Hash the id to a clean, safe token.
	digest = hashlib.md5((store_name or "").encode()).hexdigest()
	return f"coupon_gw_cb:{digest}"


def _proxy(store, endpoint, payload):
	# Circuit breaker: if this store just failed, fail fast instead of hanging every scan on a
	# dead upstream (Azure Gateway Routing risk: gateway in the data path — bulkhead each store).
	if frappe.cache().get_value(_cb_key(store.name)):
		return {"success": False, "reason": "store_unavailable",
				"error": _("Store is temporarily unavailable, please retry")}

	key = frappe.db.get_value("Coupon Store", store.name, "service_api_key")
	secret = get_decrypted_password(
		"Coupon Store", store.name, "service_secret", raise_exception=False
	)
	if not (store.site_url and key and secret):
		return {"success": False, "reason": "store_misconfigured",
				"error": _("Store {0} has no routing credentials").format(store.name)}

	url = f"{store.site_url.rstrip('/')}/api/method/coupon_system.api.{endpoint}"
	# NO transport-level retries: a proxied scan is a non-idempotent write (credits points, marks
	# the card used). If the connection drops after the store commits, an auto-retry could either
	# double-credit or surface a false "already used" to the client. So we make exactly one attempt
	# and let the circuit breaker + the client's own retry handle genuinely-transient failures.
	session = get_request_session(max_retries=0)
	try:
		r = session.post(
			url, headers={"Authorization": f"token {key}:{secret}"}, data=payload, timeout=_TIMEOUT
		)
		r.raise_for_status()
	except Exception as e:
		frappe.cache().set_value(_cb_key(store.name), "1", expires_in_sec=_CB_COOLDOWN)
		# title has a hard length cap; the (long) upstream error must go in `message`, and logging
		# itself must never break the proxy — so keep the title short and swallow any log failure.
		try:
			frappe.log_error(message=f"{store.name}: {e}", title="Coupon gateway proxy failed")
		except Exception:
			pass
		return {"success": False, "reason": "store_unreachable",
				"error": _("Could not reach the store, please retry")}

	try:
		return r.json().get("message") or {}
	except ValueError:
		return {"success": False, "reason": "bad_response",
				"error": _("Store returned an invalid response")}
