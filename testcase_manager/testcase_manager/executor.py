"""
Test execution engine.

Runs Frappe tests in-process using frappe's own TestRunner with a
realtime-streaming output stream, then persists a Test Case Log.

Key design:
- RealtimeLineStream is passed as the TestRunner's stream (captures ✔/✖ symbols).
- sys.stdout is ALSO redirected to the stream during the run because Frappe's
  printErrors() uses click.echo() which writes to stdout, not to self.stream.
"""

import re
import sys
import time

import frappe
from frappe.utils import now_datetime

# Matches ANSI escape sequences (colour/style codes) emitted by the test runner.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _strip_ansi(text: str) -> str:
	return _ANSI_RE.sub("", text or "")


def _sum_exec_time(all_results: list) -> float:
	"""Actual test execution time across suites (the unittest 'Ran in' window)."""
	return round(sum(getattr(r, "_tc_exec_time", 0) or 0 for r in all_results), 3)


# ---------------------------------------------------------------------------
# Realtime output stream
# ---------------------------------------------------------------------------


class RealtimeLineStream:
	"""
	File-like object given to TestRunner as its output stream.

	Each complete text line is:
	  1. Published immediately via frappe.publish_realtime (live console).
	  2. Accumulated internally for log storage.
	"""

	def __init__(self, task_id: str, run_name: str) -> None:
		self.task_id = task_id
		self.run_name = run_name
		self._buf = ""
		self._lines: list[str] = []
		self.encoding = "utf-8"
		self.errors = "replace"

	# ── Standard stream interface ─────────────────────────────────────────

	def isatty(self) -> bool:
		# Not a terminal → callers (click, frappe deprecation_dumpster, etc.)
		# won't try to emit ANSI escape sequences.
		return False

	def writable(self) -> bool:
		return True

	def readable(self) -> bool:
		return False

	def seekable(self) -> bool:
		return False

	@property
	def closed(self) -> bool:
		return False

	def fileno(self) -> int:
		import io

		raise io.UnsupportedOperation("fileno")

	def write(self, text: str) -> int:
		self._buf += text
		while "\n" in self._buf:
			line, self._buf = self._buf.split("\n", 1)
			self._emit(line)
		return len(text)

	def flush(self) -> None:
		if self._buf:
			self._emit(self._buf)
			self._buf = ""

	def _emit(self, line: str) -> None:
		# Strip ANSI at the source so both the live stream and the stored
		# output are clean, readable plain text.
		line = _strip_ansi(line)
		self._lines.append(line)
		_publish(self.task_id, "test_output", {"run_name": self.run_name, "line": line})

	def getvalue(self) -> str:
		return "\n".join(self._lines)


# ---------------------------------------------------------------------------
# Background job entry point
# ---------------------------------------------------------------------------


