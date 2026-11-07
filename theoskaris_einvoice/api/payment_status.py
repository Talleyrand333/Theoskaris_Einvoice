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

	# The registry must mirror the accounting record: derive what ERPNext
	# actually knows and refuse anything the invoice does not support.
	outstanding = flt(invoice.get("outstanding_amount"))
	grand_total = flt(invoice.get("grand_total"))
	paid = grand_total - outstanding

	if status == "PAID":
		if outstanding > 0.009:
			frappe.throw(
				_(
					"Invoice {0} still has {1} outstanding in ERPNext. Record the "
					"payment first; NRS must not show PAID before the books do."
				).format(invoice.name, frappe.format_value(outstanding, {"fieldtype": "Currency"})),
				title=_("Payment Not Recorded"),
			)
	else:
		amount = flt(amount)
		if paid <= 0:
			frappe.throw(
				_("No payment is recorded against {0}; nothing to send as PARTIAL.").format(
					invoice.name
				),
				title=_("Payment Not Recorded"),
			)
		if outstanding <= 0.009:
			frappe.throw(
				_("Invoice {0} is fully paid in ERPNext. Use PAID instead.").format(invoice.name),
				title=_("Invoice Fully Paid"),
			)
		if amount <= 0:
			frappe.throw(_("Enter the amount paid for a PARTIAL update."))
		if amount > paid + 0.009:
			frappe.throw(
				_(
					"Amount {0} exceeds the {1} actually received against {2}."
				).format(
					frappe.format_value(amount, {"fieldtype": "Currency"}),
					frappe.format_value(paid, {"fieldtype": "Currency"}),
					invoice.name,
				),
				title=_("Amount Exceeds Payments"),
			)

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
