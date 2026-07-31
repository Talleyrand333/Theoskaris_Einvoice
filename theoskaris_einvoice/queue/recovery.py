"""Recover stuck FIRS Queue items and retry failed items."""

import frappe


@frappe.whitelist()
def recover_stuck_items():
	"""Reset items stuck in Processing for > 30 minutes back to Pending.

	Also retry Failed items whose next_retry_at has passed and retry_count
	is below max_retries.
	"""
	now = frappe.utils.now()

	# 1. Reset stuck Processing items (> 30 min) back to Pending
	threshold = frappe.utils.add_to_date(now, minutes=-30)
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

	# 2. Retry Failed items whose next_retry_at has passed and under max_retries
	failed_ready = frappe.db.get_all(
		"FIRS Queue",
		filters={
			"status": "Failed",
			"next_retry_at": ["<=", now],
			"retry_count": ["<", "max_retries"],
		},
		pluck="name",
	)
	for name in failed_ready:
		queue = frappe.get_doc("FIRS Queue", name)
		queue.status = "Pending"
		queue.save(ignore_permissions=True)

	if stuck or failed_ready:
		frappe.db.commit()
