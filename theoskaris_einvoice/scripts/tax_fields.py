import frappe

OPTIONS = "\nSTANDARD_VAT\nZERO_VAT\nEXEMPT\nWITHHOLDING_TAX\nSTAMP_DUTY"


def ensure_field(dt, fieldname, label, insert_after=None):
    if frappe.db.exists("Custom Field", {"dt": dt, "fieldname": fieldname}):
        cf = frappe.get_doc("Custom Field", {"dt": dt, "fieldname": fieldname})
        cf.options = OPTIONS
        cf.save(ignore_permissions=True)
        print("UPDATED", dt, fieldname)
        return
    doc = {
        "doctype": "Custom Field",
        "dt": dt,
        "fieldname": fieldname,
        "label": label,
        "fieldtype": "Select",
        "options": OPTIONS,
        "insert_after": insert_after,
        "module": "FIRS E-Invoice",
    }
    frappe.get_doc(doc).insert(ignore_permissions=True)
    print("CREATED", dt, fieldname)


def run():
    ensure_field("Sales Taxes and Charges Template", "custom_nrs_tax_category", "NRS Tax Category")
    ensure_field("Purchase Taxes and Charges Template", "custom_nrs_tax_category", "NRS Tax Category")
    ensure_field("Sales Taxes and Charges", "custom_nrs_tax_category", "NRS Tax Category", "account_head")
    ensure_field("Purchase Taxes and Charges", "custom_nrs_tax_category", "NRS Tax Category", "account_head")
    frappe.db.commit()
    print("DONE")
