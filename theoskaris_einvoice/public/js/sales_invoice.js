// Sales Invoice client script for FIRS e-Invoicing.

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		toggle_firs_tab(frm);
	},

	is_return(frm) {
		toggle_firs_tab(frm);
	},
});

function toggle_firs_tab(frm) {
	// Show the FIRS tab only for returns (original invoices carry the
	// custom_submit_to_nrs flag removed 2026-07; returns set is_return).
	const show = cint(frm.doc.is_return);
	frm.toggle_display("custom_firs_tab", show);
	if (frm.doc.custom_nrs_irn) {
		frm.set_df_property("custom_nrs_irn", "read_only", 1);
	}
}
