"""Base HTTP client for FIRS APP/SI providers."""

import json
from abc import ABC, abstractmethod
from typing import Optional

import frappe
import requests


class FIRSAPIError(Exception):
	"""Raised when the FIRS API returns a non-success response."""

	def __init__(self, message, status_code=None, response_body=None):
		super().__init__(message)
		self.status_code = status_code
		self.response_body = response_body


class BaseFIRSClient(ABC):
	"""Abstract base class for FIRS APP/SI clients."""

	def __init__(self, company_doc):
		self.company = company_doc
		self.base_url = self._get_base_url()
		self.verify_ssl = self.company.get("custom_firs_verify_ssl") != 0

	@abstractmethod
	def _get_base_url(self) -> str:
		"""Return the API base URL for this provider."""
		pass

	@abstractmethod
	def _get_auth_headers(self) -> dict:
		"""Return authentication headers for this provider."""
		pass

	def _request(self, method, endpoint, payload=None, timeout=60):
		url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
		headers = self._get_auth_headers()
		headers["Content-Type"] = "application/json"
		data = json.dumps(payload, default=str) if payload is not None else None
		resp = requests.request(
			method, url, data=data, headers=headers, timeout=timeout, verify=self.verify_ssl
		)
		return resp

	def _parse_response(self, resp):
		try:
			body = resp.json()
		except ValueError:
			body = resp.text
		return body

	def validate_invoice(self, payload: dict) -> dict:
		"""Validate + sign invoice via APP endpoint. Returns parsed response."""
		resp = self._request("POST", "/api/v1/invoice/validate", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS validation failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def sign_invoice(self, payload: dict) -> dict:
		"""Sign a validated invoice payload.

		Returns 201 with {"ok": True} on success.
		"""
		resp = self._request("POST", "/api/v1/invoice/sign", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS signing failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def transmit_invoice(self, irn: str) -> dict:
		"""Transmit an already signed/validated invoice by IRN.

		IRN is passed in the URL path, not the request body.
		"""
		resp = self._request("POST", f"/api/v1/invoice/transmit/{irn}", payload={})
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS transmit failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def confirm_invoice(self, irn: str) -> dict:
		"""Confirm/check a signed invoice by IRN.

		GET request per API docs.
		"""
		resp = self._request("GET", f"/api/v1/invoice/confirm/{irn}")
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS confirm failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def download_invoice(self, irn: str) -> dict:
		"""Download a transmitted invoice by IRN."""
		resp = self._request("GET", f"/api/v1/invoice/download/{irn}")
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS download failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def update_payment_status(self, irn: str, status: str, amount=None, reference=None) -> dict:
		"""Update payment status of a registered invoice: PATCH /api/v1/invoice/update/{irn}.

		Docs (v3, works on v1 host per live probe 2026-11-06):
		- {"payment_status": "PAID"} or {"payment_status": "REJECTED"}
		- {"payment_status": "PARTIAL", "amount": <number>, "reference": "<note>"}
		PAID/REJECTED are terminal — no further updates allowed.
		"""
		payload = {"payment_status": status}
		if status == "PARTIAL":
			if amount is None:
				raise FIRSAPIError("PARTIAL update requires amount")
			payload["amount"] = amount
			if reference:
				payload["reference"] = reference
		resp = self._request("PATCH", f"/api/v1/invoice/update/{irn}", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS payment status update failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def generate_irn(self, invoice_number: str, issuance_date: str) -> dict:
		"""Generate IRN via SI endpoint: POST /api/v3/si/generate-irn.

		Docs: developers.etranzactng.com → Generate IRN.
		Payload: {invoice_number, service_id, issuance_date, business_id}.
		"""
		payload = {
			"invoice_number": invoice_number,
			"service_id": self.company.get("custom_firs_service_id") or "",
			"issuance_date": issuance_date,
			"business_id": self.company.get("custom_firs_business_id") or "",
		}
		resp = self._request("POST", "/api/v3/si/generate-irn", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS IRN generation failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def generate_qr_code(
		self, invoice_number: str, issuance_date: str, certificate: str | None = None
	) -> dict:
		"""Generate QR code via SI endpoint: POST /api/v3/si/generate-qr-code.

		Docs: certificate is optional — when omitted the Seller/Supplier field
		prints "Test Business" (acceptable in sandbox/Test Mode).
		Returns data.qr_code_base64 (base64 PNG) per the API docs.
		"""
		payload = {
			"invoice_number": invoice_number,
			"service_id": self.company.get("custom_firs_service_id") or "",
			"issuance_date": issuance_date,
			"business_id": self.company.get("custom_firs_business_id") or "",
		}
		if certificate:
			payload["certificate"] = certificate
		resp = self._request("POST", "/api/v3/si/generate-qr-code", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS QR generation failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def verify_tin(self, tin: str) -> dict:
		"""Lookup a taxpayer by TIN."""
		resp = self._request("GET", f"/api/v1/invoice/transmit/lookup/tin/{tin}")
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS TIN lookup failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	@abstractmethod
	def is_retryable(self, error: FIRSAPIError) -> bool:
		"""Return True if the error should be retried."""
		pass


class EtranzactClient(BaseFIRSClient):
	"""eTranzact APP/SI provider implementation."""

	DEFAULT_BASE_URL = "https://eivc-k6z6d.ondigitalocean.app"

	def _get_base_url(self) -> str:
		url = self.company.get("custom_firs_api_base_url")
		if not url:
			url = self.DEFAULT_BASE_URL
		return url.rstrip("/")

	def _get_auth_headers(self) -> dict:
		from datetime import datetime, timezone

		timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
		return {
			"x-api-key": self.company.get_password("custom_firs_api_key") or "",
			"x-api-secret": self.company.get_password("custom_firs_api_signature") or "",
			"x-api-timestamp": timestamp,
		}

	def is_retryable(self, error: FIRSAPIError) -> bool:
		"""Retry on network/timeout/server errors and 5xx status codes."""
		if error.status_code is None:
			return True
		if error.status_code >= 500:
			return True
		# Do not retry client/validation errors
		return False


def get_firs_client(company_name: str) -> BaseFIRSClient:
	"""Factory: return the configured FIRS client for a company.

	Version selection via Company field custom_firs_api_version:
	- "v3" (or unset/unknown): eTranzact v3 APP client (HMAC-SHA256 auth,
	  /api/v3 endpoints, documented sandbox firseinvoicedemo.etranzactng.com)
	- "v1": legacy eTranzact v1 client (x-api-secret header, /api/v1 endpoints)
	"""
	company = frappe.get_doc("Company", company_name)
	version = (company.get("custom_firs_api_version") or "v3").strip().lower()
	if version == "v1":
		return EtranzactClient(company)
	from theoskaris_einvoice.api.client_v3 import EtranzactV3Client

	return EtranzactV3Client(company)
