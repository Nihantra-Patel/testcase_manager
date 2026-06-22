<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- Filter bar: two rows — filters on top, actions below — so the bar stays
         tidy as the Kind toggle and per-tier controls come and go. -->
    <div class="border-b border-outline-gray-2 bg-surface-white px-8 py-3">
      <!-- Row 1: tier toggle + filters -->
      <div class="flex flex-wrap items-end gap-3">
        <!-- Tier toggle: Python (fast, in-process) vs UI (Cypress, browser). -->
        <div>
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">Kind</div>
          <div class="flex h-[28px] overflow-hidden rounded-md border border-outline-gray-2 text-xs">
            <button
              v-for="k in ['Python', 'UI']"
              :key="k"
              class="px-3.5 font-medium transition-colors"
              :class="
                kind === k
                  ? 'bg-surface-gray-7 text-ink-white'
                  : 'bg-surface-white text-ink-gray-6 hover:bg-surface-gray-2'
              "
              @click="setKind(k)"
            >
              {{ k }}
            </button>
          </div>
        </div>
        <div class="w-[160px]">
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">App</div>
          <Select v-model="filters.app" :options="appOptions" class="w-full" />
        </div>
        <div v-if="kind === 'Python'" class="w-[140px]">
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">Type</div>
          <Select v-model="filters.type" :options="typeOptions" class="w-full" />
        </div>
        <div v-if="kind === 'Python'" class="w-[230px]">
          <div class="mb-1 truncate text-xs font-semibold text-ink-gray-5">
            {{ refLabel }}
          </div>
          <Select v-model="filters.ref" :options="refOptions" class="w-full" />
        </div>
        <div class="w-[210px]">
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">
            {{ kind === 'UI' ? 'Search Spec' : 'Search Method' }}
          </div>
          <FormControl
            v-model="filters.search"
            type="text"
            :placeholder="kind === 'UI' ? 'spec_file_name…' : 'test_method_name…'"
            class="w-full"
          />
        </div>

        <div v-if="kind === 'Python'">
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">Mode</div>
          <label
            class="flex h-[28px] cursor-pointer select-none items-center gap-1.5 text-xs text-ink-gray-6"
            title="On: background job with live streaming. Off: inline run, faster, output shown when finished."
          >
            <input type="checkbox" v-model="realtime" class="tc-checkbox" />
            Realtime run
          </label>
        </div>
      </div>

      <!-- Row 2: actions, right-aligned, on their own line. -->
      <div class="mt-3 flex items-center justify-end gap-2">
        <Button
          v-if="filters.app && kind === 'Python'"
          variant="subtle"
          :loading="impact.loading"
          @click="analyzeImpact"
        >
          <template #prefix><FeatherIcon name="git-pull-request" class="h-3.5 w-3.5" /></template>
          Analyze Impact
        </Button>
        <Button v-if="filters.app && kind === 'Python'" variant="subtle" @click="confirmRunApp">
          <template #prefix><FeatherIcon name="play" class="h-3.5 w-3.5" /></template>
          Run Entire App
        </Button>
        <Button variant="subtle" label="Clear Filter" @click="resetFilters" />
        <Button variant="subtle" :loading="syncing" label="Sync" @click="syncTests">
          <template #prefix><FeatherIcon name="refresh-cw" class="h-3.5 w-3.5" /></template>
        </Button>
      </div>
    </div>

    <!-- UI tier note: Cypress specs are slow, browser-based, opt-in. -->
    <div
      v-if="kind === 'UI'"
      class="flex items-start gap-2 border-b border-outline-gray-2 bg-surface-gray-1 px-8 py-2 text-[11px] text-ink-gray-6"
    >
      <FeatherIcon name="info" class="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-ink-gray-5" />
      <span>
        UI tests open a real browser (Cypress) and take minutes per spec — each run
        executes one whole spec file in the background. For a fast feedback loop,
        prefer a Python form/controller test (the <b>Python</b> tab) whenever the
        behaviour can be checked server-side.
      </span>
    </div>

    <!-- Impact analysis result banner -->
    <div
      v-if="impact.result"
      class="border-b border-outline-amber-2 bg-surface-amber-1 px-8 py-2.5"
    >
      <!-- Row 1: summary (left) + controls (right) -->
      <div class="flex items-center gap-4">
        <div class="flex min-w-0 items-baseline gap-2">
          <FeatherIcon name="git-pull-request" class="h-4 w-4 flex-shrink-0 text-ink-amber-3" />
          <span class="text-sm font-semibold text-ink-amber-3">
            {{ impact.result.affected_count }} of {{ impact.result.total_app_tests }} tests affected
          </span>
          <span class="truncate text-xs text-ink-gray-6">
            {{ impact.result.changed_file_count }} file(s) changed ·
            <template v-if="impact.result.base === impact.result.head">
              uncommitted on <span class="font-medium">{{ impact.result.head }}</span>
            </template>
            <template v-else>
              <span class="font-medium">{{ impact.result.base }}</span>
              →
              <span class="font-medium">{{ impact.result.head }}</span>
            </template>
          </span>
        </div>

        <div class="ml-auto flex flex-shrink-0 items-center gap-2">
          <span class="text-xs font-medium text-ink-gray-6">Depth</span>
          <Select
            v-model.number="impact.depth"
            :options="depthOptions"
            class="w-[140px]"
            @update:modelValue="analyzeImpact"
          />
          <Tooltip :hover-delay="0.1">
            <FeatherIcon name="help-circle" class="h-4 w-4 cursor-help text-ink-gray-4" />
            <template #body>
              <div class="w-max max-w-[520px] rounded-md bg-surface-gray-7 px-3 py-2 text-xs text-ink-white">
                <div class="mb-1 font-medium">How widely to look for affected tests</div>
                <div class="whitespace-nowrap">
                  <span class="font-semibold">1 — Direct:</span> only tests that use a changed file directly. Fewest.
                </div>
                <div class="whitespace-nowrap">
                  <span class="font-semibold">2 — Balanced:</span> also tests one step away. Recommended.
                </div>
                <div class="whitespace-nowrap">
                  <span class="font-semibold">3 — Broad:</span> looks further out. More tests, less precise.
                </div>
              </div>
            </template>
          </Tooltip>
          <Button
            variant="solid"
            :disabled="!impact.result.affected_count || !canStartNewRun"
            @click="runAffected"
          >
            <template #prefix><FeatherIcon name="play" class="h-3.5 w-3.5" /></template>
            Run affected ({{ impact.result.affected_count }})
          </Button>
          <Button variant="ghost" @click="clearImpact">Clear</Button>
        </div>
      </div>

      <!-- Row 2: caveat + changed-files toggle -->
      <div class="mt-1 flex items-center gap-3 text-[11px] text-ink-gray-5">
        <span>
          This is a quick guess from your code changes — it may not catch every
          affected test, so keep the full run as your final check.
        </span>
        <button
          class="underline underline-offset-2 hover:text-ink-gray-7"
          @click="impact.showFiles = !impact.showFiles"
        >
          {{ impact.showFiles ? 'Hide' : 'Show' }} changed files
        </button>
      </div>

      <!-- Changed files (collapsible) -->
      <div
        v-if="impact.showFiles"
        class="mt-1.5 max-h-32 overflow-y-auto rounded border border-outline-amber-2 bg-surface-white px-2 py-1.5"
      >
        <div
          v-for="f in impact.result.changed_files"
          :key="f"
          class="truncate font-mono text-[11px] text-ink-gray-6"
        >
          {{ f }}
        </div>
      </div>
    </div>

    <!-- Two-column body -->
    <div class="flex min-h-0 flex-1">
      <!-- Tests list -->
      <div class="flex w-2/5 flex-col border-r border-outline-gray-2">
        <div
          class="flex items-center justify-between border-b border-outline-gray-2 bg-surface-gray-1 px-3 py-1.5"
        >
          <div class="flex items-baseline gap-2">
            <span class="text-xs font-bold text-ink-gray-5">Tests</span>
            <span class="text-xs text-ink-gray-5">{{ countLabel }}</span>
          </div>
          <label v-if="kind === 'Python'" class="flex cursor-pointer items-center gap-1.5 text-xs">
            <input type="checkbox" :checked="allSelected" @change="toggleAll" class="tc-checkbox" />
            Select all
          </label>
        </div>
        <div class="flex-1 overflow-y-auto">
          <div v-if="loading" class="p-6 text-center text-sm text-ink-gray-5">Loading…</div>
          <div v-else-if="!records.length" class="p-8 text-center text-sm text-ink-gray-5">
            No tests found. Adjust filters or Sync.
          </div>
          <template v-else>
            <div v-for="group in groupedRecords" :key="group.label">
              <div
                class="border-y border-outline-gray-2 bg-surface-gray-1 px-3 py-1.5 text-[10px] font-extrabold uppercase tracking-wide text-ink-gray-5"
              >
                {{ group.label }}
              </div>
              <div
                v-for="tc in group.rows"
                :key="tc.name"
                class="flex items-center gap-2 border-b border-outline-gray-1 px-3 py-1.5 hover:bg-surface-gray-2"
              >
                <input
                  v-if="kind === 'Python'"
                  type="checkbox"
                  :value="tc.name"
                  v-model="selected"
                  class="tc-checkbox flex-shrink-0"
                />
                <div class="min-w-0 flex-1 cursor-pointer" @click="toggleOne(tc.name)">
                  <div class="flex items-center gap-1.5">
                    <span class="truncate text-sm font-semibold">{{ tc.test_method }}</span>
                    <span
                      v-if="tc.test_kind === 'UI' && tc.ui_test_count"
                      class="flex-shrink-0 rounded bg-surface-gray-3 px-1.5 py-0.5 text-[10px] font-medium text-ink-gray-6"
                      :title="tc.ui_test_names"
                    >
                      {{ tc.ui_test_count }} it()
                    </span>
                    <span
                      v-if="impact.reasons[tc.name]"
                      class="flex-shrink-0 rounded bg-surface-amber-2 px-1.5 py-0.5 text-[10px] font-medium text-ink-amber-3"
                      :title="impact.reasons[tc.name].join('\n')"
                    >
                      affected
                    </span>
                  </div>
                  <div class="truncate text-xs text-ink-gray-4">
                    {{ tc.test_kind === 'UI' ? tc.test_file_path || tc.test_file : tc.python_path }}
                  </div>
                </div>
                <!-- Per-row run. Hidden once 2+ tests are selected, where "Run
                     Selected" takes over (a single tick still runs from the row).
                     Gray subtle button reads well in both themes, with a clear
                     hover state. -->
                <Button
                  v-if="selected.length < 2"
                  variant="subtle"
                  theme="gray"
                  size="sm"
                  :disabled="!canStartNewRun"
                  :title="
                    canStartNewRun
                      ? 'Run this test'
                      : 'A run is in progress — Quick run is disabled (switch to Realtime to queue it)'
                  "
                  @click="runRow(tc)"
                >
                  <FeatherIcon name="play" class="h-3 w-3" />
                </Button>
              </div>
            </div>
          </template>
        </div>
        <!-- Run-selected bar appears only for a multi-selection (2+). A single tick
             is run from the row's own play button, so the bar doesn't compete. -->
        <div
          v-if="selected.length > 1"
          class="flex h-[52px] flex-shrink-0 items-center gap-2 border-t border-outline-gray-2 px-2"
        >
          <Button
            class="flex-1"
            variant="solid"
            theme="gray"
            :disabled="!canStartNewRun"
            @click="runSelected"
          >
            <template #prefix><FeatherIcon name="play" class="h-4 w-4" /></template>
            Run Selected ({{ selected.length }})
          </Button>
          <Button variant="ghost" :label="'Clear'" @click="selected = []" />
        </div>
      </div>

      <!-- Console panel -->
      <div class="flex w-3/5 flex-col">
        <div
          class="flex items-center justify-between border-b border-outline-gray-2 bg-surface-gray-1 px-3 py-1.5"
        >
          <span class="truncate text-sm font-semibold">{{ runner.runLabel.value }}</span>
          <div class="flex items-center gap-2">
            <!-- One activity indicator: while anything is in progress, show only the
                 live "N running" pill. Once everything is idle, show the terminal
                 status badge (Passed / Failed / Stopped) for this console's run. -->
            <button
              v-if="activeRuns > 0"
              class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-surface-amber-1 px-2.5 py-1 text-xs font-medium text-ink-amber-3 transition-colors hover:bg-surface-amber-2"
              title="View running tests in History"
              @click="$router.push({ path: '/history', query: { status: 'Running' } })"
            >
              <span class="relative flex h-2 w-2 flex-shrink-0">
                <span
                  class="absolute inline-flex h-full w-full animate-ping rounded-full bg-current opacity-75"
                />
                <span class="relative inline-flex h-2 w-2 rounded-full bg-current" />
              </span>
              <span>{{ activeRuns }} running</span>
            </button>
            <Badge
              v-else-if="runner.status.value"
              :theme="statusTheme"
              :label="runner.status.value"
            />
            <Button
              v-if="runner.isRunning.value"
              variant="ghost"
              theme="red"
              size="sm"
              title="Stop this run"
              @click="runner.stop()"
            >
              <template #prefix>
                <FeatherIcon name="stop-circle" class="h-4 w-4" />
              </template>
              Stop
            </Button>
          </div>
        </div>

        <Console :lines="runner.lines.value" />

        <!-- Stopped notice (the pass/fail tally lives in the footer below). -->
        <div
          v-if="runner.summary.show && runner.summary.stopped"
          class="flex-shrink-0 bg-[#4a1515] px-3.5 py-2 text-sm font-bold text-[#ff7b72]"
        >
          ■ Stopped by user
        </div>
        <!-- Footer bar — only shown once a run has started; mirrors the left
             pane's "Run Selected" bar height so the two bottom rows align. -->
        <div
          v-if="showOpenRun"
          class="flex h-[52px] flex-shrink-0 items-center justify-between border-t border-outline-gray-2 px-3.5"
        >
          <RouterLink
            :to="`/history/${runner.lastRun.value}`"
            class="text-xs font-medium text-ink-gray-7 underline underline-offset-2 hover:text-ink-gray-9"
          >
            Open full run →
          </RouterLink>
          <div
            v-if="showProgress"
            class="flex items-center gap-3 text-xs font-medium tabular-nums"
          >
            <span class="text-ink-gray-6">{{ progressCount }}</span>
            <span :class="progressPassed ? 'text-ink-green-3' : 'text-ink-gray-5'">
              ✓ {{ progressPassed }} Passed
            </span>
            <span
              :class="progressFailed ? 'text-ink-red-3' : 'text-ink-gray-5'"
              title="An assertion failed"
            >
              ✕ {{ progressFailed }} Failed
            </span>
            <span
              :class="progressErrors ? 'text-ink-amber-3' : 'text-ink-gray-5'"
              title="The test crashed with an unexpected exception"
            >
              ⚠ {{ progressErrors }} Errors
            </span>
          </div>
        </div>
      </div>
    </div>

    <Dialog
      v-model="showRunAppDialog"
      :options="{
        title: 'Run entire app?',
        message: `Run the ENTIRE test suite for ${filters.app}? This may take a while.`,
        actions: [
          { label: 'Run', variant: 'solid', onClick: () => doRunApp() },
          { label: 'Cancel', onClick: () => (showRunAppDialog = false) },
        ],
      }"
    />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { toast } from 'frappe-ui'
