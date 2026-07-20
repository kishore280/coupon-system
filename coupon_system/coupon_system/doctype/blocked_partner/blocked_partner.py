import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import now_datetime


class BlockedPartner(Document):
	# begin: auto-generated types
	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		user: DF.Link
		blocked_by_store: DF.Link | None
		blocked_on: DF.Datetime | None
		blocked_by: DF.Link | None
		reason: DF.SmallText | None
	# end: auto-generated types

	def validate(self):
		if not self.blocked_on:
			self.blocked_on = now_datetime()
		if not self.blocked_by:
			self.blocked_by = frappe.session.user
		self._ensure_unique_block()

	def _ensure_unique_block(self):
		"""At most one block per (user, store). An empty store is the single
		HQ-level block for that user — so two HQ blocks also collapse to one.
		"""
		duplicate = frappe.db.exists(
			"Blocked Partner",
			{
				"user": self.user,
				"blocked_by_store": self.blocked_by_store or "",
				"name": ["!=", self.name],
			},
		)
		if duplicate:
			frappe.throw(
				_("{0} is already blocked by {1}.").format(
					self.user, self.blocked_by_store or _("HQ")
				)
			)


def is_blocked(user):
	"""Return the list of stores currently blocking `user` (an HQ block shows as
	None in the list), or an empty list if the user is not blocked anywhere.

	This is the single source of truth for the block gate — every app endpoint
	asks here, so "blocked" always means the exact same thing: at least one
	Blocked Partner row exists for the user.
	"""
	rows = frappe.get_all(
		"Blocked Partner",
		filters={"user": user},
		fields=["blocked_by_store"],
	)
	return [r.blocked_by_store for r in rows]
