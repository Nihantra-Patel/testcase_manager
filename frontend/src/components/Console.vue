<template>
  <div
    ref="el"
    class="flex-1 overflow-y-auto whitespace-pre-wrap break-all bg-[#0d1117] px-4 py-3.5 font-mono text-xs leading-relaxed"
  >
    <div v-for="(l, i) in lines" :key="i" :class="lineColor(l.text)">{{ l.text || ' ' }}</div>
  </div>
</template>

<script setup>
import { nextTick, ref, watch } from 'vue'
import { lineColor } from '@/utils'

const props = defineProps({
  lines: { type: Array, default: () => [] },
})

const el = ref(null)

// Auto-scroll to the bottom as new lines stream in.
watch(
  () => props.lines.length,
  async () => {
    await nextTick()
    if (el.value) el.value.scrollTop = el.value.scrollHeight
  },
)
</script>
