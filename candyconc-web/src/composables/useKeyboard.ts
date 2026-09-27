/**
 * useKeyboard Composable - Global keyboard shortcuts
 */

import { onMounted, onUnmounted } from 'vue'
import { asSwitchTabId, useUiStore, useCopilotStore, useCorpusCapabilitiesStore, useProductCapabilitiesStore } from '@/stores'
import { actionBus } from '@/actions'
import { analysisTabSurfaces } from '@/lib/productCapabilities'
import { t } from '@/i18n'

interface Shortcut {
  key: string
  ctrl?: boolean
  meta?: boolean
  shift?: boolean
  alt?: boolean
  handler: () => void | Promise<unknown>
  description?: string
}

const navigationShortcuts: Shortcut[] = analysisTabSurfaces.map((surface) => ({
  key: surface.shortcut.replace('Alt+', ''),
  alt: true,
  handler: async () => {
    const productCapabilities = useProductCapabilitiesStore()
    const corpusCapabilities = useCorpusCapabilitiesStore()
    await productCapabilities.ensureAccessContext()
    let availability = productCapabilities.surfaceAvailability(
      surface.capabilityId,
      corpusCapabilities.activeSummary,
    )
    if (availability.corpusFeatureDecision.status === 'unknown') {
      await corpusCapabilities.fetchCapabilities(corpusCapabilities.activeCorpus)
      availability = productCapabilities.surfaceAvailability(
        surface.capabilityId,
        corpusCapabilities.activeSummary,
      )
    }
    if (!availability.visible || !availability.enabled) {
      useUiStore().showToast(
        availability.disabledReason ?? t('capabilities.store.notEnabledContext', { label: surface.label }),
        'warning',
      )
      return
    }
    return actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: asSwitchTabId(surface.tab) } })
  },
  description: `Switch to ${surface.label} tab`,
}))

async function canUseSurface(id: string): Promise<boolean> {
  const productCapabilities = useProductCapabilitiesStore()
  await productCapabilities.ensureAccessContext()
  const availability = productCapabilities.surfaceAvailability(id)
  if (!availability.visible || !availability.enabled) {
    if (availability.disabledReason) {
      useUiStore().showToast(availability.disabledReason, 'warning')
    }
    return false
  }
  return true
}

async function canUseAnySurface(ids: string[]): Promise<boolean> {
  const productCapabilities = useProductCapabilitiesStore()
  await productCapabilities.ensureAccessContext()
  const decisions = ids
    .map((id) => productCapabilities.surfaceAvailability(id))
    .filter((availability) => availability.visible)
  if (decisions.some((availability) => availability.enabled)) return true
  const reason = decisions.find((availability) => availability.disabledReason)?.disabledReason
  if (reason) useUiStore().showToast(reason, 'warning')
  return false
}

