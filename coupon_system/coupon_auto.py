import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, today


def generate_on_manufacture(doc, method=None):
	"""On submit of a Manufacture Stock Entry, auto-generate coupon cards for any
	finished-goods item flagged with `custom_generate_coupons`.

	One card per produced unit (× cards_per_unit). Only Nos-UOM saleable items
	qualify — bulk Litre intermediates (RM bases) are excluded by design.
	"""
	if doc.purpose != "Manufacture":
		return

	# Aggregate finished qty per item (a single entry may split a finished good
	# across multiple rows). Capture the first batch_no seen per item.
	produced = {}
	batch_of = {}
	for row in doc.items:
		if not row.is_finished_item:
			continue
		produced[row.item_code] = produced.get(row.item_code, 0) + flt(row.qty)
		if row.get("batch_no") and row.item_code not in batch_of:
			batch_of[row.item_code] = row.batch_no

	if not produced:
		return

	from coupon_system.api import _generate_batch

	for item_code, total_qty in produced.items():
		# Idempotency: never double-generate for the same source entry + item
		if frappe.db.exists(
			"Coupon Card", {"source_stock_entry": doc.name, "item_code": item_code}
		):
			continue

		item = frappe.get_cached_doc("Item", item_code)
		if not item.get("custom_generate_coupons"):
			continue
		# Safety filter: only saleable Nos units get cards, never bulk bases
		if (item.stock_uom or "").strip().lower() != "nos":
			continue

		cards_per_unit = cint(item.get("custom_cards_per_unit")) or 1
		qty = int(flt(total_qty)) * cards_per_unit
		if qty <= 0:
			continue

		points = cint(item.get("custom_coupon_points"))
		months = cint(item.get("custom_coupon_validity_months")) or 12
		expiry = add_months(today(), months)

		_generate_batch(
			qty, item_code, points, expiry, "CC-.YYYY.-.#####",
			batch_of.get(item_code, ""), doc.get("work_order") or "",
			source_stock_entry=doc.name,
		)
		frappe.msgprint(
			_("Generated {0} coupon card(s) for {1}").format(qty, item_code),
			indicator="green", alert=True,
		)


def notify_on_manufacture_cancel(doc, method=None):
	"""On cancel of a Manufacture Stock Entry, do NOT auto-delete cards (they may
	already be printed and inserted into physical boxes). Just flag for review.
	"""
	if doc.purpose != "Manufacture":
		return

	count = frappe.db.count("Coupon Card", {"source_stock_entry": doc.name})
	if count:
		frappe.msgprint(
			_("{0} coupon card(s) were generated for this entry. They were NOT "
			  "deleted — review and void manually if these boxes were not produced.").format(count),
			indicator="orange", alert=True,
		)
