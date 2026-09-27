/**
 * Query Store Tests
 */
import { describe, it, expect, beforeEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useQueryStore, type KwicRow } from '@/stores/query'

describe('QueryStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const createMockRows = (count: number): KwicRow[] => {
    return Array.from({ length: count }, (_, i) => ({
      position: i * 100,
      left: `left context ${i}`,
      match: `match ${i}`,
      right: `right context ${i}`,
      docId: `doc-${i}`
    }))
  }

  describe('initial state', () => {
    it('should have empty initial state', () => {
      const store = useQueryStore()

      expect(store.term).toBe('')
      expect(store.results).toHaveLength(0)
      expect(store.totalHits).toBe(0)
      expect(store.totalKnown).toBe(false)
      expect(store.isLoading).toBe(false)
      expect(store.error).toBeNull()
      expect(store.selectedRows.size).toBe(0)
      expect(store.highlightedRow).toBeNull()
      expect(store.contextSize).toBe(200)
    })

    it('should have correct computed values initially', () => {
      const store = useQueryStore()

      expect(store.hasResults).toBe(false)
      expect(store.selectedCount).toBe(0)
      expect(store.selectedItems).toHaveLength(0)
    })
  })

  describe('setTerm', () => {
    it('should set the search term', () => {
      const store = useQueryStore()

      store.setTerm('Klimawandel')

      expect(store.term).toBe('Klimawandel')
    })

    it('should handle empty term', () => {
      const store = useQueryStore()
      store.setTerm('test')

      store.setTerm('')

      expect(store.term).toBe('')
    })
  })

  describe('setFilters', () => {
    it('should set filters', () => {
      const store = useQueryStore()

      store.setFilters({ corpus: 'news', metadata: { register: 'formal' } })

      expect(store.filters.corpus).toBe('news')
      expect(store.filters.metadata?.register).toBe('formal')
    })

    it('should merge filters', () => {
      const store = useQueryStore()
      store.setFilters({ corpus: 'news' })

      store.setFilters({ dateRange: { from: '2020-01-01', to: '2024-01-01' } })

      expect(store.filters.corpus).toBe('news')
      expect(store.filters.dateRange?.from).toBe('2020-01-01')
    })
  })

  describe('setResults', () => {
    it('should set results and total hits', () => {
      const store = useQueryStore()
      const rows = createMockRows(5)

      store.setResults(rows, 100)

      expect(store.results).toHaveLength(5)
      expect(store.totalHits).toBe(100)
      expect(store.totalKnown).toBe(true)
      expect(store.hasResults).toBe(true)
    })

    it('should clear error when setting results', () => {
      const store = useQueryStore()
      store.setError('Some error')

      store.setResults(createMockRows(1), 1)

      expect(store.error).toBeNull()
    })
  })

  describe('appendResults', () => {
    it('should append to existing results', () => {
      const store = useQueryStore()
      store.setResults(createMockRows(3), 10)

      store.appendResults(createMockRows(2))

      expect(store.results).toHaveLength(5)
    })
  })

  describe('loading state', () => {
    it('should set loading state', () => {
      const store = useQueryStore()

      store.setLoading(true)
      expect(store.isLoading).toBe(true)

      store.setLoading(false)
      expect(store.isLoading).toBe(false)
    })
  })

  describe('error handling', () => {
    it('should set error and clear loading', () => {
      const store = useQueryStore()
      store.setLoading(true)

      store.setError('Network error')

      expect(store.error).toBe('Network error')
      expect(store.isLoading).toBe(false)
    })

    it('should clear error', () => {
      const store = useQueryStore()
      store.setError('Some error')

      store.setError(null)

      expect(store.error).toBeNull()
    })
  })

  describe('row selection', () => {
    beforeEach(() => {
      const store = useQueryStore()
      store.setResults(createMockRows(5), 5)
    })

    it('should select a single row', () => {
      const store = useQueryStore()

      store.selectRow(2)

      expect(store.selectedRows.has(2)).toBe(true)
      expect(store.selectedCount).toBe(1)
    })

    it('should replace selection in single select mode', () => {
      const store = useQueryStore()
      store.selectRow(1)

      store.selectRow(3)

      expect(store.selectedRows.has(1)).toBe(false)
      expect(store.selectedRows.has(3)).toBe(true)
      expect(store.selectedCount).toBe(1)
    })

    it('should add to selection in multi-select mode', () => {
      const store = useQueryStore()
      store.selectRow(1)

      store.selectRow(3, true)

      expect(store.selectedRows.has(1)).toBe(true)
      expect(store.selectedRows.has(3)).toBe(true)
      expect(store.selectedCount).toBe(2)
    })

    it('should deselect a row', () => {
      const store = useQueryStore()
      store.selectRow(2)

      store.deselectRow(2)

      expect(store.selectedRows.has(2)).toBe(false)
      expect(store.selectedCount).toBe(0)
    })

    it('should toggle row selection', () => {
      const store = useQueryStore()

      store.toggleRow(2)
      expect(store.selectedRows.has(2)).toBe(true)

      store.toggleRow(2)
      expect(store.selectedRows.has(2)).toBe(false)
    })

    it('should select all rows', () => {
      const store = useQueryStore()

      store.selectAll()

      expect(store.selectedCount).toBe(5)
    })

    it('should deselect all rows', () => {
      const store = useQueryStore()
      store.selectAll()

      store.deselectAll()

      expect(store.selectedCount).toBe(0)
    })

    it('should return selected items', () => {
      const store = useQueryStore()
      store.selectRow(1)
      store.selectRow(3, true)

      const items = store.selectedItems

      expect(items).toHaveLength(2)
      expect(items[0]?.match).toBe('match 1')
      expect(items[1]?.match).toBe('match 3')
    })
  })

  describe('highlighted row', () => {
    it('should set highlighted row', () => {
      const store = useQueryStore()

      store.setHighlightedRow(5)

      expect(store.highlightedRow).toBe(5)
    })

    it('should clear highlighted row', () => {
      const store = useQueryStore()
      store.setHighlightedRow(5)

      store.setHighlightedRow(null)

      expect(store.highlightedRow).toBeNull()
    })
  })

  describe('context size', () => {
    it('should set context size', () => {
      const store = useQueryStore()

      store.setContextSize(120)

      expect(store.contextSize).toBe(120)
    })

    it('should clamp and round context size', () => {
      const store = useQueryStore()

      store.setContextSize(10)
      expect(store.contextSize).toBe(40)

      store.setContextSize(600.6)
      expect(store.contextSize).toBe(600)

      store.setContextSize(120.4)
      expect(store.contextSize).toBe(120)
    })
  })

  describe('clear', () => {
    it('should reset all state', () => {
      const store = useQueryStore()
      store.setTerm('test')
      store.setFilters({ corpus: 'news' })
      store.setResults(createMockRows(5), 100)
      store.selectRow(1)
      store.setHighlightedRow(2)

      store.clear()

      expect(store.term).toBe('')
      expect(store.filters).toEqual({})
      expect(store.results).toHaveLength(0)
      expect(store.totalHits).toBe(0)
      expect(store.totalKnown).toBe(false)
      expect(store.error).toBeNull()
      expect(store.selectedCount).toBe(0)
      expect(store.highlightedRow).toBeNull()
    })
  })
})
