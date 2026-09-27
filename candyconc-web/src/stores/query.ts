/**
 * Query Store - KWIC search state management
 */

import { defineStore } from 'pinia'
import { ref, computed, shallowRef } from 'vue'
import type { QueryFilters } from '@/actions/types'
import type { CoKwicCounts, KwicSampleProvenance } from '@/api/client'
import type { RowSpacing } from '@/utils/sourceSpacing'

export interface KwicRow extends RowSpacing {
  position: number
  left: string
  match: string
  right: string
  docId: string
  docTitle?: string
  metadata?: Record<string, string>
  collocateOffsets?: number[]
  matchOffsets?: number[]
}

export interface StreamingProgress {
  count: number
  elapsedMs: number
  isStreaming: boolean
}

/**
 * Sort direction for KWIC results.
 */
export type SortDir = 'asc' | 'desc'

/**
 * Valid sort fields for KWIC results, matching the backend `sort_by` contract.
 *
 * - `1L`/`2L`/`3L`: nth token left of the match (AntConc convention)
 * - `node`: the match itself
 * - `1R`/`2R`/`3R`: nth token right of the match
 * - `meta:FIELD`: a metadata field (e.g. `meta:source`)
 *
 * `null` means default order (unsorted / by position).
 */
export type SortField =
  | '1L'
  | '2L'
  | '3L'
  | 'node'
  | '1R'
  | '2R'
  | '3R'
  | `meta:${string}`

export interface QueryState {
  term: string
  filters: QueryFilters
  results: KwicRow[]
  totalHits: number
  totalKnown: boolean
  totalPartial: boolean
  isLoading: boolean
  error: string | null
  selectedRows: Set<number>
  highlightedRow: number | null
  contextSize: number
  scrollPosition: number
  pendingScrollPosition: number | null
  streamingProgress: StreamingProgress | null
  hasMore: boolean
  hasPrevious: boolean
  nextOffset: number
  resultOffsetStart: number
  lastExecutedAt: number | null
}

/**
 * The analysis row the current concordance was opened from. It holds data,
 * the concordance header turns it into text in the active language. Its term
 * is the query it belongs to: a new search clears it.
 */
export type BackPathOrigin =
  | {
      kind: 'wordSketch'
      term: string
      node: string
      relation: string
      relationLabel: string
      collocate: string
      /** Pairs of head and dependent the row counts. */
      pairs: number
      /** False when one side of the dependency search ignores case. */
      exact: boolean
      /** The sketch comparison opened it, not the single sketch. */
      fromComparison?: boolean
    }
  | {
      kind: 'trend'
      term: string
      query: string
      field: string
      period: string
      granularity: 'year' | 'month'
      hits: number
    }
  | {
      kind: 'contrast'
      term: string
      node: string
      collocate: string
      side: 'target' | 'reference'
      group: string
      /** Co-occurrence tokens (O11) of the row on this side. */
      cooccurrences: number
      perMillion: number
    }

const DEFAULT_CONTEXT_SIZE = 200
const MIN_CONTEXT_SIZE = 40
const MAX_CONTEXT_SIZE = 600

