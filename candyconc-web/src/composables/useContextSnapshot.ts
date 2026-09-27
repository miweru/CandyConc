/**
 * UIContextSnapshot Builder
 *
 * Generates a serialized snapshot of the current UI state for the Copilot.
 * The snapshot is the primary perception mechanism for the assistant.
 *
 * Design principles:
 * - Deterministic: same state → same snapshot
 * - Minimal: only what the assistant needs to understand context
 * - Versioned: explicit version for forward compatibility
 */

import { computed, ref } from 'vue'
import {
  useQueryStore,
  useUiStore,
  useCopilotStore,
  useDocsetStore,
  useAnalysisPresetsStore,
  useSettingsStore,
  useCorpusCapabilitiesStore,
} from '@/stores'
import { isAppLocale } from '@/i18n/locale'
import { pairSideValues } from '@/lib/pairSides'
import {
  subcorpusHash,
  queryHash,
  quickHash,
  payloadHash,
  generateId,
} from '@/utils/hashing'
import type {
  UIContextSnapshotV1,
  SubcorpusFilter,
  KwicPreviewRow,
  RecentActionSummary,
} from '@/types/copilot-protocol'

// Maximum number of KWIC preview rows to include
const MAX_PREVIEW_ROWS = 10

// Maximum recent actions to include
const MAX_RECENT_ACTIONS = 15

// Trace history for recent actions (module-level, persists across composable instances)
const recentActionTrace = ref<RecentActionSummary[]>([])

function mapMeasure(value: unknown): 'mi' | 'logDice' | 'tScore' | undefined {
  if (typeof value !== 'string') return undefined
  const lower = value.toLowerCase()
  if (lower === 'logdice') return 'logDice'
  if (lower === 'tscore') return 'tScore'
  if (lower === 'mi') return 'mi'
  return undefined
}

function buildAnalysesSnapshot(presetsStore: ReturnType<typeof useAnalysisPresetsStore>) {
  const presets = presetsStore.sortedPresets ?? []
  const latest = (type: string) => presets.find((p) => p.type === type)

  const collPreset = latest('collocations')
  const freqPreset = latest('frequency')
  const dispPreset = latest('dispersion')
  const semPreset = latest('semantic')

  return {
    collocations: collPreset
      ? {
          term: collPreset.queryTerm,
          measure: mapMeasure((collPreset.params as any)?.measure),
          window: (collPreset.params as any)?.windowSize
            ? {
                left: Number((collPreset.params as any).windowSize),
                right: Number((collPreset.params as any).windowSize),
              }
            : undefined,
          lastRunId: collPreset.id,
        }
      : undefined,
    frequency: freqPreset
      ? {
          groupBy: (freqPreset.params as any)?.groupBy,
          lastRunId: freqPreset.id,
        }
      : undefined,
    dispersion: dispPreset
      ? {
          measure: (dispPreset.params as any)?.measure,
          strata: (dispPreset.params as any)?.strata,
          lastRunId: dispPreset.id,
        }
      : undefined,
    semantic: semPreset
      ? {
          lastQuery: semPreset.queryTerm,
          lastRunId: semPreset.id,
        }
      : undefined,
  }
}

/**
 * Record an action in the trace history
 */
export function recordActionTrace(
  source: 'user' | 'copilot',
  type: string,
  payload: Record<string, unknown>,
  ok: boolean,
  summary?: string
): void {
  const entry: RecentActionSummary = {
    id: generateId('act'),
    ts: Date.now(),
    source,
    type,
    ok,
    summary,
    payloadHash: payloadHash(payload),
  }

  recentActionTrace.value.push(entry)

  // Keep only recent entries
  if (recentActionTrace.value.length > MAX_RECENT_ACTIONS * 2) {
    recentActionTrace.value = recentActionTrace.value.slice(-MAX_RECENT_ACTIONS)
  }
}

/**
 * Clear action trace (for testing or reset)
 */
export function clearActionTrace(): void {
  recentActionTrace.value = []
}

/**
 * Get recent actions for snapshot
 */
export function getRecentActions(): RecentActionSummary[] {
  return recentActionTrace.value.slice(-MAX_RECENT_ACTIONS)
}

