import base64, frappe

c = frappe.get_doc("Company", "ASHBARD ENERGY COMPANY LIMITED")
k = c.get("custom_firs_public_key") or ""
print("T_LEN", len(k))
print("T_HEAD", k[:70])
print("T_TAIL", k[-40:])
print("T_NEWLINES", k.count(chr(10)))
print("T_MODIFIED", c.modified)
print("T_CERT_HEAD", (c.get("custom_firs_certificate") or "")[:40])
