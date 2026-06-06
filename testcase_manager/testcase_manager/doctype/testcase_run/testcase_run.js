frappe.ui.form.on("Testcase Run", {
	refresh(frm) {
		_update_indicator(frm);
		if (frm.is_new()) return;

		// ── Re-run ─────────────────────────────────────────────────────────
		frm.add_custom_button(__("Re-Run"), () => {
			frappe.call({
				method: "testcase_manager.testcase_manager.api.rerun_test",
				args: { run_name: frm.doc.name },
				freeze: true,
				freeze_message: __("Queuing re-run…"),
				callback(r) {
					if (r.message) {
						frappe.show_alert({ message: __("Re-queued"), indicator: "blue" });
						frappe.set_route("Form", "Testcase Run", r.message.run_name);
					}
				},
			});
		});

		// ── Open Log ───────────────────────────────────────────────────────
		frm.add_custom_button(__("View Log"), () => {
			frappe.call({
				method: "testcase_manager.testcase_manager.api.get_log_for_run",
				args: { run_name: frm.doc.name },
				callback(r) {
					r.message?.log_name
						? frappe.set_route("Form", "Testcase Log", r.message.log_name)
						: frappe.msgprint(__("No log found yet."));
				},
			});
		});

		// Live console while the job is running; saved output (Code fields)
		// renders raw, correctly-formatted text on its own.
		if (["Running", "Pending"].includes(frm.doc.status)) {
			_attach_live_console(frm);
		}
	},
});

// ── Indicator colour ──────────────────────────────────────────────────────

function _update_indicator(frm) {
	const map = { Pending: "orange", Running: "blue", Passed: "green", Failed: "red", Error: "red" };
	frm.set_indicator(__(frm.doc.status), map[frm.doc.status] || "grey");
}

// ── Live console (while the job is Running/Pending) ───────────────────────

function _attach_live_console(frm) {
	const task_id = frm.doc.name;
	frappe.realtime.task_subscribe(task_id);

	const $saved = frm.get_field("full_output").$wrapper;
	if ($saved.find(".tc-live-console").length) return;

	const $live = $(`
		<div class="tc-live-console" style="
			font-family:'Courier New',Courier,monospace;font-size:12px;
			background:#1e1e1e;color:#d4d4d4;padding:14px 16px;border-radius:4px;
			max-height:480px;overflow-y:auto;white-space:pre-wrap;
			word-break:break-all;line-height:1.55;margin-top:6px;
		"><div class="tc-live-output"></div></div>
	`).prependTo($saved);

	const $out = $live.find(".tc-live-output");

	frappe.realtime.on("test_output", (data) => {
		if (data.run_name !== task_id) return;
		$out.append(`<div>${_colour_line(frappe.utils.escape_html(_stripAnsi(data.line)))}</div>`);
		$live[0].scrollTop = $live[0].scrollHeight;
	});

	frappe.realtime.on("test_completed", (data) => {
		if (data.run_name !== task_id) return;
		frappe.realtime.task_unsubscribe(task_id);
		frm.reload_doc();
	});
}

function _colour_line(safe) {
	if (/✔|PASS\b|^OK\b/.test(safe)) return `<span style="color:#4ec9b0">${safe}</span>`;
	if (/✖|^FAIL\b|^ERROR\b/.test(safe)) return `<span style="color:#f48771">${safe}</span>`;
	if (/^Traceback|^\s+File "/.test(safe)) return `<span style="color:#ce9178">${safe}</span>`;
	if (/^Running \d|^Ran \d/.test(safe)) return `<span style="color:#569cd6">${safe}</span>`;
	if (/^={3,}$|^-{3,}$/.test(safe)) return `<span style="color:#555">${safe}</span>`;
	return `<span style="color:#d4d4d4">${safe}</span>`;
}

function _stripAnsi(str) {
	// eslint-disable-next-line no-control-regex
	return (str || "").replace(/\x1b\[[0-9;]*[A-Za-z]/g, "");
}
