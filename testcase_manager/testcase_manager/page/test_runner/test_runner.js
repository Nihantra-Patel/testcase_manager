frappe.pages["test-runner"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: "Testcase Runner",
		single_column: true,
	});
	new TestRunnerPage(page, wrapper);
};

const TC_FILTER_KEY = "testcase_runner_filters_v1";

// ─────────────────────────────────────────────────────────────────────────────
// Main controller
// ─────────────────────────────────────────────────────────────────────────────

class TestRunnerPage {
	constructor(page, wrapper) {
		this.page = page;
		this.wrapper = wrapper;
		this.records = [];
		this.current_run = null;
		this._run_queue = [];
		this._queue_total = 0;
		this._pending_next = null;

		page.set_primary_action(__("Run Selected"), () => this._run_selected(), "play");
		page.add_menu_item(__("Sync All Tests"), () => this._sync_all());
		page.add_menu_item(__("Clear Console"), () => this._clear_console());

		this._build_layout();
		this._setup_realtime();
		this._restore_filters(); // load saved filter values
		this._load_apps(); // populates app dropdown + first query
	}

	// ── Layout ────────────────────────────────────────────────────────────

	_build_layout() {
		const $body = $(this.wrapper).find(".page-content");
		$body.empty().css({ padding: "0", overflow: "hidden", margin: "0" });

		this.$layout = $(`
			<div class="tc-root" style="display:flex;flex-direction:column;overflow:hidden;">

				<!-- ─── Filter bar ─── -->
				<div class="tc-filters" style="
					display:flex;flex-wrap:wrap;align-items:flex-end;gap:10px;
					padding:10px 16px;border-bottom:1px solid var(--border-color);
					background:var(--card-bg);flex-shrink:0;
				">
					<div class="tc-fg">
						<div class="tc-flabel">App</div>
						<select class="form-control form-control-sm tc-f-app" style="min-width:140px;"></select>
					</div>
					<div class="tc-fg">
						<div class="tc-flabel">Type</div>
						<select class="form-control form-control-sm tc-f-type" style="min-width:110px;">
							<option value="">All Types</option>
							<option value="DocType">DocType</option>
							<option value="Report">Report</option>
						</select>
					</div>
					<div class="tc-fg">
						<div class="tc-flabel tc-ref-label">DocType / Report</div>
						<div class="tc-ref-wrap" style="min-width:220px;"></div>
					</div>
					<div class="tc-fg">
						<div class="tc-flabel">Search Method</div>
						<input type="text" class="form-control form-control-sm tc-f-search"
							placeholder="test_method_name…" style="min-width:180px;">
					</div>

					<div style="margin-left:auto;display:flex;gap:6px;align-items:flex-end;">
						<span class="tc-count text-muted" style="font-size:12px;align-self:center;"></span>
						<button class="btn btn-sm btn-default tc-runapp-btn" style="display:none;" title="Run every test in this app">
							&#x25B6;&nbsp;Run Entire App
						</button>
						<button class="btn btn-sm btn-default tc-reset-btn" title="Clear all filters">
							&#x2715;&nbsp;Clear Filter
						</button>
						<button class="btn btn-sm btn-default tc-sync-btn" title="Re-discover test cases">
							&#x21BB;&nbsp;Sync
						</button>
					</div>
				</div>

				<!-- ─── Two-column body ─── -->
				<div style="display:flex;flex:1;overflow:hidden;">
					<div style="flex:0 0 40%;max-width:40%;display:flex;flex-direction:column;border-right:1px solid var(--border-color);">
						<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 12px;border-bottom:1px solid var(--border-color);background:var(--subtle-bg);flex-shrink:0;">
							<span style="font-size:11px;font-weight:700;color:var(--text-muted);text-transform:uppercase;letter-spacing:.5px;">Tests</span>
							<label style="font-size:12px;cursor:pointer;user-select:none;margin:0;display:flex;align-items:center;gap:4px;">
								<input type="checkbox" class="tc-select-all"> Select all
							</label>
						</div>
						<div class="tc-list" style="flex:1;overflow-y:auto;"></div>
					</div>

					<div style="flex:0 0 60%;max-width:60%;display:flex;flex-direction:column;min-width:0;">
						<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 12px;border-bottom:1px solid var(--border-color);background:var(--subtle-bg);flex-shrink:0;">
							<span class="tc-run-label" style="font-weight:600;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:400px;">Console</span>
							<div style="display:flex;gap:6px;align-items:center;flex-shrink:0;">
								<span class="tc-status-badge" style="display:none;padding:2px 10px;border-radius:10px;font-size:11px;font-weight:700;color:#fff;"></span>
								<button class="btn btn-xs btn-danger tc-stop-btn" style="display:none;">&#x25A0;&nbsp;Stop</button>
								<button class="btn btn-xs btn-default tc-copy-btn">&#x1F4CB;&nbsp;Copy</button>
								<button class="btn btn-xs btn-default tc-clear-btn">Clear</button>
							</div>
						</div>
						<div class="tc-console" style="flex:1;font-family:'SFMono-Regular',Menlo,Consolas,'Courier New',monospace;font-size:12px;background:#0d1117;color:#e6edf3;padding:14px 16px;overflow-y:auto;white-space:pre-wrap;word-break:break-all;line-height:1.65;"></div>
						<div class="tc-summary" style="display:none;padding:8px 14px;font-size:13px;font-weight:700;flex-shrink:0;"></div>
						<div class="tc-log-link-row" style="display:none;padding:4px 14px 8px;flex-shrink:0;">
							<a class="tc-log-link" href="#" style="font-size:12px;color:var(--primary);text-decoration:none;">Open full log &#x2192;</a>
						</div>
					</div>
				</div>
			</div>
		`).appendTo($body);

		// Size the layout to exactly fill from its real top to the viewport bottom
		// (no magic constant), so there is never a blank strip beneath the console.
		this._fit_height();
		// Recalc on next frame too — the header/breadcrumbs may not have settled
		// their final height on the first synchronous measurement.
		setTimeout(() => this._fit_height(), 0);
		setTimeout(() => this._fit_height(), 200);
		$(window)
			.off("resize.tcrunner")
			.on("resize.tcrunner", () => this._fit_height());

		this.$layout.find(".tc-flabel").css({
			fontSize: "11px",
			fontWeight: "700",
			color: "var(--text-muted)",
			textTransform: "uppercase",
			letterSpacing: ".5px",
			marginBottom: "3px",
		});

		this.$f_app = this.$layout.find(".tc-f-app");
		this.$f_type = this.$layout.find(".tc-f-type");
		this.$f_search = this.$layout.find(".tc-f-search");
		this.$ref_label = this.$layout.find(".tc-ref-label");
		this.$list = this.$layout.find(".tc-list");
		this.$console = this.$layout.find(".tc-console");
		this.$count = this.$layout.find(".tc-count");
		this.$summary = this.$layout.find(".tc-summary");
		this.$run_label = this.$layout.find(".tc-run-label");
		this.$status_badge = this.$layout.find(".tc-status-badge");
		this.$log_link_row = this.$layout.find(".tc-log-link-row");
		this.$log_link = this.$layout.find(".tc-log-link");
		this.$runapp_btn = this.$layout.find(".tc-runapp-btn");
		this.$stop_btn = this.$layout.find(".tc-stop-btn");
		this.$stop_btn.on("click", () => this._stop());

		// DocType/Report picker — real Link control (search dropdown, app-scoped)
		this._init_ref_control(this.$layout.find(".tc-ref-wrap"));

		// Filter events
		this.$f_app.on("change", () => {
			this._save_filters();
			this._refresh_ref_control().then(() => this._query_server());
			this._toggle_runapp_btn();
		});
		this.$f_type.on("change", () => {
			this._save_filters();
			this._update_ref_label();
			this._refresh_ref_control().then(() => this._query_server());
		});
		this.$f_search.on("input", () => {
			this._save_filters();
			this._query_server();
		});

		// Buttons
		this.$layout.find(".tc-select-all").on("change", (e) => {
			this.$list.find(".tc-row-check").prop("checked", e.target.checked);
		});
		this.$layout.find(".tc-copy-btn").on("click", () => this._copy_console());
		this.$layout.find(".tc-clear-btn").on("click", () => this._clear_console());
		this.$layout.find(".tc-sync-btn").on("click", () => this._sync_all());
		this.$layout.find(".tc-reset-btn").on("click", () => this._reset_filters());
		this.$runapp_btn.on("click", () => this._run_entire_app());
	}

