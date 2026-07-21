"""Store-mode → HQ client.

A store site owns its campaigns and immutable card definitions locally, but holds **no**
points ledger — every earn/redeem is a call to HQ over HTTP (service creds). This is the thin
side of ADR-0001/0002/0003: the store is a writer into HQ's single ledger, never an owner.
"""

import json

import frappe
from frappe import _
from frappe.utils import get_request_session, get_url

_TIMEOUT = 15


def is_store():
	# A site_config override (`coupon_site_role`) lets an admin declare Store mode BEFORE the app
	# is installed, so after_install skips HQ-only seeding (default campaigns, mobile user).
	# Falls back to the setting once the doctype exists.
	role = (
		frappe.conf.get("coupon_site_role")
		or frappe.db.get_single_value("Coupon System Settings", "site_role")
		or "HQ"
	)
	return role == "Store"


def _conf():
	# Reuse the sync app's HQ connection (the SAME creds the branch redemption already uses)
	# rather than a second, drift-prone config. This store's identity on HQ is its own URL.
	if not frappe.db.exists("DocType", "HQ Integration Settings"):
		frappe.throw(_("Store mode requires the oxifix_multisite_sync app "
					   "(HQ Integration Settings) installed on this site."))
	s = frappe.get_cached_doc("HQ Integration Settings")
	base = (s.hq_url or "").rstrip("/")
	key = s.api_key
	secret = s.api_secret  # a Data field on HQ Integration Settings - read plainly, as the sync does
	store_id = get_url()
	if not (base and key and secret):
		frappe.throw(_("HQ Integration Settings not configured (need hq_url, api_key, api_secret)"))
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
	session = get_request_session()
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


@frappe.whitelist()
def store_mint(quantity, campaign):
	"""Mint coupons for this store: generate namespaced codes, register the immutable defs to
	HQ, then write the store's local copy and commit. Store mode only.

	Order matters. Codes are generated first (read-only), HQ is called with NO local write
	transaction open (so no row lock is held across the network round-trip), and only on HQ
	success are the local rows written + committed - so a store never hands out a coupon HQ
	doesn't know about.
	"""
	from coupon_system.api import _campaign_snapshot, _insert_cards, _store_prefix, _unique_codes

	if not is_store():
		frappe.throw(_("store_mint runs only on a Store-mode site"))

	sid = store_id()
	# Guard: the local Coupon Store + namespace must exist, or codes would be UN-namespaced
	# (collision risk) and card.store would dangle.
	ns = frappe.db.get_value("Coupon Store", sid, "code_namespace")
	if not ns:
		frappe.throw(_("Local Coupon Store {0} with a code_namespace must exist before minting").format(sid))

	pts, expiry = _campaign_snapshot(campaign)
	codes = _unique_codes(int(quantity), code_prefix=_store_prefix(sid))
	cards = [{"code": c, "points_value": pts, "expiry_date": str(expiry)} for c in codes]

	reg = hq_register_cards(cards)
	if not reg.get("success"):
		frappe.throw(_("HQ registration failed: {0}").format(reg.get("error") or "unknown"))

	_insert_cards(codes, "", pts, expiry, "CC-.YYYY.-.#####", "", "",
				  campaign=campaign, origin="Store", store=sid)
	frappe.db.commit()
	return {"success": True, "codes": codes, "registered_to": sid}


