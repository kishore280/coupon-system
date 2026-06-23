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

	Card generation is decoupled from the Work Order itself: a coupon-side failure
	is logged and surfaced as a warning but never blocks/rolls back the WO submit —
	production must not halt over a coupon side effect. Missing cards can be minted
	later from the campaign's "Generate Cards" button.
	"""
	# Amendment re-fires on_submit on a NEW doc (WO-x → WO-x-1). The original run's
	# cards already exist (and the amend's cancel voids the originals), so generating
	# again would double the batch for the same physical run. Skip amendments.
	if doc.get("amended_from"):
		return

	rows = doc.get("required_items") or []
	if not rows:
		return

	# One query for all coupon components on this WO (instead of per-row lookups on
	# every site-wide Work Order submit).
	item_codes = list({r.item_code for r in rows if r.item_code})
	if not item_codes:
		return
	coupon_items = {
		i.name: i
		for i in frappe.get_all(
			"Item",
			filters={"name": ["in", item_codes], "custom_coupon_campaign": ["is", "set"]},
			fields=["name", "custom_coupon_campaign", "custom_coupon_enabled"],
		)
	}
	if not coupon_items:
		return

	from coupon_system.api import _generate_batch, _campaign_snapshot

	# Aggregate required_qty per (campaign) in case the same coupon item appears twice.
	seen_campaigns = set()
	for req in rows:
		item = coupon_items.get(req.item_code)
		if not item:
			continue
		# Master switch: NULL (never set) is treated as enabled; only an explicit 0 pauses.
		if item.custom_coupon_enabled is not None and not cint(item.custom_coupon_enabled):
			continue
		campaign = item.custom_coupon_campaign
		if campaign in seen_campaigns:
			continue

		# round, don't truncate — float qty like 9.9999 must not lose a card
		qty = int(round(flt(req.required_qty)))
		if qty <= 0:
			continue

		# Idempotency: never double-generate for the same WO + campaign
		if frappe.db.exists("Coupon Card", {"work_order": doc.name, "campaign": campaign}):
			seen_campaigns.add(campaign)
			continue

		frappe.db.savepoint("coupon_gen")
		try:
			points, expiry = _campaign_snapshot(campaign)
			_generate_batch(
				qty, doc.production_item or "", points, expiry, "CC-.YYYY.-.#####",
				"", doc.name, campaign=campaign, status="Active",
			)
			seen_campaigns.add(campaign)
			frappe.msgprint(
				_("Generated {0} '{1}' coupon card(s) — ready to print").format(qty, campaign),
				indicator="green", alert=True,
			)
		except Exception:
			# Never let a coupon error roll back the Work Order — undo only our own
			# partial work and carry on.
			frappe.db.rollback(save_point="coupon_gen")
			frappe.log_error(frappe.get_traceback(), f"Coupon generation failed for WO {doc.name}")
			frappe.msgprint(
				_("Could not generate '{0}' coupon cards for this Work Order — generate them "
				  "manually from the campaign. (Production was not affected.)").format(campaign),
				indicator="orange", alert=True,
			)


def expire_cards():
	"""Daily sweep: retire unused cards that are past their own expiry date, OR
	whose campaign has reached its end_date. Redeemed/Void cards are untouched.
	"""
	from frappe.utils import today

	t = today()

	# 1. Cards past their own expiry date
	frappe.db.sql(
		"""
		UPDATE `tabCoupon Card`
		SET status = 'Expired'
		WHERE status IN ('Active', 'Generated') AND is_used = 0 AND expiry_date < %s
		""",
		t,
	)

	# 2. Cards whose campaign has ended → Retired (distinct from own-date Expired)
	frappe.db.sql(
		"""
		UPDATE `tabCoupon Card` cc
		JOIN `tabCoupon Campaign` camp ON camp.name = cc.campaign
		SET cc.status = 'Retired'
		WHERE cc.status IN ('Active', 'Generated') AND cc.is_used = 0
		  AND camp.end_date IS NOT NULL AND camp.end_date < %s
		""",
		t,
	)


def void_on_work_order_cancel(doc, method=None):
	"""On Work Order cancel, void its unused generated cards in one statement.
	Already-redeemed cards are left intact — voiding only affects unused stock.
	"""
	count = frappe.db.count(
		"Coupon Card",
		{"work_order": doc.name, "status": ["in", ["Active", "Generated"]], "is_used": 0},
	)
	if not count:
		return

	frappe.db.sql(
		"""
		UPDATE `tabCoupon Card`
		SET status = 'Void'
		WHERE work_order = %s AND is_used = 0 AND status IN ('Active', 'Generated')
		""",
		doc.name,
	)
	frappe.msgprint(
		_("{0} unused coupon card(s) for this Work Order were voided.").format(count),
		indicator="orange", alert=True,
	)
