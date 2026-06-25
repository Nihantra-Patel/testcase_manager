app_name = "testcase_manager"
app_title = "Testcase Manager"
app_publisher = "Nihantra Patel"
app_description = "UI-based Test Case Management and Test Runner for Frappe"
app_email = "nihantra@frappe.io"
app_license = "mit"

# Scheduled Tasks
scheduler_events = {
	"daily": [
		"testcase_manager.tasks.sync_test_cases_daily",
		"testcase_manager.tasks.compute_flaky_tests_daily",
	],
}

# Migration hook — refresh test case metadata after every migrate
after_migrate = ["testcase_manager.tasks.sync_after_migrate"]

# ---------------------------------------------------------------------------
# Vue SPA (frappe-ui) — served at /testcase_manager
# ---------------------------------------------------------------------------
# vue-router uses history mode, so every /testcase_manager/<sub-route> must be
# served by the same SPA page (www/testcase_manager.html, built from frontend/).
website_route_rules = [
	{"from_route": "/testcase_manager/<path:app_path>", "to_route": "testcase_manager"},
]

export_python_type_annotations = True
require_type_annotated_api_methods = True

default_log_clearing_doctypes = {
	"Testcase Run": 90,
	"Testcase Log": 90,
}