	// Fill exactly from the layout's top edge to the bottom of the window.
	_fit_height() {
		if (!this.$layout || !this.$layout.length) return;
		const top = this.$layout[0].getBoundingClientRect().top;
		this.$layout.css("height", `${Math.max(window.innerHeight - top, 300)}px`);
	}

	// ── DocType/Report Link control (real Link field, app-scoped) ─────────

	_init_ref_control($container) {
		const self = this;
		// A genuine Link control → native search dropdown over the DocType /
		// Report master (same UX as the Testcase form). get_query() scopes the
		// results to the modules of the currently-selected app.
		this.ref_ctrl = frappe.ui.form.make_control({
			df: {
				fieldtype: "Link",
				fieldname: "tc_ref",
				options: "DocType",
				placeholder: __("All DocTypes"),
				get_query() {
					const modules = self._app_modules || [];
					return modules.length ? { filters: { module: ["in", modules] } } : {};
				},
				change: () => {
					// Suppress while we programmatically clear/restore the value,
					// otherwise the restore would be overwritten with an empty ref.
					if (this._suppress_ref_change) return;
					this._save_filters();
					this._query_server();
				},
			},
			parent: $container[0],
			render_input: true,
			only_input: true,
		});
		this.ref_ctrl.refresh();
		$container.find(".frappe-control").css("margin-bottom", "0");
		$container.find("input").css({ height: "31px", fontSize: "12px" });
	}

