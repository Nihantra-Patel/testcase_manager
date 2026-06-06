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
    </header>

    <main class="min-h-0 flex-1 overflow-hidden">
      <RouterView />
    </main>

    <ToastProvider />
  </div>
</template>

<script setup>
import { ToastProvider } from 'frappe-ui'

const links = [
  // exact match for Runner so it isn't highlighted on /history routes
  { to: '/', label: 'Runner', exact: true },
  { to: '/history', label: 'History' },
]
</script>
