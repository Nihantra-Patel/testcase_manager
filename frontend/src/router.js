import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Runner',
    component: () => import('@/pages/RunnerView.vue'),
  },
  {
    path: '/profiler',
    name: 'Profiler',
    component: () => import('@/pages/ProfilerView.vue'),
  },
  {
    path: '/history',
    name: 'History',
    component: () => import('@/pages/HistoryView.vue'),
  },
  {
    path: '/history/:runName',
    name: 'RunDetail',
    component: () => import('@/pages/RunDetailView.vue'),
    props: true,
  },
]

const router = createRouter({
  // Served under /testcase-manager (see website_route_rules in hooks.py).
  history: createWebHistory('/testcase-manager'),
  routes,
})

export default router
