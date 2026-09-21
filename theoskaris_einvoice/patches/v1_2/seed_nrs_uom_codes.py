import frappe

from theoskaris_einvoice.payload.uom_map import UOM_NRS_CODE_MAP


def execute():
	"""Seed custom_nrs_uom_code on existing UOM docs from the name map."""
	updated = 0
	for uom in frappe.get_all("UOM", pluck="name"):
		doc = frappe.get_doc("UOM", uom)
		if doc.get("custom_nrs_uom_code"):
			continue
		code = UOM_NRS_CODE_MAP.get(doc.name.strip().lower())
		if not code:
			# try the built-in builder map as secondary source
			from theoskaris_einvoice.payload.builder import _UOM_CODE_MAP

			code = _UOM_CODE_MAP.get(doc.name.strip().upper())
		if code:
			doc.db_set("custom_nrs_uom_code", code, update_modified=False)
			updated += 1
	if updated:
		frappe.db.commit()
		print(f"theoskaris_einvoice: seeded NRS UOM code on {updated} UOMs")