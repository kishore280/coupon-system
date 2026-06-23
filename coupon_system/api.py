import secrets
import string

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.query_builder import Order
from frappe.query_builder.functions import Sum
from frappe.utils import add_months, cint, flt, getdate, now_datetime, today


def _get_balance(phone):
	CL = frappe.qb.DocType("Coupon Ledger")
	rows = (
		
		frappe.qb.from_(CL)
		.select(CL.type, Sum(CL.points).as_("total"))
		.where(CL.phone == phone)
		.groupby(CL.type)
		.run(as_dict=True)
	)
	totals = {r.type: cint(r.total) for r in rows}
	return totals.get("CREDIT", 0) - totals.get("DEBIT", 0)


def _get_or_create_user(phone, full_name=None):
	if frappe.db.exists("Coupon User", phone):
		return frappe.get_doc("Coupon User", phone)
	user = frappe.new_doc("Coupon User")
	user.phone = phone
	user.full_name = full_name or ""
	user.insert(ignore_permissions=True)
	return user


def _resolve_card_points(card):
	"""Resolve the LIVE point value of a card.

	Campaign value if the card is linked to one (the dynamic dial); otherwise the
	card's snapshot points_value as a fallback. Raises if the campaign is inactive.
	"""
	if card.get("campaign"):
		camp = frappe.db.get_value(
			"Coupon Campaign", card.campaign, ["points", "is_active", "end_date"], as_dict=True
		)
		if camp:
			if not camp.is_active:
				frappe.throw(_("This campaign is not active"))
			if camp.end_date and getdate(camp.end_date) < getdate(today()):
				frappe.throw(_("This campaign has ended"))
			return cint(camp.points)
	return cint(card.get("points_value"))


def _assert_card_scannable(card):
	"""Raise if a card cannot be earned/redeemed right now (lifecycle + expiry)."""
	if card.get("status") == "Void":
		frappe.throw(_("Card has been voided"))
	if card.get("status") == "Generated":
		frappe.throw(_("Card is not active yet"))
	if card.get("status") == "Redeemed" or card.get("is_used"):
		frappe.throw(_("Card already redeemed"))
	if card.get("status") == "Retired":
		frappe.throw(_("This campaign has ended"))
	if card.get("status") == "Expired" or getdate(card.expiry_date) < getdate(today()):
		frappe.throw(_("Card expired"))


def _generate_code():
	chars = string.ascii_uppercase + string.digits
	part1 = "".join(secrets.choice(chars) for _ in range(4))
	part2 = "".join(secrets.choice(chars) for _ in range(4))
	return f"{part1}-{part2}"


def _campaign_snapshot(campaign):
	"""Look up a campaign → (points_snapshot, expiry_date). Raises if missing/inactive."""
	camp = frappe.db.get_value(
		"Coupon Campaign", campaign,
		["points", "validity_months", "is_active", "end_date"], as_dict=True,
	)
	if not camp:
		frappe.throw(_("Campaign {0} not found").format(campaign))
	if not camp.is_active:
		frappe.throw(_("Campaign {0} is not active").format(campaign))
	if camp.end_date and getdate(camp.end_date) < getdate(today()):
		frappe.throw(_("Campaign {0} has ended").format(campaign))
	points = cint(camp.points)
	if points <= 0:
		frappe.throw(_("Campaign {0} has no point value set").format(campaign))
	expiry = add_months(today(), cint(camp.validity_months) or 12)
	return points, expiry


def _validate_campaign_row(row):
	"""Validate one generation-row dict (campaign-driven).
	Returns (qty, points_snapshot, expiry_date). Raises on bad input."""
	try:
		qty = int(row["quantity"])
	except (KeyError, TypeError, ValueError):
		frappe.throw(_("quantity must be a positive integer"))
	if qty <= 0:
		frappe.throw(_("quantity must be a positive integer"))
	if qty > 10_000:
		frappe.throw(_("quantity cannot exceed 10,000 per call"))

	if not row.get("campaign"):
		frappe.throw(_("campaign is required"))

	points, expiry = _campaign_snapshot(row["campaign"])
	return qty, points, expiry


