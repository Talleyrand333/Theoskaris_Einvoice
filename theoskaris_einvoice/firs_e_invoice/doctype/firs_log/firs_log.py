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
):
	"""Create a FIRS Log entry for an API call."""
	doc = frappe.new_doc("FIRS Log")
	doc.document_type = document_type
	doc.document_name = document_name
	doc.request_payload = request_payload
	doc.response_data = response_data
	doc.status = status
	doc.response_status_code = response_status_code
	doc.retry_attempt = retry_attempt
	doc.irn = irn
	doc.processing_time = processing_time
	doc.api_version = api_version
	doc.error_message = error_message
	doc.insert(ignore_permissions=True)
	frappe.db.commit()
	return doc.name
