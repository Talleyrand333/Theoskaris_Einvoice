"""Build FIRS / eTranzact UBL JSON payload from ERPNext Sales or Purchase Invoice."""

from typing import Any

import frappe
from frappe.utils import flt, get_datetime

from theoskaris_einvoice.payload.uom_map import UOM_NRS_CODE_MAP


EMPTY_ADDRESS = {
	"street_name": "",
	"city_name": "",
	"lga": "",
	"state": "",
	"postal_zone": "",
	"country": "NG",
}

# The API validates country against ISO 3166-1 alpha-2 codes (see its
# Get Country Codes resource). ERPNext Address.country holds names
# ("Nigeria"), and users type free text, so normalize before sending.
_COUNTRY_TO_ISO2 = {
	"nigeria": "NG",
	"ghana": "GH",
	"united kingdom": "GB",
	"united states": "US",
	"united states of america": "US",
	"usa": "US",
	"canada": "CA",
	"south africa": "ZA",
	"kenya": "KE",
	"togo": "TG",
	"benin": "BJ",
	"cote divoire": "CI",
	"côte d'ivoire": "CI",
	"ivory coast": "CI",
	"cameroon": "CM",
	"niger": "NE",
	"egypt": "EG",
}


def _country_to_iso2(country: str) -> str:
	"""Normalize an ERPNext country name/value to ISO alpha-2.

	Falls back to the ERPNext Country doctype code, then to NG.
	"""
	if not country:
		return "NG"
	val = str(country).strip()
	if len(val) == 2:
		return val.upper()
	code = _COUNTRY_TO_ISO2.get(val.lower())
	if not code:
		code = frappe.db.get_value("Country", {"name": ["like", val]}, "code")
		if code:
			code = code.upper()
	return code or "NG"


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
		"buyer_reference": inv.get("cost_center") or (inv.supplier if is_purchase else inv.customer),
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
					"issue_date": str(frappe.db.get_value(inv.doctype, inv.return_against, "posting_date")),
				}
			]

	return payload


def _get_invoice_kind(customer) -> str:
	"""Return B2B if customer has a TIN (standard Tax ID), otherwise B2C."""
	if _get_tin(customer):
		return "B2B"
	return "B2C"


def _get_tin(customer) -> str:
	"""Get customer TIN from the standard Tax ID field. Empty when unset."""
	tin = customer.get("tax_id")
	return str(tin).strip() if tin else ""


def _build_supplier_party(company) -> dict:
	"""Build accounting supplier party from Company."""
	tin = company.get("custom_firs_company_tin") or company.get("tax_id") or ""
	address = _get_address(company.name, "Company") or EMPTY_ADDRESS
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
	address = _get_address(customer.name, "Customer") or EMPTY_ADDRESS
	phone = _normalize_phone(customer.get("mobile_no"))
	if not phone:
		phone = _get_contact_phone(customer.name, "Customer")
	return {
		"party_name": customer.customer_name,
		"tin": tin,
		"email": customer.get("email_id") or _get_contact_email(customer.name, "Customer") or "",
		"telephone": phone or "",
		"business_description": customer.get("custom_firs_business_description") or customer.customer_name,
		"postal_address": address,
	}


def _build_supplier_from_supplier(supplier) -> dict:
	"""Build accounting supplier party from Supplier doc (Purchase Invoice)."""
	tin = supplier.get("tax_id") or ""
	address = _get_address(supplier.name, "Supplier") or EMPTY_ADDRESS
	phone = _normalize_phone(supplier.get("mobile_no"))
	if not phone:
		phone = _get_contact_phone(supplier.name, "Supplier")
	return {
		"party_name": supplier.supplier_name,
		"tin": str(tin).strip(),
		"email": supplier.get("email_id") or _get_contact_email(supplier.name, "Supplier") or "",
		"telephone": phone or "",
		"business_description": supplier.supplier_name,
		"postal_address": address,
	}


def _build_customer_from_company(company) -> dict:
	"""Build accounting customer party from Company (Purchase Invoice buyer)."""
	tin = company.get("custom_firs_company_tin") or company.get("tax_id") or ""
	address = _get_address(company.name, "Company") or EMPTY_ADDRESS
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
		"state": (addr.get("state") or "").title(),
		"postal_zone": addr.get("pincode") or "",
		"country": _country_to_iso2(addr.get("country")),
	}


