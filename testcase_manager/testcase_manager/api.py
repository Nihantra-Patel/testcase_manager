"""
Whitelisted API endpoints for the TestCase Manager.

All methods are callable from the browser via frappe.call().
"""

import frappe
from frappe.utils import now_datetime

# Roles allowed to run tests / mutate Testcase records. Running a test imports and
# executes arbitrary Python in a worker, so the whitelisted endpoints must not be
# callable by every logged-in user — gate them explicitly.
ALLOWED_ROLES = ("System Manager",)


def _guard() -> None:
	"""Allow only privileged roles to invoke a mutating / test-running endpoint."""
	frappe.only_for(ALLOWED_ROLES)


# ---------------------------------------------------------------------------
# Test Execution
# ---------------------------------------------------------------------------


def _combined_reference_type(test_case_names: list[str]) -> str:
	"""
	Build the History "Type" label for a run from its testcases' reference_types.

	A single test → "DocType" or "Report". A batch spanning both → "DocType-Report"
	(types joined, sorted, deduped). Tests with no reference_type are ignored.
	"""
	if not test_case_names:
		return ""
	tc = frappe.qb.DocType("Testcase")
	rows = (
		frappe.qb.from_(tc)
		.select(tc.reference_type)
		.distinct()
		.where(tc.name.isin(test_case_names))
		.run(pluck=True)
	)
	distinct = sorted({t for t in rows if t})
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
	_guard()
	# Only a few fields are needed to seed the run — fetch them, not the whole doc.
	tc = frappe.db.get_value(
		"Testcase",
		test_case,
		["app", "test_method", "python_path", "reference_type"],
		as_dict=True,
	)

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
		return {
			"run_name": run.name,
			"task_id": run.name,
			"background": False,
			"result": _inline_result(run.name),
		}

	return {"run_name": run.name, "task_id": run.name, "background": use_bg}


def _inline_result(run_name: str) -> dict:
	"""Build the UI result payload from a finished (inline) Testcase Run."""
	run = frappe.db.get_value(
		"Testcase Run",
		run_name,
		["status", "result", "duration", "full_output", "traceback"],
		as_dict=True,
	)
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
	_guard()
	import json

	if isinstance(test_cases, str):
		test_cases = json.loads(test_cases)
	if not test_cases:
		frappe.throw("No test cases provided")

	anchor = frappe.db.get_value("Testcase", test_cases[0], ["app", "python_path"], as_dict=True)

	run = frappe.new_doc("Testcase Run")
	run.test_case = test_cases[0]
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
	_guard()
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
	_guard()
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
def run_app_tests(app: str) -> dict:
	"""
	Run the entire test suite for an app in one background job.

	Anchors the run on any one Testcase belonging to the app (the executor only
	needs ``tc.app`` to drive ``discover_all_tests`` for App scope).
	"""
	_guard()
	anchor = frappe.db.get_value("Testcase", {"app": app, "status": "Active"}, "name")
	if not anchor:
		frappe.throw(f"No active test cases found for app '{app}'")
	# Whole-app runs are long → always background.
	return run_test_case(anchor, run_scope="App", background=1)
