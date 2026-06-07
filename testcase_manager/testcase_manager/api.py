"""
Whitelisted API endpoints for the TestCase Manager.

All methods are callable from the browser via frappe.call().
"""

import frappe
from frappe.utils import now_datetime

# ---------------------------------------------------------------------------
# Test Execution
# ---------------------------------------------------------------------------


def _combined_reference_type(test_case_names: list[str]) -> str:
	"""
	Build the History "Type" label for a run from its testcases' reference_types.

	A single test → "DocType" or "Report". A batch spanning both → "DocType-Report"
	(types joined, sorted, deduped). Tests with no reference_type are ignored.
	"""
	types = frappe.get_all(
		"Testcase",
		filters={"name": ["in", test_case_names]},
		pluck="reference_type",
	)
	distinct = sorted({t for t in types if t})
	return "-".join(distinct)


@frappe.whitelist()
def run_test_case(test_case: str, run_scope: str = "Method", background: int | str | bool = 0) -> dict:
	"""
	Create a Test Case Run and execute it.

	By default (``background`` falsy) the test runs *inline* in the current
	request — faster, no RQ queue/worker pickup latency. The UI uses this for
	single tests and small selections. Heavy runs (>20 tests, "Run Entire App")
	pass ``background=1`` so they execute in an RQ worker without blocking.

	Returns:
	    dict with ``run_name`` (the new Test Case Run ID) and ``task_id``
	    (same value — used by the UI to subscribe to realtime events).
	"""
	tc = frappe.get_doc("Testcase", test_case)

	run = frappe.new_doc("Testcase Run")
	run.test_case = test_case
	run.app = tc.app
	# For a whole-app run the anchor testcase's method name is meaningless as a
	# label, so use a descriptive title instead (shown in History).
	run.test_method = f"Entire test suite for: {tc.app}" if run_scope == "App" else tc.test_method
	run.python_path = tc.python_path
	# Type label for History. A whole-app run spans every type, so label it "App".
	run.reference_type = "App" if run_scope == "App" else (tc.reference_type or "")
	run.site = frappe.local.site
	run.triggered_by = frappe.session.user
	run.status = "Pending"
	run.run_scope = run_scope
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	use_bg = str(background) not in ("0", "", "false", "False", "None")

	if use_bg:
		frappe.enqueue(
			"testcase_manager.testcase_manager.executor.execute_test_case_job",
			queue="long",
			timeout=1800,
			job_id=f"tc_run_{run.name}",
			run_name=run.name,
		)
	else:
		# Run inline so there is no worker pickup latency. Realtime events are
		# still published during the run, but since the browser only subscribes
		# after this call returns, the UI relies on the returned ``result`` for
		# rendering. The full output + counts are loaded from the saved run.
		from testcase_manager.testcase_manager.executor import execute_test_case_job

		execute_test_case_job(run.name)

		run.reload()
		log_name = frappe.db.get_value("Testcase Log", {"run_reference": run.name}, "name")
		log = (
			frappe.db.get_value(
				"Testcase Log",
				log_name,
				["passed_count", "failed_count", "error_count"],
				as_dict=True,
			)
			if log_name
			else {}
		)
		return {
			"run_name": run.name,
			"task_id": run.name,
			"background": False,
			"result": {
				"run_name": run.name,
				"status": run.status,
				"log_name": log_name,
				"summary": run.result,
				"duration": run.duration,
				"passed": (log or {}).get("passed_count") or 0,
				"failed": (log or {}).get("failed_count") or 0,
				"errors": (log or {}).get("error_count") or 0,
				"full_output": run.full_output,
				"traceback": run.traceback,
			},
		}

	return {"run_name": run.name, "task_id": run.name, "background": use_bg}


def _inline_result(run_name: str) -> dict:
	"""Build the UI result payload from a finished (inline) Testcase Run."""
	run = frappe.get_doc("Testcase Run", run_name)
	log_name = frappe.db.get_value("Testcase Log", {"run_reference": run_name}, "name")
	log = (
		frappe.db.get_value(
			"Testcase Log",
			log_name,
			["passed_count", "failed_count", "error_count"],
			as_dict=True,
		)
		if log_name
		else {}
	)
	return {
		"run_name": run_name,
		"status": run.status,
		"log_name": log_name,
		"summary": run.result,
		"duration": run.duration,
		"passed": (log or {}).get("passed_count") or 0,
		"failed": (log or {}).get("failed_count") or 0,
		"errors": (log or {}).get("error_count") or 0,
		"full_output": run.full_output,
		"traceback": run.traceback,
	}