import { api } from '@/api'
import { useTestRunner } from '@/useTestRunner'
import Console from '@/components/Console.vue'

const STORAGE_KEY = 'tc_runner_filters_v2'

const runner = useTestRunner()
onBeforeUnmount(() => runner.dispose())

// Live count of in-progress runs (Running/Pending) across the site, polled so the
// indicator reflects overlapping background runs even ones started elsewhere.
const activeRuns = ref(0)

// Point the console at the test executing now. Passing the current run keeps the
// backend locked to it while it runs, so the view doesn't flicker between runs.
async function followLiveRun() {
  try {
    const active = await api.getActiveRun(runner.currentRun.value)
    if (active && active.status === 'Running') runner.follow(active)
  } catch (e) {
    /* ignore */
  }
}
// Runner calls this the moment a followed run finishes, to advance immediately.
runner.onAdvance(followLiveRun)

async function refreshActiveRuns() {
  try {
    const res = await api.getRunCount({ status: ['in', ['Running', 'Pending']] })
    activeRuns.value = res?.count || 0
    if (activeRuns.value > 0) await followLiveRun()
  } catch (e) {
    /* ignore */
  }
}
let activePoll
refreshActiveRuns()
activePoll = setInterval(refreshActiveRuns, 3000)
onBeforeUnmount(() => clearInterval(activePoll))

