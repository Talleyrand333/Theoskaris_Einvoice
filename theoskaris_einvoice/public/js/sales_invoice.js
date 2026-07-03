"""Sales Invoice client script for FIRS e-Invoicing."""

frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		toggle_firs_tab(frm);
	},

	custom_submit_to_nrs(frm) {
		toggle_firs_tab(frm);
	},

	is_return(frm) {
		toggle_firs_tab(frm);
	},
});

function toggle_firs_tab(frm) {
	const show = frm.doc.custom_submit_to_nrs || cint(frm.doc.is_return);
	// Tab/section name must match the custom field section break label
	frm.toggle_display("custom_firs_tab", show);
	if (frm.doc.custom_nrs_irn) {
		frm.set_df_property("custom_submit_to_nrs", "read_only", 1);
	}
}
