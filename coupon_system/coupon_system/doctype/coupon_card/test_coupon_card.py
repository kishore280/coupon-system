import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from coupon_system.api import balance, bulk_generate_cards, generate_cards, redeem, reverse_redeem, scan

_ITEM_CODE = None
_SITE_URL = "https://test.oxifixinframart.com"


def get_item_code():
	global _ITEM_CODE
	if _ITEM_CODE is None:
		_ITEM_CODE = frappe.db.get_value("Item", {"disabled": 0}, "name")
	return _ITEM_CODE


def make_card(code, points_value=100, days_ahead=30, is_used=0, campaign=None, status="Active"):
	frappe.db.delete("Coupon Card", {"code": code})
	doc = frappe.new_doc("Coupon Card")
	doc.code = code
	doc.item_code = get_item_code()
	doc.points_value = points_value
	doc.expiry_date = add_days(today(), days_ahead)
	doc.is_used = is_used
	doc.status = "Redeemed" if is_used else status
	doc.campaign = campaign
	doc.insert(ignore_permissions=True)
	return doc


def cleanup_user(phone):
	frappe.db.delete("Coupon Ledger", {"phone": phone})
	if frappe.db.exists("Coupon User", phone):
		frappe.delete_doc("Coupon User", phone, ignore_permissions=True, force=True)


_TEST_CAMPAIGN = "TEST Plumber 50"


def ensure_test_campaign(points=50, validity_months=12, is_active=1, end_date=None):
	if frappe.db.exists("Coupon Campaign", _TEST_CAMPAIGN):
		frappe.db.set_value("Coupon Campaign", _TEST_CAMPAIGN,
							{"points": points, "validity_months": validity_months,
							 "is_active": is_active, "end_date": end_date})
	else:
		doc = frappe.new_doc("Coupon Campaign")
		doc.campaign_name = _TEST_CAMPAIGN
		doc.points = points
		doc.validity_months = validity_months
		doc.is_active = is_active
		doc.end_date = end_date
		doc.insert(ignore_permissions=True)
	return _TEST_CAMPAIGN


