import frappe
from frappe import _
from frappe.utils import cint, flt


def generate_on_work_order(doc, method=None):
	"""Option B (print-at-line): when a Work Order is submitted, generate uniquely
	coded cards for any coupon component in its BOM, so the crew can print + insert
	them during packing.

	A "coupon component" is any required item whose Item.custom_coupon_campaign is
	set. Cards-per-unit = the BOM line qty (already folded into required_qty).
	Cards are stamped with the finished good (production_item) for traceability.
	Idempotent on work_order + campaign.
	"""
	from coupon_system.api import _generate_batch, _campaign_snapshot

	for req in (doc.get("required_items") or []):
		campaign = frappe.db.get_value("Item", req.item_code, "custom_coupon_campaign")
		if not campaign:
			continue

		# required_qty = (coupon qty per unit in BOM) × WO qty  → one card each
		qty = int(flt(req.required_qty))
		if qty <= 0:
			continue

		# Idempotency: never double-generate for the same WO + campaign
		if frappe.db.exists(
			"Coupon Card", {"work_order": doc.name, "campaign": campaign}
		):
			continue

		try:
			points, expiry = _campaign_snapshot(campaign)
		except frappe.ValidationError:
			# Inactive/misconfigured campaign — skip silently, surface a comment
			frappe.msgprint(
				_("Coupon campaign {0} is inactive or misconfigured — no cards generated for {1}").format(
					campaign, req.item_code
				),
				indicator="orange", alert=True,
			)
			continue

		_generate_batch(
			qty, doc.production_item or "", points, expiry, "CC-.YYYY.-.#####",
			"", doc.name, campaign=campaign, status="Active",
		)
		frappe.msgprint(
			_("Generated {0} '{1}' coupon card(s) — ready to print").format(qty, campaign),
			indicator="green", alert=True,
		)


def expire_cards():
	"""Daily sweep: move Active cards past their expiry date to Expired.
	Redeemed/Void cards are untouched — only live stock expires.
	"""
	from frappe.utils import today

	frappe.db.sql(
		"""
		UPDATE `tabCoupon Card`
		SET status = 'Expired'
		WHERE status = 'Active' AND is_used = 0 AND expiry_date < %s
		""",
		today(),
	)


def void_on_work_order_cancel(doc, method=None):
	"""On Work Order cancel, void its generated cards (they were never printed/used).
	Already-redeemed cards are left intact — voiding only affects unused stock.
	"""
	cards = frappe.get_all(
		"Coupon Card",
		filters={"work_order": doc.name, "status": ["in", ["Active", "Generated"]], "is_used": 0},
		pluck="name",
	)
	for name in cards:
		frappe.db.set_value("Coupon Card", name, "status", "Void", update_modified=False)

	if cards:
		frappe.msgprint(
			_("{0} unused coupon card(s) for this Work Order were voided.").format(len(cards)),
			indicator="orange", alert=True,
		)
