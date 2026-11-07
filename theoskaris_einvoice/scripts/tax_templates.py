import frappe

CO = "RIGHT INSPECTION SERVICES NIGERIA LIMITED"
VAT_ACC = "700030203 - VAT Charge on Sales Invoices - RIS"
WHT_ACC = "800070101 - WHT Withheld/Payable FIRS-NGN - RIS"


def make_template(name, vat=7.5, wht=0.0):
    if frappe.db.exists("Sales Taxes and Charges Template", name):
        print("TPL_EXISTS", name)
        return name
    doc = frappe.get_doc({
        "doctype": "Sales Taxes and Charges Template",
        "title": name,
        "company": CO,
        "is_default": 0,
        "taxes": [
            {
                "charge_type": "On Net Total",
                "account_head": VAT_ACC,
                "rate": vat,
                "description": "VAT @ 7.5%",
                "custom_nrs_tax_category": "STANDARD_VAT",
            },
        ],
    })
    if wht:
        doc.append("taxes", {
            "charge_type": "On Net Total",
            "account_head": WHT_ACC,
            "rate": -wht,
            "description": f"WHT @ {wht}%",
            "custom_nrs_tax_category": "WITHHOLDING_TAX",
        })
    doc.insert(ignore_permissions=True)
    print("TPL_CREATED", name, "vat", vat, "wht", wht)
    return name


def run():
    make_template("RIS VAT 7.5", 7.5, 0)
    make_template("RIS VAT 7.5 + WHT 5", 7.5, 5)
    make_template("RIS VAT 7.5 + WHT 10", 7.5, 10)
    frappe.db.commit()
    print("DONE")