	_get_ref_value() {
		if (!this.ref_ctrl) return "";
		// Prefer the visible input (covers values restored via set_input), then
		// fall back to the control's internal value.
		const input_val = this.ref_ctrl.$input ? this.ref_ctrl.$input.val() : "";
		return (input_val || this.ref_ctrl.get_value() || "").trim();
	}

	// Point the Link control at DocType or Report, and refresh the app's module
	// scope so the dropdown only shows that app's doctypes/reports.
	async _refresh_ref_control() {
		const app = this.$f_app.val() || "";
		const type = this.$f_type.val() || "";

		// Fetch + cache the modules for the selected app (for get_query scoping)
		if (app) {
			const r = await frappe.call({
				method: "testcase_manager.testcase_manager.api.get_app_modules",
				args: { app },
			});
			this._app_modules = r.message || [];
		} else {
			this._app_modules = [];
		}

		this.ref_ctrl.df.options = type === "Report" ? "Report" : "DocType";
		this.ref_ctrl.df.placeholder = type === "Report" ? __("All Reports") : __("All DocTypes");
		this._suppress_ref_change = true;
		await this.ref_ctrl.set_value("");
		this._suppress_ref_change = false;
		this.ref_ctrl.refresh();
	}

	// ── Filter persistence (localStorage) ─────────────────────────────────

	_save_filters() {
		const data = {
			app: this.$f_app.val() || "",
			type: this.$f_type.val() || "",
			ref: this._get_ref_value(),
			search: this.$f_search.val() || "",
		};
		try {
			localStorage.setItem(TC_FILTER_KEY, JSON.stringify(data));
		} catch (e) {
			// storage unavailable, ignore
		}
	}

	_restore_filters() {
		try {
			this._saved = JSON.parse(localStorage.getItem(TC_FILTER_KEY) || "{}");
		} catch (e) {
			this._saved = {};
		}
		if (this._saved.type) this.$f_type.val(this._saved.type);
		if (this._saved.search) this.$f_search.val(this._saved.search);
		this._update_ref_label();
	}

