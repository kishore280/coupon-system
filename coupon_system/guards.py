"""Structural guards that make the SSOT invariant impossible to violate by accident."""

import frappe
from frappe import _


def block_local_ledger_in_store_mode(doc, method=None):
	"""In Store mode the local Coupon Ledger must never be written — all points live on HQ
	(ADR-0001/0002). This refuses any local ledger insert on a store site, so a stray hook
	or a curious admin can't silently create a second, divergent wallet."""
	from coupon_system.hq_client import is_store

	if is_store():
		frappe.throw(_("This site is in Store mode — points are held on HQ, not written locally."))
