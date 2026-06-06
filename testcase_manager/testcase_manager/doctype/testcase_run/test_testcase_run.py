# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Unit tests for the Testcase Run doctype.

Verifies:
  - A Testcase Run record can be created for a given site.
  - Status transitions (Pending → Running → Passed/Failed) are persisted.
  - ``triggered_by`` is captured and readable.
  - ``site`` field reflects the current Frappe site.
"""

import frappe

from testcase_manager.tests.utils import TestcaseManagerTestSuite


class TestTestcaseRun(TestcaseManagerTestSuite):
	# ------------------------------------------------------------------ helpers

	def _make_testcase(self) -> frappe.Document:
		tc = frappe.get_doc(
			{
				"doctype": "Testcase",
				"app": "frappe",
				"test_method": "test_run_helper_method",
				"python_path": "frappe.tests.test_utils.TestUtils",
			}
		)
		tc.insert(ignore_permissions=True)
		self.addCleanup(tc.delete, ignore_permissions=True, force=True)
		return tc

	def _make_run(self, tc: frappe.Document, **kwargs) -> frappe.Document:
		defaults = {
			"doctype": "Testcase Run",
			"test_case": tc.name,
			"app": tc.app,
			"test_method": tc.test_method,
			"python_path": tc.python_path,
			"site": frappe.local.site,
			"triggered_by": frappe.session.user,
			"status": "Pending",
			"run_scope": "Method",
		}
		defaults.update(kwargs)
		run = frappe.get_doc(defaults)
		run.insert(ignore_permissions=True)
		frappe.db.commit()
		self.addCleanup(run.delete, ignore_permissions=True, force=True)
		return run

	# ------------------------------------------------------------------ tests

	def test_testcase_run_creation(self):
		"""A Testcase Run can be inserted and retrieved from the DB."""
		tc = self._make_testcase()
		run = self._make_run(tc)

		self.assertTrue(run.name, "Testcase Run should have a name after insert")
		fetched = frappe.get_doc("Testcase Run", run.name)
		self.assertEqual(fetched.test_case, tc.name)
		self.assertEqual(fetched.status, "Pending")

	def test_run_site_matches_current_site(self):
		"""The ``site`` field must contain the active Frappe site name."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		self.assertEqual(run.site, frappe.local.site)

	def test_run_triggered_by_is_set(self):
		"""``triggered_by`` should be populated with the current user."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		self.assertTrue(run.triggered_by, "triggered_by should not be empty")

	def test_status_transition_pending_to_running(self):
		"""Status can be updated from Pending to Running via db_set."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		self.assertEqual(run.status, "Pending")

		frappe.db.set_value(
			"Testcase Run",
			run.name,
			{"status": "Running"},
			update_modified=False,
		)
		frappe.db.commit()

		updated = frappe.get_doc("Testcase Run", run.name)
		self.assertEqual(updated.status, "Running")

	def test_status_transition_running_to_passed(self):
		"""Status can be updated to Passed; result fields are persisted."""
		tc = self._make_testcase()
		run = self._make_run(tc, status="Running")

		frappe.db.set_value(
			"Testcase Run",
			run.name,
			{
				"status": "Passed",
				"result": "Passed: 1, Failed: 0, Errors: 0",
				"full_output": "test_run_helper_method ... ok\n",
			},
			update_modified=False,
		)
		frappe.db.commit()

		updated = frappe.get_doc("Testcase Run", run.name)
		self.assertEqual(updated.status, "Passed")
		self.assertIn("Passed: 1", updated.result)

	def test_run_scope_default_is_method(self):
		"""Default run_scope must be Method."""
		tc = self._make_testcase()
		run = self._make_run(tc)
		self.assertEqual(run.run_scope, "Method")

	def test_multiple_runs_for_same_testcase(self):
		"""Multiple Testcase Run records can reference the same Testcase."""
		tc = self._make_testcase()
		run1 = self._make_run(tc)
		run2 = self._make_run(tc)

		self.assertNotEqual(run1.name, run2.name, "Each run should have a unique name")

		runs = frappe.get_all(
			"Testcase Run",
			filters={"test_case": tc.name},
			fields=["name"],
		)
		run_names = {r.name for r in runs}
		self.assertIn(run1.name, run_names)
		self.assertIn(run2.name, run_names)
