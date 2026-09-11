"""Remove the FIRS TIN custom field from Customer and Supplier.

TIN now lives in the standard Tax ID field on both doctypes, so the
app-specific field is redundant. create_custom_fields() only adds or
updates fields, it never deletes, so removal needs an explicit patch.
"""

import frappe

PARTIES = ("Customer", "Supplier")
FIELDNAME = "custom_firs_tin"


def execute():
	for dt in PARTIES:
		name = frappe.db.get_value(
			"Custom Field", {"dt": dt, "fieldname": FIELDNAME}, "name"
		)
		if name:
			frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
			print(f"Deleted Custom Field {dt}.{FIELDNAME} ({name})")

	frappe.clear_cache()
