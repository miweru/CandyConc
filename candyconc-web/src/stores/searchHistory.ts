/**
 * Search History Store - Track recent searches
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// ============================================
// Types
// ============================================

export interface SearchHistoryItem {
  id: string
  query: string
  timestamp: number
  resultCount: number
}

// ============================================
// Store
// ============================================

export const useSearchHistoryStore = defineStore('searchHistory', () => {
  // ============================================
  // State
  // ============================================

  const history = ref<SearchHistoryItem[]>([])
  const maxItems = ref(20)

  // ============================================
  // Computed
  // ============================================

  const hasHistory = computed(() => history.value.length > 0)

  const recentSearches = computed(() => history.value.slice(0, 10))

  // ============================================
  // Actions
  // ============================================

  function load() {
    try {
      const stored = localStorage.getItem('candyconc_search_history')
      if (stored) {
        history.value = JSON.parse(stored)
      }
    } catch (error) {
      console.error('Failed to load search history:', error)
    }
  }

  function add(query: string, resultCount: number) {
    // Don't add empty queries
    if (!query.trim()) return

    // Remove duplicate if exists
    const existingIndex = history.value.findIndex(
      h => h.query.toLowerCase() === query.toLowerCase()
    )
    if (existingIndex !== -1) {
      history.value.splice(existingIndex, 1)
    }

    // Add new item at the beginning
    const item: SearchHistoryItem = {
      id: crypto.randomUUID(),
      query: query.trim(),
      timestamp: Date.now(),
      resultCount
    }
    history.value.unshift(item)

    // Trim to max items
    if (history.value.length > maxItems.value) {
      history.value = history.value.slice(0, maxItems.value)
    }

    persist()
  }

  function remove(id: string) {
    const index = history.value.findIndex(h => h.id === id)
    if (index !== -1) {
      history.value.splice(index, 1)
      persist()
    }
  }

  function clear() {
    history.value = []
    persist()
  }

  function persist() {
    try {
      localStorage.setItem('candyconc_search_history', JSON.stringify(history.value))
    } catch (error) {
      console.error('Failed to persist search history:', error)
    }
  }

  // Initialize
  function init() {
    load()
  }

  return {
    // State
    history,
    maxItems,

    // Computed
    hasHistory,
    recentSearches,

    // Actions
    load,
    add,
    remove,
    clear,
    init,
  }
})
