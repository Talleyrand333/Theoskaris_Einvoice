import frappe, json, hmac, hashlib, base64, requests
from datetime import datetime, timezone

c = frappe.get_doc("Company", "RIGHT INSPECTION SERVICES NIGERIA LIMITED")
key = c.get_password("custom_firs_api_key")
secret = c.get_password("custom_firs_api_signature")

payload = {
  "invoice_number": "INV285",
  "service_id": "94ND90NR",
  "issuance_date": "20250412",
  "business_id": "6f19a0f0-c8f3-4d2b-8a8b-1b2c45e89d0f",
  "certificate": "VmxRamMwR2E5NGRvQW9QQVdGYUdzMzJucVh4azhVYmhabnRhY0k9QmxBcWE=",
}
body = json.dumps(payload, separators=(',', ':'))
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
sig_b64 = base64.b64encode(hmac.new(secret.encode(), (body + ts).encode(), hashlib.sha256).digest()).decode()
sig_hex = hmac.new(secret.encode(), (body + ts).encode(), hashlib.sha256).hexdigest()

for label, sig in (("base64", sig_b64), ("hex", sig_hex)):
    hdrs = {"X-API-Key": key, "X-API-Signature": sig, "X-API-Timestamp": ts, "Content-Type": "application/json"}
    r = requests.post("https://firseinvoicedemo.etranzactng.com/api/v3/si/generate-qr-code", data=body, headers=hdrs, timeout=20)
    print("T_DEMO", label, "->", r.status_code, r.text[:140].replace(chr(10), " "))