def _get_contact_phone(party_name: str, doctype: str = "Customer") -> str:
	"""Try to fetch phone from primary contact.

	Works for Customer and Supplier doctypes.
	"""
	if doctype == "Customer":
		contact_name = frappe.db.get_value("Customer", party_name, "customer_primary_contact")
	else:
		contact_name = frappe.db.get_value("Supplier", party_name, "primary_contact")
	if contact_name:
		phone = frappe.db.get_value("Contact", contact_name, "mobile_no") or frappe.db.get_value(
			"Contact", contact_name, "phone"
		)
		return _normalize_phone(phone)
	return ""


def _get_contact_email(party_name: str, doctype: str = "Customer") -> str:
	"""Try to fetch email from primary contact.

	Works for Customer and Supplier doctypes.
	"""
	if doctype == "Customer":
		contact_name = frappe.db.get_value("Customer", party_name, "customer_primary_contact")
	else:
		contact_name = frappe.db.get_value("Supplier", party_name, "primary_contact")
	if contact_name:
		return frappe.db.get_value("Contact", contact_name, "email_id") or ""
	return ""


# UN/ECE Rec 20 unit-of-measure codes required by FIRS price_unit (max 3 chars).
# FIRS/eTranzact expects codes from its "invoice quantity code list" — in practice
# C62 ("one/unit") is the safe default; mapped codes used where a direct match exists.
_UOM_CODE_MAP = {
	"PCS": "C62",
	"PCE": "C62",
	"PIECE": "C62",
	"PIECES": "C62",
	"NOS": "C62",
	"NUMBERS": "C62",
	"UNIT": "C62",
	"EA": "C62",
	"EACH": "C62",
	"QTY": "C62",
	"LUMP SUM": "C62",
	"DAY RATE": "HUR",
	"DRUM(S)": "C62",
	"METER(S)": "MTR",
	"MONTH(S)": "MON",
	"KG": "KGM",
	"GRAM": "GRM",
	"GRAMS": "GRM",
	"LITRE": "LTR",
	"LITRES": "LTR",
	"LITER": "LTR",
	"LITERS": "LTR",
	"METER": "MTR",
	"METERS": "MTR",
	"METRE": "MTR",
	"METRES": "MTR",
	"FOOT": "FOT",
	"FEET": "FOT",
	"BOX": "C62",
	"PACK": "C62",
	"SET": "C62",
	"HOUR": "HUR",
	"HOURS": "HUR",
	"DAY": "DAY",
	"DAYS": "DAY",
	"MONTH": "MON",
	"MONTHS": "MON",
}


def _price_unit_code(uom: str, uom_doc: str = None) -> str:
	"""Resolve the NRS/FIRS price_unit code for a UOM.

	Priority:
	1. custom_nrs_uom_code on the UOM doc (manually set or seeded)
	2. _UOM_CODE_MAP / UOM_NRS_CODE_MAP by name
	3. Pass through if already a valid ≤3-char code, else C62
	"""
	if uom_doc and frappe.db.exists("UOM", uom_doc):
		code = frappe.db.get_value("UOM", uom_doc, "custom_nrs_uom_code")
		if code and code.strip():
			return code.strip().upper()

	u = (uom or "").strip().upper()
	code = _UOM_CODE_MAP.get(u) or UOM_NRS_CODE_MAP.get(u)
	if code:
		return code
	if len(u) <= 3 and u.isalpha():
		return u
	return "C62"


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
	"""Build FIRS invoice lines from Sales Invoice items.

	Stock items (Maintain Stock) → hsn_code + product_category (goods).
	Non-stock items (services) → isic_code + service_category (ISIC Rev.4).
	"""
	lines = []
	for item in inv.items:
		qty = abs(flt(item.qty))
		net_rate = abs(flt(item.net_rate))
		line_ext = abs(flt(item.net_amount))
		discount = abs(flt(item.discount_amount))

		code = (item.get("custom_firs_hsn_code") or "").strip()
		is_stock = _item_is_stock(item.item_code)

		if is_stock:
			classification = {
				"hsn_code": _format_hsn(code or "0000.00"),
				"product_category": item.get("item_group") or "General",
			}
		else:
			classification = {
				"isic_code": code,
				"service_category": item.get("item_group") or "General",
			}

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
					"price_unit": _price_unit_code(item.uom, item.uom),
				},
				**classification,
				"invoiced_quantity": qty,
				"line_extension_amount": line_ext,
				"discount_amount": discount,
			}
		)
	return lines


