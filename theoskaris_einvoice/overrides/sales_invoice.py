"""Sales Invoice DocEvent handlers for FIRS e-Invoicing.

Enable/disable control is in FIRS Settings — not per invoice or per company.
Batch uploads are handled by FIRS Invoice Upload doctype, not on submit.
"""

import frappe

from theoskaris_einvoice.payload.validators import (
	FIRSValidationError,
	has_placeholder_code,
	unclassified_tax_rows,
	assert_not_transmitted,
	get_counterparty_address,
	get_counterparty_email,
	get_counterparty_phone,
	get_counterparty_tin,
	validate_sales_invoice,
)
from theoskaris_einvoice.utils.settings import is_firs_enabled_for


def validate(doc, method=None):
	"""Run FIRS readiness validation and tag the invoice."""
	if not is_firs_enabled_for("Sales Invoice"):
		doc.db_set("custom_firs_ready", 0)
		return

	# Auto-fetch NRS item code (HSN/ISIC) from Item master if missing on invoice lines
	for item in doc.items:
		if not item.get("custom_firs_hsn_code") and item.item_code:
			# Goods use HSN; services fall back to ISIC when HSN is not set
			hsn = frappe.db.get_value("Item", item.item_code, "custom_firs_hsn_code")
			if not hsn:
				hsn = frappe.db.get_value("Item", item.item_code, "custom_firs_isic_code")
			if hsn:
				item.custom_firs_hsn_code = hsn

	ready = _check_firs_ready(doc)
	doc.db_set("custom_firs_ready", 1 if ready else 0)

	# Warn when the Customer TIN is missing — it blocks FIRS upload
	if not get_counterparty_tin(doc):
		frappe.msgprint(
			f"FIRS TIN is missing for Customer {doc.customer}. "
			f"Set the Tax ID on the Customer record to make this invoice FIRS Ready.",
			title="FIRS Validation",
			indicator="orange",
			alert=True,
		)

	# Warn when the Customer email or phone is missing — they block FIRS upload
	if not get_counterparty_email(doc):
		frappe.msgprint(
			f"Email is missing for Customer {doc.customer}. "
			f"Set the Email or a primary Contact with an email to make this invoice FIRS Ready.",
			title="FIRS Validation",
			indicator="orange",
			alert=True,
		)
	if not get_counterparty_phone(doc):
		frappe.msgprint(
			f"Phone number is missing for Customer {doc.customer}. "
			f"Set the Mobile No or a primary Contact with a phone to make this invoice FIRS Ready.",
			title="FIRS Validation",
			indicator="orange",
			alert=True,
		)

	# Warn when the company phone is missing — the NRS payload needs it
	if not frappe.db.get_value("Company", doc.company, "phone_no"):
		frappe.msgprint(
			f"Company {doc.company} has no phone number. NRS requires the supplier "
			f"telephone (starting with '+') on the FIRS payload.",
			title="FIRS Validation",
			indicator="orange",
			alert=True,
		)

	if unclassified_tax_rows(doc):
		frappe.msgprint(
			f"Tax rows without a valid NRS Tax Category: {', '.join(unclassified_tax_rows(doc))}. "
			f"Use a category accepted by the provider (e.g. STANDARD_VAT, ZERO_VAT, SERVICE_TAX).",
			title="FIRS Validation",
			indicator="orange",
			alert=True,
		)

	placeholder_rows = [
		item.item_code for item in doc.items
		if has_placeholder_code(item.get("custom_firs_hsn_code"))
	]
	if placeholder_rows:
		frappe.msgprint(
			f"Items with a placeholder NRS code (0000): {', '.join(placeholder_rows)}. "
			f"Set the real HSN/ISIC code — NRS rejects 0000.",
			title="FIRS Validation",
			indicator="orange",
			alert=True,
		)

	# Warn about missing HSN codes using frappe.alert (non-blocking)
	missing_items = [
		item.item_code for item in doc.items if not item.get("custom_firs_hsn_code")
	]
	if missing_items:
		frappe.msgprint(
			f"Items missing NRS item code (HSN/ISIC): {', '.join(missing_items)}. "
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

	# NRS requires a supplier telephone in E.164 form; the payload rejects a blank.
	if not company.get("phone_no"):
		return False

	# Invoice must have items
	if not doc.items:
		return False

	# All items must have HSN codes
	for item in doc.items:
		if not item.get("custom_firs_hsn_code"):
			return False

	# NRS rejects 0000/0000.00 placeholder classification codes
	for item in doc.items:
		if has_placeholder_code(item.get("custom_firs_hsn_code")):
			return False

	# Every taxed row needs a category the provider accepts
	if unclassified_tax_rows(doc):
		return False

	# Customer TIN is required — an invoice without it cannot be marked FIRS Ready.
	if not get_counterparty_tin(doc):
		return False

	# Customer email, phone and address are required — the FIRS payload needs them.
	if not get_counterparty_email(doc):
		return False
	if not get_counterparty_phone(doc):
		return False
	if not get_counterparty_address(doc):
		return False

	return True


def before_submit(doc, method=None):
	"""Hard validation before submission."""
	if not is_firs_enabled_for("Sales Invoice"):
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