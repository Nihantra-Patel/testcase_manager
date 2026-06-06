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
	],
}

# Migration hook — refresh test case metadata after every migrate
after_migrate = ["testcase_manager.tasks.sync_after_migrate"]

export_python_type_annotations = True
require_type_annotated_api_methods = True

default_log_clearing_doctypes = {
	"Testcase Run": 90,
	"Testcase Log": 90,
}
