// Purchase Invoice client script for FIRS e-Invoicing.

frappe.ui.form.on("Purchase Invoice", {
	refresh(frm) {
		toggle_firs_fields(frm);
	},

	custom_submit_to_nrs(frm) {
		toggle_firs_fields(frm);
	},

	is_return(frm) {
		toggle_firs_fields(frm);
	},
});

function toggle_firs_fields(frm) {
	// Always show the section break and checkbox.
	// Hide status/IRN fields until Submit to NRS is checked.
	const show_status = frm.doc.custom_submit_to_nrs || cint(frm.doc.is_return);
	const fields = ["custom_nrs_status", "custom_nrs_irn", "custom_nrs_qr_code",
		"custom_nrs_qr_code_url", "custom_nrs_response", "custom_nrs_datetime"];
	fields.forEach(f => frm.toggle_display(f, show_status));
	if (frm.doc.custom_nrs_irn) {
		frm.set_df_property("custom_submit_to_nrs", "read_only", 1);
	}
}
