import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from coupon_system.api import scan

_ITEM_CODE = None


def get_item_code():
	global _ITEM_CODE
	if _ITEM_CODE is None:
		_ITEM_CODE = frappe.db.get_value("Item", {"disabled": 0}, "name")
	return _ITEM_CODE


class TestCouponUser(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not get_item_code():
			raise unittest.SkipTest("No Items found on this site — skipping coupon user tests")

	def setUp(self):
		self.phone = "+91-9000000099"
		frappe.db.delete("Coupon Ledger", {"phone": self.phone})
		if frappe.db.exists("Coupon User", self.phone):
			frappe.delete_doc("Coupon User", self.phone, ignore_permissions=True, force=True)
		frappe.db.delete("Coupon Card", {"code": ["like", "UTEST-%"]})

	def tearDown(self):
		frappe.db.delete("Coupon Ledger", {"phone": self.phone})
		if frappe.db.exists("Coupon User", self.phone):
			frappe.delete_doc("Coupon User", self.phone, ignore_permissions=True, force=True)
		frappe.db.delete("Coupon Card", {"code": ["like", "UTEST-%"]})

	def _make_card(self, code, points_value=100, days_ahead=30):
		doc = frappe.new_doc("Coupon Card")
		doc.code = code
		doc.item_code = get_item_code()
		doc.points_value = points_value
		doc.expiry_date = add_days(today(), days_ahead)
		doc.insert(ignore_permissions=True)
		return doc

	def test_onload_zero_balance_for_new_user(self):
		user = frappe.new_doc("Coupon User")
		user.phone = self.phone
		user.full_name = "Test"
		user.insert(ignore_permissions=True)
		user.onload()
		self.assertEqual(user.get_onload("points_balance"), 0.0)

	def test_onload_reflects_scan_credits(self):
		self._make_card("UTEST-0001", points_value=75)
		scan(self.phone, "UTEST-0001", full_name="Test User")

		user = frappe.get_doc("Coupon User", self.phone)
		user.onload()
		self.assertEqual(user.get_onload("points_balance"), 75.0)
