<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- Filters -->
    <div class="border-b border-outline-gray-2 px-8 py-3">
      <div class="flex flex-wrap items-end gap-3">
        <div>
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">App</div>
          <Select v-model="filters.app" :options="appOptions" class="min-w-[150px]" />
        </div>
        <div>
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">Type</div>
          <Select v-model="filters.type" :options="typeOptions" class="min-w-[130px]" />
        </div>
        <div>
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">Status</div>
          <Select v-model="filters.status" :options="statusOptions" class="min-w-[130px]" />
        </div>
        <div>
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">Mode</div>
          <Select v-model="filters.mode" :options="modeOptions" class="min-w-[120px]" />
        </div>
        <div>
          <div class="mb-1 text-xs font-semibold text-ink-gray-5">
            Search
          </div>
          <FormControl
            v-model="filters.search"
            type="text"
            placeholder="Test title…"
            class="min-w-[200px]"
          />
        </div>
        <div class="ml-auto flex items-end gap-2">
          <Button variant="subtle" label="Clear Filter" @click="resetFilters" />
          <Button variant="subtle" :loading="runs.loading" label="Refresh" @click="runs.reload()">
            <template #prefix><FeatherIcon name="refresh-cw" class="h-3.5 w-3.5" /></template>
          </Button>
        </div>
      </div>
    </div>

    <!-- Table (flex-based list so columns align and the Action hugs the right) -->
    <div class="flex-1 overflow-y-auto">
      <!-- Header -->
      <div
        class="sticky top-0 z-[1] flex items-center border-b border-outline-gray-2 bg-surface-white px-8 py-2.5 text-xs font-semibold text-ink-gray-5"
      >
        <span class="flex-1 min-w-[180px] pr-4">Test</span>
        <span class="w-[130px] flex-shrink-0 pr-4">App</span>
        <span class="w-[110px] flex-shrink-0 pr-4">Mode</span>
        <span class="w-[100px] flex-shrink-0 pr-4">Scope</span>
        <span class="w-[150px] flex-shrink-0 pr-4">Type</span>
        <span class="w-[105px] flex-shrink-0 pr-4">Status</span>
        <span class="w-[110px] flex-shrink-0 pr-4">Start Time</span>
        <span class="w-[110px] flex-shrink-0 pr-4">End Time</span>
        <span class="w-[80px] flex-shrink-0 pr-4 text-right" title="Actual test execution time">
          Test Time
        </span>
        <span class="w-[80px] flex-shrink-0 pr-4 text-right" title="Total process time">
          Total
        </span>
        <span class="w-[56px] flex-shrink-0 text-right">Action</span>
      </div>
      <!-- Rows -->
      <div
        v-for="r in runs.data || []"
        :key="r.name"
        class="flex cursor-pointer items-center border-b border-outline-gray-1 px-8 py-2.5 text-sm transition-colors hover:bg-surface-gray-2"
        @click="$router.push(`/history/${r.name}`)"
      >
        <span
          class="flex-1 min-w-[180px] truncate pr-4 font-medium text-ink-gray-9"
          :title="r.test_method"
        >
          {{ r.test_method }}
        </span>
        <span class="w-[130px] flex-shrink-0 pr-4">
          <Badge theme="gray" :title="r.app">
            <template #prefix>
              <img
                v-if="appLogos[r.app]"
                :src="appLogos[r.app]"
                class="h-3.5 w-3.5 rounded-sm object-contain"
                alt=""
              />
              <FeatherIcon v-else name="package" class="h-3 w-3" />
            </template>
            <span class="block max-w-[78px] truncate">{{ r.app }}</span>
          </Badge>
        </span>
        <span class="w-[110px] flex-shrink-0 pr-4">
          <Badge theme="gray" :label="r.realtime ? 'Realtime' : 'Quick'">
            <template #prefix>
              <FeatherIcon :name="modeIcon(r.realtime)" class="h-3 w-3" />
            </template>
          </Badge>
        </span>
        <span class="w-[100px] flex-shrink-0 pr-4">
          <Badge theme="gray" :label="r.run_scope">
            <template #prefix>
              <FeatherIcon :name="scopeIcon(r.run_scope)" class="h-3 w-3" />
            </template>
          </Badge>
        </span>
        <span class="w-[150px] flex-shrink-0 pr-4">
          <Badge v-if="r.reference_type" theme="gray" :label="r.reference_type">
            <template #prefix>
              <FeatherIcon :name="typeIcon(r.reference_type)" class="h-3 w-3" />
            </template>
          </Badge>
          <span v-else class="text-ink-gray-4">—</span>
        </span>
        <span class="w-[105px] flex-shrink-0 pr-4">
          <Badge :theme="theme(r.status)" :label="r.status">
            <template #prefix>
              <span class="mr-1">{{ statusIcon(r.status) }}</span>
            </template>
          </Badge>
        </span>
        <span
          class="w-[110px] flex-shrink-0 truncate pr-4 text-ink-gray-6"
          :title="r.start_time"
        >
          {{ dateTime(r.start_time) }}
        </span>
        <span
          class="w-[110px] flex-shrink-0 truncate pr-4 text-ink-gray-6"
          :title="r.end_time"
        >
          {{ dateTime(r.end_time) }}
        </span>
        <span class="w-[80px] flex-shrink-0 pr-4 text-right tabular-nums text-ink-gray-7">
          {{ secs(r.exec_time) }}
        </span>
        <span class="w-[80px] flex-shrink-0 pr-4 text-right tabular-nums text-ink-gray-7">
          {{ secs(r.duration) }}
        </span>
        <span class="w-[56px] flex-shrink-0 text-right">
          <Button
            v-if="isRunningStatus(r.status)"
            variant="ghost"
            theme="red"
            size="sm"
            :loading="stopping[r.name]"
            title="Stop this run"
            @click.stop="stopRun(r)"
          >
            <template #icon><FeatherIcon name="stop-circle" class="h-4 w-4" /></template>
          </Button>
          <Button
            v-else
            variant="ghost"
            size="sm"
            title="Preview output"
            @click.stop="openPreview(r)"
          >
            <template #icon><FeatherIcon name="eye" class="h-4 w-4" /></template>
          </Button>
        </span>
      </div>
      <div v-if="!runs.loading && !(runs.data || []).length" class="p-8 text-center text-ink-gray-5">
        No runs found.
      </div>
    </div>

    <!-- Bottom bar — page-size pills (left) + count and Load more (right) -->
    <div
      class="flex flex-shrink-0 items-center justify-between border-t border-outline-gray-2 px-8 py-2"
    >
      <div class="flex items-center gap-1">
        <button
          v-for="n in pageSizeOptions"
          :key="n"
          class="rounded px-2 py-1 text-xs font-medium transition-colors"
          :class="
            pageSize === n
              ? 'bg-surface-gray-3 text-ink-gray-9'
              : 'text-ink-gray-6 hover:bg-surface-gray-2'
          "
          @click="pageSize = n"
        >
          {{ n }}
        </button>
      </div>
      <div class="flex items-center gap-3">
        <span class="text-xs text-ink-gray-5">
          {{ (runs.data || []).length }} of {{ totalCount }}
        </span>
        <Button
          v-if="runs.hasNextPage"
          variant="subtle"
          label="Load more"
          @click="runs.next()"
        />
      </div>
    </div>

    <!-- Quick output preview -->
    <Dialog v-model="preview.show" bare size="4xl">
      <template #default="{ close }">
        <div
          class="flex h-[600px] max-h-[80vh] w-full flex-col overflow-hidden rounded-xl bg-surface-modal"
        >
          <!-- Sticky header — clearly separated from the output by a border -->
          <div
            class="flex flex-shrink-0 items-center justify-between gap-3 border-b border-outline-gray-2 bg-surface-gray-1 px-4 py-3"
          >
            <div class="flex min-w-0 items-center gap-3">
              <span class="truncate text-sm font-semibold text-ink-gray-9">
                {{ preview.title }}
              </span>
              <Badge
                v-if="preview.status"
                :theme="theme(preview.status)"
                :label="preview.status"
              />
              <div
                v-if="previewSummary"
                class="flex flex-shrink-0 items-center gap-3 text-xs font-medium tabular-nums"
              >
                <span class="text-ink-gray-6">
                  {{ previewSummary.total }} / {{ previewSummary.total }} tests
                </span>
                <span :class="previewSummary.passed ? 'text-ink-green-3' : 'text-ink-gray-5'">
                  ✓ {{ previewSummary.passed }} Passed
                </span>
                <span
                  :class="previewSummary.failed ? 'text-ink-red-3' : 'text-ink-gray-5'"
                  title="An assertion failed"
                >
                  ✕ {{ previewSummary.failed }} Failed
                </span>
                <span
                  :class="previewSummary.errors ? 'text-ink-amber-3' : 'text-ink-gray-5'"
                  title="The test crashed with an unexpected exception"
                >
                  ⚠ {{ previewSummary.errors }} Errors
                </span>
              </div>
            </div>
            <div class="flex flex-shrink-0 items-center gap-3">
              <Button
                v-if="previewSummary && previewSummary.failed + previewSummary.errors > 0"
                variant="subtle"
                theme="red"
                size="sm"
                :loading="rerunning"
                label="Rerun failed"
                title="Re-run only the failed and errored tests as a new batch"
                @click="rerunFailed(preview.name, close)"
              >
                <template #prefix><FeatherIcon name="refresh-cw" class="h-3.5 w-3.5" /></template>
              </Button>
              <RouterLink
                v-if="preview.name"
                :to="`/history/${preview.name}`"
                class="text-xs font-medium text-ink-gray-7 underline underline-offset-2 hover:text-ink-gray-9"
              >
                Open full run →
              </RouterLink>
              <button
                class="flex h-7 w-7 items-center justify-center rounded-full text-ink-gray-7 hover:bg-surface-gray-3"
                @click="close"
              >
                <FeatherIcon name="x" class="h-4 w-4" />
              </button>
            </div>
          </div>
          <!-- Output (fills remaining height, scrolls) -->
          <div
            v-if="preview.loading"
            class="flex flex-1 items-center justify-center text-sm text-ink-gray-5"
          >
            Loading…
          </div>
          <Console v-else :lines="previewLines" class="min-h-0 flex-1" />
        </div>
      </template>
    </Dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { createListResource, call, toast } from 'frappe-ui'
