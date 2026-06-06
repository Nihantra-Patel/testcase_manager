"""
Test Case discovery engine.

Walks installed Frappe apps, finds test_*.py files, extracts test methods via
AST (no imports, so no side-effects), and upserts Test Case records.
"""

import ast
import hashlib
import os
from pathlib import Path

import frappe
from frappe.utils import now_datetime

# ---------------------------------------------------------------------------
# Public entry points
# ---------------------------------------------------------------------------


def discover_all_test_cases(app_name: str | None = None) -> dict:
	"""
	Discover test cases for one app (or all installed apps) and sync records.
	Returns a summary dict: {created, updated, deactivated, errors}.
	"""
	apps = [app_name] if app_name else frappe.get_installed_apps()
	summary: dict = {"created": 0, "updated": 0, "deactivated": 0, "errors": []}

	for app in apps:
		try:
			result = _discover_app(app)
			for k in ("created", "updated", "deactivated"):
				summary[k] += result.get(k, 0)
		except Exception as exc:
			msg = f"{app}: {exc}"
			summary["errors"].append(msg)
			frappe.log_error(f"TestCase discovery error — {msg}")

	return summary


# ---------------------------------------------------------------------------
# Per-app discovery
# ---------------------------------------------------------------------------


def _discover_app(app: str) -> dict:
	app_path = Path(frappe.get_app_path(app))
	discovered: list[dict] = []

	for root, dirs, files in os.walk(app_path):
		# Prune directories that never contain tests
		dirs[:] = [
			d
			for d in dirs
			if d
			not in {
				"__pycache__",
				"node_modules",
				"public",
				"locals",
				".git",
				"locale",
				"translations",
				"static",
				"fixtures",
				"logs",
			}
		]
		# Skip the boilerplate doctype scaffold
		if os.path.join("doctype", "doctype", "boilerplate") in root:
			continue

		for filename in files:
			if not (filename.startswith("test_") and filename.endswith(".py")):
				continue
			if filename == "test_runner.py":
				continue

			file_path = Path(root) / filename
			try:
				methods = _extract_test_methods(file_path)
			except Exception as exc:
				frappe.log_error(f"AST parse error on {file_path}: {exc}")
				continue

			if not methods:
				continue

			module_path = _file_to_module_path(file_path, app_path)
			reference_type, reference_doctype, report = _infer_reference(file_path)
			module_label = _infer_frappe_module(file_path, app_path)
			rel_path = str(file_path.relative_to(app_path.parent))

			for method in methods:
				discovered.append(
					{
						"app": app,
						"module": module_label,
						"reference_type": reference_type,
						"reference_doctype": reference_doctype,
						"report": report,
						"test_file": filename,
						"test_file_path": rel_path,
						"test_method": method,
						"python_path": module_path,
					}
				)

	return _sync_records(app, discovered)


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------


def _extract_test_methods(file_path: Path) -> list[str]:
	"""Return all `test_*` method names found in *file_path* via AST parsing."""
	source = file_path.read_text(encoding="utf-8", errors="ignore")
	try:
		tree = ast.parse(source, filename=str(file_path))
	except SyntaxError:
		return []

	methods: list[str] = []

	for node in ast.walk(tree):
		# Methods inside classes
		if isinstance(node, ast.ClassDef):
			for item in node.body:
				if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
					if item.name.startswith("test_"):
						methods.append(item.name)

	# Top-level test functions (less common but supported)
	for node in ast.iter_child_nodes(tree):
		if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
			if node.name.startswith("test_"):
				methods.append(node.name)

	# Deduplicate while preserving order
	seen: set[str] = set()
	unique: list[str] = []
	for m in methods:
		if m not in seen:
			seen.add(m)
			unique.append(m)
	return unique


# ---------------------------------------------------------------------------
# Path / module inference helpers
# ---------------------------------------------------------------------------