export const useQueryStore = defineStore('query', () => {
  // State
  const term = ref('')
  const filters = ref<QueryFilters>({})
  const results = shallowRef<KwicRow[]>([])
  const totalHits = ref(0)
  const totalKnown = ref(false)
  const totalPartial = ref(false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const selectedRows = ref<Set<number>>(new Set())
  const highlightedRow = ref<number | null>(null)
  const caseSensitive = ref(false)
  // Kontext wird automatisch nach Breite dargestellt; wir holen bewusst mehr Tokens,
  // damit die UI die volle Breite ohne Nachladen füllen kann.
  const contextSize = ref(DEFAULT_CONTEXT_SIZE)
  // KWIC sort state. `sortBy === null` is the default (unsorted / by position).
  const sortBy = ref<SortField | null>(null)
  const sortDir = ref<SortDir>('asc')
  const scrollPosition = ref(0)
  const pendingScrollPosition = ref<number | null>(null)
  const streamingProgress = ref<StreamingProgress | null>(null)
  const hasMore = ref(false)
  const hasPrevious = ref(false)
  const nextOffset = ref(0)
  const resultOffsetStart = ref(0)
  const lastExecutedAt = ref<number | null>(null)

  // ── KWIC-Zufallsstichprobe (Thinning, T1) ─────────────────────────────
  // sampleActive/-Size/-Seed sind die NUTZERKONFIGURATION; sampleProvenance
  // ist die SERVER-Wahrheit (X-CandyConc-Sample) des aktuell angezeigten
  // Resultats. setResults() löscht die Provenienz, damit ein normal geladenes
  // Vollresultat nie fälschlich als Stichprobe ausgewiesen wird — der sampled
  // Ladepfad setzt sie unmittelbar nach setResults() wieder.
  const sampleActive = ref(false)
  const sampleSize = ref(200)
  const sampleSeed = ref<number | null>(null)
  const sampleProvenance = ref<KwicSampleProvenance | null>(null)
  // Co-KWIC counting provenance (rows are node hits, O11 counts collocate
  // tokens). Cleared by every new result set, set again by the Co-KWIC paths.
  const coKwicCounts = ref<CoKwicCounts | null>(null)
  const backPathOrigin = ref<BackPathOrigin | null>(null)

  // Abort controller for cancelling streaming queries
  let abortController: AbortController | null = null

  // Computed
  const hasResults = computed(() => results.value.length > 0)
  // totalPartial covers two cases: the count itself is a lower bound, or the
  // count is exact and only part of the rows is loaded. Only the first case is
  // a lower bound (otherwise an exact 495 would read "≥ 495 (partiell)").
  const countIsLowerBound = computed(() => totalPartial.value && !totalKnown.value)
  const rowsIncomplete = computed(
    () => totalKnown.value && results.value.length < totalHits.value,
  )
  const selectedCount = computed(() => selectedRows.value.size)
  const selectedItems = computed(() => {
    if (!selectedRows.value.size) return []
    const items: KwicRow[] = []
    for (const index of selectedRows.value) {
      const row = results.value[index]
      if (row) items.push(row)
    }
    return items
  })

  // Actions
  function setTerm(newTerm: string) {
    term.value = newTerm
    if (backPathOrigin.value && backPathOrigin.value.term !== newTerm) backPathOrigin.value = null
  }

  function setFilters(newFilters: QueryFilters) {
    filters.value = { ...filters.value, ...newFilters }
  }

  function setResults(newResults: KwicRow[], total: number, known = true, partial = false) {
    results.value = newResults
    totalHits.value = total
    totalKnown.value = known
    totalPartial.value = partial
    error.value = null
    // Jede neue Ergebnismenge invalidiert die Stichproben-Provenienz; der
    // sampled Ladepfad setzt sie direkt danach aus dem Server-Header neu.
    sampleProvenance.value = null
    coKwicCounts.value = null
  }

  function setTotalHits(total: number, known = true, partial = false) {
    totalHits.value = total
    totalKnown.value = known
    totalPartial.value = partial
  }

  function appendResults(moreResults: KwicRow[]) {
    if (!moreResults.length) return
    results.value = [...results.value, ...moreResults]
  }

  function prependResults(moreResults: KwicRow[]) {
    if (!moreResults.length) return
    const shift = moreResults.length
    results.value = [...moreResults, ...results.value]
    if (selectedRows.value.size) {
      const next = new Set<number>()
      selectedRows.value.forEach((idx) => {
        next.add(idx + shift)
      })
      selectedRows.value = next
    }
    if (highlightedRow.value !== null) {
      highlightedRow.value = highlightedRow.value + shift
    }
  }

  function setLoading(loading: boolean) {
    isLoading.value = loading
  }

  function setError(err: string | null) {
    error.value = err
    isLoading.value = false
  }

  function selectRow(index: number, multiSelect = false) {
    if (!multiSelect) {
      selectedRows.value.clear()
    }
    selectedRows.value.add(index)
  }

  function deselectRow(index: number) {
    selectedRows.value.delete(index)
  }

  function toggleRow(index: number) {
    if (selectedRows.value.has(index)) {
      selectedRows.value.delete(index)
    } else {
      selectedRows.value.add(index)
    }
  }

  function selectAll() {
    selectedRows.value = new Set(results.value.map((_, i) => i))
  }

  function deselectAll() {
    selectedRows.value.clear()
  }

  function setHighlightedRow(index: number | null) {
    highlightedRow.value = index
  }

  function setCaseSensitive(value: boolean) {
    caseSensitive.value = Boolean(value)
  }

  function setSelectedRows(indices: number[]) {
    selectedRows.value = new Set(indices)
  }

  function setContextSize(size: number) {
    const next = Math.max(MIN_CONTEXT_SIZE, Math.min(MAX_CONTEXT_SIZE, Math.round(size)))
    contextSize.value = next
  }

  function setSort(field: SortField | null, dir: SortDir = 'asc') {
    sortBy.value = field
    sortDir.value = dir
  }

  /**
   * Toggle sorting for a field. Clicking the active field flips the direction;
   * clicking a new field sorts it ascending. Returns the resulting state so
   * callers can re-run the query.
   */
  function toggleSort(field: SortField): { sortBy: SortField | null; sortDir: SortDir } {
    if (sortBy.value === field) {
      sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
    } else {
      sortBy.value = field
      sortDir.value = 'asc'
    }
    return { sortBy: sortBy.value, sortDir: sortDir.value }
  }

  function resetSort() {
    sortBy.value = null
    sortDir.value = 'asc'
  }

  function setScrollPosition(position: number) {
    scrollPosition.value = Math.max(0, position)
  }

  function setPendingScrollPosition(position: number | null) {
    pendingScrollPosition.value = position === null ? null : Math.max(0, position)
  }

  function setStreamingProgress(progress: StreamingProgress | null) {
    streamingProgress.value = progress
  }

  function startStreaming(initialCount = 0): AbortSignal {
    // Cancel any existing streaming query
    if (abortController) {
      abortController.abort()
    }
    abortController = new AbortController()
    streamingProgress.value = { count: initialCount, elapsedMs: 0, isStreaming: true }
    return abortController.signal
  }

  function cancelStreaming() {
    if (abortController) {
      abortController.abort()
      abortController = null
    }
    if (streamingProgress.value) {
      streamingProgress.value = { ...streamingProgress.value, isStreaming: false }
    }
  }

  function finishStreaming() {
    abortController = null
    if (streamingProgress.value) {
      streamingProgress.value = { ...streamingProgress.value, isStreaming: false }
    }
  }

  function clear() {
    cancelStreaming()
    term.value = ''
    filters.value = {}
    results.value = []
    totalHits.value = 0
    totalKnown.value = false
    totalPartial.value = false
    error.value = null
    selectedRows.value.clear()
    highlightedRow.value = null
    scrollPosition.value = 0
    pendingScrollPosition.value = null
    streamingProgress.value = null
    hasMore.value = false
    hasPrevious.value = false
    nextOffset.value = 0
    resultOffsetStart.value = 0
    lastExecutedAt.value = null
    caseSensitive.value = false
    sortBy.value = null
    sortDir.value = 'asc'
    sampleActive.value = false
    sampleProvenance.value = null
    coKwicCounts.value = null
    backPathOrigin.value = null
  }

  // A rejected search must not leave the previous query's evidence on screen.
  // Keep the researcher’s active filters and display preferences intact so the
  // reason can be corrected and submitted again without rebuilding the search.
  function rejectAttempt(attemptedTerm: string, reason: string) {
    cancelStreaming()
    term.value = attemptedTerm
    results.value = []
    totalHits.value = 0
    totalKnown.value = false
    totalPartial.value = false
    selectedRows.value.clear()
    highlightedRow.value = null
    scrollPosition.value = 0
    pendingScrollPosition.value = null
    streamingProgress.value = null
    hasMore.value = false
    hasPrevious.value = false
    nextOffset.value = 0
    resultOffsetStart.value = 0
    lastExecutedAt.value = null
    error.value = reason
    isLoading.value = false
  }

  function setHasMore(value: boolean) {
    hasMore.value = value
  }

  function setHasPrevious(value: boolean) {
    hasPrevious.value = value
  }

  function setNextOffset(value: number) {
    nextOffset.value = Math.max(0, value)
  }

  function setResultOffsetStart(value: number) {
    resultOffsetStart.value = Math.max(0, value)
  }

  function setLastExecutedAt(value: number | null) {
    lastExecutedAt.value = value
  }

  /** Stichproben-Konfiguration setzen (Größe/Seed werden nur validiert übernommen). */
  function setSampleConfig(active: boolean, size?: number, seed?: number) {
    sampleActive.value = active
    if (typeof size === 'number' && Number.isFinite(size) && size >= 1) {
      sampleSize.value = Math.round(size)
    }
    if (typeof seed === 'number' && Number.isFinite(seed) && seed >= 0) {
      sampleSeed.value = Math.round(seed)
    }
  }

  /** Server-Provenienz des angezeigten Stichproben-Resultats übernehmen. */
  function setSampleProvenance(provenance: KwicSampleProvenance | null) {
    sampleProvenance.value = provenance
  }

  function setCoKwicCounts(counts: CoKwicCounts | null | undefined) {
    coKwicCounts.value = counts ?? null
  }

  function setBackPathOrigin(origin: BackPathOrigin | null) {
    backPathOrigin.value = origin
  }

  /** Stichprobe deaktivieren (Konfiguration bleibt für erneutes Aktivieren erhalten). */
  function clearSample() {
    sampleActive.value = false
    sampleProvenance.value = null
  }

  return {
    // State
    term,
    filters,
    results,
    totalHits,
    totalKnown,
    totalPartial,
    isLoading,
    error,
    selectedRows,
    highlightedRow,
    caseSensitive,
    contextSize,
    sortBy,
    sortDir,
    scrollPosition,
    pendingScrollPosition,
    streamingProgress,
    hasMore,
    hasPrevious,
    nextOffset,
    resultOffsetStart,
    lastExecutedAt,
    sampleActive,
    sampleSize,
    sampleSeed,
    sampleProvenance,
    coKwicCounts,
    backPathOrigin,
    // Computed
    hasResults,
    countIsLowerBound,
    rowsIncomplete,
    selectedCount,
    selectedItems,
    // Actions
    setTerm,
    setFilters,
    setResults,
    setTotalHits,
    appendResults,
    prependResults,
    setLoading,
    setError,
    selectRow,
    deselectRow,
    toggleRow,
    selectAll,
    deselectAll,
    setHighlightedRow,
    setCaseSensitive,
    setSelectedRows,
    setContextSize,
    setSort,
    toggleSort,
    resetSort,
    setScrollPosition,
    setPendingScrollPosition,
    setStreamingProgress,
    setHasMore,
    setHasPrevious,
    setNextOffset,
    setResultOffsetStart,
    setLastExecutedAt,
    setSampleConfig,
    setSampleProvenance,
    setCoKwicCounts,
    setBackPathOrigin,
    clearSample,
    startStreaming,
    cancelStreaming,
    finishStreaming,
    clear,
    rejectAttempt,
  }
})
