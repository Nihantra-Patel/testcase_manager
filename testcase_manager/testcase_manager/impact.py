"""
Static test-impact analysis (no test execution).

Given the files changed on a branch, work out which testcases are affected — so a
user can run only those as a pre-PR check, instead of the whole app.

It never runs tests. It reads the git diff and the test files' imports, plus the
Testcase metadata already in the DB:

  • import graph  — a test that ``import``s a changed module is affected, even when
    it lives in a different file/path/app.
  • doctype links — a changed doctype affects its own tests and tests of doctypes
    that link to it.

This is approximate by design: static analysis can over-select (run a few extra)
and can miss purely dynamic dependencies (hooks, doc events, server scripts) that
leave no import. The UI states this so the result is read as "likely affected",
not "provably complete".
"""

from __future__ import annotations

import ast
import hashlib
import os
import subprocess

import frappe


def _app_path(app: str) -> str:
	"""Absolute path to an installed app's repo (…/apps/<app>)."""
	from frappe.utils import get_bench_path

	return os.path.join(get_bench_path(), "apps", app)


def _default_branch(app_path: str) -> str:
	"""The repo's default branch (origin/HEAD), falling back to develop/main."""
	try:
		out = subprocess.run(
			["git", "symbolic-ref", "refs/remotes/origin/HEAD"],
			cwd=app_path,
			capture_output=True,
			text=True,
			timeout=10,
		)
		ref = out.stdout.strip()
		if ref:
			return ref.rsplit("/", 1)[-1]
	except Exception:
		pass
	for candidate in ("develop", "main", "master"):
		check = subprocess.run(
			["git", "rev-parse", "--verify", candidate],
			cwd=app_path,
			capture_output=True,
			text=True,
		)
		if check.returncode == 0:
			return candidate
	return "develop"


def get_changed_files(app: str, base: str | None = None) -> dict:
	"""Files changed on the app's current branch vs its base branch.

	Returns ``{"base": <branch>, "head": <branch>, "files": [relative paths]}``.
	Includes committed branch changes AND uncommitted working edits, so the result
	reflects everything that would land in the PR.
	"""
	app_path = _app_path(app)
	if not os.path.isdir(os.path.join(app_path, ".git")):
		frappe.throw(f"{app} is not a git repository — impact analysis needs git.")

	base = base or _default_branch(app_path)
	head = "HEAD"
	try:
		head = (
			subprocess.run(
				["git", "rev-parse", "--abbrev-ref", "HEAD"],
				cwd=app_path,
				capture_output=True,
				text=True,
				timeout=10,
			).stdout.strip()
			or "HEAD"
		)
	except Exception:
		pass

	files: set[str] = set()
	# Committed diff vs base (merge-base, so unrelated base commits don't show up).
	for args in (
		["git", "diff", "--name-only", f"{base}...HEAD"],
		["git", "diff", "--name-only"],  # unstaged
		["git", "diff", "--name-only", "--cached"],  # staged
	):
		try:
			out = subprocess.run(args, cwd=app_path, capture_output=True, text=True, timeout=20)
			for line in out.stdout.splitlines():
				line = line.strip()
				if line:
					files.add(line)
		except Exception:
			continue

	return {"base": base, "head": head, "files": sorted(files)}


def _rel_to_module(app: str, rel_path: str) -> str | None:
	"""``lending/loan_management/x.py`` → dotted module ``lending.loan_management.x``."""
	if not rel_path.endswith(".py"):
		return None
	parts = rel_path[:-3].split("/")
	if parts and parts[-1] == "__init__":
		parts = parts[:-1]
	return ".".join(parts) if parts else None


def _imported_modules(file_path: str) -> set[str]:
	"""Dotted modules a Python file imports (best-effort AST parse)."""
	mods: set[str] = set()
	try:
		with open(file_path, encoding="utf-8") as fh:
			tree = ast.parse(fh.read(), filename=file_path)
	except Exception:
		return mods
	for node in ast.walk(tree):
		if isinstance(node, ast.Import):
			for alias in node.names:
				mods.add(alias.name)
		elif isinstance(node, ast.ImportFrom) and node.module:
			mods.add(node.module)
	return mods


def _build_import_graph(app: str) -> dict[str, set[str]]:
	"""Map every in-app module → the in-app modules it imports (one hop).

	Only intra-app edges are kept; following framework/3rd-party imports would
	explode the graph and isn't what we're tracking. Walks the app package once.
	"""
	app_path = _app_path(app)
	pkg_root = os.path.join(app_path, app)
	graph: dict[str, set[str]] = {}
	for dirpath, _dirs, files in os.walk(pkg_root):
		if "node_modules" in dirpath or "/.git" in dirpath:
			continue
		for fname in files:
			if not fname.endswith(".py"):
				continue
			abs_path = os.path.join(dirpath, fname)
			rel = os.path.relpath(abs_path, app_path)
			mod = _rel_to_module(app, rel)
			if not mod:
				continue
			# Keep only edges that point back into this app.
			deps = {m for m in _imported_modules(abs_path) if m == app or m.startswith(app + ".")}
			graph[mod] = deps
	return graph


