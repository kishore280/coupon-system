import frappe
from frappe import _


def execute(filters=None):
	filters = filters or {}

	conditions = []
	values = {}
	if filters.get("campaign"):
		conditions.append("campaign = %(campaign)s")
		values["campaign"] = filters["campaign"]
	if filters.get("item_code"):
		conditions.append("item_code = %(item_code)s")
		values["item_code"] = filters["item_code"]
	if filters.get("work_order"):
		conditions.append("work_order = %(work_order)s")
		values["work_order"] = filters["work_order"]

	where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

	# One row per campaign × item, with a count column per lifecycle state.
	rows = frappe.db.sql(
		f"""
		SELECT
			campaign,
			item_code,
			SUM(status = 'Generated') AS generated,
			SUM(status = 'Active')    AS active,
			SUM(status = 'Redeemed')  AS redeemed,
			SUM(status = 'Expired')   AS expired,
			SUM(status = 'Void')      AS void,
			COUNT(*)                  AS total
		FROM `tabCoupon Card`
		{where}
		GROUP BY campaign, item_code
		ORDER BY campaign, item_code
		""",
		values,
		as_dict=True,
	)

	columns = [
		{"label": _("Campaign"), "fieldname": "campaign", "fieldtype": "Link", "options": "Coupon Campaign", "width": 150},
		{"label": _("Item"), "fieldname": "item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Generated"), "fieldname": "generated", "fieldtype": "Int", "width": 100},
		{"label": _("Active"), "fieldname": "active", "fieldtype": "Int", "width": 90},
		{"label": _("Redeemed"), "fieldname": "redeemed", "fieldtype": "Int", "width": 100},
		{"label": _("Expired"), "fieldname": "expired", "fieldtype": "Int", "width": 90},
		{"label": _("Void"), "fieldname": "void", "fieldtype": "Int", "width": 80},
		{"label": _("Total"), "fieldname": "total", "fieldtype": "Int", "width": 90},
	]

	return columns, rows
