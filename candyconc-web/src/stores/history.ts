/**
 * History Store - Undo/Redo state management
 */

import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import type { ActiveTab } from './ui'
import type { QueryFilters } from '@/actions/types'

// ============================================
// Types
// ============================================

export interface HistoryState {
  query: string
  selectedRows: number[]
  tab: ActiveTab
  scrollPosition: number
  filters: QueryFilters
  timestamp: number
}

// ============================================
// Store
// ============================================

export const useHistoryStore = defineStore('history', () => {
  // ============================================
  // State
  // ============================================

  const past = ref<HistoryState[]>([])
  const future = ref<HistoryState[]>([])
  const maxHistory = ref(50)
  const isRestoring = ref(false)

  // Current state snapshot function (will be set by the app)
  let getCurrentState: (() => HistoryState) | null = null
  let restoreState: ((state: HistoryState) => void) | null = null

  // ============================================
  // Computed
  // ============================================

  const canUndo = computed(() => past.value.length > 0)
  const canRedo = computed(() => future.value.length > 0)
  const undoCount = computed(() => past.value.length)
  const redoCount = computed(() => future.value.length)

  // ============================================
  // Actions
  // ============================================

  function setStateHandlers(
    getState: () => HistoryState,
    restore: (state: HistoryState) => void
  ) {
    getCurrentState = getState
    restoreState = restore
  }

  function pushState() {
    if (!getCurrentState) return

    const state = getCurrentState()

    // Don't push if it's the same as the last state
    const lastState = past.value[past.value.length - 1]
    if (lastState && JSON.stringify(lastState) === JSON.stringify(state)) {
      return
    }

    past.value.push(state)

    // Clear future on new action
    future.value = []

    // Trim history if too long
    if (past.value.length > maxHistory.value) {
      past.value = past.value.slice(-maxHistory.value)
    }
  }

  function undo(): boolean {
    if (!canUndo.value || !getCurrentState || !restoreState) return false

    // Save current state to future
    const currentState = getCurrentState()
    future.value.push(currentState)

    // Pop and restore previous state
    const previousState = past.value.pop()
    if (previousState) {
      restoreState(previousState)
      return true
    }

    return false
  }

  function redo(): boolean {
    if (!canRedo.value || !getCurrentState || !restoreState) return false

    // Save current state to past
    const currentState = getCurrentState()
    past.value.push(currentState)

    // Pop and restore future state
    const nextState = future.value.pop()
    if (nextState) {
      restoreState(nextState)
      return true
    }

    return false
  }

  function clear() {
    past.value = []
    future.value = []
  }

  function setRestoring(restoring: boolean) {
    isRestoring.value = restoring
  }

  return {
    // State
    past,
    future,
    maxHistory,
    isRestoring,

    // Computed
    canUndo,
    canRedo,
    undoCount,
    redoCount,

    // Actions
    setStateHandlers,
    pushState,
    undo,
    redo,
    clear,
    setRestoring,
  }
})
