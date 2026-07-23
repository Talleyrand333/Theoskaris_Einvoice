"""Cron scheduler entrypoint for FIRS Queue processing."""

import frappe

from theoskaris_einvoice.firs_e_invoice.doctype.firs_queue.firs_queue import FIRSQueue
from theoskaris_einvoice.queue.processor import process_queue_item


@frappe.whitelist()
def process_firs_queue():
	"""Scheduled cron: process one pending queue item at a time."""
	frappe.flags.ignore_permission = True

	# Single concurrency: process exactly one item per cron run
	pending = FIRSQueue.get_next_pending()
	if pending:
		queue_name = pending[0].name
		frappe.enqueue(
			method="theoskaris_einvoice.queue.processor.process_queue_item",
			queue="short",
			job_name=f"firs-process-{queue_name}",
			queue_name=queue_name,
		)


@frappe.whitelist()
def enqueue_invoice(doc_type: str, doc_name: str) -> str:
	"""Manually enqueue a document into the FIRS Queue."""
	if frappe.db.exists("FIRS Queue", {"document_type": doc_type, "document_name": doc_name, "status": ["in", ["Pending", "Processing"]]}):
		return None

	queue = frappe.new_doc("FIRS Queue")
	queue.document_type = doc_type
	queue.document_name = doc_name
	queue.status = "Pending"
	queue.retry_count = 0
	queue.max_retries = 5
	queue.insert(ignore_permissions=True)
	frappe.db.commit()
	return queue.name
