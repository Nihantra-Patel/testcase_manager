"""
cProfile-based document profiling (savepoint-isolated, never persists).

Replaces the manual console ritual::

    doc = frappe.get_doc("DocType", "name")
    %prun -s cumulative doc.submit()

with a whitelisted call that profiles a single document action (submit/cancel)
inside a database savepoint, then rolls it back — so the timings are *real*
(all hooks fire) but nothing is written to disk.

Output is the raw cProfile table sorted by cumulative time (familiar ``%prun``
output), with bench paths shortened to start at ``/apps`` or ``/env``.
"""

from __future__ import annotations

import cProfile
import io
import pstats
import re

import frappe

# Rewrites absolute bench paths in the raw cProfile output so each path starts at
# ``/apps/…`` (or ``/env/…``) instead of the long ``…/dev/frappe-bench`` prefix —
# the prefix is noise and identical on every line.
_BENCH_PREFIX_RE = re.compile(r"\S*?/frappe-bench(?=/(?:apps|env|sites)/)")


def _shorten_paths(text: str) -> str:
	return _BENCH_PREFIX_RE.sub("", text or "")


class RunProfiler:
	"""Context manager that profiles whatever runs inside it.

	Usage::

	    profiler = RunProfiler()
	    with profiler:
	        doc.submit()
	    text = profiler.render()
	"""

	def __init__(self, top: int = 60) -> None:
		self._pr = cProfile.Profile()
		self._top = top
		self._used = False

	def __enter__(self) -> "RunProfiler":
		self._used = True
		self._pr.enable()
		return self

	def __exit__(self, *exc) -> bool:
		try:
			self._pr.disable()
		except Exception:
			pass
		return False  # never suppress an exception from the profiled code

	def render(self) -> str:
		if not self._used:
			return ""
		note = (
			"# Note: cProfile measures Python time and adds overhead, so absolute "
			"times run slower than normal — read them relatively. First-call numbers "
			"include import/cache warmup.\n"
		)
		return f"{note}\n{self._render_raw()}"

	def _render_raw(self) -> str:
		buf = io.StringIO()
		try:
			pstats.Stats(self._pr, stream=buf).sort_stats("cumulative").print_stats(self._top)
		except Exception:
			return ""
		header = "=" * 70 + f"\nRAW cProfile (top {self._top} by cumulative time)\n" + "=" * 70
		return f"{header}\n{_shorten_paths(buf.getvalue())}"


def profile_document_action(doctype: str, name: str, action: str) -> dict:
	"""Profile one document action without persisting anything.

	*action* (always on the real record, rolled back so the original is untouched):
	  - ``"submit"`` — profile ``submit()`` of a draft (docstatus 0).
	  - ``"cancel"`` — profile ``cancel()`` of a submitted doc (docstatus 1).

	The whole action runs inside a savepoint and is rolled back, so all hooks fire
	(real timings) but no write survives.
	"""
	if action not in ("submit", "cancel"):
		frappe.throw(frappe._("action must be 'submit' or 'cancel'"))

	source = frappe.get_doc(doctype, name)
	if action == "submit":
		# Only a draft can be submitted.
		if source.docstatus != 0:
			frappe.throw(
				frappe._("{0} {1} is not a draft (docstatus={2}); cannot profile submit.").format(
					doctype, name, source.docstatus
				)
			)
		op = lambda: source.submit()  # noqa: E731 — tiny local callable for the profiler
	else:
		# Only a submitted doc can be cancelled.
		if source.docstatus != 1:
			frappe.throw(
				frappe._("{0} {1} is not submitted (docstatus={2}); cannot profile cancel.").format(
					doctype, name, source.docstatus
				)
			)
		op = lambda: source.cancel()  # noqa: E731

	savepoint = "tcm_profile_" + frappe.generate_hash(length=8)
	frappe.db.savepoint(savepoint)
	profiler = RunProfiler()
	error = None
	try:
		with profiler:
			op()
	except Exception as exc:
		# Capture but don't re-raise: a failed action still produced a partial
		# profile, and we always roll back. Surface the error in the result.
		error = f"{type(exc).__name__}: {exc}"
	finally:
		# Undo everything the action wrote — this is the whole point.
		frappe.db.rollback(save_point=savepoint)

	return {
		"doctype": doctype,
		"name": name,
		"action": action,
		"profile_data": profiler.render(),
		"error": error,
	}
