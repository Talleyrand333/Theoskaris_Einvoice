"""Whitelisted endpoints: push an invoice's payment status to NRS.

NRS tracks a remaining balance per invoice. The amount on a PARTIAL update is
the instalment being reported now, not the cumulative amount paid, and an
instalment that clears the balance must be sent as PAID. We therefore track what
has already been reported (custom_nrs_paid_reported) and derive the instalment
from the invoice's own figures.
"""

import frappe
from frappe import _
from frappe.utils import flt

from theoskaris_einvoice.api.client_base import FIRSAPIError, get_firs_client

TOLERANCE = 0.009


def _state(inv):
	total = flt(inv.get("grand_total"))
	outstanding = flt(inv.get("outstanding_amount"))
	paid = total - outstanding
	reported = flt(inv.get("custom_nrs_paid_reported"))
	remaining_nrs = max(total - reported, 0.0)
	instalment = max(paid - reported, 0.0)
	return {
		"total": total,
		"erp_paid": paid,
		"outstanding": outstanding,
		"reported": reported,
		"remaining_nrs": remaining_nrs,
		"instalment": instalment,
	}


@frappe.whitelist()
def get_payment_state(invoice):
	"""Figures the Update NRS Payment dialog needs."""
	inv = frappe.get_doc("Sales Invoice", invoice)
	state = _state(inv)
	state["irn"] = inv.get("custom_nrs_irn")
	state["is_return"] = bool(inv.get("is_return"))
	return state


@frappe.whitelist()
def push_payment_status(invoice, status, amount=None, reference=None):
	inv = frappe.get_doc("Sales Invoice", invoice)
	if inv.docstatus != 1:
		frappe.throw(_("Submit the invoice before updating its NRS payment status."))

	irn = inv.get("custom_nrs_irn")
	if not irn:
		frappe.throw(_("Invoice {0} has no IRN. Push it to NRS first.").format(inv.name))

	status = (status or "").upper()
	if status not in ("PARTIAL", "PAID"):
		frappe.throw(_("Status must be PARTIAL or PAID."))

	state = _state(inv)
	remaining = state["remaining_nrs"]

	if remaining <= TOLERANCE:
		frappe.throw(
			_("NRS already holds the full amount for {0}; nothing left to report.").format(
				inv.name
			),
			title=_("Already Reported"),
		)

	if status == "PAID":
		if state["outstanding"] > TOLERANCE:
			frappe.throw(
				_(
					"Invoice {0} still has {1} outstanding in ERPNext. Record the "
					"payment first; NRS must not show PAID before the books do."
				).format(
					inv.name,
					frappe.format_value(state["outstanding"], {"fieldtype": "Currency"}),
				),
				title=_("Payment Not Recorded"),
			)
		amount = remaining
	else:
		if state["instalment"] <= TOLERANCE:
			frappe.throw(
				_(
					"No new payment is recorded against {0}. Record the receipt first, "
					"or use PAID if the balance is settled."
				).format(inv.name),
				title=_("Nothing New To Report"),
			)
		amount = flt(amount) or state["instalment"]
		if amount > state["instalment"] + TOLERANCE:
			frappe.throw(
				_(
					"Instalment {0} exceeds the {1} received since the last report "
					"against {2}."
				).format(
					frappe.format_value(amount, {"fieldtype": "Currency"}),
					frappe.format_value(state["instalment"], {"fieldtype": "Currency"}),
					inv.name,
				),
				title=_("Amount Exceeds Receipts"),
			)
		if amount >= remaining - TOLERANCE:
			frappe.throw(
				_("Instalment {0} clears the remaining NRS balance {1}. Use PAID.").format(
					frappe.format_value(amount, {"fieldtype": "Currency"}),
					frappe.format_value(remaining, {"fieldtype": "Currency"}),
				),
				title=_("Use PAID"),
			)

	client = get_firs_client(inv.company)
	try:
		response = client.update_payment_status(
			irn, status, amount=amount if status == "PARTIAL" else None, reference=reference
		)
	except FIRSAPIError as e:
		message = str(getattr(e, "response_body", None) or e)
		# NRS marks an invoice terminal once it considers the balance settled.
		# If the books agree, treat it as already reported instead of failing.
		if "terminal state" in message and state["outstanding"] <= TOLERANCE:
			frappe.db.set_value(
				"Sales Invoice",
				inv.name,
				"custom_nrs_paid_reported",
				state["total"],
				update_modified=False,
			)
			return {
				"irn": irn,
				"status": "PAID",
				"amount": remaining,
				"reported": state["total"],
				"already_terminal": True,
			}
		frappe.throw(
			_("NRS rejected the payment update: {0}").format(message),
			title=_("NRS Payment Update"),
		)

	reported = state["reported"] + (amount if status == "PARTIAL" else remaining)
	frappe.db.set_value(
		"Sales Invoice",
		inv.name,
		{
			"custom_nrs_paid_reported": reported,
			"custom_nrs_response": frappe.as_json(
				{
					"payment_status_update": {
						"status": status,
						"amount": amount,
						"reference": reference,
						"response": response,
					}
				}
			),
		},
		update_modified=False,
	)

	return {"irn": irn, "status": status, "amount": amount, "reported": reported}
