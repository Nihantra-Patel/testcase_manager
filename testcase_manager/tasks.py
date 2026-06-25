import frappe


def sync_after_migrate() -> None:
	"""Called automatically after every `bench migrate`."""
	_ensure_scheduler_enabled()
	try:
		from testcase_manager.testcase_manager.discovery import discover_all_test_cases

		result = discover_all_test_cases()
		frappe.logger("testcase_manager").info(
			f"Post-migrate sync: created={result['created']}, "
			f"updated={result['updated']}, deleted={result['deleted']}"
		)
		_sync_ui_specs("Post-migrate")
	except Exception:
		frappe.log_error("Testcase Manager post-migrate sync failed")


def _sync_ui_specs(label: str) -> None:
	"""Discover Cypress UI specs alongside the Python tests. Best-effort."""
	try:
		from testcase_manager.testcase_manager.ui_discovery import discover_all_ui_specs

		ui = discover_all_ui_specs()
		frappe.logger("testcase_manager").info(
			f"{label} UI sync: created={ui['created']}, updated={ui['updated']}, deleted={ui['deleted']}"
		)
	except Exception:
		frappe.log_error(f"Testcase Manager {label} UI sync failed")


def _ensure_scheduler_enabled() -> None:
	"""
	Re-enable the scheduler if it got turned off.

	``bench migrate`` (and a test run that errors mid-setup) disables the
	scheduler, so it can be left inactive. This site keeps the scheduler on, so
	turn it back on after every migrate.
	"""
	try:
		import frappe.utils.scheduler as _sched

		if _sched.is_scheduler_disabled(verbose=False):
			_sched.enable_scheduler()
			frappe.db.commit()
	except Exception:
		frappe.log_error("Testcase Manager: failed to re-enable scheduler after migrate")


def sync_test_cases_daily() -> None:
	"""Daily scheduler: re-discover all test cases from installed apps."""
	try:
		from testcase_manager.testcase_manager.discovery import discover_all_test_cases

		result = discover_all_test_cases()
		frappe.logger("testcase_manager").info(
			f"Daily sync: created={result['created']}, "
			f"updated={result['updated']}, deleted={result['deleted']}"
		)
		_sync_ui_specs("Daily")
	except Exception:
		frappe.log_error("Testcase Manager daily sync failed")


def compute_flaky_tests_daily() -> None:
	"""Daily scheduler: recompute the ``is_flaky`` flag on every Testcase."""
	try:
		from testcase_manager.testcase_manager.api import compute_flaky_tests

		result = compute_flaky_tests()
		frappe.logger("testcase_manager").info(
			f"Daily flaky scan: checked={result['checked']}, flaky={result['flaky']}"
		)
	except Exception:
		frappe.log_error("Testcase Manager daily flaky scan failed")
