import base64, frappe, json

given = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtKqp6GRJ5a2IUv2fXABu
i27BqwWB0UoPw4YoyVUHrLwiZIOS594QvHUIytFNcBAakEvFRAw1nFjcWl5C8epA
zbHX6t/ykXwf5MWGycaX4xLMhpAGop77SY9Dx0u+Jv+q+sUKgT05GqMizWby2Es6
gk/lw7VNVFbvj4lNeSk75vXw5u41v1a7BgLlb04zMawxRHB9AKOQgrLuBew3QS4N
0cdmL1X+Qln9seNT0kFu42+MlZWZGtZ/oIEMZMhp+YMGLpVMskE+mfj7X+034vJB
Dw0JPoB0nMY4Mejj1pAGe2oBj1BA6AWwXTGu1xfrQe3abGup2oknGjnJ2gH8/nOv
qQIDAQAB
-----END PUBLIC KEY-----
"""

c = frappe.get_doc("Company", "ASHBARD ENERGY COMPANY LIMITED")
stored = (c.get("custom_firs_public_key") or "").strip()
pem_norm = given.strip() + chr(10)
try:
    stored_pem = base64.b64decode(stored).decode()
except Exception as e:
    stored_pem = ''
print("T_STORED_LEN", len(stored), "| b64_ok", bool(stored_pem))
print("T_MATCH_B64", stored == base64.b64encode(pem_norm.encode()).decode())
print("T_MATCH_PEM", stored_pem.replace(chr(13), "") .strip() == pem_norm.strip())
print("T_STORED_PEM_HEAD", stored_pem[:60].replace(chr(10), " "))
print("T_GIVEN_HEAD", pem_norm[:60].replace(chr(10), " "))
print("T_CERT_LEN", len(c.get("custom_firs_certificate") or ""))
print("T_BIZID", c.get("custom_firs_business_id") or "")
print("T_SEGMENT", c.get("custom_firs_irn_segment") or "")