	_reset_filters() {
		try {
			localStorage.removeItem(TC_FILTER_KEY);
		} catch (e) {
			// storage unavailable, ignore
		}
		this._saved = {};
		this.$f_app.val("");
		this.$f_type.val("");
		this.$f_search.val("");
		if (this.ref_ctrl) this.ref_ctrl.set_value("");
		this._update_ref_label();
		this._toggle_runapp_btn();
		this._clear_console();
		this._refresh_ref_control().then(() => this._query_server());
		frappe.show_alert({ message: __("Filters cleared"), indicator: "blue" });
	}

	// ── Dropdown population ────────────────────────────────────────────────

	async _load_apps() {
		const r = await frappe.call({
			method: "testcase_manager.testcase_manager.api.get_installed_apps_list",
		});
		this.$f_app.empty().append(`<option value="">${__("All Apps")}</option>`);
		(r.message || []).forEach((a) => this.$f_app.append(`<option value="${a}">${a}</option>`));

		if (this._saved && this._saved.app) this.$f_app.val(this._saved.app);
		this._toggle_runapp_btn();

		await this._refresh_ref_control();
		// Restore a previously-selected DocType/Report after the control is scoped.
		// Use set_input (display only) — NOT set_value — so the Link control does
		// not run server-side validation against its get_query scope, which would
		// raise "X did not match any results" for the restored value on load.
		if (this._saved && this._saved.ref) {
			this._suppress_ref_change = true;
			this.ref_ctrl.set_input(this._saved.ref);
			this.ref_ctrl.value = this._saved.ref;
			this.ref_ctrl.last_value = this._saved.ref;
			this._suppress_ref_change = false;
		}
		this._query_server();
	}

	_update_ref_label() {
		const type = this.$f_type.val() || "";
		this.$ref_label.text(
			type === "Report"
				? __("Report")
				: type === "DocType"
				? __("DocType")
				: __("DocType / Report")
		);
	}

	_toggle_runapp_btn() {
		this.$runapp_btn.toggle(!!(this.$f_app.val() || ""));
	}

	// ── Query ──────────────────────────────────────────────────────────────

	_query_server() {
		clearTimeout(this._query_timer);
		this._query_timer = setTimeout(() => this._do_query(), 300);
	}

	async _do_query() {
		const app = this.$f_app.val() || "";
		const type = this.$f_type.val() || "";
		const ref = this._get_ref_value();
		const search = (this.$f_search.val() || "").trim();

		const args = { app, reference_type: type, search, page_size: 10000 };
		if (type === "Report") args.report = ref;
		else args.reference_doctype = ref;

		this.$list.html(`<div style="padding:20px;text-align:center;color:#888;">Loading…</div>`);

		const r = await frappe.call({
			method: "testcase_manager.testcase_manager.api.get_test_cases_for_page",
			args,
		});
		if (!r.message) return;

		this.records = r.message.records || [];
		const total = r.message.total || 0;
		this.$count.text(
			total > this.records.length
				? `${this.records.length} of ${total} — refine filters`
				: `${this.records.length} test(s)`
		);

		this._render_list();
	}

	// ── List rendering (alphabetical within groups) ───────────────────────

