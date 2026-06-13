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
	except Exception:
		frappe.log_error("Testcase Manager post-migrate sync failed")


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
	except Exception:
		frappe.log_error("Testcase Manager daily sync failed")