import { api } from '@/api'
import Console from '@/components/Console.vue'

const route = useRoute()
const router = useRouter()

const STORAGE_KEY = 'tc_history_filters_v1'

const filters = reactive({ app: '', status: '', type: '', mode: '', search: '' })
const pageSize = ref(20)
const apps = ref([])
const appLogos = ref({}) // app name → logo URL (real per-app SVG)

// ── Quick output preview (dialog) ───────────────────────────────────────────
const preview = reactive({
  show: false,
  loading: false,
  name: '',
  title: '',
  status: '',
  output: '',
  result: '',
})
const previewLines = computed(() =>
  (preview.output || 'No output.').split('\n').map((text) => ({ text })),
)
// Parsed pass/fail/error tally for the preview header, mirroring the Runner's
// footer format ("N / N tests  ✓ N Passed  ✕ N Failed  ⚠ N Errors").
const previewSummary = computed(() => parseSummary(preview.result))
async function openPreview(r) {
  preview.show = true
  preview.loading = true
  preview.name = r.name
  preview.title = r.test_method
  preview.status = r.status
  preview.output = ''
  preview.result = ''
  try {
    const doc = await call('frappe.client.get', { doctype: 'Testcase Run', name: r.name })
    preview.output = doc?.full_output || 'No output.'
    preview.result = doc?.result || ''
  } catch (e) {
    preview.output = 'Failed to load output.'
  } finally {
    preview.loading = false
  }
}

