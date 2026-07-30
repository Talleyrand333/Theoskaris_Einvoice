"""FIRS Invoice Upload controller.

Submittable doctype with a "Fetch Invoices" action that queries qualifying
Sales/Purchase Invoices in a date range and populates the child table.
On submit, each fetched invoice is individually queued to FIRS.
"""

from __future__ import annotations

import frappe
from frappe.model.document import Document


class FIRSInvoiceUpload(Document):
	# ------------------------------------------------------------------
	# Server Action: fetch_invoices
	# ------------------------------------------------------------------
	def fetch_invoices(self):
		"""Fetch qualifying invoices into the child table.

		Qualifying criteria:
		- docstatus = 1 (submitted)
		- posting_date within [start_date, end_date]
		- custom_firs_ready = 1
		- No existing FIRS Queue entry in Pending/Processing state
		"""
		if not self.start_date or not self.end_date:
			frappe.throw("Start Date and End Date are required before fetching invoices.")

		# Clear existing entries
		self.queue_entries = []

		settings = frappe.get_single("FIRS Settings")
		enabled_doctypes = []
		if settings.get("enable_sales_invoice"):
			enabled_doctypes.append("Sales Invoice")
		if settings.get("enable_purchase_invoice"):
			enabled_doctypes.append("Purchase Invoice")

		if not enabled_doctypes:
			frappe.throw(
				"No document type is enabled in FIRS Settings. "
				"Enable at least one before fetching invoices."
			)

		total = 0

		for doctype in enabled_doctypes:
			invoices = frappe.get_all(
				doctype,
				filters={
					"docstatus": 1,
					"posting_date": ["between", [self.start_date, self.end_date]],
					"custom_firs_ready": 1,
				},
				fields=["name", "posting_date", "custom_firs_ready", "custom_nrs_status"],
				order_by="posting_date asc, name asc",
			)

			for inv in invoices:
				# Skip if already has an active FIRS Queue entry
				existing_queue = frappe.db.exists(
					"FIRS Queue",
					{
						"document_type": doctype,
						"document_name": inv.name,
						"status": ["in", ["Pending", "Processing"]],
					},
				)
				if existing_queue:
					continue

				# Skip if already appears in another FIRS Invoice Upload record
				existing_upload = frappe.db.exists(
					"FIRS Upload Queue Reference",
					{"document_type": doctype, "document_name": inv.name},
				)
				if existing_upload:
					continue

				total += 1
				self.append(
					"queue_entries",
					{
						"document_type": doctype,
						"document_name": inv.name,
						"firs_ready": 1,
						"status": "Pending",
					},
				)

		self.total_invoices = total
		self.queued_entries = 0
		self.failed_invoices = 0
		self.status = "Fetched" if total > 0 else "Draft"
		self.save(ignore_permissions=True)

		frappe.msgprint(
			f"Found {total} qualifying invoice(s) ready for upload.",
			title="Fetch Complete",
			indicator="green" if total > 0 else "orange",
		)

	# ------------------------------------------------------------------
	# on_submit: queue each invoice and trigger immediate processing
	# ------------------------------------------------------------------
	def on_submit(self):
		"""Create a FIRS Queue entry for each invoice and trigger immediate processing.

		Each invoice gets exactly 1 FIRS Queue entry. After queueing, each item
		is immediately enqueued for background processing via frappe.enqueue.
		The scheduled cron job (every 5 min) handles retries for any failed items.
		Uses db_set to update child rows to avoid validate_update_after_submit errors.
		"""
		if not self.queue_entries:
			frappe.throw("No invoices to upload. Use 'Fetch Invoices' first.")

		self.db_set("status", "Processing")
		frappe.db.commit()

		queued = 0
		failed = 0
		queue_names = []

		for row in self.queue_entries:
			try:
				queue_name = self._create_queue_entry(row.document_type, row.document_name)
				if queue_name:
					# Use db_set to avoid UpdateAfterSubmitError
					frappe.db.set_value(
						"FIRS Upload Queue Reference",
						row.name,
						{"queue_name": queue_name, "status": "Pending"},
						update_modified=False,
					)
					queued += 1
					queue_names.append(queue_name)
				else:
					frappe.db.set_value(
						"FIRS Upload Queue Reference",
						row.name,
						{"status": "Failed"},
						update_modified=False,
					)
					failed += 1
			except Exception as e:
				frappe.db.set_value(
					"FIRS Upload Queue Reference",
					row.name,
					{"status": "Failed"},
					update_modified=False,
				)
				failed += 1
				frappe.log_error(
					title="FIRS Upload Queue Error",
					message=f"{row.document_type} {row.document_name}: {e}\n{frappe.get_traceback()}",
				)

		# Determine final status
		if failed == 0 and queued > 0:
			new_status = "Queued"
		elif queued > 0 and failed > 0:
			new_status = "Partial"
		elif queued == 0 and failed > 0:
			new_status = "Failed"
		else:
			new_status = "Draft"

		self.db_set("queued_entries", queued)
		self.db_set("failed_invoices", failed)
		self.db_set("status", new_status)
		frappe.db.commit()

		# Trigger immediate processing of each queued item
		for qname in queue_names:
			try:
				frappe.enqueue(
					method="theoskaris_einvoice.queue.processor.process_queue_item",
					queue="short",
					job_name=f"firs-process-{qname}",
					queue_name=qname,
				)
			except Exception as e:
				frappe.log_error(
					title="FIRS Immediate Processing Enqueue Error",
					message=f"Queue {qname}: {e}\n{frappe.get_traceback()}",
				)

	@staticmethod
	def _create_queue_entry(doc_type: str, doc_name: str) -> str | None:
		"""Create a single FIRS Queue entry if none exists for this invoice."""
		# Double-check no active queue exists
		if frappe.db.exists(
			"FIRS Queue",
			{
				"document_type": doc_type,
				"document_name": doc_name,
				"status": ["in", ["Pending", "Processing"]],
			},
		):
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


@frappe.whitelist()
def fetch_invoices(docname: str):
	"""Server method called by the 'Fetch Invoices' button."""
	doc = frappe.get_doc("FIRS Invoice Upload", docname)
	doc.fetch_invoices()
	return {"status": doc.status, "total": doc.total_invoices}