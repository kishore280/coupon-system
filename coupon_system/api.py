import random
import string

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.query_builder import Order
from frappe.query_builder.functions import Sum
from frappe.utils import flt, getdate, now_datetime, today


def _get_balance(phone):
	CL = frappe.qb.DocType("Coupon Ledger")
	rows = (
		frappe.qb.from_(CL)
		.select(CL.type, Sum(CL.points).as_("total"))
		.where(CL.phone == phone)
		.groupby(CL.type)
		.run(as_dict=True)
	)
	totals = {r.type: flt(r.total) for r in rows}
	return totals.get("CREDIT", 0.0) - totals.get("DEBIT", 0.0)


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
	part1 = "".join(random.choices(chars, k=4))
	part2 = "".join(random.choices(chars, k=4))
	return f"PAINT-{part1}-{part2}"


@frappe.whitelist()
def scan(phone, code, full_name=None):
	try:
		card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
		if not card_name:
			frappe.throw(_("Card not found"))

		card = frappe.get_doc("Coupon Card", card_name)

		if getdate(card.expiry_date) < getdate(today()):
			frappe.throw(_("Card expired"))

		if card.is_used:
			frappe.throw(_("Card already redeemed"))

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
		amount = flt(amount)

		if frappe.db.exists("Coupon Ledger", {"invoice_no": invoice_no, "type": "DEBIT"}):
			frappe.throw(_("Already redeemed for this invoice"))

		if code:
			card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
			if not card_name:
				frappe.throw(_("Card not found"))

			card = frappe.get_doc("Coupon Card", card_name)

			if getdate(card.expiry_date) < getdate(today()):
				frappe.throw(_("Card expired"))

			if card.is_used:
				frappe.throw(_("Card already redeemed"))

			if flt(card.points_value) < amount:
				frappe.throw(_("Insufficient balance"))

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

		else:
			if not frappe.db.exists("Coupon User", phone):
				frappe.throw(_("User not found"))

			current_balance = _get_balance(phone)
			if current_balance < amount:
				frappe.throw(_("Insufficient balance"))

		debit = frappe.new_doc("Coupon Ledger")
		debit.phone = phone
		debit.type = "DEBIT"
		debit.points = amount
		debit.description = f"Redeemed at {branch}"
		debit.branch = branch
		debit.invoice_no = invoice_no
		debit.timestamp = now_datetime()
		debit.insert(ignore_permissions=True)

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

	if isinstance(codes, str):
		codes = json.loads(codes)
	fn = get_coupon_qr if img_type == "qr" else get_coupon_barcode
	return {code: fn(code) for code in codes}


@frappe.whitelist()
def generate_cards(items):
	"""
	items: list of {quantity, item_code, points_value, expiry_date,
	                naming_series, batch_no, work_order}
	Each row generates `quantity` unique coupon cards.
	"""
	import json

	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		if isinstance(items, str):
			items = json.loads(items)

		# Load all existing codes once to avoid collisions across rows
		CC = frappe.qb.DocType("Coupon Card")
		existing_codes = {r[0] for r in frappe.qb.from_(CC).select(CC.code).run()}

		now = now_datetime()
		user = frappe.session.user
		fields = [
			"name", "naming_series", "code", "item_code", "points_value",
			"expiry_date", "batch_no", "work_order", "is_used", "docstatus",
			"creation", "modified", "owner", "modified_by",
		]
		all_values = []

		for row in items:
			quantity = int(row["quantity"])
			item_code = row["item_code"]
			points_value = flt(row["points_value"])
			expiry_date = row["expiry_date"]
			batch_no = row.get("batch_no") or ""
			work_order = row.get("work_order") or ""
			series = row.get("naming_series") or "CC-.YYYY.-.#####"

			codes = []
			attempts = 0
			max_attempts = quantity * 20
			while len(codes) < quantity and attempts < max_attempts:
				code = _generate_code()
				if code not in existing_codes:
					codes.append(code)
					existing_codes.add(code)
				attempts += 1

			if len(codes) < quantity:
				frappe.throw(_("Could not generate enough unique codes for row {0}. Try again.").format(item_code))

			for code in codes:
				name = make_autoname(series)
				all_values.append([
					name, series, code, item_code, points_value, expiry_date,
					batch_no, work_order, 0, 0, now, now, user, user,
				])

		frappe.db.bulk_insert("Coupon Card", fields=fields, values=all_values)

		return {"success": True, "count": len(all_values)}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}
