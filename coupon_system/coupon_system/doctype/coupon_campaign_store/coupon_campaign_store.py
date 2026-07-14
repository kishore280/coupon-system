import frappe
from frappe.model.document import Document


class CouponCampaignStore(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		store: DF.Link
	# end: auto-generated types
