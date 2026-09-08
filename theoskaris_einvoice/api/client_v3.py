"""eTranzact NRS e-Invoicing API v3 client.

Implements the Access Point Provider (APP) endpoints per the official docs at
developers.etranzactng.com (NRS E-Invoicing Service):

- POST {base}/api/v3/app/invoice/validate       (Validate & Sign Invoice)
- POST {base}/api/v3/app/invoice/sign           (Sign Invoice)
- POST {base}/api/v3/app/invoice/validate-irn   (Validate IRN)
- POST {base}/api/v3/app/invoice/transmit       (Transmit Invoice, body {irn})
- GET  {base}/api/v3/app/invoice/confirm/{irn}  (Confirm Invoice)

Authentication (per docs: NRS E-Invoicing Service → Introduction → Authentication):
- X-API-Key: client API key
- X-API-Signature: HMAC-SHA256(request_body + timestamp, client_secret), base64
- X-API-Timestamp: ISO-20022 timestamp (UTC, e.g. 2025-11-17T12:50:05Z; ±5 min window)

Sandbox base URL: https://firseinvoicedemo.etranzactng.com

The v1 client (client_base.py EtranzactClient) is retained untouched for
fallback; this module is selected by Company field custom_firs_api_version
(default: v3 when configured, v1 otherwise).
"""

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone

import frappe
import requests

from theoskaris_einvoice.api.client_base import BaseFIRSClient, FIRSAPIError


class EtranzactV3Client(BaseFIRSClient):
	"""eTranzact APP v3 API client (HMAC-SHA256 auth)."""

	DEFAULT_BASE_URL = "https://firseinvoicedemo.etranzactng.com"

	def _get_base_url(self) -> str:
		url = self.company.get("custom_firs_api_base_url")
		if not url or "ondigitalocean" in (url or ""):
			# v1 sandbox host is not a v3 endpoint — use the documented v3 sandbox
			url = self.DEFAULT_BASE_URL
		return url.rstrip("/")

	def _get_auth_headers(self) -> dict:
		return {}  # v3 signs per-request in _request (body is part of signature)

	# -- signing helpers ---------------------------------------------------

	@staticmethod
	def _timestamp() -> str:
		# ISO-20022 UTC timestamp without milliseconds: 2025-11-17T12:50:05Z
		return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

	def _sign(self, body: str, timestamp: str) -> str:
		secret = self.company.get_password("custom_firs_api_signature") or ""
		message = (body + timestamp).encode()
		sig = hmac.new(secret.encode(), message, hashlib.sha256).digest()
		return base64.b64encode(sig).decode()

	# -- request plumbing ----------------------------------------------------

	def _request(self, method, endpoint, payload=None, timeout=60):
		url = f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}"
		body = json.dumps(payload, default=str) if payload is not None else ""
		timestamp = self._timestamp()
		headers = {
			"X-API-Key": self.company.get_password("custom_firs_api_key") or "",
			"X-API-Signature": self._sign(body, timestamp),
			"X-API-Timestamp": timestamp,
			"Content-Type": "application/json",
		}
		return requests.request(
			method, url, data=body if body else None, headers=headers,
			timeout=timeout, verify=self.verify_ssl,
		)

	def _parse_response(self, resp):
		try:
			return resp.json()
		except ValueError:
			return resp.text

	def _call(self, method, endpoint, payload=None, action="call"):
		"""Issue request; raise FIRSAPIError on non-2xx or API error status."""
		resp = self._request(method, endpoint, payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"eTranzact v3 {action} failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	# -- endpoint methods ----------------------------------------------------

	def validate_invoice(self, payload: dict) -> dict:
		"""Validate & Sign Invoice: POST /api/v3/app/invoice/validate."""
		return self._call("POST", "/api/v3/app/invoice/validate", payload, "validate")

	def sign_invoice(self, payload: dict) -> dict:
		"""Sign Invoice: POST /api/v3/app/invoice/sign."""
		return self._call("POST", "/api/v3/app/invoice/sign", payload, "sign")

	def validate_irn(self, irn: str, business_id: str, invoice_number: str = None) -> dict:
		"""Validate IRN: POST /api/v3/app/invoice/validate-irn."""
		payload = {"irn": irn, "business_id": business_id}
		if invoice_number:
			payload["invoice_number"] = invoice_number
		return self._call("POST", "/api/v3/app/invoice/validate-irn", payload, "validate-irn")

	def transmit_invoice(self, irn: str) -> dict:
		"""Transmit Invoice: POST /api/v3/app/invoice/transmit with body {irn}."""
		return self._call("POST", "/api/v3/app/invoice/transmit", {"irn": irn}, "transmit")

	def confirm_invoice(self, irn: str) -> dict:
		"""Confirm Invoice: GET /api/v3/app/invoice/confirm/{irn}."""
		return self._call("GET", f"/api/v3/app/invoice/confirm/{irn}", None, "confirm")

	def download_invoice(self, irn: str) -> dict:
		"""Download invoice (v1 had /api/v1/invoice/download/{irn}).

		v3 docs don't list a download endpoint; keep v1-style path on the v3
		host and surface a clean error if unsupported.
		"""
		return self._call("GET", f"/api/v3/app/invoice/download/{irn}", None, "download")

	def is_retryable(self, error: FIRSAPIError) -> bool:
		"""Retry on network/timeout/5xx; do not retry 4xx client errors."""
		if error.status_code is None:
			return True
		return error.status_code >= 500