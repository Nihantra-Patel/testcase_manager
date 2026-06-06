import frappe
from frappe.model.document import Document


class TestcaseRun(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app: DF.Data | None
		duration: DF.Float
		end_time: DF.Datetime | None
		full_output: DF.Code | None
		python_path: DF.Data | None
		result: DF.SmallText | None
		run_scope: DF.Literal["Method", "File", "DocType", "App", "Batch"]
		site: DF.Data | None
		start_time: DF.Datetime | None
		status: DF.Literal["Pending", "Running", "Passed", "Failed", "Error", "Stopped"]
		test_case: DF.Link
		test_method: DF.Data | None
		traceback: DF.Code | None
		triggered_by: DF.Link | None
	# end: auto-generated types

	pass
