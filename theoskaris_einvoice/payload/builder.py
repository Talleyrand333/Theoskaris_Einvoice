"""Build FIRS / eTranzact UBL JSON payload from ERPNext Sales or Purchase Invoice."""

from typing import Any

import frappe
from frappe.utils import flt, get_datetime

from theoskaris_einvoice.payload.uom_map import UOM_NRS_CODE_MAP
from theoskaris_einvoice.utils.nrs_tax_categories import NRS_TAX_CATEGORY_OPTIONS


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
		"payment_status": _get_payment_status(inv),
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


def _format_isic(isic: str) -> str:
	"""Normalize ISIC code to plain 4 digits (NRS format: 0000).

	Accepts values stored with a decimal suffix (e.g. 0000.00 from HSN-style
	entry) and strips it: the NRS ISIC validator expects exactly 4 digits.
	"""
	isic = str(isic).strip()
	if "." in isic:
		isic = isic.split(".")[0]
	return isic


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
		if not code:
			# Service lines: fall back to the ISIC code when HSN is absent
			code = (frappe.db.get_value("Item", item.item_code, "custom_firs_isic_code") or "").strip()
		is_stock = _item_is_stock(item.item_code)

		if is_stock:
			classification = {
				"hsn_code": _format_hsn(code or "0000.00"),
				"product_category": item.get("item_group") or "General",
			}
		else:
			classification = {
				"isic_code": _format_isic(code or "0000"),
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

    Amounts come from the tax rows' document-currency fields. ERPNext keeps
    base_tax_amount in company currency, so using it while declaring the
    invoice currency produced NGN figures inside USD payloads.

    NRS requires every tax amount to be zero or positive, so each bucket is
    reported as a magnitude. A withholding/deduction row still gets its own
    WITHHOLDING_TAX bucket, but with a positive amount: the provider rejected
    a negative liability ("taxtotal[1].taxamount must be greater than or equal
    to 0", FIRS-LOG-2026-00063) and the account's accepted invoices
    (SINV-00558/559) were signed with positive WHT amounts. The deduction
    direction is kept for classification only; it is not encoded as a sign.
    """

    totals = {}
    template_category = _get_template_tax_category(inv)
    sign = _document_sign(inv)
    for tax in inv.taxes:
        if str(tax.get("category") or "") == "Valuation":
            # Valuation taxes are internal and never part of the payable total.
            continue
        if tax.get("included_in_print_rate"):
            frappe.throw(
                frappe._(
                    "Tax row '{0}' on {1} is marked 'Is this Tax included in "
                    "Basic Rate?'. NRS payloads need tax-exclusive amounts; "
                    "disable that option or use a tax-exclusive template."
                ).format(tax.description or tax.account_head, inv.name),
                title=frappe._("NRS Tax-Inclusive Row"),
            )

        amount = _tax_row_amount(tax)
        deduction = _is_tax_deduction(tax, amount, credit_note=sign < 0)
        category = _resolve_tax_category(
            tax, inv, template_category, deduction=deduction
        )
        if not category:
            frappe.throw(
                _missing_category_message(tax, inv, template_category, deduction),
                title=frappe._("NRS Tax Category Missing"),
            )

        # A zero-amount row is still meaningful for zero-rated/exempt supply:
        # it tells NRS why the taxable base carries no tax.
        if not amount and category["id"] not in ZERO_RATE_CATEGORIES:
            continue

        # NRS validates tax amounts as non-negative. WHT is reported as a
        # positive magnitude; the row's deduction flag only decides that it
        # belongs in WITHHOLDING_TAX rather than in a VAT bucket.
        normalized_amount = abs(amount)
        if (
            category["id"] == "WITHHOLDING_TAX"
            and not deduction
            and not inv.get("is_return")
        ):
            frappe.throw(
                frappe._(
                    "Tax row '{0}' on {1} is mapped to WITHHOLDING_TAX but "
                    "does not reduce the invoice total. Withholding must be "
                    "a deduction (negative rate or Deduct); NRS then receives "
                    "it as a positive amount in its own tax bucket."
                ).format(tax.description or tax.account_head, inv.name),
                title=frappe._("NRS Withholding Tax Sign"),
            )

        # net_amount is the row's taxable base in document currency and is
        # not cumulative. tax.total includes earlier taxes, so subtracting
        # the row amount from it double-counted multi-rate invoices.
        taxable = abs(flt(tax.get("net_amount")))
        if not taxable:
            percent = abs(flt(tax.get("rate")))
            if percent:
                taxable = abs(amount) * 100.0 / percent
            else:
                taxable = abs(flt(inv.get("net_total")))

        key = (category["id"], round(flt(category.get("percent")), 4))
        if key not in totals:
            totals[key] = {
                "taxable_amount": 0.0,
                "tax_amount": 0.0,
                "category": category,
            }
        totals[key]["tax_amount"] += normalized_amount
        totals[key]["taxable_amount"] += taxable

    # No taxes on the invoice: send no tax_total rather than inventing one.
    if not totals:
        return []

    tax_total = []
    for bucket in totals.values():
        amount = flt(bucket["tax_amount"], 2)
        taxable = flt(bucket["taxable_amount"], 2)
        tax_total.append(
            {
                "tax_amount": amount,
                "tax_subtotal": [
                    {
                        "taxable_amount": taxable,
                        "tax_amount": amount,
                        "tax_category": bucket["category"],
                        "tax_category_percent": bucket["category"]["percent"],
                    }
                ],
            }
        )
    return tax_total


# NRS tax category ids and their default VAT scheme.
# Membership comes from the shared field definition so Select options, the
# installer patch and payload validation cannot drift. Values are default
# percentages only; the payload always sends the row's own rate.
NRS_TAX_CATEGORIES = dict.fromkeys(NRS_TAX_CATEGORY_OPTIONS, 0.0)
NRS_TAX_CATEGORIES["STANDARD_VAT"] = 7.5

# Categories that may legitimately carry a zero tax amount: they describe a
# zero-rated or exempt supply and still need a subtotal.
ZERO_RATE_CATEGORIES = frozenset({"ZERO_VAT", "ZERO_GST", "EXEMPTED"})

# Legacy Select values written by earlier versions of this app. EXEMPT was
# never an NRS tax category; the documented identifier is EXEMPTED.
_TAX_CATEGORY_ALIASES = {"EXEMPT": "EXEMPTED"}


def _normalize_tax_category(value) -> str:
    code = str(value or "").strip().upper()
    return _TAX_CATEGORY_ALIASES.get(code, code)


def _tax_row_amount(tax_row) -> float:
    """Tax amount in document currency, after any invoice-level discount."""
    return flt(tax_row.get("tax_amount_after_discount_amount"))


def _is_tax_deduction(tax_row, amount=None, credit_note=False) -> bool:
    """True when the tax row reduces the invoice total.

    On a credit note every amount is negative because of the document
    direction, not because the row is a deduction. Only an explicit Deduct
    flag or a negative rate makes a credit-note row a deduction.
    """
    if str(tax_row.get("add_deduct_tax") or "").strip().lower() == "deduct":
        return True
    if flt(tax_row.get("rate")) < 0:
        return True
    if credit_note:
        return False
    if amount is None:
        amount = _tax_row_amount(tax_row)
    return flt(amount) < 0


def _document_sign(inv) -> float:
    """+1 for an invoice, -1 for a credit note.

    The 380 type code conveys the credit-note direction, so monetary fields
    are sent as positive magnitudes.
    """
    if inv.get("is_return"):
        return -1.0
    return -1.0 if flt(inv.get("grand_total")) < 0 else 1.0


def _tax_category_from_description(tax_row) -> str:
    """Map tax-row wording to an NRS category.

    Only specific markers match. A generic "VAT" is deliberately ignored so
    an unset template fails validation instead of being guessed as standard
    VAT.
    """
    search = "{} {}".format(
        tax_row.get("description") or "", tax_row.get("account_head") or ""
    ).upper()
    if any(marker in search for marker in ("WITHHOLD", "WHT", "WITHHELD")):
        return "WITHHOLDING_TAX"
    if "STAMP" in search and "DUTY" in search:
        return "STAMP_DUTY"
    if "EXEMPT" in search:
        return "EXEMPTED"
    if "ZERO" in search:
        return "ZERO_GST" if "GST" in search else "ZERO_VAT"
    if "REDUCED" in search and "GST" in search:
        return "REDUCED_GST"
    if "REDUCED" in search and "VAT" in search:
        return "REDUCED_VAT"
    if "SERVICE" in search and "TAX" in search:
        return "SERVICE_TAX"
    if "LOCAL" in search and "SALES" in search:
        return "LOCAL_SALES_TAX"
    if "STATE" in search and "SALES" in search:
        return "STATE_SALES_TAX"
    if "LUXURY" in search:
        return "LUXURY_TAX"
    if "TOURISM" in search:
        return "TOURISM_TAX"
    if "CARBON" in search:
        return "CARBON_TAX"
    if "PLASTIC" in search:
        return "PLASTIC_TAX"
    if "IMPORT" in search and "DUTY" in search:
        return "IMPORT_DUTY"
    if "EXPORT" in search and "DUTY" in search:
        return "EXPORT_DUTY"
    return ""


def _tax_category(code: str, tax_row) -> dict:
    return {
        "id": code,
        "percent": flt(abs(flt(tax_row.get("rate"))), 2),
    }


def _missing_category_message(tax_row, inv, template_category, deduction) -> str:
    row_value = str(tax_row.get("custom_nrs_tax_category") or "").strip()
    template_value = str(template_category or "").strip()
    label = tax_row.get("description") or tax_row.get("account_head") or ""

    if row_value and _normalize_tax_category(row_value) not in NRS_TAX_CATEGORIES:
        return frappe._(
            "Tax row '{0}' on {1} uses NRS Tax Category '{2}', which the "
            "provider does not accept. Choose one of: {3}."
        ).format(label, inv.name, row_value, ", ".join(NRS_TAX_CATEGORY_OPTIONS))

    if template_value and _normalize_tax_category(template_value) not in NRS_TAX_CATEGORIES:
        return frappe._(
            "The taxes and charges template on {0} uses NRS Tax Category "
            "'{1}', which the provider does not accept. Set a supported "
            "category on the template or on tax row '{2}'."
        ).format(inv.name, template_value, label)

    if deduction and row_value:
        return frappe._(
            "Tax row '{0}' on {1} reduces the invoice total but its NRS Tax "
            "Category is '{2}'. Set it to WITHHOLDING_TAX so the deduction "
            "is reported separately from VAT."
        ).format(label, inv.name, row_value)

    if deduction:
        resolved = _normalize_tax_category(
            _tax_category_from_description(tax_row) or template_value
        )
        return frappe._(
            "Tax row '{0}' on {1} reduces the invoice total but resolves to "
            "NRS Tax Category '{2}'. Set NRS Tax Category to WITHHOLDING_TAX "
            "on that row, or remove the deduction, before pushing to NRS."
        ).format(label, inv.name, resolved or "none")

    return frappe._(
        "Tax row '{0}' on {1} has no valid NRS Tax Category. Set one on the "
        "tax row (or its template) using a category accepted by the provider "
        "before pushing to NRS."
    ).format(label, inv.name)


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


def _resolve_tax_category(tax_row, inv=None, template_category: str = "", deduction=None) -> dict:
    """Resolve a tax row to an NRS Tax Category.

    Priority: explicit row category, then specific wording (withholding,
    stamp duty, zero/exempt), then the invoice template's category. A
    deduction may only resolve to WITHHOLDING_TAX; silently reporting a
    negative row under VAT would inflate the tax and break the payable total.
    """
    if deduction is None:
        deduction = _is_tax_deduction(tax_row)

    row_category = _normalize_tax_category(tax_row.get("custom_nrs_tax_category"))
    if row_category:
        if row_category not in NRS_TAX_CATEGORIES:
            return None
        if deduction and row_category != "WITHHOLDING_TAX":
            return None
        return _tax_category(row_category, tax_row)

    description_category = _normalize_tax_category(
        _tax_category_from_description(tax_row)
    )
    if description_category:
        if description_category not in NRS_TAX_CATEGORIES:
            return None
        if deduction and description_category != "WITHHOLDING_TAX":
            return None
        return _tax_category(description_category, tax_row)

    template_category = _normalize_tax_category(template_category)
    if template_category:
        if template_category not in NRS_TAX_CATEGORIES:
            return None
        if deduction and template_category != "WITHHOLDING_TAX":
            return None
        return _tax_category(template_category, tax_row)

    # No silent default: an unclassified row must fail rather than be
    # reported to NRS as standard VAT with an invented percentage.
    return None


def _build_legal_monetary_total(inv, tax_total) -> dict:
    """Build legal_monetary_total from ERPNext's document-currency totals.

    tax_inclusive_amount is the invoiced gross before withholding: line
    extension plus the taxes actually added to the charge. WHT is reported
    as a non-negative TaxTotal component, but it is withheld from the
    payment rather than added to the invoice, so it is excluded from
    tax_inclusive_amount.

    payable_amount is what the buyer actually pays: tax inclusive less the
    withholding. It must equal ERPNext's grand_total in document currency.
    The NRS schema exposes no separate withholding or settlement field, so a
    positive WITHHOLDING_TAX component plus a net payable is the documented
    representation. This also fails loudly if the tax rows cannot produce
    the accounting grand total.
    """
    line_ext = flt(abs(flt(inv.get("net_total"))), 2)
    tax_amount = flt(
        sum(flt(total.get("tax_amount")) for total in tax_total), 2
    )
    withholding = flt(
        sum(
            flt(total.get("tax_amount"))
            for total in tax_total
            if any(
                (sub.get("tax_category") or {}).get("id") == "WITHHOLDING_TAX"
                for sub in total.get("tax_subtotal") or []
            )
        ),
        2,
    )
    non_withholding_tax = flt(tax_amount - withholding, 2)
    tax_inclusive = flt(line_ext + non_withholding_tax, 2)
    payable = flt(tax_inclusive - withholding, 2)
    grand_total = flt(abs(flt(inv.get("grand_total"))), 2)
    if not grand_total and not line_ext:
        grand_total = payable

    if abs(payable - grand_total) > 0.02:
        frappe.throw(
            frappe._(
                "Tax totals for {0} do not reconcile in {1}: line extension "
                "{2}, non-withheld tax {3}, withholding {4}, so tax inclusive "
                "is {5} and payable is {6}, but the invoice grand total is "
                "{7}. Correct the tax rows before pushing to NRS."
            ).format(
                inv.name,
                inv.get("currency") or "",
                line_ext,
                non_withholding_tax,
                withholding,
                tax_inclusive,
                payable,
                grand_total,
            ),
            title=frappe._("NRS Tax Total Mismatch"),
        )

    return {
        "line_extension_amount": line_ext,
        "tax_exclusive_amount": line_ext,
        "tax_inclusive_amount": tax_inclusive,
        "payable_amount": payable,
    }
def _get_payment_status(inv) -> str:
	"""Derive NRS payment_status from the invoice's own payment state.

	Read at payload-build time, so it reflects the invoice as uploaded:
	- fully settled (outstanding <= 0.1) -> PAID
	- anything else -> PENDING
	NRS rejects PARTIAL as an initial status ("initial invoice payment status
	cannot be PARTIAL or REJECTED"), so a partially paid invoice is registered
	PENDING and the partial amount is pushed by the queue right after signing
	(see processor._sync_payment_status_after_sign).
	"""
	if inv.doctype not in ("Sales Invoice", "Purchase Invoice"):
		return "PENDING"
	if inv.get("is_return"):
		# A credit note is never "paid" — register it as PENDING.
		return "PENDING"

	outstanding = flt(inv.get("outstanding_amount"))
	grand_total = flt(inv.get("grand_total"))

	if grand_total and outstanding <= 0.1:
		return "PAID"
	return "PENDING"


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
	# IRN segment: the portal assigns a fixed 8-char segment per taxpayer
	# (shown next to the API key on the portal). Prefer it when configured;
	# derive from Entity ID + Business ID only as a fallback.
	irn_segment = (company.get("custom_firs_irn_segment") or "").strip().upper()
	if not irn_segment:
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
