import { reactive, ref } from 'vue'
import { toast } from 'frappe-ui'
import { api } from '@/api'
import { useSocket } from '@/socket'
import { stripAnsi } from '@/utils'

/**
 * useTestRunner — drives a single test run (one test, a batch, or a whole app)
 * and exposes reactive state for RunnerView.
 *
 * Live console output arrives over the socket as `test_output` events; the run
 * lifecycle is tracked via `test_started` / `test_completed`. Inline API calls
 * (single test / small batch) also return a `result` payload directly, which we
 * fold in so the UI renders even though the browser only subscribes after the
 * call returns.
 *
 * All public scalar state is a `ref`, so the template accesses `.value`
 * (e.g. `runner.isRunning.value`), matching RunnerView's usage.
 */
export function useTestRunner() {
  const isRunning = ref(false)
  const status = ref('') // '', 'Running', 'Passed', 'Failed', 'Error', 'Stopped'
  const lines = ref([]) // [{ text }]
  const runLabel = ref('No active run')
  const lastRun = ref('')

  const summary = reactive({
    show: false,
    ok: false,
    stopped: false,
    passed: 0,
    failed: 0,
    errors: 0,
  })

  // The run we are currently subscribed to; realtime events are filtered by it.
  let currentRun = null
  const socket = useSocket()

  function resetConsole(label) {
    runLabel.value = label
    lines.value = []
    status.value = 'Running'
    isRunning.value = true
    lastRun.value = ''
    summary.show = false
    summary.stopped = false
    summary.ok = false
    summary.passed = 0
    summary.failed = 0
    summary.errors = 0
  }

  function pushLine(text) {
    lines.value.push({ text: stripAnsi(String(text ?? '')) })
  }

  // ── Realtime handlers ──────────────────────────────────────────────────────
  function onOutput(data) {
    if (!data || data.run_name !== currentRun) return
    pushLine(data.line)
  }

  function onStarted(data) {
    if (!data || data.run_name !== currentRun) return
    status.value = 'Running'
    isRunning.value = true
  }

  function onCompleted(data) {
    if (!data || data.run_name !== currentRun) return
    applyResult(data)
  }

  function subscribe() {
    if (!socket) return
    socket.on('test_output', onOutput)
    socket.on('test_started', onStarted)
    socket.on('test_completed', onCompleted)
  }

  function unsubscribe() {
    if (!socket) return
    socket.off('test_output', onOutput)
    socket.off('test_started', onStarted)
    socket.off('test_completed', onCompleted)
  }

  /** Fold a completed-run payload (from realtime or an inline API result). */
  function applyResult(r) {
    if (!r) return
    if (r.full_output && lines.value.length === 0) {
      for (const l of String(r.full_output).split('\n')) pushLine(l)
    }
    status.value = r.status || 'Passed'
    summary.passed = r.passed || 0
    summary.failed = r.failed || 0
    summary.errors = r.errors || 0
    summary.ok = r.status === 'Passed'
    summary.stopped = r.status === 'Stopped'
    summary.show = true
    isRunning.value = false
    lastRun.value = r.run_name || currentRun || ''
  }

  // ── Run kickoff helpers ─────────────────────────────────────────────────────
  function begin(res) {
    // `res` is the API response: { run_name, task_id, background, result? }
    currentRun = res.run_name
    if (res.result) {
      // Inline run already finished; render its result directly.
      applyResult(res.result)
    }
    // For background runs (or to catch trailing inline events) we stay
    // subscribed; realtime events update the console live.
  }

  function failKickoff(err) {
    pushLine(`Failed to start run: ${err?.message || err}`)
    status.value = 'Error'
    isRunning.value = false
    summary.show = false
    toast({ title: 'Could not start test run', icon: 'x', iconClasses: 'text-red-600' })
  }

  // ── Public actions ──────────────────────────────────────────────────────────
  async function runOne(testCase, methodName) {
    subscribe()
    resetConsole(methodName || testCase)
    try {
      begin(await api.runTestCase(testCase, 'Method', 0))
    } catch (e) {
      failKickoff(e)
    }
  }

  async function runSelected(names, records) {
    const list = Array.isArray(names) ? names : []
    if (!list.length) return
    subscribe()
    resetConsole(`${list.length} selected test(s)`)
    // Large selections run in the background to avoid blocking the request.
    const background = list.length > 20 ? 1 : 0
    try {
      begin(await api.runTestBatch(list, background))
    } catch (e) {
      failKickoff(e)
    }
  }

  async function runEntireApp(app) {
    if (!app) return
    subscribe()
    resetConsole(`Entire test suite for: ${app}`)
    try {
      begin(await api.runAppTests(app))
    } catch (e) {
      failKickoff(e)
    }
  }

  async function stop() {
    if (!currentRun) return
    const partial = lines.value.map((l) => l.text).join('\n')
    try {
      await api.stopRun(currentRun, partial)
    } catch (e) {
      /* best-effort */
    }
    status.value = 'Stopped'
    isRunning.value = false
    summary.stopped = true
    summary.ok = false
    summary.show = true
    lastRun.value = currentRun
  }

  function dispose() {
    unsubscribe()
    currentRun = null
  }

  return {
    isRunning,
    status,
    lines,
    runLabel,
    lastRun,
    summary,
    runOne,
    runSelected,
    runEntireApp,
    stop,
    dispose,
  }
}
