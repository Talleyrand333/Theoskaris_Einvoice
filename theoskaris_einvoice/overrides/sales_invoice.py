"""Sales Invoice DocEvent handlers for FIRS e-Invoicing."""

import frappe

from theoskaris_einvoice.payload.validators import (
	FIRSValidationError,
	assert_not_transmitted,
	can_transmit,
	validate_sales_invoice,
)
from theoskaris_einvoice.queue.scheduler import enqueue_invoice


def validate(doc, method=None):
	"""Light validation: warn if FIRS data is missing."""
	if not doc.get("custom_submit_to_nrs"):
		return
	company = frappe.get_doc("Company", doc.company)
	if not company.get("custom_firs_enabled"):
		return
	# Light check only; full validation happens at before_submit
	for item in doc.items:
		if not item.get("custom_firs_hsn_code"):
			frappe.msgprint(
				f"Item {item.item_code} is missing FIRS HSN code. Submission may fail.",
				title="FIRS Validation",
				indicator="orange",
			)


def before_submit(doc, method=None):
	"""Hard validation before submission."""
	if not doc.get("custom_submit_to_nrs"):
		return
	try:
		validate_sales_invoice(doc)
	except FIRSValidationError as e:
		frappe.throw(str(e), title="FIRS Validation Failed")


def on_submit(doc, method=None):
	"""Queue invoice for FIRS transmission after ERPNext submit."""
	if not can_transmit(doc):
		return
	queue_name = enqueue_invoice(doc.doctype, doc.name)
	if queue_name:
		doc.db_set("custom_nrs_status", "Pending")
		frappe.msgprint(
			f"Sales Invoice queued for FIRS submission (Queue: {queue_name}).",
			title="FIRS Queue",
			indicator="blue",
		)
		# Enqueue processing immediately so the user doesn't have to wait for the cron
		frappe.enqueue(
			method="theoskaris_einvoice.queue.processor.process_queue_item",
			queue="short",
			job_name=f"firs-immediate-{queue_name}",
			queue_name=queue_name,
		)


def before_cancel(doc, method=None):
	"""Block cancellation if invoice already transmitted."""
	assert_not_transmitted(doc)


def on_cancel(doc, method=None):
	"""No-op; cancellation already blocked before."""
	pass
