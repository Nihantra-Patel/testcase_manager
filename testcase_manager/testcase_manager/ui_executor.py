"""
UI (Cypress) test execution engine.

The Python engine runs ``unittest`` in-process. UI tests can't work that way:
Cypress is a Node + Chromium subprocess that needs a live web server and emits a
JSON report instead of ``unittest.TestResult`` objects. So a UI run is:

    spawn `bench run-ui-tests <app> --headless --spec <file>`
      → stream its stdout into the existing RealtimeLineStream (live console)
      → parse the result counts from the output
      → persist a Testcase Run + Testcase Log exactly like the Python jobs.

We shell out to Frappe's own ``bench run-ui-tests`` rather than calling Cypress
directly, so site URL, admin password and the Cypress plugin install are handled
by the framework (see frappe/commands/testing.py:run_ui_tests).
"""

import os
import re
import subprocess
import time

import frappe
from frappe.utils import now_datetime

from testcase_manager.testcase_manager.executor import (
	RealtimeLineStream,
	_ensure_scheduler_enabled,
	_publish,
	_run_lock,
	_strip_ansi,
	live_output_key,
)

# Cypress prints a per-spec "(Results)" block with labelled lines
# (Tests:/Passing:/Failing:/Pending:) for normal runs; we parse those first.
_PASSING_RE = re.compile(r"\bPassing:\s+(\d+)", re.IGNORECASE)
_FAILING_RE = re.compile(r"\bFailing:\s+(\d+)", re.IGNORECASE)
_PENDING_RE = re.compile(r"\bPending:\s+(\d+)", re.IGNORECASE)
_TESTS_RE = re.compile(r"\bTests:\s+(\d+)", re.IGNORECASE)

# When a `before all` hook fails, the labelled block is missing but the final
# spec-table grid row still carries the numbers, e.g.:
#   "✖  assignment_rule.js   00:01   1   -   1   -   -"
# i.e. <mark> <spec> <duration> <tests> <passing> <failing> <pending> <skipped>,
# with "-" meaning zero. Parse that as a fallback so counts stay accurate.
_GRID_ROW_RE = re.compile(
	r"[✔✖]\s+\S+\.js\s+\d+:\d+\s+"
	r"(?P<tests>\d+|-)\s+(?P<passing>\d+|-)\s+(?P<failing>\d+|-)\s+(?P<pending>\d+|-)",
)


def _bench_path() -> str:
	"""Absolute path to the bench root (…/frappe-bench), derived from the site path."""
	# frappe.utils.get_bench_path() returns the bench dir; fall back to walking up
	# from sites_path if that helper is unavailable.
	try:
		return frappe.utils.get_bench_path()
	except Exception:
		return os.path.abspath(os.path.join(frappe.get_site_path(), "..", ".."))


def _parse_cypress_counts(output: str) -> tuple[int, int, int, int]:
	"""Return (total, passed, failed, pending) parsed from Cypress' run summary.

	Cypress prints a final "(Run Finished)" table with Tests/Passing/Failing/Pending.
	When a run dies before that table (compile error, server down) all counts are 0,
	which the caller maps to an Error status.
	"""

	out = output or ""

	# Sum across all spec blocks: Cypress prints one summary per spec plus a grand
	# total at the very end. The grand total is the LAST occurrence of each key.
	def _last(rx) -> int:
		vals = rx.findall(out)
		return int(vals[-1]) if vals else 0

	total = _last(_TESTS_RE)
	passed = _last(_PASSING_RE)
	failed = _last(_FAILING_RE)
	pending = _last(_PENDING_RE)

	# Fallback: no labelled "(Results)" block (e.g. a hook failed). Sum the
	# spec-table grid rows, treating "-" as 0.
	if not total:

		def _n(v: str) -> int:
			return 0 if v == "-" else int(v)

		rows = list(_GRID_ROW_RE.finditer(out))
		if rows:
			total = sum(_n(m.group("tests")) for m in rows)
			passed = sum(_n(m.group("passing")) for m in rows)
			failed = sum(_n(m.group("failing")) for m in rows)
			pending = sum(_n(m.group("pending")) for m in rows)

	return total, passed, failed, pending