	_render_list() {
		if (!this.records.length) {
			this.$list.html(
				`<div style="padding:32px;text-align:center;color:#888;">${__(
					"No tests found. Adjust filters or Sync."
				)}</div>`
			);
			return;
		}

		const groups = {};
		this.records.forEach((r) => {
			const gk = `${r.app} › ${r.module || r.reference_doctype || r.report || "—"}`;
			(groups[gk] = groups[gk] || []).push(r);
		});

		const $frag = $(document.createDocumentFragment());
		Object.keys(groups)
			.sort((a, b) => a.localeCompare(b))
			.forEach((label) => {
				const rows = groups[label].sort((a, b) =>
					(a.test_method || "").localeCompare(b.test_method || "")
				);

				const $g = $(
					`<div style="display:block;"><div style="display:block;padding:6px 12px;background:var(--subtle-bg);border-top:1px solid var(--border-color);border-bottom:1px solid var(--border-color);font-size:10px;font-weight:800;color:var(--text-muted);text-transform:uppercase;letter-spacing:.6px;line-height:1.4;">${frappe.utils.escape_html(
						label
					)}</div></div>`
				);

				rows.forEach((tc) => {
					const $row = $(`
					<div class="tc-row" data-name="${
						tc.name
					}" style="display:flex;align-items:center;gap:8px;padding:7px 12px;border-bottom:1px solid var(--border-color);cursor:pointer;">
						<input type="checkbox" class="tc-row-check" data-name="${
							tc.name
						}" style="flex-shrink:0;cursor:pointer;">
						<div style="flex:1;min-width:0;">
							<div style="font-size:13px;font-weight:600;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${frappe.utils.escape_html(
								tc.test_method
							)}</div>
							<div style="font-size:11px;color:#888;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${frappe.utils.escape_html(
								tc.python_path
							)}</div>
						</div>
						<button class="btn btn-xs btn-primary tc-run-btn" title="${__("Run this test")}">&#x25B6;</button>
					</div>
				`);
					$row.on("mouseenter", () =>
						$row.css("background", "var(--fg-hover-color)")
					).on("mouseleave", () => $row.css("background", ""));
					$row.find(".tc-run-btn").on("click", (e) => {
						e.stopPropagation();
						this._run_one(tc.name, tc.test_method);
					});
					$row.on("click", (e) => {
						if ($(e.target).is("input,button")) return;
						const $cb = $row.find(".tc-row-check");
						$cb.prop("checked", !$cb.prop("checked"));
					});
					$g.append($row);
				});
				$frag.append($g);
			});

		this.$list.empty().append($frag);
	}

	// ── Run actions ─────────────────────────────────────────────────────────

	// Session = one user-initiated run action (single test, app run, or a queue).
	_start_session(mode, label) {
		this._clear_console();
		this._stopped = false;
		this._session = { active: true, mode, passed: 0, failed: 0, errors: 0 };
		this.$run_label.text(label);
		this._set_status(__("Queuing…"), "#dca03c");
		this.$log_link_row.hide();
		this.$stop_btn.show();
	}

	_end_session() {
		if (this._session) this._session.active = false;
		this.$stop_btn.hide();
		this.current_run = null;
	}

	_run_one(test_case_name, label) {
		this._start_session("single", label);
		this._set_status(__("Running"), "#dca03c");
		this._append_line(`▶ Running test: ${label}`, "#79c0ff");
		this._append_line("", null);
		frappe.call({
			method: "testcase_manager.testcase_manager.api.run_test_case",
			args: { test_case: test_case_name, run_scope: "Method", background: 0 },
			callback: (r) => {
				if (!r.message) {
					this._append_line("✖ Failed to start the test (API error).", "#ff7b72");
					this._end_session();
					return;
				}
				this._set_log_link(__("Open run →"), "Testcase Run", r.message.run_name);
				if (r.message.result) {
					// Inline run — already finished; render from returned result.
					this.current_run = r.message.run_name;
					this._render_inline_output(r.message.result);
					this._on_run_complete(r.message.result, true);
				} else {
					this._subscribe(r.message.run_name);
				}
			},
		});
	}

	// Append full_output to the console for an inline (non-realtime) run.
	// The intro header is preserved (we don't clear), so the user always sees
	// the "Running…" context above the captured test output.
	_render_inline_output(result) {
		(result.full_output || "").split("\n").forEach((l) => this._append_line(l));
	}

	_run_entire_app() {
		const app = this.$f_app.val();
		if (!app) return;
		frappe.confirm(
			__("Run the ENTIRE test suite for <b>{0}</b>? This may take a while.", [app]),
			() => {
				this._start_session("single", __("Entire app: {0}", [app]));
				this._append_line(`▶ Running the entire test suite for: ${app}`, "#79c0ff");
				this._append_line(
					"This runs in the background and may take several minutes…",
					"#8b949e"
				);
				this._append_line("", null);
				frappe.call({
					method: "testcase_manager.testcase_manager.api.run_app_tests",
					args: { app },
					callback: (r) => {
						if (!r.message) {
							this._end_session();
							return;
						}
						this._subscribe(r.message.run_name);
						this._set_status(__("Running"), "#dca03c");
						this._set_log_link(__("Open run →"), "Testcase Run", r.message.run_name);
					},
				});
			}
		);
	}

