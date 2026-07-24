// FIRS Invoice Upload — adds "Fetch Invoices" button to the form

frappe.ui.form.on("FIRS Invoice Upload", {
    refresh: function (frm) {
        if (frm.doc.docstatus === 0 && frm.doc.start_date && frm.doc.end_date) {
            frm.add_custom_button(
                __("Fetch Invoices"),
                function () {
                    frappe.call({
                        method:
                            "theoskaris_einvoice.firs_e_invoice.doctype.firs_invoice_upload.firs_invoice_upload.fetch_invoices",
                        args: { docname: frm.doc.name },
                        freeze: true,
                        freeze_message: __("Fetching qualifying invoices..."),
                        callback: function (r) {
                            if (r.message) {
                                frm.reload_doc();
                                frappe.msgprint({
                                    title: __("Fetch Complete"),
                                    message: __(
                                        "Found {0} qualifying invoice(s).",
                                        [r.message.total]
                                    ),
                                    indicator:
                                        r.message.total > 0 ? "green" : "orange",
                                });
                            }
                        },
                    });
                },
                __("Actions")
            );
        }
    },
});