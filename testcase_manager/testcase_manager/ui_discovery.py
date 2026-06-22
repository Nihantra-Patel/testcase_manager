"""
UI (Cypress) spec discovery.

The Python engine discovers ``test_*.py`` methods via AST. UI tests are a
different tier: Cypress specs are JavaScript files run by a real browser, so we
can't import them. Instead we glob the two spec patterns Frappe's
``cypress.config.js`` uses — ``cypress/integration/*.js`` and ``ui_test_*.js``
anywhere in the app — and parse the ``describe()``/``it()`` titles with a regex
(no JS engine needed) to list the individual UI tests inside each spec.

Discovered specs are upserted into the same ``Testcase`` DocType as Python tests,
distinguished by ``test_kind = "UI"``, so the Runner, History and console all
work unchanged. One ``Testcase`` row == one spec FILE (a spec is the smallest
unit Cypress can run via ``--spec``); the parsed ``it()`` titles are stored for
display only.
"""

import os
import re
from pathlib import Path

import frappe
from frappe.utils import now_datetime

# Spec discovery patterns, mirroring frappe/cypress.config.js `specPattern`:
#   - cypress/integration/*.js  (the classic Frappe location)
#   - **/ui_test_*.js           (per-doctype specs colocated with the controller)
_INTEGRATION_DIR = os.path.join("cypress", "integration")

# describe(...) / context(...) and it(...) / specify(...) title extraction. Cypress
# uses these BDD globals; we pull the first string-literal argument of each.
_BLOCK_RE = re.compile(
	r"""\b(?:describe|context)\s*\(\s*(['"`])(?P<title>(?:\\.|(?!\1).)*)\1""",
	re.MULTILINE,
)
_TEST_RE = re.compile(
	r"""\b(?:it|specify)\s*\(\s*(['"`])(?P<title>(?:\\.|(?!\1).)*)\1""",
	re.MULTILINE,
)

_PRUNE_DIRS = {"__pycache__", "node_modules", "public", ".git", "dist"}


def discover_all_ui_specs(app_name: str | None = None) -> dict:
	"""Discover UI specs across apps and sync ``Testcase`` rows (test_kind=UI).

	Scope: a single app when *app_name* is given, else every installed app.
	Returns ``{created, updated, deleted, errors}``.
	"""
	apps = [app_name] if app_name else frappe.get_installed_apps()
	summary: dict = {"created": 0, "updated": 0, "deleted": 0, "errors": []}

	for app in apps:
		try:
			result = _discover_app(app)
			for k in ("created", "updated", "deleted"):
				summary[k] += result.get(k, 0)
		except Exception as exc:
			msg = f"{app}: {exc}"
			summary["errors"].append(msg)
			frappe.log_error(f"UI spec discovery error — {msg}")

	return summary


# ---------------------------------------------------------------------------
# Per-app discovery
# ---------------------------------------------------------------------------


def _discover_app(app: str) -> dict:
	# The app SOURCE root (…/apps/<app>) — where cypress/ lives — not the module
	# dir (…/apps/<app>/<app>) that get_app_path() returns.
	app_path = Path(frappe.get_app_source_path(app))
	discovered: list[dict] = []

	for spec_path in _iter_spec_files(app_path):
		try:
			tests = _extract_tests(spec_path)
		except Exception as exc:
			frappe.log_error(f"UI spec parse error on {spec_path}: {exc}")
			continue

		# `bench run-ui-tests` chdir's into the app source root and passes --spec
		# straight to Cypress, so the spec path must be relative to that root
		# (e.g. "cypress/integration/control_data.js").
		rel_to_app = spec_path.relative_to(app_path)
		discovered.append(
			{
				"app": app,
				"module": _infer_module(spec_path, app_path),
				"test_file": spec_path.name,
				# test_file_path is what `bench run-ui-tests --spec` receives, so it
				# must be relative to the app source root (apps/<app>/…).
				"test_file_path": str(rel_to_app),
				# One spec == one runnable unit; the it() titles are shown as a hint.
				"test_method": spec_path.stem,
				"ui_test_names": "\n".join(tests),
				"ui_test_count": len(tests),
			}
		)

	return _sync_records(app, discovered)


