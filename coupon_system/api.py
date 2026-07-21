import secrets

import frappe
from frappe import _
from frappe.model.naming import make_autoname
from frappe.query_builder import Order
from frappe.query_builder.functions import Sum
from frappe.utils import add_months, cint, flt, getdate, now_datetime, today


def _buckets(phone):
	"""Net points per bucket for a phone: {None: general, "<store>": locked, ...}.

	The (phone, bucket_store) pair is the account address (ADR-0003). bucket_store is
	blank for general points (central coupons, spendable anywhere) or a Coupon Store for
	store-locked points. A CREDIT adds to its bucket; a DEBIT subtracts from it.
	"""
	CL = frappe.qb.DocType("Coupon Ledger")
	rows = (
		frappe.qb.from_(CL)
		.select(CL.bucket_store, CL.type, Sum(CL.points).as_("total"))
		.where(CL.phone == phone)
		.groupby(CL.bucket_store, CL.type)
		.run(as_dict=True)
	)
	buckets = {}
	for r in rows:
		key = r.bucket_store or None
		sign = 1 if r.type == "CREDIT" else -1
		buckets[key] = buckets.get(key, 0) + sign * cint(r.total)
	return buckets


def _get_balance(phone):
	"""Total wallet balance across every bucket - the number the app shows as the total."""
	return sum(_buckets(phone).values())


def _available_at(phone, store):
	"""Points spendable at `store` = general + that store's locked bucket. Points locked
	to OTHER stores are excluded (they're frozen away from their store)."""
	buckets = _buckets(phone)
	return buckets.get(None, 0) + (buckets.get(store, 0) if store else 0)


def _withdrawable(phone):
	"""Points eligible for cash-out. Launch scope: general points ONLY - store-locked
	points are not withdrawable (store cash-out is deferred)."""
	return _buckets(phone).get(None, 0)


def _get_locked_withdrawal_points(phone):
	"""Points already tied up in this phone's own Pending withdrawal requests -
	the "reserved" half of available = ledger balance - locked. Paid requests are
	excluded (already reflected in the ledger itself, would double-count) and
	Rejected requests are excluded (never actually held anything, once closed)."""
	return cint(frappe.db.get_value(
		"Coupon Withdrawal Request", {"phone": phone, "status": "Pending"}, ["sum(points)"]
	) or 0)


def _get_available_balance(phone):
	"""Withdrawable balance = general points minus points already locked in Pending
	withdrawal requests. Store-locked points are excluded (not withdrawable at launch)."""
	return _withdrawable(phone) - _get_locked_withdrawal_points(phone)


def _post_ledger(phone, entry_type, points, description, site_url=None, invoice_no=None,
				 bucket_store=None):
	"""The one place that writes a Coupon Ledger row. site_url = where the transaction
	happened (redeem context); bucket_store = which account the points belong to (blank =
	general, else a store). Both optional - a withdrawal or central earn simply omits them."""
	entry = frappe.new_doc("Coupon Ledger")
	entry.phone = phone
	entry.type = entry_type
	entry.points = points
	entry.description = description
	entry.site_url = site_url
	entry.bucket_store = bucket_store
	entry.invoice_no = invoice_no
	entry.timestamp = now_datetime()
	entry.insert(ignore_permissions=True)
	return entry


def _debit_buckets(phone, amount, store, invoice_no, description="Redeemed", buckets=None):
	"""Spend `amount` points at `store`, draining that store's locked bucket FIRST, then
	general - so store-locked points never get stranded. Posts up to two DEBIT rows (one
	per bucket touched) to keep the buckets exact and fully auditable; both carry the same
	invoice_no and site_url = the redeeming store. Caller must already hold the user row
	lock and have checked availability. Pass `buckets` to avoid recomputing the aggregate."""
	if buckets is None:
		buckets = _buckets(phone)
	from_store = min(amount, max(buckets.get(store, 0), 0)) if store else 0
	from_general = amount - from_store
	if from_store > 0:
		_post_ledger(phone, "DEBIT", from_store, description, site_url=store,
					 invoice_no=invoice_no, bucket_store=store)
	if from_general > 0:
		_post_ledger(phone, "DEBIT", from_general, description, site_url=store,
					 invoice_no=invoice_no, bucket_store=None)


def _get_or_create_user(phone, full_name=None):
	if frappe.db.exists("Coupon User", phone):
		return frappe.get_doc("Coupon User", phone)
	user = frappe.new_doc("Coupon User")
	user.phone = phone
	user.full_name = full_name or ""
	user.insert(ignore_permissions=True)
	return user


