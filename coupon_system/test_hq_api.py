import unittest
from unittest.mock import MagicMock, patch

import frappe

from coupon_system.hq_api import get_my_stores


class TestGetMyStores(unittest.TestCase):
	def setUp(self):
		self.site_url = "https://teststore.example.com"
		if not frappe.db.exists("Coupon Store", self.site_url):
			store = frappe.new_doc("Coupon Store")
			store.store_name = "Test Store HQ"
			store.site_url = self.site_url
			store.is_active = 1
			store.service_api_key = "svc_key"
			store.service_secret = "svc_secret"
			store.insert(ignore_permissions=True)

		self.user = "hq_partner@example.com"
		if not frappe.db.exists("User", self.user):
			user = frappe.new_doc("User")
			user.email = self.user
			user.first_name = "HQ"
			user.save(ignore_permissions=True)
		# Phone-first: the broker requires a mobile number on the user.
		frappe.db.set_value("User", self.user, "mobile_no", "9998887777")

		if not frappe.db.exists(
			"Partner Store Link", {"user": self.user, "store": self.site_url}
		):
			link = frappe.new_doc("Partner Store Link")
			link.user = self.user
			link.store = self.site_url
			link.sales_partner = "SP-1"
			link.status = "Active"
			link.insert(ignore_permissions=True)

		frappe.set_user("Administrator")

	def _as_user(self, fn):
		frappe.set_user(self.user)
		try:
			return fn()
		finally:
			frappe.set_user("Administrator")

	@patch("coupon_system.hq_api.requests.post")
	def test_returns_store_with_brokered_token(self, mock_post):
		resp = MagicMock()
		resp.status_code = 200
		resp.json.return_value = {
			"message": {"access_token": "a1", "refresh_token": "r1", "expires_in": 3600}
		}
		mock_post.return_value = resp

		out = self._as_user(get_my_stores)

		stores = out["stores"]
		self.assertEqual(len(stores), 1)
		self.assertEqual(stores[0]["store"], self.site_url)
		self.assertEqual(stores[0]["sales_partner"], "SP-1")
		self.assertEqual(stores[0]["access_token"], "a1")

		# HQ must call the store's issue_user_token with ITS service key, for this
		# user, passing the phone so the store provisions the user with a number.
		_, kwargs = mock_post.call_args
		self.assertIn("issue_user_token", mock_post.call_args[0][0])
		self.assertIn("token svc_key:", kwargs["headers"]["Authorization"])
		self.assertEqual(kwargs["json"]["user"], self.user)
		self.assertEqual(kwargs["json"]["mobile_no"], "9998887777")

	@patch("coupon_system.hq_api.requests.post")
	def test_store_down_is_marked_unavailable(self, mock_post):
		mock_post.side_effect = Exception("connection refused")
		out = self._as_user(get_my_stores)
		self.assertEqual(out["stores"][0]["error"], "unavailable")
		self.assertNotIn("access_token", out["stores"][0])

	@patch("coupon_system.hq_api.requests.post")
	def test_phoneless_user_is_rejected_before_any_store(self, mock_post):
		# A user with no mobile number must be stopped at HQ — no store call at all.
		phoneless = "nophone_partner@example.com"
		if not frappe.db.exists("User", phoneless):
			user = frappe.new_doc("User")
			user.email = phoneless
			user.first_name = "N"
			user.save(ignore_permissions=True)
		frappe.db.set_value("User", phoneless, "mobile_no", None)

		frappe.set_user(phoneless)
		try:
			with self.assertRaises(frappe.ValidationError):
				get_my_stores()
		finally:
			frappe.set_user("Administrator")
		mock_post.assert_not_called()

	def tearDown(self):
		frappe.set_user("Administrator")
