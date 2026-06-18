import frappe
from frappe.utils import now_datetime
import secrets


def after_install():
	_create_mobile_user()


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