def _iter_spec_files(app_path: Path):
	"""Yield every Cypress spec file in an app (both supported patterns)."""
	seen: set[Path] = set()

	integration = app_path / _INTEGRATION_DIR
	if integration.is_dir():
		for f in sorted(integration.glob("*.js")):
			if f not in seen:
				seen.add(f)
				yield f

	for root, dirs, files in os.walk(app_path):
		dirs[:] = [d for d in dirs if d not in _PRUNE_DIRS]
		for filename in files:
			if filename.startswith("ui_test_") and filename.endswith(".js"):
				f = Path(root) / filename
				if f not in seen:
					seen.add(f)
					yield f


def _extract_tests(spec_path: Path) -> list[str]:
	"""Return the it()/specify() titles in a spec, prefixed by their describe block."""
	source = spec_path.read_text(encoding="utf-8", errors="ignore")
	block = None
	m = _BLOCK_RE.search(source)
	if m:
		block = m.group("title").strip()

	titles: list[str] = []
	seen: set[str] = set()
	for tm in _TEST_RE.finditer(source):
		title = tm.group("title").strip()
		label = f"{block} > {title}" if block else title
		if label not in seen:
			seen.add(label)
			titles.append(label)
	return titles


def _infer_module(spec_path: Path, app_path: Path) -> str:
	rel = spec_path.relative_to(app_path)
	parts = rel.parts
	if parts and parts[0] == "cypress":
		return "Cypress"
	return " ".join(word.capitalize() for word in parts[0].split("_")) if parts else "UI"


# ---------------------------------------------------------------------------
# Database sync
# ---------------------------------------------------------------------------


def _sync_records(app: str, discovered: list[dict]) -> dict:
	"""Upsert discovered UI specs and delete stale ones, scoped to UI kind."""
	counts = {"created": 0, "updated": 0, "deleted": 0}

	tc = frappe.qb.DocType("Testcase")
	existing_rows = (
		frappe.qb.from_(tc)
		.select(tc.name, tc.test_file_path)
		.where((tc.app == app) & (tc.test_kind == "UI"))
		.run(as_dict=True)
	)
	existing: dict[str, str] = {r.test_file_path: r.name for r in existing_rows}

	discovered_keys: set[str] = set()
	now = now_datetime()

	for data in discovered:
		key = data["test_file_path"]
		discovered_keys.add(key)
		try:
			if key in existing:
				frappe.db.set_value(
					"Testcase",
					existing[key],
					{
						"module": data["module"],
						"test_file": data["test_file"],
						"test_method": data["test_method"],
						"ui_test_names": data["ui_test_names"],
						"ui_test_count": data["ui_test_count"],
						"status": "Active",
						"last_synced": now,
					},
					update_modified=False,
				)
				counts["updated"] += 1
			else:
				doc = frappe.new_doc("Testcase")
				doc.update(data)
				doc.test_kind = "UI"
				doc.reference_type = ""
				doc.python_path = ""
				doc.status = "Active"
				doc.last_synced = now
				doc.insert(ignore_permissions=True, ignore_if_duplicate=True, ignore_links=True)
				counts["created"] += 1
		except Exception:
			frappe.log_error(f"UI spec sync skipped: {key}", "Testcase Manager UI discovery")

	for key, name in existing.items():
		if key not in discovered_keys:
			try:
				_delete_testcase(name)
				counts["deleted"] += 1
			except Exception:
				frappe.log_error(f"UI spec delete failed: {name}", "Testcase Manager UI discovery")

	# Discovery runs as a background job / scheduler task with no enclosing request
	# transaction, so the upserts must be committed explicitly to persist. Mirrors
	# discovery.py's Python-test sync.
	frappe.db.commit()  # nosemgrep: frappe-semgrep-rules.rules.frappe-manual-commit
	return counts


def _delete_testcase(name: str) -> None:
	"""Hard-delete a UI Testcase and its dependent Run/Log records."""
	run = frappe.qb.DocType("Testcase Run")
	run_names = frappe.qb.from_(run).select(run.name).where(run.test_case == name).run(pluck=True)
	for run in run_names:
		frappe.db.delete("Testcase Log", {"run_reference": run})
	frappe.db.delete("Testcase Run", {"test_case": name})
	frappe.delete_doc("Testcase", name, force=True, ignore_permissions=True, delete_permanently=True)
