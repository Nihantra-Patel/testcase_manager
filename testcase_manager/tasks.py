import frappe


def sync_after_migrate() -> None:
	"""Called automatically after every `bench migrate`."""
	try:
		from testcase_manager.testcase_manager.discovery import discover_all_test_cases

		result = discover_all_test_cases()
		frappe.logger("testcase_manager").info(
			f"Post-migrate sync: created={result['created']}, "
			f"updated={result['updated']}, deleted={result['deleted']}"
		)
	except Exception:
		frappe.log_error("Testcase Manager post-migrate sync failed")


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
