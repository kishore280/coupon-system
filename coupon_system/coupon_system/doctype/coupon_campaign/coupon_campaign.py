import frappe
from frappe import _
from frappe.model.document import Document


class CouponCampaign(Document):
	def validate(self):
		if self.points is not None and int(self.points) <= 0:
			frappe.throw(_("Points must be greater than 0"))
		if self.validity_months is not None and int(self.validity_months) < 0:
			frappe.throw(_("Validity (Months) cannot be negative"))
