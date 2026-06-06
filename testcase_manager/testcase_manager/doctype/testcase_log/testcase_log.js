frappe.ui.form.on("Testcase Log", {
	refresh(frm) {
		if (frm.is_new()) return;

		const colour_map = { Passed: "green", Failed: "red", Error: "red" };
		frm.set_indicator(
			__(frm.doc.execution_status || "Unknown"),
			colour_map[frm.doc.execution_status] || "grey"
		);

		// ── Re-Run ─────────────────────────────────────────────────────────
		frm.add_custom_button(
			__("Re-Run Test"),
			() => {
				frappe.call({
					method: "testcase_manager.testcase_manager.api.rerun_test",
					args: { run_name: frm.doc.run_reference },
					freeze: true,
					freeze_message: __("Queuing test run…"),
					callback(r) {
						if (r.message) {
							frappe.show_alert({
								message: __("New run created"),
								indicator: "blue",
							});
							frappe.set_route("Form", "Testcase Run", r.message.run_name);
						}
					},
				});
			},
			__("Actions")
		);

		if (frm.doc.run_reference) {
			frm.add_custom_button(__("View Run"), () => {
				frappe.set_route("Form", "Testcase Run", frm.doc.run_reference);
			});
		}

		// full_output / traceback / errors are Code fields — they render raw,
		// correctly-formatted monospace text on their own (no custom rendering).
	},
});
