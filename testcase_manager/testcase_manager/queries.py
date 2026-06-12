"""
Read-only whitelisted endpoints that feed the Runner and History pages.

These only query Testcase / Testcase Run records — they never start a run or
mutate data — so they don't need the role gate the execution endpoints use.
Mutating / test-running endpoints live in ``api.py``.
"""

import frappe

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

	page = max(int(page), 1)
	page_size = min(max(int(page_size), 1), MAX_PAGE_SIZE)

	records = frappe.get_all(
		"Testcase",
		filters=filters,
		or_filters=or_filters,
		fields=fields,
		limit_start=(page - 1) * page_size,
		limit_page_length=page_size,
		order_by="app asc, module asc, test_method asc",
	)

	return {"total": total, "records": records}


@frappe.whitelist()
def get_installed_apps_list() -> list[str]:
	"""Return only apps that actually have discovered test cases (for filter dropdowns)."""
	return frappe.get_all(
		"Testcase",
		filters={"status": "Active"},
		distinct=True,
		pluck="app",
		order_by="app asc",
	)


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

	def _names(field: str, type_value: str) -> list[dict]:
		filters: dict = {"status": "Active", "reference_type": type_value}
		if app and app.strip():
			filters["app"] = app.strip()
		values = frappe.get_all(
			"Testcase",
			filters=filters,
			distinct=True,
			pluck=field,
			order_by=f"{field} asc",
		)
		return [{"value": v, "type": type_value} for v in values if v]

	if rtype == "Report":
		return _names("report", "Report")
	if rtype == "DocType":
		return _names("reference_doctype", "DocType")
	# All Types → both, DocTypes first then Reports.
	return _names("reference_doctype", "DocType") + _names("report", "Report")


@frappe.whitelist()
def get_run_count(filters: str | dict | None = None) -> dict:
	"""Total number of Testcase Run records matching the History page filters."""
	import json

	if isinstance(filters, str):
		filters = json.loads(filters or "{}")

	return {"count": frappe.db.count("Testcase Run", filters=dict(filters or {}))}


@frappe.whitelist()
def get_active_run() -> dict | None:
	"""
	The most recent still-in-progress run (status Running/Pending), if any.

	Lets the UI reconnect and resume streaming after a page reload — it returns
	the run name, its label, and the output already saved so the console can be
	seeded before live events take over.
	"""
	rows = frappe.get_all(
		"Testcase Run",
		filters={"status": ["in", ["Running", "Pending"]]},
		fields=["name", "test_method", "status", "full_output"],
		order_by="creation desc",
		limit=1,
	)
	return rows[0] if rows else None
