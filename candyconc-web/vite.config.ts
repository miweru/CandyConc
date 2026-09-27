import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import tailwindcss from '@tailwindcss/vite'
import { fileURLToPath, URL } from 'node:url'
import { createDevProxy } from './vite.proxy'
import { thirdPartyLicenses } from './tooling/thirdPartyLicenses'

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), tailwindcss(), thirdPartyLicenses()],
  // vue-i18n feature flags: Composition API only, runtime message compiler on.
  define: {
    __VUE_I18N_FULL_INSTALL__: true,
    __VUE_I18N_LEGACY_API__: false,
    __INTLIFY_PROD_DEVTOOLS__: false,
    __INTLIFY_DROP_MESSAGE_COMPILER__: false,
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  build: {
    rollupOptions: {
      output: {
        manualChunks: {
          // Vue core + state management
          'vue-vendor': ['vue', 'pinia'],
          // Interface icons
          'ui-vendor': ['lucide-vue-next'],
          // Data visualization (D3 is large)
          'd3-vendor': ['d3'],
          // Data fetching & virtualization
          'data-vendor': ['@tanstack/vue-query', '@tanstack/vue-virtual', 'ky'],
          // Schema validation
          'zod-vendor': ['zod']
        }
      }
    },
    chunkSizeWarningLimit: 300
  },
  server: {
    port: 5173,
    proxy: createDevProxy()
  }
})
