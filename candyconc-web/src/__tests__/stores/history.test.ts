/**
 * History Store Tests
 */
import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useHistoryStore, type HistoryState } from '@/stores/history'

describe('useHistoryStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  function createMockState(query: string): HistoryState {
    return {
      query,
      selectedRows: [],
      tab: 'kwic',
      scrollPosition: 0,
      filters: {},
      timestamp: Date.now()
    }
  }

  describe('initial state', () => {
    it('should have empty past and future', () => {
      const store = useHistoryStore()
      expect(store.past).toEqual([])
      expect(store.future).toEqual([])
    })

    it('should not be able to undo or redo initially', () => {
      const store = useHistoryStore()
      expect(store.canUndo).toBe(false)
      expect(store.canRedo).toBe(false)
    })
  })

  describe('setStateHandlers', () => {
    it('should set state handlers', () => {
      const store = useHistoryStore()
      const getState = vi.fn(() => createMockState('test'))
      const restore = vi.fn()

      store.setStateHandlers(getState, restore)
      store.pushState()

      expect(getState).toHaveBeenCalled()
    })
  })

  describe('pushState', () => {
    it('should push state to history', () => {
      const store = useHistoryStore()
      let currentState = createMockState('first')

      store.setStateHandlers(
        () => currentState,
        () => {}
      )

      store.pushState()
      expect(store.past).toHaveLength(1)
      expect(store.past[0]?.query).toBe('first')
    })

    it('should not push duplicate states', () => {
      const store = useHistoryStore()
      const state = createMockState('same')

      store.setStateHandlers(
        () => state,
        () => {}
      )

      store.pushState()
      store.pushState()
      store.pushState()

      expect(store.past).toHaveLength(1)
    })

    it('should clear future on new push', () => {
      const store = useHistoryStore()
      let currentQuery = 'first'

      store.setStateHandlers(
        () => createMockState(currentQuery),
        (state) => { currentQuery = state.query }
      )

      store.pushState()
      currentQuery = 'second'
      store.pushState()
      store.undo()

      expect(store.future).toHaveLength(1)

      currentQuery = 'third'
      store.pushState()

      expect(store.future).toHaveLength(0)
    })

    it('should trim history when exceeding maxHistory', () => {
      const store = useHistoryStore()
      store.maxHistory = 5
      let counter = 0

      store.setStateHandlers(
        () => createMockState(`query-${counter++}`),
        () => {}
      )

      for (let i = 0; i < 10; i++) {
        store.pushState()
      }

      expect(store.past.length).toBeLessThanOrEqual(5)
    })
  })

  describe('undo', () => {
    it('should restore the last pushed state', () => {
      const store = useHistoryStore()
      let currentQuery = 'initial'
      const restoreMock = vi.fn((state: HistoryState) => {
        currentQuery = state.query
      })

      store.setStateHandlers(
        () => createMockState(currentQuery),
        restoreMock
      )

      // Save checkpoint at "initial"
      store.pushState() // past = ["initial"]

      // Change to "modified" (not saved)
      currentQuery = 'modified'

      // Undo should restore "initial"
      const result = store.undo()

      expect(result).toBe(true)
      expect(restoreMock).toHaveBeenCalledWith(
        expect.objectContaining({ query: 'initial' })
      )
    })

    it('should allow multiple undos', () => {
      const store = useHistoryStore()
      let currentQuery = 'first'
      const restoreMock = vi.fn((state: HistoryState) => {
        currentQuery = state.query
      })

      store.setStateHandlers(
        () => createMockState(currentQuery),
        restoreMock
      )

      // Push checkpoints
      store.pushState() // past = ["first"]
      currentQuery = 'second'
      store.pushState() // past = ["first", "second"]
      currentQuery = 'third'

      // First undo restores "second"
      store.undo()
      expect(restoreMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: 'second' })
      )

      // Second undo restores "first"
      store.undo()
      expect(restoreMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: 'first' })
      )
    })

    it('should move current state to future', () => {
      const store = useHistoryStore()
      let currentQuery = 'first'

      store.setStateHandlers(
        () => createMockState(currentQuery),
        (state) => { currentQuery = state.query }
      )

      store.pushState()
      currentQuery = 'second'
      store.pushState()
      store.undo()

      expect(store.future).toHaveLength(1)
      expect(store.future[0]?.query).toBe('second')
    })

    it('should return false when nothing to undo', () => {
      const store = useHistoryStore()
      store.setStateHandlers(
        () => createMockState('test'),
        () => {}
      )

      const result = store.undo()
      expect(result).toBe(false)
    })
  })

  describe('redo', () => {
    it('should restore future state', () => {
      const store = useHistoryStore()
      let currentQuery = 'first'
      const restoreMock = vi.fn((state: HistoryState) => {
        currentQuery = state.query
      })

      store.setStateHandlers(
        () => createMockState(currentQuery),
        restoreMock
      )

      store.pushState()
      currentQuery = 'second'
      store.pushState()
      store.undo()
      store.redo()

      expect(restoreMock).toHaveBeenLastCalledWith(
        expect.objectContaining({ query: 'second' })
      )
    })

    it('should return false when nothing to redo', () => {
      const store = useHistoryStore()
      store.setStateHandlers(
        () => createMockState('test'),
        () => {}
      )

      const result = store.redo()
      expect(result).toBe(false)
    })
  })

  describe('clear', () => {
    it('should clear all history', () => {
      const store = useHistoryStore()
      let currentQuery = 'first'

      store.setStateHandlers(
        () => createMockState(currentQuery),
        (state) => { currentQuery = state.query }
      )

      store.pushState()
      currentQuery = 'second'
      store.pushState()
      store.undo()

      store.clear()

      expect(store.past).toHaveLength(0)
      expect(store.future).toHaveLength(0)
      expect(store.canUndo).toBe(false)
      expect(store.canRedo).toBe(false)
    })
  })

  describe('computed', () => {
    it('should correctly compute undoCount and redoCount', () => {
      const store = useHistoryStore()
      let currentQuery = 'first'

      store.setStateHandlers(
        () => createMockState(currentQuery),
        (state) => { currentQuery = state.query }
      )

      store.pushState()
      currentQuery = 'second'
      store.pushState()
      currentQuery = 'third'
      store.pushState()

      expect(store.undoCount).toBe(3)
      expect(store.redoCount).toBe(0)

      store.undo()
      store.undo()

      expect(store.undoCount).toBe(1)
      expect(store.redoCount).toBe(2)
    })
  })

  describe('isRestoring', () => {
    it('should track restoring state', () => {
      const store = useHistoryStore()

      expect(store.isRestoring).toBe(false)

      store.setRestoring(true)
      expect(store.isRestoring).toBe(true)

      store.setRestoring(false)
      expect(store.isRestoring).toBe(false)
    })
  })
})
