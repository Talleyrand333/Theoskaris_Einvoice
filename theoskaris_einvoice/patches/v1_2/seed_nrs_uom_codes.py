import frappe

from theoskaris_einvoice.payload.uom_map import UOM_NRS_CODE_MAP


def execute():
	"""Seed custom_nrs_uom_code on existing UOM docs from the name map.

	Defensive: skips silently if the custom field does not exist yet
	(fresh installs run patches before after_install creates the field;
	install.after_install seeds there instead). Idempotent: never
	overwrites an existing value.
	"""
	if not frappe.db.has_column("UOM", "custom_nrs_uom_code"):
		print("theoskaris_einvoice: custom_nrs_uom_code column missing, skipping seed")
		return

	_seed_uom_codes()


def _seed_uom_codes() -> int:
	"""Fill blank custom_nrs_uom_code values on existing UOMs. Returns count."""
	from theoskaris_einvoice.payload.builder import _UOM_CODE_MAP

	updated = 0
	for uom in frappe.get_all("UOM", pluck="name"):
		doc = frappe.get_doc("UOM", uom)
		if doc.get("custom_nrs_uom_code"):
			continue
		code = UOM_NRS_CODE_MAP.get(doc.name.strip().lower()) or _UOM_CODE_MAP.get(
			doc.name.strip().upper()
		)
		if code:
			doc.db_set("custom_nrs_uom_code", code, update_modified=False)
			updated += 1
	if updated:
		frappe.db.commit()
		print(f"theoskaris_einvoice: seeded NRS UOM code on {updated} UOMs")
	return updated