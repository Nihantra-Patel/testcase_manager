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
	"""Map an RQ job id (``<site>||tc_run_<name>`` / ``tc_batch_<name>``) → run name."""
	if not job_id:
		return None
	tail = job_id
	for sep in ("||", "::"):  # current builds use "||"; older ones used "::"
		if sep in tail:
			tail = tail.rsplit(sep, 1)[-1]
	for prefix in ("tc_run_", "tc_batch_"):
		if tail.startswith(prefix):
			return tail[len(prefix) :]
	return None


def _executing_run_names() -> list[str]:
	"""Run names a worker is currently executing (newest first), read from RQ.

	Uses RQ's StartedJobRegistry, not the Testcase Run ``status`` field which can be
	left stale (a crashed run stays "Running" in the DB though no worker has it).
	"""
	try:
		from frappe.utils.background_jobs import get_queue, get_redis_conn
		from rq.job import Job
		from rq.registry import StartedJobRegistry

		conn = get_redis_conn()
		names: list[tuple] = []
		for qname in ("short", "default", "long"):  # runs are routed across all three
			try:
				job_ids = StartedJobRegistry(queue=get_queue(qname)).get_job_ids()
			except Exception:
				continue
			for jid in job_ids:
				name = _run_name_from_job_id(jid)
				if not name:
					continue
				try:
					started = Job.fetch(jid, connection=conn).started_at
				except Exception:
					started = None
				names.append((started, name))
		names.sort(key=lambda t: (t[0] is not None, t[0]), reverse=True)
		return [n for _, n in names]
	except Exception:
		return []


@frappe.whitelist()
def get_active_run(current: str | None = None) -> dict | None:
	"""The run a worker is executing right now (from RQ, not the stale DB status).

	``current`` is the run the console already follows; we stick with it while it's
	still executing so the view doesn't flicker between parallel runs, advancing to
	another only once it finishes. Falls back to the oldest DB Pending/Running when
	RQ reports nothing executing (inline runs, or before a worker picks one up).
	"""
	run = frappe.qb.DocType("Testcase Run")

	def _fetch(name: str):
		rows = (
			frappe.qb.from_(run)
			.select(run.name, run.test_method, run.run_scope, run.status, run.full_output)
			.where(run.name == name)
			.limit(1)
			.run(as_dict=True)
		)
		row = rows[0] if rows else None
		if row:
			row["status"] = "Running"  # DB status may lag; a worker has it, so it's running
		return row

	executing = _executing_run_names()
	if current and current in executing:  # stay on the run we're already following
		row = _fetch(current)
		if row:
			return row
	for name in executing:
		row = _fetch(name)
		if row:
			return row

	def _oldest(status: str):
		rows = (
			frappe.qb.from_(run)
			.select(run.name, run.test_method, run.run_scope, run.status, run.full_output)
			.where(run.status == status)
			.orderby(run.creation, order=frappe.qb.asc)
			.limit(1)
			.run(as_dict=True)
		)
		return rows[0] if rows else None

	return _oldest("Running") or _oldest("Pending")
