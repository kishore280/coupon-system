import frappe

no_cache = 1


def get_context(context):
	code = frappe.form_dict.get("code") or ""
	if not code:
		frappe.throw("Invalid link", frappe.NotFound)

	context.code = code
	context.play_store_url = frappe.db.get_single_value("Coupon System Settings", "play_store_url") or "#"
	context.app_store_url = frappe.db.get_single_value("Coupon System Settings", "app_store_url") or "#"
	context.no_breadcrumbs = True
	context.title = "Open in App"
