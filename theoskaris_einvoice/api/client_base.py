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
		data = json.dumps(payload) if payload is not None else None
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
		resp = self._request("POST", "/api/v2/app/invoice/validate", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS validation failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def transmit_invoice(self, irn: str) -> dict:
		"""Transmit an already signed/validated invoice by IRN."""
		payload = {"irn": irn}
		resp = self._request("POST", "/api/v2/app/invoice/transmit", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS transmit failed: {body}",
				status_code=resp.status_code,
				response_body=body,
			)
		return body

	def verify_tin(self, tin: str) -> dict:
		"""Verify a taxpayer identification number."""
		payload = {"tin": tin}
		resp = self._request("POST", "/api/v2/resource/verify-tin", payload=payload)
		body = self._parse_response(resp)
		if not resp.ok:
			raise FIRSAPIError(
				f"FIRS TIN verification failed: {body}",
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
			"x-api-signature": self.company.get_password("custom_firs_api_signature") or "",
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
	"""Factory: return the configured FIRS client for a company."""
	company = frappe.get_doc("Company", company_name)
	# Currently only eTranzact is supported.
	return EtranzactClient(company)
