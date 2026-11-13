import base64

import frappe


def run():
    from frappe.utils.pdf import get_pdf

    html = frappe.get_print(
        "Sales Invoice", "SINV-00582", "NRS Tax Invoice",
        doc=frappe.get_doc("Sales Invoice", "SINV-00582"), as_pdf=False,
    )
    pdf = get_pdf(html)
    open("/tmp/00582_fresh.pdf", "wb").write(pdf)
    print("T_PDF", len(pdf))

    # extract embedded PNG from the PDF and decode the QR from it
    uri = frappe.db.get_value("Sales Invoice", "SINV-00582", "custom_nrs_qr_code_url")
    open("/tmp/00582_current_qr.png", "wb").write(base64.b64decode(uri.split(",", 1)[1]))
    print("T_SAVED_PNG")
