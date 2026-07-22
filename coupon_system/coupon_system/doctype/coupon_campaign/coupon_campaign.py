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
		# A self-contained store is one local wallet - there is no other store to lock points to -
		# so owned_by_store is meaningless here. Clear it rather than leaving it set-but-ignored.
		if self.owned_by_store:
			from coupon_system.hq_client import is_self_contained

			if is_self_contained():
				self.owned_by_store = None
				frappe.msgprint(
					_("Owned By Store isn't used on a self-contained store — cleared."),
					indicator="orange", alert=True,
				)

	def on_update(self):
		# If the campaign has already ended, retire its unused cards now so the
		# Coupon Card status reflects it immediately (the daily sweep handles
		# future end dates when they arrive).
		if self.end_date and getdate(self.end_date) <= getdate(today()):
			retire_campaign_cards(self.name)


def retire_campaign_cards(campaign):
	"""Mark every unused (Active/Generated) card of a campaign as Retired (distinct
	from Expired, which is a card reaching its own date). Returns the count."""
	count = frappe.db.count(
		"Coupon Card",
		{"campaign": campaign, "status": ["in", ["Active", "Generated"]], "is_used": 0},
	)
	if count:
		frappe.db.sql(
			"""
			UPDATE `tabCoupon Card` SET status = 'Retired'
			WHERE campaign = %s AND is_used = 0 AND status IN ('Active', 'Generated')
			""",
			campaign,
		)
	return count
