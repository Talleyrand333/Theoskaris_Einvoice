"""FIRS Queue controller."""

import frappe
from frappe.model.document import Document


class FIRSQueue(Document):
	def before_insert(self):
		if not self.created_at:
			self.created_at = frappe.utils.now()
		if not self.max_retries:
			self.max_retries = 5
		if not self.retry_count:
			self.retry_count = 0

	def mark_processing(self):
		self.status = "Processing"
		if not self.submitted_at:
			self.submitted_at = frappe.utils.now()
		self.save(ignore_permissions=True)
		frappe.db.commit()

	def mark_completed(self, response=None):
		self.status = "Completed"
		self.last_response = response or self.last_response
		self.save(ignore_permissions=True)
		frappe.db.commit()

	def mark_failed(self, error, increment_retry=True):
		self.status = "Failed"
		self.last_error = str(error)
		if increment_retry:
			self.retry_count += 1
			self.next_retry_at = self.calculate_next_retry()
		self.save(ignore_permissions=True)
		frappe.db.commit()

	def mark_pending(self):
		self.status = "Pending"
		self.save(ignore_permissions=True)
		frappe.db.commit()

	def calculate_next_retry(self):
		# Exponential backoff: 5min, 15min, 45min, 2h, 6h
		backoff_minutes = [5, 15, 45, 120, 360]
		idx = min(self.retry_count, len(backoff_minutes) - 1)
		return frappe.utils.add_to_date(frappe.utils.now(), minutes=backoff_minutes[idx])

	def retry(self):
		"""Reset a Failed queue item to Pending and enqueue immediate processing."""
		if self.status != "Failed":
			frappe.throw("Only Failed queue items can be retried.")
		self.status = "Pending"
		self.last_error = None
		self.save(ignore_permissions=True)
		frappe.db.commit()
		frappe.enqueue(
			method="theoskaris_einvoice.queue.processor.process_queue_item",
			queue="short",
			job_name=f"firs-retry-{self.name}",
			queue_name=self.name,
		)
		frappe.msgprint(
			f"Queue item {self.name} requeued for processing.",
			indicator="green",
		)

	@staticmethod
	def get_next_pending():
		"""Return the oldest pending queue item."""
		return frappe.db.get_all(
			"FIRS Queue",
			filters={"status": "Pending"},
			fields=["name"],
			order_by="created_at asc",
			limit=1,
		)


@frappe.whitelist()
def retry_queue_item(doc=None):
	"""Server action entry point for the Retry button on FIRS Queue."""
	if isinstance(doc, str):
		try:
			doc = frappe.parse_json(doc)
		except Exception:
			pass
	if isinstance(doc, dict):
		docname = doc.get("name")
	elif hasattr(doc, "name"):
		docname = doc.name
	else:
		docname = doc
	if not docname:
		frappe.throw("Document name is required.")
	queue = frappe.get_doc("FIRS Queue", docname)
	queue.retry()