@frappe.whitelist()
def scan(phone, code, full_name=None):
	try:
		roles = frappe.get_roles()
		if not ({"System Manager", "Coupon Manager", "Coupon Mobile"} & set(roles)):
			frappe.throw(_("Not permitted"))

		if not phone or not str(phone).strip():
			frappe.throw(_("phone is required"))

		card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
		if not card_name:
			frappe.throw(_("Card not found"))

		# Lock the row before reading so concurrent scans can't both see is_used=0
		frappe.db.sql("SELECT name FROM `tabCoupon Card` WHERE name = %s FOR UPDATE", card_name)
		card = frappe.get_doc("Coupon Card", card_name)

		_assert_card_scannable(card)

		# Resolve the LIVE value now, then lock it into the ledger forever.
		points = _resolve_card_points(card)

		# _get_or_create_user is inside the savepoint so a write failure rolls it back
		frappe.db.savepoint("coupon_scan")
		try:
			_get_or_create_user(phone, full_name)

			card.is_used = 1
			card.status = "Redeemed"
			card.used_by_phone = phone
			card.scanned_at = now_datetime()
			card.save(ignore_permissions=True)

			ledger = frappe.new_doc("Coupon Ledger")
			ledger.phone = phone
			ledger.type = "CREDIT"
			ledger.points = points
			ledger.description = f"Card {code} scanned"
			ledger.timestamp = now_datetime()
			ledger.insert(ignore_permissions=True)
		except Exception:
			frappe.db.rollback(save_point="coupon_scan")
			raise

		return {
			"success": True,
			"points_added": points,
			"new_balance": _get_balance(phone),
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def balance(phone):
	try:
		roles = frappe.get_roles()
		if not ({"System Manager", "Coupon Manager", "Coupon Mobile"} & set(roles)):
			frappe.throw(_("Not permitted"))

		if not frappe.db.exists("Coupon User", phone):
			frappe.throw(_("User not found"))

		user = frappe.get_doc("Coupon User", phone)

		CL = frappe.qb.DocType("Coupon Ledger")

		# Single GROUP BY for balance + totals
		rows = (
			frappe.qb.from_(CL)
			.select(CL.type, Sum(CL.points).as_("total"))
			.where(CL.phone == phone)
			.groupby(CL.type)
			.run(as_dict=True)
		)
		totals = {r.type: cint(r.total) for r in rows}
		total_earned = totals.get("CREDIT", 0)
		total_redeemed = totals.get("DEBIT", 0)
		points_balance = total_earned - total_redeemed

		ledger_entries = (
			frappe.qb.from_(CL)
			.select(CL.type, CL.points, CL.description, CL.site_url, CL.invoice_no, CL.timestamp)
			.where(CL.phone == phone)
			.orderby(CL.timestamp, order=Order.desc)
			.limit(20)
			.run(as_dict=True)
		)

		# Earned points never expire in the current model (a card's expiry_date only
		# governs UNSCANNED cards). Until a "points expire N months after earning"
		# feature exists, the honest value is 0 — kept in the response so the mobile
		# contract is stable.
		points_expiring_soon = 0

		return {
			"success": True,
			"phone": phone,
			"full_name": user.full_name,
			"points_balance": points_balance,
			"total_earned": total_earned,
			"total_redeemed": total_redeemed,
			"points_expiring_soon": points_expiring_soon,
			"ledger": ledger_entries,
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def redeem(phone, amount, site_url, invoice_no, code=None, full_name=None):
	try:
		if not phone or not str(phone).strip():
			frappe.throw(_("phone is required"))

		amount = cint(amount)
		if amount <= 0:
			frappe.throw(_("Redemption amount must be greater than 0"))

		if frappe.db.exists("Coupon Ledger", {"invoice_no": invoice_no, "site_url": site_url, "type": "DEBIT"}):
			frappe.throw(_("Already redeemed for this invoice"))

		if code:
			card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
			if not card_name:
				frappe.throw(_("Card not found"))

			# Lock the row before reading so concurrent redemptions can't both see is_used=0
			frappe.db.sql("SELECT name FROM `tabCoupon Card` WHERE name = %s FOR UPDATE", card_name)
			card = frappe.get_doc("Coupon Card", card_name)

			_assert_card_scannable(card)

			points = _resolve_card_points(card)
			if points < amount:
				frappe.throw(_("Insufficient balance"))

			frappe.db.savepoint("coupon_redeem")
			try:
				_get_or_create_user(phone, full_name)

				card.is_used = 1
				card.status = "Redeemed"
				card.used_by_phone = phone
				card.scanned_at = now_datetime()
				card.save(ignore_permissions=True)

				credit = frappe.new_doc("Coupon Ledger")
				credit.phone = phone
				credit.type = "CREDIT"
				credit.points = points
				credit.description = f"Card {code} redeemed"
				credit.site_url = site_url
				credit.timestamp = now_datetime()
				credit.insert(ignore_permissions=True)

				debit = frappe.new_doc("Coupon Ledger")
				debit.phone = phone
				debit.type = "DEBIT"
				debit.points = amount
				debit.description = "Redeemed"
				debit.site_url = site_url
				debit.invoice_no = invoice_no
				debit.timestamp = now_datetime()
				debit.insert(ignore_permissions=True)
			except Exception:
				frappe.db.rollback(save_point="coupon_redeem")
				raise

		else:
			if not frappe.db.exists("Coupon User", phone):
				frappe.throw(_("User not found"))

			current_balance = _get_balance(phone)
			if current_balance < amount:
				frappe.throw(_("Insufficient balance"))

			frappe.db.savepoint("coupon_redeem")
			try:
				debit = frappe.new_doc("Coupon Ledger")
				debit.phone = phone
				debit.type = "DEBIT"
				debit.points = amount
				debit.description = "Redeemed"
				debit.site_url = site_url
				debit.invoice_no = invoice_no
				debit.timestamp = now_datetime()
				debit.insert(ignore_permissions=True)
			except Exception:
				frappe.db.rollback(save_point="coupon_redeem")
				raise

		return {
			"success": True,
			"redeemed": amount,
			"new_balance": _get_balance(phone),
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def reverse_redeem(invoice_no, site_url):
	"""
	Reverse a redemption when its Sales Invoice is cancelled.
	Creates a CREDIT entry to restore the points; preserves the original DEBIT
	so the full audit trail is intact.  Idempotent — safe to call more than once.
	"""
	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		debit = frappe.db.get_value(
			"Coupon Ledger",
			{"invoice_no": invoice_no, "site_url": site_url, "type": "DEBIT"},
			["name", "phone", "points"],
			as_dict=True,
		)
		if not debit:
			frappe.throw(_("No redemption found for this invoice"))

		# Idempotency: CREDIT with invoice_no means a reversal already exists
		if frappe.db.exists("Coupon Ledger", {
			"invoice_no": invoice_no,
			"site_url": site_url,
			"type": "CREDIT",
		}):
			frappe.throw(_("Reversal already processed for this invoice"))

		credit = frappe.new_doc("Coupon Ledger")
		credit.phone = debit.phone
		credit.type = "CREDIT"
		credit.points = debit.points
		credit.description = f"Reversal for invoice {invoice_no}"
		credit.site_url = site_url
		credit.invoice_no = invoice_no
		credit.timestamp = now_datetime()
		credit.insert(ignore_permissions=True)

		return {
			"success": True,
			"phone": debit.phone,
			"points_restored": debit.points,
			"new_balance": _get_balance(debit.phone),
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def campaign_card_counts(campaign):
	"""Lifecycle counts for a campaign, for the Coupon Campaign form dashboard."""
	roles = frappe.get_roles()
	if "System Manager" not in roles and "Coupon Manager" not in roles:
		frappe.throw(_("Not permitted"))

	CC = frappe.qb.DocType("Coupon Card")
	rows = (
		frappe.qb.from_(CC)
		.select(CC.status, frappe.qb.functions("COUNT", CC.name).as_("n"))
		.where(CC.campaign == campaign)
		.groupby(CC.status)
		.run(as_dict=True)
	)
	counts = {r.status: cint(r.n) for r in rows}
	active = counts.get("Active", 0)
	points = cint(frappe.db.get_value("Coupon Campaign", campaign, "points"))
	return {
		"total": sum(counts.values()),
		"generated": counts.get("Generated", 0),
		"active": active,
		"redeemed": counts.get("Redeemed", 0),
		"expired": counts.get("Expired", 0),
		"retired": counts.get("Retired", 0),
		"void": counts.get("Void", 0),
		"potential_points": active * points,  # if every Active card were scanned now
	}


@frappe.whitelist()
def get_card_images(codes, img_type="qr"):
	import json

	from coupon_system.utils import get_coupon_barcode, get_coupon_qr

	roles = frappe.get_roles()
	if "System Manager" not in roles and "Coupon Manager" not in roles:
		frappe.throw(_("Not permitted"))

	if isinstance(codes, str):
		codes = json.loads(codes)
	fn = get_coupon_qr if img_type == "qr" else get_coupon_barcode
	return {code: fn(code) for code in codes}


@frappe.whitelist()
def generate_cards(quantity, campaign, item_code=None, naming_series=None,
				   batch_no=None, work_order=None):
	"""Generate a single batch of coupon cards for a campaign.

	Points and expiry are derived from the campaign at generation (snapshot);
	the live point value is still resolved from the campaign at scan time.
	"""
	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		qty, pts, expiry = _validate_campaign_row({"quantity": quantity, "campaign": campaign})

		return _generate_batch(
			qty, item_code or "", pts, expiry,
			naming_series or "CC-.YYYY.-.#####",
			batch_no or "", work_order or "",
			campaign=campaign,
		)
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
	except Exception:
		# e.g. a unique-code IntegrityError under concurrent generation — return a
		# clean retryable error instead of a 500.
		frappe.log_error(frappe.get_traceback(), "Coupon generate_cards failed")
		return {"success": False, "error": _("Card generation failed — please retry")}


@frappe.whitelist()
def bulk_generate_cards(items):
	"""
	Generate multiple batches in one call.
	items: JSON list of {quantity, campaign, item_code, naming_series, batch_no, work_order}
	"""
	import json

	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		if isinstance(items, str):
			items = json.loads(items)

		if not items:
			frappe.throw(_("items list cannot be empty"))

		# Validate all rows before any DB writes
		validated = []
		for i, row in enumerate(items, start=1):
			try:
				qty, pts, expiry = _validate_campaign_row(row)
			except frappe.ValidationError as e:
				frappe.throw(_("Row {0}: {1}").format(i, str(e)))
			validated.append((qty, pts, expiry, row))

		# Shared seen-set prevents cross-batch collisions without loading all DB codes
		seen = set()
		now = now_datetime()
		user = frappe.session.user
		fields = [
			"name", "naming_series", "code", "campaign", "status", "item_code",
			"points_value", "expiry_date", "batch_no", "work_order", "is_used",
			"docstatus", "creation", "modified", "owner", "modified_by",
		]
		all_values = []

		for qty, pts, expiry, row in validated:
			series = row.get("naming_series") or "CC-.YYYY.-.#####"
			codes = _unique_codes(qty, seen)  # seen grows across rows
			for code in codes:
				all_values.append([
					make_autoname(series), series, code,
					row["campaign"], "Active", row.get("item_code") or "",
					pts, expiry, row.get("batch_no") or "", row.get("work_order") or "",
					0, 0, now, now, user, user,
				])

		frappe.db.bulk_insert("Coupon Card", fields=fields, values=all_values)
		codes = [row[2] for row in all_values]  # index 2 = code field
		return {"success": True, "count": len(codes), "codes": codes}
	except Exception as e:
		return {"success": False, "error": str(e)}


def _unique_codes(quantity, seen=None):
	"""
	Generate `quantity` unique XXXX-XXXX codes.

	Only checks *candidate* codes against the DB — O(quantity) memory regardless
	of total cards in the table.  `seen` is a mutable set the caller can pass in
	to avoid cross-batch collisions inside bulk_generate_cards.
	"""
	if seen is None:
		seen = set()

	result = []
	CC = frappe.qb.DocType("Coupon Card")

	while len(result) < quantity:
		# Overshoot by 3× to minimise round-trips; collision rate is negligible
		# for XXXX-XXXX (36^8 ≈ 2.8 trillion combinations).
		candidates = list({_generate_code() for _ in range((quantity - len(result)) * 3)})
		candidates = [c for c in candidates if c not in seen]

		if not candidates:
			continue  # astronomically unlikely — all candidates were in seen

		taken = {
			r[0]
			for r in frappe.qb.from_(CC)
			.select(CC.code)
			.where(CC.code.isin(candidates))
			.run()
		}
		fresh = [c for c in candidates if c not in taken]
		batch = fresh[: quantity - len(result)]
		result.extend(batch)
		seen.update(batch)

	return result


def _generate_batch(quantity, item_code, points_value, expiry_date,
					naming_series, batch_no, work_order, source_stock_entry="",
					campaign="", status="Active"):
	codes = _unique_codes(quantity)

	now = now_datetime()
	user = frappe.session.user
	fields = [
		"name", "naming_series", "code", "campaign", "status", "item_code",
		"points_value", "expiry_date", "batch_no", "work_order", "source_stock_entry",
		"is_used", "docstatus", "creation", "modified", "owner", "modified_by",
	]
	values = [
		[make_autoname(naming_series), naming_series, code, campaign, status, item_code,
		 points_value, expiry_date, batch_no, work_order, source_stock_entry,
		 0, 0, now, now, user, user]
		for code in codes
	]
	frappe.db.bulk_insert("Coupon Card", fields=fields, values=values)
	return {"success": True, "count": len(codes), "codes": codes}
