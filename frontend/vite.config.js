import path from 'path'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import frappeui from 'frappe-ui/vite'

export default defineConfig({
  plugins: [
    frappeui({
      // Drives: dev proxy, SPA route rule target, build outDir
      // (../testcase_manager/public/frontend) and baseUrl
      // (/assets/testcase_manager/frontend/).
      frontendRoute: '/testcase-manager',
      // The www page (controller + template) must stay underscored:
      // Frappe imports the www controller as a Python module, and
      // "testcase-manager.py" is not a valid module name, so get_context
      // (which injects csrf_token into boot) would silently not run.
      // Public URL stays /testcase-manager via website_route_rules → to_route.
      buildConfig: {
        indexHtmlPath: '../testcase_manager/www/testcase_manager.html',
      },
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
