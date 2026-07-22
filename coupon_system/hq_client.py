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


def _site_role():
	# A site_config override (`coupon_site_role`) lets an admin declare the role BEFORE the app is
	# installed, so after_install skips HQ-only seeding. Falls back to the setting once it exists.
	return (
		frappe.conf.get("coupon_site_role")
		or frappe.db.get_single_value("Coupon System Settings", "site_role")
		or "HQ"
	)


def is_store():
	"""HQ-backed store (Mode A): thin, registers to HQ, local ledger is guarded off."""
	return _site_role() == "Store"


def is_self_contained():
	"""Standalone store (Mode B): its own local ledger, no central HQ - everything local."""
	return _site_role() == "Standalone Store"


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

	roles = frappe.get_roles()
	if "System Manager" not in roles and "Coupon Manager" not in roles:
		frappe.throw(_("Not permitted"))
	if is_self_contained():
		# Self-contained store: mint locally (no HQ round-trip). If this store has a local
		# Coupon Store with a code_namespace, mint NAMESPACED, store-tagged codes so an HQ
		# gateway can route a scan here by the code's namespace (single-call proxy) and the
		# points lock to this store. With no namespace it stays a plain local wallet.
		from coupon_system.api import generate_cards

		sid = store_id()
		ns = frappe.db.get_value("Coupon Store", sid, "code_namespace") if sid else None
		if sid and ns:
			return generate_cards(quantity, campaign, origin="Store", store=sid)
		return generate_cards(quantity, campaign)
	if not is_store():
		frappe.throw(_("store_mint runs only on a store site"))

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


