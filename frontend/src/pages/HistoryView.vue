<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- Filters -->
    <div class="border-b border-outline-gray-2 px-6 py-3">
      <div class="flex flex-wrap items-end gap-3">
        <div>
          <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-gray-5">App</div>
          <Select v-model="filters.app" :options="appOptions" class="min-w-[150px]" />
        </div>
        <div>
          <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-gray-5">
            Status
          </div>
          <Select v-model="filters.status" :options="statusOptions" class="min-w-[130px]" />
        </div>
        <div>
          <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-gray-5">Type</div>
          <Select v-model="filters.type" :options="typeOptions" class="min-w-[130px]" />
        </div>
        <div>
          <div class="mb-1 text-xs font-semibold uppercase tracking-wide text-ink-gray-5">
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

    <!-- Table -->
    <div class="flex-1 overflow-y-auto px-6">
      <table class="w-full text-sm">
        <thead
          class="sticky top-0 z-10 bg-surface-white text-left text-xs uppercase text-ink-gray-5"
        >
          <tr class="border-b border-outline-gray-2">
            <th class="py-2 pr-4 font-semibold">Test</th>
            <th class="py-2 pr-4 font-semibold">App</th>
            <th class="py-2 pr-4 font-semibold">Scope</th>
            <th class="py-2 pr-4 font-semibold">Type</th>
            <th class="py-2 pr-4 font-semibold">Status</th>
            <th class="py-2 pr-4 font-semibold">Duration</th>
            <th class="py-2 pr-4 font-semibold">When</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in runs.data || []"
            :key="r.name"
            class="cursor-pointer border-b border-outline-gray-1 hover:bg-surface-gray-2"
            @click="$router.push(`/history/${r.name}`)"
          >
            <td class="max-w-[280px] truncate py-2 pr-4">{{ r.test_method }}</td>
            <td class="py-2 pr-4">{{ r.app }}</td>
            <td class="py-2 pr-4">{{ r.run_scope }}</td>
            <td class="py-2 pr-4">{{ r.reference_type || '—' }}</td>
            <td class="py-2 pr-4"><Badge :theme="theme(r.status)" :label="r.status" /></td>
            <td class="py-2 pr-4">{{ r.duration ? r.duration + 's' : '—' }}</td>
            <td class="py-2 pr-4 text-ink-gray-5">{{ r.creation }}</td>
          </tr>
          <tr v-if="!runs.loading && !(runs.data || []).length">
            <td colspan="7" class="p-8 text-center text-ink-gray-5">No runs found.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Bottom bar — page-size pills (left) + count and Load more (right) -->
    <div
      class="flex flex-shrink-0 items-center justify-between border-t border-outline-gray-2 px-6 py-2"
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
  </div>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { createListResource } from 'frappe-ui'
import { api } from '@/api'

const STORAGE_KEY = 'tc_history_filters_v1'

const filters = reactive({ app: '', status: '', type: '', search: '' })
const pageSize = ref(20)
const apps = ref([])

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
  return f
}

const runs = createListResource({
  doctype: 'Testcase Run',
  fields: [
    'name',
    'test_method',
    'app',
    'run_scope',
    'status',
    'duration',
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
  () => [filters.app, filters.status, filters.type, pageSize.value],
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
  return 'gray' // Stopped, etc.
}

async function loadApps() {
  apps.value = (await api.getInstalledApps()) || []
}

restoreFilters()
loadApps()
applyAndReload()
</script>
