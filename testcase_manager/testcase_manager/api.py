"""
Whitelisted API endpoints for the TestCase Manager.

All methods are callable from the browser via frappe.call().
"""

import frappe
from frappe.utils import now_datetime


# ---------------------------------------------------------------------------
# Test Execution
# ---------------------------------------------------------------------------


@frappe.whitelist()
def run_test_case(test_case: str, run_scope: str = "Method") -> dict:
	"""
	Create a Test Case Run and enqueue the background execution job.

	Returns:
	    dict with ``run_name`` (the new Test Case Run ID) and ``task_id``
	    (same value — used by the UI to subscribe to realtime events).
	"""
	tc = frappe.get_doc("Testcase", test_case)

	run = frappe.new_doc("Testcase Run")
	run.test_case = test_case
	run.app = tc.app
	run.test_method = tc.test_method
	run.python_path = tc.python_path
	run.site = frappe.local.site
	run.triggered_by = frappe.session.user
	run.status = "Pending"
	run.run_scope = run_scope
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	frappe.enqueue(
		"testcase_manager.testcase_manager.executor.execute_test_case_job",
		queue="long",
		timeout=1800,
		job_id=f"tc_run_{run.name}",
		run_name=run.name,
	)

	return {"run_name": run.name, "task_id": run.name}


@frappe.whitelist()
def stop_run(run_name: str) -> dict:
	"""
	Best-effort abort of a running/queued test execution.

	- If the RQ job hasn't started yet, it is cancelled (removed from the queue).
	- If it is already running in a worker, a stop command is sent to terminate it.
	- The Testcase Run is marked as ``Error`` with a "Stopped by user" note.
	"""
	from frappe.utils.background_jobs import create_job_id, get_redis_conn

	full_job_id = create_job_id(f"tc_run_{run_name}")
	cancelled = False
	try:
		from rq.job import Job

		conn = get_redis_conn()
		job = Job.fetch(full_job_id, connection=conn)
		status = job.get_status(refresh=True)
		if status == "started":
			from rq.command import send_stop_job_command

			send_stop_job_command(conn, full_job_id)
			cancelled = True
		else:
			job.cancel()
			cancelled = True
	except Exception:
		# Job may have already finished or never existed — that's fine.
		pass

	# Mark the run as stopped (only if not already in a terminal state)
	current = frappe.db.get_value("Testcase Run", run_name, "status")
	if current in ("Pending", "Running"):
		frappe.db.set_value(
			"Testcase Run",
			run_name,
			{"status": "Error", "result": "Stopped by user", "end_time": now_datetime()},
			update_modified=False,
		)
		frappe.db.commit()

	return {"stopped": cancelled, "run_name": run_name}


@frappe.whitelist()
def rerun_test(run_name: str) -> dict:
	"""
	Create a fresh Test Case Run from an existing run (or log's run reference).
	Useful for the Re-Run button on Test Case Log.
	"""
	original = frappe.get_doc("Testcase Run", run_name)
	return run_test_case(original.test_case, original.run_scope or "Method")


# ---------------------------------------------------------------------------
# Test Case Discovery / Sync
# ---------------------------------------------------------------------------


@frappe.whitelist()
def sync_test_cases(app: str | None = None) -> dict:
	"""
	Trigger test case discovery for one app or all installed apps.

	This runs synchronously for a single app; for all apps it uses a
	background job to avoid request timeouts.
	"""
	from testcase_manager.testcase_manager.discovery import discover_all_test_cases

	if app:
		result = discover_all_test_cases(app_name=app)
	else:
		frappe.enqueue(
			"testcase_manager.testcase_manager.discovery.discover_all_test_cases",
			queue="long",
			timeout=600,
			job_id="tc_full_sync",
		)
		return {"status": "queued", "message": "Full sync queued in background"}

	return {"status": "ok", **result}


# ---------------------------------------------------------------------------
# Data queries (used by Test Runner page)
# ---------------------------------------------------------------------------


