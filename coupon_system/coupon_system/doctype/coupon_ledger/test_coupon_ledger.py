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
		entry = frappe.new_doc("Coupon Ledger")
		entry.phone = "+91-0000000001"
		entry.type = "CREDIT"
		entry.points = 50
		entry.timestamp = now_datetime()
		entry.insert(ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Coupon Ledger", entry.name))
		frappe.db.delete("Coupon Ledger", {"name": entry.name})

	def test_points_is_required(self):
		entry = frappe.new_doc("Coupon Ledger")
		entry.phone = "+91-0000000000"
		entry.type = "CREDIT"
		entry.timestamp = now_datetime()
		self.assertRaises(frappe.exceptions.MandatoryError, entry.insert)
