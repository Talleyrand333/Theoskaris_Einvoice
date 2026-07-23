"""Build FIRS / eTranzact UBL JSON payload from ERPNext Sales or Purchase Invoice."""

from typing import Any

import frappe
from frappe.utils import flt, get_datetime


PLACEHOLDER_TIN = "00000000-0001"
PLACEHOLDER_ADDRESS = {
	"street_name": "1 Marina Road",
	"city_name": "Lagos",
	"lga": "Lagos Island",
	"state": "Lagos",
	"postal_zone": "100001",
	"country": "NG",
}


def build_payload(invoice: str | Any) -> dict:
	"""Build the eTranzact ValidateInvoiceRequest payload for Sales or Purchase Invoice."""
	if isinstance(invoice, str):
		inv = frappe.get_doc(invoice)  # Can be Sales Invoice or Purchase Invoice
	else:
		inv = invoice

	company = frappe.get_doc("Company", inv.company)

	# Sales Invoice: company = supplier/seller, customer = buyer
	# Purchase Invoice: company = buyer/customer, supplier = seller
	is_purchase = inv.doctype == "Purchase Invoice"

	if is_purchase:
		supplier = frappe.get_doc("Supplier", inv.supplier)
		customer = company  # For PI, company is the buyer
		invoice_kind = "B2B" if supplier.get("tax_id") else "B2C"
		supplier_party = _build_supplier_from_supplier(supplier)
		customer_party = _build_customer_from_company(company)
	else:
		customer = frappe.get_doc("Customer", inv.customer)
		invoice_kind = _get_invoice_kind(customer)
		supplier_party = _build_supplier_party(company)
		customer_party = _build_customer_party(customer)

	invoice_type_code = "381" if not inv.is_return else "380"
	lines = _build_invoice_lines(inv)
	tax_total = _build_tax_total(inv)
	legal_monetary_total = _build_legal_monetary_total(inv, tax_total)
	payment_means = _build_payment_means(inv)

	posting_dt = get_datetime(inv.posting_date)
	issue_date = posting_dt.strftime("%Y-%m-%d")
	posting_time = inv.posting_time
	if isinstance(posting_time, (str,)):
		issue_time = posting_time.split(".")[0]
	elif hasattr(posting_time, "total_seconds"):
		# ERPNext stores posting_time as timedelta in some versions
		seconds = int(posting_time.total_seconds())
		issue_time = f"{seconds // 3600:02d}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"
	else:
		issue_time = posting_dt.strftime("%H:%M:%S")
	due_date = inv.due_date and str(inv.due_date) or issue_date

	payload = {
		"business_id": company.get("custom_firs_business_id") or "",
		"irn": inv.get("custom_nrs_irn") or _generate_internal_irn(inv, company),
		"issue_date": issue_date,
		"due_date": due_date,
		"issue_time": issue_time,
		"invoice_type_code": invoice_type_code,
		"invoice_kind": invoice_kind,
		"payment_status": "PENDING",
		"tax_point_date": issue_date,
		"document_currency_code": inv.currency,
		"tax_currency_code": inv.currency,
		"buyer_reference": inv.get("cost_center") or inv.customer,
		"order_reference": inv.get("po_no") or inv.name,
		"accounting_supplier_party": supplier_party,
		"accounting_customer_party": customer_party,
		"payment_means": payment_means,
		"tax_total": tax_total,
		"legal_monetary_total": legal_monetary_total,
		"invoice_line": lines,
	}

	if inv.get("remarks"):
		payload["note"] = inv.remarks

	# Credit notes reference the original invoice IRN
	if inv.is_return and inv.return_against:
		original_irn = frappe.db.get_value(inv.doctype, inv.return_against, "custom_nrs_irn")
		if original_irn:
			payload["billing_reference"] = [
				{
					"irn": original_irn,
					"issue_date": frappe.db.get_value(inv.doctype, inv.return_against, "posting_date"),
				}
			]

	return payload


def _get_invoice_kind(customer) -> str:
	"""Return B2B if customer has TIN, otherwise B2C."""
	tin = _get_tin(customer)
	if tin and tin != PLACEHOLDER_TIN:
		return "B2B"
	# If customer has a tax_id set on the Customer record, treat as B2B
	customer_tax_id = (customer.get("tax_id") or "").strip()
	if customer_tax_id:
		return "B2B"
	return "B2C"


def _get_tin(customer) -> str:
	"""Get customer TIN, falling back to placeholder."""
	tin = customer.get("custom_firs_tin") or customer.get("tax_id")
	if tin:
		return str(tin).strip()
	return PLACEHOLDER_TIN


def _build_supplier_party(company) -> dict:
	"""Build accounting supplier party from Company."""
	tin = company.get("custom_firs_company_tin") or company.get("tax_id") or PLACEHOLDER_TIN
	address = _get_address(company.name, "Company") or PLACEHOLDER_ADDRESS
	return {
		"party_name": company.company_name,
		"tin": str(tin).strip(),
		"email": company.get("email") or "",
		"telephone": _normalize_phone(company.get("phone_no")) or "",
		"business_description": company.get("custom_firs_business_description") or company.company_name,
		"postal_address": address,
	}