	_run_selected() {
		const names = this.$list
			.find(".tc-row-check:checked")
			.map((_, el) => $(el).data("name"))
			.get();
		if (!names.length) {
			frappe.msgprint(__("Select at least one test to run."));
			return;
		}

		if (names.length === 1) {
			const rec = this.records.find((r) => r.name === names[0]);
			this._run_one(names[0], rec?.test_method || names[0]);
			return;
		}

		this._run_batch(names);
	}

	// Run a multi-test selection as ONE batch → the costly Frappe test
	// environment setup (before_tests hooks, global records, cache clear) is
	// paid once for the whole batch instead of once per test. Much faster.
	_run_batch(names) {
		this._start_session("single", __("{0} tests (batch)", [names.length]));
		this._set_status(__("Running"), "#dca03c");
		this._append_line(
			`▶ Running ${names.length} tests together (one shared setup)`,
			"#79c0ff"
		);
		this._append_line("Please wait — test environment is being prepared…", "#8b949e");
		this._append_line("", null);
		const background = names.length > 20 ? 1 : 0;
		frappe.call({
			method: "testcase_manager.testcase_manager.api.run_test_batch",
			args: { test_cases: JSON.stringify(names), background },
			callback: (r) => {
				if (!r.message) {
					this._append_line("✖ Failed to start the batch (API error).", "#ff7b72");
					this._end_session();
					return;
				}
				this._set_log_link(__("Open run →"), "Testcase Run", r.message.run_name);
				if (r.message.result) {
					this.current_run = r.message.run_name;
					this._render_inline_output(r.message.result);
					this._on_run_complete(r.message.result, true);
				} else {
					this._subscribe(r.message.run_name);
				}
			},
		});
	}

	_process_queue() {
		if (this._stopped) return;
		if (!this._run_queue.length) {
			// Queue finished — show aggregate summary across all tests.
			this._render_summary(this._session, `All ${this._queue_total} tests completed`);
			this._queue_total = 0;
			this._end_session();
			return;
		}
		const { name, label } = this._run_queue.shift();
		this._queue_done++;
		this._append_line(`\n${"─".repeat(50)}`, "#6e7681");
		this._append_line(`[${this._queue_done}/${this._queue_total}] ${label}`, "#79c0ff");
		this._set_status(`${this._queue_done}/${this._queue_total}`, "#dca03c");
		frappe.call({
			method: "testcase_manager.testcase_manager.api.run_test_case",
			args: {
				test_case: name,
				run_scope: "Method",
				background: this._queue_background ? 1 : 0,
			},
			callback: (r) => {
				if (!r.message) {
					this._append_line("  ERROR: API call failed.", "#ff7b72");
					this._process_queue();
					return;
				}
				if (r.message.result) {
					// Inline — already finished; render output then advance.
					this.current_run = r.message.run_name;
					(r.message.result.full_output || "")
						.split("\n")
						.forEach((l) => this._append_line(l));
					this._pending_next = () => this._process_queue();
					this._on_run_complete(r.message.result, true);
				} else {
					this._subscribe(r.message.run_name);
					this._pending_next = () => this._process_queue();
				}
			},
		});
	}

	// ── Stop / abort ──────────────────────────────────────────────────────

	_stop() {
		this._stopped = true;
		const running = this.current_run;
		this._run_queue = [];
		this._pending_next = null;
		if (running) {
			frappe.realtime.task_unsubscribe(running);
			frappe.call({
				method: "testcase_manager.testcase_manager.api.stop_run",
				args: { run_name: running },
			});
		}
		this.current_run = null;
		this._append_line("\n■ Stopped by user.", "#ff7b72");
		this._set_status(__("Stopped"), "#999");
		this.$summary
			.css({ background: "#4a1515", color: "#ff7b72" })
			.html("&#x25A0; Stopped by user")
			.show();
		this._end_session();
	}

