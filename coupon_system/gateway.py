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


def proxy_balance(store, phone):
	"""Proxy a balance read to a self-contained store and relay its response (for aggregation)."""
	return _proxy(store, "balance", {"phone": phone})


def routable_stores():
	"""All self-contained stores HQ proxies to (route_scans on)."""
	return frappe.get_all(
		"Coupon Store",
		filters={"route_scans": 1, "is_active": 1},
		fields=["name", "site_url", "store_name"],
	)


def _cb_rawkey(store_name):
	# Full, redis-ready breaker key. The store id is a URL, so hash it to a clean token, then
	# run it through make_key for the site prefix.
	digest = hashlib.md5((store_name or "").encode()).hexdigest()
	return frappe.cache().make_key(f"coupon_gw_cb:{digest}")


def _cb_open(store_name):
	"""Is the breaker tripped for this store? Uses the RAW redis client on purpose (see _cb_trip)."""
	return bool(frappe.cache().get(_cb_rawkey(store_name)))


def _cb_trip(store_name):
	"""Trip the breaker for _CB_COOLDOWN seconds.

	Deliberately uses the raw redis client (setex/get) rather than frappe.cache().set_value/
	get_value: the wrapper keeps a per-request in-process cache layer that DESYNCS from redis right
	after a failed outbound `requests` call — so a value written here via set_value is invisible to
	a get_value in the same call, and the breaker would silently never engage. The raw client always
	hits redis, so it's correct in-process (tests, console) and in a web request alike.
	"""
	frappe.cache().setex(_cb_rawkey(store_name), _CB_COOLDOWN, "1")


def _proxy(store, endpoint, payload):
	# Circuit breaker: if this store just failed, fail fast instead of hanging every scan on a
	# dead upstream (Azure Gateway Routing risk: gateway in the data path — bulkhead each store).
	if _cb_open(store.name):
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
		_cb_trip(store.name)
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