def _item_is_stock(item_code: str) -> bool:
	"""True if the item has Maintain Stock checked (goods); False = service."""
	if not item_code:
		return True  # default to goods when unknown
	val = frappe.db.get_value("Item", item_code, "is_stock_item")
	return 1 if val is None else bool(val)


def _build_tax_total(inv) -> list:
	"""Build tax_total from invoice taxes grouped by NRS tax category.

	The NRS category is read from the NRS Tax Category field on the Sales/Purchase
	Taxes and Charges Template assigned to the invoice (template_category),
	falling back to description/account-head matching for templates where it is unset.
	"""
	totals = {}
	template_category = _get_template_tax_category(inv)
	for tax in inv.taxes:
		if not tax.tax_amount:
			continue
		category = _resolve_tax_category(tax, inv, template_category)
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
		if template_category:
			percent = NRS_TAX_CATEGORIES.get(template_category, 0.0)
			if template_category == "STANDARD_VAT" and not percent:
				percent = 7.5
			category = {"id": template_category, "percent": percent, "tax_scheme": {"id": "VAT"}}
		else:
			category = {"id": "STANDARD_VAT", "percent": 7.5, "tax_scheme": {"id": "VAT"}}
		totals[category["id"]] = {
			"taxable_amount": flt(inv.net_total),
			"tax_amount": 0.0,
			"category": category,
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


# NRS tax category ids and their default VAT scheme.
NRS_TAX_CATEGORIES = {
	"STANDARD_VAT": 7.5,
	"ZERO_VAT": 0.0,
	"EXEMPT": 0.0,
	"WITHHOLDING_TAX": 0.0,
	"STAMP_DUTY": 0.0,
}


def _get_template_tax_category(inv) -> str:
	"""Read NRS Tax Category from the Taxes and Charges Template on the invoice."""
	template = inv.get("taxes_and_charges")
	if not template:
		return ""
	template_doctype = (
		"Purchase Taxes and Charges Template"
		if inv.doctype == "Purchase Invoice"
		else "Sales Taxes and Charges Template"
	)
	if not frappe.db.exists(template_doctype, template):
		return ""
	return (frappe.db.get_value(template_doctype, template, "custom_nrs_tax_category") or "").strip()


def _resolve_tax_category(tax_row, inv=None, template_category: str = "") -> dict:
	"""Resolve a tax row to an NRS Tax Category.

	Priority: NRS Tax Category on the template assigned to the invoice, then
	description/account-head keyword matching, then standard VAT at the row rate.
	"""
	if template_category:
		rate = flt(tax_row.rate, 2)
		if template_category != "STANDARD_VAT" and not rate:
			rate = NRS_TAX_CATEGORIES.get(template_category, 0.0)
		if not rate and template_category == "STANDARD_VAT":
			rate = 7.5
		return {"id": template_category, "percent": rate, "tax_scheme": {"id": "VAT"}}

	# Try description first, then account head
	search = (tax_row.description or tax_row.account_head or "").upper()
	if "ZERO" in search:
		return {"id": "ZERO_VAT", "percent": 0.0, "tax_scheme": {"id": "VAT"}}
	if "EXEMPT" in search:
		return {"id": "EXEMPT", "percent": 0.0, "tax_scheme": {"id": "VAT"}}
	if "WITHHOLD" in search:
		return {"id": "WITHHOLDING_TAX", "percent": 0.0, "tax_scheme": {"id": "VAT"}}
	if "STAMP" in search:
		return {"id": "STAMP_DUTY", "percent": 0.0, "tax_scheme": {"id": "VAT"}}
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
	"""Build legal_monetary_total block.

	Credit notes have negative totals in ERPNext, but FIRS requires
	all monetary values to be >= 0. Use abs() for safety.
	"""
	line_ext = abs(flt(inv.net_total))
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
	"""Build payment_means array from the invoice's Payment Terms Template.

	Reads custom_firs_payment_code from the Payment Terms Template, falling back
	to the Default Payment Means configured in FIRS Settings.
	"""
	code = None
	if inv.get("payment_terms_template"):
		mapped = frappe.db.get_value(
			"Payment Terms Template", inv.payment_terms_template, "custom_firs_payment_code"
		)
		if mapped:
			code = mapped
	if not code:
		code = (
			frappe.db.get_single_value("FIRS Settings", "default_payment_means") or "10"
		)
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