def _build_customer_party(customer) -> dict:
	"""Build accounting customer party from Customer."""
	tin = _get_tin(customer)
	address = _get_address(customer.name, "Customer") or PLACEHOLDER_ADDRESS
	phone = _normalize_phone(customer.get("mobile_no"))
	if not phone:
		phone = _get_contact_phone(customer.name)
	return {
		"party_name": customer.customer_name,
		"tin": tin,
		"email": customer.get("email_id") or _get_contact_email(customer.name) or "",
		"telephone": phone or "",
		"business_description": customer.get("custom_firs_business_description") or customer.customer_name,
		"postal_address": address,
	}


def _build_supplier_from_supplier(supplier) -> dict:
	"""Build accounting supplier party from Supplier doc (Purchase Invoice)."""
	tin = supplier.get("tax_id") or PLACEHOLDER_TIN
	address = _get_address(supplier.name, "Supplier") or PLACEHOLDER_ADDRESS
	phone = _normalize_phone(supplier.get("mobile_no"))
	if not phone:
		phone = _get_contact_phone(supplier.name)
	return {
		"party_name": supplier.supplier_name,
		"tin": str(tin).strip(),
		"email": supplier.get("email_id") or _get_contact_email(supplier.name) or "",
		"telephone": phone or "",
		"business_description": supplier.supplier_name,
		"postal_address": address,
	}


def _build_customer_from_company(company) -> dict:
	"""Build accounting customer party from Company (Purchase Invoice buyer)."""
	tin = company.get("custom_firs_company_tin") or company.get("tax_id") or PLACEHOLDER_TIN
	address = _get_address(company.name, "Company") or PLACEHOLDER_ADDRESS
	return {
		"party_name": company.company_name,
		"tin": str(tin).strip(),
		"email": company.get("email") or "",
		"telephone": _normalize_phone(company.get("phone_no")) or "",
		"business_description": company.company_name,
		"postal_address": address,
	}


def _get_address(link_name, link_doctype) -> dict | None:
	"""Fetch primary address for a Customer/Company."""
	addr_name = None
	if link_doctype == "Customer":
		addr_name = frappe.db.get_value("Customer", link_name, "customer_primary_address")
	else:
		# Try to find the default Company address
		addr_name = frappe.db.get_value(
			"Dynamic Link",
			{"parenttype": "Address", "link_doctype": link_doctype, "link_name": link_name},
			"parent",
		)
	if not addr_name:
		return None
	addr = frappe.get_doc("Address", addr_name)
	return {
		"street_name": " ".join(
			filter(None, [addr.get("address_line1"), addr.get("address_line2")])
		),
		"city_name": addr.get("city") or "",
		"lga": addr.get("county") or addr.get("city") or "",
		"state": addr.get("state") or "",
		"postal_zone": addr.get("pincode") or "",
		"country": addr.get("country") or "NG",
	}


def _get_contact_phone(customer_name: str) -> str:
	"""Try to fetch phone from primary contact."""
	contact_name = frappe.db.get_value("Customer", customer_name, "customer_primary_contact")
	if contact_name:
		phone = frappe.db.get_value("Contact", contact_name, "mobile_no") or frappe.db.get_value(
			"Contact", contact_name, "phone"
		)
		return _normalize_phone(phone)
	return ""


def _get_contact_email(customer_name: str) -> str:
	"""Try to fetch email from primary contact."""
	contact_name = frappe.db.get_value("Customer", customer_name, "customer_primary_contact")
	if contact_name:
		return frappe.db.get_value("Contact", contact_name, "email_id") or ""
	return ""


def _format_hsn(hsn: str) -> str:
	"""Ensure HSN code has 2 decimal places (format: 0000.00)."""
	hsn = str(hsn).strip()
	if "." not in hsn:
		return f"{hsn}.00"
	parts = hsn.split(".")
	if len(parts[1]) == 0:
		return f"{parts[0]}.00"
	if len(parts[1]) == 1:
		return f"{hsn}0"
	return hsn


def _normalize_phone(phone) -> str:
	"""Normalize Nigerian phone to E.164-ish +234 format."""
	if not phone:
		return ""
	phone = str(phone).strip().replace(" ", "").replace("-", "")
	if phone.startswith("+234"):
		return phone
	if phone.startswith("234") and len(phone) == 13:
		return f"+{phone}"
	if phone.startswith("0") and len(phone) == 11:
		return f"+234{phone[1:]}"
	if phone.startswith("0") and len(phone) == 10:
		return f"+234{phone[1:]}"
	# If it doesn't match, return as-is
	return phone


