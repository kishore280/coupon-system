import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from coupon_system.coupon_auto import (
	expire_cards,
	generate_on_work_order,
	void_on_work_order_cancel,
)

_WO_PREFIX = "WO-CPNTEST-"
_CAMPAIGN = "TEST WO Painter 20"


class _FakeWO:
	"""Minimal stand-in for a Work Order. The handler reads name, production_item,
	and required_items[].{item_code, required_qty} — a real WO exposes the same."""

	def __init__(self, name, production_item, rows):
		self.name = name
		self.production_item = production_item
		self.required_items = [frappe._dict(r) for r in rows]

	def get(self, key, default=None):
		return getattr(self, key, default)


def _cards_for(work_order):
	return frappe.get_all(
		"Coupon Card",
		filters={"work_order": work_order},
		fields=["name", "campaign", "item_code", "points_value", "status"],
	)


def ensure_campaign(points=20, validity_months=12, is_active=1):
	if frappe.db.exists("Coupon Campaign", _CAMPAIGN):
		frappe.db.set_value("Coupon Campaign", _CAMPAIGN,
							{"points": points, "validity_months": validity_months, "is_active": is_active})
	else:
		doc = frappe.new_doc("Coupon Campaign")
		doc.campaign_name = _CAMPAIGN
		doc.points = points
		doc.validity_months = validity_months
		doc.is_active = is_active
		doc.insert(ignore_permissions=True)
	return _CAMPAIGN


class TestCouponAutoWorkOrder(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": "custom_coupon_campaign"}):
			raise unittest.SkipTest("custom_coupon_campaign not installed — run bench migrate")

		items = frappe.get_all("Item", {"disabled": 0}, pluck="name", limit=2)
		if len(items) < 1:
			raise unittest.SkipTest("No Items on this site — skipping")
		cls.coupon_item = items[0]                       # the BOM coupon component
		cls.finished_item = items[1] if len(items) > 1 else items[0]

		ensure_campaign()
		frappe.db.set_value("Item", cls.coupon_item, "custom_coupon_campaign", _CAMPAIGN)
		frappe.clear_document_cache("Item", cls.coupon_item)

	@classmethod
	def tearDownClass(cls):
		frappe.db.set_value("Item", cls.coupon_item, "custom_coupon_campaign", None)
		frappe.db.delete("Coupon Card", {"campaign": _CAMPAIGN})
		if frappe.db.exists("Coupon Campaign", _CAMPAIGN):
			frappe.delete_doc("Coupon Campaign", _CAMPAIGN, ignore_permissions=True, force=True)
		super().tearDownClass()

	def tearDown(self):
		frappe.db.delete("Coupon Card", {"work_order": ["like", _WO_PREFIX + "%"]})
		frappe.db.commit()

	def _wo(self, name, qty):
		return _FakeWO(name, self.finished_item,
					   [{"item_code": self.coupon_item, "required_qty": qty}])

	def test_generates_cards_for_coupon_line(self):
		name = _WO_PREFIX + "0001"
		generate_on_work_order(self._wo(name, 100))
		cards = _cards_for(name)
		self.assertEqual(len(cards), 100)
		self.assertEqual(cards[0]["campaign"], _CAMPAIGN)
		self.assertEqual(cards[0]["item_code"], self.finished_item)  # stamped with finished good
		self.assertEqual(cards[0]["points_value"], 20)               # snapshot
		self.assertEqual(cards[0]["status"], "Active")

	def test_skips_non_coupon_components(self):
		name = _WO_PREFIX + "0002"
		# a row whose item has no custom_coupon_campaign
		other = frappe.get_all("Item", {"disabled": 0, "custom_coupon_campaign": ["in", [None, ""]]},
							   pluck="name", limit=1)
		wo = _FakeWO(name, self.finished_item, [{"item_code": other[0], "required_qty": 50}])
		generate_on_work_order(wo)
		self.assertEqual(len(_cards_for(name)), 0)

	def test_idempotent_on_resubmit(self):
		name = _WO_PREFIX + "0003"
		wo = self._wo(name, 10)
		generate_on_work_order(wo)
		generate_on_work_order(wo)  # second call must not duplicate
		self.assertEqual(len(_cards_for(name)), 10)

	def test_inactive_campaign_generates_nothing(self):
		ensure_campaign(is_active=0)
		name = _WO_PREFIX + "0004"
		generate_on_work_order(self._wo(name, 5))
		self.assertEqual(len(_cards_for(name)), 0)
		ensure_campaign(is_active=1)  # restore

	def test_void_on_cancel(self):
		name = _WO_PREFIX + "0005"
		wo = self._wo(name, 8)
		generate_on_work_order(wo)
		self.assertEqual(len(_cards_for(name)), 8)
		void_on_work_order_cancel(wo)
		statuses = {c["status"] for c in _cards_for(name)}
		self.assertEqual(statuses, {"Void"})

	def test_void_leaves_redeemed_intact(self):
		name = _WO_PREFIX + "0006"
		wo = self._wo(name, 3)
		generate_on_work_order(wo)
		# mark one as redeemed
		one = _cards_for(name)[0]["name"]
		frappe.db.set_value("Coupon Card", one, {"status": "Redeemed", "is_used": 1})
		void_on_work_order_cancel(wo)
		self.assertEqual(frappe.db.get_value("Coupon Card", one, "status"), "Redeemed")
		voided = [c for c in _cards_for(name) if c["status"] == "Void"]
		self.assertEqual(len(voided), 2)

	def test_expire_cards_sweep(self):
		name = _WO_PREFIX + "0007"
		generate_on_work_order(self._wo(name, 2))
		# force expiry into the past
		frappe.db.sql(
			"UPDATE `tabCoupon Card` SET expiry_date = %s WHERE work_order = %s",
			(add_days(today(), -1), name),
		)
		expire_cards()
		statuses = {c["status"] for c in _cards_for(name)}
		self.assertEqual(statuses, {"Expired"})
