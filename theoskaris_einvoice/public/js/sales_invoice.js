// Sales Invoice client script for FIRS e-Invoicing.

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		toggle_firs_tab(frm);
		add_payment_update_button(frm);
	},

	is_return(frm) {
		toggle_firs_tab(frm);
	},
});

function toggle_firs_tab(frm) {
	const show = cint(frm.doc.is_return);
	frm.toggle_display("custom_firs_tab", show);
	if (frm.doc.custom_nrs_irn) {
		frm.set_df_property("custom_nrs_irn", "read_only", 1);
	}
}

function add_payment_update_button(frm) {
	if (frm.doc.docstatus !== 1 || !frm.doc.custom_nrs_irn || frm.doc.is_return) {
		return;
	}

	frm.add_custom_button(
		__("Update NRS Payment"),
		() => {
			const paid = flt(frm.doc.grand_total) - flt(frm.doc.outstanding_amount);
			const d = new frappe.ui.Dialog({
				title: __("Update NRS Payment Status"),
				fields: [
					{
						fieldtype: "HTML",
						fieldname: "info",
						options:
							'<p class="text-muted small">' +
							__(
								"NRS does not accept PARTIAL at registration, so partially paid invoices are registered as PENDING and updated here."
							) +
							"</p>",
					},
					{
						fieldname: "status",
						fieldtype: "Select",
						label: __("Status"),
						options: ["PARTIAL", "PAID"],
						default: flt(frm.doc.outstanding_amount) > 0 ? "PARTIAL" : "PAID",
						reqd: 1,
					},
					{
						fieldname: "amount",
						fieldtype: "Currency",
						label: __("Amount Paid"),
						default: paid,
						depends_on: "eval:doc.status=='PARTIAL'",
						mandatory_depends_on: "eval:doc.status=='PARTIAL'",
					},
					{
						fieldname: "reference",
						fieldtype: "Data",
						label: __("Payment Reference"),
						default: frm.doc.name,
					},
				],
				primary_action_label: __("Push to NRS"),
				primary_action(values) {
					frappe.call({
						method:
							"theoskaris_einvoice.api.payment_status.push_payment_status",
						args: {
							invoice: frm.doc.name,
							status: values.status,
							amount: values.amount,
							reference: values.reference,
						},
						freeze: true,
						freeze_message: __("Updating NRS..."),
						callback: (r) => {
							if (!r.exc) {
								d.hide();
								frm.reload_doc();
								frappe.show_alert({
									message: __("NRS payment status updated to {0}", [
										values.status,
									]),
									indicator: "green",
								});
							}
						},
					});
				},
			});
			d.show();
		},
		__("FIRS")
	);
}
