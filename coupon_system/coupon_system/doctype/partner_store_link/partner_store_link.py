import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class PartnerStoreLink(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		user: DF.Link
		store: DF.Link
		status: DF.Literal["Active", "Pending", "Revoked"]
		enrolled_on: DF.Datetime | None
	# end: auto-generated types

	def validate(self):
		if not self.enrolled_on:
			self.enrolled_on = now_datetime()
		self._ensure_unique_link()

	def _ensure_unique_link(self):
		"""A user partners in a given store at most once."""
		duplicate = frappe.db.exists(
			"Partner Store Link",
			{"user": self.user, "store": self.store, "name": ["!=", self.name]},
		)
		if duplicate:
			frappe.throw(
				_("{0} is already linked to store {1}.").format(self.user, self.store)
			)
