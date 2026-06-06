import frappe
from frappe.model.document import Document


class TestcaseLog(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app: DF.Data | None
		duration: DF.Float
		error_count: DF.Int
		errors: DF.Code | None
		execution_status: DF.Literal["Passed", "Failed", "Error"]
		failed_count: DF.Int
		full_output: DF.Code | None
		passed_count: DF.Int
		run_reference: DF.Link
		test_case: DF.Link | None
		test_method: DF.Data | None
		traceback: DF.Code | None
	# end: auto-generated types

	pass
