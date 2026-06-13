<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- Filter bar -->
    <div
      class="flex flex-wrap items-end gap-3 border-b border-outline-gray-2 bg-surface-white px-8 py-3"
    >
      <div class="w-[150px]">
        <div class="mb-1 text-xs font-semibold text-ink-gray-5">App</div>
        <Select v-model="filters.app" :options="appOptions" class="w-full" />
      </div>
      <div class="w-[130px]">
        <div class="mb-1 text-xs font-semibold text-ink-gray-5">Type</div>
        <Select v-model="filters.type" :options="typeOptions" class="w-full" />
      </div>
      <div class="w-[220px]">
        <div class="mb-1 truncate text-xs font-semibold text-ink-gray-5">
          {{ refLabel }}
        </div>
        <Select v-model="filters.ref" :options="refOptions" class="w-full" />
      </div>
      <div class="w-[200px]">
        <div class="mb-1 text-xs font-semibold text-ink-gray-5">
          Search Method
        </div>
        <FormControl
          v-model="filters.search"
          type="text"
          placeholder="test_method_name…"
          class="w-full"
        />
      </div>

      <div>
        <div class="mb-1 text-xs font-semibold text-ink-gray-5">Mode</div>
        <label
          class="flex h-[28px] cursor-pointer select-none items-center gap-1.5 text-xs text-ink-gray-6"
          title="On: background job with live streaming. Off: inline run, faster, output shown when finished."
        >
          <input type="checkbox" v-model="realtime" class="tc-checkbox" />
          Realtime run
        </label>
      </div>

      <div class="ml-auto flex items-end gap-2">
        <button
          v-if="activeRuns > 0"
          class="flex items-center gap-1.5 self-center rounded-full bg-surface-amber-1 px-2.5 py-1 text-xs font-medium text-ink-amber-3 transition-colors hover:bg-surface-amber-2"
          title="View running tests in History"
          @click="$router.push({ path: '/history', query: { status: 'Running' } })"
        >
          <span class="relative flex h-2 w-2">
            <span
              class="absolute inline-flex h-full w-full animate-ping rounded-full bg-ink-amber-3 opacity-75"
            />
            <span class="relative inline-flex h-2 w-2 rounded-full bg-ink-amber-3" />
          </span>
          {{ activeRuns }} running
        </button>
        <span class="self-center text-xs text-ink-gray-5">{{ countLabel }}</span>
        <Button v-if="filters.app" variant="subtle" @click="confirmRunApp">
          <template #prefix><FeatherIcon name="play" class="h-3.5 w-3.5" /></template>
          Run Entire App
        </Button>
        <Button variant="subtle" label="Clear Filter" @click="resetFilters" />
        <Button variant="subtle" :loading="syncing" label="Sync" @click="syncTests">
          <template #prefix><FeatherIcon name="refresh-cw" class="h-3.5 w-3.5" /></template>
        </Button>
      </div>
    </div>

    <!-- Two-column body -->
    <div class="flex min-h-0 flex-1">
      <!-- Tests list -->
      <div class="flex w-2/5 flex-col border-r border-outline-gray-2">
        <div
          class="flex items-center justify-between border-b border-outline-gray-2 bg-surface-gray-1 px-3 py-1.5"
        >
          <span class="text-xs font-bold text-ink-gray-5">Tests</span>
          <label class="flex cursor-pointer items-center gap-1.5 text-xs">
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
                  type="checkbox"
                  :value="tc.name"
                  v-model="selected"
                  class="tc-checkbox flex-shrink-0"
                />
                <div class="min-w-0 flex-1 cursor-pointer" @click="toggleOne(tc.name)">
                  <div class="truncate text-sm font-semibold">{{ tc.test_method }}</div>
                  <div class="truncate text-xs text-ink-gray-4">{{ tc.python_path }}</div>
                </div>
                <Button
                  variant="solid"
                  size="sm"
                  :disabled="!canStartNewRun"
                  :title="
                    canStartNewRun
                      ? 'Run this test'
                      : 'A run is in progress — Quick run is disabled (switch to Realtime to queue it)'
                  "
                  @click="runner.runOne(tc.name, tc.test_method, realtime)"
                >
                  <FeatherIcon name="play" class="h-3 w-3" />
                </Button>
              </div>
            </div>
          </template>
        </div>
        <div
          class="flex h-[52px] flex-shrink-0 items-center border-t border-outline-gray-2 px-2"
        >
          <Button
            class="w-full"
            variant="solid"
            :disabled="!selected.length || !canStartNewRun"
            @click="runSelected"
          >
            <template #prefix><FeatherIcon name="play" class="h-4 w-4" /></template>
            Run Selected ({{ selected.length }})
          </Button>
        </div>
      </div>

      <!-- Console panel -->
      <div class="flex w-3/5 flex-col">
        <div
          class="flex items-center justify-between border-b border-outline-gray-2 bg-surface-gray-1 px-3 py-1.5"
        >
          <span class="truncate text-sm font-semibold">{{ runner.runLabel.value }}</span>
          <div class="flex items-center gap-2">
            <Badge v-if="runner.status.value" :theme="statusTheme" :label="runner.status.value" />
            <Button
              v-if="runner.isRunning.value"
              variant="solid"
              theme="red"
              size="sm"
              label="Stop"
              @click="runner.stop()"
            />
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
async function refreshActiveRuns() {
  try {
    const res = await api.getRunCount({ status: ['in', ['Running', 'Pending']] })
    activeRuns.value = res?.count || 0
  } catch (e) {
    /* ignore */
  }
}
let activePoll
refreshActiveRuns()
activePoll = setInterval(refreshActiveRuns, 3000)
onBeforeUnmount(() => clearInterval(activePoll))

const filters = reactive({ app: '', type: '', ref: '', search: '' })
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
  if (realtime.value) return true // realtime always queues
  return !runner.isRunning.value && !runner.inlineRunning.value
})

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

const allSelected = computed(
  () => records.value.length > 0 && selected.value.length === records.value.length,
)
function toggleAll(e) {
  selected.value = e.target.checked ? records.value.map((r) => r.name) : []
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
    selected.value = []
  } finally {
    loading.value = false
  }
}

async function loadRefOptions() {
  if (!filters.app && !filters.type) {
    refValues.value = []
    return
  }
  refValues.value = (await api.getReferenceOptions(filters.app, filters.type)) || []
}

// ── Filter persistence ──────────────────────────────────────────────────────
function saveFilters() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...filters, realtime: realtime.value }))
  } catch (e) {
    /* ignore */
  }
}
function restoreFilters() {
  try {
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (typeof s.realtime === 'boolean') realtime.value = s.realtime
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
watch(realtime, saveFilters)

// ── Actions ─────────────────────────────────────────────────────────────────
function runSelected() {
  runner.runSelected(selected.value, records.value, realtime.value)
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
  const args = { app: filters.app }
  if (filters.app) {
    const kind = filters.type || selectedRefType.value
    if (kind) args.reference_type = kind
    if (filters.ref) args.reference = filters.ref
  }
  try {
    const m = (await api.syncTestCases(args)) || {}
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
  apps.value = (await api.getInstalledApps()) || []
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

