import frappe
from theoskaris_einvoice.queue.processor import process_queue_item

CO = "RIGHT INSPECTION SERVICES NIGERIA LIMITED"
FIELDS = ("charge_type", "account_head", "rate", "description", "category", "cost_center", "custom_nrs_tax_category")


def make(tpl, tag):
    master = frappe.get_doc("Sales Taxes and Charges Template", tpl)
    si = frappe.get_doc({
        "doctype": "Sales Invoice",
        "customer": "FIRS Test Buyer Ltd",
        "company": CO,
        "currency": "NGN",
        "posting_date": frappe.utils.today(),
        "set_posting_time": 1,
        "items": [{"item_code": "TEST-RIS-SVC", "qty": 1, "rate": 1000000, "uom": "Nos"}],
        "taxes_and_charges": tpl,
        "remarks": tag,
    })
    for row in master.taxes:
        si.append("taxes", {f: row.get(f) for f in FIELDS})
    si.calculate_taxes_and_totals()
    si.insert(ignore_permissions=True)
    si.submit()
    frappe.db.commit()
    return si


def push(si):
    q = frappe.get_doc({"doctype": "FIRS Queue", "document_type": "Sales Invoice", "document_name": si.name, "status": "Pending"}).insert(ignore_permissions=True)
    frappe.db.commit()
    process_queue_item(q.name)
    st = frappe.db.get_value("FIRS Queue", q.name, ["status", "last_error"], as_dict=True)
    return st.status, (st.last_error or "")[:220]


def run():
    cases = [
        ("RIS VAT 7.5 - RIS", "TAX S1: VAT 7.5 only"),
        ("RIS VAT 7.5 + WHT 5 - RIS", "TAX S2: VAT 7.5 + WHT 5"),
        ("RIS VAT 7.5 + WHT 10 - RIS", "TAX S3: VAT 7.5 + WHT 10"),
    ]
    for tpl, tag in cases:
        si = make(tpl, tag)
        print("CREATED", si.name, "| net", si.net_total, "| grand", si.grand_total, "| taxes", len(si.taxes), "| ready", si.custom_firs_ready)
        status, err = push(si)
        d = frappe.db.get_value("Sales Invoice", si.name, ["custom_nrs_status", "custom_nrs_irn"], as_dict=True)
        print("RESULT", si.name, "| queue", status, "| nrs", d.custom_nrs_status, "| irn", d.custom_nrs_irn)
        if err:
            print("  ERR", err)
