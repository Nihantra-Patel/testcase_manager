import frappe
from frappe.model.document import Document


class Testcase(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		app: DF.Data
		last_synced: DF.Datetime | None
		module: DF.Data | None
		python_path: DF.Data | None
		reference_doctype: DF.Link | None
		reference_type: DF.Literal["", "DocType", "Report"]
		report: DF.Link | None
		status: DF.Literal["Active", "Inactive"]
		test_file: DF.Data | None
		test_file_path: DF.Data | None
		test_method: DF.Data | None
	# end: auto-generated types

	def before_save(self) -> None:
		if not self.last_synced:
			from frappe.utils import now_datetime

			self.last_synced = now_datetime()
