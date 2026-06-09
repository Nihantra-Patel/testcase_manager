<template>
  <div class="flex h-full flex-col bg-surface-white text-ink-gray-9">
    <!-- Top bar -->
    <header
      class="flex h-12 flex-shrink-0 items-center justify-between border-b border-outline-gray-2 px-4"
    >
      <div class="flex items-center gap-2">
        <FeatherIcon name="check-circle" class="h-5 w-5 text-ink-green-3" />
        <span class="text-base font-semibold">Testcase Manager</span>
      </div>
      <div class="flex items-center gap-3">
        <nav class="flex items-center gap-1 rounded-lg bg-surface-gray-2 p-0.5">
          <RouterLink
            v-for="link in links"
            :key="link.to"
            :to="link.to"
            v-slot="{ isActive, isExactActive }"
          >
            <button
              class="rounded-md px-3 py-1 text-sm font-medium transition-colors"
              :class="
                (link.exact ? isExactActive : isActive)
                  ? 'bg-surface-white text-ink-gray-9 shadow-sm'
                  : 'text-ink-gray-6 hover:text-ink-gray-8'
              "
            >
              {{ link.label }}
            </button>
          </RouterLink>
        </nav>

        <!-- Light / dark theme toggle -->
        <button
          class="flex h-7 w-12 items-center rounded-full border border-outline-gray-2 bg-surface-gray-2 px-0.5 transition-colors"
          :title="isDark ? 'Switch to light mode' : 'Switch to dark mode'"
          @click="toggleTheme"
        >
          <span
            class="flex h-5 w-5 items-center justify-center rounded-full bg-surface-white shadow-sm transition-transform"
            :class="isDark ? 'translate-x-5' : 'translate-x-0'"
          >
            <FeatherIcon :name="isDark ? 'moon' : 'sun'" class="h-3 w-3 text-ink-gray-7" />
          </span>
        </button>
      </div>
    </header>

    <main class="min-h-0 flex-1 overflow-hidden">
      <RouterView />
    </main>

    <ToastProvider />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ToastProvider } from 'frappe-ui'

const links = [
  // exact match for Runner so it isn't highlighted on /history routes
  { to: '/', label: 'Runner', exact: true },
  { to: '/history', label: 'History' },
]

// Light / dark theme. frappe-ui's design tokens (surface-/ink-/outline-) respond
// to data-theme="dark" on <html>. Default is LIGHT; the choice is persisted.
const theme = ref(localStorage.getItem('theme') === 'dark' ? 'dark' : 'light')
const isDark = computed(() => theme.value === 'dark')

function applyTheme(t) {
  theme.value = t
  document.documentElement.setAttribute('data-theme', t)
  localStorage.setItem('theme', t)
}
function toggleTheme() {
  applyTheme(isDark.value ? 'light' : 'dark')
}

// Apply persisted (or default light) theme immediately on load.
applyTheme(theme.value)
</script>
