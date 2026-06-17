<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- Control bar -->
    <div
      class="flex flex-wrap items-end gap-3 border-b border-outline-gray-2 bg-surface-white px-8 py-3"
    >
      <!-- DocType picker -->
      <div class="relative w-[220px]">
        <div class="mb-1 text-xs font-semibold text-ink-gray-5">DocType</div>
        <FormControl
          v-model="doctypeSearch"
          type="text"
          placeholder="Search DocType…"
          class="w-full"
          @focus="dtOpen = true"
          @update:modelValue="onDoctypeSearch"
        />
        <div
          v-if="dtOpen && doctypeOptions.length"
          class="absolute z-10 mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-outline-gray-2 bg-surface-white shadow-md"
        >
          <button
            v-for="dt in doctypeOptions"
            :key="dt"
            class="block w-full truncate px-3 py-1.5 text-left text-sm hover:bg-surface-gray-2"
            @mousedown.prevent="selectDoctype(dt)"
          >
            {{ dt }}
          </button>
        </div>
      </div>

      <!-- Record picker -->
      <div class="relative w-[260px]">
        <div class="mb-1 text-xs font-semibold text-ink-gray-5">Record</div>
        <FormControl
          v-model="recordSearch"
          type="text"
          :disabled="!doctype"
          placeholder="Search a record…"
          class="w-full"
          @focus="onRecordFocus"
          @update:modelValue="onRecordSearch"
        />
        <div
          v-if="recOpen && recordOptions.length"
          class="absolute z-10 mt-1 max-h-60 w-full overflow-y-auto rounded-md border border-outline-gray-2 bg-surface-white shadow-md"
        >
          <button
            v-for="r in recordOptions"
            :key="r"
            class="block w-full truncate px-3 py-1.5 text-left text-sm hover:bg-surface-gray-2"
            @mousedown.prevent="selectRecord(r)"
          >
            {{ r }}
          </button>
        </div>
      </div>

      <!-- Action -->
      <div class="w-[230px]">
        <div class="mb-1 text-xs font-semibold text-ink-gray-5">Action</div>
        <Select v-model="action" :options="actionOptions" class="w-full" />
      </div>

      <div class="ml-auto flex items-end gap-2">
        <Button variant="solid" :loading="loading" :disabled="!canProfile" @click="runProfile">
          <template #prefix><FeatherIcon name="clock" class="h-3.5 w-3.5" /></template>
          Profile
        </Button>
        <Button variant="subtle" label="Clear" @click="clearAll" />
      </div>
    </div>

    <!-- Caveat -->
    <div class="border-b border-outline-gray-2 bg-surface-gray-1 px-8 py-2 text-[11px] text-ink-gray-5">
      Runs the selected action inside a database savepoint and rolls it back — all
      hooks fire (real timings) but nothing is saved. cProfile adds overhead, so
      read times relatively, not as absolute production numbers.
    </div>

    <!-- Output -->
    <div v-if="error" class="bg-[#4a1515] px-8 py-2 text-sm font-bold text-[#ff7b72]">
      {{ error }}
    </div>

    <div
      v-if="hasOutput"
      class="flex items-center border-b border-outline-gray-2 px-8 py-1.5 text-xs font-medium text-ink-gray-6"
    >
      cProfile <span class="ml-2 truncate text-ink-gray-5">{{ lastLabel }}</span>
    </div>

    <div v-if="!hasOutput && !loading" class="flex flex-1 items-center justify-center p-10 text-sm text-ink-gray-5">
      Pick a DocType, a record, and an action — then Profile to see where time goes.
    </div>
    <Console v-else :lines="profileLines" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { call, toast } from 'frappe-ui'
import Console from '@/components/Console.vue'
import { api } from '@/api'

const doctype = ref('')
const docName = ref('')
const action = ref('submit')
const actionOptions = [
  { label: 'Submit (real doc, rolled back)', value: 'submit' },
  { label: 'Cancel (real doc, rolled back)', value: 'cancel' },
]

// The chosen doctype/record are derived from their search text: a selection is
// valid only while the text still equals the picked value. This avoids the
// fragile "programmatic set re-fires the input handler and clears the choice"
// race — selecting sets the text, and validity is computed from it, so there is
// no value to be clobbered.

// ── DocType picker ──────────────────────────────────────────────────────────
const doctypeSearch = ref('')
const doctypeOptions = ref([])
const dtOpen = ref(false)
let dtTimer
function onDoctypeSearch(v) {
  // Only treat typing as a new search when it diverges from the current choice.
  if (v === doctype.value) return
  doctype.value = ''
  clearTimeout(dtTimer)
  dtTimer = setTimeout(async () => {
    doctypeOptions.value = (await api.getProfileableDoctypes(v || '')) || []
    dtOpen.value = true
  }, 250)
}
function selectDoctype(dt) {
  doctype.value = dt
  doctypeSearch.value = dt
  dtOpen.value = false
  // Reset the record selection whenever the doctype changes.
  docName.value = ''
  recordSearch.value = ''
  recordOptions.value = []
}

// ── Record picker ───────────────────────────────────────────────────────────
const recordSearch = ref('')
const recordOptions = ref([])
const recOpen = ref(false)
let recTimer
function onRecordSearch(v) {
  if (v === docName.value) return
  docName.value = ''
  clearTimeout(recTimer)
  recTimer = setTimeout(async () => {
    if (!doctype.value) return
    recordOptions.value = await searchRecords(v || '')
    recOpen.value = true
  }, 250)
}
// Focusing the (empty) record field should immediately show recent records, so
// the user can pick without typing — mirrors a Link field's behaviour.
async function onRecordFocus() {
  recOpen.value = true
  if (doctype.value && !recordOptions.value.length) {
    recordOptions.value = await searchRecords('')
  }
}
async function searchRecords(txt) {
  const r = await call('frappe.client.get_list', {
    doctype: doctype.value,
    filters: txt ? [[doctype.value, 'name', 'like', `%${txt}%`]] : [],
    fields: ['name'],
    limit_page_length: 25,
    order_by: 'modified desc',
  })
  return (r || []).map((x) => x.name)
}
function selectRecord(r) {
  docName.value = r
  recordSearch.value = r
  recOpen.value = false
}

// ── Profile run ─────────────────────────────────────────────────────────────
const loading = ref(false)
const error = ref('')
const profileText = ref('')
const lastLabel = ref('')

const canProfile = computed(() => !!doctype.value && !!docName.value && !loading.value)
const hasOutput = computed(() => !!profileText.value)
const profileLines = computed(() =>
  (profileText.value || '').split('\n').map((text) => ({ text })),
)

async function runProfile() {
  loading.value = true
  error.value = ''
  profileText.value = ''
  try {
    const res = await api.profileDocument(doctype.value, docName.value, action.value)
    profileText.value = res.profile_data || ''
    error.value = res.error || ''
    lastLabel.value = `${res.doctype} · ${res.name} · ${res.action}`
    if (!profileText.value && !error.value) {
      toast({ title: 'No profile captured', icon: 'info' })
    }
  } catch (e) {
    error.value = e?.messages?.[0] || 'Profiling failed'
    toast({ title: error.value, icon: 'x', iconClasses: 'text-red-600' })
  } finally {
    loading.value = false
  }
}

function clearAll() {
  doctype.value = ''
  doctypeSearch.value = ''
  docName.value = ''
  recordSearch.value = ''
  doctypeOptions.value = []
  recordOptions.value = []
  profileText.value = ''
  error.value = ''
  lastLabel.value = ''
}
</script>