def _resolve_card_points(card):
	"""Resolve the point value of a card.

	Store coupons carry a value SNAPSHOT frozen at mint (gift-card model, ADR-0003 / D1):
	their value is never re-resolved from a campaign, so editing a store campaign can't
	revalue coupons already in customers' hands. Central cards resolve LIVE from their
	campaign (the dynamic dial), falling back to the snapshot only if unlinked.
	"""
	if card.get("origin") == "Store":
		return cint(card.get("points_value"))
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


def _get_campaign_allowed_site_urls(campaign):
	"""Site URLs a campaign is restricted to. Empty set = unrestricted (default).

	Coupon Store is autonamed by site_url, so the Coupon Campaign Store child
	table's `store` Link values already ARE the site_url strings - no separate
	lookup needed to translate a store name into its site_url."""
	return set(frappe.get_all(
		"Coupon Campaign Store", filters={"parent": campaign}, pluck="store"
	))


def _assert_card_scannable(card, site_url=None):
	"""Raise if a card cannot be earned/redeemed right now (lifecycle + expiry + store).

	site_url is only checked when passed — the scan (earn) flow leaves it None and
	is never store-restricted; only redeem() passes it through.
	"""
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
	if site_url and card.get("campaign"):
		allowed = _get_campaign_allowed_site_urls(card.campaign)
		if allowed and site_url not in allowed:
			frappe.throw(_("This card cannot be redeemed at this store"))


# Unambiguous, no-vowel alphabet (Crockford base32 minus vowels, per the de-facto
# standard for human-transmitted codes). No 0/O, 1/I/L → can't be misread on a
# printed card; no vowels → can't spell a real or offensive word.
_CODE_CHARS = "23456789BCDFGHJKMNPQRSTVWXZ"


def _generate_code(prefix=""):
	part1 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
	part2 = "".join(secrets.choice(_CODE_CHARS) for _ in range(4))
	body = f"{part1}-{part2}"
	return f"{prefix}-{body}" if prefix else body