@frappe.whitelist()
def get_test_cases_for_page(
	app: str | None = None,
	reference_type: str | None = None,
	reference_doctype: str | None = None,
	report: str | None = None,
	search: str | None = None,
	page: int = 1,
	page_size: int = 200,
) -> dict:
	"""
	Return paginated, filtered list of Test Case records for the Test Runner page.

	``reference_doctype`` filters the ``reference_doctype`` field (used when
	reference_type is "DocType").
	``report`` filters the ``report`` field (used when reference_type is "Report").
	"""
	filters: dict = {"status": "Active"}
	if app and app.strip():
		filters["app"] = app.strip()
	if reference_type and reference_type.strip():
		filters["reference_type"] = reference_type.strip()
	if report and report.strip():
		filters["report"] = report.strip()
	if reference_doctype and reference_doctype.strip():
		filters["reference_doctype"] = reference_doctype.strip()

	or_filters = None
	if search and search.strip():
		or_filters = [
			["test_method", "like", f"%{search.strip()}%"],
			["reference_doctype", "like", f"%{search.strip()}%"],
			["report", "like", f"%{search.strip()}%"],
			["python_path", "like", f"%{search.strip()}%"],
		]

	fields = [
		"name",
		"app",
		"module",
		"reference_type",
		"reference_doctype",
		"report",
		"test_file",
		"test_method",
		"python_path",
		"status",
	]

	total = frappe.db.count("Testcase", filters=filters)

	records = frappe.get_all(
		"Testcase",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		limit_start=(int(page) - 1) * int(page_size),
		limit_page_length=int(page_size),
		order_by="app asc, module asc, test_method asc",
	)

	return {"total": total, "records": records}


@frappe.whitelist()
def get_installed_apps_list() -> list[str]:
	"""Return only apps that actually have discovered test cases (for filter dropdowns)."""
	rows = frappe.get_all(
		"Testcase",
		filters={"status": "Active"},
		distinct=True,
		pluck="app",
		order_by="app asc",
	)
	return rows


@frappe.whitelist()
def get_reference_options(app: str | None = None, reference_type: str | None = None) -> list[str]:
	"""
	Return the distinct DocType (or Report) names that actually have test cases,
	optionally scoped to a single app.

	Used by the Test Runner's DocType/Report filter so it only offers references
	relevant to the selected app — not every DocType/Report on the site.
	"""
	filters: dict = {"status": "Active"}
	if app and app.strip():
		filters["app"] = app.strip()

	field = "report" if (reference_type or "").strip() == "Report" else "reference_doctype"
	if (reference_type or "").strip():
		filters["reference_type"] = reference_type.strip()

	values = frappe.get_all(
		"Testcase",
		filters=filters,
		distinct=True,
		pluck=field,
		order_by=f"{field} asc",
	)
	return [v for v in values if v]


@frappe.whitelist()
def get_app_modules(app: str | None = None) -> list[str]:
	"""
	Return the Module Def names that belong to *app* — used to scope the
	Test Runner's DocType/Report Link picker to the selected app.
	"""
	if not (app and app.strip()):
		return []
	return frappe.get_all("Module Def", filters={"app_name": app.strip()}, pluck="name")


@frappe.whitelist()
def run_app_tests(app: str) -> dict:
	"""
	Run the entire test suite for an app in one background job.

	Anchors the run on any one Testcase belonging to the app (the executor only
	needs ``tc.app`` to drive ``discover_all_tests`` for App scope).
	"""
	anchor = frappe.db.get_value("Testcase", {"app": app, "status": "Active"}, "name")
	if not anchor:
		frappe.throw(f"No active test cases found for app '{app}'")
	return run_test_case(anchor, run_scope="App")


@frappe.whitelist()
def get_run_status(run_name: str) -> dict:
	"""Lightweight poll endpoint; the UI prefers realtime but this is a fallback."""
	doc = frappe.get_doc("Testcase Run", run_name)
	return {
		"status": doc.status,
		"result": doc.result,
		"start_time": str(doc.start_time) if doc.start_time else None,
		"end_time": str(doc.end_time) if doc.end_time else None,
	}


@frappe.whitelist()
def get_log_for_run(run_name: str) -> dict | None:
	"""Return the Test Case Log name for a given run (if it exists)."""
	name = frappe.db.get_value("Testcase Log", {"run_reference": run_name}, "name")
	return {"log_name": name} if name else None