// ── Rerun failed & errored tests ────────────────────────────────────────────
// Launches a new batch run of just the failing tests from `runName`, then jumps
// to that run's full view ("Open full run") so it streams live there.
const rerunning = ref(false)
async function rerunFailed(runName, closeDialog) {
  if (!runName || rerunning.value) return
  rerunning.value = true
  try {
    // background=1 → realtime run so RunDetailView can stream it as it executes.
    const res = await api.rerunFailed(runName, 1)
    if (closeDialog) closeDialog()
    toast({ title: 'Re-running failed tests…', icon: 'check', iconClasses: 'text-green-600' })
    runs.reload()
    refreshCount()
    // Switch straight to the latest run's full view.
    if (res?.run_name) router.push(`/history/${res.run_name}`)
  } catch (e) {
    toast({
      title: e?.messages?.[0] || 'Failed to start re-run',
      icon: 'x',
      iconClasses: 'text-red-600',
    })
  } finally {
    rerunning.value = false
  }
}

// The run's `result` field stores "Passed: X, Failed: Y, Errors: Z". Parse it into
// counts plus a total; returns null when the run didn't record a tally (e.g. it's
// still running or was stopped before any result was written).
function parseSummary(result) {
  if (!result) return null
  const m = result.match(/Passed:\s*(\d+),\s*Failed:\s*(\d+),\s*Errors:\s*(\d+)/i)
  if (!m) return null
  const passed = +m[1]
  const failed = +m[2]
  const errors = +m[3]
  return { passed, failed, errors, total: passed + failed + errors }
}