export function useContextSnapshot() {
  const queryStore = useQueryStore()
  const uiStore = useUiStore()
  const copilotStore = useCopilotStore()
  const docsetStore = useDocsetStore()
  const analysisPresetsStore = useAnalysisPresetsStore()
  const settingsStore = useSettingsStore()
  const corpusCapabilities = useCorpusCapabilitiesStore()

  /**
   * Build subcorpus filters from docset store
   */
  function buildSubcorpusFilters(): SubcorpusFilter[] {
    const filters: SubcorpusFilter[] = []
    const docsetFilters = docsetStore.filters

    if (docsetFilters.prompting_method.length > 0) {
      filters.push({
        field: 'prompting_method',
        op: 'in',
        value: docsetFilters.prompting_method,
      })
    }

    if (docsetFilters.model.length > 0) {
      filters.push({
        field: 'model',
        op: 'in',
        value: docsetFilters.model,
      })
    }

    if (docsetFilters.register.length > 0) {
      filters.push({
        field: 'register',
        op: 'in',
        value: docsetFilters.register,
      })
    }

    if (docsetFilters.source.length > 0) {
      filters.push({
        field: 'source',
        op: 'in',
        value: docsetFilters.source,
      })
    }

    // Add text type filters. The side values follow the corpus: anchor and
    // version for paired imports from builder revision 2 on, human and ai
    // before.
    const sides = pairSideValues(corpusCapabilities.activeSummary)
    if (!docsetStore.includeAi) {
      filters.push({
        field: 'text_type',
        op: 'eq',
        value: sides.anchor,
      })
    } else if (!docsetStore.includeHuman) {
      filters.push({
        field: 'text_type',
        op: 'eq',
        value: sides.version,
      })
    }

    return filters
  }

  /**
   * Build KWIC preview rows (limited subset for context)
   */
  function buildKwicPreview(): KwicPreviewRow[] {
    const results = queryStore.results
    if (results.length === 0) return []

    // Take a sample: first few, some from middle, some selected
    const preview: KwicPreviewRow[] = []
    const selected = queryStore.selectedRows
    const highlighted = queryStore.highlightedRow

    // Add highlighted row first if exists
    if (highlighted !== null && results[highlighted]) {
      const row = results[highlighted]!
      preview.push({
        rowId: `row-${highlighted}`,
        left: row.left,
        match: row.match,
        right: row.right,
        docId: row.docId,
        position: row.position,
      })
    }

    // Add selected rows (up to 3)
    let selectedCount = 0
    for (const idx of selected) {
      if (selectedCount >= 3) break
      if (idx === highlighted) continue // Skip if already added
      const row = results[idx]
      if (row) {
        preview.push({
          rowId: `row-${idx}`,
          left: row.left,
          match: row.match,
          right: row.right,
          docId: row.docId,
          position: row.position,
        })
        selectedCount++
      }
    }

    // Fill with first few rows
    for (let i = 0; i < Math.min(results.length, MAX_PREVIEW_ROWS - preview.length); i++) {
      const alreadyIncluded = preview.some(p => p.rowId === `row-${i}`)
      if (alreadyIncluded) continue

      const row = results[i]!
      preview.push({
        rowId: `row-${i}`,
        left: row.left,
        match: row.match,
        right: row.right,
        docId: row.docId,
        position: row.position,
      })

      if (preview.length >= MAX_PREVIEW_ROWS) break
    }

    return preview
  }

  // Same source as the interface language: the stored preference, which
  // itself falls back to the browser language.
  function resolveLocale(): 'de' | 'en' {
    const language = settingsStore.preferences.language
    return isAppLocale(language) ? language : 'de'
  }

  function resolveQueryMode(queryTerm: string) {
    const trimmed = queryTerm.trim()
    const isCqlf = trimmed.toLowerCase().startsWith('cql:')
    return {
      mode: isCqlf ? 'cqlf' as const : 'term' as const,
      term: isCqlf ? undefined : (queryTerm || undefined),
      cqlf: isCqlf ? trimmed.slice(4).trim() || undefined : undefined,
    }
  }

  /**
   * Build the full UI context snapshot
   */
  async function buildSnapshot(): Promise<UIContextSnapshotV1> {
    const corpusId = docsetStore.activeCorpus
    const filters = buildSubcorpusFilters()
    const subcorpusHashValue = filters.length > 0
      ? await subcorpusHash(corpusId, filters.map(f => ({
          field: f.field,
          op: f.op,
          value: f.value,
        })))
      : undefined

    const queryTerm = queryStore.term
    const queryMode = resolveQueryMode(queryTerm)
    const contextSize = queryStore.contextSize
    const lastExecutedHash = queryTerm
      ? await queryHash({
          mode: queryMode.mode,
          term: queryMode.term,
          cqlf: queryMode.cqlf,
          context: { left: contextSize, right: contextSize },
        })
      : undefined

    const resultSetHash = queryStore.hasResults
      ? quickHash({
          term: queryTerm,
          total: queryStore.totalHits,
          first: queryStore.results[0]?.position,
        })
      : undefined

    const snapshot: UIContextSnapshotV1 = {
      version: '1.0',
      ts: Date.now(),

      session: {
        conversationId: copilotStore.conversationId ?? generateId('conv'),
        autonomy: copilotStore.autonomyLevel,
        locale: resolveLocale(),
      },

      view: {
        activeTab: uiStore.activeTab as UIContextSnapshotV1['view']['activeTab'],
        theme: uiStore.isDarkMode ? 'dark' : 'light',
      },

      corpus: {
        corpusId,
        subcorpus: {
          filters,
          size: docsetStore.hasActiveDocset
            ? {
                docs: docsetStore.stats.docCount,
                tokens: docsetStore.stats.tokenCount,
              }
            : undefined,
          hash: subcorpusHashValue,
        },
      },

      query: {
        mode: queryMode.mode,
        term: queryMode.term,
        cqlf: queryMode.cqlf,
        context: { left: contextSize, right: contextSize },
        options: {
          caseSensitive: queryStore.caseSensitive,
        },
        lastExecuted: queryStore.hasResults && queryStore.lastExecutedAt
          ? {
              ts: queryStore.lastExecutedAt,
              hash: lastExecutedHash ?? '',
            }
          : undefined,
      },

      kwic: {
        resultSet: queryStore.hasResults
          ? {
              hash: resultSetHash ?? '',
              rows: queryStore.totalHits,
            }
          : undefined,
        selection: {
          rowIds: Array.from(queryStore.selectedRows).map(i => `row-${i}`),
          anchorRowId: queryStore.highlightedRow !== null
            ? `row-${queryStore.highlightedRow}`
            : undefined,
        },
        preview: buildKwicPreview(),
      },

      analyses: buildAnalysesSnapshot(analysisPresetsStore),

      history: {
        recentActions: getRecentActions(),
      },
    }

    return snapshot
  }

  /**
   * Build a synchronous snapshot (without async hashes)
   * Use for immediate context where async is not possible
   */
  function buildSnapshotSync(): UIContextSnapshotV1 {
    const corpusId = docsetStore.activeCorpus
    const filters = buildSubcorpusFilters()
    const queryTerm = queryStore.term
    const queryMode = resolveQueryMode(queryTerm)
    const contextSize = queryStore.contextSize

    const resultSetHash = queryStore.hasResults
      ? quickHash({
          term: queryTerm,
          total: queryStore.totalHits,
          first: queryStore.results[0]?.position,
        })
      : undefined

    return {
      version: '1.0',
      ts: Date.now(),

      session: {
        conversationId: copilotStore.conversationId ?? generateId('conv'),
        autonomy: copilotStore.autonomyLevel,
        locale: resolveLocale(),
      },

      view: {
        activeTab: uiStore.activeTab as UIContextSnapshotV1['view']['activeTab'],
        theme: uiStore.isDarkMode ? 'dark' : 'light',
      },

      corpus: {
        corpusId,
        subcorpus: {
          filters,
          size: docsetStore.hasActiveDocset
            ? {
                docs: docsetStore.stats.docCount,
                tokens: docsetStore.stats.tokenCount,
              }
            : undefined,
          hash: quickHash({ corpusId, filters }),
        },
      },

      query: {
        mode: queryMode.mode,
        term: queryMode.term,
        cqlf: queryMode.cqlf,
        context: { left: contextSize, right: contextSize },
        options: {
          caseSensitive: queryStore.caseSensitive,
        },
        lastExecuted: queryStore.hasResults && queryStore.lastExecutedAt
          ? {
              ts: queryStore.lastExecutedAt,
              hash: quickHash({
                mode: queryMode.mode,
                query: queryMode.mode === 'cqlf' ? queryMode.cqlf : queryMode.term,
                context: contextSize,
              }),
            }
          : undefined,
      },

      kwic: {
        resultSet: queryStore.hasResults
          ? {
              hash: resultSetHash ?? '',
              rows: queryStore.totalHits,
            }
          : undefined,
        selection: {
          rowIds: Array.from(queryStore.selectedRows).map(i => `row-${i}`),
          anchorRowId: queryStore.highlightedRow !== null
            ? `row-${queryStore.highlightedRow}`
            : undefined,
        },
        preview: buildKwicPreview(),
      },

      analyses: buildAnalysesSnapshot(analysisPresetsStore),

      history: {
        recentActions: getRecentActions(),
      },
    }
  }

  /**
   * Computed snapshot hash for change detection
   */
  const snapshotHash = computed(() => {
    return quickHash({
      term: queryStore.term,
      totalHits: queryStore.totalHits,
      activeTab: uiStore.activeTab,
      autonomy: copilotStore.autonomyLevel,
      selectedCount: queryStore.selectedRows.size,
      highlightedRow: queryStore.highlightedRow,
      docsetId: docsetStore.activeDocsetId,
    })
  })

  return {
    buildSnapshot,
    buildSnapshotSync,
    snapshotHash,
    recordActionTrace,
    clearActionTrace,
    getRecentActions,
  }
}
