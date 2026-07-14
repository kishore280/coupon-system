import frappe
from frappe.model.document import Document


class CouponCard(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		code: DF.Data
		item_code: DF.Link
		points_value: DF.Float
		expiry_date: DF.Date
		batch_no: DF.Data | None
		work_order: DF.Data | None
		is_used: DF.Check
		used_by_phone: DF.Link | None
		scanned_at: DF.Datetime | None
	# end: auto-generated types

	def before_validate(self):
		if not self.naming_series:
			self.naming_series = "CC-.YYYY.-.#####"
