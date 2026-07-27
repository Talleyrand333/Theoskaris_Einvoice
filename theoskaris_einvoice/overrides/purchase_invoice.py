"""Purchase Invoice DocEvent handlers for FIRS e-Invoicing.

Enable/disable control is in FIRS Settings — not per invoice or per company.
Batch uploads are handled by FIRS Invoice Upload doctype, not on submit.
"""

import frappe

from theoskaris_einvoice.payload.validators import (
	FIRSValidationError,
	assert_not_transmitted,
	validate_sales_invoice,
)
from theoskaris_einvoice.utils.settings import is_firs_enabled_for


def validate(doc, method=None):
	"""Run FIRS readiness validation and tag the invoice."""
	if not is_firs_enabled_for("Purchase Invoice"):
		doc.db_set("custom_firs_ready", 0)
		return

	# Auto-fetch HSN code from Item master if missing on invoice lines
	for item in doc.items:
		if not item.get("custom_firs_hsn_code") and item.item_code:
			hsn = frappe.db.get_value("Item", item.item_code, "custom_firs_hsn_code")
			if hsn:
				item.custom_firs_hsn_code = hsn

	ready = _check_firs_ready(doc)
	doc.db_set("custom_firs_ready", 1 if ready else 0)

	# Warn about missing HSN codes using frappe.alert (non-blocking)
	missing_items = [
		item.item_code for item in doc.items if not item.get("custom_firs_hsn_code")
	]
	if missing_items:
		frappe.msgprint(
			f"Items missing FIRS HSN code: {', '.join(missing_items)}. "
			f"Set the HSN code on the Item master to resolve.",
			title="FIRS Validation",
			indicator="orange",
			alert=True,
		)


def _check_firs_ready(doc) -> bool:
	"""Check if invoice satisfies all FIRS upload requirements."""
	company = frappe.get_doc("Company", doc.company)

	# Company credentials
	if not company.get("custom_firs_api_key"):
		return False
	if not company.get("custom_firs_api_signature"):
		return False
	if not company.get("custom_firs_business_id"):
		return False
	if not company.get("custom_firs_service_id"):
		return False
	if not company.get("tax_id") and not company.get("custom_firs_company_tin"):
		return False

	# Invoice must have items
	if not doc.items:
		return False

	# All items must have HSN codes
	for item in doc.items:
		if not item.get("custom_firs_hsn_code"):
			return False

	# Supplier TIN is optional — B2C invoices (no TIN) are valid for FIRS upload.
	# The payload builder classifies them as B2C with a placeholder TIN.

	return True


def before_submit(doc, method=None):
	"""Hard validation before submission."""
	if not is_firs_enabled_for("Purchase Invoice"):
		return
	try:
		validate_sales_invoice(doc)
	except FIRSValidationError as e:
		frappe.throw(str(e), title="FIRS Validation Failed")


def on_submit(doc, method=None):
	"""No auto-queue. FIRS Invoice Upload doctype handles batch queuing."""
	pass


def before_cancel(doc, method=None):
	"""Block cancellation if invoice already transmitted."""
	assert_not_transmitted(doc)


def on_cancel(doc, method=None):
	"""No-op; cancellation already blocked before."""
	pass