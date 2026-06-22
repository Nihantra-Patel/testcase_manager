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


# Queues a run is routed to, sized by how many tests it runs. Smaller jobs go to
# faster queues so a quick single test isn't stuck behind a whole-app run, and the
# RQ timeout scales with the expected work.
#   1-25 tests  -> "short"   (timeout 1800s)
#   26-50 tests -> "default" (timeout 2400s)
#   50+ / app   -> "long"    (timeout 3600s)
def _queue_for(test_count: int, is_app: bool = False) -> tuple[str, int]:
	if is_app or test_count > 50:
		return "long", 3600
	if test_count > 25:
		return "default", 2400
	return "short", 1800


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
	# Planned test count for live "done / total" progress: a whole-app run is every
	# active test in the app; a single method/file run is one. Stored on the run so
	# the UI keeps the total after a reload or when it follows the run mid-stream.
	if run_scope == "App":
		run.total_tests = frappe.db.count("Testcase", {"app": tc.app, "status": "Active"})
	else:
		run.total_tests = 1
	use_bg = str(background) not in ("0", "", "false", "False", "None")
	run.realtime = 1 if use_bg else 0
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	if use_bg:
		# A whole-app run → long; a single method/file → short.
		queue, timeout = _queue_for(1, is_app=(run_scope == "App"))
		frappe.enqueue(
			"testcase_manager.testcase_manager.executor.execute_test_case_job",
			queue=queue,
			timeout=timeout,
			job_id=f"tc_run_{run.name}",
			# Mark the run Error if the job dies for any reason the in-job handler
			# can't catch (crash before the try-block, killed worker, etc.).
			on_failure="testcase_manager.testcase_manager.executor.mark_run_failed_on_job_failure",
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
	run.total_tests = len(test_cases)  # for live "done / total" progress
	use_bg = str(background) not in ("0", "", "false", "False", "None")
	run.realtime = 1 if use_bg else 0
	run.insert(ignore_permissions=True)
	frappe.db.commit()

	if use_bg:
		queue, timeout = _queue_for(len(test_cases))
		frappe.enqueue(
			"testcase_manager.testcase_manager.executor.execute_test_batch_job",
			queue=queue,
			timeout=timeout,
			job_id=f"tc_batch_{run.name}",
			# Mark the run Error if the job dies for any reason the in-job handler
			# can't catch (crash before the try-block, killed worker, etc.).
			on_failure="testcase_manager.testcase_manager.executor.mark_run_failed_on_job_failure",
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


import re

# The "FAIL:/FAIL/ERROR:/ERROR" summary headers (from unittest's printErrors and
# our own _write_errors_to_stream fallback) name the test as
# "method (module.Class.method)" with the dotted path at the very end of the line.
# We parse those headers — not the live "✖ method (path) (1.2s)" lines, whose
# trailing "(1.2s)" makes the end-anchored path ambiguous.
_FAIL_HEADER_RE = re.compile(r"^(?:FAIL|ERROR)\b.*\(([\w.]+)\.(\w+)\)\s*$")


def _failed_tests_from_output(full_output: str) -> list[tuple[str, str]]:
	"""
	Extract (python_path, test_method) pairs for tests that failed or errored.

	Reads the run's saved console output and keeps the "FAIL …"/"ERROR …" summary
	headers, parsing the dotted "module.Class.method" from the trailing parens. The
	part before the class is the test module's python_path — what Testcase stores.
	Returns de-duplicated pairs in first-seen order.
	"""
	pairs: list[tuple[str, str]] = []
	seen: set[tuple[str, str]] = set()
	for raw in (full_output or "").splitlines():
		m = _FAIL_HEADER_RE.match(raw.strip())
		if not m:
			continue
		# group(1) = "module.Class" (path up to and incl. the class); strip the class.
		python_path = m.group(1).rsplit(".", 1)[0]
		method = m.group(2)
		key = (python_path, method)
		if key not in seen:
			seen.add(key)
			pairs.append(key)
	return pairs


@frappe.whitelist()
def get_failed_tests(run_name: str) -> dict:
	"""
	How many failed/errored tests in a run can be re-run (used to enable the UI button).

	Returns ``{"count": N}`` — the number of distinct failed/errored tests from the
	run's output that resolve to a known Testcase record.
	"""
	_guard()
	full_output = frappe.db.get_value("Testcase Run", run_name, "full_output") or ""
	pairs = _failed_tests_from_output(full_output)
	return {"count": len(_resolve_testcases(pairs))}


def _resolve_testcases(pairs: list[tuple[str, str]]) -> list[str]:
	"""Map (python_path, test_method) pairs to Testcase names, dropping unknowns."""
	if not pairs:
		return []
	tc = frappe.qb.DocType("Testcase")
	names: list[str] = []
	for python_path, method in pairs:
		row = (
			frappe.qb.from_(tc)
			.select(tc.name)
			.where((tc.python_path == python_path) & (tc.test_method == method))
			.limit(1)
			.run(pluck=True)
		)
		if row:
			names.append(row[0])
	# De-dup while preserving order (a method could appear twice across modules).
	return list(dict.fromkeys(names))


@frappe.whitelist()
def rerun_failed(run_name: str, background: int | str | bool = 1) -> dict:
	"""
	Re-run only the failed and errored tests from a previous run, as one batch.

	Parses the original run's output for failing tests, resolves them to Testcase
	records, and launches a fresh batch run (default: background/realtime so the UI
	can stream it). Returns the new run details, including ``run_name`` so the caller
	can navigate straight to it. Throws if nothing re-runnable is found.
	"""
	_guard()
	full_output = frappe.db.get_value("Testcase Run", run_name, "full_output") or ""
	pairs = _failed_tests_from_output(full_output)
	test_cases = _resolve_testcases(pairs)
	if not test_cases:
		frappe.throw("No failed or errored tests found to re-run.")
	return run_test_batch(test_cases, background=background)


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
# UI (Cypress) test execution
# ---------------------------------------------------------------------------


@frappe.whitelist()
def run_ui_test(test_case: str) -> dict:
	"""Run a single UI (Cypress) spec in the background.

	UI runs always go to the background: they boot a real browser and take
	minutes, so they must never block the request. The job streams Cypress
	output to the live console like a Python run. Returns ``run_name``/``task_id``
	for the UI to subscribe to realtime events.
	"""
	_guard()
	tc = frappe.db.get_value(
		"Testcase", test_case, ["app", "test_method", "test_file", "test_kind"], as_dict=True
	)
	if not tc or tc.test_kind != "UI":
		frappe.throw(frappe._("This test case is not a UI spec."))

	run = frappe.new_doc("Testcase Run")
	run.test_case = test_case
	run.app = tc.app
	run.test_method = f"UI: {tc.test_file or tc.test_method}"
	run.reference_type = "UI"
	run.run_scope = "UI Spec"
	run.total_tests = 1
	run.site = frappe.local.site
	run.triggered_by = frappe.session.user
	run.status = "Pending"
	run.realtime = 1
	run.insert(ignore_permissions=True)
	# Commit the run row before enqueuing so the worker can read it immediately.
	# Mirrors run_test_case.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

	frappe.enqueue(
		"testcase_manager.testcase_manager.ui_executor.execute_ui_test_job",
		queue="long",  # browser runs are slow → long queue / timeout
		timeout=3600,
		job_id=f"tc_run_{run.name}",
		on_failure="testcase_manager.testcase_manager.executor.mark_run_failed_on_job_failure",
		run_name=run.name,
	)
	return {"run_name": run.name, "task_id": run.name, "background": True}


@frappe.whitelist()
def sync_ui_specs(app: str | None = None) -> dict:
	"""Discover Cypress UI specs (``test_kind = UI``), scoped to *app* if given."""
	_guard()
	from testcase_manager.testcase_manager.ui_discovery import discover_all_ui_specs

	if app and app.strip():
		return {"status": "ok", **discover_all_ui_specs(app_name=app.strip())}

	frappe.enqueue(
		"testcase_manager.testcase_manager.ui_discovery.discover_all_ui_specs",
		queue="long",
		timeout=600,
		job_id="tc_ui_sync",
	)
	return {"status": "queued", "message": "Full UI sync queued in background"}


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


# ---------------------------------------------------------------------------
# Document profiler (Feature 2): profile one save/submit without persisting.
# ---------------------------------------------------------------------------


@frappe.whitelist()
def profile_document(doctype: str, name: str, action: str = "insert") -> dict:
	"""Profile a single document action (insert/submit) and roll it back.

	Returns the cProfile bucketed summary + raw table (``profile_data``) plus the
	echoed inputs and any error from the action. Nothing is written to disk — the
	action runs inside a savepoint that is always rolled back.
	"""
	_guard()
	from testcase_manager.testcase_manager.profiling import profile_document_action

	return profile_document_action(doctype, name, action)


@frappe.whitelist()
def get_profileable_doctypes(search: str | None = None) -> list[str]:
	"""DocTypes a user can pick to profile: non-child, non-single, with records.

	Child tables and Single doctypes have no standalone insert/submit to profile,
	so they're excluded. Filtered by *search* (substring) for the picker.
	"""
	_guard()
	filters: dict = {"istable": 0, "issingle": 0}
	if search:
		filters["name"] = ["like", f"%{search}%"]
	rows = frappe.get_all("DocType", filters=filters, pluck="name", order_by="name", limit=50)
	return rows
