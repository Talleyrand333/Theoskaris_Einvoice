import base64, frappe
from theoskaris_einvoice.utils.qr_generator import _load_public_key, _normalize_certificate

given_body = "".join("""MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAtKqp6GRJ5a2IUv2fXABu
i27BqwWB0UoPw4YoyVUHrLwiZIOS594QvHUIytFNcBAakEvFRAw1nFjcWl5C8epA
zbHX6t/ykXwf5MWGycaX4xLMhpAGop77SY9Dx0u+Jv+q+sUKgT05GqMizWby2Es6
gk/lw7VNVFbvj4lNeSk75vXw5u41v1a7BgLlb04zMawxRHB9AKOQgrLuBew3QS4N
0cdmL1X+Qln9seNT0kFu42+MlZWZGtZ/oIEMZMhp+YMGLpVMskE+mfj7X+034vJB
Dw0JPoB0nMY4Mejj1pAGe2oBj1BA6AWwXTGu1xfrQe3abGup2oknGjnJ2gH8/nOv
qQIDAQAB""".split())

c = frappe.get_doc("Company", "ASHBARD ENERGY COMPANY LIMITED")
stored = (c.get("custom_firs_public_key") or "").strip()
stored_body = "".join(stored.replace(chr(92) + "n", " ").split())
stored_body = stored_body.replace("-----BEGINPUBLICKEY-----", "").replace("-----ENDPUBLICKEY-----", "")
print("T_BODY_MATCH", stored_body == given_body)
print("T_LEN_STORED", len(stored_body), "| given", len(given_body))
key = _load_public_key(stored)
print("T_LOADED", key.key_size)
print("T_CERT_EMPTY", not (c.get("custom_firs_certificate") or "").strip())