	// ── Sync ─────────────────────────────────────────────────────────────

	_sync_all() {
		// Scope the sync to whatever filters are currently selected.
		const app = this.$f_app.val() || "";
		const type = this.$f_type.val() || "";
		const ref = this._get_ref_value();

		const args = { app };
		if (app) {
			if (type) args.reference_type = type;
			if (ref) args.reference = ref;
		}

		const scope_label = !app
			? __("all apps")
			: ref
			? `${app} › ${ref}`
			: type
			? `${app} › ${type}`
			: app;

		frappe.call({
			method: "testcase_manager.testcase_manager.api.sync_test_cases",
			args,
			freeze: true,
			freeze_message: __("Syncing {0}…", [scope_label]),
			callback: (r) => {
				const m = r.message || {};
				if (m.status === "queued") {
					frappe.show_alert({
						message: __("Full sync queued in background"),
						indicator: "blue",
					});
				} else {
					frappe.show_alert({
						message: __(
							"Sync complete ({0}) — created: {1}, updated: {2}, deleted: {3}",
							[scope_label, m.created, m.updated, m.deleted]
						),
						indicator: "green",
					});
					// Reload the test list in place — keep the current filters
					// exactly as they are (don't rerun the app/restore flow, which
					// would reset the DocType/Report selection).
					this._query_server();
				}
			},
		});
	}

	// ── Realtime ──────────────────────────────────────────────────────────

	_setup_realtime() {
		frappe.realtime.on("test_output", (data) => {
			if (data.run_name !== this.current_run) return;
			this._append_line(data.line);
		});
		frappe.realtime.on("test_completed", (data) => {
			if (data.run_name !== this.current_run) return;
			this._on_run_complete(data);
		});
	}

	_subscribe(run_name) {
		if (this.current_run && this.current_run !== run_name)
			frappe.realtime.task_unsubscribe(this.current_run);
		this.current_run = run_name;
		frappe.realtime.task_subscribe(run_name);
	}

	// ── Console helpers ───────────────────────────────────────────────────

	_copy_console() {
		// Join each rendered line with a newline (\n) — .text() alone drops the
		// line breaks between the <div> rows and produces one long line.
		const text = this.$console
			.children()
			.map((_, el) => $(el).text())
			.get()
			.join("\n");
		if (!text.trim()) {
			frappe.show_alert({ message: __("Console is empty"), indicator: "orange" });
			return;
		}
		const done = () =>
			frappe.show_alert({ message: __("Console output copied"), indicator: "green" });
		const fallback = () => {
			// Fallback for non-secure contexts where navigator.clipboard is unavailable
			const ta = document.createElement("textarea");
			ta.value = text;
			document.body.appendChild(ta);
			ta.select();
			try {
				document.execCommand("copy");
				done();
			} catch (e) {
				frappe.msgprint(__("Copy failed — select text manually."));
			}
			document.body.removeChild(ta);
		};
		if (navigator.clipboard?.writeText)
			navigator.clipboard.writeText(text).then(done, fallback);
		else fallback();
	}

	_append_line(raw_line, forced_color = null) {
		const safe = frappe.utils.escape_html(_stripAnsi(raw_line || ""));
		const html = forced_color
			? `<span style="color:${forced_color}">${safe}</span>`
			: _colourLine(safe);
		this.$console.append(`<div>${html}</div>`);
		this.$console[0].scrollTop = this.$console[0].scrollHeight;
	}

	_clear_console() {
		this.$console.empty();
		this.$summary.hide();
		this.$status_badge.hide();
		this.$log_link_row.hide();
		if (this.$stop_btn) this.$stop_btn.hide();
		this.$run_label.text("Console");
	}

	_set_status(label, bg) {
		this.$status_badge.text(label).css({ display: "inline-block", background: bg }).show();
	}