def _code_prefix():
	"""Sanitised brand prefix from settings (alphanumeric, upper-case), or ''."""
	raw = frappe.db.get_single_value("Coupon System Settings", "code_prefix") or ""
	return "".join(ch for ch in raw.upper() if ch.isalnum())


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

			# Store coupons lock their points to the issuing store; central coupons are general.
			bucket = card.store if card.get("origin") == "Store" else None
			_post_ledger(phone, "CREDIT", points, f"Card {code} scanned", bucket_store=bucket)
		except Exception:
			frappe.db.rollback(save_point="coupon_scan")
			raise

		return {
			"success": True,
			"points_added": points,
			"locked_to_store": card.store if card.get("origin") == "Store" else None,
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

		# Partition the wallet into buckets: general (spendable anywhere) + one entry per
		# store the customer holds locked points at. The app shows the total + this breakdown.
		buckets = _buckets(phone)
		general = buckets.get(None, 0)
		store_ids = [s for s in buckets if s is not None and buckets[s] > 0]
		names = {
			r.name: r.store_name
			for r in frappe.get_all(
				"Coupon Store", filters={"name": ["in", store_ids]}, fields=["name", "store_name"]
			)
		} if store_ids else {}
		restricted = [
			{"store": s, "store_name": names.get(s) or s, "points": buckets[s]}
			for s in store_ids
		]

		ledger_entries = (
			frappe.qb.from_(CL)
			.select(CL.type, CL.points, CL.description, CL.site_url, CL.bucket_store,
					CL.invoice_no, CL.timestamp)
			.where(CL.phone == phone)
			.orderby(CL.timestamp, order=Order.desc)
			.limit(20)
			.run(as_dict=True)
		)

		# Banked points never expire at launch (Clock B deferred); a card's expiry_date only
		# governs UNSCANNED cards. Kept in the response as an honest 0.
		return {
			"success": True,
			"phone": phone,
			"full_name": user.full_name,
			"points_balance": sum(buckets.values()),
			"general": general,
			"restricted": restricted,
			"total_earned": total_earned,
			"total_redeemed": total_redeemed,
			"points_expiring_soon": 0,
			"ledger": ledger_entries,
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def redeem(phone, amount, site_url, invoice_no, code=None, full_name=None):
	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		if not phone or not isinstance(phone, str) or not phone.strip():
			frappe.throw(_("phone is required"))

		if not site_url or not isinstance(site_url, str) or not site_url.strip():
			frappe.throw(_("site_url is required"))

		if not invoice_no or not isinstance(invoice_no, str) or not invoice_no.strip():
			frappe.throw(_("invoice_no is required"))

		amount = cint(amount)
		if amount <= 0:
			frappe.throw(_("Redemption amount must be greater than 0"))

		if frappe.db.exists("Coupon Ledger", {"invoice_no": invoice_no, "site_url": site_url, "type": "DEBIT"}):
			frappe.throw(_("Already redeemed for this invoice"))

		if code:
			# Legacy path (ADR-0002 D3, left intact): redeem a physical card directly at a store.
			card_name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
			if not card_name:
				frappe.throw(_("Card not found"))

			# Lock the row before reading so concurrent redemptions can't both see is_used=0
			frappe.db.sql("SELECT name FROM `tabCoupon Card` WHERE name = %s FOR UPDATE", card_name)
			card = frappe.get_doc("Coupon Card", card_name)

			_assert_card_scannable(card, site_url=site_url)

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

				_post_ledger(phone, "CREDIT", points, f"Card {code} redeemed", site_url=site_url)
				_debit_buckets(phone, amount, site_url, invoice_no)
			except Exception:
				frappe.db.rollback(save_point="coupon_redeem")
				raise

		else:
			if not frappe.db.exists("Coupon User", phone):
				frappe.throw(_("User not found"))

			# Lock the user row so two concurrent redemptions can't both read the same
			# balance and overspend. (Withdrawal already locks; redeem must too.)
			frappe.get_doc("Coupon User", phone, for_update=True)

			# One aggregate read, reused for the availability check and the debit split.
			# Spendable here = general + this store's locked bucket; other stores excluded.
			buckets = _buckets(phone)
			if buckets.get(None, 0) + max(buckets.get(site_url, 0), 0) < amount:
				frappe.throw(_("Insufficient balance"))

			frappe.db.savepoint("coupon_redeem")
			try:
				_debit_buckets(phone, amount, site_url, invoice_no, buckets=buckets)
			except Exception:
				frappe.db.rollback(save_point="coupon_redeem")
				raise

		after = _buckets(phone)
		return {
			"success": True,
			"redeemed": amount,
			"new_balance": sum(after.values()),
			"available_here": after.get(None, 0) + max(after.get(site_url, 0), 0),
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

		if not invoice_no or not isinstance(invoice_no, str) or not invoice_no.strip():
			frappe.throw(_("invoice_no is required"))

		if not site_url or not isinstance(site_url, str) or not site_url.strip():
			frappe.throw(_("site_url is required"))

		# A redemption may be split across buckets (store-locked + general), i.e. MORE than
		# one DEBIT row for the same invoice - reverse every one into its own bucket.
		debits = frappe.get_all(
			"Coupon Ledger",
			filters={"invoice_no": invoice_no, "site_url": site_url, "type": "DEBIT"},
			fields=["phone", "points", "bucket_store"],
		)
		if not debits:
			frappe.throw(_("No redemption found for this invoice"))

		# Idempotency: a CREDIT tagged with this invoice means a reversal already ran.
		if frappe.db.exists("Coupon Ledger", {
			"invoice_no": invoice_no,
			"site_url": site_url,
			"type": "CREDIT",
		}):
			frappe.throw(_("Reversal already processed for this invoice"))

		phone = debits[0].phone
		restored = 0
		for d in debits:
			_post_ledger(d.phone, "CREDIT", d.points, f"Reversal for invoice {invoice_no}",
						 site_url=site_url, invoice_no=invoice_no, bucket_store=d.bucket_store)
			restored += cint(d.points)

		return {
			"success": True,
			"phone": phone,
			"points_restored": restored,
			"new_balance": _get_balance(phone),
		}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def request_withdrawal(phone, points, payout_details):
	"""Create a Pending cash-out request for a phone's points balance.

	No ledger entry is written here - the points are only *locked* (excluded from
	future available-balance checks via _get_locked_withdrawal_points), not spent.
	The single Coupon Ledger DEBIT is written by Coupon Withdrawal Request's own
	controller, exactly once, only when staff transitions it to Paid.
	"""
	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		if not frappe.db.get_single_value("Coupon System Settings", "enable_withdrawals"):
			frappe.throw(_("Withdrawals are currently disabled"))

		if not phone or not isinstance(phone, str) or not phone.strip():
			frappe.throw(_("phone is required"))

		points = cint(points)
		if points <= 0:
			frappe.throw(_("points must be a positive integer"))

		if not payout_details or not isinstance(payout_details, str) or not payout_details.strip():
			frappe.throw(_("payout_details is required"))

		if not frappe.db.exists("Coupon User", phone):
			frappe.throw(_("User not found"))

		# Lock the Coupon User row so two concurrent requests from the same phone
		# can't both read the same available balance and both get created.
		frappe.get_doc("Coupon User", phone, for_update=True)

		if points > _get_available_balance(phone):
			frappe.throw(_("Insufficient balance"))

		request = frappe.new_doc("Coupon Withdrawal Request")
		request.phone = phone
		request.points = points
		request.payout_details = payout_details
		request.insert(ignore_permissions=True)

		return {
			"success": True,
			"request": request.name,
			"amount": request.amount,
			"available_balance": _get_available_balance(phone),
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
				   batch_no=None, work_order=None, origin="Central", store=None):
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
			campaign=campaign, origin=origin, store=store or "",
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
			"points_value", "expiry_date", "batch_no", "work_order",
			"origin", "store",
			"is_used", "docstatus", "creation", "modified", "owner", "modified_by",
		]
		all_values = []

		for qty, pts, expiry, row in validated:
			series = row.get("naming_series") or "CC-.YYYY.-.#####"
			origin = row.get("origin") or "Central"
			store = row.get("store") or ""
			prefix = _code_prefix()
			if origin == "Store" and store:
				ns = frappe.db.get_value("Coupon Store", store, "code_namespace")
				if ns:
					prefix = f"{prefix}-{ns}" if prefix else ns
			codes = _unique_codes(qty, seen, code_prefix=prefix)  # seen grows across rows
			for code in codes:
				all_values.append([
					make_autoname(series), series, code,
					row["campaign"], "Active", row.get("item_code") or "",
					pts, expiry, row.get("batch_no") or "", row.get("work_order") or "",
					origin, store,
					0, 0, now, now, user, user,
				])

		frappe.db.bulk_insert("Coupon Card", fields=fields, values=all_values)
		codes = [row[2] for row in all_values]  # index 2 = code field
		return {"success": True, "count": len(codes), "codes": codes}
	except Exception as e:
		return {"success": False, "error": str(e)}


def _unique_codes(quantity, seen=None, code_prefix=None):
	"""
	Generate `quantity` unique XXXX-XXXX codes.

	Only checks *candidate* codes against the DB — O(quantity) memory regardless
	of total cards in the table.  `seen` is a mutable set the caller can pass in
	to avoid cross-batch collisions inside bulk_generate_cards.
	"""
	if seen is None:
		seen = set()

	prefix = code_prefix if code_prefix is not None else _code_prefix()  # fetched once, not per-code
	result = []
	CC = frappe.qb.DocType("Coupon Card")

	while len(result) < quantity:
		# Overshoot by 3× to minimise round-trips; collision rate is negligible
		# for XXXX-XXXX (27^8 ≈ 282 billion combinations).
		candidates = list({_generate_code(prefix) for _ in range((quantity - len(result)) * 3)})
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
					campaign="", status="Active", origin="Central", store="", source_invoice=""):
	# Store coupons carry a store-namespaced prefix so independent minting never collides.
	prefix = _code_prefix()
	if origin == "Store" and store:
		ns = frappe.db.get_value("Coupon Store", store, "code_namespace")
		if ns:
			prefix = f"{prefix}-{ns}" if prefix else ns
	codes = _unique_codes(quantity, code_prefix=prefix)

	now = now_datetime()
	user = frappe.session.user
	fields = [
		"name", "naming_series", "code", "campaign", "status", "item_code",
		"points_value", "expiry_date", "batch_no", "work_order", "source_stock_entry",
		"origin", "store", "source_invoice",
		"is_used", "docstatus", "creation", "modified", "owner", "modified_by",
	]
	values = [
		[make_autoname(naming_series), naming_series, code, campaign, status, item_code,
		 points_value, expiry_date, batch_no, work_order, source_stock_entry,
		 origin, store, source_invoice,
		 0, 0, now, now, user, user]
		for code in codes
	]
	frappe.db.bulk_insert("Coupon Card", fields=fields, values=values)
	return {"success": True, "count": len(codes), "codes": codes}


@frappe.whitelist()
def register_cards(store, cards):
	"""Register a store's immutable card DEFINITIONS on HQ (ADR-0002/0003).

	The store mints locally with a store-namespaced code, then calls this so HQ can resolve
	a scan on its own (keeps the mobile client dumb-simple). Idempotent per code - the unique
	index on `code` is the real backstop, so a retry never double-inserts.
	"""
	import json

	try:
		roles = frappe.get_roles()
		if "System Manager" not in roles and "Coupon Manager" not in roles:
			frappe.throw(_("Not permitted"))

		if not store or not frappe.db.exists("Coupon Store", store):
			frappe.throw(_("Unknown store"))
		if not frappe.db.get_value("Coupon Store", store, "is_active"):
			frappe.throw(_("Store {0} is not active").format(store))
		namespace = frappe.db.get_value("Coupon Store", store, "code_namespace")

		if isinstance(cards, str):
			cards = json.loads(cards)
		if not cards:
			frappe.throw(_("cards list cannot be empty"))

		registered, skipped = [], []
		for row in cards:
			code = (row.get("code") or "").strip()
			if not code:
				frappe.throw(_("each card needs a code"))
			if namespace and namespace not in code.split("-"):
				frappe.throw(_("Code {0} does not carry store namespace {1}").format(code, namespace))
			if not row.get("expiry_date"):
				frappe.throw(_("Code {0} is missing expiry_date").format(code))

			# Idempotent: skip a code HQ already knows (retry-safe).
			if frappe.db.exists("Coupon Card", {"code": code}):
				skipped.append(code)
				continue

			card = frappe.new_doc("Coupon Card")
			card.naming_series = "CC-.YYYY.-.#####"
			card.code = code
			card.origin = "Store"
			card.store = store
			card.status = "Active"
			card.points_value = cint(row.get("points_value"))
			card.expiry_date = row.get("expiry_date")
			card.item_code = row.get("item_code")
			# The campaign is the store's; only link it if HQ happens to know it - otherwise
			# value comes from the points_value snapshot (D1).
			camp = row.get("campaign")
			if camp and frappe.db.exists("Coupon Campaign", camp):
				card.campaign = camp

			# The unique index on `code` is the real backstop: under a concurrent
			# double-register the loser hits an IntegrityError - treat that as "already there"
			# rather than letting it escape as a 500.
			frappe.db.savepoint("reg_card")
			try:
				card.insert(ignore_permissions=True)
				registered.append(code)
			except Exception:
				frappe.db.rollback(save_point="reg_card")
				if frappe.db.exists("Coupon Card", {"code": code}):
					skipped.append(code)
				else:
					raise

		return {"success": True, "registered": registered, "skipped": skipped}
	except frappe.ValidationError as e:
		return {"success": False, "error": str(e)}


@frappe.whitelist()
def mark_given(code, invoice_no):
	"""Traceability: record that a store coupon was handed out with a Sales Invoice by
	stamping source_invoice on the card. Idempotent - re-stamping is a no-op."""
	roles = frappe.get_roles()
	if "System Manager" not in roles and "Coupon Manager" not in roles:
		frappe.throw(_("Not permitted"))
	name = frappe.db.get_value("Coupon Card", {"code": code}, "name")
	if not name:
		frappe.throw(_("Card not found"))
	frappe.db.set_value("Coupon Card", name, "source_invoice", invoice_no)
	return {"success": True, "code": code, "source_invoice": invoice_no}


@frappe.whitelist()
def store_card_counts(store):
	"""Lifecycle counts for a store's registered coupons, so a store can see its own stock
	(HQ is the source of truth for used/unused - the store's local card status is cosmetic)."""
	roles = frappe.get_roles()
	if "System Manager" not in roles and "Coupon Manager" not in roles:
		frappe.throw(_("Not permitted"))
	CC = frappe.qb.DocType("Coupon Card")
	rows = (
		frappe.qb.from_(CC)
		.select(CC.status, frappe.qb.functions("COUNT", CC.name).as_("n"))
		.where((CC.origin == "Store") & (CC.store == store))
		.groupby(CC.status)
		.run(as_dict=True)
	)
	counts = {r.status: cint(r.n) for r in rows}
	return {
		"success": True,
		"store": store,
		"active": counts.get("Active", 0),
		"redeemed": counts.get("Redeemed", 0),
		"expired": counts.get("Expired", 0),
		"retired": counts.get("Retired", 0),
		"void": counts.get("Void", 0),
		"total": sum(counts.values()),
	}