// Global shortcuts registry
const shortcuts: Shortcut[] = [
  // Copilot
  {
    key: 'k',
    meta: true,
    handler: () => {
      const ui = useUiStore()
      ui.openCommandPalette()
    },
    description: 'Open Command Palette'
  },
  {
    key: 'k',
    meta: true,
    shift: true,
    handler: async () => {
      if (!(await canUseSurface('research.copilot_grounding'))) return
      const copilot = useCopilotStore()
      copilot.toggle()
    },
    description: 'Toggle Copilot'
  },
  {
    key: 'Escape',
    handler: () => {
      const ui = useUiStore()
      const copilot = useCopilotStore()
      ui.closeCommandPalette()
      ui.closeShortcuts()
      if (copilot.isOpen) {
        copilot.close()
      }
    },
    description: 'Close Copilot'
  },
  ...navigationShortcuts,

  // Selection
  {
    key: 'a',
    meta: true,
    handler: () => {
      const ui = useUiStore()
      if (ui.activeTab === 'kwic') {
        actionBus.dispatch({ type: 'kwic/selectRows', payload: { indices: [] } }) // Select all handled in component
      }
    },
    description: 'Select all rows', // i18n-ignore: internal, not displayed
  },
  
  // Focus search
  {
    key: '/',
    handler: () => {
      const searchInput = document.querySelector('[data-search-input]') as HTMLInputElement
      searchInput?.focus()
    },
    description: 'Focus search input'
  },
  
  // Theme toggle
  {
    key: 't',
    meta: true,
    shift: true,
    handler: () => {
      const ui = useUiStore()
      ui.toggleTheme()
    },
    description: 'Toggle dark mode'
  },

  // Settings
  {
    key: ',',
    meta: true,
    handler: async () => {
      if (!(await canUseAnySurface([
        'settings.preferences',
        'settings.embedding_management',
        'admin.system_operations',
        'corpus.catalogue',
        'corpus.import',
      ]))) return
      const ui = useUiStore()
      ui.openSettings()
    },
    description: 'Open Settings', // i18n-ignore: internal, not displayed
  },

  // Export
  {
    key: 'e',
    meta: true,
    handler: async () => {
      if (!(await canUseSurface('research.replay_export'))) return
      const ui = useUiStore()
      ui.openExport()
    },
    description: 'Open Export Dialog', // i18n-ignore: internal, not displayed
  },

  // Query Builder
  {
    key: 'b',
    meta: true,
    handler: async () => {
      if (!(await canUseSurface('query.cqlf'))) return
      const ui = useUiStore()
      ui.openQueryBuilder()
    },
    description: 'Open Query Builder'
  },

  // Shortcuts overlay
  {
    key: '?',
    shift: true,
    handler: () => {
      const ui = useUiStore()
      ui.toggleShortcuts()
    },
    description: 'Show Shortcuts', // i18n-ignore: internal, not displayed
  }
]

function matchesShortcut(event: KeyboardEvent, shortcut: Shortcut): boolean {
  const keyMatch = event.key.toLowerCase() === shortcut.key.toLowerCase()
  const ctrlMatch = !!shortcut.ctrl === (event.ctrlKey && !event.metaKey)
  const metaMatch = !!shortcut.meta === event.metaKey
  const shiftMatch = !!shortcut.shift === event.shiftKey
  const altMatch = !!shortcut.alt === event.altKey

  return keyMatch && ctrlMatch && metaMatch && shiftMatch && altMatch
}

export function useKeyboard() {
  const uiStore = useUiStore()

  function handleKeyDown(event: KeyboardEvent) {
    // Skip if shortcuts disabled or in input field
    if (!uiStore.shortcutsEnabled) return
    
    const target = event.target as HTMLElement
    const isInput = target.tagName === 'INPUT' || 
                    target.tagName === 'TEXTAREA' || 
                    target.isContentEditable

    // Allow some shortcuts even in inputs
    const allowInInput = ['Escape', 'k', ',', 'e']

    for (const shortcut of shortcuts) {
      if (matchesShortcut(event, shortcut)) {
        if (isInput && !allowInInput.includes(shortcut.key)) {
          continue
        }
        
        event.preventDefault()
        shortcut.handler()
        return
      }
    }
  }

  onMounted(() => {
    window.addEventListener('keydown', handleKeyDown)
  })

  onUnmounted(() => {
    window.removeEventListener('keydown', handleKeyDown)
  })

  return {
    shortcuts: shortcuts.map(s => ({
      key: s.key,
      modifiers: {
        ctrl: s.ctrl,
        meta: s.meta,
        shift: s.shift,
        alt: s.alt
      },
      description: s.description
    }))
  }
}

/**
 * Register a custom shortcut
 */
export function registerShortcut(shortcut: Shortcut): () => void {
  shortcuts.push(shortcut)
  return () => {
    const idx = shortcuts.indexOf(shortcut)
    if (idx > -1) shortcuts.splice(idx, 1)
  }
}
