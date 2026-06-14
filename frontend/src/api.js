import { call } from 'frappe-ui'

// Execution endpoints (run / stop / sync) live in api.py; read-only page queries
// live in queries.py.
const M = 'testcase_manager.testcase_manager.api'
const Q = 'testcase_manager.testcase_manager.queries'

export const api = {
  // ── Read-only queries ──────────────────────────────────────────────
  getInstalledApps: () => call(`${Q}.get_installed_apps_list`),
  getAppLogos: () => call(`${Q}.get_app_logos`),
  getReferenceOptions: (app, reference_type) =>
    call(`${Q}.get_reference_options`, { app, reference_type }),
  getTestCases: (args) => call(`${Q}.get_test_cases_for_page`, args),
  getRunCount: (filters) => call(`${Q}.get_run_count`, { filters: JSON.stringify(filters || {}) }),
  getActiveRun: (current) => call(`${Q}.get_active_run`, current ? { current } : {}),
  // Live (partial) output of a running test, read from the worker's Redis snapshot
  // so it works even when realtime sockets don't reach the client.
  getLiveOutput: (run_name) =>
    call('testcase_manager.testcase_manager.executor.get_live_output', { run_name }),

  // ── Execution ──────────────────────────────────────────────────────
  runTestCase: (test_case, run_scope = 'Method', background = 0) =>
    call(`${M}.run_test_case`, { test_case, run_scope, background }),
  runTestBatch: (test_cases, background = 0) =>
    call(`${M}.run_test_batch`, { test_cases: JSON.stringify(test_cases), background }),
  runAppTests: (app) => call(`${M}.run_app_tests`, { app }),
  stopRun: (run_name, partial_output) =>
    call(`${M}.stop_run`, { run_name, partial_output }),
  syncTestCases: (args) => call(`${M}.sync_test_cases`, args),
}