const filters = reactive({ app: '', type: '', ref: '', search: '' })
// Which tier the runner is showing: 'Python' (fast, in-process) or 'UI' (Cypress).
const kind = ref('Python')
// Realtime ON  → background job with live streaming (default).
// Realtime OFF → inline run, faster, output shown at completion.
const realtime = ref(true)
const records = ref([])
const total = ref(0)
const selected = ref([])
const loading = ref(false)
const syncing = ref(false)
const apps = ref([])
const refValues = ref([])
const showRunAppDialog = ref(false)

// ── Impact analysis (pre-PR "run only what changed") ────────────────────────
// depth bounds how many import-hops to follow when deciding a test is affected.
const impact = reactive({ loading: false, result: null, showFiles: false, reasons: {}, depth: 2 })
const depthOptions = [
  { label: '1 — Direct', value: 1 },
  { label: '2 — Balanced', value: 2 },
  { label: '3 — Broad', value: 3 },
]
async function analyzeImpact() {
  if (!filters.app) return
  impact.loading = true
  try {
    // Show the whole app's tests so every affected one is visible (and badged),
    // not just those under the current Type/DocType/search filter.
    filters.type = ''
    filters.ref = ''
    filters.search = ''
    const res = await api.analyzeImpact(filters.app, impact.depth)
    impact.result = res
    impact.showFiles = false
    impact.reasons = {}
    for (const a of res.affected || []) impact.reasons[a.name] = a.reasons
    // Auto-select the affected tests so the user can run them with Run Selected.
    selected.value = (res.affected || []).map((a) => a.name)
    if (!res.affected_count) {
      toast({ title: 'No affected tests found for the current changes', icon: 'info' })
    }
  } catch (e) {
    toast({
      title: e?.messages?.[0] || 'Impact analysis failed',
      icon: 'x',
      iconClasses: 'text-red-600',
    })
  } finally {
    impact.loading = false
  }
}
function clearImpact() {
  impact.result = null
  impact.reasons = {}
  impact.showFiles = false
}
// One-click: run all affected tests as a background batch (realtime), reusing the
// normal run flow. records is passed so a single-test run can resolve its label.
async function runAffected() {
  const names = (impact.result?.affected || []).map((a) => a.name)
  if (!names.length) return
  await runner.runSelected(names, records.value, realtime.value)
  selected.value = []
  nudgeOwnRun()
}

