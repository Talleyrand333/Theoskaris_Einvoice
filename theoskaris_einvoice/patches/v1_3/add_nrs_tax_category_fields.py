"""Add NRS Tax Category to sales and purchase tax rows.

The template fields already exist; the row fields were previously created
by an ad-hoc script whose option list stopped at five categories. Run after
model sync so the child doctypes and their columns exist. Existing fields
are preserved: only missing fields are created, and stale Select options
are widened by appending the canonical categories.
"""

from theoskaris_einvoice.utils.nrs_tax_categories import ensure_nrs_tax_category_fields


def execute():
	result = ensure_nrs_tax_category_fields()
	print(
		"theoskaris_einvoice: NRS tax category rows "
		f"created={result['created']} updated={result['updated']} "
		f"skipped={result['skipped']}"
	)
