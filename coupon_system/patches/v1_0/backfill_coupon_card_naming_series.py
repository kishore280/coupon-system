import frappe


def execute():
	frappe.db.sql("""
		UPDATE `tabCoupon Card`
		SET naming_series = 'CC-.YYYY.-.#####'
		WHERE naming_series IS NULL OR naming_series = ''
	""")
