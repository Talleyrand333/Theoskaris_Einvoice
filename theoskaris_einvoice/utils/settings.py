"""FIRS Settings helpers."""

import frappe


def is_firs_enabled_for(doctype: str) -> bool:
	"""Check if FIRS e-Invoicing is enabled for a given doctype."""
	try:
		settings = frappe.get_single("FIRS Settings")
	except frappe.DoesNotExistError:
		return True  # Default to enabled if settings doc doesn't exist

	if doctype == "Sales Invoice":
		return bool(settings.get("enable_sales_invoice", 1))
	if doctype == "Purchase Invoice":
		return bool(settings.get("enable_purchase_invoice", 0))
	return False
