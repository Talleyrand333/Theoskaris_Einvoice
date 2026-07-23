"""Installation hooks for Theoskaris Einvoice."""

import json
from pathlib import Path

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


MODULE_NAME = "Theoskaris Einvoice"
APP_DIR = Path(__file__).resolve().parent


def after_install():
	"""Seed reference data, settings, and ensure custom fields exist."""
	frappe.clear_cache(doctype="FIRS Tax Category")
	frappe.clear_cache(doctype="FIRS Payment Means Code")
	frappe.clear_cache(doctype="FIRS Settings")
	_create_firs_settings()
	create_firs_custom_fields()
	seed_tax_categories()
	seed_payment_means_codes()


def _create_firs_settings():
	"""Create default FIRS Settings if not exists."""
	if not frappe.db.exists("FIRS Settings", "FIRS Settings"):
		settings = frappe.new_doc("FIRS Settings")
		settings.enable_sales_invoice = 1
		settings.enable_purchase_invoice = 0
		settings.insert(ignore_permissions=True)
		frappe.db.commit()


def create_firs_custom_fields():
	"""Create custom fields on Company, Sales Invoice, Customer, Sales Invoice Item."""
	with open(APP_DIR / "custom_field.json", "r") as f:
		field_list = json.load(f)

	grouped = {}
	for cf in field_list:
		if cf.get("doctype") != "Custom Field":
			continue
		dt = cf.pop("dt", None)
		# Remove internal keys not accepted by create_custom_fields
		cf.pop("doctype", None)
		cf.pop("module", None)
		cf.pop("name", None)
		if not dt:
			continue
		grouped.setdefault(dt, []).append(cf)

	create_custom_fields(grouped)
	frappe.db.commit()


def seed_tax_categories():
	"""Pre-seed standard Nigerian FIRS tax categories."""
	categories = [
		{"tax_category_id": "STANDARD_VAT", "tax_rate": 7.5, "description": "Standard VAT"},
		{"tax_category_id": "ZERO_VAT", "tax_rate": 0.0, "description": "Zero-rated VAT"},
		{"tax_category_id": "EXEMPT", "tax_rate": 0.0, "description": "VAT Exempt"},
	]
	for cat in categories:
		if not frappe.db.exists("FIRS Tax Category", cat["tax_category_id"]):
			doc = frappe.new_doc("FIRS Tax Category")
			doc.tax_category_id = cat["tax_category_id"]
			doc.tax_rate = cat["tax_rate"]
			doc.description = cat["description"]
			doc.insert(ignore_permissions=True)
	frappe.db.commit()


def seed_payment_means_codes():
	"""Pre-seed common FIRS payment means codes (configurable by user)."""
	codes = [
		{"code": "01", "description": "Cash"},
		{"code": "03", "description": "Cheque"},
		{"code": "10", "description": "Bank Transfer"},
		{"code": "30", "description": "Card / POS"},
		{"code": "42", "description": "Payment to bank account"},
		{"code": "49", "description": "Direct debit"},
	]
	for code in codes:
		if not frappe.db.exists("FIRS Payment Means Code", code["code"]):
			doc = frappe.new_doc("FIRS Payment Means Code")
			doc.code = code["code"]
			doc.description = code["description"]
			doc.insert(ignore_permissions=True)
	frappe.db.commit()
