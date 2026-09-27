/**
 * UI Store - Application-wide UI state
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ProductSurfaceOpenTarget } from '@/lib/productSurfaceRegistry'

export type ActiveTab =
  | 'kwic' | 'frequency' | 'collocations' | 'collocation_network' | 'dispersion' | 'semantic'
  | 'ngrams' | 'contrast' | 'keyness' | 'wordsketch' | 'trend' | 'reader'

/**
 * HANDOFF(S3-Trend): Die `nav/switchTab`-Payload-Union in
 * `src/actions/types.ts` (für S3-Agenten TABU, parallele Copilot-Arbeit)
 * kennt 'trend' noch nicht; zur Laufzeit akzeptiert der registrierte Handler
 * (`switchAnalysisTab(tab: ActiveTab)`) bereits jede ActiveTab. Dieser
 * Adapter bündelt den nötigen Downcast an EINER Stelle. Sobald die Union in
 * actions/types.ts um 'trend' erweitert ist, Helfer und Aufrufstellen auf
 * direkte Übergabe zurückbauen.
 */
export function asSwitchTabId(tab: ActiveTab): Exclude<ActiveTab, 'trend' | 'reader'> {
  return tab as Exclude<ActiveTab, 'trend' | 'reader'>
}
export type Theme = 'light' | 'dark' | 'system' | 'pink'

const THEME_STORAGE_KEY = 'candyconc_theme'

/** Read the persisted theme so dark mode survives a reload (DESIGN-A11Y-03). */
function readPersistedTheme(): Theme {
  try {
    const raw = localStorage.getItem(THEME_STORAGE_KEY)
    if (raw === 'light' || raw === 'dark' || raw === 'system' || raw === 'pink') return raw
  } catch {
    // localStorage unavailable (SSR / privacy mode) — fall back to system.
  }
  return 'system'
}
export type SettingsTab = 'general' | 'appearance' | 'corpora' | 'embeddings' | 'modelroute' | 'system'
export type ToastType = 'info' | 'success' | 'warning' | 'error'

export interface DocumentDetailRequest {
  docId: string
  corpus?: string
  fallbackLabel?: string
  fallbackMeta?: Record<string, string>
  highlight?: string
  highlightPosition?: number
  highlightLeft?: string
  highlightRight?: string
}

export interface Toast {
  id: string
  message: string
  type: ToastType
  duration: number
  timestamp: number
}

export interface ProductOperationFocus {
  operationId: string
  capabilityId: string
  surfaceSlot: string
  openTarget: ProductSurfaceOpenTarget | null
  preferredMode: string | null
  responseShape: string
  inputSchemaRef: string
  timestamp: number
}