const pageSizeOptions = [20, 100, 500, 2500]
const statusOptions = [
  { label: 'All Status', value: '' },
  { label: 'Passed', value: 'Passed' },
  { label: 'Failed', value: 'Failed' },
  { label: 'Error', value: 'Error' },
  { label: 'Stopped', value: 'Stopped' },
  { label: 'Running', value: 'Running' },
  { label: 'Pending', value: 'Pending' },
]
const modeOptions = [
  { label: 'All Modes', value: '' },
  { label: 'Realtime', value: '1' },
  { label: 'Quick', value: '0' },
]
const typeOptions = [
  { label: 'All Types', value: '' },
  { label: 'DocType', value: 'DocType' },
  { label: 'Report', value: 'Report' },
  { label: 'DocType-Report', value: 'DocType-Report' },
  { label: 'App', value: 'App' },
]
const appOptions = computed(() => [
  { label: 'All Apps', value: '' },
  ...apps.value.map((a) => ({ label: a, value: a })),
])

// The Testcase Run stores its own `reference_type` — one of "DocType",
// "Report", "DocType-Report" (mixed batch), or "App" (whole-app run) — so the
// Type filter is an exact match against that stored value.
function buildFilters() {
  const f = {}
  if (filters.app) f.app = filters.app
  if (filters.status) f.status = filters.status
  if (filters.search.trim()) f.test_method = ['like', `%${filters.search.trim()}%`]
  if (filters.type) f.reference_type = filters.type
  if (filters.mode) f.realtime = filters.mode
  return f
}

const runs = createListResource({
  doctype: 'Testcase Run',
  fields: [
    'name',
    'test_method',
    'app',
    'run_scope',
    'realtime',
    'status',
    'duration',
    'exec_time',
    'start_time',
    'end_time',
    'creation',
    'reference_type',
  ],
  filters: buildFilters(),
  orderBy: 'creation desc',
  pageLength: pageSize.value,
  auto: true,
})

const totalCount = ref(0)
async function refreshCount() {
  const res = await api.getRunCount(buildFilters())
  totalCount.value = res?.count ?? 0
}

function applyAndReload() {
  runs.filters = buildFilters()
  runs.pageLength = pageSize.value
  runs.reload()
  refreshCount()
}

watch(
  () => [filters.app, filters.status, filters.type, filters.mode, pageSize.value],
  () => {
    saveFilters()
    applyAndReload()
  },
)

