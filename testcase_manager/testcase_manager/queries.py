"""
Read-only whitelisted endpoints that feed the Runner and History pages.

These only query Testcase / Testcase Run records — they never start a run or
mutate data — so they don't need the role gate the execution endpoints use.
Mutating / test-running endpoints live in ``api.py``.
"""

import frappe
from frappe.query_builder.functions import Count

# Cap on how many records a single list query may return (avoids a client asking
# for an unbounded page that could exhaust memory). The Runner loads a whole app's
# tests in one page, so this must comfortably exceed the largest app's test count.
MAX_PAGE_SIZE = 20000


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
	tc = frappe.qb.DocType("Testcase")

	# Equality filters (ANDed together).
	criterion = tc.status == "Active"
	if app and app.strip():
		criterion &= tc.app == app.strip()
	if reference_type and reference_type.strip():
		criterion &= tc.reference_type == reference_type.strip()
	if report and report.strip():
		criterion &= tc.report == report.strip()
	if reference_doctype and reference_doctype.strip():
		criterion &= tc.reference_doctype == reference_doctype.strip()

	# Free-text search across a few fields (ORed), combined with the filters above.
	if search and search.strip():
		like = f"%{search.strip()}%"
		criterion &= (
			tc.test_method.like(like)
			| tc.reference_doctype.like(like)
			| tc.report.like(like)
			| tc.python_path.like(like)
		)

	total = frappe.qb.from_(tc).select(Count("*")).where(criterion).run()[0][0]

	page = max(int(page), 1)
	page_size = min(max(int(page_size), 1), MAX_PAGE_SIZE)

	records = (
		frappe.qb.from_(tc)
		.select(
			tc.name,
			tc.app,
			tc.module,
			tc.reference_type,
			tc.reference_doctype,
			tc.report,
			tc.test_file,
			tc.test_method,
			tc.python_path,
			tc.status,
		)
		.where(criterion)
		.orderby(tc.app)
		.orderby(tc.module)
		.orderby(tc.test_method)
		.limit(page_size)
		.offset((page - 1) * page_size)
		.run(as_dict=True)
	)

	return {"total": total, "records": records}


@frappe.whitelist()
def get_installed_apps_list() -> list[str]:
	"""Return only apps that actually have discovered test cases (for filter dropdowns)."""
	tc = frappe.qb.DocType("Testcase")
	return (
		frappe.qb.from_(tc)
		.select(tc.app)
		.distinct()
		.where(tc.status == "Active")
		.orderby(tc.app)
		.run(pluck=True)
	)


@frappe.whitelist()
def get_app_logos() -> dict:
	"""
	Map each installed app → its logo URL (from the app's ``app_logo_url`` hook).

	Used to show real app icons in the History list. Apps without the hook are
	omitted so the UI can fall back to a generic icon.
	"""
	logos: dict = {}
	for app in frappe.get_installed_apps():
		url = frappe.get_hooks("app_logo_url", app_name=app)
		if url:
			logos[app] = url[-1]  # last wins, mirroring Frappe's hook resolution
	return logos


@frappe.whitelist()
def get_reference_options(app: str | None = None, reference_type: str | None = None) -> list[dict]:
	"""
	Return the distinct references (DocTypes and/or Reports) that actually have
	test cases, optionally scoped to a single app.

	Each item is ``{"value": name, "type": "DocType"|"Report"}``. When
	``reference_type`` is empty (the "All Types" filter), both DocTypes and Reports
	are returned so the dropdown isn't limited to DocTypes.

	Used by the Test Runner's DocType/Report filter so it only offers references
	relevant to the selected app — not every DocType/Report on the site.
	"""
	rtype = (reference_type or "").strip()

	tc = frappe.qb.DocType("Testcase")

	def _names(field, type_value: str) -> list[dict]:
		criterion = (tc.status == "Active") & (tc.reference_type == type_value)
		if app and app.strip():
			criterion &= tc.app == app.strip()
		values = frappe.qb.from_(tc).select(field).distinct().where(criterion).orderby(field).run(pluck=True)
		return [{"value": v, "type": type_value} for v in values if v]

	if rtype == "Report":
		return _names(tc.report, "Report")
	if rtype == "DocType":
		return _names(tc.reference_doctype, "DocType")
	# All Types → both, DocTypes first then Reports.
	return _names(tc.reference_doctype, "DocType") + _names(tc.report, "Report")


