import frappe


def run():
    from theoskaris_einvoice.utils.qr_generator import generate_invoice_qr

    inv = frappe.get_doc("Sales Invoice", "SINV-00582")
    payload, uri = generate_invoice_qr(inv, inv.custom_nrs_irn)
    inv.db_set("custom_nrs_qr_code", payload)
    inv.db_set("custom_nrs_qr_code_url", uri)
    frappe.db.commit()
    open("/tmp/qr_now.txt", "w").write(payload)
    print("T_REGEN_NOW", len(payload))

    from frappe.utils.pdf import get_pdf
    html = frappe.get_print("Sales Invoice", "SINV-00582", "NRS Tax Invoice", doc=inv.reload(), as_pdf=False)
    open("/tmp/00582_fresh2.pdf", "wb").write(get_pdf(html))
    print("T_PDF_NOW")
