import unittest

import frappe


class TestcaseManagerTestSuite(unittest.TestCase):
	"""Base test class for Testcase Manager tests."""

	def tearDown(self):
		frappe.db.rollback()
