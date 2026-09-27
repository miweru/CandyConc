/**
 * CandyConc Frontend - Entry Point
 */
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import { VueQueryPlugin } from '@tanstack/vue-query'
import App from './App.vue'
import { i18n } from './i18n'
import { startAuthBootstrap } from './api/auth'
import { registerActionHandlers } from './actions/handlers'
// Run records are loaded automatically when the module is imported
import './services/runRecordService'
import './style.css'

// Create app instance
const app = createApp(App)

// State management
const pinia = createPinia()
app.use(pinia)

// Interface language. The settings store sets the active locale on creation.
app.use(i18n)

// Register action handlers (must be after pinia)
registerActionHandlers()

// Data fetching
app.use(VueQueryPlugin, {
  queryClientConfig: {
    defaultOptions: {
      queries: {
        staleTime: 1000 * 60 * 5, // 5 minutes
        retry: 1,
        refetchOnWindowFocus: false
      }
    }
  }
})

// Mount. First acquire a local dev token (if the backend issues one — RBAC off,
// not release) so local token-gated analysis endpoints work before a manual login.
// Never blocks longer than the auth-bootstrap timeout and never throws, so the
// app always mounts (degrading gracefully if no token is available).
void startAuthBootstrap().finally(() => {
  app.mount('#app')
})

// Log startup in dev mode
if (import.meta.env.DEV) {
  console.log('%c🍬 CandyConc Frontend', 'color: #8b5cf6; font-size: 16px; font-weight: bold')
  console.log('Shortcuts: Cmd+K (Palette), Cmd+Shift+K (Copilot), Alt+1-8 (Tabs), Cmd+, (Settings), Cmd+E (Export), ? (Help), / (Search)')
}
