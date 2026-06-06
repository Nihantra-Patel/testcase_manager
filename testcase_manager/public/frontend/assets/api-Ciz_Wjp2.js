async function a(e, r, p = {}) {
	r || (r = {});
	let g = Object.assign(
		{
			Accept: "application/json",
			"Content-Type": "application/json; charset=utf-8",
			"X-Frappe-Site-Name": window.location.hostname,
		},
		p.headers || {}
	);
	window.csrf_token &&
		window.csrf_token !== "{{ csrf_token }}" &&
		(g["X-Frappe-CSRF-Token"] = window.csrf_token);
	let l = e.startsWith("/") ? e : `/api/method/${e}`;
	const i = await fetch(l, { method: "POST", headers: g, body: JSON.stringify(r) });
	if (i.ok) {
		const o = await i.json();
		if (o.docs || e === "login") return o;
		if (o.exc)
			try {
				console.groupCollapsed(e), console.log(`method: ${e}`), console.log("params:", r);
				let s = JSON.parse(o.exc);
				for (let c of s) console.log(c);
				console.groupEnd();
			} catch (s) {
				console.warn("Error printing debug messages", s);
			}
		return o.message;
	} else {
		let o = await i.text(),
			s,
			c;
		try {
			s = JSON.parse(o);
		} catch {}
		let f = [[e, s.exc_type, s._error_message].filter(Boolean).join(" ")];
		if (s.exc) {
			c = s.exc;
			try {
				(c = JSON.parse(c)[0]), console.log(c);
			} catch {}
		}
		let t = new Error(
			f.join(`
`)
		);
		throw (
			((t.exc_type = s.exc_type),
			(t.exc = c),
			(t.status = i.status),
			(t.messages = s._server_messages ? JSON.parse(s._server_messages) : []),
			(t.messages = t.messages.concat(s.message)),
			(t.messages = t.messages.map((_) => {
				try {
					return JSON.parse(_).message;
				} catch {
					return _;
				}
			})),
			(t.messages = t.messages.filter(Boolean)),
			t.messages.length ||
				(t.messages = s._error_message ? [s._error_message] : ["Internal Server Error"]),
			p.onError && p.onError({ response: i, status: i.status, error: t }),
			t)
		);
	}
}
const n = "testcase_manager.testcase_manager.api",
	m = {
		getInstalledApps: () => a(`${n}.get_installed_apps_list`),
		getReferenceOptions: (e, r) =>
			a(`${n}.get_reference_options`, { app: e, reference_type: r }),
		getTestCases: (e) => a(`${n}.get_test_cases_for_page`, e),
		runTestCase: (e, r = "Method", p = 0) =>
			a(`${n}.run_test_case`, { test_case: e, run_scope: r, background: p }),
		runTestBatch: (e, r = 0) =>
			a(`${n}.run_test_batch`, { test_cases: JSON.stringify(e), background: r }),
		runAppTests: (e) => a(`${n}.run_app_tests`, { app: e }),
		stopRun: (e, r) => a(`${n}.stop_run`, { run_name: e, partial_output: r }),
		syncTestCases: (e) => a(`${n}.sync_test_cases`, e),
		getRunCount: (e) => a(`${n}.get_run_count`, { filters: JSON.stringify(e || {}) }),
		getTestCaseNamesByType: (e) =>
			a(`${n}.get_test_case_names_by_type`, { reference_type: e }),
	};
export { m as a };
//# sourceMappingURL=api-Ciz_Wjp2.js.map
