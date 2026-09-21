"""UOM doc_events overrides for Theoskaris Einvoice."""

import frappe

from theoskaris_einvoice.payload.uom_map import UOM_NRS_CODE_MAP


def before_validate(doc, method=None):
	"""Auto-fill custom_nrs_uom_code for new UOMs from the name map.

	Never overwrites a manually-set value.
	"""
	if doc.get("custom_nrs_uom_code"):
		return
	if not frappe.db.has_column("UOM", "custom_nrs_uom_code"):
		return
	code = UOM_NRS_CODE_MAP.get(doc.uom_name.strip().lower()) or UOM_NRS_CODE_MAP.get(
		doc.name.strip().lower() if doc.name else ""
	)
	if code:
		doc.custom_nrs_uom_code = code