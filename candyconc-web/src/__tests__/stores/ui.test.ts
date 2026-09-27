/**
 * UI Store Tests
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUiStore } from '@/stores/ui'

describe('useUiStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    // Reset document state
    document.documentElement.classList.remove('dark', 'pink')
  })

  afterEach(() => {
    vi.clearAllTimers()
  })

  describe('initial state', () => {
    it('should have default values', () => {
      const store = useUiStore()

      expect(store.activeTab).toBe('kwic')
      expect(store.theme).toBe('system')
      expect(store.sidebarOpen).toBe(true)
      expect(store.toasts).toEqual([])
      expect(store.commandPaletteOpen).toBe(false)
      expect(store.shortcutsOpen).toBe(false)
      expect(store.settingsOpen).toBe(false)
    })
  })

  describe('setActiveTab', () => {
    it('should change active tab', () => {
      const store = useUiStore()

      store.setActiveTab('frequency')
      expect(store.activeTab).toBe('frequency')

      store.setActiveTab('collocations')
      expect(store.activeTab).toBe('collocations')
    })
  })

  describe('theme', () => {
    it('applies and restores the pink theme and removes it when switching designs', () => {
      const store = useUiStore()
      store.setTheme('dark')
      store.setTheme('pink')
      expect(document.documentElement.classList.contains('pink')).toBe(true)
      expect(document.documentElement.classList.contains('dark')).toBe(false)
      expect(localStorage.setItem).toHaveBeenCalledWith('candyconc_theme', 'pink')

      vi.mocked(localStorage.getItem).mockReturnValueOnce('pink')
      setActivePinia(createPinia())
      const restored = useUiStore()
      expect(restored.theme).toBe('pink')
      expect(document.documentElement.classList.contains('pink')).toBe(true)
      for (const theme of ['light', 'dark', 'system'] as const) {
        restored.setTheme(theme)
        expect(document.documentElement.classList.contains('pink')).toBe(false)
      }
    })

    it('should set theme', () => {
      const store = useUiStore()

      store.setTheme('dark')
      expect(store.theme).toBe('dark')

      store.setTheme('light')
      expect(store.theme).toBe('light')
    })

    it('should toggle theme', () => {
      const store = useUiStore()

      // Start with light (system defaults to light in mock)
      store.setTheme('light')
      store.toggleTheme()
      expect(store.theme).toBe('dark')

      store.toggleTheme()
      expect(store.theme).toBe('light')
    })

    it('should compute isDarkMode correctly', () => {
      const store = useUiStore()

      store.setTheme('dark')
      expect(store.isDarkMode).toBe(true)

      store.setTheme('light')
      expect(store.isDarkMode).toBe(false)
    })
  })

  describe('sidebar', () => {
    it('should toggle sidebar', () => {
      const store = useUiStore()

      expect(store.sidebarOpen).toBe(true)

      store.toggleSidebar()
      expect(store.sidebarOpen).toBe(false)

      store.toggleSidebar()
      expect(store.sidebarOpen).toBe(true)
    })
  })

  describe('loading states', () => {
    it('should set loading state', () => {
      const store = useUiStore()

      store.setLoading('query', true)
      expect(store.isLoadingKey('query')).toBe(true)
      expect(store.isLoading).toBe(true)

      store.setLoading('query', false)
      expect(store.isLoadingKey('query')).toBe(false)
      expect(store.isLoading).toBe(false)
    })

    it('should handle multiple loading states', () => {
      const store = useUiStore()

      store.setLoading('query', true)
      store.setLoading('analysis', true)

      expect(store.isLoading).toBe(true)

      store.setLoading('query', false)
      expect(store.isLoading).toBe(true) // analysis still loading

      store.setLoading('analysis', false)
      expect(store.isLoading).toBe(false)
    })
  })

  describe('toasts', () => {
    beforeEach(() => {
      vi.useFakeTimers()
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it('should show toast', () => {
      const store = useUiStore()

      const id = store.showToast('Test message', 'info')

      expect(store.toasts).toHaveLength(1)
      expect(store.toasts[0]?.message).toBe('Test message')
      expect(store.toasts[0]?.type).toBe('info')
      expect(store.toasts[0]?.id).toBe(id)
    })

    it('should auto-remove toast after duration', () => {
      const store = useUiStore()

      store.showToast('Auto remove', 'success', 3000)
      expect(store.toasts).toHaveLength(1)

      vi.advanceTimersByTime(3000)
      expect(store.toasts).toHaveLength(0)
    })

    it('should manually remove toast', () => {
      const store = useUiStore()

      const id = store.showToast('Manual remove', 'warning', 0) // No auto-remove
      expect(store.toasts).toHaveLength(1)

      store.removeToast(id)
      expect(store.toasts).toHaveLength(0)
    })

    it('should clear all toasts', () => {
      const store = useUiStore()

      store.showToast('Toast 1', 'info', 0)
      store.showToast('Toast 2', 'success', 0)
      store.showToast('Toast 3', 'error', 0)

      expect(store.toasts).toHaveLength(3)

      store.clearToasts()
      expect(store.toasts).toHaveLength(0)
    })

    it('should support different toast types', () => {
      const store = useUiStore()

      store.showToast('Info', 'info', 0)
      store.showToast('Success', 'success', 0)
      store.showToast('Warning', 'warning', 0)
      store.showToast('Error', 'error', 0)

      expect(store.toasts.map(t => t.type)).toEqual([
        'info', 'success', 'warning', 'error'
      ])
    })
  })

  describe('modal states', () => {
    it('should open and close command palette', () => {
      const store = useUiStore()

      expect(store.commandPaletteOpen).toBe(false)

      store.openCommandPalette()
      expect(store.commandPaletteOpen).toBe(true)

      store.closeCommandPalette()
      expect(store.commandPaletteOpen).toBe(false)
    })

    it('should toggle command palette', () => {
      const store = useUiStore()

      store.toggleCommandPalette()
      expect(store.commandPaletteOpen).toBe(true)

      store.toggleCommandPalette()
      expect(store.commandPaletteOpen).toBe(false)
    })

    it('should open and close shortcuts', () => {
      const store = useUiStore()

      store.openShortcuts()
      expect(store.shortcutsOpen).toBe(true)

      store.closeShortcuts()
      expect(store.shortcutsOpen).toBe(false)
    })

    it('should open and close settings', () => {
      const store = useUiStore()

      store.openSettings()
      expect(store.settingsOpen).toBe(true)

      store.closeSettings()
      expect(store.settingsOpen).toBe(false)
    })

    it('should clear the corpus manager scope when settings close', () => {
      const store = useUiStore()

      store.openCorpusManager()
      expect(store.settingsOpen).toBe(true)
      expect(store.corpusManagerOpen).toBe(true)

      store.closeSettings()
      expect(store.settingsOpen).toBe(false)
      expect(store.corpusManagerOpen).toBe(false)
    })

    it('should open and close export', () => {
      const store = useUiStore()

      store.openExport()
      expect(store.exportOpen).toBe(true)

      store.closeExport()
      expect(store.exportOpen).toBe(false)
    })

    it('should open and close bookmarks', () => {
      const store = useUiStore()

      store.openBookmarks()
      expect(store.bookmarksOpen).toBe(true)

      store.closeBookmarks()
      expect(store.bookmarksOpen).toBe(false)
    })

    it('should open and close query builder', () => {
      const store = useUiStore()

      store.openQueryBuilder()
      expect(store.queryBuilderOpen).toBe(true)

      store.closeQueryBuilder()
      expect(store.queryBuilderOpen).toBe(false)
    })
  })

  describe('shortcuts enabled', () => {
    it('should control shortcuts enabled state', () => {
      const store = useUiStore()

      expect(store.shortcutsEnabled).toBe(true)

      store.setShortcutsEnabled(false)
      expect(store.shortcutsEnabled).toBe(false)

      store.setShortcutsEnabled(true)
      expect(store.shortcutsEnabled).toBe(true)
    })
  })
})