// ── Filter option lists ────────────────────────────────────────────────────
const appOptions = computed(() => [
  { label: 'All Apps', value: '' },
  ...apps.value.map((a) => ({ label: a, value: a })),
])
const typeOptions = [
  { label: 'All Types', value: '' },
  { label: 'DocType', value: 'DocType' },
  { label: 'Report', value: 'Report' },
]
// refValues holds { value, type } objects so a reference picked under "All Types"
// still knows whether it's a DocType or a Report.
const refAllLabel = computed(() =>
  filters.type === 'Report'
    ? 'All Reports'
    : filters.type === 'DocType'
    ? 'All DocTypes'
    : 'All DocTypes/Reports',
)
const refOptions = computed(() => [
  { label: refAllLabel.value, value: '' },
  ...refValues.value.map((r) => ({
    // Under "All Types", suffix the kind so a DocType and a Report of the same
    // name are distinguishable.
    label: filters.type ? r.value : `${r.value} · ${r.type}`,
    value: r.value,
  })),
])
const refLabel = computed(() =>
  filters.type === 'Report' ? 'Report' : filters.type === 'DocType' ? 'DocType' : 'DocType / Report',
)
// The type of the currently selected reference (for routing the query when the
// Type filter is "All Types").
const selectedRefType = computed(
  () => refValues.value.find((r) => r.value === filters.ref)?.type || '',
)

