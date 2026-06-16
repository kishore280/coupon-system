import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from coupon_system.api import balance, generate_cards, redeem, scan

_ITEM_CODE = None


def get_item_code():
	global _ITEM_CODE
	if _ITEM_CODE is None:
		_ITEM_CODE = frappe.db.get_value("Item", {"disabled": 0}, "name")
	return _ITEM_CODE


def make_card(code, points_value=100, days_ahead=30, is_used=0):
	frappe.db.delete("Coupon Card", {"code": code})
	doc = frappe.new_doc("Coupon Card")
	doc.code = code
	doc.item_code = get_item_code()
	doc.points_value = points_value
	doc.expiry_date = add_days(today(), days_ahead)
	doc.is_used = is_used
	doc.insert(ignore_permissions=True)
	return doc


def cleanup_user(phone):
	frappe.db.delete("Coupon Ledger", {"phone": phone})
	if frappe.db.exists("Coupon User", phone):
		frappe.delete_doc("Coupon User", phone, ignore_permissions=True, force=True)


class TestCouponCard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not get_item_code():
			raise unittest.SkipTest("No Items found on this site — skipping coupon tests")

	def setUp(self):
		self.phone = "+91-9999000001"
		cleanup_user(self.phone)

	def tearDown(self):
		cleanup_user(self.phone)
		frappe.db.delete("Coupon Card", {"code": ["like", "TEST-%"]})

	def test_scan_valid_card(self):
		make_card("TEST-AAAA-0001", points_value=50)
		result = scan(self.phone, "TEST-AAAA-0001", full_name="Test User")
		self.assertTrue(result["success"])
		self.assertEqual(result["points_added"], 50)
		self.assertEqual(result["new_balance"], 50)

	def test_scan_already_used_card(self):
		make_card("TEST-AAAA-0002", is_used=1)
		result = scan(self.phone, "TEST-AAAA-0002")
		self.assertFalse(result["success"])
		self.assertIn("already redeemed", result["error"])

	def test_scan_expired_card(self):
		make_card("TEST-AAAA-0003", days_ahead=-1)
		result = scan(self.phone, "TEST-AAAA-0003")
		self.assertFalse(result["success"])
		self.assertIn("expired", result["error"])

	def test_scan_nonexistent_card(self):
		result = scan(self.phone, "TEST-DOESNOTEXIST")
		self.assertFalse(result["success"])
		self.assertIn("not found", result["error"])

	def test_redeem_phone_sufficient_balance(self):
		make_card("TEST-AAAA-0004", points_value=500)
		scan(self.phone, "TEST-AAAA-0004")
		result = redeem(self.phone, 200, "Branch A", "SINV-TEST-001")
		self.assertTrue(result["success"])
		self.assertEqual(result["redeemed"], 200)
		self.assertEqual(result["new_balance"], 300)

	def test_redeem_phone_insufficient_balance(self):
		make_card("TEST-AAAA-0005", points_value=100)
		scan(self.phone, "TEST-AAAA-0005")
		result = redeem(self.phone, 500, "Branch A", "SINV-TEST-002")
		self.assertFalse(result["success"])
		self.assertIn("Insufficient", result["error"])

	def test_redeem_by_code(self):
		make_card("TEST-AAAA-0006", points_value=300)
		result = redeem(self.phone, 200, "Branch A", "SINV-TEST-003", code="TEST-AAAA-0006")
		self.assertTrue(result["success"])
		self.assertEqual(result["redeemed"], 200)
		self.assertEqual(result["new_balance"], 100)

	def test_redeem_duplicate_invoice(self):
		make_card("TEST-AAAA-0007", points_value=500)
		scan(self.phone, "TEST-AAAA-0007")
		redeem(self.phone, 100, "Branch A", "SINV-TEST-004")
		result = redeem(self.phone, 100, "Branch A", "SINV-TEST-004")
		self.assertFalse(result["success"])
		self.assertIn("Already redeemed", result["error"])

	def test_balance_unknown_phone(self):
		result = balance("+91-0000000000")
		self.assertFalse(result["success"])
		self.assertIn("not found", result["error"])

	def test_balance_success(self):
		make_card("TEST-AAAA-0008", points_value=100)
		scan(self.phone, "TEST-AAAA-0008", full_name="Balance Tester")
		redeem(self.phone, 40, "Branch A", "SINV-TEST-005")
		result = balance(self.phone)
		self.assertTrue(result["success"])
		self.assertEqual(result["phone"], self.phone)
		self.assertEqual(result["full_name"], "Balance Tester")
		self.assertEqual(result["points_balance"], 60)
		self.assertEqual(len(result["ledger"]), 2)
		types = {e["type"] for e in result["ledger"]}
		self.assertIn("CREDIT", types)
		self.assertIn("DEBIT", types)

	def test_redeem_code_expired_card(self):
		make_card("TEST-AAAA-0009", points_value=200, days_ahead=-1)
		result = redeem(self.phone, 100, "Branch A", "SINV-TEST-006", code="TEST-AAAA-0009")
		self.assertFalse(result["success"])
		self.assertIn("expired", result["error"])

	def test_redeem_code_already_used_card(self):
		make_card("TEST-AAAA-0010", points_value=200, is_used=1)
		result = redeem(self.phone, 100, "Branch A", "SINV-TEST-007", code="TEST-AAAA-0010")
		self.assertFalse(result["success"])
		self.assertIn("already redeemed", result["error"])

	def test_redeem_code_insufficient(self):
		make_card("TEST-AAAA-0011", points_value=50)
		result = redeem(self.phone, 200, "Branch A", "SINV-TEST-008", code="TEST-AAAA-0011")
		self.assertFalse(result["success"])
		self.assertIn("Insufficient", result["error"])

	def test_generate_cards_count_and_uniqueness(self):
		result = generate_cards(
			quantity=5,
			item_code=get_item_code(),
			points_value=50,
			expiry_date=add_days(today(), 365),
		)
		self.assertTrue(result["success"])
		self.assertEqual(result["count"], 5)
		self.assertEqual(len(set(result["codes"])), 5)
		for code in result["codes"]:
			self.assertTrue(frappe.db.exists("Coupon Card", {"code": code}))
		for code in result["codes"]:
			frappe.db.delete("Coupon Card", {"code": code})