@frappe.whitelist()
def run_test_batch(test_cases: str | list, background: int | str | bool = 0) -> dict:
	"""
	Run several selected tests as ONE batch (single environment setup).

	``test_cases`` is a JSON array (or list) of Testcase names. The whole batch
	is anchored on one Testcase Run. Runs inline by default; pass background=1
	for large selections.
	"""
	import json

	if isinstance(test_cases, str):
		test_cases = json.loads(test_cases)
	if not test_cases:
		frappe.throw("No test cases provided")

	anchor = frappe.get_doc("Testcase", test_cases[0])

	run = frappe.new_doc("Testcase Run")
	run.test_case = anchor.name
	run.app = anchor.app
	run.test_method = f"{len(test_cases)} tests (batch)"
	run.python_path = anchor.python_path
	# Combined type across the batch → "DocType", "Report", or "DocType-Report".
	run.reference_type = _combined_reference_type(test_cases)
	run.site = frappe.local.site
	run.triggered_by = frappe.session.user
	run.status = "Pending"
	run.run_scope = "Batch"
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	use_bg = str(background) not in ("0", "", "false", "False", "None")

	if use_bg:
		frappe.enqueue(
			"testcase_manager.testcase_manager.executor.execute_test_batch_job",
			queue="long",
			timeout=3600,
			job_id=f"tc_batch_{run.name}",
			run_name=run.name,
			test_cases=test_cases,
		)
		return {"run_name": run.name, "task_id": run.name, "background": True}

	from testcase_manager.testcase_manager.executor import execute_test_batch_job

	execute_test_batch_job(run.name, test_cases)
	return {
		"run_name": run.name,
		"task_id": run.name,
		"background": False,
		"result": _inline_result(run.name),
	}


@frappe.whitelist()
def stop_run(run_name: str, partial_output: str | None = None) -> dict:
	"""
	Best-effort abort of a running/queued test execution.

	- If the RQ job hasn't started yet, it is cancelled (removed from the queue).
	- If it is already running in a worker, a stop command is sent to terminate it.
	- The Testcase Run is marked as ``Error`` with a "Stopped by user" note.

	Because a force-stopped worker can't flush its own output, the UI passes the
	console text it has already streamed (``partial_output``) so the History page
	still shows what ran before the stop.
	"""
	from frappe.utils.background_jobs import create_job_id, get_redis_conn

	cancelled = False
	try:
		from rq.command import send_stop_job_command
		from rq.job import Job

		conn = get_redis_conn()
		# Background runs use one of two job_id prefixes (single/app vs. batch).
		for prefix in ("tc_run_", "tc_batch_"):
			try:
				job = Job.fetch(create_job_id(f"{prefix}{run_name}"), connection=conn)
			except Exception:
				continue
			if job.get_status(refresh=True) == "started":
				send_stop_job_command(conn, job.id)
			else:
				job.cancel()
			cancelled = True
	except Exception:
		# Job may have already finished or never existed — that's fine.
		pass

	# Mark the run as Stopped (only if not already in a terminal state), keeping
	# whatever output the worker managed to persist, else the UI's partial output.
	current = frappe.db.get_value("Testcase Run", run_name, "status")
	if current in ("Pending", "Running"):
		values = {
			"status": "Stopped",
			"result": "Stopped by user",
			"end_time": now_datetime(),
		}
		existing_output = frappe.db.get_value("Testcase Run", run_name, "full_output")
		output = existing_output or partial_output or ""
		# Make the stop explicit in the saved output (matches the live console).
		if "Stopped by user" not in output:
			output = (output + "\n\n■ Stopped by user").strip()
		values["full_output"] = output
		frappe.db.set_value("Testcase Run", run_name, values, update_modified=False)
		frappe.db.commit()

	return {"stopped": cancelled, "run_name": run_name}


# ---------------------------------------------------------------------------
# Test Case Discovery / Sync
# ---------------------------------------------------------------------------


@frappe.whitelist()
def sync_test_cases(
	app: str | None = None,
	reference_type: str | None = None,
	reference: str | None = None,
) -> dict:
	"""
	Trigger test case discovery, scoped to the caller's current filters.

	Scope (narrowest wins):
	  - app + reference_type + reference → just that DocType/Report (sync)
	  - app + reference_type             → that app's DocTypes/Reports (sync)
	  - app                              → the whole app (sync)
	  - none                             → every installed app (background job)

	Scoped syncs run synchronously (fast); only a full all-apps sync is queued.
	"""
	from testcase_manager.testcase_manager.discovery import discover_all_test_cases

	if app and app.strip():
		result = discover_all_test_cases(
			app_name=app.strip(),
			reference_type=(reference_type or "").strip() or None,
			reference=(reference or "").strip() or None,
		)
		return {"status": "ok", **result}

	frappe.enqueue(
		"testcase_manager.testcase_manager.discovery.discover_all_test_cases",
		queue="long",
		timeout=600,
		job_id="tc_full_sync",
	)
	return {"status": "queued", "message": "Full sync queued in background"}


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
def run_app_tests(app: str) -> dict:
	"""
	Run the entire test suite for an app in one background job.

	Anchors the run on any one Testcase belonging to the app (the executor only
	needs ``tc.app`` to drive ``discover_all_tests`` for App scope).
	"""
	anchor = frappe.db.get_value("Testcase", {"app": app, "status": "Active"}, "name")
	if not anchor:
		frappe.throw(f"No active test cases found for app '{app}'")
	# Whole-app runs are long → always background.
	return run_test_case(anchor, run_scope="App", background=1)


@frappe.whitelist()
def get_run_count(filters: str | dict | None = None) -> dict:
	"""Total number of Testcase Run records matching the History page filters."""
	import json

	if isinstance(filters, str):
		filters = json.loads(filters or "{}")

	return {"count": frappe.db.count("Testcase Run", filters=dict(filters or {}))}
