import re

import frappe
import requests

VERIFY_STAMP_URL = "https://api.firsmbs.com/api/v1/integration/verify_stamp"
IRN_RE = re.compile(r"^[A-Za-z0-9._-]+-[0-9A-Fa-f]{8}-[0-9]{8}$")


def _looks_like_payload(value):
	return len(value) > 180 and not IRN_RE.match(value)


def _device():
	return {
		"deviceId": "public-verify-page",
		"deviceName": "Public verification page",
		"modelName": "web",
	}


@frappe.whitelist(allow_guest=True)
def validate(value=None):
	"""Verify an IRN or a QR payload. Returns a display-ready result."""
	text = (value or "").strip()
	if not text:
		frappe.throw("Paste an IRN or QR payload.")
	if len(text) > 1000:
		frappe.throw("That value is too long to be an IRN or QR payload.")

	if _looks_like_payload(text):
		return _verify_payload(text)
	return _verify_irn(text)


def _verify_payload(code):
	try:
		payload = {"code": code}
		payload.update(_device())
		r = requests.post(VERIFY_STAMP_URL, json=payload, timeout=20)
	except Exception as exc:
		frappe.log_error(title="Public verify: stamp call failed", message=str(exc))
		return {
			"valid": False,
			"headline": "Could not reach the NRS verification service",
			"fields": {},
			"note": "Try again in a moment.",
		}

	if r.status_code != 200:
		try:
			body = r.json()
		except Exception:
			body = {}
		return {
			"valid": False,
			"headline": body.get("message") or "QR payload could not be verified",
			"fields": {},
			"note": "If you typed the payload by hand, check that it was copied in full.",
		}

	data = (r.json() or {}).get("data") or {}
	irn = data.get("irn") or ""
	fields = {"IRN": irn, "Issuer": data.get("issuer") or ""}
	fields.update(_local_invoice_fields(irn))
	return {
		"valid": bool(irn),
		"headline": "QR verified by NRS" if irn else "NRS returned no IRN",
		"fields": fields,
		"note": "Checked against the NRS portal stamp service.",
	}


def _verify_irn(irn):
	if not IRN_RE.match(irn):
		return {
			"valid": False,
			"headline": "That does not look like an IRN",
			"fields": {},
			"note": "Expected format is INVOICE-SEGMENT-YYYYMMDD. You can paste the full QR payload instead.",
		}

	rows = frappe.get_all(
		"Sales Invoice",
		filters={"custom_nrs_irn": irn},
		fields=["name", "company", "customer", "posting_date", "grand_total", "docstatus"],
		limit=1,
	)
	if not rows:
		return {
			"valid": False,
			"headline": "IRN not found in our records",
			"fields": {"IRN": irn},
			"note": "This IRN was not issued by us, or the invoice is not in this system.",
		}

	row = rows[0]
	fields = {
		"IRN": irn,
		"Invoice": row.get("name"),
		"Issuer": row.get("company"),
		"Customer": row.get("customer"),
		"Date": str(row.get("posting_date") or ""),
		"Amount": frappe.utils.fmt_money(row.get("grand_total"), currency="NGN"),
		"Status": "Cancelled" if row.get("docstatus") == 2 else "Issued",
	}

	ok, message = _registry_check(row.get("company"), irn)
	if ok is None:
		fields["Registry"] = "Not reachable"
	elif ok:
		fields["Registry"] = "Confirmed"
	else:
		fields["Registry"] = message

	return {
		"valid": bool(ok) if ok is not None else True,
		"headline": (
			"IRN confirmed by the NRS registry"
			if ok
			else ("Found in our records" if ok is None else "IRN rejected by the registry")
		),
		"fields": fields,
		"note": (
			"Verified against the registry using this company's credentials."
			if ok
			else "Paste the QR payload for a full stamp check if in doubt."
		),
	}


def _registry_check(company, irn):
	"""Ask the SI registry about the IRN. ok is None when unreachable."""
	if not company:
		return None, ""
	try:
		from theoskaris_einvoice.api.client_base import get_firs_client

		client = get_firs_client(company)
		company_doc = frappe.get_doc("Company", company)
		resp = client._request(
			"POST",
			"/api/v1/invoice/irn/validate",
			payload={
				"business_id": company_doc.get("custom_firs_business_id"),
				"invoice_reference": irn.split("-")[0],
				"irn": irn,
			},
		)
		if resp.status_code == 200:
			return True, ""
		return False, "HTTP %s" % resp.status_code
	except Exception as exc:
		frappe.log_error(title="Public verify: registry check failed", message=str(exc))
		return None, ""


def _local_invoice_fields(irn):
	if not irn:
		return {}
	row = frappe.db.get_value(
		"Sales Invoice",
		{"custom_nrs_irn": irn},
		["name", "posting_date", "grand_total", "docstatus"],
		as_dict=True,
	)
	if not row:
		return {}
	return {
		"Invoice": row.get("name"),
		"Date": str(row.get("posting_date") or ""),
		"Amount": frappe.utils.fmt_money(row.get("grand_total"), currency="NGN"),
	}

