import { call } from 'frappe-ui'

const M = 'testcase_manager.testcase_manager.api'

export const api = {
  getInstalledApps: () => call(`${M}.get_installed_apps_list`),
  getReferenceOptions: (app, reference_type) =>
    call(`${M}.get_reference_options`, { app, reference_type }),
  getTestCases: (args) => call(`${M}.get_test_cases_for_page`, args),
  runTestCase: (test_case, run_scope = 'Method', background = 0) =>
    call(`${M}.run_test_case`, { test_case, run_scope, background }),
  runTestBatch: (test_cases, background = 0) =>
    call(`${M}.run_test_batch`, { test_cases: JSON.stringify(test_cases), background }),
  runAppTests: (app) => call(`${M}.run_app_tests`, { app }),
  stopRun: (run_name, partial_output) =>
    call(`${M}.stop_run`, { run_name, partial_output }),
  syncTestCases: (args) => call(`${M}.sync_test_cases`, args),
  getRunCount: (filters) => call(`${M}.get_run_count`, { filters: JSON.stringify(filters || {}) }),
}