def execute_test_case_job(run_name: str) -> None:
	"""
	Background job executed by RQ.

	Streams test output to the UI via realtime events, then saves a
	Test Case Log record with the full output and summary counts.
	"""
	task_id = run_name

	frappe.db.set_value(
		"Testcase Run",
		run_name,
		{"status": "Running", "start_time": now_datetime()},
		update_modified=False,
	)
	frappe.db.commit()

	_publish(task_id, "test_started", {"run_name": run_name, "status": "Running"})

	start_ts = time.monotonic()
	stream = RealtimeLineStream(task_id, run_name)

	try:
		run_doc = frappe.get_doc("Testcase Run", run_name)
		tc = frappe.get_doc("Testcase", run_doc.test_case)
		run_scope = run_doc.run_scope or "Method"

		all_results = _run_tests_in_process(tc, run_scope, stream)

		stream.flush()
		duration = round(time.monotonic() - start_ts, 3)
		exec_time = _sum_exec_time(all_results)
		full_output = stream.getvalue()

		total_passed = sum(r.testsRun - len(r.failures) - len(r.errors) for r in all_results)
		total_failed = sum(len(r.failures) for r in all_results)
		total_errors = sum(len(r.errors) for r in all_results)

		if total_failed or total_errors:
			status = "Failed"
		elif all_results:
			status = "Passed"
		else:
			status = "Error"

		result_summary = f"Passed: {total_passed}, Failed: {total_failed}, Errors: {total_errors}"

		traceback_text = _strip_ansi(
			"\n\n".join("\n".join(tb for _, tb in (r.failures + r.errors)) for r in all_results).strip()
		)

		frappe.db.set_value(
			"Testcase Run",
			run_name,
			{
				"status": status,
				"end_time": now_datetime(),
				"duration": duration,
				"exec_time": exec_time,
				"result": result_summary,
				"full_output": full_output,
				"traceback": traceback_text,
			},
			update_modified=False,
		)

		log = frappe.new_doc("Testcase Log")
		log.run_reference = run_name
		log.test_case = run_doc.test_case
		log.test_method = tc.test_method
		log.app = tc.app
		log.full_output = full_output
		log.traceback = traceback_text
		log.passed_count = total_passed
		log.failed_count = total_failed
		log.error_count = total_errors
		log.duration = duration
		log.execution_status = status
		log.insert(ignore_permissions=True)
		frappe.db.commit()

		_publish(
			task_id,
			"test_completed",
			{
				"run_name": run_name,
				"status": status,
				"log_name": log.name,
				"summary": result_summary,
				"duration": duration,
				"passed": total_passed,
				"failed": total_failed,
				"errors": total_errors,
				"full_output": full_output,
				"traceback": traceback_text,
			},
		)

	except Exception as exc:
		import traceback as _tb

		err_text = _tb.format_exc()
		frappe.log_error(f"Test execution failed for run {run_name}: {exc}")

		stream.flush()
		full_output = stream.getvalue() + "\n\nFATAL ERROR:\n" + err_text

		frappe.db.set_value(
			"Testcase Run",
			run_name,
			{
				"status": "Error",
				"end_time": now_datetime(),
				"result": str(exc),
				"full_output": full_output,
				"traceback": err_text,
			},
			update_modified=False,
		)
		frappe.db.commit()
		_publish(
			task_id,
			"test_completed",
			{
				"run_name": run_name,
				"status": "Error",
				"error": str(exc),
				"full_output": full_output,
				"traceback": err_text,
			},
		)


def execute_test_batch_job(run_name: str, test_cases: list[str]) -> None:
	"""
	Run a batch of selected tests under ONE environment setup.

	A single Testcase Run (``run_name``) anchors the batch; the run's
	full_output/counts reflect all *test_cases*. This avoids paying the multi-
	second per-test setup cost N times for a multi-test selection.
	"""
	task_id = run_name

	frappe.db.set_value(
		"Testcase Run",
		run_name,
		{"status": "Running", "start_time": now_datetime()},
		update_modified=False,
	)
	frappe.db.commit()
	_publish(task_id, "test_started", {"run_name": run_name, "status": "Running"})

	start_ts = time.monotonic()
	stream = RealtimeLineStream(task_id, run_name)

	try:
		tcs = [frappe.get_doc("Testcase", name) for name in test_cases]
		all_results = _run_batch_in_process(tcs, stream)

		stream.flush()
		duration = round(time.monotonic() - start_ts, 3)
		exec_time = _sum_exec_time(all_results)
		full_output = stream.getvalue()

		total_passed = sum(r.testsRun - len(r.failures) - len(r.errors) for r in all_results)
		total_failed = sum(len(r.failures) for r in all_results)
		total_errors = sum(len(r.errors) for r in all_results)

		if total_failed or total_errors:
			status = "Failed"
		elif all_results:
			status = "Passed"
		else:
			status = "Error"

		result_summary = f"Passed: {total_passed}, Failed: {total_failed}, Errors: {total_errors}"
		traceback_text = _strip_ansi(
			"\n\n".join("\n".join(tb for _, tb in (r.failures + r.errors)) for r in all_results).strip()
		)

		frappe.db.set_value(
			"Testcase Run",
			run_name,
			{
				"status": status,
				"end_time": now_datetime(),
				"duration": duration,
				"exec_time": exec_time,
				"result": result_summary,
				"full_output": full_output,
				"traceback": traceback_text,
			},
			update_modified=False,
		)

		log = frappe.new_doc("Testcase Log")
		log.run_reference = run_name
		log.test_case = tcs[0].name if tcs else None
		log.app = tcs[0].app if tcs else None
		log.full_output = full_output
		log.traceback = traceback_text
		log.passed_count = total_passed
		log.failed_count = total_failed
		log.error_count = total_errors
		log.duration = duration
		log.execution_status = status
		log.insert(ignore_permissions=True)
		frappe.db.commit()

		_publish(
			task_id,
			"test_completed",
			{
				"run_name": run_name,
				"status": status,
				"log_name": log.name,
				"summary": result_summary,
				"duration": duration,
				"passed": total_passed,
				"failed": total_failed,
				"errors": total_errors,
				"full_output": full_output,
				"traceback": traceback_text,
			},
		)

	except Exception as exc:
		import traceback as _tb

		err_text = _tb.format_exc()
		frappe.log_error(f"Batch test execution failed for run {run_name}: {exc}")
		stream.flush()
		full_output = stream.getvalue() + "\n\nFATAL ERROR:\n" + err_text
		frappe.db.set_value(
			"Testcase Run",
			run_name,
			{
				"status": "Error",
				"end_time": now_datetime(),
				"result": str(exc),
				"full_output": full_output,
				"traceback": err_text,
			},
			update_modified=False,
		)
		frappe.db.commit()
		_publish(
			task_id,
			"test_completed",
			{"run_name": run_name, "status": "Error", "error": str(exc), "full_output": full_output},
		)