def execute_ui_test_job(run_name: str) -> None:
	"""Background job: run one Cypress spec, stream output, persist results.

	Mirrors ``execute_test_case_job`` for the Python tier so History, the live
	console and status badges behave identically.
	"""
	task_id = run_name

	frappe.db.set_value(
		"Testcase Run",
		run_name,
		{"status": "Running", "start_time": now_datetime()},
		update_modified=False,
	)
	# Background job (no request transaction); commit so the worker's status update
	# is visible to the polling UI immediately. Mirrors executor.py.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	_publish(task_id, "test_started", {"run_name": run_name, "status": "Running"})

	start_ts = time.monotonic()
	stream = RealtimeLineStream(task_id, run_name)

	try:
		run_doc = frappe.db.get_value("Testcase Run", run_name, ["test_case", "app"], as_dict=True)
		tc = frappe.db.get_value(
			"Testcase", run_doc.test_case, ["app", "test_file", "test_file_path"], as_dict=True
		)

		# Serialize with Python runs too: a UI run boots a browser against the same
		# site, so overlapping a heavy Python run only fights for the DB. Reuse the
		# global run-lock for consistent, deadlock-free behaviour across both tiers.
		with _run_lock(stream):
			output, returncode = _run_cypress(tc, stream)

		_hint_common_failures(output, stream)
		stream.flush()
		duration = round(time.monotonic() - start_ts, 3)
		total, passed, failed, pending = _parse_cypress_counts(output)

		# The Cypress process exit code is authoritative: it is non-zero whenever any
		# test (or hook) fails, and zero only when everything passed. The parsed
		# counts feed the summary but must NOT decide pass/fail on their own — a
		# `before all` hook failure prints a spec-table grid without the labelled
		# "Failing: N" line, so count-parsing alone wrongly read that as a pass.
		if returncode != 0:
			# A genuine test failure prints a results table (total > 0); a crash
			# before any test runs (bad binary, server down) produces none.
			status = "Failed" if total else "Error"
			# If counts didn't surface a failure but the run failed, reflect that.
			if status == "Failed" and not failed:
				failed = max(total - passed - pending, 1)
		else:
			status = "Passed"

		# Use the same "Passed/Failed/Errors" shape as the Python tier so the UI's
		# parseCounts() and the console footer tally read it uniformly. Cypress has
		# no separate "errors" bucket (a failure is a failure), so errors=0; pending
		# is appended for detail only.
		result_summary = f"Passed: {passed}, Failed: {failed}, Errors: 0"
		if pending:
			result_summary += f", Pending: {pending}"
		full_output = stream.getvalue()

		frappe.db.set_value(
			"Testcase Run",
			run_name,
			{
				"status": status,
				"end_time": now_datetime(),
				"duration": duration,
				"exec_time": duration,
				"result": result_summary,
				"full_output": full_output,
			},
			update_modified=False,
		)

		log = frappe.new_doc("Testcase Log")
		log.run_reference = run_name
		log.test_case = run_doc.test_case
		log.app = tc.app
		log.full_output = full_output
		log.passed_count = passed
		log.failed_count = failed
		log.error_count = 0
		log.duration = duration
		log.execution_status = status
		log.insert(ignore_permissions=True)
		# Persist the finished run + log from the background worker. Mirrors executor.py.
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit

		_publish(
			task_id,
			"test_completed",
			{
				"run_name": run_name,
				"status": status,
				"log_name": log.name,
				"summary": result_summary,
				"duration": duration,
				"passed": passed,
				"failed": failed,
				"errors": 0,
				"full_output": full_output,
			},
		)

	except Exception as exc:
		import traceback as _tb

		err_text = _tb.format_exc()
		frappe.log_error(f"UI test execution failed for run {run_name}: {exc}")
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
		# Persist the error outcome from the background worker. Mirrors executor.py.
		frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
		_publish(
			task_id,
			"test_completed",
			{"run_name": run_name, "status": "Error", "error": str(exc), "full_output": full_output},
		)
	finally:
		_ensure_scheduler_enabled()
		try:
			from frappe.utils.background_jobs import get_redis_conn

			get_redis_conn().delete(live_output_key(run_name))
		except Exception:
			pass


