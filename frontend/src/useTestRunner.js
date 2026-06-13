import { reactive, ref } from 'vue'
import { api } from './api'
import { stripAnsi } from './utils'
import { useSocket } from './socket'

/**
 * Encapsulates the test-run lifecycle: starting single / batch / whole-app runs,
 * streaming realtime console output, computing the summary, and stopping.
 *
 * Ported from the original Desk page controller (test_runner.js) but built around
 * Vue reactivity instead of jQuery DOM manipulation. The backend API and the
 * realtime event contract (test_output / test_completed) are unchanged.
 *
 * Realtime delivery: the executor publishes with task_id=run_name, so events land
 * in the `task_progress:<run_name>` room. The client MUST `task_subscribe` to that
 * room (see subscribe()) or no live output arrives.
 */
function createRunner() {
  const socket = useSocket()

  const lines = ref([]) // [{ text }]
  const status = ref('') // Queuing… / Running / Passed / Failed / Error / Stopped
  const runLabel = ref('Console')
  const currentRun = ref(null)
  const lastRun = ref(null) // survives end-of-session (for the "open log" link)
  const logName = ref(null)
  const isRunning = ref(false)
  const summary = reactive({ show: false, ok: true, stopped: false, passed: 0, failed: 0, errors: 0 })
  // Live progress while a run streams: how many tests have finished vs the total
  // the run was started with (`total` is 0 when unknown, e.g. whole-app runs),
  // plus running pass/fail tallies parsed from the stream.
  const progress = reactive({ done: 0, total: 0, passed: 0, failed: 0, errors: 0 })

  let stopped = false
  let session = null
  let pendingNext = null

  function appendLine(text) {
    lines.value.push({ text: stripAnsi(text ?? '') })
  }

  function clearConsole() {
    lines.value = []
    summary.show = false
    summary.stopped = false
    status.value = ''
    logName.value = null
    runLabel.value = 'Console'
  }

  // ── Realtime ──────────────────────────────────────────────────────────────
  // A finished-test line looks like "   ✔ test_name (1.2s)" / "✖ …" / "= …".
  // The "▸ running …" line marks a *start*, so it's deliberately excluded.
  const DONE_LINE = /^\s*[✔✖=xu]\s/
  const PASS_LINE = /^\s*[✔=]\s/ // ✔ passed, = skipped (counted as not-failed)

  function tally(text) {
    if (!DONE_LINE.test(text)) return
    progress.done += 1
    if (PASS_LINE.test(text)) progress.passed += 1
    else progress.failed += 1 // ✖ — a failure or error (split exactly at completion)
  }

  function onOutput(data) {
    if (data.run_name !== currentRun.value) return
    tally(stripAnsi(data.line ?? ''))
    appendLine(data.line)
  }
  function onCompleted(data) {
    if (data.run_name !== currentRun.value) return
    handleComplete(data, false)
  }
  socket.on('test_output', onOutput)
  socket.on('test_completed', onCompleted)

  // No-op: the runner is a singleton shared across route navigations, so its
  // socket listeners (and console state) intentionally outlive any single page.
  function dispose() {}

  function subscribe(runName) {
    if (currentRun.value && currentRun.value !== runName) {
      socket.emit('task_unsubscribe', currentRun.value)
    }
    currentRun.value = runName
    socket.emit('task_subscribe', runName)
  }

  // ── Session lifecycle ───────────────────────────────────────────────────
  function startSession(label, total = 0) {
    clearConsole()
    stopped = false
    session = { active: true, passed: 0, failed: 0, errors: 0 }
    progress.done = 0
    progress.total = total
    progress.passed = 0
    progress.failed = 0
    progress.errors = 0
    isRunning.value = true
    runLabel.value = label
    status.value = 'Queuing…'
  }

  function endSession() {
    if (session) session.active = false
    isRunning.value = false
    currentRun.value = null
  }

  function renderSummary(status_label) {
    const ok = session.failed + session.errors === 0
    summary.ok = ok
    summary.passed = session.passed
    summary.failed = session.failed
    summary.errors = session.errors
    summary.show = true
    // Sync the live footer tally with the authoritative final counts (the stream
    // can't tell a failure from an error; the completion event can).
    progress.passed = session.passed
    progress.failed = session.failed
    progress.errors = session.errors
    // No console summary line / banner — the footer shows the final tally.
    status.value = ok ? 'Passed' : 'Failed'
  }

  function handleComplete(data, inline) {
    if (stopped) return
    if (!inline) socket.emit('task_unsubscribe', currentRun.value)

    if (session) {
      session.passed += data.passed || 0
      session.failed += data.failed || 0
      session.errors += data.errors || 0
    }

    // Re-render from full_output only if streaming clearly missed a chunk.
    if (data.full_output && !inline) {
      const seen = lines.value.length
      const total = data.full_output.split('\n').length
      if (seen < total * 0.6) {
        lines.value = []
        data.full_output.split('\n').forEach(appendLine)
      }
    }
    if (data.duration) appendLine(`Duration: ${data.duration}s`)

    renderSummary(data.status)
    if (data.log_name) logName.value = data.log_name
    endSession()

    if (pendingNext) {
      const next = pendingNext
      pendingNext = null
      currentRun.value = null
      setTimeout(next, 300)
    }
  }

  // ── Run actions ───────────────────────────────────────────────────────────
  // Render a finished inline run from the API response (background=0): there is
  // no realtime stream, so the full output and summary arrive all at once.
  function renderInline(result) {
    if (stopped) return
    if (result.full_output) {
      lines.value = []
      result.full_output.split('\n').forEach(appendLine)
    }
    if (session) {
      session.passed += result.passed || 0
      session.failed += result.failed || 0
      session.errors += result.errors || 0
    }
    if (result.duration) appendLine(`Duration: ${result.duration}s`)
    renderSummary(result.status)
    if (result.log_name) logName.value = result.log_name
    endSession()
  }

  async function runOne(testCaseName, label, realtime = true) {
    startSession(label, 1)
    status.value = 'Running'
    appendLine(`▶ Running test: ${label}`)
    if (!realtime) appendLine('Running inline — output appears when finished…')
    appendLine('')
    try {
      // Realtime → background job, worker streams per-test progress live.
      // Inline (realtime off) → blocks the request, output returned at the end.
      const res = await api.runTestCase(testCaseName, 'Method', realtime ? 1 : 0)
      lastRun.value = res.run_name
      if (realtime) subscribe(res.run_name)
      else renderInline(res.result || {})
    } catch (e) {
      appendLine('✖ Failed to start the test (API error).')
      endSession()
    }
  }

  async function runBatch(names, realtime = true) {
    startSession(`${names.length} tests (batch)`, names.length)
    status.value = 'Running'
    appendLine(`▶ Running ${names.length} tests together (one shared setup)`)
    appendLine(
      realtime
        ? 'Please wait — test environment is being prepared…'
        : 'Running inline — output appears when finished…',
    )
    appendLine('')
    try {
      const res = await api.runTestBatch(names, realtime ? 1 : 0)
      lastRun.value = res.run_name
      if (realtime) subscribe(res.run_name)
      else renderInline(res.result || {})
    } catch (e) {
      appendLine('✖ Failed to start the batch (API error).')
      endSession()
    }
  }

  function runSelected(names, records, realtime = true) {
    if (!names.length) return
    if (names.length === 1) {
      const rec = records.find((r) => r.name === names[0])
      return runOne(names[0], rec?.test_method || names[0], realtime)
    }
    return runBatch(names, realtime)
  }

  async function runEntireApp(app, total = 0) {
    startSession(`Entire test suite for: ${app}`, total)
    appendLine(`▶ Running the entire test suite for: ${app}`)
    appendLine('This runs in the background and may take several minutes…')
    appendLine('')
    try {
      const res = await api.runAppTests(app)
      lastRun.value = res.run_name
      subscribe(res.run_name)
      status.value = 'Running'
    } catch (e) {
      appendLine('✖ Failed to start the app run (API error).')
      endSession()
    }
  }

  // Reconnect to a run that's still in progress (e.g. after a page reload):
  // seed the console from its saved output and subscribe for further events.
  // No-op if we're already streaming this run.
  function resume(run) {
    if (!run || !run.name) return
    if (currentRun.value === run.name || lastRun.value === run.name) return
    startSession(run.test_method || run.name)
    status.value = 'Running'
    const seed = (run.full_output || '').split('\n')
    if (seed.length === 1 && seed[0] === '') seed.length = 0
    seed.forEach((text) => {
      tally(stripAnsi(text))
      appendLine(text)
    })
    lastRun.value = run.name
    subscribe(run.name)
  }

  async function stop() {
    stopped = true
    const running = currentRun.value
    pendingNext = null
    if (running) {
      socket.emit('task_unsubscribe', running)
      // Send the console text already streamed so the History page can show what
      // ran before the stop (a force-killed worker can't flush its own output).
      const partial = lines.value.map((l) => l.text).join('\n')
      try {
        await api.stopRun(running, partial)
      } catch (e) {
        /* best effort */
      }
    }
    currentRun.value = null
    appendLine('')
    appendLine('■ Stopped by user.')
    status.value = 'Stopped'
    summary.show = true
    summary.ok = false
    summary.stopped = true
    endSession()
  }

  return {
    lines,
    status,
    runLabel,
    currentRun,
    lastRun,
    logName,
    isRunning,
    summary,
    progress,
    clearConsole,
    resume,
    runOne,
    runSelected,
    runEntireApp,
    stop,
    dispose,
  }
}

// Shared singleton so the console output and run status persist when the user
// navigates away (e.g. to History) and back. A new run still auto-clears via
// startSession() → clearConsole().
let _instance = null
export function useTestRunner() {
  if (!_instance) _instance = createRunner()
  return _instance
}
