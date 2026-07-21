"""Store-locked points (buckets) — the new SSOT scoping. See docs/store-coupons-build-spec.md
and docs/adr/0003. Central points are general (spendable anywhere); store coupons lock points to
their store; a redemption at store X may draw general + X only, store-locked-first."""

import unittest
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from coupon_system.api import (
	_available_at,
	_buckets,
	_get_or_create_user,
	balance,
	redeem,
	register_cards,
	request_withdrawal,
	reverse_redeem,
	scan,
)

_STORE_A = "https://store-a.example.com"
_STORE_B = "https://store-b.example.com"
_STORE_RT = "https://rt1.example.com"
_NS_A = "SA1"
_NS_B = "SB1"
_NS_RT = "RT1"

_ITEM_CODE = None


def get_item_code():
	global _ITEM_CODE
	if _ITEM_CODE is None:
		_ITEM_CODE = frappe.db.get_value("Item", {"disabled": 0}, "name")
	return _ITEM_CODE


def ensure_store(site_url, name, namespace, route_scans=0):
	if not frappe.db.exists("Coupon Store", site_url):
		doc = frappe.new_doc("Coupon Store")
		doc.store_name = name
		doc.site_url = site_url
		doc.code_namespace = namespace
		doc.is_active = 1
		doc.route_scans = route_scans
		doc.insert(ignore_permissions=True)
	else:
		frappe.db.set_value("Coupon Store", site_url,
							{"code_namespace": namespace, "is_active": 1, "route_scans": route_scans})
	return site_url


def make_card(code, points_value, store=None, days_ahead=30):
	"""Central card if store is None, else a store-locked card (origin=Store, value snapshot)."""
	frappe.db.delete("Coupon Card", {"code": code})
	doc = frappe.new_doc("Coupon Card")
	doc.code = code
	doc.item_code = get_item_code()
	doc.points_value = points_value
	doc.expiry_date = add_days(today(), days_ahead)
	doc.status = "Active"
	if store:
		doc.origin = "Store"
		doc.store = store
	doc.insert(ignore_permissions=True)
	return doc


def cleanup_user(phone):
	frappe.db.delete("Coupon Ledger", {"phone": phone})
	if frappe.db.exists("Coupon User", phone):
		frappe.delete_doc("Coupon User", phone, ignore_permissions=True, force=True)


