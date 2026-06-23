import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate, today


class CouponCampaign(Document):
	def validate(self):
		if self.points is not None and int(self.points) <= 0:
			frappe.throw(_("Points must be greater than 0"))
		if self.validity_months is not None and int(self.validity_months) < 0:
			frappe.throw(_("Validity (Months) cannot be negative"))

	def on_update(self):
		# If the campaign has already ended, retire its unused cards now so the
		# Coupon Card status reflects it immediately (the daily sweep handles
		# future end dates when they arrive).
		if self.end_date and getdate(self.end_date) <= getdate(today()):
			retire_campaign_cards(self.name)


def retire_campaign_cards(campaign):
	"""Mark every unused (Active/Generated) card of a campaign as Expired.
	Returns the number of cards retired."""
	count = frappe.db.count(
		"Coupon Card",
		{"campaign": campaign, "status": ["in", ["Active", "Generated"]], "is_used": 0},
	)
	if count:
		frappe.db.sql(
			"""
			UPDATE `tabCoupon Card` SET status = 'Expired'
			WHERE campaign = %s AND is_used = 0 AND status IN ('Active', 'Generated')
			""",
			campaign,
		)
	return count
