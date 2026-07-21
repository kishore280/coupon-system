"""Store-mode Sales Invoice hooks — the POS trigger for redeeming points at the store.

Gated by is_store(): on HQ these are no-ops. A slow/failed HQ blocks the submit rather than
handing out a discount without debiting points (HQ is assumed reachable — ADR-0001).
"""

import frappe
from frappe import _
from frappe.utils import cint


def on_sales_invoice_submit(doc, method=None):
	from coupon_system.hq_client import hq_redeem, is_store

	if not is_store():
		return

	phone = (doc.get("custom_coupon_redeem_phone") or "").strip()
	points = cint(doc.get("custom_coupon_redeem_points"))
	if not phone or points <= 0:
		return

	try:
		hq_redeem(phone, points, doc.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "coupon store redeem failed")
		frappe.throw(_("Coupon redemption failed at HQ — invoice not submitted."))


def on_sales_invoice_cancel(doc, method=None):
	from coupon_system.hq_client import hq_reverse, is_store

	if not is_store():
		return

	# Only reverse if this invoice actually redeemed points.
	if not (doc.get("custom_coupon_redeem_phone") and cint(doc.get("custom_coupon_redeem_points")) > 0):
		return

	try:
		hq_reverse(doc.name)
	except Exception:
		frappe.log_error(frappe.get_traceback(), "coupon store reverse failed")
		frappe.throw(_("Coupon reversal failed at HQ — invoice not cancelled."))
