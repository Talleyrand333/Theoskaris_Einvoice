"""Pre-submission validation for FIRS e-Invoice payloads."""

import frappe
from frappe import _

from theoskaris_einvoice.utils.settings import is_firs_enabled_for


class FIRSValidationError(Exception):
	pass


def _get_counterparty(inv):
	"""Get the counterparty (Customer for Sales Invoice, Supplier for Purchase Invoice)."""
	if inv.doctype == "Purchase Invoice":
		return frappe.get_doc("Supplier", inv.supplier)
	return frappe.get_doc("Customer", inv.customer)


def _get_tin(counterparty) -> str:
	"""Get TIN from a Customer or Supplier (standard Tax ID field)."""
	return counterparty.get("tax_id") or ""


def get_counterparty_tin(inv) -> str:
	"""Resolved TIN of the invoice counterparty (Customer on Sales Invoice, Supplier on Purchase Invoice)."""
	try:
		return _get_tin(_get_counterparty(inv)).strip()
	except Exception:
		return ""


def _get_contact(inv, counterparty):
	"""Primary Contact linked to the Customer/Supplier, or None."""
	dt = counterparty.doctype
	contact_name = counterparty.get("customer_primary_contact" if dt == "Customer" else "primary_contact")
	if contact_name:
		return frappe.get_cached_doc("Contact", contact_name)
	return None


def get_counterparty_email(inv) -> str:
	"""Counterparty email: own email_id, falling back to the primary Contact."""
	try:
		counterparty = _get_counterparty(inv)
		email = (counterparty.get("email_id") or "").strip()
		if not email:
			contact = _get_contact(inv, counterparty)
			if contact:
				email = (contact.get("email_id") or "").strip()
		return email
	except Exception:
		return ""


def get_counterparty_phone(inv) -> str:
	"""Counterparty phone: own mobile_no, falling back to the primary Contact."""
	try:
		counterparty = _get_counterparty(inv)
		phone = (counterparty.get("mobile_no") or "").strip()
		if not phone:
			contact = _get_contact(inv, counterparty)
			if contact:
				phone = (contact.get("mobile_no") or contact.get("phone") or "").strip()
		return phone
	except Exception:
		return ""


def get_counterparty_address(inv) -> str:
	"""Name of the counterparty's primary Address, or "" if none.

	NRS needs a street, city and country on the party — an address with
	missing core fields counts as absent.
	"""
	try:
		counterparty = _get_counterparty(inv)
		dt = counterparty.doctype
		addr_name = counterparty.get(
			"customer_primary_address" if dt == "Customer" else "supplier_primary_address"
		)
		if not addr_name:
			addr_name = frappe.db.get_value(
				"Dynamic Link",
				{"parenttype": "Address", "link_doctype": dt, "link_name": counterparty.name},
				"parent",
			)
		if not addr_name:
			return ""
		addr = frappe.db.get_value(
			"Address", addr_name, ["address_line1", "city", "country"], as_dict=True
		)
		if not addr or not addr.address_line1 or not addr.city or not addr.country:
			return ""
		return addr_name
	except Exception:
		return ""


def validate_sales_invoice(inv) -> list:
	"""Run hard validation before submitting a Sales/Purchase Invoice to FIRS."""
	errors = []

	company = frappe.get_doc("Company", inv.company)

	if not company.get("custom_firs_api_key"):
		errors.append(_("Company FIRS API Key is missing"))

	if not company.get("custom_firs_api_signature"):
		errors.append(_("Company FIRS API Signature is missing"))

	if not company.get("custom_firs_business_id"):
		errors.append(_("Company FIRS Business ID is missing"))

	if not company.get("custom_firs_service_id"):
		errors.append(_("Company FIRS Service ID is missing"))

	if not company.get("tax_id") and not company.get("custom_firs_company_tin"):
		errors.append(_("Company TIN is missing"))

	if not inv.items:
		errors.append(_("Invoice must have at least one item"))

	for item in inv.items:
		# Item classification codes (HSN/ISIC) do NOT block submission — a missing
		# code only keeps the FIRS Ready checkbox off, per 2026-09-21 decision.
		pass

	# Counterparty details are required for NRS (TIN, email, phone, address)
	tin = get_counterparty_tin(inv)
	if not tin:
		errors.append(
			_("Counterparty TIN is missing — set Tax ID on {0} for NRS upload").format(
				inv.customer if inv.doctype == "Sales Invoice" else inv.supplier
			)
		)
	if not get_counterparty_email(inv):
		errors.append(_("Counterparty email is missing — required for NRS upload"))
	if not get_counterparty_phone(inv):
		errors.append(_("Counterparty phone is missing — required for NRS upload"))
	if not get_counterparty_address(inv):
		errors.append(
			_("Counterparty address is missing (needs street, city and country) — required for NRS upload")
		)

	# Credit notes must reference an already-transmitted original invoice
	if inv.is_return:
		if not inv.return_against:
			errors.append(_("Credit Note must reference the original invoice (Return Against)"))
		else:
			original_irn = frappe.db.get_value(inv.doctype, inv.return_against, "custom_nrs_irn")
			if not original_irn:
				errors.append(
					_(
						"Original invoice {0} has not been transmitted to FIRS yet (no IRN)"
					).format(inv.return_against)
				)

	if errors:
		raise FIRSValidationError("\n".join(errors))
	return errors


def can_transmit(inv) -> bool:
	"""Return True if the invoice should be enqueued for FIRS transmission.

	Checks central FIRS Settings toggle — not the invoice or company flags.
	"""
	if inv.get("custom_nrs_irn"):
		return False
	return is_firs_enabled_for(inv.doctype)


def assert_not_transmitted(inv):
	"""Raise if the invoice already has an IRN (cancellation block)."""
	if inv.get("custom_nrs_irn"):
		frappe.throw(
			_(
				"This invoice has already been transmitted to FIRS (IRN: {0}). "
				"Cancellation is blocked. Create a Credit Note instead."
			).format(inv.custom_nrs_irn),
			title=_("FIRS Transmitted Invoice"),
		)
