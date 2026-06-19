import base64
from io import BytesIO

import qrcode
import frappe


def get_coupon_qr(code):
	base_url = frappe.db.get_single_value("Coupon System Settings", "scan_base_url")
	if not base_url:
		frappe.throw(frappe._("Coupon System Settings: scan_base_url is not configured"))
	url = f"{base_url.rstrip('/')}/{code}"
	img = qrcode.make(url)
	buffer = BytesIO()
	img.save(buffer, format="PNG")
	encoded = base64.b64encode(buffer.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"


def get_coupon_barcode(code):
	import barcode
	from barcode.writer import ImageWriter

	base_url = frappe.db.get_single_value("Coupon System Settings", "scan_base_url")
	if not base_url:
		frappe.throw(frappe._("Coupon System Settings: scan_base_url is not configured"))
	url = f"{base_url.rstrip('/')}/{code}"

	bar = barcode.get("code128", url, writer=ImageWriter())
	buffer = BytesIO()
	bar.write(buffer, options={"write_text": False, "quiet_zone": 2, "module_height": 10})
	encoded = base64.b64encode(buffer.getvalue()).decode()
	return f"data:image/png;base64,{encoded}"
