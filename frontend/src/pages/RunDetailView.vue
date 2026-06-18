<template>
  <div class="flex h-full flex-col overflow-hidden">
    <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-2.5">
      <div class="flex items-center gap-3">
        <Button variant="ghost" size="sm" @click="$router.push('/history')">
          <FeatherIcon name="arrow-left" class="h-4 w-4" />
        </Button>
        <span class="truncate text-sm font-semibold">{{ doc?.test_method || runName }}</span>
        <Badge v-if="doc" :theme="theme(displayStatus)" :label="displayStatus" />
      </div>
      <div class="flex items-center gap-3 text-xs text-ink-gray-5">
        <Button
          v-if="canRerun"
          variant="subtle"
          theme="red"
          size="sm"
          :loading="rerunning"
          label="Rerun failed"
          title="Re-run only the failed and errored tests as a new batch"
          @click="rerunFailed"
        >
          <template #prefix><FeatherIcon name="refresh-cw" class="h-3.5 w-3.5" /></template>
        </Button>
        <span>{{ doc?.app }}</span>
        <span v-if="doc?.duration">{{ doc.duration }}s</span>
      </div>
    </div>

    <div v-if="run.loading && !doc" class="p-6 text-sm text-ink-gray-5">Loading…</div>

    <template v-else-if="doc">
      <div
        v-if="summary"
        class="flex items-center gap-3 border-b border-outline-gray-2 px-4 py-2 text-sm font-medium tabular-nums"
      >
        <span class="text-ink-gray-6">{{ summary.total }} / {{ summary.total }} tests</span>
        <span :class="summary.passed ? 'text-ink-green-3' : 'text-ink-gray-5'">
          ✓ {{ summary.passed }} Passed
        </span>
        <span
          :class="summary.failed ? 'text-ink-red-3' : 'text-ink-gray-5'"
          title="An assertion failed"
        >
          ✕ {{ summary.failed }} Failed
        </span>
        <span
          :class="summary.errors ? 'text-ink-amber-3' : 'text-ink-gray-5'"
          title="The test crashed with an unexpected exception"
        >
          ⚠ {{ summary.errors }} Errors
        </span>
      </div>
      <div
        v-else-if="doc.result"
        class="border-b border-outline-gray-2 px-4 py-2 text-sm font-semibold"
      >
        {{ doc.result }}
      </div>
      <Console :lines="outputLines" />
    </template>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { createResource, toast } from 'frappe-ui'
import Console from '@/components/Console.vue'
import { api } from '@/api'
import { useSocket } from '@/socket'
import { stripAnsi } from '@/utils'

const props = defineProps({ runName: { type: String, required: true } })

const socket = useSocket()
const router = useRouter()

// Lines streamed live while the run is still in progress. Only consulted while
// `streaming` is true; once the run finishes we fall back to the saved
// full_output (the authoritative final output).
const liveLines = ref([])
const streaming = ref(false)
// Local status override from realtime completion, so the badge updates without
// waiting for the doc reload.
const liveStatus = ref(null)

const run = createResource({
  url: 'frappe.client.get',
  params: { doctype: 'Testcase Run', name: props.runName },
  auto: true,
  onSuccess(d) {
    // Stream live only if the run is still active; otherwise show saved output.
    if (d && ['Running', 'Pending'].includes(d.status)) startLive(d)
  },
})

const doc = computed(() => run.data)
const displayStatus = computed(() => liveStatus.value || doc.value?.status || 'Unknown')

// Parse the run's `result` ("Passed: X, Failed: Y, Errors: Z") into a styled
// tally that mirrors the Runner footer. Null when no tally was recorded.
const summary = computed(() => {
  const result = doc.value?.result
  if (!result) return null
  const m = result.match(/Passed:\s*(\d+),\s*Failed:\s*(\d+),\s*Errors:\s*(\d+)/i)
  if (!m) return null
  const passed = +m[1]
  const failed = +m[2]
  const errors = +m[3]
  return { passed, failed, errors, total: passed + failed + errors }
})

// Offer "Rerun failed" only on a finished run that actually had failures/errors.
const canRerun = computed(() => {
  if (['Running', 'Pending'].includes(displayStatus.value)) return false
  return !!summary.value && summary.value.failed + summary.value.errors > 0
})

const rerunning = ref(false)
async function rerunFailed() {
  if (rerunning.value) return
  rerunning.value = true
  try {
    // background=1 → realtime run so this view streams it as it executes.
    const res = await api.rerunFailed(props.runName, 1)
    toast({ title: 'Re-running failed tests…', icon: 'check', iconClasses: 'text-green-600' })
    // Switch straight to the new run's full view (the latest history log).
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

const outputLines = computed(() => {
  // While actively streaming, show whatever has come in (may be empty briefly).
  if (streaming.value) return liveLines.value
  // Finished run → the saved full_output is the source of truth.
  return (doc.value?.full_output || 'No output.').split('\n').map((text) => ({ text }))
})

// ── Realtime (only while the run is Running/Pending) ────────────────────────
function onOutput(data) {
  if (!data || data.run_name !== props.runName) return
  liveLines.value.push({ text: stripAnsi(String(data.line ?? '')) })
}
function onCompleted(data) {
  if (!data || data.run_name !== props.runName) return
  liveStatus.value = data.status || 'Passed'
  teardownLive()
  // Reload the saved doc so full_output/result/duration reflect the final state;
  // outputLines switches to full_output now that `streaming` is false.
  run.reload()
}

let subscribed = false
function startLive(d) {
  if (subscribed) return
  subscribed = true
  streaming.value = true
  // Seed with output already persisted before we attached (split, drop trailing
  // empty so an empty field doesn't render a stray blank line).
  const seed = (d.full_output || '').split('\n')
  if (seed.length === 1 && seed[0] === '') seed.length = 0
  liveLines.value = seed.map((text) => ({ text }))
  socket.emit('task_subscribe', props.runName)
  socket.on('test_output', onOutput)
  socket.on('test_completed', onCompleted)
}
function teardownLive() {
  streaming.value = false
  if (!subscribed) return
  subscribed = false
  socket.emit('task_unsubscribe', props.runName)
  socket.off('test_output', onOutput)
  socket.off('test_completed', onCompleted)
}

onBeforeUnmount(teardownLive)
watch(() => props.runName, teardownLive)

function theme(status) {
  if (status === 'Passed') return 'green'
  if (status === 'Failed' || status === 'Error') return 'red'
  if (status === 'Running' || status === 'Pending') return 'orange'
  return 'gray'
}
</script>
