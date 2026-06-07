<div align="center" markdown="1">

<h1>Testcase Manager</h1>

**Discover, run, and track your Frappe tests from a modern web UI**

[![CI](https://github.com/Nihantra-Patel/testcase_manager/actions/workflows/ci.yml/badge.svg)](https://github.com/Nihantra-Patel/testcase_manager/actions/workflows/ci.yml)

</div>

---

## Overview

Running Frappe tests usually means dropping to a terminal, remembering the right
`bench run-tests` incantation, and reading scrollback to figure out what passed.
**Testcase Manager** replaces that workflow with a purpose-built web application.

It automatically discovers every `test_*.py` test across your installed apps,
stores each test method as a first-class record, and lets you run any test —
a single method, a whole DocType, or an entire app — from the browser. Output
streams to a live console in real time, and every run is saved with its full
output, pass/fail counts, and timing for later inspection.

The interface is a single-page application built with [Frappe UI](https://ui.frappe.io)
(Vue 3), served at `/testcase_manager`.

## Who it's for

- **Developers** who want a faster feedback loop while writing tests, without
  leaving the browser or memorising CLI flags.
- **QA / reviewers** who need to run a specific suite and share a link to the
  result.
- **Teams** who want a persistent, searchable history of test runs on a site.

## Key Features

- **Automatic discovery** — finds `test_*.py` files across installed apps using
  AST parsing, so no test modules are imported (and no side effects run) during
  discovery.
- **Flexible run scopes** — execute a single **Method**, a whole **File**, all
  tests for a **DocType**, an entire **App**, or a **Batch** of hand-picked tests
  that share a single (expensive) environment setup.
- **Realtime console** — test output streams live to the UI over websockets
  while the run is in progress.
- **Inline & background execution** — small selections run inline for instant
  feedback; large selections and whole-app runs are dispatched to background
  workers so the UI stays responsive.
- **Persistent history** — every run is recorded in `Testcase Run` (with full
  output, status, and duration) and `Testcase Log` (with pass/fail/error counts),
  browsable through a paginated, filterable History view.
- **Stop control** — abort a queued or running job; partial output is preserved.
- **Automatic sync** — discovered tests are kept up to date after every
  migration and on a daily schedule.

## Architecture

Testcase Manager is a standard Frappe app with a Vue frontend.

```
testcase_manager/
├── frontend/                     # Vue 3 + Frappe UI single-page app (Vite)
│   └── src/
│       ├── pages/                # Runner, History, Run detail views
│       ├── useTestRunner.js      # run lifecycle + realtime state (shared)
│       └── api.js                # typed wrappers over the whitelisted endpoints
└── testcase_manager/
    ├── testcase_manager/
    │   ├── api.py                # whitelisted endpoints consumed by the SPA
    │   ├── discovery.py          # AST-based test discovery & sync
    │   ├── executor.py           # runs tests in-process, streams realtime output
    │   └── doctype/              # Testcase, Testcase Run, Testcase Log
    ├── www/testcase_manager.html # built SPA entry page (generated)
    └── hooks.py                  # routing, scheduler, log retention
```

**Request flow**

1. **Discovery** (`discovery.py`) scans installed apps for `test_*.py` files and
   upserts every test method into the `Testcase` DocType.
2. The **frontend** lists those records and calls a whitelisted API method to
   start a run, which creates a `Testcase Run`.
3. The **executor** (`executor.py`) runs the selected tests in-process and
   publishes `test_output` / `test_completed` events via `frappe.publish_realtime`.
4. On completion, the run's full output, status, duration, and counts are
   persisted to `Testcase Run` and a `Testcase Log`.

### Data model

| DocType        | Purpose                                                              |
| -------------- | ------------------------------------------------------------------- |
| `Testcase`     | A discovered test method (app, module, path, reference DocType/Report). |
| `Testcase Run` | One execution (scope, status, timing, full output, traceback).      |
| `Testcase Log` | Result summary for a run (pass / fail / error counts, duration).    |

### Routing

`website_route_rules` in `hooks.py` maps `/testcase_manager/<path:app_path>` to
the SPA page (`www/testcase_manager.html`), so the Vue Router's history-mode
routes (`/`, `/history`, `/history/<run>`) all resolve to the app.

### Automatic sync

Configured via `hooks.py`:

| Hook                       | Behaviour                                  |
| -------------------------- | ------------------------------------------ |
| `after_migrate`            | Full re-sync of discovered tests after every `bench migrate`. |
| `scheduler_events.daily`   | Daily full re-sync.                        |

### Log retention

`Testcase Run` and `Testcase Log` records are auto-cleared after **90 days**
via Frappe's `default_log_clearing_doctypes`.

## Built with

- [Frappe Framework](https://github.com/frappe/frappe) — full-stack web framework
  and test runner that powers discovery and execution.
- [Frappe UI](https://github.com/frappe/frappe-ui) — Vue 3 component library and
  data layer for the frontend.
- [Vite](https://vitejs.dev) — frontend build tooling.

## Requirements

- A working [Frappe Bench](https://github.com/frappe/bench) (Frappe v16+).
- **Python** ≥ 3.14
- **Node.js** 20+ and **Yarn** (only needed to build the frontend).

## Installation

From your bench directory:

```bash
# 1. Fetch the app
bench get-app https://github.com/Nihantra-Patel/testcase_manager.git

# 2. Install it on a site
bench --site your-site.localhost install-app testcase_manager

# 3. Build the frontend assets
bench build --app testcase_manager
```

Then open **`https://your-site.localhost/testcase_manager`** in a browser
(you must be logged in).

> The built frontend (`public/frontend/` and `www/testcase_manager.html`) is
> generated by the build step and is not committed to the repository, so
> `bench build` is required after install and after pulling changes.

## Usage

### Runner

The **Runner** is the main view. Filter the test list by **App**, **Type**
(DocType / Report), a specific **DocType / Report**, or a method-name search,
then:

- Run a single test with its inline ▶ button, or
- Select multiple tests and **Run Selected** (executed as one batch with a shared
  setup), or
- **Run Entire App** to execute the app's full suite.

Output streams to the console on the right; a status badge and a pass/fail
summary appear when the run finishes. Use **Stop** to abort a running job.

### History

The **History** view lists past runs with their app, scope, type, status,
duration, and timestamp. It supports a total count, page sizes of
20 / 50 / 100 / 500 / 2500, filters (App, Status, Type), and a title search.
Click any row to open the full saved output.

## Development

The backend is a normal Frappe app; the frontend is a Vite project under
`frontend/`.

```bash
# Frontend dev server with hot-module reload (proxies API calls to your bench)
cd apps/testcase_manager/frontend
yarn install
yarn dev

# Production build (outputs to ../testcase_manager/public/frontend and copies
# the entry page to ../testcase_manager/www/testcase_manager.html)
yarn build
```

`bench build --app testcase_manager` runs the same production build via the app's
root `package.json`.

### Running the test suite

```bash
bench --site your-site.localhost set-config allow_tests true
bench --site your-site.localhost run-tests --app testcase_manager
```

### Continuous Integration

GitHub Actions run on every push to `develop` and on pull requests:

- **CI** — pre-commit checks, builds the Vue frontend, then runs the server-side
  test suite against a fresh site.
- **Linters** — pre-commit, Semgrep (Frappe rules), and a vulnerable-dependency
  audit.

Code style is enforced by [pre-commit](https://pre-commit.com)
(Ruff for Python; Prettier and ESLint for Desk-side JS):

```bash
pre-commit install
pre-commit run --all-files
```

## License

[MIT](license.txt)
