import frappe
from frappe.model.document import Document

from coupon_system.api import _get_balance


class CouponUser(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		phone: DF.Data
		full_name: DF.Data | None
		points_balance: DF.Float
	# end: auto-generated types

	def after_load(self):
		self.points_balance = _get_balance(self.phone)
