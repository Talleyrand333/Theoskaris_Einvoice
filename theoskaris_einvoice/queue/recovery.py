"""Recover stuck FIRS Queue items."""

import frappe


@frappe.whitelist()
def recover_stuck_items():
	"""Reset items stuck in Processing for > 30 minutes back to Pending."""
	threshold = frappe.utils.add_to_date(frappe.utils.now(), minutes=-30)
	stuck = frappe.db.get_all(
		"FIRS Queue",
		filters={
			"status": "Processing",
			"submitted_at": ["<", threshold],
		},
		pluck="name",
	)
	for name in stuck:
		queue = frappe.get_doc("FIRS Queue", name)
		queue.status = "Pending"
		queue.save(ignore_permissions=True)

	if stuck:
		frappe.db.commit()