class TestStoreBuckets(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not get_item_code():
			raise unittest.SkipTest("No Items found on this site — skipping bucket tests")
		ensure_store(_STORE_A, "TEST Bucket Store A", _NS_A)
		ensure_store(_STORE_B, "TEST Bucket Store B", _NS_B)

	@classmethod
	def tearDownClass(cls):
		frappe.db.delete("Coupon Card", {"code": ["like", "TB-%"]})
		frappe.db.delete("Coupon Card", {"store": ["in", [_STORE_A, _STORE_B]]})
		for name in (_STORE_A, _STORE_B, _STORE_RT):
			if frappe.db.exists("Coupon Store", name):
				frappe.delete_doc("Coupon Store", name, ignore_permissions=True, force=True)
		super().tearDownClass()

	def setUp(self):
		self.phone = "+91-9888000001"
		cleanup_user(self.phone)

	def tearDown(self):
		cleanup_user(self.phone)
		frappe.db.delete("Coupon Card", {"code": ["like", "TB-%"]})

	# --- helpers ---------------------------------------------------------------
	def earn_general(self, points):
		code = f"TB-GEN-{points}"
		make_card(code, points)
		self.assertTrue(scan(self.phone, code)["success"])

	def earn_store(self, store, points, tag="X"):
		code = f"TB-{tag}-{points}"
		make_card(code, points, store=store)
		res = scan(self.phone, code)
		self.assertTrue(res["success"])
		self.assertEqual(res["locked_to_store"], store)

	# --- tests -----------------------------------------------------------------
	def test_store_scan_lands_in_bucket_not_general(self):
		self.earn_general(100)
		self.earn_store(_STORE_A, 10)
		b = _buckets(self.phone)
		self.assertEqual(b.get(None), 100)
		self.assertEqual(b.get(_STORE_A), 10)
		self.assertEqual(sum(b.values()), 110)

	def test_available_at_excludes_other_store(self):
		self.earn_general(100)
		self.earn_store(_STORE_A, 10, tag="A")
		self.earn_store(_STORE_B, 5, tag="B")
		self.assertEqual(_available_at(self.phone, _STORE_A), 110)  # general + A
		self.assertEqual(_available_at(self.phone, _STORE_B), 105)  # general + B

	def test_redeem_drains_store_locked_first(self):
		self.earn_general(100)
		self.earn_store(_STORE_A, 10, tag="A")
		res = redeem(self.phone, 10, _STORE_A, "TB-INV-1")
		self.assertTrue(res["success"])
		b = _buckets(self.phone)
		self.assertEqual(b.get(_STORE_A, 0), 0)   # store bucket drained first
		self.assertEqual(b.get(None), 100)        # general untouched
		# exactly one DEBIT row, tagged to the store bucket
		debits = frappe.get_all("Coupon Ledger",
			filters={"phone": self.phone, "type": "DEBIT"}, fields=["points", "bucket_store"])
		self.assertEqual(len(debits), 1)
		self.assertEqual(debits[0].bucket_store, _STORE_A)

	def test_redeem_splits_across_buckets(self):
		self.earn_general(100)
		self.earn_store(_STORE_A, 10, tag="A")
		res = redeem(self.phone, 105, _STORE_A, "TB-INV-2")  # 10 store + 95 general
		self.assertTrue(res["success"])
		rows = {r.bucket_store: r.points for r in frappe.get_all("Coupon Ledger",
			filters={"phone": self.phone, "type": "DEBIT"}, fields=["points", "bucket_store"])}
		self.assertEqual(rows.get(_STORE_A), 10)
		self.assertEqual(rows.get(None), 95)
		self.assertEqual(_buckets(self.phone).get(None), 5)

	def test_redeem_insufficient_ignores_other_stores_points(self):
		self.earn_store(_STORE_A, 10, tag="A")
		self.earn_store(_STORE_B, 5, tag="B")
		# total is 15, but only 10 is available at A → must fail
		res = redeem(self.phone, 15, _STORE_A, "TB-INV-3")
		self.assertFalse(res["success"])
		self.assertIn("Insufficient", res["error"])

	def test_reverse_restores_each_bucket(self):
		self.earn_general(100)
		self.earn_store(_STORE_A, 10, tag="A")
		self.assertTrue(redeem(self.phone, 105, _STORE_A, "TB-INV-4")["success"])
		rev = reverse_redeem("TB-INV-4", _STORE_A)
		self.assertTrue(rev["success"])
		self.assertEqual(rev["points_restored"], 105)
		b = _buckets(self.phone)
		self.assertEqual(b.get(None), 100)
		self.assertEqual(b.get(_STORE_A), 10)

	def test_reverse_is_idempotent(self):
		self.earn_store(_STORE_A, 10, tag="A")
		self.assertTrue(redeem(self.phone, 10, _STORE_A, "TB-INV-5")["success"])
		self.assertTrue(reverse_redeem("TB-INV-5", _STORE_A)["success"])
		again = reverse_redeem("TB-INV-5", _STORE_A)
		self.assertFalse(again["success"])
		self.assertIn("already", again["error"].lower())

	def test_redeem_idempotent_per_invoice(self):
		self.earn_store(_STORE_A, 20, tag="A")
		self.assertTrue(redeem(self.phone, 5, _STORE_A, "TB-INV-6")["success"])
		dup = redeem(self.phone, 5, _STORE_A, "TB-INV-6")
		self.assertFalse(dup["success"])
		self.assertIn("Already redeemed", dup["error"])

	def test_withdrawal_excludes_store_locked(self):
		frappe.db.set_single_value("Coupon System Settings", "enable_withdrawals", 1)
		self.earn_general(20)
		self.earn_store(_STORE_A, 100, tag="A")
		# withdrawable is general only (20), not the 120 total
		bad = request_withdrawal(self.phone, 100, "upi: test@bank")
		self.assertFalse(bad["success"])
		self.assertIn("Insufficient", bad["error"])
		ok = request_withdrawal(self.phone, 20, "upi: test@bank")
		self.assertTrue(ok["success"])
		frappe.db.delete("Coupon Withdrawal Request", {"phone": self.phone})

	def test_balance_breakdown(self):
		self.earn_general(100)
		self.earn_store(_STORE_A, 10, tag="A")
		self.earn_store(_STORE_B, 5, tag="B")
		res = balance(self.phone)
		self.assertTrue(res["success"])
		self.assertEqual(res["points_balance"], 115)
		self.assertEqual(res["general"], 100)
		by_store = {r["store"]: r["points"] for r in res["restricted"]}
		self.assertEqual(by_store.get(_STORE_A), 10)
		self.assertEqual(by_store.get(_STORE_B), 5)

	def test_register_cards_idempotent_and_namespace(self):
		good = f"OXFX-{_NS_A}-TB01"
		res = register_cards(_STORE_A, [{"code": good, "points_value": 10, "expiry_date": add_days(today(), 30)}])
		self.assertTrue(res["success"])
		self.assertIn(good, res["registered"])
		# re-register → skipped, no duplicate
		again = register_cards(_STORE_A, [{"code": good, "points_value": 10, "expiry_date": add_days(today(), 30)}])
		self.assertIn(good, again["skipped"])
		# wrong namespace → rejected
		bad = register_cards(_STORE_A, [{"code": f"OXFX-{_NS_B}-TB02", "points_value": 10, "expiry_date": add_days(today(), 30)}])
		self.assertFalse(bad["success"])
		self.assertIn("namespace", bad["error"].lower())

	def test_registered_store_card_scans_into_its_bucket(self):
		code = f"OXFX-{_NS_A}-TB07"
		register_cards(_STORE_A, [{"code": code, "points_value": 15, "expiry_date": add_days(today(), 30)}])
		res = scan(self.phone, code)
		self.assertTrue(res["success"])
		self.assertEqual(res["points_added"], 15)
		self.assertEqual(res["locked_to_store"], _STORE_A)
		self.assertEqual(_buckets(self.phone).get(_STORE_A), 15)

	# --- stable machine reasons (so hooks never match on translatable text) ---
	def test_redeem_reason_already_redeemed(self):
		self.earn_store(_STORE_A, 20, tag="A")
		self.assertTrue(redeem(self.phone, 5, _STORE_A, "TB-RE-1")["success"])
		dup = redeem(self.phone, 5, _STORE_A, "TB-RE-1")
		self.assertFalse(dup["success"])
		self.assertEqual(dup["reason"], "already_redeemed")

	def test_reverse_reason_codes(self):
		none = reverse_redeem("TB-NOPE-1", _STORE_A)
		self.assertFalse(none["success"])
		self.assertEqual(none["reason"], "no_redemption")

		self.earn_store(_STORE_A, 10, tag="A")
		self.assertTrue(redeem(self.phone, 10, _STORE_A, "TB-RE-2")["success"])
		self.assertTrue(reverse_redeem("TB-RE-2", _STORE_A)["success"])
		again = reverse_redeem("TB-RE-2", _STORE_A)
		self.assertFalse(again["success"])
		self.assertEqual(again["reason"], "already_reversed")

	def test_store_mode_blocks_local_ledger(self):
		# In Store mode the local points ledger must be UNWRITABLE (structural SSOT guard) - all
		# points live on HQ. is_store() honors the coupon_site_role site_config override.
		_get_or_create_user(self.phone)
		frappe.local.conf["coupon_site_role"] = "Store"
		try:
			with self.assertRaisesRegex(frappe.ValidationError, "Store mode"):
				e = frappe.new_doc("Coupon Ledger")
				e.phone = self.phone
				e.type = "CREDIT"
				e.points = 5
				e.insert(ignore_permissions=True)
		finally:
			frappe.local.conf.pop("coupon_site_role", None)

	# --- HQ scan gateway: route a self-contained store's code by namespace ---
	def test_route_store_for_code_matches_namespace(self):
		from coupon_system.gateway import route_store_for_code

		ensure_store(_STORE_RT, "RT1 Store", _NS_RT, route_scans=1)
		s = route_store_for_code(f"{_NS_RT}-AAAA-BBBB")
		self.assertIsNotNone(s)
		self.assertEqual(s.code_namespace, _NS_RT)
		# a namespace with no routable store -> no route
		self.assertIsNone(route_store_for_code("NOSUCH-AAAA-BBBB"))

	def test_route_ignores_non_routable_store(self):
		from coupon_system.gateway import route_store_for_code

		# HQ-backed store (route_scans=0) must NOT be a proxy target
		ensure_store(_STORE_A, "A", _NS_A, route_scans=0)
		self.assertIsNone(route_store_for_code(f"{_NS_A}-AAAA-BBBB"))

	def test_scan_proxies_unknown_code_to_self_contained_store(self):
		ensure_store(_STORE_RT, "RT1 Store", _NS_RT, route_scans=1)
		canned = {"success": True, "points_added": 7, "locked_to_store": None, "new_balance": 7}
		with patch("coupon_system.gateway.proxy_scan", return_value=canned) as m:
			res = scan(self.phone, f"{_NS_RT}-ZZZZ-YYYY")  # not a local card -> routed
		self.assertEqual(res, canned)
		m.assert_called_once()

	def test_scan_unknown_code_with_no_route_is_not_found(self):
		res = scan(self.phone, "GHOST-1234-5678")
		self.assertFalse(res["success"])
		self.assertIn("not found", res["error"].lower())