	_set_log_link(text, doctype, name) {
		this.$log_link
			.text(text)
			.off("click")
			.on("click", (e) => {
				e.preventDefault();
				frappe.set_route("Form", doctype, name);
			});
		this.$log_link_row.show();
	}

	_on_run_complete(data, inline = false) {
		if (this._stopped) return;
		if (!inline) frappe.realtime.task_unsubscribe(this.current_run);

		// Accumulate this run's counts into the session totals.
		if (this._session) {
			this._session.passed += data.passed || 0;
			this._session.failed += data.failed || 0;
			this._session.errors += data.errors || 0;
		}

		// In single mode the streamed lines are already shown; only re-render
		// from full_output if we clearly missed a chunk (fast test / timing).
		// For inline runs the output was already painted by _render_inline_output.
		if (data.full_output && !inline) {
			const seen = this.$console.children().length;
			const total = data.full_output.split("\n").length;
			if (seen < total * 0.6) {
				this.$console.empty();
				data.full_output.split("\n").forEach((l) => this._append_line(l));
			}
		}
		if (data.duration) this._append_line(`Duration: ${data.duration}s`, "#8b949e");

		const queue_continuing =
			this._pending_next &&
			this._run_queue.length >= 0 &&
			this._session?.mode === "queue" &&
			this._run_queue.length > 0;

		if (this._session && this._session.mode === "single") {
			// Single run: final summary uses this run's counts.
			this._render_summary(this._session, data.status);
			if (data.log_name)
				this._set_log_link(__("Open full log →"), "Testcase Log", data.log_name);
			this._end_session();
		}

		// Advance the queue (the queue end will render the aggregate summary).
		if (this._pending_next) {
			const next = this._pending_next;
			this._pending_next = null;
			this.current_run = null;
			setTimeout(next, 400);
		} else if (!this._session || this._session.mode !== "single") {
			this.current_run = null;
		}
	}

	// Render the green/red summary bar from accumulated counts.
	_render_summary(sess, status_label) {
		const ok = sess.failed + sess.errors === 0;
		const fg = ok ? "#3fb950" : "#ff7b72";
		const bg = ok ? "#1a472a" : "#4a1515";
		const icon = ok ? "✔" : "✖";
		const word = ok ? "Passed" : "Failed";
		const summary = `Passed: ${sess.passed}, Failed: ${sess.failed}, Errors: ${sess.errors}`;

		this._append_line("", null);
		this._append_line(`${icon} ${word} — ${summary}`, fg);

		this.$summary
			.css({ background: bg, color: fg })
			.html(`${icon} ${word} &mdash; ${frappe.utils.escape_html(summary)}`)
			.show();
		this._set_status(word, fg);
	}
}

// ── Module helpers ────────────────────────────────────────────────────────

function _stripAnsi(str) {
	// eslint-disable-next-line no-control-regex
	return (str || "").replace(/\x1b\[[0-9;]*[mGKHF]/g, "");
}

function _colourLine(safe) {
	// High-contrast palette tuned for the #0d1117 background.
	if (/✔|PASS\b|^OK\b/.test(safe)) return `<span style="color:#3fb950">${safe}</span>`;
	if (/✖/.test(safe)) return `<span style="color:#ff7b72">${safe}</span>`;
	if (/^FAIL\b|^ERROR\b|^AssertionError/.test(safe))
		return `<span style="color:#ff7b72;font-weight:600">${safe}</span>`;
	if (/^Traceback/.test(safe)) return `<span style="color:#ffa657">${safe}</span>`;
	if (/^\s+File "|^\s+raise /.test(safe)) return `<span style="color:#ffa657">${safe}</span>`;
	if (/^Running \d|^Ran \d/.test(safe)) return `<span style="color:#79c0ff">${safe}</span>`;
	if (/^={3,}$|^-{3,}$/.test(safe)) return `<span style="color:#6e7681">${safe}</span>`;
	if (/^FAILED\b/.test(safe))
		return `<span style="color:#ff7b72;font-weight:700">${safe}</span>`;
	return `<span style="color:#e6edf3">${safe}</span>`;
}
