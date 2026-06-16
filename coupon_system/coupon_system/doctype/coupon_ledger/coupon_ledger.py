import frappe
from frappe.model.document import Document


class CouponLedger(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		phone: DF.Data
		type: DF.Literal["CREDIT", "DEBIT"]
		points: DF.Float
		description: DF.Data | None
		branch: DF.Data | None
		invoice_no: DF.Data | None
		timestamp: DF.Datetime | None
	# end: auto-generated types