@frappe.whitelist()
def get_run_count(filters: str | dict | None = None) -> dict:
	"""Total number of Testcase Run records matching the History page filters."""
	import json

	if isinstance(filters, str):
		filters = json.loads(filters or "{}")

	return {"count": frappe.db.count("Testcase Run", filters=dict(filters or {}))}


def _run_name_from_job_id(job_id: str) -> str | None:
	"""Extract the Testcase Run name from one of our RQ job ids.

	Runs are enqueued as ``tc_run_<name>`` (single/app) or ``tc_batch_<name>``
	(batch). Frappe namespaces job ids as ``<site>::<job_id>``, so strip that first.
	"""
	if not job_id:
		return None
	# Frappe namespaces job ids as "<site>||<job_id>" (older builds used "::").
	# Take whatever follows the last separator, then strip our prefix.
	tail = job_id
	for sep in ("||", "::"):
		if sep in tail:
			tail = tail.rsplit(sep, 1)[-1]
	for prefix in ("tc_run_", "tc_batch_"):
		if tail.startswith(prefix):
			return tail[len(prefix) :]
	return None


def _executing_run_names() -> list[str]:
	"""Run names a worker is ACTIVELY executing right now, newest first.

	This reads RQ's StartedJobRegistry — the authoritative list of jobs a worker has
	picked up and is currently running — instead of the Testcase Run ``status``
	field, which can be stale (a crashed or superseded run can be left marked
	"Running" in the DB even though no worker is processing it). This is what lets
	the console follow the test that's truly running.
	"""
	try:
		from rq.job import Job
		from rq.registry import StartedJobRegistry

		from frappe.utils.background_jobs import get_redis_conn, get_queue

		conn = get_redis_conn()
		# Runs are routed across short/default/long by test count, so scan all three.
		names: list[tuple] = []
		for qname in ("short", "default", "long"):
			try:
				registry = StartedJobRegistry(queue=get_queue(qname))
				job_ids = registry.get_job_ids()
			except Exception:
				continue
			for jid in job_ids:
				name = _run_name_from_job_id(jid)
				if not name:
					continue
				try:
					job = Job.fetch(jid, connection=conn)
					started = job.started_at
				except Exception:
					started = None
				names.append((started, name))
		# Newest-started first so the console shows the most recently picked-up run.
		names.sort(key=lambda t: (t[0] is not None, t[0]), reverse=True)
		return [n for _, n in names]
	except Exception:
		return []


@frappe.whitelist()
def get_active_run(current: str | None = None) -> dict | None:
	"""
	The run a worker is actually executing right now, if any.

	We trust RQ's StartedJobRegistry (the real running jobs) over the DB status
	field, which can be left stale.

	``current`` is the run the console is currently following. With several workers,
	multiple runs execute in parallel; to keep the console STABLE (not flickering
	between them) we keep returning ``current`` for as long as it's still executing,
	and only move on to another executing run once it finishes. When ``current`` is
	not given or no longer running, we return the most recently started executing
	run. Falls back to the oldest DB ``Pending``/``Running`` row only when RQ reports
	nothing executing (inline runs, or the window before a worker picks one up).
	"""
	run = frappe.qb.DocType("Testcase Run")

	def _fetch(name: str):
		rows = (
			frappe.qb.from_(run)
			.select(run.name, run.test_method, run.status, run.full_output)
			.where(run.name == name)
			.limit(1)
			.run(as_dict=True)
		)
		row = rows[0] if rows else None
		if row:
			# The DB status may lag; if a worker is executing it, present it as Running
			# so the client follows it.
			row["status"] = "Running"
		return row

	executing = _executing_run_names()
	# Stay on the run we're already following while it's still executing.
	if current and current in executing:
		row = _fetch(current)
		if row:
			return row
	for name in executing:
		row = _fetch(name)
		if row:
			return row

	# Nothing executing per RQ — fall back to the DB (covers inline runs and the
	# brief window before a worker picks up a freshly-queued run).
	def _oldest(status: str):
		rows = (
			frappe.qb.from_(run)
			.select(run.name, run.test_method, run.status, run.full_output)
			.where(run.status == status)
			.orderby(run.creation, order=frappe.qb.asc)
			.limit(1)
			.run(as_dict=True)
		)
		return rows[0] if rows else None

	return _oldest("Running") or _oldest("Pending")
