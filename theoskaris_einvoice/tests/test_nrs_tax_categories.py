"""Focused checks for NRS tax category field definitions and upgrades."""

import json
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from theoskaris_einvoice.utils import nrs_tax_categories as tax_categories

APP_DIR = Path(__file__).resolve().parents[1]
STALE_OPTIONS = "\nSTANDARD_VAT\nZERO_VAT\nEXEMPT\nWITHHOLDING_TAX\nSTAMP_DUTY"


class CanonicalOptionsTest(unittest.TestCase):
	def test_options_are_27_and_unique(self):
		options = tax_categories.NRS_TAX_CATEGORY_OPTIONS
		self.assertEqual(len(options), 27)
		self.assertEqual(len(set(options)), 27)
		self.assertEqual(options[0], "STANDARD_VAT")
		self.assertEqual(options[-2:], ("STAMP_DUTY", "EXEMPTED"))

	def test_withholding_and_stamp_duty_are_supported(self):
		for code in ("WITHHOLDING_TAX", "STAMP_DUTY", "EXEMPTED"):
			self.assertIn(code, tax_categories.NRS_TAX_CATEGORY_OPTIONS)
		self.assertNotIn("EXEMPT", tax_categories.NRS_TAX_CATEGORY_OPTIONS)

	def test_template_json_uses_the_same_options(self):
		data = json.loads((APP_DIR / "custom_field.json").read_text(encoding="utf-8"))
		for doctype in (
			"Sales Taxes and Charges Template",
			"Purchase Taxes and Charges Template",
		):
			entry = next(
				row
				for row in data
				if row["dt"] == doctype and row["fieldname"] == tax_categories.FIELDNAME
			)
			self.assertEqual(
				[line for line in entry["options"].splitlines() if line.strip()],
				list(tax_categories.NRS_TAX_CATEGORY_OPTIONS),
				doctype,
			)

	def test_field_definition_targets_row_field(self):
		definition = tax_categories.field_definition("account_head")
		self.assertEqual(definition["fieldname"], "custom_nrs_tax_category")
		self.assertEqual(definition["fieldtype"], "Select")
		self.assertEqual(definition["insert_after"], "account_head")
		self.assertEqual(definition["options"], tax_categories.NRS_TAX_CATEGORY_OPTIONS_TEXT)


class MergeOptionsTest(unittest.TestCase):
	def test_empty_options_get_full_list(self):
		merged = tax_categories.merge_missing_options(None)
		self.assertEqual(merged, tax_categories.NRS_TAX_CATEGORY_OPTIONS_TEXT)

	def test_stale_options_are_widened_without_dropping_custom_entries(self):
		merged = tax_categories.merge_missing_options(STALE_OPTIONS)
		lines = [line for line in merged.splitlines() if line.strip()]
		self.assertEqual(lines[:5], ["STANDARD_VAT", "ZERO_VAT", "EXEMPT", "WITHHOLDING_TAX", "STAMP_DUTY"])
		self.assertEqual(lines[5:], [
			option for option in tax_categories.NRS_TAX_CATEGORY_OPTIONS
			if option not in {
				"STANDARD_VAT",
				"ZERO_VAT",
				"EXEMPT",
				"WITHHOLDING_TAX",
				"STAMP_DUTY",
			}
		])

	def test_canonical_options_are_returned_unchanged(self):
		original = "\n" + "\n".join(tax_categories.NRS_TAX_CATEGORY_OPTIONS) + "\n"
		self.assertEqual(tax_categories.merge_missing_options(original), original)


