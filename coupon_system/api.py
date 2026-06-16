import secrets
import string

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.query_builder import Order
from frappe.query_builder.functions import Sum
from frappe.utils import cint, flt, getdate, now_datetime, today


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


def _generate_code():
	chars = string.ascii_uppercase + string.digits
	part1 = "".join(secrets.choice(chars) for _ in range(4))
	part2 = "".join(secrets.choice(chars) for _ in range(4))
	return f"PAINT-{part1}-{part2}"


def _validate_card_row(row):
	"""Validate one batch-row dict. Raises frappe.ValidationError on bad input."""
	try:
		qty = int(row["quantity"])
	except (KeyError, TypeError, ValueError):
		frappe.throw(_("quantity must be a positive integer"))
	if qty <= 0:
		frappe.throw(_("quantity must be a positive integer"))
	if qty > 10_000:
		frappe.throw(_("quantity cannot exceed 10,000 per call"))

	if not row.get("item_code"):
		frappe.throw(_("item_code is required"))

	try:
		pts = cint(row.get("points_value", 0))
	except (TypeError, ValueError):
		frappe.throw(_("points_value must be a positive integer"))
	if pts <= 0:
		frappe.throw(_("points_value must be a positive integer"))

	expiry = row.get("expiry_date")
	if not expiry:
		frappe.throw(_("expiry_date is required"))
	if getdate(expiry) < getdate(today()):
		frappe.throw(_("expiry_date must be in the future"))

	return qty, pts, expiry


