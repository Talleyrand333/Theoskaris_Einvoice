"""Installation hooks for Theoskaris Einvoice."""

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

APP_DIR = Path(__file__).resolve().parent

# Layout fieldtypes have no DB column; switching between them is metadata-only.
_LAYOUT_TYPES = {"Section Break", "Column Break", "Tab Break"}


def _safe_fieldtype_change(old: str, new: str) -> bool:
	"""Only widening text-family changes (varchar/text/longtext -> longtext)
	and layout<->layout swaps are safe to auto-fix. Everything else keeps
	Frappe's "cannot be changed" guard — it may be catching a real mistake.
	"""
	if old in _LAYOUT_TYPES or new in _LAYOUT_TYPES:
		return old in _LAYOUT_TYPES and new in _LAYOUT_TYPES
	old_col = frappe.db.type_map.get(old, ("",))[0]
	new_col = frappe.db.type_map.get(new, ("",))[0]
	return new_col == "longtext" and old_col in ("varchar", "text", "longtext")


def _fix_legacy_fieldtypes(grouped: dict):
	"""Sync fieldtypes the app deliberately changed (c8f152b: Attach->Long Text,
	Data->Long Text, Section Break->Tab Break) on sites still carrying the old
	type. create_custom_fields refuses fieldtype changes, so older sites crash
	on every migrate. Flip the safe ones directly in DB (bypassing validate);
	updatedb then widens the column.
	"""
	for dt, fields in grouped.items():
		for df in fields:
			row = frappe.db.get_value(
				"Custom Field", {"dt": dt, "fieldname": df["fieldname"]}, ["name", "fieldtype"]
			)
			if not row or row[1] == df["fieldtype"]:
				continue
			old, new = row[1], df["fieldtype"]
			if not _safe_fieldtype_change(old, new):
				continue
			frappe.db.set_value("Custom Field", row[0], "fieldtype", new, update_modified=False)
			frappe.clear_cache(doctype=dt)
			frappe.db.updatedb(dt)
			print(f"theoskaris_einvoice: {dt}.{df['fieldname']} fieldtype {old} -> {new}")


def after_install():
	"""Seed reference data, settings, and ensure custom fields exist."""
	frappe.clear_cache(doctype="FIRS Settings")
	_create_firs_settings()
	create_firs_custom_fields()
	# Seed UOM codes now that the custom field exists (patches run before
	# after_install on fresh installs).
	from theoskaris_einvoice.patches.v1_2.seed_nrs_uom_codes import _seed_uom_codes

	_seed_uom_codes()


def after_migrate():
	"""Re-apply custom fields on migrate (handles field additions/changes)."""
	create_firs_custom_fields()
	# Upgrade sites run the UOM seed patch before this hook creates the
	# column (patches run first), so the patch silently skips there. Re-seed;
	# _seed_uom_codes is idempotent and never overwrites existing values.
	if frappe.db.has_column("UOM", "custom_nrs_uom_code"):
		from theoskaris_einvoice.patches.v1_2.seed_nrs_uom_codes import _seed_uom_codes

		_seed_uom_codes()


def _create_firs_settings():
	"""Create default FIRS Settings if not exists."""
	if not frappe.db.exists("FIRS Settings", "FIRS Settings"):
		settings = frappe.new_doc("FIRS Settings")
		settings.enable_sales_invoice = 1
		settings.enable_purchase_invoice = 0
		settings.insert(ignore_permissions=True)
		frappe.db.commit()


def create_firs_custom_fields():
	"""Create all custom fields defined in custom_field.json.

	Reads the JSON file and groups entries by target DocType,
	then calls Frappe's create_custom_fields to idempotently
	create or update them.
	"""
	with open(APP_DIR / "custom_field.json", "r") as f:
		field_list = json.load(f)

	grouped = {}
	for cf in field_list:
		# All entries should have doctype="Custom Field"
		doctype_val = cf.get("doctype")
		if doctype_val and doctype_val != "Custom Field":
			continue

		dt = cf.get("dt")
		if not dt:
			continue

		# Build a clean field dict — strip internal keys
		field_data = {
			"fieldname": cf["fieldname"],
			"label": cf["label"],
			"fieldtype": cf["fieldtype"],
			"insert_after": cf.get("insert_after"),
			"module": "FIRS E-Invoice",
		}

		# Optional fields
		for opt_key in [
			"options",
			"default",
			"read_only",
			"no_copy",
			"reqd",
			"description",
			"allow_on_submit",
		]:
			if opt_key in cf:
				field_data[opt_key] = cf[opt_key]

		grouped.setdefault(dt, []).append(field_data)

	if grouped:
		_fix_legacy_fieldtypes(grouped)
		create_custom_fields(grouped)
		frappe.db.commit()