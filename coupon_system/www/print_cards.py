import json

import frappe


def get_context(context):
	frappe.only_for("System Manager")
	context.no_cache = 1
	context.full_width = 1

	raw_filters = json.loads(frappe.form_dict.get("filters", "[]"))

	filters = {}
	for f in raw_filters:
		if len(f) == 4:
			field, op, value = f[1], f[2], f[3]
			if op == "=":
				filters[field] = value
			elif op == "in":
				filters[field] = ["in", value]

	cards = frappe.get_all(
		"Coupon Card",
		filters=filters,
		fields=["name", "code", "points_value", "expiry_date", "item_code"],
		order_by="creation asc",
		limit_page_length=0,
	)

	if not cards:
		frappe.throw("No cards found for the selected filters.")

	context.cards = cards
	context.total = len(cards)
