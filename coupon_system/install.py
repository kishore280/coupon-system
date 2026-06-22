import frappe
import secrets

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# Our coupon config lives in its own Item tab. The tab break is anchored to the
# form's current last field (computed at runtime) so it always lands at the very
# end — never splitting an ERPNext section and never depending on a specific
# ERPNext version's field layout.
_OWN_FIELDS = (
	"custom_coupon_tab",
	"custom_generate_coupons",
	"custom_coupon_points",
	"custom_coupon_validity_months",
	"custom_cards_per_unit",
)


def _item_custom_fields(anchor):
	return {
		"Item": [
			{
				"fieldname": "custom_coupon_tab",
				"fieldtype": "Tab Break",
				"label": "Coupon Cards",
				"insert_after": anchor,
			},
			{
				"fieldname": "custom_generate_coupons",
				"fieldtype": "Check",
				"label": "Generate Coupon Cards on Manufacture",
				"insert_after": "custom_coupon_tab",
				"description": "Auto-create cards when this item is produced via a Manufacture Stock Entry (Nos items only).",
			},
			{
				"fieldname": "custom_coupon_points",
				"fieldtype": "Int",
				"label": "Coupon Points per Card",
				"insert_after": "custom_generate_coupons",
				"depends_on": "custom_generate_coupons",
				"mandatory_depends_on": "custom_generate_coupons",
			},
			{
				"fieldname": "custom_coupon_validity_months",
				"fieldtype": "Int",
				"label": "Coupon Validity (Months)",
				"default": "12",
				"insert_after": "custom_coupon_points",
				"depends_on": "custom_generate_coupons",
			},
			{
				"fieldname": "custom_cards_per_unit",
				"fieldtype": "Int",
				"label": "Cards per Unit",
				"default": "1",
				"insert_after": "custom_coupon_validity_months",
				"depends_on": "custom_generate_coupons",
			},
		]
	}


def after_install():
	ensure_custom_fields()
	_create_mobile_user()


def after_migrate():
	ensure_custom_fields()


def ensure_custom_fields():
	# Remove the old mid-form section break that absorbed standard Inventory fields.
	if frappe.db.exists("Custom Field", "Item-custom_coupon_section"):
		frappe.delete_doc("Custom Field", "Item-custom_coupon_section", ignore_permissions=True)

	# Anchor the tab at the form's last field, ignoring our own fields so re-runs
	# don't chain onto themselves.
	anchor = None
	for field in reversed(frappe.get_meta("Item").fields):
		if field.fieldname not in _OWN_FIELDS:
			anchor = field.fieldname
			break

	create_custom_fields(_item_custom_fields(anchor), ignore_validate=True)


def _create_mobile_user():
	email = "coupon-mobile@system.local"

	if frappe.db.exists("User", email):
		print(f"[coupon_system] Mobile user {email} already exists — skipping")
		return

	user = frappe.new_doc("User")
	user.email = email
	user.first_name = "Coupon Mobile"
	user.user_type = "System User"
	user.send_welcome_email = 0
	user.enabled = 1
	user.new_password = secrets.token_urlsafe(24)
	user.append("roles", {"role": "Coupon Mobile"})
	user.insert(ignore_permissions=True)

	# Generate API key/secret
	api_key = secrets.token_hex(16)
	api_secret = secrets.token_hex(16)
	user.api_key = api_key
	user.api_secret = api_secret
	user.save(ignore_permissions=True)
	frappe.db.commit()

	print("\n" + "=" * 60)
	print("[coupon_system] Mobile App Credentials")
	print(f"  API Key    : {api_key}")
	print(f"  API Secret : {api_secret}")
	print("  Paste these into HQ Integration Settings → Mobile App Credentials")
	print("=" * 60 + "\n")
