# Testcase Manager

UI-based Test Case Management and Test Runner for Frappe.

This app discovers `test_*.py` tests from installed apps, stores them as first-class records, and lets you run tests from Desk with realtime output and execution history.

## Key Features

- Automatic test discovery using AST (no test module imports during discovery).
- Stores discovered tests in `Testcase` records.
- Desk page runner (`test-runner`) with filters (app, type, reference, method search).
- Run scopes:
	- Method
	- File
	- DocType
	- App
- Realtime console streaming while tests run in background jobs.
- Persistent run history in:
	- `Testcase Run`
	- `Testcase Log`
- Stop queued/running jobs (best effort).
- Scheduled and migrate-time sync of discovered tests.

## Installation

Install using Bench:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench --site $YOUR_SITE install-app testcase_manager
```

## How It Works

1. Discovery scans installed app folders for `test_*.py` files.
2. Test methods are extracted from AST and upserted into `Testcase`.
3. From the Test Runner page, selected tests are queued as background jobs.
4. Execution streams output in realtime and writes final results.
5. Summaries and traceback are persisted on `Testcase Run` and `Testcase Log`.

## Auto Sync Hooks

Configured in app hooks:

- `after_migrate`: full test sync after every `bench migrate`
- `scheduler_events.daily`: daily full re-sync

## API Endpoints

Whitelisted API methods (browser-callable via `frappe.call`):

- `testcase_manager.testcase_manager.api.sync_test_cases`
- `testcase_manager.testcase_manager.api.get_test_cases_for_page`
- `testcase_manager.testcase_manager.api.run_test_case`
- `testcase_manager.testcase_manager.api.stop_run`
- `testcase_manager.testcase_manager.api.rerun_test`
- `testcase_manager.testcase_manager.api.run_app_tests`
- `testcase_manager.testcase_manager.api.get_installed_apps_list`
- `testcase_manager.testcase_manager.api.get_reference_options`
- `testcase_manager.testcase_manager.api.get_app_modules`

## Development

Python requirement:

- `>=3.14`

Triggered on:

- push to `develop`
- pull requests

## License

MIT
