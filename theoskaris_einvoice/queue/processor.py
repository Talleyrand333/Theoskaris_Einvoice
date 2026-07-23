"""Background queue worker that processes a single FIRS Queue item."""

import json
import time

import frappe

from theoskaris_einvoice.api.client_base import FIRSAPIError, get_firs_client
from theoskaris_einvoice.firs_e_invoice.doctype.firs_log.firs_log import log_request
from theoskaris_einvoice.payload.builder import build_payload


def process_queue_item(queue_name: str):
	"""Process one FIRS Queue item end-to-end."""
	queue = frappe.get_doc("FIRS Queue", queue_name)
	queue.mark_processing()

	try:
		inv = frappe.get_doc(queue.document_type, queue.document_name)
		client = get_firs_client(inv.company)

		payload = build_payload(inv)
		payload_json = json.dumps(payload, default=str)

		# Step 1: validate + sign via APP endpoint
		start = time.time() * 1000
		try:
			resp_validate = client.validate_invoice(payload)
		except FIRSAPIError as e:
			log_request(
				document_type=queue.document_type,
				document_name=queue.document_name,
				request_payload=payload_json,
				response_data=json.dumps(e.response_body, default=str) if e.response_body else str(e),
				status="Invalid" if e.status_code and e.status_code < 500 else "Error",
				response_status_code=str(e.status_code) if e.status_code else "",
				retry_attempt=queue.retry_count,
				processing_time=round(time.time() * 1000 - start, 2),
				api_version="v2",
				error_message=str(e),
			)
			if client.is_retryable(e):
				queue.mark_failed(e)
			else:
				queue.mark_failed(e, increment_retry=False)
			_set_invoice_status(inv, "Error", error=str(e))
			raise

		validate_ms = round(time.time() * 1000 - start, 2)
		irn = _extract_irn(resp_validate) or payload.get("irn")

		# Step 2: transmit by IRN
		start = time.time() * 1000
		try:
			resp_transmit = client.transmit_invoice(irn)
		except FIRSAPIError as e:
			log_request(
				document_type=queue.document_type,
				document_name=queue.document_name,
				request_payload=json.dumps({"irn": irn}),
				response_data=json.dumps(e.response_body, default=str) if e.response_body else str(e),
				status="Error",
				response_status_code=str(e.status_code) if e.status_code else "",
				retry_attempt=queue.retry_count,
				processing_time=round(time.time() * 1000 - start, 2),
				api_version="v2",
				error_message=str(e),
			)
			if client.is_retryable(e):
				queue.mark_failed(e)
			else:
				queue.mark_failed(e, increment_retry=False)
			_set_invoice_status(inv, "Error", error=str(e))
			raise

		transmit_ms = round(time.time() * 1000 - start, 2)

		# Persist IRN + response back to invoice
		qr_code = _extract_qr_code(resp_validate) or _extract_qr_code(resp_transmit)
		_response = {
			"validate_response": resp_validate,
			"transmit_response": resp_transmit,
		}
		_set_invoice_status(
			inv,
			status="Transmitted",
			irn=irn,
			qr_code=qr_code,
			response=_response,
		)

		# Log success
		log_request(
			document_type=queue.document_type,
			document_name=queue.document_name,
			request_payload=payload_json,
			response_data=json.dumps(_response, default=str),
			status="Success",
			response_status_code="200",
			retry_attempt=queue.retry_count,
			irn=irn,
			processing_time=validate_ms + transmit_ms,
			api_version="v2",
		)

		queue.mark_completed(response=json.dumps(_response, default=str))

	except Exception as e:
		# Ensure queue is failed if any unhandled error occurs
		if queue.status == "Processing":
			queue.mark_failed(e)
		frappe.log_error(title="FIRS Queue Processing Error", message=frappe.get_traceback())


def _extract_irn(response) -> str | None:
	if not response:
		return None
	for key in ("irn", "IRN", "invoice_reference_number", "data"):
		val = response.get(key)
		if val and isinstance(val, str):
			return val
		if val and isinstance(val, dict):
			return val.get("irn") or val.get("IRN")
	return None


def _extract_qr_code(response) -> str | None:
	if not response:
		return None
	for key in ("qr_code", "qrCode", "qr", "data"):
		val = response.get(key)
		if val and isinstance(val, str):
			return val
		if val and isinstance(val, dict):
			return val.get("qr_code") or val.get("qrCode")
	return None


def _set_invoice_status(inv, status, irn=None, qr_code=None, response=None, error=None):
	inv.db_set("custom_nrs_status", status)
	if irn:
		inv.db_set("custom_nrs_irn", irn)
	if qr_code:
		inv.db_set("custom_nrs_qr_code", qr_code)
	if response:
		inv.db_set("custom_nrs_response", json.dumps(response, default=str))
	if error:
		inv.db_set("custom_nrs_response", json.dumps({"error": error}, default=str))
	inv.db_set("custom_nrs_datetime", frappe.utils.now())