# ---------------------------------------------------------------------------
# In-process test runner
# ---------------------------------------------------------------------------


def _streaming_result_class():
	"""
	A TestResult that announces each test *before* it runs.

	Frappe's stock TestResult only writes a line once a test finishes
	(``✔ name``/``✖ name``), so a slow test looks like a hang. This subclass
	emits a "▸ running name…" line in ``startTest`` so the UI shows which test
	is currently executing, in real time. Built lazily so the import of
	frappe.testing happens inside the worker.
	"""
	from frappe.testing.result import TestResult

	class StreamingTestResult(TestResult):
		def startTest(self, test):
			super().startTest(test)
			method = self.getTestMethodName(test)
			self.stream.write(f"  ▸ running {method} …\n")
			self.stream.flush()

	return StreamingTestResult


def _run_tests_in_process(tc, run_scope: str, stream: "RealtimeLineStream") -> list:
	"""
	Run Frappe tests in-process using the same TestRunner frappe uses.
	Returns a list of unittest.TestResult objects.

	sys.stdout is temporarily redirected to *stream* so that click.echo()
	calls inside Frappe's TestResult.printErrors() also reach the UI.
	"""
	from frappe.testing import (
		TestConfig,
		TestRunner,
		discover_all_tests,
		discover_doctype_tests,
		discover_module_tests,
	)
	from frappe.testing.environment import _cleanup_after_tests, _initialize_test_environment

	scope = (run_scope or "Method").strip()
	cfg_tests: tuple[str, ...] = (tc.test_method,) if scope == "Method" else ()

	config = TestConfig(tests=cfg_tests)
	site = frappe.local.site

	# Safe in background job — frappe.init() returns early if already init'd;
	# this still sets toggle_test_mode(True) which integration tests require.
	_initialize_test_environment(site, config)

	runner = TestRunner(stream=stream, verbosity=2, cfg=config, resultclass=_streaming_result_class())

	# Long-lived workers cache imported test modules in sys.modules, so edits to
	# a test file on disk would be ignored (old bytecode keeps running) until the
	# process restarts. Drop the relevant modules first so discovery re-imports
	# the current source — a saved change is reflected on the very next run.
	if scope in ("Method", "File", "DocType", ""):
		_invalidate_test_module(tc.python_path)

	if scope in ("Method", "File"):
		discover_module_tests([tc.python_path], runner, tc.app)
	elif scope == "DocType" and tc.reference_doctype:
		discover_doctype_tests([tc.reference_doctype], runner, tc.app)
	elif scope == "App":
		discover_all_tests([tc.app], runner)
	else:
		discover_module_tests([tc.python_path], runner, tc.app)

	return _drive_runner(runner, stream)


