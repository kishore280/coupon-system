"""Store-mode → HQ client.

A store site owns its campaigns and immutable card definitions locally, but holds **no**
points ledger — every earn/redeem is a call to HQ over HTTP (service creds). This is the thin
side of ADR-0001/0002/0003: the store is a writer into HQ's single ledger, never an owner.
"""

import json

import frappe
from frappe import _

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
	"""POST to an HQ whitelisted coupon_system.api.<method>. Returns the `message` payload.
	Raises on transport error or a business-level {success: False}."""
	import requests

	base, key, secret, _sid = _conf()
	url = f"{base}/api/method/coupon_system.api.{method}"
	headers = {"Authorization": f"token {key}:{secret}"}
	resp = requests.post(url, headers=headers, data=params, timeout=_TIMEOUT)
	resp.raise_for_status()
	msg = resp.json().get("message", {})
	if isinstance(msg, dict) and msg.get("success") is False:
		frappe.throw(_("HQ: {0}").format(msg.get("error") or "call failed"))
	return msg


def hq_register_cards(cards):
	return call_hq("register_cards", store=store_id(), cards=json.dumps(cards))


def hq_redeem(phone, amount, invoice_no):
	return call_hq("redeem", phone=phone, amount=amount, site_url=store_id(), invoice_no=invoice_no)


def hq_reverse(invoice_no):
	return call_hq("reverse_redeem", invoice_no=invoice_no, site_url=store_id())


@frappe.whitelist()
def store_mint(quantity, campaign):
	"""Mint coupons locally (this store's immutable defs, namespaced code) and register the
	definitions to HQ so a scan resolves there. Store mode only."""
	from coupon_system.api import _campaign_snapshot, _generate_batch

	if not is_store():
		frappe.throw(_("store_mint runs only on a Store-mode site"))

	sid = store_id()
	pts, expiry = _campaign_snapshot(campaign)
	res = _generate_batch(
		int(quantity), "", pts, expiry, "CC-.YYYY.-.#####", "", "",
		campaign=campaign, origin="Store", store=sid,
	)
	cards = [{"code": c, "points_value": pts, "expiry_date": str(expiry)} for c in res["codes"]]
	hq_register_cards(cards)
	frappe.db.commit()
	return {"success": True, "codes": res["codes"], "registered_to": sid}


@frappe.whitelist()
def store_redeem(phone, amount, invoice_no):
	"""Spend a customer's points at this store, against an invoice — debits HQ's ledger
	(store-locked first, then general). Store mode only."""
	if not is_store():
		frappe.throw(_("store_redeem runs only on a Store-mode site"))
	return hq_redeem(phone, cint_amount(amount), invoice_no)


def cint_amount(amount):
	from frappe.utils import cint

	return cint(amount)
