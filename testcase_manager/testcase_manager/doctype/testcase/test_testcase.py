# Copyright (c) 2024, Frappe Technologies and contributors
# For license information, please see license.txt

"""
Unit tests for the Testcase doctype.

Verifies:
  - A Testcase record can be created and retrieved at site level.
  - `before_save` auto-populates ``last_synced`` on first save.
  - ``last_synced`` is NOT overwritten on subsequent saves.
  - Required field ``app`` is enforced.
"""

import frappe
from testcase_manager.tests.utils import TestcaseManagerTestSuite


class TestTestcase(TestcaseManagerTestSuite):
	# ------------------------------------------------------------------ helpers

	def _make_testcase(self, **kwargs) -> frappe.Document:
		"""Create and return a Testcase document (cleaned up after the test)."""
		defaults = {
			"doctype": "Testcase",
			"app": "frappe",
			"test_method": "test_example_method",
			"python_path": "frappe.tests.test_utils.TestUtils",
		}
		defaults.update(kwargs)
		doc = frappe.get_doc(defaults)
		doc.insert(ignore_permissions=True)
		self.addCleanup(doc.delete, ignore_permissions=True, force=True)
		return doc

	# ------------------------------------------------------------------ tests

	def test_testcase_creation(self):
		"""A Testcase record can be saved and fetched from the DB."""
		doc = self._make_testcase()
		self.assertTrue(doc.name, "Testcase should have a name after insert")

		fetched = frappe.get_doc("Testcase", doc.name)
		self.assertEqual(fetched.app, "frappe")
		self.assertEqual(fetched.test_method, "test_example_method")

	def test_before_save_sets_last_synced_on_creation(self):
		"""``last_synced`` must be populated by before_save on the first save."""
		doc = self._make_testcase()
		self.assertIsNotNone(doc.last_synced, "last_synced should be set after first save")

	def test_before_save_does_not_overwrite_last_synced(self):
		"""Re-saving should NOT change ``last_synced`` once it is already set."""
		doc = self._make_testcase()
		original_synced = doc.last_synced

		doc.test_method = "test_updated_method"
		doc.save(ignore_permissions=True)

		self.assertEqual(
			doc.last_synced,
			original_synced,
			"before_save must not overwrite an existing last_synced value",
		)

	def test_app_field_is_required(self):
		"""Inserting a Testcase without ``app`` must raise a MandatoryError."""
		doc = frappe.get_doc(
			{
				"doctype": "Testcase",
				"test_method": "test_no_app",
			}
		)
		with self.assertRaises(frappe.exceptions.MandatoryError):
			doc.insert(ignore_permissions=True)

	def test_testcase_belongs_to_current_site(self):
		"""
		Testcase records are stored in the site DB and are site-isolated —
		fetching by name must succeed on the same site.
		"""
		doc = self._make_testcase()
		exists = frappe.db.exists("Testcase", doc.name)
		self.assertTrue(exists, "Testcase should exist in the current site's DB")