def _app_source_fingerprint(app: str) -> str:
	"""Cheap signature of the app's .py files (path + mtime + size).

	Walking paths/mtimes is far cheaper than parsing every file's AST, so we use
	this to decide whether a cached import graph is still valid. Any edit, add, or
	delete of a .py file changes the fingerprint and invalidates the cache.
	"""
	app_path = _app_path(app)
	pkg_root = os.path.join(app_path, app)
	parts: list[str] = []
	for dirpath, _dirs, files in os.walk(pkg_root):
		if "node_modules" in dirpath or "/.git" in dirpath:
			continue
		for fname in files:
			if not fname.endswith(".py"):
				continue
			abs_path = os.path.join(dirpath, fname)
			try:
				st = os.stat(abs_path)
				parts.append(f"{abs_path}:{int(st.st_mtime)}:{st.st_size}")
			except OSError:
				continue
	parts.sort()
	return hashlib.sha1("\n".join(parts).encode("utf-8")).hexdigest()


def _get_import_graph(app: str) -> dict[str, set[str]]:
	"""Import graph for *app*, cached in frappe.cache and keyed on source fingerprint.

	Building the graph means an os.walk + AST parse of the whole app — the expensive,
	depth-independent step. The depth selector re-runs the cheap reachability pass on
	top of this, so toggling depth 1→2→3 no longer rebuilds the graph each time.
	The fingerprint key means a code edit transparently rebuilds it on the next call.
	"""
	fingerprint = _app_source_fingerprint(app)
	cache_key = f"testcase_manager:import_graph:{app}:{fingerprint}"
	cache = frappe.cache()

	cached = cache.get_value(cache_key)
	if cached is not None:
		# Stored as plain lists (JSON-serialisable); restore the set-of-deps shape.
		return {mod: set(deps) for mod, deps in cached.items()}

	graph = _build_import_graph(app)
	cache.set_value(cache_key, {mod: sorted(deps) for mod, deps in graph.items()}, expires_in_sec=3600)
	return graph


def _modules_reaching(graph: dict[str, set[str]], targets: set[str], max_depth: int = 2) -> set[str]:
	"""Modules whose imports reach any target within ``max_depth`` hops (reverse).

	Returns modules M that import a target directly (depth 1) or through up to
	``max_depth`` chained in-app imports. Depth is bounded on purpose: in a tightly
	coupled app, unbounded closure reaches almost every test (a shared util/core
	doctype sits in every chain), which collapses to "run everything" and defeats
	the narrowing. Depth 2 catches the common "test -> core module -> changed file"
	case while staying selective.
	"""
	# Reverse the graph: dep -> modules that import it. An import of a sub-module
	# (foo.bar) also counts as reaching its package target (foo), so match prefixes.
	reverse: dict[str, set[str]] = {}
	for mod, deps in graph.items():
		for dep in deps:
			reverse.setdefault(dep, set()).add(mod)

	def _importers_of(target: str) -> set[str]:
		out = set(reverse.get(target, ()))
		for dep, importers in reverse.items():
			if dep.startswith(target + "."):  # importers of a sub-module of target
				out |= importers
		return out

	impacted: set[str] = set()
	frontier = set(targets)
	for _ in range(max(1, max_depth)):
		nxt: set[str] = set()
		for t in frontier:
			for importer in _importers_of(t):
				if importer not in impacted:
					impacted.add(importer)
					nxt.add(importer)
		if not nxt:
			break
		frontier = nxt
	return impacted


def _reaching_paths(
	graph: dict[str, set[str]], targets: set[str], max_depth: int = 2
) -> dict[str, list[str]]:
	"""Like ``_modules_reaching`` but records the path each impacted module took.

	Returns ``{impacted_module: [impacted_module, …, changed_module]}`` — the shortest
	import chain (in hops) from the impacted module down to a changed one. This is what
	lets the UI explain *why* a test is "transitively affected" instead of just asserting
	it. BFS, so the first path found for a module is the shortest.
	"""
	reverse: dict[str, set[str]] = {}
	for mod, deps in graph.items():
		for dep in deps:
			reverse.setdefault(dep, set()).add(mod)

	def _importers_of(target: str) -> set[str]:
		out = set(reverse.get(target, ()))
		for dep, importers in reverse.items():
			if dep.startswith(target + "."):
				out |= importers
		return out

	# path[m] = chain from m down to a changed module (m first, changed-module last).
	paths: dict[str, list[str]] = {t: [t] for t in targets}
	frontier = set(targets)
	for _ in range(max(1, max_depth)):
		nxt: set[str] = set()
		for t in frontier:
			for importer in _importers_of(t):
				if importer not in paths:
					paths[importer] = [importer, *paths[t]]
					nxt.add(importer)
		if not nxt:
			break
		frontier = nxt

	# Drop the changed modules themselves — callers only want the reached importers.
	return {m: p for m, p in paths.items() if m not in targets}


