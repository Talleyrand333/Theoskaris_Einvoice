import frappe, json, requests
from theoskaris_einvoice.api.client_base import get_firs_client

c = frappe.get_doc("Company", "RIGHT INSPECTION SERVICES NIGERIA LIMITED")
print("T_API_VERSION", c.get("custom_firs_api_version") or "(unset)")
print("T_BASE_URL", c.get("custom_firs_api_base_url") or "(unset)")
cli = get_firs_client(c.name)
print("T_CLIENT", type(cli).__name__, "| base", cli.base_url)
r = cli._request("POST", "/api/v1/invoice/irn/validate", payload={"business_id": c.get("custom_firs_business_id"), "invoice_reference": "SINV-00584", "irn": "SINV-00584-31A9D784-20261111"})
print("T_CRED_TEST", r.status_code, r.text[:160].replace(chr(10), " "))
