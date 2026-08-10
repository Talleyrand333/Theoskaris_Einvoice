"""Installation hooks for Theoskaris Einvoice."""

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

APP_DIR = Path(__file__).resolve().parent


def after_install():
	"""Seed reference data, settings, and ensure custom fields exist."""
	frappe.clear_cache(doctype="FIRS Settings")
	_create_firs_settings()
	create_firs_custom_fields()


def after_migrate():
	"""Re-apply custom fields on migrate (handles field additions/changes)."""
	create_firs_custom_fields()


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
		create_custom_fields(grouped)
		frappe.db.commit()