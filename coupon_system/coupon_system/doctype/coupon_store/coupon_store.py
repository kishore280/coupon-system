import frappe
from frappe.model.document import Document


class CouponStore(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		store_name: DF.Data
		site_url: DF.Data
		is_active: DF.Check
	# end: auto-generated types