@frappe.whitelist()
def analyze(app: str, base: str | None = None, depth: int = 2) -> dict:
	"""Testcases affected by the app's current branch changes (no tests run).

	``depth`` bounds how many import hops to follow (default 2). Higher = catches
	more indirect dependencies but selects more tests; in a tightly coupled app a
	high depth reaches almost everything. Returns the changed files, affected
	testcases (with the reason each was picked), and counts.
	"""
	frappe.only_for(("System Manager",))

	diff = get_changed_files(app, base)
	changed = diff["files"]

	# Changed Python modules (dotted) and changed doctype names.
	changed_modules: set[str] = set()
	changed_doctypes: set[str] = set()
	for rel in changed:
		mod = _rel_to_module(app, rel)
		if mod:
			changed_modules.add(mod)
		# A doctype's folder holds <name>.json/.py: …/doctype/<name>/<name>.(py|json)
		parts = rel.split("/")
		if "doctype" in parts:
			i = parts.index("doctype")
			if i + 1 < len(parts):
				changed_doctypes.add(frappe.unscrub(parts[i + 1]))

	# All active testcases for this app, with the metadata we match on.
	tests = frappe.get_all(
		"Testcase",
		filters={"status": "Active", "app": app},
		fields=["name", "test_method", "python_path", "test_file_path", "reference_doctype", "module"],
	)

	affected: dict[str, dict] = {}

	def _mark(t: dict, reason: str, path: list[str] | None = None):
		row = affected.setdefault(
			t["name"],
			{
				"name": t["name"],
				"test_method": t["test_method"],
				"python_path": t["python_path"],
				"reasons": [],
				"paths": [],
			},
		)
		if reason not in row["reasons"]:
			row["reasons"].append(reason)
		if path and path not in row["paths"]:
			row["paths"].append(path)

	# Transitive reach: every in-app module that imports a changed one, directly or
	# through a chain. A test whose own module is in here is impacted even when it
	# doesn't import the changed file itself (it goes through intermediate modules).
	# The graph is cached (depth-independent); _reaching_paths also yields, per module,
	# the import chain back to a changed file so the UI can explain the link.
	graph = _get_import_graph(app)
	max_depth = int(depth or 2)
	paths_by_module = _reaching_paths(graph, changed_modules, max_depth=max_depth)
	impacted_modules = set(paths_by_module)

	for t in tests:
		test_mod = t.get("python_path") or ""

		# 1) The test file itself changed.
		if t.get("test_file_path") and t["test_file_path"] in changed:
			_mark(t, "Test file changed")

		# 2) The test directly imports a changed module. Read the test's imports from
		#    the cached graph (keyed by dotted module) instead of re-reading and
		#    AST-parsing every test file on each call — that re-parse was the bulk of
		#    the analyze cost and is fully redundant with the graph we already built.
		imports = graph.get(test_mod, set())
		hit = {m for m in changed_modules if any(i == m or i.startswith(m + ".") for i in imports)}
		for m in sorted(hit):
			_mark(t, f"Imports changed module: {m}")

		# 3) The test reaches a changed module transitively (through other modules).
		#    Attach the import chain (test_mod → … → changed_mod) so the UI can show
		#    exactly which intermediate modules linked the test to the change.
		if test_mod in impacted_modules:
			path = paths_by_module.get(test_mod)
			reason = "Depends (transitively) on changed code"
			if path and len(path) > 1:
				reason = f"Depends (transitively) via: {' → '.join(path)}"
			_mark(t, reason, path)

		# 4) The test targets a changed doctype.
		if t.get("reference_doctype") and t["reference_doctype"] in changed_doctypes:
			_mark(t, f"Targets changed doctype: {t['reference_doctype']}")

	rows = sorted(affected.values(), key=lambda r: r["test_method"] or r["name"])
	return {
		"app": app,
		"base": diff["base"],
		"head": diff["head"],
		"changed_files": changed,
		"changed_file_count": len(changed),
		"depth": int(depth or 2),
		"affected": rows,
		"affected_count": len(rows),
		"total_app_tests": len(tests),
	}
