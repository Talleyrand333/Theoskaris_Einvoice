app_name = "theoskaris_einvoice"
app_title = "Theoskaris Einvoice"
app_publisher = "Theoskaris"
app_description = "FIRS e-Invoicing integration for ERPNext via eTranzact"
app_email = "hello@theoskaris.com"
app_license = "mit"

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
app_include_js = "/assets/theoskaris_einvoice/js/theoskaris_einvoice.js"

# include js in doctype views
doctype_js = {
	"Sales Invoice": "public/js/sales_invoice.js",
}
doctype_list_js = {
	"Sales Invoice": "public/js/sales_invoice_list.js",
}

# Document Events
# ---------------
doc_events = {
	"Sales Invoice": {
		"validate": "theoskaris_einvoice.overrides.sales_invoice.validate",
		"before_submit": "theoskaris_einvoice.overrides.sales_invoice.before_submit",
		"on_submit": "theoskaris_einvoice.overrides.sales_invoice.on_submit",
		"before_cancel": "theoskaris_einvoice.overrides.sales_invoice.before_cancel",
		"on_cancel": "theoskaris_einvoice.overrides.sales_invoice.on_cancel",
	}
}

# Scheduled Tasks
# ---------------
scheduler_events = {
	"cron": {
		"*/5 * * * *": [
			"theoskaris_einvoice.queue.scheduler.process_firs_queue",
		],
		"*/30 * * * *": [
			"theoskaris_einvoice.queue.recovery.recover_stuck_items",
		],
	}
}

# Installation
# ------------
after_install = "theoskaris_einvoice.install.after_install"

# Fixtures (custom fields created during install/exported via fixtures)
# We create custom fields programmatically in install.py to avoid needing export/import.
# Reference data DocTypes are exported as fixtures.
fixtures = [
	"FIRS Tax Category",
	"FIRS Payment Means Code",
]