def _file_to_module_path(file_path: Path, app_path: Path) -> str:
	"""
	Convert an absolute file path to a dotted Python module path.

	Example:
	  .../apps/erpnext/erpnext/accounts/doctype/sales_invoice/test_sales_invoice.py
	  → erpnext.accounts.doctype.sales_invoice.test_sales_invoice
	"""
	rel = file_path.relative_to(app_path.parent)  # relative to apps/<app>/
	parts = [*list(rel.parent.parts), file_path.stem]
	return ".".join(parts)


def _infer_reference(file_path: Path) -> tuple[str, str, str]:
	"""
	Return (reference_type, reference_doctype, report) by inspecting the path.

	Patterns:
	  .../doctype/<name>/test_<name>.py  → DocType
	  .../report/<name>/test_<name>.py   → Report
	"""
	parts = file_path.parts
	for i, part in enumerate(parts[:-1]):
		if part == "doctype" and i + 1 < len(parts) - 1:
			folder = parts[i + 1]
			title = _folder_to_title(folder)
			return "DocType", title, ""
		if part == "report" and i + 1 < len(parts) - 1:
			folder = parts[i + 1]
			title = _folder_to_title(folder)
			return "Report", "", title
	return "", "", ""


def _infer_frappe_module(file_path: Path, app_path: Path) -> str:
	"""Return the top-level Frappe module label from the first directory under the app root."""
	rel = file_path.relative_to(app_path)
	parts = rel.parts
	if parts:
		return _folder_to_title(parts[0])
	return ""


def _folder_to_title(folder: str) -> str:
	return " ".join(word.capitalize() for word in folder.split("_"))


# ---------------------------------------------------------------------------
# Database sync
# ---------------------------------------------------------------------------


def _make_key(python_path: str, test_method: str) -> str:
	"""Stable hash key for a test case record — used as autoname."""
	raw = f"{python_path}::{test_method}"
	return hashlib.md5(raw.encode()).hexdigest()[:12].upper()


def _sync_records(app: str, discovered: list[dict]) -> dict:
	"""Upsert discovered test cases and deactivate stale ones."""
	counts = {"created": 0, "updated": 0, "deactivated": 0}

	# Fetch existing records for this app
	existing_rows = frappe.get_all(
		"Testcase",
		filters={"app": app},
		fields=["name", "python_path", "test_method"],
	)
	existing: dict[str, str] = {f"{r.python_path}::{r.test_method}": r.name for r in existing_rows}

	discovered_keys: set[str] = set()
	now = now_datetime()

	for data in discovered:
		composite_key = f"{data['python_path']}::{data['test_method']}"
		discovered_keys.add(composite_key)

		# Harden against a single bad record aborting the whole app's sync.
		try:
			if composite_key in existing:
				# Update metadata but keep existing record name
				frappe.db.set_value(
					"Testcase",
					existing[composite_key],
					{
						"module": data["module"],
						"reference_type": data["reference_type"],
						"reference_doctype": data["reference_doctype"],
						"report": data["report"],
						"test_file": data["test_file"],
						"test_file_path": data["test_file_path"],
						"status": "Active",
						"last_synced": now,
					},
					update_modified=False,
				)
				counts["updated"] += 1
			else:
				doc = frappe.new_doc("Testcase")
				doc.update(data)
				doc.status = "Active"
				doc.last_synced = now
				# ignore_links: discovered DocType/Report names are inferred from
				# folder paths and may not exactly match a real master record;
				# we must not let Link validation reject a discovered test.
				doc.insert(ignore_permissions=True, ignore_if_duplicate=True, ignore_links=True)
				counts["created"] += 1
		except Exception:
			frappe.log_error(
				f"TestCase sync skipped a record: {composite_key}",
				"Testcase Manager discovery",
			)

	# Deactivate test cases that no longer exist on disk
	for key, name in existing.items():
		if key not in discovered_keys:
			frappe.db.set_value("Testcase", name, "status", "Inactive", update_modified=False)
			counts["deactivated"] += 1

	frappe.db.commit()
	return counts
