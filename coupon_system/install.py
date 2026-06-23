import frappe
import secrets

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


# Our coupon config lives in its own Item tab. The tab break is anchored to the
# form's current last field (computed at runtime) so it always lands at the very
# end — never splitting an ERPNext section and never depending on a specific
# ERPNext version's field layout.
_OWN_FIELDS = (
	"custom_coupon_tab",
	"custom_coupon_enabled",
	"custom_coupon_campaign",
)

# v1 flag-based fields, superseded by the campaign link — removed on migrate.
_LEGACY_ITEM_FIELDS = (
	"custom_coupon_section",
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
				"fieldname": "custom_coupon_enabled",
				"fieldtype": "Check",
				"label": "Coupon Generation Enabled",
				"default": "0",
				"insert_after": "custom_coupon_tab",
				"description": "Off by default — a normal item is not a coupon. Check this only on a coupon (blank-card) item, then pick its campaign. Uncheck later to pause generation without losing the campaign mapping.",
			},
			{
				"fieldname": "custom_coupon_campaign",
				"fieldtype": "Link",
				"label": "Coupon Campaign",
				"options": "Coupon Campaign",
				"insert_after": "custom_coupon_enabled",
				"depends_on": "custom_coupon_enabled",
				"mandatory_depends_on": "custom_coupon_enabled",
				"description": "If set, this item is a coupon component. When a Work Order whose BOM includes this item is submitted, that many cards of this campaign are generated for the finished good.",
			},
		]
	}


# Default campaigns seeded on install (idempotent). audience is set only when the
# matching Customer Group already exists — otherwise left blank (it is label-only).
_DEFAULT_CAMPAIGNS = [
	{"campaign_name": "Plumber 5", "audience": "Plumber", "points": 5},
	{"campaign_name": "Plumber 10", "audience": "Plumber", "points": 10},
	{"campaign_name": "Painter 10", "audience": "Painter", "points": 10},
	{"campaign_name": "Painter 20", "audience": "Painter", "points": 20},
]


def after_install():
	ensure_custom_fields()
	seed_campaigns()
	_create_mobile_user()


def after_migrate():
	ensure_custom_fields()
	seed_campaigns()


def seed_campaigns():
	"""Create the default campaigns if missing. Never overwrites existing ones."""
	for c in _DEFAULT_CAMPAIGNS:
		if frappe.db.exists("Coupon Campaign", c["campaign_name"]):
			continue
		doc = frappe.new_doc("Coupon Campaign")
		doc.campaign_name = c["campaign_name"]
		doc.points = c["points"]
		doc.validity_months = 12
		doc.is_active = 1
		if frappe.db.exists("Customer Group", c["audience"]):
			doc.audience = c["audience"]
		doc.insert(ignore_permissions=True)
		print(f"[coupon_system] Seeded campaign: {c['campaign_name']}")


def ensure_custom_fields():
	# Drop superseded v1 flag fields (value now lives on the campaign).
	for fieldname in _LEGACY_ITEM_FIELDS:
		docname = f"Item-{fieldname}"
		if frappe.db.exists("Custom Field", docname):
			frappe.delete_doc("Custom Field", docname, ignore_permissions=True)

	# Anchor the tab at the form's last field, ignoring our own fields so re-runs
	# don't chain onto themselves.
	anchor = None
	for field in reversed(frappe.get_meta("Item").fields):
		if field.fieldname not in _OWN_FIELDS:
			anchor = field.fieldname
			break

	create_custom_fields(_item_custom_fields(anchor), ignore_validate=True)

	# Existing coupon items predate the enable switch — default them to enabled
	# (only touches NULLs, never overrides an explicit disable).
	frappe.db.sql(
		"""
		UPDATE `tabItem` SET custom_coupon_enabled = 1
		WHERE custom_coupon_enabled IS NULL
		  AND custom_coupon_campaign IS NOT NULL AND custom_coupon_campaign != ''
		"""
	)


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
