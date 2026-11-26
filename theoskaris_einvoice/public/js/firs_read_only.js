// Read-only presentation for the system-generated FIRS queue and log records.
// This is a UI lock only: DocPerms are untouched, and the queue processor keeps
// inserting/updating both doctypes with ignore_permissions.
// Existing form buttons (including Retry) are left in place.

const LAYOUT_FIELDTYPES = ["Section Break", "Column Break", "Tab Break", "HTML", "Button"];

function lock_fields(frm) {
	frm.fields.forEach((field) => {
		const df = field.df;
		if (!df || !df.fieldname || LAYOUT_FIELDTYPES.includes(df.fieldtype)) return;
		frm.set_df_property(df.fieldname, "read_only", 1);
	});

	frm.fields.forEach((field) => {
		const df = field.df;
		if (!df || df.fieldtype !== "Table" || !field.grid) return;

		const grid = field.grid;
		grid.cannot_add_rows = true;
		grid.df.cannot_add_rows = 1;
		grid.df.cannot_delete_rows = 1;
		grid.refresh();

		// Child rows are rendered from the grid's own copies of the docfields.
		(grid.docfields || []).forEach((child) => {
			child.read_only = 1;
		});
		(grid.grid_rows || []).forEach((row) => {
			(row.docfields || []).forEach((child) => {
				child.read_only = 1;
			});
		});
	});
}

["FIRS Queue", "FIRS Log"].forEach((doctype) => {
	frappe.ui.form.on(doctype, {
		refresh(frm) {
			lock_fields(frm);
		},
	});
});
