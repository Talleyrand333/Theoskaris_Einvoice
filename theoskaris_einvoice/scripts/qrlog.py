import frappe
lg = frappe.get_doc("FIRS Log", "FIRS-LOG-2026-00051")
print("T_LOG_STATUS", lg.status)
for st in lg.stages:
    print("T_STAGE", st.stage, "|", st.status, "|", st.error_message or "", "| code", st.response_status_code)
