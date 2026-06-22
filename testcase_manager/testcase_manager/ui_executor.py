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
	"""Return the GRAND-TOTAL (total, passed, failed, pending) across all specs.

	Cypress prints a per-spec labelled "(Results)" block (Tests:/Passing:/…) — one
	PER SPEC, with NO labelled grand total. The single source of the grand total is
	the final "(Run Finished)" spec-table grid, which lists one row per spec:

	    ✔  assignment_rule.js   00:28   1   1   -   -   -
	    ✔  control_attach.js    00:42   7   7   -   -   -

	So we sum those per-spec grid rows. Summing the grid (not reading the last
	labelled block) is correct for both single- and multi-spec runs. When the grid
	is absent (a crash before any spec ran), we fall back to the labelled blocks.
	"""

	out = output or ""

	def _n(v: str) -> int:
		return 0 if v == "-" else int(v)

	# Primary: sum the per-spec rows of the final spec-table grid (the grand total).
	rows = list(_GRID_ROW_RE.finditer(out))
	if rows:
		total = sum(_n(m.group("tests")) for m in rows)
		passed = sum(_n(m.group("passing")) for m in rows)
		failed = sum(_n(m.group("failing")) for m in rows)
		pending = sum(_n(m.group("pending")) for m in rows)
		return total, passed, failed, pending

	# Fallback: no grid (e.g. crash before the run-finished table). Sum the labelled
	# per-spec (Results) blocks instead.
	def _sum(rx) -> int:
		return sum(int(v) for v in rx.findall(out))

	return _sum(_TESTS_RE), _sum(_PASSING_RE), _sum(_FAILING_RE), _sum(_PENDING_RE)


