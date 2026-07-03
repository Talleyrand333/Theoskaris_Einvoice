"""Bulk submission API for Sales Invoices."""

import frappe
from frappe import _

from theoskaris_einvoice.payload.validators import can_transmit, validate_sales_invoice
from theoskaris_einvoice.queue.scheduler import enqueue_invoice


@frappe.whitelist()
def submit_selected_to_firs(docnames: list) -> dict:
	"""Queue a list of Sales Invoice names for FIRS submission."""
	queued = 0
	errors = []
	for name in docnames:
		inv = frappe.get_doc("Sales Invoice", name)
		if not can_transmit(inv):
			errors.append(_("{0}: cannot transmit (already transmitted or not flagged)").format(name))
			continue
		try:
			validate_sales_invoice(inv)
			queue_name = enqueue_invoice(inv.doctype, inv.name)
			if queue_name:
				queued += 1
		except Exception as e:
			errors.append(f"{name}: {e}")
			frappe.log_error(title="FIRS Bulk Submit Error", message=frappe.get_traceback())

	return {"queued": queued, "errors": errors}
