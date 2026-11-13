import frappe, json, hmac, hashlib, base64, requests
from datetime import datetime, timezone

c = frappe.get_doc("Company", "RIGHT INSPECTION SERVICES NIGERIA LIMITED")
key = c.get_password("custom_firs_api_key") or ""
secret = c.get_password("custom_firs_api_signature") or ""
print("T_CRED", "key" if key else "missing", "|", "secret" if secret else "missing")

body = json.dumps({
    "invoice_number": "SINV-00584",
    "service_id": c.get("custom_firs_service_id") or "",
    "issuance_date": "20261111",
    "business_id": c.get("custom_firs_business_id") or "",
}, separators=(',', ':'))
ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
sig = base64.b64encode(hmac.new(secret.encode(), (body + ts).encode(), hashlib.sha256).digest()).decode()
hdrs = {"X-API-Key": key, "X-API-Signature": sig, "X-API-Timestamp": ts, "Content-Type": "application/json"}

for base in ("https://firseinvoicedemo.etranzactng.com", "https://eivc-k6z6d.ondigitalocean.app"):
    for path in ("/api/v3/si/generate-irn", "/api/v3/app/invoice/validate-irn"):
        try:
            r = requests.post(base + path, data=body, headers=hdrs, timeout=20)
            print("T_PROBE", base.split("//")[1][:28], path, "->", r.status_code, r.text[:120].replace(chr(10), " "))
        except Exception as e:
            print("T_PROBE", base, path, "ERR", str(e)[:80])
