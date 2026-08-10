"""FIRS Log controller."""

import frappe
from frappe.model.document import Document


class FIRSLog(Document):
	pass


def log_request(
	document_type,
	document_name,
	request_payload,
	response_data,
	status,
	response_status_code,
	retry_attempt=0,
	irn=None,
	processing_time=None,
	api_version="v2",
	error_message=None,
	queue_name=None,
	stages=None,
):
	"""Create a FIRS Log entry for a queue run.

	Args:
		document_type: DocType of the source document (e.g. "Sales Invoice")
		document_name: Name of the source document
		request_payload: JSON string of the request payload sent
		response_data: JSON string of the response (or error body)
		status: Overall run status — "Success" | "Invalid" | "Error"
		response_status_code: HTTP status of the run ("" if mixed stages)
		retry_attempt: Queue retry count at time of run
		irn: Invoice Reference Number if known
		processing_time: Total processing time in ms
		api_version: API version label
		error_message: Overall error message (fatal steps only)
		queue_name: Link to the FIRS Queue this run belongs to
		stages: Optional list of dicts, one per API stage:
			{"stage": "Validate|Sign|Transmit|Confirm", "status": "Success|Error|Skipped",
			 "response_status_code": str, "processing_time": float, "error_message": str}
	"""
	doc = frappe.new_doc("FIRS Log")
	doc.document_type = document_type
	doc.document_name = document_name
	doc.queue = queue_name
	doc.request_payload = request_payload
	doc.response_data = response_data
	doc.status = status
	doc.response_status_code = response_status_code
	doc.retry_attempt = retry_attempt
	doc.irn = irn
	doc.processing_time = processing_time
	doc.api_version = api_version
	doc.error_message = error_message

	for stage in stages or []:
		doc.append(
			"stages",
			{
				"stage": stage.get("stage"),
				"status": stage.get("status"),
				"response_status_code": stage.get("response_status_code") or "",
				"processing_time": stage.get("processing_time") or 0,
				"error_message": stage.get("error_message") or "",
			},
		)

	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name
