import base64
import json

import frappe


def run():
    try:
        _run()
    except Exception:
        import traceback
        traceback.print_exc()


def _run():
    from theoskaris_einvoice.queue.processor import process_queue_item
    from theoskaris_einvoice.queue.scheduler import enqueue_invoice

    company = "RIGHT INSPECTION SERVICES NIGERIA LIMITED"
    prev = frappe.get_doc("Sales Invoice", "SINV-00582")
    inv = frappe.new_doc("Sales Invoice")
    inv.company = company
    inv.customer = prev.customer
    inv.remarks = "MBS360 QR format test"
    inv.posting_date = frappe.utils.today()
    inv.append("items", {
        "item_code": prev.items[0].item_code,
        "qty": 1,
        "rate": 30000,
        "income_account": prev.items[0].income_account,
    })
    inv.insert(ignore_permissions=True)
    inv.submit()
    frappe.db.commit()
    print("T_INV", inv.name, "| total", inv.grand_total)

    q = enqueue_invoice("Sales Invoice", inv.name)
    print("T_Q", q)
    process_queue_item(q)

    doc = frappe.db.get_value(
        "Sales Invoice", inv.name,
        ["custom_nrs_irn", "custom_nrs_status", "custom_nrs_qr_code"],
        as_dict=True,
    )
    print("T_IRN", doc.custom_nrs_irn, "| status", doc.custom_nrs_status)
    print("T_QR_LEN", len(doc.custom_nrs_qr_code or ""))
    open("/tmp/new_invoice_qr.txt", "w").write(doc.custom_nrs_qr_code or "")
    print("T_QUEUE", frappe.db.get_value("FIRS Queue", q, "status"))

    # verify the fresh QR server-side
    code = doc.custom_nrs_qr_code
    if code:
        import urllib.request
        import urllib.error
        body = {"code": code, "deviceId": "lumos-e2e-005", "deviceName": "Lumos Test Device", "modelName": "Server"}
        req = urllib.request.Request(
            "https://api.firsmbs.com/api/v1/integration/verify_stamp",
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                print("T_VERIFY", r.status, r.read().decode()[:300])
        except urllib.error.HTTPError as e:
            print("T_VERIFY", e.code, e.read().decode()[:300])

    # fresh PDF for scanning
    from frappe.utils.pdf import get_pdf
    html = frappe.get_print(
        "Sales Invoice", inv.name, "NRS Tax Invoice",
        doc=frappe.get_doc("Sales Invoice", inv.name), as_pdf=False,
    )
    open(f"/tmp/{inv.name}.pdf", "wb").write(get_pdf(html))
    print("T_PDF_DONE", inv.name)
