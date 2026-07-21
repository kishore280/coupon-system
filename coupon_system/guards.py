"""Structural guards that make the SSOT invariant impossible to violate by accident."""

import frappe
from frappe import _


def block_local_ledger_in_store_mode(doc, method=None):
	"""In Store mode the local Coupon Ledger must never be written — all points live on HQ
	(ADR-0001/0002).

	This is the SINGLE structural backstop for every local points path: all points movement
	(earn, redeem, and even a Withdrawal Request payout) goes through a Coupon Ledger insert,
	so blocking it here makes the whole class of local-wallet misuse impossible. That's why the
	store's other installed-but-unused points doctypes (Coupon Withdrawal Request, etc.) are
	inert without needing their own guards - no ceremony required. A stray hook or a curious
	admin can't create a second, divergent wallet.
	"""
	from coupon_system.hq_client import is_store

	if is_store():
		frappe.throw(_("This site is in Store mode — points are held on HQ, not written locally."))
