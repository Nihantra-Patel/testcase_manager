# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Unit tests for the Testcase Log doctype.

Verifies:
  - A Testcase Log record can be created and retrieved.
  - Count fields (passed, failed, error) are stored correctly.
  - ``execution_status`` reflects the correct outcome.
  - A log can be linked back to its originating Testcase Run.
"""

import frappe
from testcase_manager.tests.utils import TestcaseManagerTestSuite


class TestTestcaseLog(TestcaseManagerTestSuite):
	# ------------------------------------------------------------------ helpers

	def _make_testcase(self) -> frappe.Document:
		tc = frappe.get_doc(
			{
				"doctype": "Testcase",
				"app": "frappe",
				"test_method": "test_log_helper_method",
				"python_path": "frappe.tests.test_utils.TestUtils",
			}
		)
		tc.insert(ignore_permissions=True)
		self.addCleanup(tc.delete, ignore_permissions=True, force=True)
		return tc

	def _make_run(self, tc: frappe.Document) -> frappe.Document:
		run = frappe.get_doc(
			{
				"doctype": "Testcase Run",
				"test_case": tc.name,
				"app": tc.app,
				"test_method": tc.test_method,
				"python_path": tc.python_path,
				"site": frappe.local.site,
				"triggered_by": frappe.session.user,
				"status": "Passed",
				"run_scope": "Method",
			}
		)
		run.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(run.delete, ignore_permissions=True, force=True)
		return run

	def _make_log(self, tc: frappe.Document, run: frappe.Document, **kwargs) -> frappe.Document:
		defaults = {
			"doctype": "Testcase Log",
			"test_case": tc.name,
			"run_reference": run.name,
			"test_method": tc.test_method,
			"app": tc.app,
			"execution_status": "Passed",
			"passed_count": 1,
			"failed_count": 0,
			"error_count": 0,
			"duration": 0.123,
			"full_output": "test_log_helper_method ... ok\n",
		}
		defaults.update(kwargs)
		log = frappe.get_doc(defaults)
		log.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(log.delete, ignore_permissions=True, force=True)
		return log

	# ------------------------------------------------------------------ tests

	def test_testcase_log_creation(self):
		"""A Testcase Log can be inserted and fetched from the DB."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		log = self._make_log(tc, run)

		self.assertTrue(log.name, "Testcase Log should have a name after insert")
		fetched = frappe.get_doc("Testcase Log", log.name)
		self.assertEqual(fetched.test_case, tc.name)
		self.assertEqual(fetched.run_reference, run.name)

	def test_passed_log_counts(self):
		"""Passed counts are persisted and summed correctly."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		log = self._make_log(tc, run, passed_count=5, failed_count=0, error_count=0)

		fetched = frappe.get_doc("Testcase Log", log.name)
		self.assertEqual(fetched.passed_count, 5)
		self.assertEqual(fetched.failed_count, 0)
		self.assertEqual(fetched.error_count, 0)

	def test_failed_log_status(self):
		"""A failed test execution is stored with execution_status=Failed."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		log = self._make_log(
			tc,
			run,
			execution_status="Failed",
			passed_count=0,
			failed_count=2,
			error_count=0,
			full_output="FAIL: test_log_helper_method\n",
			traceback="AssertionError: 1 != 2\n",
		)

		fetched = frappe.get_doc("Testcase Log", log.name)
		self.assertEqual(fetched.execution_status, "Failed")
		self.assertEqual(fetched.failed_count, 2)
		self.assertIn("AssertionError", fetched.traceback)

	def test_log_linked_to_run(self):
		"""Testcase Log's run_reference must resolve to a valid Testcase Run."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		log = self._make_log(tc, run)

		run_exists = frappe.db.exists("Testcase Run", log.run_reference)
		self.assertTrue(run_exists, "run_reference should point to an existing Testcase Run")

	def test_duration_stored_as_float(self):
		"""``duration`` is stored and retrieved as a float value."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		log = self._make_log(tc, run, duration=1.456)

		fetched = frappe.get_doc("Testcase Log", log.name)
		self.assertAlmostEqual(float(fetched.duration), 1.456, places=2)

	def test_multiple_logs_per_testcase(self):
		"""Multiple runs of the same test produce separate log records."""
		tc = self._make_testcase()
		run1 = self._make_run(tc)
		run2 = self._make_run(tc)

		log1 = self._make_log(tc, run1)
		log2 = self._make_log(tc, run2)

		self.assertNotEqual(log1.name, log2.name)

		logs = frappe.get_all(
			"Testcase Log",
			filters={"test_case": tc.name},
			fields=["name"],
		)
		log_names = {l.name for l in logs}
		self.assertIn(log1.name, log_names)
		self.assertIn(log2.name, log_names)