// ── Saved record link helper ────────────────────────────────────────────────
const countLabel = computed(() =>
  total.value > records.value.length
    ? `${records.value.length} of ${total.value} — refine filters`
    : `${records.value.length} test(s)`,
)

const statusTheme = computed(() => {
  const s = runner.status.value
  if (s === 'Passed') return 'green'
  if (s === 'Failed' || s === 'Error') return 'red'
  if (s === 'Stopped') return 'gray'
  return 'orange'
})

// Show "Open full run" only once a run has actually started streaming output
// (i.e. there are console lines for a known run), not the instant it's queued.
const showOpenRun = computed(
  () => !!runner.lastRun.value && runner.lines.value.length > 0,
)

// Live progress shown in the console footer: how many tests have run (vs total)
// and a running pass/fail tally that updates as each test completes.
const progressCount = computed(() => {
  const { done, total } = runner.progress
  if (!done && !runner.isRunning.value) return ''
  return total ? `${done} / ${total} tests` : `${done} tests`
})
const progressPassed = computed(() => runner.progress.passed)
const progressFailed = computed(() => runner.progress.failed)
const progressErrors = computed(() => runner.progress.errors)
const showProgress = computed(() => !!progressCount.value)

// Gating depends on the selected Mode:
//   • Realtime → background job; queues safely via the worker lock → always allowed.
//   • Quick (inline) → runs in the web process, bypassing that lock, so it would
//     deadlock against ANY active run. Block it while anything is running.
const canStartNewRun = computed(() => {
  if (kind.value === 'UI') return true // UI runs are always background → queue safely
  if (realtime.value) return true // realtime always queues
  return !runner.isRunning.value && !runner.inlineRunning.value
})

