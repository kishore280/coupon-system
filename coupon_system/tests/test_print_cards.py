import json
import unittest

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from coupon_system.www.print_cards import get_context
from coupon_system.utils import get_coupon_qr

_ITEM_CODE = None


def get_item_code():
	global _ITEM_CODE
	if _ITEM_CODE is None:
		_ITEM_CODE = frappe.db.get_value("Item", {"disabled": 0}, "name")
	return _ITEM_CODE


def make_card(code, batch_no="TEST-BATCH-PRINT"):
	frappe.db.delete("Coupon Card", {"code": code})
	doc = frappe.new_doc("Coupon Card")
	doc.code = code
	doc.item_code = get_item_code()
	doc.points_value = 50
	doc.expiry_date = add_days(today(), 30)
	doc.batch_no = batch_no
	doc.insert(ignore_permissions=True)
	return doc


def ctx_with_filters(filters):
	frappe.form_dict.filters = json.dumps(filters)
	context = frappe._dict()
	get_context(context)
	return context


class TestPrintCards(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not get_item_code():
			raise unittest.SkipTest("No Items found on this site")

	def setUp(self):
		for i in range(3):
			make_card(f"PRNT-TEST-000{i}")

	def tearDown(self):
		frappe.db.delete("Coupon Card", {"batch_no": "TEST-BATCH-PRINT"})

	def test_filter_by_batch_returns_correct_cards(self):
		ctx = ctx_with_filters([["Coupon Card", "batch_no", "=", "TEST-BATCH-PRINT"]])
		self.assertEqual(ctx.total, 3)
		codes = {c.code for c in ctx.cards}
		for i in range(3):
			self.assertIn(f"PRNT-TEST-000{i}", codes)

	def test_no_filters_returns_all_cards(self):
		ctx = ctx_with_filters([])
		self.assertGreaterEqual(ctx.total, 3)

	def test_nonequality_filters_are_ignored(self):
		# only "=" filters are applied — others are skipped safely
		ctx = ctx_with_filters([
			["Coupon Card", "batch_no", "=", "TEST-BATCH-PRINT"],
			["Coupon Card", "points_value", ">", "0"],
		])
		self.assertEqual(ctx.total, 3)

	def test_no_matching_cards_raises(self):
		with self.assertRaises(Exception):
			ctx_with_filters([["Coupon Card", "batch_no", "=", "BATCH-DOES-NOT-EXIST"]])

	def test_get_coupon_qr_returns_png_data_uri(self):
		result = get_coupon_qr("TEST-XXXX-0001")
		self.assertTrue(result.startswith("data:image/png;base64,"))
		# must be non-trivial base64 content
		b64_part = result.split(",", 1)[1]
		self.assertGreater(len(b64_part), 100)
