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
  const isRunning = ref(false)
  // True only while a Quick (inline) run is blocking the request. Realtime runs
  // are background jobs that queue via the worker lock, so they don't set this —
  // the UI disables the run buttons only during an inline run.
  const inlineRunning = ref(false)
  const summary = reactive({ show: false, ok: true, stopped: false, passed: 0, failed: 0, errors: 0 })
  // Live progress while a run streams: how many tests have finished vs the total
  // the run was started with (`total` is 0 when unknown, e.g. whole-app runs),
  // plus running pass/fail tallies parsed from the stream.
  const progress = reactive({ done: 0, total: 0, passed: 0, failed: 0, errors: 0 })

  let stopped = false
  let session = null
  let pendingNext = null
  let autoFollowing = false // console is on an auto-followed run, not one the user started
  // Page-registered callback returning the run executing now, so we can advance
  // the instant a followed run finishes instead of waiting for the next poll.
  let advanceFn = null
  function onAdvance(fn) {
    advanceFn = fn
  }
  // True once real output has arrived for the current run (it's executing, not queued).
  const streamStarted = ref(false)

  function appendLine(text) {
    lines.value.push({ text: stripAnsi(text ?? '') })
  }

  // Parse "Passed: X, Failed: Y, Errors: Z" (the run's stored result) into counts.
  function parseCounts(result) {
    const m = (result || '').match(/Passed:\s*(\d+),\s*Failed:\s*(\d+),\s*Errors:\s*(\d+)/i)
    if (!m) return { passed: 0, failed: 0, errors: 0 }
    return { passed: +m[1], failed: +m[2], errors: +m[3] }
  }

  function clearConsole() {
    lines.value = []
    summary.show = false
    summary.stopped = false
    status.value = ''
    runLabel.value = 'Console'
  }

  // ── Realtime ──────────────────────────────────────────────────────────────
  // A finished-test line looks like "   ✔ test_name (1.2s)" / "✖ …" / "= …".
  // The "▸ running …" line marks a *start*, so it's deliberately excluded.
  const DONE_LINE = /^\s*[✔✖=xu]\s/
  const PASS_LINE = /^\s*[✔=]\s/ // ✔ passed, = skipped (counted as not-failed)

  function tally(text) {
    if (!DONE_LINE.test(text)) return
    // Never let the live count exceed the known total — error tests can emit extra
    // ✖/traceback lines that would otherwise push `done` past `total` (the final
    // count is corrected authoritatively in renderSummary).
    if (progress.total && progress.done >= progress.total) return
    progress.done += 1
    if (PASS_LINE.test(text)) progress.passed += 1
    else progress.failed += 1 // ✖ — a failure or error (split exactly at completion)
  }

  function onOutput(data) {
    if (data.run_name !== currentRun.value) return
    streamStarted.value = true // real output → this run is executing, not queued
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
    startOutputPoll(runName)
  }

  // Poll the worker's live output snapshot (get_live_output) so the console works
  // even when realtime sockets don't reach the client. The fuller source wins, so
  // sockets stay an optimization.
  let outputPoll = null
  function stopOutputPoll() {
    if (outputPoll) {
      clearInterval(outputPoll)
      outputPoll = null
    }
  }
  function startOutputPoll(runName) {
    stopOutputPoll()
    outputPoll = setInterval(async () => {
      if (stopped || currentRun.value !== runName) {
        stopOutputPoll()
        return
      }
      let doc
      try {
        doc = await api.getLiveOutput(runName)
      } catch (e) {
        return
      }
      if (!doc || currentRun.value !== runName) return
      const seed = (doc.output || '').split('\n')
      if (seed.length === 1 && seed[0] === '') seed.length = 0
      // Render the snapshot when it's ahead of what's shown (or nothing streamed yet).
      const hasRealLines = streamStarted.value
      if (seed.length && (!hasRealLines || seed.length > lines.value.length)) {
        lines.value = []
        progress.done = 0
        progress.passed = 0
        progress.failed = 0
        seed.forEach((text) => {
          tally(stripAnsi(text))
          appendLine(text)
        })
        streamStarted.value = true
        status.value = 'Running'
      }
      // Finished without a completion event — wrap it up so the console doesn't hang.
      if (['Passed', 'Failed', 'Error', 'Stopped'].includes(doc.status)) {
        stopOutputPoll()
        const counts = parseCounts(doc.result)
        handleComplete(
          {
            run_name: runName,
            status: doc.status,
            full_output: doc.output,
            duration: doc.duration,
            passed: counts.passed,
            failed: counts.failed,
            errors: counts.errors,
          },
          false,
        )
      }
    }, 1000)
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
    streamStarted.value = false
    runLabel.value = label
    status.value = 'Queuing…'
  }

  function endSession() {
    if (session) session.active = false
    isRunning.value = false
    currentRun.value = null
    stopOutputPoll()
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
    // `progress.done` is tallied from stream lines while running, which can
    // over-count (error tests emit extra ✖/traceback lines), so the footer could
    // show e.g. 2655 / 2615. The completion event is authoritative: the number of
    // tests that finished is exactly passed + failed + errors.
    progress.done = session.passed + session.failed + session.errors
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
    autoFollowing = false
    endSession()

    // Advance to the next executing run now (not on the next poll), so fast
    // in-between runs aren't skipped.
    if (advanceFn) Promise.resolve(advanceFn()).catch(() => {})

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
    endSession()
  }

  async function runOne(testCaseName, label, realtime = true) {
    startSession(label, 1)
    status.value = 'Running'
    appendLine(`▶ Running test: ${label}`)
    if (!realtime) appendLine('Running inline — output appears when finished…')
    appendLine('')
    if (!realtime) inlineRunning.value = true
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
    } finally {
      inlineRunning.value = false
    }
  }

  // Run one Cypress UI spec. Always background (a browser run takes minutes), so
  // it streams like a realtime Python run. UI counts have no separate "errors"
  // bucket (a Cypress failure is a failure), so the footer shows passed/failed.
  async function runUiSpec(testCaseName, label, total = 0) {
    startSession(label, total)
    status.value = 'Running'
    appendLine(`▶ Running UI spec: ${label}`)
    appendLine('Launching a headless browser — this can take a few minutes…')
    appendLine('')
    try {
      const res = await api.runUiTest(testCaseName)
      lastRun.value = res.run_name
      subscribe(res.run_name)
    } catch (e) {
      appendLine('✖ Failed to start the UI test (API error).')
      endSession()
    }
  }

  // Queue several Cypress specs. Each spec is its own background job (one browser
  // per spec — they can't share a batch), so we enqueue them all; the backend
  // run-lock serializes execution and the console auto-follows the active run.
  async function runUiSpecs(specs) {
    if (!specs || !specs.length) return
    if (specs.length === 1) {
      const s = specs[0]
      return runUiSpec(s.name, s.test_file || s.test_method, s.ui_test_count || 0)
    }
    startSession(`${specs.length} UI specs (queued)`, 0)
    status.value = 'Running'
    appendLine(`▶ Queued ${specs.length} UI specs — they run one at a time.`)
    appendLine('The console follows whichever spec is executing.')
    appendLine('')
    let firstRun = null
    for (const s of specs) {
      try {
        const res = await api.runUiTest(s.name)
        if (!firstRun) firstRun = res.run_name
      } catch (e) {
        appendLine(`✖ Failed to queue ${s.test_file || s.name}.`)
      }
    }
    if (firstRun) {
      lastRun.value = firstRun
      subscribe(firstRun)
    } else {
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
    if (!realtime) inlineRunning.value = true
    try {
      const res = await api.runTestBatch(names, realtime ? 1 : 0)
      lastRun.value = res.run_name
      if (realtime) subscribe(res.run_name)
      else renderInline(res.result || {})
    } catch (e) {
      appendLine('✖ Failed to start the batch (API error).')
      endSession()
    } finally {
      inlineRunning.value = false
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

  // Infer a run's total test count so resume()/follow() can show "done / total"
  // (not just "done"). The run stores total_tests (single=1, batch=N, app=app's
  // test count) — use it. Fall back to older heuristics for runs created before
  // total_tests existed: a batch's test_method is "N tests (batch)"; a single
  // method/file is 1; otherwise unknown (0 → no "/ total").
  function inferTotal(run) {
    if (run.total_tests) return +run.total_tests
    const m = /^(\d+)\s+tests?\s*\(batch\)/i.exec(run.test_method || '')
    if (m) return +m[1]
    if (run.run_scope === 'Method' || run.run_scope === 'File') return 1
    return 0
  }

  // Reconnect to a run that's still in progress (e.g. after a page reload):
  // seed the console from its saved output and subscribe for further events.
  // No-op if we're already streaming this run.
  function resume(run) {
    if (!run || !run.name) return
    if (currentRun.value === run.name || lastRun.value === run.name) return
    startSession(run.test_method || run.name, inferTotal(run))
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

  // Switch the console to the run a worker is currently executing. `run` always
  // comes from get_active_run (RQ's StartedJobRegistry), so a name mismatch means
  // our current run isn't the live one — switch, even if it printed a "waiting…"
  // line. No-op if we're already on it.
  function follow(run) {
    if (!run || !run.name) return
    if (currentRun.value === run.name) return
    autoFollowing = true
    const label = run.test_method || run.name
    startSession(label, inferTotal(run))
    status.value = 'Running'
    const seed = (run.full_output || '').split('\n')
    if (seed.length === 1 && seed[0] === '') seed.length = 0
    if (seed.length) {
      seed.forEach((text) => {
        tally(stripAnsi(text))
        appendLine(text)
      })
      streamStarted.value = true
    } else {
      appendLine(`▶ Running: ${label}`)
      appendLine('Waiting for live output…')
      appendLine('')
    }
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
    streamStarted.value = false
    autoFollowing = false
    appendLine('')
    appendLine('■ Stopped by user.')
    status.value = 'Stopped'
    summary.show = true
    summary.ok = false
    summary.stopped = true
    endSession()
    // `stopped` only guarded the in-flight handlers above; clear it and advance to
    // the next executing run so stopping doesn't freeze the console.
    stopped = false
    if (advanceFn) Promise.resolve(advanceFn()).catch(() => {})
  }

  return {
    lines,
    status,
    runLabel,
    currentRun,
    lastRun,
    isRunning,
    inlineRunning,
    summary,
    progress,
    resume,
    follow,
    onAdvance,
    runOne,
    runUiSpec,
    runUiSpecs,
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
