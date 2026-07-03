"""Desk icon configuration for Theoskaris Einvoice."""

from frappe import _


def get_data():
	return [
		{
			"module_name": "Theoskaris Einvoice",
			"category": "Modules",
			"label": _("Theoskaris Einvoice"),
			"color": "blue",
			"icon": "fa fa-file-invoice",
			"type": "module",
		}
	]
