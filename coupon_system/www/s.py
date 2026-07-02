import frappe

no_cache = 1


def get_context(context):
	# No code (e.g. bare /s/ — used by Play Console App Links validation) must
	# still return HTTP 200, so render the generic "Open in App" landing page.
	code = frappe.form_dict.get("code") or ""

	context.code = code
	context.play_store_url = frappe.db.get_single_value("Coupon System Settings", "play_store_url") or "#"
	context.app_store_url = frappe.db.get_single_value("Coupon System Settings", "app_store_url") or "#"
	context.no_breadcrumbs = True
	context.title = "Open in App"