@frappe.whitelist()
def scan(phone, code, full_name=None):
	try:
		if not phone or not str(phone).strip():
			frappe.throw(_("phone is required"))

		card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
		if not card_name:
			frappe.throw(_("Card not found"))

		# Lock the row before reading so concurrent scans can't both see is_used=0
		frappe.db.sql("SELECT name FROM `tabCoupon Card` WHERE name = %s FOR UPDATE", card_name)
		card = frappe.get_doc("Coupon Card", card_name)

		if getdate(card.expiry_date) < getdate(today()):
			frappe.throw(_("Card expired"))

		if card.is_used:
			frappe.throw(_("Card already redeemed"))

		# _get_or_create_user is inside the savepoint so a write failure rolls it back
		frappe.db.savepoint("coupon_scan")
		try:
			_get_or_create_user(phone, full_name)

			card.is_used = 1
			card.used_by_phone = phone
			card.scanned_at = now_datetime()
			card.save(ignore_permissions=True)

			ledger = frappe.new_doc("Coupon Ledger")
			ledger.phone = phone
			ledger.type = "CREDIT"
			ledger.points = card.points_value
			ledger.description = f"Card {code} scanned"
			ledger.timestamp = now_datetime()
			ledger.insert(ignore_permissions=True)
		except Exception:
			frappe.db.rollback(save_point="coupon_scan")
			raise

		return {
			"success": True,
			"points_added": card.points_value,
			"new_balance": _get_balance(phone),
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def balance(phone):
	try:
		if not frappe.db.exists("Coupon User", phone):
			frappe.throw(_("User not found"))

		user = frappe.get_doc("Coupon User", phone)

		CL = frappe.qb.DocType("Coupon Ledger")
		ledger_entries = (
			frappe.qb.from_(CL)
			.select(CL.type, CL.points, CL.description, CL.branch, CL.invoice_no, CL.timestamp)
			.where(CL.phone == phone)
			.orderby(CL.timestamp, order=Order.desc)
			.limit(20)
			.run(as_dict=True)
		)

		return {
			"success": True,
			"phone": phone,
			"full_name": user.full_name,
			"points_balance": _get_balance(phone),
			"ledger": ledger_entries,
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def redeem(phone, amount, branch, invoice_no, code=None):
	try:
		if not phone or not str(phone).strip():
			frappe.throw(_("phone is required"))

		amount = cint(amount)
		if amount <= 0:
			frappe.throw(_("Redemption amount must be greater than 0"))

		if frappe.db.exists("Coupon Ledger", {"invoice_no": invoice_no, "type": "DEBIT"}):
			frappe.throw(_("Already redeemed for this invoice"))

		if code:
			card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
			if not card_name:
				frappe.throw(_("Card not found"))

			# Lock the row before reading so concurrent redemptions can't both see is_used=0
			frappe.db.sql("SELECT name FROM `tabCoupon Card` WHERE name = %s FOR UPDATE", card_name)
			card = frappe.get_doc("Coupon Card", card_name)

			if getdate(card.expiry_date) < getdate(today()):
				frappe.throw(_("Card expired"))

			if card.is_used:
				frappe.throw(_("Card already redeemed"))

			if cint(card.points_value) < amount:
				frappe.throw(_("Insufficient balance"))

			frappe.db.savepoint("coupon_redeem")
			try:
				_get_or_create_user(phone)

				card.is_used = 1
				card.used_by_phone = phone
				card.scanned_at = now_datetime()
				card.save(ignore_permissions=True)

				credit = frappe.new_doc("Coupon Ledger")
				credit.phone = phone
				credit.type = "CREDIT"
				credit.points = card.points_value
				credit.description = f"Card {code} redeemed at branch"
				credit.branch = branch
				credit.timestamp = now_datetime()
				credit.insert(ignore_permissions=True)

				debit = frappe.new_doc("Coupon Ledger")
				debit.phone = phone
				debit.type = "DEBIT"
				debit.points = amount
				debit.description = f"Redeemed at {branch}"
				debit.branch = branch
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
				debit.description = f"Redeemed at {branch}"
				debit.branch = branch
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
def generate_cards(quantity, item_code, points_value, expiry_date,
				   naming_series=None, batch_no=None, work_order=None):
	"""Generate a single batch of coupon cards. Original signature kept for backward compat."""
	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		qty, pts, expiry = _validate_card_row({
			"quantity": quantity,
			"item_code": item_code,
			"points_value": points_value,
			"expiry_date": expiry_date,
		})

		return _generate_batch(
			qty, item_code, pts, expiry,
			naming_series or "CC-.YYYY.-.#####",
			batch_no or "", work_order or "",
		)
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def bulk_generate_cards(items):
	"""
	Generate multiple batches in one call.
	items: JSON list of {quantity, item_code, points_value, expiry_date,
	                     naming_series, batch_no, work_order}
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
				qty, pts, expiry = _validate_card_row(row)
			except frappe.ValidationError as e:
				frappe.throw(_("Row {0}: {1}").format(i, str(e)))
			validated.append((qty, pts, expiry, row))

		# Shared seen-set prevents cross-batch collisions without loading all DB codes
		seen = set()
		now = now_datetime()
		user = frappe.session.user
		fields = [
			"name", "naming_series", "code", "item_code", "points_value",
			"expiry_date", "batch_no", "work_order", "is_used", "docstatus",
			"creation", "modified", "owner", "modified_by",
		]
		all_values = []

		for qty, pts, expiry, row in validated:
			series = row.get("naming_series") or "CC-.YYYY.-.#####"
			codes = _unique_codes(qty, seen)  # seen grows across rows
			for code in codes:
				all_values.append([
					make_autoname(series), series, code,
					row["item_code"], pts, expiry,
					row.get("batch_no") or "", row.get("work_order") or "",
					0, 0, now, now, user, user,
				])

		frappe.db.bulk_insert("Coupon Card", fields=fields, values=all_values)
		codes = [row[2] for row in all_values]  # index 2 = code field
		return {"success": True, "count": len(codes), "codes": codes}
	except Exception as e:
		return {"success": False, "error": str(e)}


def _unique_codes(quantity, seen=None):
	"""
	Generate `quantity` unique PAINT-XXXX-XXXX codes.

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
		# for PAINT-XXXX-XXXX (36^8 ≈ 2.8 trillion combinations).
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
					naming_series, batch_no, work_order):
	codes = _unique_codes(quantity)

	now = now_datetime()
	user = frappe.session.user
	fields = [
		"name", "naming_series", "code", "item_code", "points_value",
		"expiry_date", "batch_no", "work_order", "is_used", "docstatus",
		"creation", "modified", "owner", "modified_by",
	]
	values = [
		[make_autoname(naming_series), naming_series, code, item_code, points_value,
		 expiry_date, batch_no, work_order, 0, 0, now, now, user, user]
		for code in codes
	]
	frappe.db.bulk_insert("Coupon Card", fields=fields, values=values)
	return {"success": True, "count": len(codes), "codes": codes}
