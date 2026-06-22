import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_months, getdate, today

from coupon_system.coupon_auto import generate_on_manufacture, notify_on_manufacture_cancel

_SRC_PREFIX = "STE-CPNTEST-"


class _FakeSE:
	"""Minimal stand-in for a Stock Entry doc — avoids building a real Manufacture
	entry (BOM, warehouses, raw materials). A plain class (not frappe._dict) is
	used because `_dict.items` resolves to the dict method, shadowing the rows;
	a real Stock Entry exposes `items` as a child-table attribute, like this."""

	def __init__(self, name, rows, purpose="Manufacture", work_order=None):
		self.name = name
		self.purpose = purpose
		self.work_order = work_order
		self.items = [frappe._dict(r) for r in rows]

	def get(self, key, default=None):
		return getattr(self, key, default)


def _fake_se(name, rows, purpose="Manufacture", work_order=None):
	return _FakeSE(name, rows, purpose=purpose, work_order=work_order)


def _row(item_code, qty, is_finished_item=1, batch_no=None):
	return {
		"item_code": item_code,
		"qty": qty,
		"is_finished_item": is_finished_item,
		"batch_no": batch_no,
	}


def _set_flags(item, **kw):
	frappe.db.set_value("Item", item, kw)
	frappe.clear_document_cache("Item", item)


def _cards_for(name):
	return frappe.get_all(
		"Coupon Card",
		filters={"source_stock_entry": name},
		fields=["name", "item_code", "points_value", "expiry_date", "batch_no", "work_order"],
	)


class TestCouponAutoGenerate(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		cls.nos_item = frappe.db.get_value("Item", {"stock_uom": "Nos", "disabled": 0}, "name")
		cls.non_nos_item = frappe.db.get_value(
			"Item", {"stock_uom": ["!=", "Nos"], "disabled": 0}, "name"
		)
		if not cls.nos_item:
			raise unittest.SkipTest("No Nos-UOM Item on this site — skipping auto-generation tests")
		if not frappe.db.exists("Custom Field", {"dt": "Item", "fieldname": "custom_generate_coupons"}):
			raise unittest.SkipTest("Coupon Item custom fields not installed — run bench migrate")

	def tearDown(self):
		frappe.db.delete("Coupon Card", {"source_stock_entry": ["like", _SRC_PREFIX + "%"]})
		for item in (self.nos_item, self.non_nos_item):
			if item:
				_set_flags(
					item,
					custom_generate_coupons=0,
					custom_coupon_points=0,
					custom_coupon_validity_months=0,
					custom_cards_per_unit=0,
				)
		frappe.db.commit()

	def test_generates_one_card_per_unit(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=75,
				   custom_coupon_validity_months=12, custom_cards_per_unit=1)
		name = _SRC_PREFIX + "0001"
		generate_on_manufacture(_fake_se(name, [_row(self.nos_item, 6)]))
		cards = _cards_for(name)
		self.assertEqual(len(cards), 6)
		self.assertEqual(cards[0]["points_value"], 75)
		self.assertEqual(getdate(cards[0]["expiry_date"]), getdate(add_months(today(), 12)))

	def test_cards_per_unit_multiplier(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=10,
				   custom_cards_per_unit=2)
		name = _SRC_PREFIX + "0002"
		generate_on_manufacture(_fake_se(name, [_row(self.nos_item, 5)]))
		self.assertEqual(len(_cards_for(name)), 10)

	def test_skips_non_manufacture_purpose(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=10)
		name = _SRC_PREFIX + "0003"
		generate_on_manufacture(_fake_se(name, [_row(self.nos_item, 5)], purpose="Repack"))
		self.assertEqual(len(_cards_for(name)), 0)

	def test_skips_item_without_flag(self):
		_set_flags(self.nos_item, custom_generate_coupons=0, custom_coupon_points=10)
		name = _SRC_PREFIX + "0004"
		generate_on_manufacture(_fake_se(name, [_row(self.nos_item, 5)]))
		self.assertEqual(len(_cards_for(name)), 0)

	def test_skips_non_nos_item_even_if_flagged(self):
		if not self.non_nos_item:
			self.skipTest("No non-Nos Item available to test the UOM safety filter")
		_set_flags(self.non_nos_item, custom_generate_coupons=1, custom_coupon_points=10)
		name = _SRC_PREFIX + "0005"
		generate_on_manufacture(_fake_se(name, [_row(self.non_nos_item, 5)]))
		self.assertEqual(len(_cards_for(name)), 0)

	def test_idempotent_on_resubmit(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=10)
		name = _SRC_PREFIX + "0006"
		se = _fake_se(name, [_row(self.nos_item, 4)])
		generate_on_manufacture(se)
		generate_on_manufacture(se)  # second call must not duplicate
		self.assertEqual(len(_cards_for(name)), 4)

	def test_aggregates_duplicate_item_rows(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=10)
		name = _SRC_PREFIX + "0007"
		generate_on_manufacture(
			_fake_se(name, [_row(self.nos_item, 3), _row(self.nos_item, 4)])
		)
		self.assertEqual(len(_cards_for(name)), 7)

	def test_ignores_non_finished_rows(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=10)
		name = _SRC_PREFIX + "0008"
		generate_on_manufacture(
			_fake_se(name, [_row(self.nos_item, 5, is_finished_item=0)])
		)
		self.assertEqual(len(_cards_for(name)), 0)

	def test_stamps_batch_and_work_order(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=10)
		name = _SRC_PREFIX + "0009"
		generate_on_manufacture(
			_fake_se(name, [_row(self.nos_item, 2, batch_no="BATCH-XYZ")], work_order="WO-123")
		)
		cards = _cards_for(name)
		self.assertEqual(len(cards), 2)
		self.assertEqual(cards[0]["batch_no"], "BATCH-XYZ")
		self.assertEqual(cards[0]["work_order"], "WO-123")

	def test_cancel_notifies_without_deleting(self):
		_set_flags(self.nos_item, custom_generate_coupons=1, custom_coupon_points=10)
		name = _SRC_PREFIX + "0010"
		se = _fake_se(name, [_row(self.nos_item, 3)])
		generate_on_manufacture(se)
		self.assertEqual(len(_cards_for(name)), 3)
		notify_on_manufacture_cancel(se)  # must NOT delete the cards
		self.assertEqual(len(_cards_for(name)), 3)
