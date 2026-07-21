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


def _sales_invoice_custom_fields():
	# Store-mode POS fields: cashier enters a customer's phone + points to redeem, and/or the
	# code of a coupon handed out. Present on all sites but only acted on in Store mode.
	return {
		"Sales Invoice": [
			{
				"fieldname": "custom_coupon_section",
				"fieldtype": "Section Break",
				"label": "Coupon",
				"insert_after": "customer",
				"collapsible": 1,
			},
			{
				"fieldname": "custom_coupon_redeem_phone",
				"fieldtype": "Data",
				"label": "Coupon Phone (redeem)",
				"insert_after": "custom_coupon_section",
			},
			{
				"fieldname": "custom_coupon_redeem_points",
				"fieldtype": "Int",
				"label": "Points to Redeem",
				"insert_after": "custom_coupon_redeem_phone",
			},
			{
				"fieldname": "custom_coupon_given",
				"fieldtype": "Data",
				"label": "Coupon Given (code)",
				"insert_after": "custom_coupon_redeem_points",
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


_WITHDRAWAL_WORKFLOW = "Coupon Withdrawal Request Approval"


def after_install():
	ensure_custom_fields()
	seed_campaigns()
	_create_mobile_user()
	ensure_withdrawal_workflow()


def after_migrate():
	ensure_custom_fields()
	seed_campaigns()
	ensure_withdrawal_workflow()


def ensure_withdrawal_workflow():
	"""Pending -> Paid / Rejected approval workflow for Coupon Withdrawal Request.
	Idempotent - never overwrites an existing Workflow doc. Reuses the doctype's
	own `status` Select field as workflow_state_field (Workflow only auto-creates a
	field if one by that name doesn't already exist), so no extra hidden field or
	duplicate status tracking is introduced."""
	if not frappe.db.exists("Workflow State", "Paid"):
		frappe.get_doc({"doctype": "Workflow State", "workflow_state_name": "Paid"}).insert(
			ignore_permissions=True)

	if frappe.db.exists("Workflow", _WITHDRAWAL_WORKFLOW):
		return

	workflow = frappe.new_doc("Workflow")
	workflow.workflow_name = _WITHDRAWAL_WORKFLOW
	workflow.document_type = "Coupon Withdrawal Request"
	workflow.workflow_state_field = "status"
	workflow.is_active = 1

	for state in ("Pending", "Paid", "Rejected"):
		workflow.append("states", {"state": state, "doc_status": "0", "allow_edit": "Coupon Manager"})

	# allow_self_approval=1: this is a small-team tool, not a segregation-of-duties
	# control - the same one or two staff members request and approve payouts.
	workflow.append("transitions", {
		"state": "Pending", "action": "Approve", "next_state": "Paid",
		"allowed": "Coupon Manager", "allow_self_approval": 1,
	})
	workflow.append("transitions", {
		"state": "Pending", "action": "Reject", "next_state": "Rejected",
		"allowed": "Coupon Manager", "allow_self_approval": 1,
	})

	workflow.insert(ignore_permissions=True)
	print(f"[coupon_system] Created workflow: {_WITHDRAWAL_WORKFLOW}")


def seed_campaigns():
	"""Create the default campaigns if missing. Never overwrites existing ones. Skipped on a
	store - a store runs its own store-owned campaigns, not the generic HQ defaults."""
	from coupon_system.hq_client import is_store

	if is_store():
		return
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
	create_custom_fields(_sales_invoice_custom_fields(), ignore_validate=True)

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
	from coupon_system.hq_client import is_store

	# The mobile user + its API credentials belong on HQ (the app talks to HQ). Not on a store.
	if is_store():
		return

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
