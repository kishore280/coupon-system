import frappe


def before_uninstall():
	"""Remove the Custom Fields this app injected onto the standard `Item` doctype.

	`bench uninstall-app` only removes records the app owns (its own doctypes, module
	def, module-linked records). These Custom Fields live on `Item` (an ERPNext
	doctype), so they are NOT owned by this app and would otherwise be left behind -
	and `custom_coupon_campaign` (a Link to the now-deleted `Coupon Campaign`) then
	breaks every Item/Stock Entry form with "Missing DocType". Remove them explicitly.
	"""
	item_custom_fields = [
		# current fields (install.py: _item_custom_fields)
		"Item-custom_coupon_tab",
		"Item-custom_coupon_enabled",
		"Item-custom_coupon_campaign",
		# legacy v1 fields (install.py: _LEGACY_ITEM_FIELDS), in case an old site still has them
		"Item-custom_coupon_section",
		"Item-custom_generate_coupons",
		"Item-custom_coupon_points",
		"Item-custom_coupon_validity_months",
		"Item-custom_cards_per_unit",
	]
	for docname in item_custom_fields:
		if frappe.db.exists("Custom Field", docname):
			frappe.delete_doc("Custom Field", docname, ignore_permissions=True, force=True)

	frappe.clear_cache(doctype="Item")
