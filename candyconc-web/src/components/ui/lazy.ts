/**
 * Lazy-loaded UI components for code splitting
 * Use for heavy components that are shown conditionally
 */
import { defineAsyncComponent } from 'vue'

// Command palette with search/filtering logic
export const CommandPalette = defineAsyncComponent({
  loader: () => import('./CommandPalette.vue'),
  delay: 50
})

// Shortcuts overlay (rarely shown)
export const ShortcutsOverlay = defineAsyncComponent({
  loader: () => import('./ShortcutsOverlay.vue'),
  delay: 50
})
