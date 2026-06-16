import frappe
from frappe.model.document import Document


class CouponSystemSettings(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		scan_base_url: DF.Data
	# end: auto-generated types
