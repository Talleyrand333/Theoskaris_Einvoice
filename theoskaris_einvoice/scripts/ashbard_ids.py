import frappe
c = frappe.get_doc("Company", "ASHBARD ENERGY COMPANY LIMITED")
sid = c.get("custom_firs_service_id") or ""
bid = c.get("custom_firs_business_id") or ""
seg = c.get("custom_firs_irn_segment") or ""
derived = (sid.split("-")[1] if sid.count("-") >= 1 else "") + (bid.split("-")[1] if bid.count("-") >= 1 else "")
print("T_SERVICE", sid)
print("T_BIZ", bid)
print("T_SEGMENT", seg)
print("T_DERIVED", derived.upper())
print("T_SEG_MATCH", derived.upper() == seg.upper())
