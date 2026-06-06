<template>
  <div class="flex h-full flex-col overflow-hidden">
    <div class="flex items-center justify-between border-b border-outline-gray-2 px-4 py-2.5">
      <div class="flex items-center gap-3">
        <Button variant="ghost" size="sm" @click="$router.push('/history')">
          <FeatherIcon name="arrow-left" class="h-4 w-4" />
        </Button>
        <span class="truncate text-sm font-semibold">{{ doc?.test_method || runName }}</span>
        <Badge v-if="doc" :theme="theme(doc.status)" :label="doc.status" />
      </div>
      <div class="flex items-center gap-3 text-xs text-ink-gray-5">
        <span>{{ doc?.app }}</span>
        <span v-if="doc?.duration">{{ doc.duration }}s</span>
      </div>
    </div>

    <div v-if="run.loading" class="p-6 text-sm text-ink-gray-5">Loading…</div>

    <template v-else-if="doc">
      <div v-if="doc.result" class="border-b border-outline-gray-2 px-4 py-2 text-sm font-semibold">
        {{ doc.result }}
      </div>
      <Console :lines="outputLines" />
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { createResource } from 'frappe-ui'
import Console from '@/components/Console.vue'

const props = defineProps({ runName: { type: String, required: true } })

const run = createResource({
  url: 'frappe.client.get',
  params: { doctype: 'Testcase Run', name: props.runName },
  auto: true,
})

const doc = computed(() => run.data)
const outputLines = computed(() =>
  (doc.value?.full_output || 'No output.').split('\n').map((text) => ({ text })),
)

function theme(status) {
  if (status === 'Passed') return 'green'
  if (status === 'Failed' || status === 'Error') return 'red'
  if (status === 'Running' || status === 'Pending') return 'orange'
  return 'gray'
}
</script>
