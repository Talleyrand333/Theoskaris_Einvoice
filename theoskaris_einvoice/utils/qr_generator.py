"""NRS MBS QR code generation per the official IRN Signing spec.

Flow (einvoice.nrs.gov.ng → System Integrators → QR Code):
1. RSA-encrypt {"irn": "<IRN>.<unix_ts>", "certificate": "<b64 cert>"}
   with the taxpayer's public key (from crypto_keys.txt download).
2. Base64-encode the ciphertext.
3. Render that base64 string as a QR code image (scannable by MBS360).

The encrypted base64 string is stored in custom_nrs_qr_code; a rendered
PNG data URI is stored in custom_nrs_qr_code_url for print formats.
"""

import base64
import json
import time

import frappe
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

# PKCS1v15 max plaintext for a 2048-bit key
_RSA_2048_MAX_PLAINTEXT = 245


def generate_qr_payload(irn: str, certificate: str, public_key_b64: str) -> str:
	"""RSA-encrypt {irn, certificate}, return base64 string for QR rendering.

	Args:
		irn: Invoice Reference Number (no timestamp suffix; added here)
		certificate: Base64 certificate string from crypto_keys.txt
		public_key_b64: Base64-encoded PEM public key from crypto_keys.txt

	Returns:
		Base64-encoded RSA-encrypted payload (the QR code content).
	"""
	if not public_key_b64:
		raise ValueError("FIRS public key not configured on Company")
	if not certificate:
		raise ValueError("FIRS certificate not configured on Company")

	pem_bytes = base64.b64decode(public_key_b64)
	public_key = load_pem_public_key(pem_bytes)

	timestamp = int(time.time())
	payload = json.dumps(
		{"irn": f"{irn}.{timestamp}", "certificate": certificate},
		separators=(",", ":"),
	).encode()

	if len(payload) > _RSA_2048_MAX_PLAINTEXT:
		raise ValueError(
			f"QR payload too large for RSA encryption ({len(payload)} > 245 bytes). "
			"Check the certificate value on the Company."
		)

	encrypted = public_key.encrypt(payload, padding.PKCS1v15())
	return base64.b64encode(encrypted).decode()


def generate_qr_data_uri(qr_payload: str) -> str:
	"""Render the encrypted payload as a PNG data URI (for print formats)."""
	# box_size 10 + border 4 gives a large, high-contrast QR that survives
	# print/PDF rendering and scans reliably from paper and screen.
	import io

	import qrcode

	qr = qrcode.QRCode(
		version=None,
		error_correction=qrcode.constants.ERROR_CORRECT_M,
		box_size=10,
		border=4,
	)
	qr.add_data(qr_payload)
	qr.make(fit=True)
	img = qr.make_image(fill_color="black", back_color="white")
	buf = io.BytesIO()
	img.save(buf, format="PNG")
	b64 = base64.b64encode(buf.getvalue()).decode()
	return f"data:image/png;base64,{b64}"


def generate_invoice_qr(inv, irn: str) -> tuple[str, str]:
	"""Generate QR payload + PNG data URI for an invoice's company config.

	Returns (qr_payload_base64, qr_png_data_uri).
	Raises ValueError if the Company crypto keys are not configured.
	"""
	company = frappe.get_doc("Company", inv.company)
	public_key_b64 = company.get("custom_firs_public_key") or ""
	certificate = company.get("custom_firs_certificate") or ""
	# Password fields need get_password; fall back to raw for Long Text
	try:
		if not public_key_b64:
			public_key_b64 = company.get_password("custom_firs_public_key") or ""
	except Exception:
		pass

	qr_payload = generate_qr_payload(irn, certificate, public_key_b64)
	return qr_payload, generate_qr_data_uri(qr_payload)


if __name__ == "__main__":
	# Self-check: encrypt + decrypt round-trip with a fresh test key
	from cryptography.hazmat.primitives.asymmetric import padding as _p
	from cryptography.hazmat.primitives.asymmetric import rsa
	from cryptography.hazmat.primitives.serialization import (
		Encoding,
		PublicFormat,
	)

	key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
	pem = key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
	pub_b64 = base64.b64encode(pem).decode()
	cert = base64.b64encode(b"test_cert").decode()

	result = generate_qr_payload("INV001-TEST0001-20240101", cert, pub_b64)
	assert result, "QR payload should not be empty"

	decrypted = key.decrypt(base64.b64decode(result), _p.PKCS1v15())
	payload = json.loads(decrypted)
	assert payload["irn"].startswith("INV001-TEST0001-20240101."), f"IRN mismatch: {payload['irn']}"
	assert payload["certificate"] == cert, "Certificate mismatch"
	uri = generate_qr_data_uri(result)
	assert uri.startswith("data:image/png;base64,")
	print("OK - generate_qr_payload self-check passed")