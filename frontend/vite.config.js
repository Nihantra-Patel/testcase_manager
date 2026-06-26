import path from 'path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'

export default defineConfig({
  plugins: [
    frappeui({
      // Drives: dev proxy, SPA route rule target, build outDir
      // (../testcase_manager/public/frontend), baseUrl
      // (/assets/testcase_manager/frontend/) and copies the built index.html
      // to ../testcase_manager/www/testcase-manager.html
      frontendRoute: '/testcase-manager',
      frappeProxy: true,
      lucideIcons: true,
      jinjaBootData: true,
    }),
    vue(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, 'src'),
    },
  },
  server: {
    allowedHosts: true,
    fs: {
      allow: ['..', 'node_modules'],
    },
  },
  optimizeDeps: {
    include: ['feather-icons', 'showdown', 'tailwind.config.js'],
  },
})
