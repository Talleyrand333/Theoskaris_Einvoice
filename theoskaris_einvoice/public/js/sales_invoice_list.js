// Sales Invoice list view button for bulk FIRS submission.

frappe.listview_settings["Sales Invoice"] = {
	onload(listview) {
		listview.page.add_action_item(
			__("Submit to FIRS"),
			function () {
				const selected = listview.get_checked_items();
				if (!selected.length) {
					frappe.msgprint(__("Please select at least one invoice."));
					return;
				}

				frappe.confirm(
					__("Queue {0} invoice(s) for FIRS submission?", [selected.length]),
					() => {
						frappe.call({
							method: "theoskaris_einvoice.api.bulk_submit.submit_selected_to_firs",
							args: {
								docnames: selected.map((r) => r.name),
							},
							freeze: true,
							freeze_message: __("Queuing invoices for FIRS submission..."),
							callback(r) {
								if (r.message) {
									frappe.show_alert({
										message: __("Queued {0} invoice(s).", [r.message.queued]),
										indicator: "green",
									});
									listview.refresh();
								}
							},
						});
					}
				);
			}
		);
	},
};