def _build_invoice_lines(inv) -> list:
	"""Build FIRS invoice lines from Sales Invoice items."""
	lines = []
	for item in inv.items:
		qty = abs(flt(item.qty))
		net_rate = abs(flt(item.net_rate))
		line_ext = abs(flt(item.net_amount))
		discount = abs(flt(item.discount_amount))
		lines.append(
			{
				"item": {
					"name": item.item_name or item.item_code,
					"description": item.description or item.item_name or item.item_code,
					"sellers_item_identification": item.item_code,
				},
				"price": {
					"price_amount": net_rate,
					"base_quantity": 1,
					"price_unit": f"{inv.currency} per {item.uom}",
				},
				"hsn_code": _format_hsn(item.get("custom_firs_hsn_code") or "0000.00"),
				"product_category": item.get("item_group") or "General",
				"invoiced_quantity": qty,
				"line_extension_amount": line_ext,
				"discount_amount": discount,
			}
		)
	return lines


def _build_tax_total(inv) -> list:
	"""Build tax_total from invoice taxes grouped by FIRS tax category."""
	totals = {}
	for tax in inv.taxes:
		if not tax.tax_amount:
			continue
		category = _resolve_tax_category(tax)
		key = category["id"]
		if key not in totals:
			totals[key] = {
				"taxable_amount": 0.0,
				"tax_amount": 0.0,
				"category": category,
			}
		# Add tax amount; base is net total for this row
		base = abs(flt(tax.base_tax_amount)) or abs(flt(tax.tax_amount))
		totals[key]["tax_amount"] += base
		totals[key]["taxable_amount"] += _get_tax_base_for_row(tax, inv)

	# Fallback when no taxes configured
	if not totals:
		totals["STANDARD_VAT"] = {
			"taxable_amount": flt(inv.net_total),
			"tax_amount": 0.0,
			"category": {"id": "STANDARD_VAT", "percent": 7.5, "tax_scheme": {"id": "VAT"}},
		}

	tax_total = []
	for bucket in totals.values():
		tax_total.append(
			{
				"tax_amount": flt(bucket["tax_amount"], 2),
				"tax_subtotal": [
					{
						"taxable_amount": flt(bucket["taxable_amount"], 2),
						"tax_amount": flt(bucket["tax_amount"], 2),
						"tax_category": bucket["category"],
						"tax_category_percent": bucket["category"]["percent"],
					}
				],
			}
		)
	return tax_total


def _resolve_tax_category(tax_row) -> dict:
	"""Resolve tax row to a FIRS Tax Category."""
	# Try description first, then account head
	search = (tax_row.description or tax_row.account_head or "").upper()
	if "ZERO" in search:
		return {"id": "ZERO_VAT", "percent": 0.0, "tax_scheme": {"id": "VAT"}}
	if "EXEMPT" in search:
		return {"id": "EXEMPT", "percent": 0.0, "tax_scheme": {"id": "VAT"}}
	# Default to standard VAT at configured rate
	rate = flt(tax_row.rate, 2)
	if not rate:
		rate = 7.5
	return {"id": "STANDARD_VAT", "percent": rate, "tax_scheme": {"id": "VAT"}}


def _get_tax_base_for_row(tax_row, inv) -> float:
	"""Estimate taxable base for a tax row."""
	if tax_row.total:
		return abs(flt(tax_row.total)) - abs(flt(tax_row.tax_amount_after_discount_amount or 0))
	return flt(inv.net_total)


def _build_legal_monetary_total(inv, tax_total) -> dict:
	"""Build legal_monetary_total block."""
	line_ext = flt(inv.net_total)
	tax_amt = sum(flt(t["tax_amount"]) for t in tax_total)
	tax_exclusive = line_ext
	tax_inclusive = tax_exclusive + tax_amt
	return {
		"line_extension_amount": line_ext,
		"tax_exclusive_amount": tax_exclusive,
		"tax_inclusive_amount": tax_inclusive,
		"payable_amount": tax_inclusive,
	}


def _build_payment_means(inv) -> list:
	"""Build payment_means array from invoice payment terms template."""
	code = "10"  # default bank transfer
	if inv.get("payment_terms_template"):
		mapped = frappe.db.get_value("FIRS Payment Means Code", {"payment_terms_template": inv.payment_terms_template}, "code")
		if mapped:
			code = mapped
	return [
		{
			"payment_means_code": code,
			"payment_due_date": str(inv.due_date or inv.posting_date),
		}
	]


def _generate_internal_irn(inv, company) -> str:
	"""Generate a temporary IRN-like reference before real IRN is returned.

	FIRS IRN must follow the eTranzact template:
	  {invoice_no}-{entity_seg2}{business_seg2}-{issue_date_YYYYMMDD}
	All uppercase, only '-' special character allowed.
	"""
	# Extract IRN segment from Entity ID (service_id) + Business ID per dashboard template
	entity_id = company.get("custom_firs_service_id") or ""
	business_id = company.get("custom_firs_business_id") or ""

	def _segment2(uuid_str: str) -> str:
		parts = uuid_str.split("-")
		return parts[1] if len(parts) >= 2 else ""

	irn_segment = (_segment2(entity_id) + _segment2(business_id)).upper()
	if not irn_segment:
		irn_segment = (company.get("custom_firs_service_id") or "").upper()

	issuance = str(inv.posting_date).replace("-", "")
	# Invoice number uppercased and safe
	inv_ref = inv.name.upper()
	return f"{inv_ref}-{irn_segment}-{issuance}"
