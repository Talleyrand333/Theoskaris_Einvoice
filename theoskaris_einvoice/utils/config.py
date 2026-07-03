"""Per-company configuration helpers."""

import frappe


def get_firs_company_settings(company_name: str) -> dict:
	"""Return a dict with FIRS settings for a Company."""
	fields = [
		"custom_firs_enabled",
		"custom_firs_api_base_url",
		"custom_firs_report_base_url",
		"custom_firs_business_id",
		"custom_firs_service_id",
		"custom_firs_company_tin",
		"custom_firs_verify_ssl",
	]
	return frappe.db.get_value("Company", company_name, fields, as_dict=True) or {}