class TestCouponCard(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not get_item_code():
			raise unittest.SkipTest("No Items found on this site — skipping coupon tests")
		cls.campaign = ensure_test_campaign()

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Coupon Card", {"campaign": _TEST_CAMPAIGN})
		if frappe.db.exists("Coupon Campaign", _TEST_CAMPAIGN):
			frappe.delete_doc("Coupon Campaign", _TEST_CAMPAIGN, ignore_permissions=True, force=True)
		super().tearDownClass()

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

	def test_scan_resolves_campaign_value_not_snapshot(self):
		# snapshot says 100, but the campaign says 50 → the LIVE campaign value wins
		ensure_test_campaign(points=50)
		make_card("TEST-DYN-0001", points_value=100, campaign=self.campaign)
		result = scan(self.phone, "TEST-DYN-0001")
		self.assertTrue(result["success"])
		self.assertEqual(result["points_added"], 50)

	def test_change_campaign_value_affects_future_only(self):
		# earn at 50, then the campaign is raised to 75; earned points stay 50
		ensure_test_campaign(points=50)
		make_card("TEST-DYN-0002", campaign=self.campaign)
		first = scan(self.phone, "TEST-DYN-0002")
		self.assertEqual(first["points_added"], 50)

		ensure_test_campaign(points=75)  # change the dial
		make_card("TEST-DYN-0003", campaign=self.campaign)
		second = scan(self.phone, "TEST-DYN-0003")
		self.assertEqual(second["points_added"], 75)        # new scan gets new value
		self.assertEqual(second["new_balance"], 125)        # 50 (frozen) + 75
		ensure_test_campaign(points=50)                      # restore for other tests

	def test_scan_inactive_campaign_rejected(self):
		ensure_test_campaign(points=50, is_active=0)
		make_card("TEST-DYN-0004", campaign=self.campaign)
		result = scan(self.phone, "TEST-DYN-0004")
		self.assertFalse(result["success"])
		self.assertIn("not active", result["error"])
		ensure_test_campaign(points=50, is_active=1)  # restore

	def test_scan_voided_card_rejected(self):
		make_card("TEST-DYN-0005", status="Void")
		result = scan(self.phone, "TEST-DYN-0005")
		self.assertFalse(result["success"])
		self.assertIn("voided", result["error"])

	def test_scan_ended_campaign_rejected(self):
		ensure_test_campaign(points=50, end_date=add_days(today(), -1))
		make_card("TEST-DYN-0006", campaign=self.campaign)
		result = scan(self.phone, "TEST-DYN-0006")
		self.assertFalse(result["success"])
		self.assertIn("ended", result["error"])
		ensure_test_campaign(points=50, end_date=None)  # restore

	def test_setting_past_end_date_retires_cards(self):
		ensure_test_campaign(points=50, end_date=None)
		make_card("TEST-DYN-0007", campaign=self.campaign, status="Active")
		# set a past end date via the doc so on_update propagation fires
		camp = frappe.get_doc("Coupon Campaign", self.campaign)
		camp.end_date = add_days(today(), -1)
		camp.save(ignore_permissions=True)
		self.assertEqual(
			frappe.db.get_value("Coupon Card", {"code": "TEST-DYN-0007"}, "status"),
			"Retired",
		)
		# restore (and the card stays Expired — that's correct, it's retired)
		camp.end_date = None
		camp.save(ignore_permissions=True)

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
		result = redeem(self.phone, 200, _SITE_URL, "SINV-TEST-001")
		self.assertTrue(result["success"])
		self.assertEqual(result["redeemed"], 200)
		self.assertEqual(result["new_balance"], 300)

	def test_redeem_phone_insufficient_balance(self):
		make_card("TEST-AAAA-0005", points_value=100)
		scan(self.phone, "TEST-AAAA-0005")
		result = redeem(self.phone, 500, _SITE_URL, "SINV-TEST-002")
		self.assertFalse(result["success"])
		self.assertIn("Insufficient", result["error"])

	def test_redeem_by_code(self):
		make_card("TEST-AAAA-0006", points_value=300)
		result = redeem(self.phone, 200, _SITE_URL, "SINV-TEST-003", code="TEST-AAAA-0006")
		self.assertTrue(result["success"])
		self.assertEqual(result["redeemed"], 200)
		self.assertEqual(result["new_balance"], 100)

	def test_redeem_duplicate_invoice(self):
		make_card("TEST-AAAA-0007", points_value=500)
		scan(self.phone, "TEST-AAAA-0007")
		redeem(self.phone, 100, _SITE_URL, "SINV-TEST-004")
		result = redeem(self.phone, 100, _SITE_URL, "SINV-TEST-004")
		self.assertFalse(result["success"])
		self.assertIn("Already redeemed", result["error"])

	def test_balance_unknown_phone(self):
		result = balance("+91-0000000000")
		self.assertFalse(result["success"])
		self.assertIn("not found", result["error"])

	def test_balance_success(self):
		make_card("TEST-AAAA-0008", points_value=100)
		scan(self.phone, "TEST-AAAA-0008", full_name="Balance Tester")
		redeem(self.phone, 40, _SITE_URL, "SINV-TEST-005")
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
		result = redeem(self.phone, 100, _SITE_URL, "SINV-TEST-006", code="TEST-AAAA-0009")
		self.assertFalse(result["success"])
		self.assertIn("expired", result["error"])

	def test_redeem_code_already_used_card(self):
		make_card("TEST-AAAA-0010", points_value=200, is_used=1)
		result = redeem(self.phone, 100, _SITE_URL, "SINV-TEST-007", code="TEST-AAAA-0010")
		self.assertFalse(result["success"])
		self.assertIn("already redeemed", result["error"])

	def test_redeem_code_insufficient(self):
		make_card("TEST-AAAA-0011", points_value=50)
		result = redeem(self.phone, 200, _SITE_URL, "SINV-TEST-008", code="TEST-AAAA-0011")
		self.assertFalse(result["success"])
		self.assertIn("Insufficient", result["error"])

	def test_reverse_redeem_restores_balance(self):
		make_card("TEST-AAAA-0012", points_value=500)
		scan(self.phone, "TEST-AAAA-0012")
		redeem(self.phone, 200, _SITE_URL, "SINV-TEST-009")
		result = reverse_redeem("SINV-TEST-009", _SITE_URL)
		self.assertTrue(result["success"])
		self.assertEqual(result["points_restored"], 200)
		self.assertEqual(result["new_balance"], 500)

	def test_reverse_redeem_idempotent(self):
		make_card("TEST-AAAA-0013", points_value=300)
		scan(self.phone, "TEST-AAAA-0013")
		redeem(self.phone, 100, _SITE_URL, "SINV-TEST-010")
		reverse_redeem("SINV-TEST-010", _SITE_URL)
		result = reverse_redeem("SINV-TEST-010", _SITE_URL)
		self.assertFalse(result["success"])
		self.assertIn("already", result["error"].lower())

	def test_reverse_redeem_nonexistent_invoice(self):
		result = reverse_redeem("SINV-DOES-NOT-EXIST", _SITE_URL)
		self.assertFalse(result["success"])
		self.assertIn("redemption found", result["error"].lower())

	def test_generate_cards_count_and_uniqueness(self):
		result = generate_cards(quantity=5, campaign=self.campaign, item_code=get_item_code())
		self.assertTrue(result["success"])
		self.assertEqual(result["count"], 5)
		self.assertEqual(len(set(result["codes"])), 5)
		for code in result["codes"]:
			doc = frappe.get_doc("Coupon Card", {"code": code})
			self.assertEqual(doc.campaign, self.campaign)
			self.assertEqual(doc.status, "Active")
			self.assertEqual(doc.points_value, 50)  # snapshot from campaign
		for code in result["codes"]:
			frappe.db.delete("Coupon Card", {"code": code})

	def test_generate_cards_persists_naming_series(self):
		result = generate_cards(quantity=2, campaign=self.campaign, naming_series="CC-.YYYY.-.#####")
		self.assertTrue(result["success"])
		for code in result["codes"]:
			doc = frappe.get_doc("Coupon Card", {"code": code})
			self.assertEqual(doc.naming_series, "CC-.YYYY.-.#####")
			self.assertTrue(doc.name.startswith("CC-"))
		for code in result["codes"]:
			frappe.db.delete("Coupon Card", {"code": code})

	def test_generate_cards_unknown_campaign_fails(self):
		result = generate_cards(quantity=2, campaign="NO-SUCH-CAMPAIGN")
		self.assertFalse(result["success"])
		self.assertIn("not found", result["error"])

	def test_bulk_generate_cards_multiple_batches(self):
		items = [
			{"campaign": self.campaign, "quantity": 3, "item_code": get_item_code()},
			{"campaign": self.campaign, "quantity": 4, "item_code": get_item_code()},
		]
		result = bulk_generate_cards(items)
		self.assertTrue(result["success"])
		self.assertEqual(result["count"], 7)

		for code in result["codes"]:
			frappe.db.delete("Coupon Card", {"code": code})

	def test_bulk_generate_cards_no_cross_batch_collisions(self):
		"""All codes across all batches must be unique — no intra-call duplicates."""
		items = [
			{"campaign": self.campaign, "quantity": 10},
			{"campaign": self.campaign, "quantity": 10},
			{"campaign": self.campaign, "quantity": 10},
		]
		result = bulk_generate_cards(items)
		self.assertTrue(result["success"])
		self.assertEqual(result["count"], 30)
		self.assertEqual(len(set(result["codes"])), 30, "Duplicate codes found across batches")

		for code in result["codes"]:
			frappe.db.delete("Coupon Card", {"code": code})
