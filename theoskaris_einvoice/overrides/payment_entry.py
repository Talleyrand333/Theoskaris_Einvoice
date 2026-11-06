"""Sync invoice payment status to NRS when Payment Entries reconcile.

On Payment Entry submit (and cancel), every reconciled Sales/Purchase Invoice
that is registered with NRS (has an IRN) gets an update call:
  - outstanding > 0 → PARTIAL + allocated amount + reference
  - outstanding == 0 → PAID (terminal; further updates rejected)

Register-side rules (verified live 2026-11-06):
  - Initial registration only accepts PENDING/PAID (not PARTIAL).
  - PARTIAL updates may repeat until settled; PAID is terminal.
"""

import frappe

from theoskaris_einvoice.api.client_base import FIRSAPIError, get_firs_client


def _sync_reference_invoice(ref):
    """Sync one reference row of a submitted Payment Entry."""
    dt, dn = ref.reference_doctype, ref.reference_name
    if dt not in ("Sales Invoice", "Purchase Invoice"):
        return
    irn = frappe.db.get_value(dt, dn, "custom_nrs_irn")
    if not irn:
        return  # never registered with NRS — nothing to update

    company = frappe.db.get_value(dt, dn, "company")
    outstanding = frappe.db.get_value(dt, dn, "outstanding_amount") or 0
    grand_total = frappe.db.get_value(dt, dn, "grand_total") or 0

    client = get_firs_client(company)
    if outstanding <= 0.009 and grand_total:
        status, amount = "PAID", None
    else:
        status, amount = "PARTIAL", abs(ref.allocated_amount)

    try:
        resp = client.update_payment_status(
            irn, status, amount=amount, reference=ref.parent
        )
        frappe.logger("firs-einvoice").info(
            {"event": "payment-status-synced", "invoice": dn, "irn": irn,
             "status": status, "amount": amount, "response": resp}
        )
    except FIRSAPIError as e:
        # Terminal-state errors mean the registry is already PAID/REJECTED —
        # expected on re-submits; log quietly instead of failing the PE.
        msg = str(e)
        if "terminal state" in msg:
            frappe.logger("firs-einvoice").info(
                {"event": "payment-update-skipped-terminal", "invoice": dn, "irn": irn}
            )
            return
        frappe.log_error(
            title="FIRS payment status update failed",
            message=f"Invoice {dn}, IRN {irn}: {msg}\n"
            f"response: {getattr(e, 'response_body', None)}",
        )
    except Exception:
        frappe.log_error(
            title="FIRS payment status sync error",
            message=frappe.get_traceback(),
        )


def on_submit(doc, method=None):
    """Payment Entry submitted — sync every reconciled invoice."""
    for ref in doc.references or []:
        try:
            _sync_reference_invoice(ref)
        except Exception:
            frappe.log_error(
                title="FIRS payment sync row error",
                message=f"PE {doc.name}, ref {ref.reference_name}\n{frappe.get_traceback()}",
            )
