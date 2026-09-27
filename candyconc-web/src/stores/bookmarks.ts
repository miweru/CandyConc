/**
 * Bookmarks Store - Save and restore query states
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ActiveTab } from './ui'
import { getPrefs, updatePrefs } from '@/api/client'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { t } from '@/i18n'

// ============================================
// Types
// ============================================

export interface Bookmark {
  id: string
  name: string
  query: string
  selectedRows: number[]
  tab: ActiveTab
  timestamp: number
  notes?: string
}

export const BOOKMARK_OPERATIONS = {
  read: 'research.bookmarks.read',
  write: 'research.bookmarks.write',
} as const

// ============================================
// Store
// ============================================

export const useBookmarksStore = defineStore('bookmarks', () => {
  // ============================================
  // State
  // ============================================

  const bookmarks = ref<Bookmark[]>([])
  const isLoading = ref(false)
  const STORAGE_KEY = 'candyconc_bookmarks'
  const PREF_KEY = 'bookmarks_json'

  // ============================================
  // Computed
  // ============================================

  const hasBookmarks = computed(() => bookmarks.value.length > 0)

  const sortedBookmarks = computed(() =>
    [...bookmarks.value].sort((a, b) => b.timestamp - a.timestamp)
  )

  const recentBookmarks = computed(() => sortedBookmarks.value.slice(0, 5))

  // ============================================
  // Actions
  // ============================================

  async function assertBookmarkRead(): Promise<void> {
    await useProductCapabilitiesStore().assertProductOperationAccess(
      BOOKMARK_OPERATIONS.read,
      t('kwic.bookmarks.load'),
    )
  }

  async function assertBookmarkWrite(): Promise<void> {
    await useProductCapabilitiesStore().assertProductOperationAccess(
      BOOKMARK_OPERATIONS.write,
      t('kwic.bookmarks.saveOperation'),
    )
  }

  function parseBookmarks(raw: unknown): Bookmark[] {
    if (!raw) return []

    try {
      const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
      if (!Array.isArray(parsed)) return []

      return parsed
        .filter((item) => item && typeof item === 'object')
        .map((item) => item as Bookmark)
        .filter((item) => typeof item.id === 'string')
    } catch {
      return []
    }
  }

  async function load() {
    isLoading.value = true
    try {
      await assertBookmarkRead()
      const prefsState = await getPrefs()
      const prefs = prefsState.prefs ?? {}

      if (Object.prototype.hasOwnProperty.call(prefs, PREF_KEY)) {
        const fromPrefs = parseBookmarks(prefs[PREF_KEY])
        bookmarks.value = fromPrefs
        localStorage.setItem(STORAGE_KEY, JSON.stringify(bookmarks.value))
        return
      }

      const stored = localStorage.getItem(STORAGE_KEY)
      if (stored) {
        bookmarks.value = parseBookmarks(stored)
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'ProductCapabilityDeniedError') {
        console.error('Bookmarks are not available in the current Product-Capability context:', error.message)
        throw error
      }
      console.error('Failed to load bookmarks from backend, falling back to localStorage:', error)
      try {
        const stored = localStorage.getItem(STORAGE_KEY)
        if (stored) {
          bookmarks.value = parseBookmarks(stored)
        }
      } catch (localError) {
        console.error('Failed to load bookmarks from localStorage:', localError)
      }
    } finally {
      isLoading.value = false
    }
  }

  async function add(bookmark: Omit<Bookmark, 'id' | 'timestamp'>): Promise<Bookmark> {
    await assertBookmarkWrite()
    const newBookmark: Bookmark = {
      ...bookmark,
      id: crypto.randomUUID(),
      timestamp: Date.now()
    }

    bookmarks.value.push(newBookmark)
    await persist({ assumeAuthorized: true })

    return newBookmark
  }

  async function update(id: string, updates: Partial<Omit<Bookmark, 'id' | 'timestamp'>>): Promise<boolean> {
    await assertBookmarkWrite()
    const index = bookmarks.value.findIndex(b => b.id === id)
    if (index === -1) return false

    const existing = bookmarks.value[index]
    bookmarks.value[index] = {
      ...existing,
      ...updates
    } as Bookmark
    await persist({ assumeAuthorized: true })

    return true
  }

  async function remove(id: string): Promise<boolean> {
    await assertBookmarkWrite()
    const index = bookmarks.value.findIndex(b => b.id === id)
    if (index === -1) return false

    bookmarks.value.splice(index, 1)
    await persist({ assumeAuthorized: true })

    return true
  }

  function getById(id: string): Bookmark | undefined {
    return bookmarks.value.find(b => b.id === id)
  }

  async function clear() {
    await assertBookmarkWrite()
    bookmarks.value = []
    await persist({ assumeAuthorized: true })
  }

  async function persist(options: { assumeAuthorized?: boolean } = {}) {
    if (!options.assumeAuthorized) {
      await assertBookmarkWrite()
    }
    try {
      await updatePrefs({ [PREF_KEY]: bookmarks.value })
      localStorage.setItem(STORAGE_KEY, JSON.stringify(bookmarks.value))
    } catch (error) {
      console.error('Failed to persist bookmarks to backend:', error)
      try {
        localStorage.setItem(STORAGE_KEY, JSON.stringify(bookmarks.value))
      } catch (localError) {
        console.error('Failed to persist bookmarks locally:', localError)
      }
    }
  }

  // Initialize
  function init() {
    void load().catch(() => undefined)
  }

  return {
    // State
    bookmarks,
    isLoading,

    // Computed
    hasBookmarks,
    sortedBookmarks,
    recentBookmarks,

    // Actions
    load,
    add,
    update,
    remove,
    getById,
    clear,
    init,
  }
})