// Debounce the text search so we don't refetch on every keystroke.
let searchTimer
watch(
  () => filters.search,
  () => {
    clearTimeout(searchTimer)
    searchTimer = setTimeout(applyAndReload, 300)
  },
)

// ── Filter persistence (App / Status / Type persist; reset clears them) ──────
function saveFilters() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...filters, pageSize: pageSize.value }))
  } catch (e) {
    /* ignore */
  }
}
function restoreFilters() {
  try {
    const s = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}')
    if (s.app) filters.app = s.app
    if (s.status) filters.status = s.status
    if (s.type) filters.type = s.type
    if (s.mode) filters.mode = s.mode
    if (s.pageSize) pageSize.value = s.pageSize
  } catch (e) {
    /* ignore */
  }
  // Search is transient — always start empty on a fresh load.
  filters.search = ''
}
function resetFilters() {
  filters.app = ''
  filters.status = ''
  filters.type = ''
  filters.mode = ''
  filters.search = ''
  try {
    localStorage.removeItem(STORAGE_KEY)
  } catch (e) {
    /* ignore */
  }
}

function theme(status) {
  if (status === 'Passed') return 'green'
  if (status === 'Failed' || status === 'Error') return 'red'
  if (status === 'Running' || status === 'Pending') return 'orange'
  if (status === 'Stopped') return 'orange' // interrupted — warning hue, not loud black
  return 'gray'
}

// ── Badge meta for the App / Mode / Scope / Type columns ────────────────────
// Each returns a FeatherIcon name; themes give every column a distinct, calm hue.
function modeIcon(realtime) {
  return realtime ? 'radio' : 'zap'
}
function scopeIcon(scope) {
  return (
    {
      Method: 'code',
      File: 'file',
      DocType: 'box',
      App: 'grid',
      Batch: 'layers',
    }[scope] || 'circle'
  )
}
function typeIcon(type) {
  if (type === 'Report') return 'bar-chart-2'
  if (type === 'App') return 'grid'
  if (type && type.includes('-')) return 'shuffle' // DocType-Report (mixed)
  return 'box' // DocType
}

function isRunningStatus(status) {
  return status === 'Running' || status === 'Pending'
}

// Stop a running/pending run straight from the list. Per-row loading flag so only
// the clicked row shows a spinner; reload afterwards to reflect the Stopped state.
const stopping = reactive({})
async function stopRun(r) {
  stopping[r.name] = true
  try {
    await api.stopRun(r.name)
    toast({ title: 'Run stopped', icon: 'check', iconClasses: 'text-green-600' })
    runs.reload()
    refreshCount()
  } catch (e) {
    toast({ title: 'Failed to stop the run', icon: 'x', iconClasses: 'text-red-600' })
  } finally {
    stopping[r.name] = false
  }
}

function statusIcon(status) {
  if (status === 'Passed') return '✓'
  if (status === 'Failed' || status === 'Error') return '✕'
  if (status === 'Running' || status === 'Pending') return '⟳'
  return '■' // Stopped, etc.
}

// Seconds with 2 decimals, e.g. 1.098 → "1.10s". Em-dash when missing.
function secs(value) {
  return value ? `${Number(value).toFixed(2)}s` : '—'
}

// Compact full date-time, e.g. "09 Jun, 3:49 PM". Full value stays in the title.
function dateTime(value) {
  if (!value) return '—'
  const d = new Date(value.replace(' ', 'T'))
  if (isNaN(d)) return '—'
  const date = d.toLocaleDateString(undefined, { day: '2-digit', month: 'short' })
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${date}, ${time}`
}

async function loadApps() {
  apps.value = (await api.getInstalledApps()) || []
  try {
    appLogos.value = (await api.getAppLogos()) || {}
  } catch (e) {
    /* fall back to a generic icon */
  }
}

restoreFilters()
// A ?status=… query (e.g. from the Runner's "N running" pill) pre-applies that
// status filter so the user lands on the matching list.
if (route.query.status) filters.status = String(route.query.status)
loadApps()
applyAndReload()
</script>