export const useUiStore = defineStore('ui', () => {
  // State
  const activeTab = ref<ActiveTab>('kwic')
  const theme = ref<Theme>(readPersistedTheme())
  const sidebarOpen = ref(true)
  const loadingStates = ref<Map<string, boolean>>(new Map())
  const toasts = ref<Toast[]>([])
  const commandPaletteOpen = ref(false)
  const shortcutsOpen = ref(false)
  const authOpen = ref(false)
  const settingsOpen = ref(false)
  const settingsTab = ref<SettingsTab>('general')
  const exportOpen = ref(false)
  const bookmarksOpen = ref(false)
  const annotationReviewOpen = ref(false)
  const queryBuilderOpen = ref(false)
  const subcorpusOpen = ref(false)
  const corpusManagerOpen = ref(false)
  const workspaceOpen = ref(false)
  const workspaceTab = ref<'subcorpora' | 'analyses'>('subcorpora')
  const documentDetailOpen = ref(false)
  const documentDetail = ref<DocumentDetailRequest | null>(null)
  const focusedProductOperation = ref<ProductOperationFocus | null>(null)
  const focusedProductCapabilityId = ref<string | null>(null)
  
  // Keyboard shortcuts enabled
  const shortcutsEnabled = ref(true)

  // Computed
  const isLoading = computed(() => {
    for (const loading of loadingStates.value.values()) {
      if (loading) return true
    }
    return false
  })

  const isDarkMode = computed(() => {
    if (theme.value === 'system') {
      return window.matchMedia('(prefers-color-scheme: dark)').matches
    }
    return theme.value === 'dark'
  })

  // Actions
  function setActiveTab(tab: ActiveTab) {
    activeTab.value = tab
  }

  function setTheme(newTheme: Theme) {
    theme.value = newTheme
    try {
      localStorage.setItem(THEME_STORAGE_KEY, newTheme)
    } catch {
      // Non-fatal: theme still applies this session even if it can't persist.
    }
    applyTheme()
  }

  function toggleTheme() {
    const current = isDarkMode.value
    setTheme(current ? 'light' : 'dark')
  }

  function applyTheme() {
    const html = document.documentElement
    html.classList.toggle('pink', theme.value === 'pink')
    if (isDarkMode.value) {
      html.classList.add('dark')
    } else {
      html.classList.remove('dark')
    }
  }

  function toggleSidebar() {
    sidebarOpen.value = !sidebarOpen.value
  }

  function setLoading(key: string, loading: boolean) {
    if (loading) {
      loadingStates.value.set(key, true)
    } else {
      loadingStates.value.delete(key)
    }
  }

  function isLoadingKey(key: string): boolean {
    return loadingStates.value.get(key) ?? false
  }

  // Window (ms) during which an identical toast is treated as a duplicate and
  // refreshed in place instead of stacking a second copy.
  const TOAST_DEDUPE_WINDOW = 4000
  // Default auto-expiry for non-error toasts that were created with duration 0.
  const NON_ERROR_AUTO_EXPIRE = 5000
  const toastTimers = new Map<string, ReturnType<typeof setTimeout>>()

  function scheduleToastExpiry(toast: Toast) {
    const existing = toastTimers.get(toast.id)
    if (existing) {
      clearTimeout(existing)
      toastTimers.delete(toast.id)
    }
    // Errors may persist (duration 0) so the user can read them; every other
    // type always auto-expires even if a caller passed 0.
    const ttl = toast.duration > 0
      ? toast.duration
      : (toast.type === 'error' ? 0 : NON_ERROR_AUTO_EXPIRE)
    if (ttl > 0) {
      const timer = setTimeout(() => removeToast(toast.id), ttl)
      toastTimers.set(toast.id, timer)
    }
  }

  function showToast(
    message: string,
    type: Toast['type'] = 'info',
    duration = 5000
  ): string {
    // Dedupe: a single failure can raise the same toast from multiple handlers
    // (per-tab + global). Refresh the existing toast rather than stacking it.
    const now = Date.now()
    const duplicate = toasts.value.find(
      t => t.message === message && t.type === type && now - t.timestamp < TOAST_DEDUPE_WINDOW
    )
    if (duplicate) {
      duplicate.timestamp = now
      duplicate.duration = duration
      scheduleToastExpiry(duplicate)
      return duplicate.id
    }

    const toast: Toast = {
      id: crypto.randomUUID(),
      message,
      type,
      duration,
      timestamp: now
    }
    toasts.value.push(toast)
    scheduleToastExpiry(toast)

    return toast.id
  }

  function removeToast(id: string) {
    const timer = toastTimers.get(id)
    if (timer) {
      clearTimeout(timer)
      toastTimers.delete(id)
    }
    const idx = toasts.value.findIndex(t => t.id === id)
    if (idx !== -1) {
      toasts.value.splice(idx, 1)
    }
  }

  function clearToasts() {
    for (const timer of toastTimers.values()) {
      clearTimeout(timer)
    }
    toastTimers.clear()
    toasts.value = []
  }

  function setShortcutsEnabled(enabled: boolean) {
    shortcutsEnabled.value = enabled
  }

  function openCommandPalette() {
    commandPaletteOpen.value = true
  }

  function closeCommandPalette() {
    commandPaletteOpen.value = false
  }

  function toggleCommandPalette() {
    commandPaletteOpen.value = !commandPaletteOpen.value
  }

  function openShortcuts() {
    shortcutsOpen.value = true
  }

  function closeShortcuts() {
    shortcutsOpen.value = false
  }

  function toggleShortcuts() {
    shortcutsOpen.value = !shortcutsOpen.value
  }

  function openAuth() {
    authOpen.value = true
  }

  function closeAuth() {
    authOpen.value = false
  }

  function openSettings(tab?: SettingsTab) {
    if (tab) settingsTab.value = tab
    settingsOpen.value = true
  }

  function setSettingsTab(tab: SettingsTab) {
    settingsTab.value = tab
  }

  function closeSettings() {
    settingsOpen.value = false
    corpusManagerOpen.value = false
  }

  function openExport() {
    exportOpen.value = true
  }

  function closeExport() {
    exportOpen.value = false
  }

  function openBookmarks() {
    bookmarksOpen.value = true
  }

  function closeBookmarks() {
    bookmarksOpen.value = false
  }

  function openAnnotationReview() {
    annotationReviewOpen.value = true
  }

  function closeAnnotationReview() {
    annotationReviewOpen.value = false
  }

  function openQueryBuilder() {
    queryBuilderOpen.value = true
  }

  function closeQueryBuilder() {
    queryBuilderOpen.value = false
  }

  function openSubcorpus() {
    subcorpusOpen.value = true
  }

  function closeSubcorpus() {
    subcorpusOpen.value = false
  }

  function openCorpusManager() {
    corpusManagerOpen.value = true
    settingsOpen.value = true
  }

  function closeCorpusManager() {
    corpusManagerOpen.value = false
  }

  function openWorkspace(tab?: 'subcorpora' | 'analyses') {
    if (tab) workspaceTab.value = tab
    workspaceOpen.value = true
  }

  function closeWorkspace() {
    workspaceOpen.value = false
  }

  function setWorkspaceTab(tab: 'subcorpora' | 'analyses') {
    workspaceTab.value = tab
  }

  function openDocumentDetail(request: DocumentDetailRequest) {
    documentDetail.value = request
    documentDetailOpen.value = true
  }

  function closeDocumentDetail() {
    documentDetailOpen.value = false
  }

  function focusProductOperation(
    operationId: string,
    metadata: Partial<Omit<ProductOperationFocus, 'operationId' | 'timestamp'>> = {},
  ) {
    focusedProductOperation.value = {
      operationId,
      capabilityId: metadata.capabilityId ?? '',
      surfaceSlot: metadata.surfaceSlot ?? '',
      openTarget: metadata.openTarget ?? null,
      preferredMode: metadata.preferredMode ?? null,
      responseShape: metadata.responseShape ?? 'unknown',
      inputSchemaRef: metadata.inputSchemaRef ?? '',
      ...metadata,
      timestamp: Date.now(),
    }
    focusedProductCapabilityId.value = metadata.capabilityId ?? null
  }

  function clearProductOperationFocus() {
    focusedProductOperation.value = null
    focusedProductCapabilityId.value = null
  }

  function focusProductCapability(capabilityId: string) {
    focusedProductCapabilityId.value = capabilityId
  }

  function clearProductCapabilityFocus() {
    focusedProductCapabilityId.value = null
  }

  // Initialize theme on load
  function init() {
    applyTheme()
    
    // Watch for system theme changes
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (theme.value === 'system') {
        applyTheme()
      }
    })
  }

  return {
    // State
    activeTab,
    theme,
    sidebarOpen,
    loadingStates,
    toasts,
    shortcutsEnabled,
    commandPaletteOpen,
    shortcutsOpen,
    authOpen,
    settingsOpen,
    settingsTab,
    exportOpen,
    bookmarksOpen,
    annotationReviewOpen,
    queryBuilderOpen,
    subcorpusOpen,
    corpusManagerOpen,
    workspaceOpen,
    workspaceTab,
    documentDetailOpen,
    documentDetail,
    focusedProductOperation,
    focusedProductCapabilityId,
    // Computed
    isLoading,
    isDarkMode,
    // Actions
    setActiveTab,
    setTheme,
    toggleTheme,
    toggleSidebar,
    setLoading,
    isLoadingKey,
    showToast,
    removeToast,
    clearToasts,
    setShortcutsEnabled,
    openCommandPalette,
    closeCommandPalette,
    toggleCommandPalette,
    openShortcuts,
    closeShortcuts,
    toggleShortcuts,
    openAuth,
    closeAuth,
    openSettings,
    setSettingsTab,
    closeSettings,
    openExport,
    closeExport,
    openBookmarks,
    closeBookmarks,
    openAnnotationReview,
    closeAnnotationReview,
    openQueryBuilder,
    closeQueryBuilder,
    openSubcorpus,
    closeSubcorpus,
    openCorpusManager,
    closeCorpusManager,
    openWorkspace,
    closeWorkspace,
    setWorkspaceTab,
    openDocumentDetail,
    closeDocumentDetail,
    focusProductOperation,
    clearProductOperationFocus,
    focusProductCapability,
    clearProductCapabilityFocus,
    init
  }
})