// Switch tier: UI and Python have separate app lists / filters, so reload them.
function setKind(k) {
  if (kind.value === k) return
  kind.value = k
  selected.value = []
  clearImpact()
  filters.type = ''
  filters.ref = ''
  loadApps()
  loadRefOptions()
  doQuery()
  saveFilters()
}

// Run a single row, routed by tier: a UI spec runs in a headless browser, a
// Python test runs inline/realtime per the Mode toggle.
function runRow(tc) {
  if (tc.test_kind === 'UI') return runUiRow(tc)
  return runOne(tc.name, tc.test_method)
}
async function runUiRow(tc) {
  await runner.runUiSpec(tc.name, tc.test_file || tc.test_method)
  nudgeOwnRun()
}

// ── Grouping (app › module) ─────────────────────────────────────────────────
const groupedRecords = computed(() => {
  const groups = {}
  for (const r of records.value) {
    const key = `${r.app} › ${r.module || r.reference_doctype || r.report || '—'}`
    ;(groups[key] = groups[key] || []).push(r)
  }
  return Object.keys(groups)
    .sort((a, b) => a.localeCompare(b))
    .map((label) => ({
      label,
      rows: groups[label].sort((a, b) =>
        (a.test_method || '').localeCompare(b.test_method || ''),
      ),
    }))
})

// "Select all" is scoped to the currently-visible records so it doesn't disturb
// selections made under other filters: checked = every visible test is selected.
const allSelected = computed(
  () =>
    records.value.length > 0 &&
    records.value.every((r) => selected.value.includes(r.name)),
)
function toggleAll(e) {
  const visible = records.value.map((r) => r.name)
  if (e.target.checked) {
    selected.value = [...new Set([...selected.value, ...visible])]
  } else {
    selected.value = selected.value.filter((n) => !visible.includes(n))
  }
}
function toggleOne(name) {
  const i = selected.value.indexOf(name)
  if (i === -1) selected.value.push(name)
  else selected.value.splice(i, 1)
}

// ── Server queries ──────────────────────────────────────────────────────────
let queryTimer
function queueQuery() {
  clearTimeout(queryTimer)
  queryTimer = setTimeout(doQuery, 300)
}

async function doQuery() {
  loading.value = true
  const args = {
    app: filters.app,
    reference_type: filters.type,
    search: filters.search.trim(),
    test_kind: kind.value,
    page_size: 10000,
  }
  if (filters.ref) {
    // Route the selected reference by its real kind — under "All Types" the type
    // comes from the option, otherwise from the Type filter.
    const kind = filters.type || selectedRefType.value
    if (kind === 'Report') args.report = filters.ref
    else args.reference_doctype = filters.ref
  }
  try {
    const res = await api.getTestCases(args)
    records.value = res.records || []
    total.value = res.total || 0
    // Selection intentionally persists across filter/search changes so the user can
    // build a cross-app / cross-doctype selection. It's cleared only on run or reload.
  } finally {
    loading.value = false
  }
}

async function loadRefOptions() {
  if (kind.value === 'UI' || (!filters.app && !filters.type)) {
    refValues.value = []
    return
  }
  refValues.value = (await api.getReferenceOptions(filters.app, filters.type)) || []
}

