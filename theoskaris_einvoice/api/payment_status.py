"""Whitelisted endpoint: push an invoice's payment status to NRS.

NRS refuses PARTIAL at registration time, so a partially paid invoice is
registered as PENDING and later moved to PARTIAL (or PAID) through
PATCH /invoice/update/{irn}. This exposes that call to the desk UI.
"""

import frappe
from frappe import _
from frappe.utils import flt

from theoskaris_einvoice.api.client_base import FIRSAPIError, get_firs_client


@frappe.whitelist()
def push_payment_status(invoice, status, amount=None, reference=None):
	invoice = frappe.get_doc("Sales Invoice", invoice)
	if invoice.docstatus != 1:
		frappe.throw(_("Submit the invoice before updating its NRS payment status."))

	irn = invoice.get("custom_nrs_irn")
	if not irn:
		frappe.throw(
			_("Invoice {0} has no IRN. Push it to NRS first.").format(invoice.name)
		)

	status = (status or "").upper()
	if status not in ("PARTIAL", "PAID"):
		frappe.throw(_("Status must be PARTIAL or PAID."))

	if status == "PARTIAL":
		amount = flt(amount)
		if amount <= 0:
			frappe.throw(_("Enter the amount paid for a PARTIAL update."))

	client = get_firs_client(invoice.company)
	try:
		response = client.update_payment_status(
			irn, status, amount=amount, reference=reference
		)
	except FIRSAPIError as e:
		frappe.throw(
			_("NRS rejected the payment update: {0}").format(
				getattr(e, "response_body", None) or str(e)
			),
			title=_("NRS Payment Update"),
		)

	frappe.db.set_value(
		"Sales Invoice",
		invoice.name,
		"custom_nrs_response",
		frappe.as_json(
			{
				"payment_status_update": {
					"status": status,
					"amount": amount,
					"reference": reference,
					"response": response,
				}
			}
		),
		update_modified=False,
	)

	return {"irn": irn, "status": status, "response": response}
