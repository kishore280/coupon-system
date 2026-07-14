import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, now_datetime


class CouponWithdrawalRequest(Document):
	def validate(self):
		if not self.phone or not isinstance(self.phone, str) or not self.phone.strip():
			frappe.throw(_("phone is required"))
		if not self.points or self.points <= 0:
			frappe.throw(_("points must be a positive integer"))
		if not self.payout_details or not str(self.payout_details).strip():
			frappe.throw(_("payout_details is required"))

		if self.is_new():
			self.status = "Pending"
			self.requested_on = now_datetime()
			if not self.amount:
				rate = flt(frappe.db.get_single_value(
					"Coupon System Settings", "points_to_currency_rate")) or 1
				self.amount = flt(self.points) * rate
		else:
			previous_status = frappe.db.get_value(self.doctype, self.name, "status")
			if self.status != previous_status:
				self._handle_status_transition(previous_status)

	def _handle_status_transition(self, previous_status):
		if previous_status != "Pending":
			frappe.throw(_("Only a Pending request can change status"))

		if self.status == "Paid":
			from coupon_system.api import _post_ledger
			_post_ledger(self.phone, "DEBIT", self.points, f"Withdrawal {self.name}")
			self.paid_on = now_datetime()
		elif self.status == "Rejected":
			self.rejected_on = now_datetime()
		else:
			frappe.throw(_("Invalid status transition"))