def execute_ui_test_job(run_name: str, test_cases: list[str] | None = None) -> None:
	"""Background job: run one or more Cypress specs in a SINGLE run, stream output.

	*test_cases* is the list of Testcase names to run (a single-spec run passes one;
	a multi-select passes several). They all execute in one Cypress invocation —
	mirroring the Python tier, where a multi-selection is one batch job, not N jobs.
	Falls back to the run's anchor ``test_case`` when *test_cases* isn't given.
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
		names = list(test_cases) if test_cases else [run_doc.test_case]
		# Resolve each selected spec to (app, spec path). All specs belong to one app
		# (the runner only lets you select within a single app's list).
		specs = []
		app = run_doc.app
		for name in names:
			tc = frappe.db.get_value("Testcase", name, ["app", "test_file_path"], as_dict=True)
			if tc and tc.test_file_path:
				specs.append(tc.test_file_path)
				app = tc.app

		# Serialize with Python runs too: a UI run boots a browser against the same
		# site, so overlapping a heavy Python run only fights for the DB. Reuse the
		# global run-lock for consistent, deadlock-free behaviour across both tiers.
		with _run_lock(stream):
			output, returncode = _run_cypress(app, specs, stream)

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
		log.app = app
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
		# Login is allowed but the credentials were rejected. We provision the test
		# user + its password ourselves each run, so a 401 here usually means
		# password login is restricted by some other policy (LDAP/SSO-only, social
		# login enforced) or the spec logs in as a different user than our test user.
		stream.write(
			"\n"
			"────────────────────────────────────────────────────────\n"
			"NOTE: Cypress login was rejected (401 on /api/method/login).\n"
			f"  We auto-provision the test user '{_CYPRESS_TEST_USER}' with a fresh\n"
			"  password each run, so the credentials should be valid. A 401 here\n"
			"  usually means the site enforces SSO / social login only, or the spec\n"
			"  logs in as a different user. Check the site's login policy.\n"
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


# Frappe's cypress.config.js logs in as this user (`testUser`); cy.login() sends
# whatever password we pass as CYPRESS_adminPassword. We provision this user
# ourselves so we never depend on a plaintext `admin_password` in site_config.
_CYPRESS_TEST_USER = "frappe@example.com"


def provision_cypress_user() -> str:
	"""Create/reuse the dedicated Cypress login user and return a FRESH password.

	Security: we do NOT read any stored password (passwords are one-way hashed and
	can't be retrieved), and we do NOT keep `admin_password` in site config. Instead
	we (re)set a freshly generated random password on a dedicated test user on every
	run, hand it to Cypress via an env var only, and never persist or log it. The
	user is created once (full rights, so the Frappe specs that need admin actions
	work) and reused on later runs; only its password rotates.

	Returned to the caller so it can be exported as CYPRESS_adminPassword. Also
	callable from CI via `bench execute` for the same purpose. This is a
	dev-testing-only app — the user is a test fixture, not a real account.
	"""
	from frappe.utils.password import update_password

	password = frappe.generate_hash(length=24)

	if not frappe.db.exists("User", _CYPRESS_TEST_USER):
		# Create the user once, with full rights so admin-level Frappe specs
		# (create DocType, etc.) succeed.
		user = frappe.new_doc("User")
		user.email = _CYPRESS_TEST_USER
		user.first_name = "Cypress"
		user.last_name = "Test"
		user.send_welcome_email = 0
		user.append("roles", {"role": "System Manager"})
		user.insert(ignore_permissions=True)

	# Rotate the password by writing the auth hash directly (no User .save(), so no
	# optimistic-lock TimestampMismatchError when queued specs provision in turn).
	update_password(_CYPRESS_TEST_USER, password)
	# Commit so the subprocess (separate connection) sees the new password.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	return password


def _ensure_cypress_test_user(stream: "RealtimeLineStream") -> str:
	"""Provision the Cypress test user for a run and note it in the console."""
	existed = frappe.db.exists("User", _CYPRESS_TEST_USER)
	password = provision_cypress_user()
	if not existed:
		stream.write(f"• Created Cypress test user {_CYPRESS_TEST_USER} (System Manager).\n")
		stream.flush()
	return password


def _run_cypress(app: str, specs: list[str], stream: "RealtimeLineStream") -> tuple[str, int]:
	"""Spawn `bench run-ui-tests` for one or more specs and stream stdout into *stream*.

	Returns (full_output, returncode). All *specs* (paths relative to the app
	source root) run in ONE Cypress invocation via a comma-separated ``--spec`` —
	the UI equivalent of the Python tier's single-job batch.
	"""
	site = frappe.local.site

	# Provision the login credential ourselves (no plaintext password in config).
	test_password = _ensure_cypress_test_user(stream)

	cmd = [
		"bench",
		"--site",
		site,
		"run-ui-tests",
		app,
		"--headless",
		"--browser",
		"chrome",
		# Cypress accepts a comma-separated spec list, so one invocation runs the
		# whole selection in a single browser session (one shared setup), exactly
		# like run_test_batch runs many Python tests in one job.
		"--spec",
		",".join(specs),
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
	# CYPRESS_adminPassword is the per-run password for the test user above; it
	# overrides whatever run-ui-tests would read from site config, so no plaintext
	# admin_password is needed. Passed via env only — never written or logged.
	proc = subprocess.Popen(
		cmd,
		cwd=_bench_path(),
		stdout=subprocess.PIPE,
		stderr=subprocess.STDOUT,
		text=True,
		bufsize=1,  # line-buffered → lines reach the console as they're produced
		env={
			**os.environ,
			"FORCE_COLOR": "0",  # plain text; we strip ANSI anyway
			"CYPRESS_adminPassword": test_password,
		},
	)

	try:
		for line in proc.stdout:  # blocks until each newline, streaming live
			# Belt-and-suspenders: if Cypress ever dumps the failed login request
			# body (which contains pwd), redact the password before it reaches the
			# console or the saved run output.
			stream.write(_redact(_strip_ansi(line), test_password))
	finally:
		proc.stdout.close()
		returncode = proc.wait()

	return stream.getvalue(), returncode


def _redact(text: str, secret: str) -> str:
	"""Replace any occurrence of *secret* in *text* with a placeholder."""
	if secret and secret in text:
		return text.replace(secret, "***")
	return text
