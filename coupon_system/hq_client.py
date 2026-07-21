"""Store-mode → HQ client.

A store site owns its campaigns and immutable card definitions locally, but holds **no**
points ledger — every earn/redeem is a call to HQ over HTTP (service creds). This is the thin
side of ADR-0001/0002/0003: the store is a writer into HQ's single ledger, never an owner.
"""

import json

import frappe
from frappe import _
from frappe.utils import cint

_TIMEOUT = 15


def is_store():
	return (frappe.db.get_single_value("Coupon System Settings", "site_role") or "HQ") == "Store"


def _conf():
	s = frappe.get_cached_doc("Coupon System Settings")
	base = (s.hq_base_url or "").rstrip("/")
	key = s.hq_api_key
	secret = s.get_password("hq_api_secret", raise_exception=False)
	store_id = s.hq_store_id
	if not (base and key and secret and store_id):
		frappe.throw(_("Store mode is not configured (need HQ base URL, API key, secret, and store id)"))
	return base, key, secret, store_id


def store_id():
	return _conf()[3]


def call_hq(method, **params):
	"""POST to an HQ whitelisted coupon_system.api.<method> and return its `message` dict.

	Uses Frappe's auto-retrying request session. Raises only on transport/HTTP failure - a
	business-level {success: False} is RETURNED, not raised, because some are non-errors the
	caller must interpret (e.g. an idempotent "already redeemed" on a POS retry)."""
	base, key, secret, _sid = _conf()
	url = f"{base}/api/method/coupon_system.api.{method}"
	session = frappe.get_request_session()
	try:
		resp = session.post(
			url, headers={"Authorization": f"token {key}:{secret}"}, data=params, timeout=_TIMEOUT
		)
		resp.raise_for_status()
	except Exception as e:
		frappe.throw(_("Could not reach HQ ({0}): {1}").format(method, e))
	try:
		return resp.json().get("message") or {}
	except ValueError:
		frappe.throw(_("HQ returned a non-JSON response (status {0})").format(resp.status_code))


def hq_register_cards(cards):
	return call_hq("register_cards", store=store_id(), cards=json.dumps(cards))


def hq_redeem(phone, amount, invoice_no):
	return call_hq("redeem", phone=phone, amount=amount, site_url=store_id(), invoice_no=invoice_no)


def hq_reverse(invoice_no):
	return call_hq("reverse_redeem", invoice_no=invoice_no, site_url=store_id())


def hq_mark_given(code, invoice_no):
	return call_hq("mark_given", code=code, invoice_no=invoice_no)


def hq_stock():
	return call_hq("store_card_counts", store=store_id())


@frappe.whitelist()
def store_mint(quantity, campaign):
	"""Mint coupons locally (this store's immutable defs, namespaced code) and register the
	definitions to HQ so a scan resolves there. Store mode only."""
	from coupon_system.api import _campaign_snapshot, _generate_batch

	if not is_store():
		frappe.throw(_("store_mint runs only on a Store-mode site"))

	sid = store_id()
	# Guard: the local Coupon Store + namespace must exist, or _generate_batch would emit
	# UN-namespaced codes (collision risk) and a dangling card.store link.
	ns = frappe.db.get_value("Coupon Store", sid, "code_namespace")
	if not ns:
		frappe.throw(_("Local Coupon Store {0} with a code_namespace must exist before minting").format(sid))

	pts, expiry = _campaign_snapshot(campaign)
	# Deliberate order: write local rows (uncommitted) -> register to HQ -> commit. So a store
	# never hands out a coupon HQ doesn't know about; if HQ fails, the local rows roll back.
	res = _generate_batch(
		int(quantity), "", pts, expiry, "CC-.YYYY.-.#####", "", "",
		campaign=campaign, origin="Store", store=sid,
	)
	cards = [{"code": c, "points_value": pts, "expiry_date": str(expiry)} for c in res["codes"]]

	reg = hq_register_cards(cards)
	if not reg.get("success"):
		frappe.throw(_("HQ registration failed: {0}").format(reg.get("error") or "unknown"))
	frappe.db.commit()
	return {"success": True, "codes": res["codes"], "registered_to": sid}


@frappe.whitelist()
def store_redeem(phone, amount, invoice_no):
	"""Spend a customer's points at this store, against an invoice — debits HQ's ledger
	(store-locked first, then general). Store mode only."""
	if not is_store():
		frappe.throw(_("store_redeem runs only on a Store-mode site"))
	return hq_redeem(phone, cint(amount), invoice_no)
