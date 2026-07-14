import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime


class TestCouponLedger(FrappeTestCase):
	def test_phone_is_required(self):
		entry = frappe.new_doc("Coupon Ledger")
		entry.type = "CREDIT"
		entry.points = 100
		entry.timestamp = now_datetime()
		self.assertRaises(frappe.exceptions.MandatoryError, entry.insert)

	def test_valid_entry_persists(self):
		phone = "+91-0000000001"
		if not frappe.db.exists("Coupon User", phone):
			frappe.get_doc({"doctype": "Coupon User", "phone": phone}).insert(ignore_permissions=True)
		entry = frappe.new_doc("Coupon Ledger")
		entry.phone = phone
		entry.type = "CREDIT"
		entry.points = 50
		entry.timestamp = now_datetime()
		entry.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Coupon Ledger", entry.name))
		frappe.db.delete("Coupon Ledger", {"name": entry.name})
		frappe.delete_doc("Coupon User", phone, ignore_permissions=True, force=True)

	def test_points_is_required(self):
		phone = "+91-0000000000"
		if not frappe.db.exists("Coupon User", phone):
			frappe.get_doc({"doctype": "Coupon User", "phone": phone}).insert(ignore_permissions=True)
		entry = frappe.new_doc("Coupon Ledger")
		entry.phone = phone
		entry.type = "CREDIT"
		entry.timestamp = now_datetime()
		self.assertRaises(frappe.exceptions.MandatoryError, entry.insert)
		frappe.delete_doc("Coupon User", phone, ignore_permissions=True, force=True)
