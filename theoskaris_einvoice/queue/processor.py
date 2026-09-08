"""Background queue worker that processes a single FIRS Queue item."""

import json
import time

import frappe

from theoskaris_einvoice.api.client_base import FIRSAPIError, get_firs_client
from theoskaris_einvoice.firs_e_invoice.doctype.firs_log.firs_log import log_request
from theoskaris_einvoice.payload.builder import build_payload

TRANSMIT_DENIED_STATUS_CODES = (401, 403)


def _transmit_enabled() -> bool:
	"""Read the transmit toggle from FIRS Settings (default: off)."""
	try:
		return bool(frappe.get_single("FIRS Settings").get("enable_transmit", 0))
	except frappe.DoesNotExistError:
		return False


def _make_stage(stage, status, ms=0, code="", error=""):
	return {
		"stage": stage,
		"status": status,
		"response_status_code": str(code) if code else "",
		"processing_time": ms,
		"error_message": error,
	}


def process_queue_item(queue_name: str):
	"""Process one FIRS Queue item end-to-end, logging one FIRS Log per run."""
	queue = frappe.get_doc("FIRS Queue", queue_name)
	queue.mark_processing()

	stages = []

	def log_run(status, response_data, error_message=None, irn=None, total_ms=0):
		return log_request(
			document_type=queue.document_type,
			document_name=queue.document_name,
			request_payload=payload_json,
			response_data=response_data,
			status=status,
			response_status_code="",
			retry_attempt=queue.retry_count,
			irn=irn,
			processing_time=total_ms,
			api_version="v1",
			error_message=error_message,
			queue_name=queue.name,
			stages=stages,
		)

	def safe_log_run(status, response_data, **kwargs):
		"""Log a run; never let a logging failure destroy the API response.

		On logging failure, persist the response directly on the queue row so
		the real API error is always visible.
		"""
		try:
			return log_run(status, response_data, **kwargs)
		except Exception:
			frappe.db.set_value(
				"FIRS Queue",
				queue.name,
				{
					"last_response": response_data,
					"last_error": kwargs.get("error_message") or "FIRS Log insert failed",
				},
				update_modified=False,
			)
			frappe.db.commit()
			frappe.log_error(title="FIRS Log Write Failed", message=frappe.get_traceback())

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
			validate_ms = round(time.time() * 1000 - start, 2)
			status = "Invalid" if e.status_code and e.status_code < 500 else "Error"
			stages.append(_make_stage("Validate", status, validate_ms, e.status_code, str(e)))
			safe_log_run(status, json.dumps(e.response_body, default=str) if e.response_body else str(e), error_message=str(e), total_ms=validate_ms)
			if client.is_retryable(e):
				queue.mark_failed(e)
			else:
				queue.mark_failed(e, increment_retry=False)
			_set_invoice_status(inv, "Error", error=str(e))
			return

		validate_ms = round(time.time() * 1000 - start, 2)
		stages.append(_make_stage("Validate", "Success", validate_ms))
		irn = _extract_irn(resp_validate) or payload.get("irn")

		# Step 2: sign the validated invoice
		start = time.time() * 1000
		try:
			resp_sign = client.sign_invoice(payload)
		except FIRSAPIError as e:
			sign_ms = round(time.time() * 1000 - start, 2)
			status = "Error" if e.status_code and e.status_code >= 500 else "Invalid"
			stages.append(_make_stage("Sign", status, sign_ms, e.status_code, str(e)))
			safe_log_run(status, json.dumps(e.response_body, default=str) if e.response_body else str(e), error_message=str(e), irn=irn, total_ms=validate_ms + sign_ms)
			if client.is_retryable(e):
				queue.mark_failed(e)
			else:
				queue.mark_failed(e, increment_retry=False)
			_set_invoice_status(inv, "Error", error=str(e))
			return

		sign_ms = round(time.time() * 1000 - start, 2)
		stages.append(_make_stage("Sign", "Success", sign_ms))

		# Step 3: transmit by IRN — only if enabled in FIRS Settings
		transmit_ms = 0
		resp_transmit = None
		if _transmit_enabled():
			start = time.time() * 1000
			try:
				resp_transmit = client.transmit_invoice(irn)
				transmit_ms = round(time.time() * 1000 - start, 2)
				stages.append(_make_stage("Transmit", "Success", transmit_ms))
			except FIRSAPIError as e:
				transmit_ms = round(time.time() * 1000 - start, 2)
				if e.status_code in TRANSMIT_DENIED_STATUS_CODES:
					# API key lacks transmit permission — record as Skipped, not Error
					stages.append(_make_stage("Transmit", "Skipped", transmit_ms, e.status_code, str(e)))
				else:
					stages.append(_make_stage("Transmit", "Error", transmit_ms, e.status_code, str(e)))
		else:
			stages.append(_make_stage("Transmit", "Skipped", 0, "", "Transmit disabled in FIRS Settings"))

		# Step 4: confirm the transmitted invoice
		start = time.time() * 1000
		try:
			resp_confirm = client.confirm_invoice(irn)
			confirm_ms = round(time.time() * 1000 - start, 2)
			stages.append(_make_stage("Confirm", "Success", confirm_ms))
		except FIRSAPIError as e:
			confirm_ms = round(time.time() * 1000 - start, 2)
			# Confirm is optional — log but don't fail
			stages.append(_make_stage("Confirm", "Error", confirm_ms, e.status_code, str(e)))
			resp_confirm = None

		# Persist IRN + response back to invoice
		# QR code: generated per NRS IRN Signing spec (RSA-encrypt irn+certificate,
		# render locally) — the API never returns a QR.
		qr_code = None
		qr_data_uri = None
		if irn:
			try:
				from theoskaris_einvoice.utils.qr_generator import generate_invoice_qr
				qr_code, qr_data_uri = generate_invoice_qr(inv, irn)
			except Exception as e:
				frappe.log_error(
					title="FIRS QR Generation Failed",
					message=f"IRN: {irn}, Error: {e}\n{frappe.get_traceback()}",
				)
		_response = {
			"validate_response": resp_validate,
			"sign_response": resp_sign,
			"transmit_response": resp_transmit,
			"confirm_response": resp_confirm,
		}
		_set_invoice_status(
			inv,
			status="Transmitted" if resp_transmit else "Signed",
			irn=irn,
			qr_code=qr_code,
			qr_data_uri=qr_data_uri,
			response=_response,
		)

		# One success log per run, with all stages in the child table
		total_ms = validate_ms + sign_ms + transmit_ms + confirm_ms
		safe_log_run("Success", json.dumps(_response, default=str), irn=irn, total_ms=total_ms)

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


def _set_invoice_status(inv, status, irn=None, qr_code=None, response=None, error=None, qr_data_uri=None):
	inv.db_set("custom_nrs_status", status)
	if irn:
		inv.db_set("custom_nrs_irn", irn)
	if qr_code:
		inv.db_set("custom_nrs_qr_code", qr_code)
	if qr_data_uri:
		inv.db_set("custom_nrs_qr_code_url", qr_data_uri)
	if response:
		inv.db_set("custom_nrs_response", json.dumps(response, default=str))
	if error:
		inv.db_set("custom_nrs_response", json.dumps({"error": error}, default=str))
	inv.db_set("custom_nrs_datetime", frappe.utils.now())
