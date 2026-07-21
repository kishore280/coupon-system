"""Store-mode Sales Invoice hooks — the POS trigger for redeeming points at the store.

Gated by is_store(): on HQ these are no-ops. A slow/failed HQ blocks the submit rather than
handing out a discount without debiting points (HQ is assumed reachable — ADR-0001).
"""

import frappe
from frappe import _
from frappe.utils import cint


def on_sales_invoice_submit(doc, method=None):
	from coupon_system.hq_client import hq_mark_given, hq_redeem, is_store

	if not is_store():
		return

	# Redeem points, if the cashier entered a phone + points.
	phone = (doc.get("custom_coupon_redeem_phone") or "").strip()
	points = cint(doc.get("custom_coupon_redeem_points"))
	if phone and points > 0:
		res = hq_redeem(phone, points, doc.name)
		# A submit RETRY hits idempotency - matched on a stable machine `reason`, not text.
		if not res.get("success") and res.get("reason") != "already_redeemed":
			frappe.log_error(str(res), "coupon store redeem failed")
			frappe.throw(_("Coupon redemption failed at HQ: {0}").format(res.get("error") or "unknown"))

	# Record which coupon was handed out with this invoice (traceability only - never block).
	given = (doc.get("custom_coupon_given") or "").strip()
	if given:
		try:
			hq_mark_given(given, doc.name)
		except Exception:
			frappe.log_error(frappe.get_traceback(), "coupon mark_given failed")


def on_sales_invoice_cancel(doc, method=None):
	from coupon_system.hq_client import hq_reverse, is_store

	if not is_store():
		return

	# Only relevant if this invoice actually redeemed points.
	if not (doc.get("custom_coupon_redeem_phone") and cint(doc.get("custom_coupon_redeem_points")) > 0):
		return

	res = hq_reverse(doc.name)
	# Nothing-to-reverse / already-reversed must NEVER block the cancellation.
	if not res.get("success") and res.get("reason") not in ("no_redemption", "already_reversed"):
		frappe.log_error(str(res), "coupon store reverse failed")
		frappe.throw(_("Coupon reversal failed at HQ: {0}").format(res.get("error") or "unknown"))
