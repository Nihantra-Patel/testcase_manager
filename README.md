# Testcase Manager

UI-based Test Case Management and Test Runner for Frappe, with a modern
[Frappe UI](https://ui.frappe.io/) (Vue 3) single-page app.

This app discovers `test_*.py` tests from installed apps, stores them as
first-class records, and lets you run tests from a dedicated web UI with realtime
output and execution history.

## Frontend (Frappe UI / Vue)

The primary interface is a Vue 3 + Frappe UI SPA served at:

```
/testcase_manager
```

It has two views:

- **Runner** — filter tests (App, Type, DocType/Report, method search), select and
  run them, and watch realtime console output stream in a split-pane layout.
- **History** — paginated run history with a total count, page-size selector
  (20 / 50 / 100 / 500 / 2500), filters (App, Status, Type), and a Type column.
  Click any row to open the full run output.

The legacy Desk page runner (`/app/test-runner`) is kept as a fallback.

### Frontend behaviour notes

- **Filter persistence:** on the Runner, the App / Type / DocType-Report filters
  persist across page reloads via `localStorage`; only the *Search Method* field is
  cleared on each load. **Reset Filters** clears everything. History filters
  (App / Status / Type / Page size) persist the same way.
- **Console persistence:** the console output and run status survive navigation
  between Runner and History (the runner is a shared singleton). The console only
  auto-clears when a *new* run starts.

## Key Features

- Automatic test discovery using AST (no test module imports during discovery).
- Stores discovered tests in `Testcase` records.
- Vue/Frappe UI runner at `/testcase_manager` (plus legacy Desk page `test-runner`).
- Run scopes:
	- Method
	- File
	- DocType
	- App
	- Batch (multiple selected tests in one shared environment setup)
- Realtime console streaming while tests run (inline or background jobs).
- Persistent run history in:
	- `Testcase Run`
	- `Testcase Log`
- Stop queued/running jobs (best effort).
- Scheduled and migrate-time sync of discovered tests.

## Installation

Install using Bench:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch version-2
bench --site $YOUR_SITE install-app testcase_manager
```

Then build the frontend assets:

```bash
bench build --app testcase_manager
```

Open `https://<your-site>/testcase_manager` (you must be logged in).

## How It Works

1. Discovery scans installed app folders for `test_*.py` files.
2. Test methods are extracted from AST and upserted into `Testcase`.
3. From the Runner, selected tests run inline (small selections) or as background
   jobs (large selections / "Run Entire App").
4. Execution streams output in realtime via `frappe.publish_realtime`
   (`test_output` / `test_completed` events) and writes final results.
5. Summaries and traceback are persisted on `Testcase Run` and `Testcase Log`.

## Auto Sync Hooks

Configured in app hooks:

- `after_migrate`: full test sync after every `bench migrate`
- `scheduler_events.daily`: daily full re-sync

## Routing

- `website_route_rules` maps `/testcase_manager/<path:app_path>` to the SPA page
  (`www/testcase_manager.html`) so vue-router history-mode routes resolve.



### Backend

Python requirement:

- `>=3.14`

### Frontend

The Vue app lives in `frontend/` (Vite + Vue 3 + Frappe UI).

```bash
cd apps/testcase_manager/frontend
yarn install          # first time (also runs automatically via the app's package.json)
yarn dev              # Vite dev server with HMR (proxies API to your bench)
yarn build            # production build -> testcase_manager/public/frontend
                      #   and copies index.html -> testcase_manager/www/testcase_manager.html
```

`bench build --app testcase_manager` runs the production build via the app's root
`package.json`.

CI is triggered on:

- push to `develop`
- pull requests

## License

MIT
