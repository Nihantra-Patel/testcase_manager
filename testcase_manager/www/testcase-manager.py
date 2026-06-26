"""Server context for the Testcase Manager Vue SPA (route: /testcase-manager).

The built index.html (frontend/index.html → www/testcase-manager.html) is a Jinja
template; ``jinjaBootData`` in the frappe-ui Vite plugin injects a ``boot`` object
into the page so the frontend can initialise the socket connection and CSRF token
without an extra round-trip.
"""

import frappe

no_cache = 1


def get_context(context):
	# Only logged-in users may run tests.
	if frappe.session.user == "Guest":
		frappe.throw("Not permitted", frappe.PermissionError)

	csrf_token = frappe.sessions.get_csrf_token()
	frappe.db.commit()

	context.boot = frappe._dict(
		{
			"csrf_token": csrf_token,
			"site_name": frappe.local.site,
			"frappe_version": frappe.__version__,
			"user": frappe.session.user,
		}
	)
	return context
