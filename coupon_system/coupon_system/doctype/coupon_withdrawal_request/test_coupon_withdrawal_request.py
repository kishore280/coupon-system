import frappe
from frappe.tests.utils import FrappeTestCase

from coupon_system.api import _get_available_balance, request_withdrawal, scan
from coupon_system.coupon_system.doctype.coupon_card.test_coupon_card import cleanup_user, make_card


def set_withdrawal_settings(enable=1, rate=1):
	frappe.db.set_single_value("Coupon System Settings", "enable_withdrawals", enable)
	frappe.db.set_single_value("Coupon System Settings", "points_to_currency_rate", rate)


class TestCouponWithdrawalRequest(FrappeTestCase):
	def setUp(self):
		self.phone = "+91-9999000002"
		cleanup_user(self.phone)
		settings = frappe.get_single("Coupon System Settings")
		self._orig_enable = settings.enable_withdrawals
		self._orig_rate = settings.points_to_currency_rate
		set_withdrawal_settings(enable=1, rate=1)

	def tearDown(self):
		cleanup_user(self.phone)
		frappe.db.delete("Coupon Withdrawal Request", {"phone": self.phone})
		frappe.db.delete("Coupon Card", {"code": ["like", "TEST-WD-%"]})
		set_withdrawal_settings(enable=self._orig_enable, rate=self._orig_rate or 1)

	def test_request_withdrawal_disabled_by_default(self):
		set_withdrawal_settings(enable=0)
		make_card("TEST-WD-0001", points_value=100)
		scan(self.phone, "TEST-WD-0001")
		result = request_withdrawal(self.phone, 50, "upi:test@bank")
		self.assertFalse(result["success"])
		self.assertIn("disabled", result["error"].lower())

	def test_request_withdrawal_success(self):
		make_card("TEST-WD-0002", points_value=100)
		scan(self.phone, "TEST-WD-0002")
		result = request_withdrawal(self.phone, 40, "upi:test@bank")
		self.assertTrue(result["success"])
		self.assertEqual(result["amount"], 40)
		self.assertEqual(result["available_balance"], 60)
		req = frappe.get_doc("Coupon Withdrawal Request", result["request"])
		self.assertEqual(req.status, "Pending")
		self.assertEqual(req.points, 40)

	def test_request_withdrawal_insufficient_balance(self):
		make_card("TEST-WD-0003", points_value=20)
		scan(self.phone, "TEST-WD-0003")
		result = request_withdrawal(self.phone, 50, "upi:test@bank")
		self.assertFalse(result["success"])
		self.assertIn("Insufficient", result["error"])

	def test_pending_request_locks_points_from_a_second_request(self):
		make_card("TEST-WD-0004", points_value=100)
		scan(self.phone, "TEST-WD-0004")
		first = request_withdrawal(self.phone, 70, "upi:test@bank")
		self.assertTrue(first["success"])
		# only 30 left available (100 - 70 locked), asking for 50 must fail
		second = request_withdrawal(self.phone, 50, "upi:test@bank")
		self.assertFalse(second["success"])
		self.assertIn("Insufficient", second["error"])

	def test_mark_paid_writes_single_ledger_debit(self):
		make_card("TEST-WD-0005", points_value=100)
		scan(self.phone, "TEST-WD-0005")
		result = request_withdrawal(self.phone, 40, "upi:test@bank")
		req = frappe.get_doc("Coupon Withdrawal Request", result["request"])
		req.status = "Paid"
		req.save(ignore_permissions=True)

		debits = frappe.get_all("Coupon Ledger", filters={"phone": self.phone, "type": "DEBIT"})
		self.assertEqual(len(debits), 1)
		self.assertEqual(_get_available_balance(self.phone), 60)

		req.reload()
		self.assertEqual(req.status, "Paid")
		self.assertIsNotNone(req.paid_on)

	def test_mark_rejected_has_no_ledger_effect_and_unlocks_points(self):
		make_card("TEST-WD-0006", points_value=100)
		scan(self.phone, "TEST-WD-0006")
		result = request_withdrawal(self.phone, 40, "upi:test@bank")
		req = frappe.get_doc("Coupon Withdrawal Request", result["request"])
		req.status = "Rejected"
		req.rejection_reason = "test rejection"
		req.save(ignore_permissions=True)

		debits = frappe.get_all("Coupon Ledger", filters={"phone": self.phone, "type": "DEBIT"})
		self.assertEqual(len(debits), 0)
		# the 40 points are no longer locked - full 100 available again
		self.assertEqual(_get_available_balance(self.phone), 100)

	def test_cannot_change_status_of_a_non_pending_request(self):
		make_card("TEST-WD-0007", points_value=100)
		scan(self.phone, "TEST-WD-0007")
		result = request_withdrawal(self.phone, 40, "upi:test@bank")
		req = frappe.get_doc("Coupon Withdrawal Request", result["request"])
		req.status = "Paid"
		req.save(ignore_permissions=True)

		req.reload()
		req.status = "Rejected"
		self.assertRaises(frappe.ValidationError, req.save, ignore_permissions=True)

	def test_amount_snapshotted_not_recomputed_on_later_save(self):
		make_card("TEST-WD-0008", points_value=100)
		scan(self.phone, "TEST-WD-0008")
		result = request_withdrawal(self.phone, 40, "upi:test@bank")
		self.assertEqual(result["amount"], 40)  # rate=1 at request time

		set_withdrawal_settings(enable=1, rate=5)  # change the dial after the fact
		req = frappe.get_doc("Coupon Withdrawal Request", result["request"])
		req.payout_details = "upi:updated@bank"  # any unrelated re-save
		req.save(ignore_permissions=True)

		req.reload()
		self.assertEqual(req.amount, 40)  # unchanged - never recomputed

	def test_request_withdrawal_permission_denied_without_role(self):
		test_user = "test-coupon-no-role@example.com"
		if not frappe.db.exists("User", test_user):
			frappe.get_doc({
				"doctype": "User", "email": test_user, "first_name": "Test No Role",
				"send_welcome_email": 0, "roles": [],
			}).insert(ignore_permissions=True)
		make_card("TEST-WD-0009", points_value=100)
		scan(self.phone, "TEST-WD-0009")
		with self.set_user(test_user):
			result = request_withdrawal(self.phone, 40, "upi:test@bank")
		self.assertFalse(result["success"])
		self.assertIn("permitted", result["error"].lower())
		if frappe.db.exists("User", test_user):
			frappe.delete_doc("User", test_user, ignore_permissions=True, force=True)
