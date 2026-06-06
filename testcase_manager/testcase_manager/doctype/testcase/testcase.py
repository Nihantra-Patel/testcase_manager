import frappe
from frappe.model.document import Document


class Testcase(Document):
	def before_save(self) -> None:
		if not self.last_synced:
			from frappe.utils import now_datetime

			self.last_synced = now_datetime()
