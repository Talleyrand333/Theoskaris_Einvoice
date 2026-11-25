"""Canonical NRS tax category field for taxes and charges rows.

The category on a tax row is more specific than the one on the invoice's
taxes and charges template, so both child tables need the field. These
fields are deliberately not listed in `custom_field.json`:
`install.create_firs_custom_fields()` calls Frappe's
`create_custom_fields(update=True)`, which rewrites existing field
properties and would discard site-level customisations.

This module keeps the definitions instead. The patch creates missing
fields and appends missing options to stale Select fields; labels,
placement, descriptions, defaults and stored values are left untouched.
"""

FIELDNAME = "custom_nrs_tax_category"
LABEL = "NRS Tax Category"

NRS_TAX_CATEGORY_OPTIONS = (
	"STANDARD_VAT",
	"REDUCED_VAT",
	"ZERO_VAT",
	"STANDARD_GST",
	"REDUCED_GST",
	"ZERO_GST",
	"SERVICE_TAX",
	"LOCAL_SALES_TAX",
	"STATE_SALES_TAX",
	"LUXURY_TAX",
	"TOURISM_TAX",
	"EXPORT_DUTY",
	"IMPORT_DUTY",
	"ALCOHOL_EXCISE_TAX",
	"TOBACCO_EXCISE_TAX",
	"FUEL_EXCISE_TAX",
	"CARBON_TAX",
	"PLASTIC_TAX",
	"MEDICARE_TAX",
	"SOCIAL_SECURITY_TAX",
	"CORPORATE_INCOME_TAX",
	"PERSONAL_INCOME_TAX",
	"PERSONAL_PROPERTY_TAX",
	"REAL_ESTATE_TAX",
	"WITHHOLDING_TAX",
	"STAMP_DUTY",
	"EXEMPTED",
)

# Leading blank line lets the Select accept an empty value.
NRS_TAX_CATEGORY_OPTIONS_TEXT = "\n" + "\n".join(NRS_TAX_CATEGORY_OPTIONS)

# Row-level fields owned by this module: (doctype, insert_after).
TAX_ROW_FIELDS = (
	("Sales Taxes and Charges", "account_head"),
	("Purchase Taxes and Charges", "account_head"),
)

# Template fields are seeded from custom_field.json. Listed here so the
# standalone repair script can use the same canonical options.
TAX_TEMPLATE_FIELDS = (
	("Sales Taxes and Charges Template", "taxes"),
	("Purchase Taxes and Charges Template", "taxes"),
)

ALL_TAX_CATEGORY_FIELDS = TAX_ROW_FIELDS + TAX_TEMPLATE_FIELDS


def field_definition(insert_after: str) -> dict:
	"""Return the Custom Field definition for a new row-level field."""
	return {
		"fieldname": FIELDNAME,
		"label": LABEL,
		"fieldtype": "Select",
		"options": NRS_TAX_CATEGORY_OPTIONS_TEXT,
		"insert_after": insert_after,
		"module": "FIRS E-Invoice",
	}


def merge_missing_options(options: str | None) -> str:
	"""Append canonical options missing from an existing Select value.

	Existing lines stay in their original order; unknown/custom lines are
	kept. If every canonical option is already present the original string
	is returned unchanged, so callers can skip the write.
	"""
	existing = [line.strip() for line in (options or "").splitlines() if line.strip()]
	present = set(existing)
	missing = [option for option in NRS_TAX_CATEGORY_OPTIONS if option not in present]
	if not missing:
		return options or ""

	base = (options or "").rstrip("\n")
	if not base:
		return "\n" + "\n".join(missing)
	return base + "\n" + "\n".join(missing)


def _create_field(doctype: str, insert_after: str) -> None:
	from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

	# update=False keeps an existing field (and any site edits) untouched.
	create_custom_fields(
		{doctype: [field_definition(insert_after)]},
		update=False,
	)


def ensure_nrs_tax_category_fields(doctypes=None, add_missing_options: bool = True) -> dict:
	"""Ensure the row-level fields exist; optionally widen stale options.

	Returns `{"created": [...], "updated": [...], "skipped": [...]}`.
	Existing fields are never rewritten except to append canonical options
	when `add_missing_options` is true. Set it to false from after_migrate
	so later site customisations are not touched on every migrate.
	"""
	import frappe

	targets = list(doctypes) if doctypes else [doctype for doctype, _ in TAX_ROW_FIELDS]
	insert_after = dict(ALL_TAX_CATEGORY_FIELDS)
	result = {"created": [], "updated": [], "skipped": []}

	for doctype in targets:
		existing = frappe.db.get_value(
			"Custom Field",
			{"dt": doctype, "fieldname": FIELDNAME},
			["name", "fieldtype", "options"],
			as_dict=True,
		)

		if not existing:
			_create_field(doctype, insert_after.get(doctype, "account_head"))
			result["created"].append(doctype)
			continue

		# A non-Select field is a site decision; never rewrite its options.
		if not add_missing_options or existing["fieldtype"] != "Select":
			result["skipped"].append(doctype)
			continue

		merged = merge_missing_options(existing["options"])
		if merged == (existing["options"] or ""):
			result["skipped"].append(doctype)
			continue

		frappe.db.set_value(
			"Custom Field",
			existing["name"],
			"options",
			merged,
			update_modified=False,
		)
		frappe.clear_cache(doctype=doctype)
		result["updated"].append(doctype)

	if result["created"] or result["updated"]:
		print(
			"theoskaris_einvoice: NRS tax category fields "
			f"created={result['created']} updated={result['updated']}"
		)
	return result