class EnsureFieldsTest(unittest.TestCase):
	def _fake_frappe(self, rows):
		frappe = types.ModuleType("frappe")

		class DB:
			def __init__(self):
				self.rows = rows
				self.set_calls = []

			def get_value(self, doctype, filters, fields, as_dict=False):
				return self.rows.get(filters["dt"])

			def set_value(self, doctype, name, fieldname, value, **kwargs):
				self.set_calls.append((name, fieldname, value, kwargs))

		frappe.db = DB()

		def clear_cache(**kwargs):
			return None

		frappe.clear_cache = clear_cache
		return frappe

	def test_creates_missing_field_with_canonical_definition(self):
		frappe = self._fake_frappe({})
		with mock.patch.dict(sys.modules, {"frappe": frappe}), mock.patch.object(
			tax_categories, "_create_field"
		) as create:
			result = tax_categories.ensure_nrs_tax_category_fields(
				doctypes=["Sales Taxes and Charges"]
			)

		self.assertEqual(result["created"], ["Sales Taxes and Charges"])
		create.assert_called_once_with("Sales Taxes and Charges", "account_head")
		self.assertEqual(frappe.db.set_calls, [])

	def test_appends_missing_options_to_existing_field(self):
		frappe = self._fake_frappe(
			{
				"Sales Taxes and Charges": {
					"name": "Sales Taxes and Charges-custom_nrs_tax_category",
					"fieldtype": "Select",
					"options": STALE_OPTIONS,
				}
			}
		)
		with mock.patch.dict(sys.modules, {"frappe": frappe}), mock.patch.object(
			tax_categories, "_create_field"
		) as create:
			result = tax_categories.ensure_nrs_tax_category_fields(
				doctypes=["Sales Taxes and Charges"]
			)

		self.assertEqual(result["updated"], ["Sales Taxes and Charges"])
		create.assert_not_called()
		_, fieldname, options, kwargs = frappe.db.set_calls[0]
		self.assertEqual(fieldname, "options")
		self.assertIn("STAMP_DUTY", options)
		self.assertIn("EXEMPT", options)
		self.assertEqual(kwargs, {"update_modified": False})

	def test_existing_canonical_field_is_not_written(self):
		options = "\n" + "\n".join(tax_categories.NRS_TAX_CATEGORY_OPTIONS)
		frappe = self._fake_frappe(
			{
				"Sales Taxes and Charges": {
					"name": "Sales Taxes and Charges-custom_nrs_tax_category",
					"fieldtype": "Select",
					"options": options,
				}
			}
		)
		with mock.patch.dict(sys.modules, {"frappe": frappe}):
			result = tax_categories.ensure_nrs_tax_category_fields(
				doctypes=["Sales Taxes and Charges"]
			)

		self.assertEqual(result["skipped"], ["Sales Taxes and Charges"])
		self.assertEqual(frappe.db.set_calls, [])

	def test_after_migrate_mode_leaves_existing_options_alone(self):
		frappe = self._fake_frappe(
			{
				"Sales Taxes and Charges": {
					"name": "Sales Taxes and Charges-custom_nrs_tax_category",
					"fieldtype": "Select",
					"options": STALE_OPTIONS,
				}
			}
		)
		with mock.patch.dict(sys.modules, {"frappe": frappe}):
			result = tax_categories.ensure_nrs_tax_category_fields(
				doctypes=["Sales Taxes and Charges"],
				add_missing_options=False,
			)

		self.assertEqual(result["skipped"], ["Sales Taxes and Charges"])
		self.assertEqual(frappe.db.set_calls, [])

	def test_non_select_field_is_not_rewritten(self):
		frappe = self._fake_frappe(
			{
				"Sales Taxes and Charges": {
					"name": "Sales Taxes and Charges-custom_nrs_tax_category",
					"fieldtype": "Data",
					"options": "keep-me",
				}
			}
		)
		with mock.patch.dict(sys.modules, {"frappe": frappe}):
			result = tax_categories.ensure_nrs_tax_category_fields(
				doctypes=["Sales Taxes and Charges"]
			)

		self.assertEqual(result["skipped"], ["Sales Taxes and Charges"])
		self.assertEqual(frappe.db.set_calls, [])


if __name__ == "__main__":
	unittest.main()