def _hint_common_failures(output: str, stream: "RealtimeLineStream") -> None:
	"""Append a friendly explanation for well-known environment failures.

	The raw Cypress output is preserved verbatim (a PR author sees exactly the same
	failure); this only adds a trailing hint so the cause is obvious in the console.
	Counts/status are parsed from *output* before this runs, so hints never change
	the result.
	"""
	out = output or ""
	login_401 = "/api/method/login" in out and "401" in out
	if "Login with username and password is not allowed" in out:
		# Password login is explicitly disabled on the site.
		stream.write(
			"\n"
			"────────────────────────────────────────────────────────\n"
			"NOTE: Cypress could not log in (password login is disabled).\n"
			"  Every Frappe Cypress spec starts with cy.login(), which posts\n"
			"  a username + password. Enable it once on the test site:\n"
			"    System Settings -> uncheck 'Disable Username/Password Login',\n"
			"    or: bench --site <site> set-config disable_user_pass_login 0\n"
			"────────────────────────────────────────────────────────\n"
		)
		stream.flush()
	elif login_401:
		# Login is allowed but the credentials were rejected — almost always a
		# missing `admin_password` in the site config (run-ui-tests passes it to
		# cy.login() as CYPRESS_adminPassword), or a missing test user/fixture.
		stream.write(
			"\n"
			"────────────────────────────────────────────────────────\n"
			"NOTE: Cypress login was rejected (401 on /api/method/login).\n"
			"  Login is allowed, so the credentials are wrong. Most often the\n"
			"  site has no `admin_password` in its config — run-ui-tests passes\n"
			"  that to cy.login(). Check / set it:\n"
			"    bench --site <site> set-admin-password <password>\n"
			"  (the password must match what cy.login() uses — the Administrator\n"
			"  password). Also ensure the spec's test user/fixtures exist.\n"
			"────────────────────────────────────────────────────────\n"
		)
		stream.flush()

	# A corrupted / partially-downloaded Cypress binary, or one built for the
	# wrong CPU arch (e.g. an Intel build cached on an Apple-Silicon Mac), crashes
	# before any tests run. The fix is the same on every OS: clear the cache and
	# let `bench run-ui-tests` re-download the right binary automatically.
	binary_broken = (
		("Cannot find module" in out and "Cypress.app" in out)
		or "Failed downloading the Cypress binary" in out
		or ("Cypress verification" in out and "failed" in out.lower())
	)
	if binary_broken:
		stream.write(
			"\n"
			"────────────────────────────────────────────────────────\n"
			"NOTE: The Cypress binary looks broken or missing for this machine.\n"
			"  This is environment-only (often a stale cache, or an Intel build\n"
			"  cached on an Apple-Silicon Mac). Clear it and re-run; bench will\n"
			"  re-download the correct binary automatically:\n"
			"    rm -rf ~/.cache/Cypress ~/Library/Caches/Cypress\n"
			"    (then run the spec again)\n"
			"────────────────────────────────────────────────────────\n"
		)
		stream.flush()


def _run_cypress(tc, stream: "RealtimeLineStream") -> tuple[str, int]:
	"""Spawn `bench run-ui-tests` for one spec and stream its stdout into *stream*.

	Returns (full_output, returncode). The spec path stored on the Testcase
	(apps/<app>/…) is passed to ``--spec`` so Cypress runs only that file.
	"""
	site = frappe.local.site
	app = tc.app
	spec = tc.test_file_path

	cmd = [
		"bench",
		"--site",
		site,
		"run-ui-tests",
		app,
		"--headless",
		"--browser",
		"chrome",
		"--spec",
		spec,
		# Extra args after --spec are forwarded to the cypress CLI (see
		# run_ui_tests). The runner streams output live and saves it to the run,
		# so the .mp4 recording is redundant — disable it to save time and disk.
		"--config",
		"video=false",
	]

	stream.write(f"\n$ {' '.join(cmd)}\n\n")
	stream.flush()

	# Run from the bench root so the `bench` CLI resolves the site and apps. Merge
	# stderr into stdout so Cypress' progress (which it writes to both) all streams.
	proc = subprocess.Popen(
		cmd,
		cwd=_bench_path(),
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		bufsize=1,  # line-buffered → lines reach the console as they're produced
		env={**os.environ, "FORCE_COLOR": "0"},  # plain text; we strip ANSI anyway
	)

	try:
		for line in proc.stdout:  # blocks until each newline, streaming live
			stream.write(_strip_ansi(line))
	finally:
		proc.stdout.close()
		returncode = proc.wait()

	return stream.getvalue(), returncode