// ── Filter persistence ──────────────────────────────────────────────────────
function saveFilters() {
  try {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ ...filters, realtime: realtime.value, kind: kind.value }),
    )
  } catch (e) {
    /* ignore */
  }
}
function restoreFilters() {
  try {
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (typeof s.realtime === 'boolean') realtime.value = s.realtime
    if (s.kind === 'Python' || s.kind === 'UI') kind.value = s.kind
    Object.assign(filters, { app: s.app, type: s.type, ref: s.ref, search: s.search })
  } catch (e) {
    /* ignore */
  }
  // App / Type / DocType-Report persist across reloads; the method search is
  // intentionally cleared on every fresh load (only "Clear Filter" wipes the rest).
  filters.search = ''
}
function resetFilters() {
  filters.app = ''
  filters.type = ''
  filters.ref = ''
  filters.search = ''
  realtime.value = true
  kind.value = 'Python'
  loadApps()
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch (e) {
    /* ignore */
  }
}

// True only while restoreFilters() seeds values on load, so the app/type watch
// below does NOT clear the restored DocType/Report selection.
let restoring = false

watch(
  () => [filters.app, filters.type],
  async () => {
    if (!restoring) filters.ref = '' // user changed App/Type → invalidate ref
    await loadRefOptions()
    saveFilters()
    queueQuery()
  },
)
watch(
  () => [filters.ref, filters.search],
  () => {
    saveFilters()
    queueQuery()
  },
)
// Impact analysis is per-app, so changing the app invalidates a prior result.
watch(
  () => filters.app,
  () => {
    if (!restoring) clearImpact()
  },
)
watch(realtime, saveFilters)

// ── Actions ─────────────────────────────────────────────────────────────────
// After starting a run, refresh a few times so it starts following promptly
// instead of waiting for the next poll.
function nudgeOwnRun() {
  refreshActiveRuns()
  setTimeout(refreshActiveRuns, 800)
  setTimeout(refreshActiveRuns, 1800)
}
async function runSelected() {
  await runner.runSelected(selected.value, records.value, realtime.value)
  selected.value = [] // clear the selection once it's been submitted to run
  nudgeOwnRun()
}
async function runOne(name, label) {
  await runner.runOne(name, label, realtime.value)
  nudgeOwnRun()
}
function confirmRunApp() {
  showRunAppDialog.value = true
}
async function doRunApp() {
  showRunAppDialog.value = false
  // The app run ignores Type/DocType filters, so fetch the app's full test count
  // for an accurate "done / total" progress, not the filtered total.
  let appTotal = 0
  try {
    const res = await api.getTestCases({ app: filters.app, page_size: 1 })
    appTotal = res?.total || 0
  } catch (e) {
    /* progress will fall back to a plain count */
  }
  runner.runEntireApp(filters.app, appTotal)
}

async function syncTests() {
  syncing.value = true
  try {
    let m
    if (kind.value === 'UI') {
      // UI specs are discovered by file glob; only the app scopes the sync.
      m = (await api.syncUiSpecs(filters.app)) || {}
    } else {
      const args = { app: filters.app }
      if (filters.app) {
        const refKind = filters.type || selectedRefType.value
        if (refKind) args.reference_type = refKind
        if (filters.ref) args.reference = filters.ref
      }
      m = (await api.syncTestCases(args)) || {}
    }
    if (m.status === 'queued') {
      toast({ title: 'Full sync queued in background', icon: 'clock' })
    } else {
      toast({
        title: `Sync complete — created: ${m.created}, updated: ${m.updated}, deleted: ${m.deleted}`,
        icon: 'check',
        iconClasses: 'text-green-600',
      })
      await loadApps()
      doQuery()
    }
  } finally {
    syncing.value = false
  }
}

async function loadApps() {
  apps.value = (await api.getInstalledApps(kind.value)) || []
}

// After a page reload, reconnect to a run that's still in progress so the
// console shows the whole process instead of going blank. Skip if the in-memory
// runner is already streaming (navigated back without a reload).
async function resumeActiveRun() {
  if (runner.isRunning.value || runner.lines.value.length) return
  try {
    const active = await api.getActiveRun()
    if (active) runner.resume(active)
  } catch (e) {
    /* best effort */
  }
}

// ── Init ────────────────────────────────────────────────────────────────────
restoring = true
restoreFilters()
loadApps()
loadRefOptions()
doQuery()
resumeActiveRun()
// Release the guard after Vue has flushed the watchers triggered by the restore,
// so subsequent user changes to App/Type still reset the ref as expected.
nextTick(() => {
  restoring = false
})
</script>

