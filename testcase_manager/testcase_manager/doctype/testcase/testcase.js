frappe.ui.form.on("Testcase", {
	refresh(frm) {
		if (frm.is_new()) return;

		frm.add_custom_button(
			__("Run Method"),
			() => {
				_run(frm, "Method");
			},
			__("Run")
		);

		frm.add_custom_button(
			__("Run Entire File"),
			() => {
				_run(frm, "File");
			},
			__("Run")
		);

		if (frm.doc.reference_type === "DocType" && frm.doc.reference_doctype) {
			frm.add_custom_button(
				__("Run All for DocType"),
				() => {
					_run(frm, "DocType");
				},
				__("Run")
			);
		}

		frm.add_custom_button(
			__("Run All for App"),
			() => {
				_run(frm, "App");
			},
			__("Run")
		);

		frm.add_custom_button(__("Sync This File"), () => {
			frappe.call({
				method: "testcase_manager.testcase_manager.api.sync_test_cases",
				args: { app: frm.doc.app },
				freeze: true,
				freeze_message: __("Syncing test cases…"),
				callback(r) {
					if (r.message) {
						const m = r.message;
						frappe.show_alert({
							message: __(
								"Sync complete — created: {0}, updated: {1}, deactivated: {2}",
								[m.created, m.updated, m.deactivated]
							),
							indicator: "green",
						});
						frm.reload_doc();
					}
				},
			});
		});
	},
});

function _run(frm, scope) {
	frappe.call({
		method: "testcase_manager.testcase_manager.api.run_test_case",
		args: { test_case: frm.doc.name, run_scope: scope },
		freeze: true,
		freeze_message: __("Queuing test run…"),
		callback(r) {
			if (r.message) {
				frappe.show_alert({ message: __("Test queued"), indicator: "blue" });
				frappe.set_route("Form", "Testcase Run", r.message.run_name);
			}
		},
	});
}