def _run_batch_in_process(tcs: list, stream: "RealtimeLineStream") -> list:
	"""
	Run many test methods in a SINGLE runner so the expensive environment setup
	(`_initialize_test_environment`, `before_tests` hooks, global dependency
	records) happens once for the whole batch instead of once per test.

	*tcs* is a list of Testcase docs. All their methods are collected into one
	TestConfig; their modules are discovered into one runner.
	"""
	from frappe.testing import TestConfig, TestRunner, discover_module_tests
	from frappe.testing.environment import _initialize_test_environment

	site = frappe.local.site
	methods = tuple(dict.fromkeys(tc.test_method for tc in tcs))  # de-dup, keep order
	python_paths = list(dict.fromkeys(tc.python_path for tc in tcs))
	app = tcs[0].app

	config = TestConfig(tests=methods)
	_initialize_test_environment(site, config)

	runner = TestRunner(stream=stream, verbosity=2, cfg=config, resultclass=_streaming_result_class())

	# Pick up on-disk edits (see _invalidate_test_module).
	for p in python_paths:
		_invalidate_test_module(p)

	discover_module_tests(python_paths, runner, app)

	return _drive_runner(runner, stream)


def _drive_runner(runner, stream: "RealtimeLineStream") -> list:
	"""Run a prepared TestRunner, streaming output. Shared by single + batch."""
	from frappe.testing.environment import _cleanup_after_tests

	results: list = []

	# Redirect sys.stdout → stream so click.echo() calls (used by
	# Frappe's TestResult.printErrors) are captured and streamed to the UI.
	_original_stdout = sys.stdout
	sys.stdout = stream

	try:
		for app_name, category, suite in runner.iterRun():
			count = suite.countTestCases()
			stream.write(f"\nRunning {count} {category} tests for {app_name}\n\n")
			# Wall-clock around just the suite run = unittest's "Ran N tests in X.Xs"
			# (the actual test execution time, excluding env setup/teardown).
			_run_start = time.monotonic()
			result = runner.run(suite)
			result._tc_exec_time = time.monotonic() - _run_start
			results.append(result)

			# Safety fallback: if errors/failures weren't captured via click.echo,
			# write them explicitly to the stream from the result objects.
			_write_errors_to_stream(stream, result)
	finally:
		sys.stdout = _original_stdout
		_cleanup_after_tests()

	return results


def _invalidate_test_module(python_path: str) -> None:
	"""
	Evict a test module (and the other modules in its doctype/report package)
	from ``sys.modules`` so the next import reads the current file from disk.

	Example: for ``lending.loan_management.doctype.loan_repayment.test_loan_repayment``
	we drop everything under ``lending.loan_management.doctype.loan_repayment`` —
	the test file *and* the controller it imports — so edits to either take
	effect on the next run without restarting the worker.
	"""
	import importlib
	import sys

	if not python_path:
		return

	# Package prefix = the test module's parent (the doctype/report folder).
	pkg = python_path.rsplit(".", 1)[0] if "." in python_path else python_path

	for name in list(sys.modules):
		if name == python_path or name == pkg or name.startswith(pkg + "."):
			sys.modules.pop(name, None)

	importlib.invalidate_caches()


def _write_errors_to_stream(stream: "RealtimeLineStream", result) -> None:
	"""
	Explicitly write any failure/error tracebacks to the stream.

	Frappe's TestResult.printErrors() uses click.echo() which goes to stdout.
	We redirect stdout, but as a belt-and-suspenders fallback, also write
	directly — deduplication is handled client-side (stripAnsi + display).
	"""
	sep1 = "=" * 70
	sep2 = "-" * 70

	for test_name, err_str in result.errors:
		if str(err_str) not in stream.getvalue():
			stream.write(f"\n{sep1}\n")
			stream.write(f"ERROR: {test_name}\n")
			stream.write(f"{sep2}\n")
			stream.write(f"{err_str}\n")

	for test_name, err_str in result.failures:
		if str(err_str) not in stream.getvalue():
			stream.write(f"\n{sep1}\n")
			stream.write(f"FAIL: {test_name}\n")
			stream.write(f"{sep2}\n")
			stream.write(f"{err_str}\n")


# ---------------------------------------------------------------------------
# Realtime helper
# ---------------------------------------------------------------------------


def _publish(task_id: str, event: str, message: dict) -> None:
	try:
		frappe.publish_realtime(event=event, message=message, task_id=task_id)
	except Exception:
		pass
