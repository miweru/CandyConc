<script lang="ts">
/**
 * Pure collocation ranking — exported (alongside the SFC) so the active-measure
 * sort order is unit-testable in isolation. Plain-<script> bindings are visible
 * to <script setup> below, so the component keeps using these directly.
 */
import type { Collocation as CollocationRow } from '@/api/client'
import {
  COLLOCATION_MEASURES,
  collocationScoreForRow,
  collocationSortKeyForMeasure,
  type CollocationMeasure,
} from '@/lib/collocationMeasure'
import { formatNumber } from '@/i18n/format'

export type CollocMeasure = CollocationMeasure

export function mapRowsToCollocations(
  rows: Array<Record<string, any>>,
  selectedMeasure: CollocMeasure
) {
  const mapped = rows.map((row) => {
    const deltaPNc = typeof row.delta_p_nc === 'number' ? row.delta_p_nc : null
    const deltaPCn = typeof row.delta_p_cn === 'number' ? row.delta_p_cn : null
    const observed = row.observed ?? row.f ?? row.frequency ?? 0
    const expected = typeof row.expected === 'number' ? row.expected : null
    const chi2Cell = typeof row.chi2_cell === 'number' ? row.chi2_cell : null
    const score = collocationScoreForRow(row, selectedMeasure)
    const rawWord = row.word ?? ''
    const word = typeof rawWord === 'string' ? rawWord.trim() : String(rawWord).trim()
    const rank = typeof row.rank === 'number' && Number.isFinite(row.rank) ? row.rank : undefined
    return {
      word,
      corpusFrequency: typeof row.f2 === 'number' ? row.f2 : null,
      frequency: typeof observed === 'number' ? observed : 0,
      score,
      measure: selectedMeasure,
      rank,
      observed: typeof observed === 'number' ? observed : undefined,
      expected,
      chi2Cell,
      deltaPNc,
      deltaPCn,
    }
  })
  const byWord = new Map<string, CollocationRow>()
  for (const item of mapped) {
    const key = item.word
    if (!key) continue
    const existing = byWord.get(key)
    if (!existing) {
      byWord.set(key, { ...item })
      continue
    }
    existing.frequency += item.frequency
    if (item.score > existing.score) {
      existing.score = item.score
      existing.expected = item.expected
      existing.chi2Cell = item.chi2Cell
    }
    existing.observed = existing.frequency
    if (item.rank !== undefined) {
      if (existing.rank === undefined || item.rank < existing.rank) {
        existing.rank = item.rank
      }
    }
  }
  return Array.from(byWord.values()).sort((a, b) => {
    // Order by the ACTIVE selected measure's score first: the backend `rank`
    // reflects the server-side sort_by (e.g. MI), so leading with it would
    // defeat a client-side measure switch like ΔP. Use rank only as a
    // stable tiebreak when scores are equal (preserving the server order
    // among ties), then frequency, then the word.
    if (b.score !== a.score) return b.score - a.score
    if (a.rank !== undefined && b.rank !== undefined && a.rank !== b.rank) {
      return a.rank - b.rank
    }
    if (b.frequency !== a.frequency) return b.frequency - a.frequency
    return a.word.localeCompare(b.word, 'de')
  })
}
</script>

<script setup lang="ts">
/**
 * CollocationsTab - Collocation analysis with table and network graph views
 */
import { ref, computed, nextTick, watch, onBeforeUnmount } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import {
  coerceMethodBlock,
  getCollocationsPage,
  methodStatEntries,
  type AnalysisJobRows,
  type Collocation,
  type CollocationAttribute,
  type MethodBlock,
} from '@/api/client'
import {
  useAnalysisJobsStore,
  useAnalysisPresetsStore,
  useDocsetStore,
  useQueryStore,
  useUiStore,
} from '@/stores'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useActions, useDispatch, useMobileDetection } from '@/composables'
import {
  COLLOCATION_OPERATIONS,
  COLLOCATION_ROUTES,
  COLLOCATION_SYNC_API_CAPABILITY_ID,
  useCollocationOperations,
} from '@/composables/useCollocationOperations'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { buildCoKwicQuery, coKwicWindowState, mapCoKwicHits, parseCoKwicQuery } from '@/utils/coKwic'
import { buildCsv, downloadCsv } from '@/utils/csv'
import { extractApiDetail } from '@/utils/apiError'
import { Network, List, RefreshCw, Download, AlertTriangle } from 'lucide-vue-next'
import ForceGraph from './charts/ForceGraph.vue'
import MeasureInfo from '@/components/ui/MeasureInfo.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import { executionScopeForApi } from '@/lib/researchScope'
import { actionBus } from '@/actions'
import {
  clearCollocationActionHandoff,
  collocationActionHandoff,
  type CollocationActionHandoff,
} from '@/actions/collocationHandoff'
import type { RunCollocationsAction } from '@/actions/types'
import {
  analysisCompletenessHeaderLines,
  analysisCompletenessNotice,
  completenessStateFromJobRows,
  type AnalysisCompletenessState,
} from './resultState'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const queryStore = useQueryStore()
const docsetStore = useDocsetStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const uiStore = useUiStore()

const { isMobile } = useMobileDetection()
const presetsStore = useAnalysisPresetsStore()
const analysisJobs = useAnalysisJobsStore()
const { dispatch } = useDispatch()
const { createCollocationJob, loadCollocateKwic } = useCollocationOperations()
// Lemma-Zählung läuft über die sync GET-Route (die Job-Route kennt kein
// `attribute`); eigener Gate-Handle, damit der Pfad produktseitig geprüft ist.
const lemmaStatsGate = useProductRouteOperationGate({
  capabilityId: COLLOCATION_SYNC_API_CAPABILITY_ID,
  label: t('analysis.collocations.lemmaStatsLabel'),
  operationId: COLLOCATION_OPERATIONS.stats,
  operation: { path: COLLOCATION_ROUTES.stats, method: 'GET' },
  fallbackReason: t('analysis.collocations.lemmaStatsNotEnabled'),
})

// State (CollocMeasure + mapRowsToCollocations live in the plain <script> above
// so the ranking is unit-testable; both are in module scope here).
type RawCollocationRow = Record<string, any>

const COLLOCATIONS_JOB_SCOPE = 'collocations'
const COLLOCATION_ROW_ESTIMATE_PX = 44
const COLLOCATION_FALLBACK_VIRTUAL_ROWS = 80
const COLLOCATION_DEFAULT_MIN_FREQUENCY = 5
const COLLOCATION_MAX_WINDOW = 50

interface CollocationVirtualRow {
  virtualRow: { index: number; start: number; end: number }
  row: Collocation
}

interface CollocationRunOptions {
  corpus?: string
  docsetId?: string
  minFreq?: number
}

interface CollocationResultScope {
  corpus: string
  docsetId?: string
}

const windowSize = ref(5)
const withinSentence = ref(true)
const measure = ref<CollocMeasure>('logdice')
// Zählattribut: 'word' (Oberflächenformen) oder 'lemma' (capability-gated).
const attribute = ref<CollocationAttribute>('word')
// Parameter des letzten sync-Laufs (Lemma-Pfad) für Offset-Paging; null im Job-Pfad.
const syncPagingParams = ref<Parameters<typeof getCollocationsPage>[0] | null>(null)
const limit = ref(200)
const minimumFrequency = ref(COLLOCATION_DEFAULT_MIN_FREQUENCY)
const totalRows = ref(0)
const nextOffset = ref(0)
const isLoadingMore = ref(false)
const tableContainerRef = ref<HTMLDivElement | null>(null)
const viewMode = ref<'table' | 'graph'>('table')
const isLoadingCoKwic = ref(false)
const data = ref<Collocation[]>([])
// A Copilot request may name a corpus/docset other than the currently visible
// research scope. Keep that result visibly separate instead of exporting it or
// opening Co-KWIC against whichever corpus happens to be active in the UI.
const resultScopeOverride = ref<CollocationResultScope | null>(null)
// F1: server-provided statistical provenance for the collocation result.
const collocationMethod = ref<MethodBlock | null>(null)
const collocationCompleteness = ref<AnalysisCompletenessState | null>(null)
// Older saved sessions contained rows only. Keep that omission visible instead
// of rendering a historical ranking as if its method and completeness were known.
const restoredProvenanceUnknown = ref(false)
const isLoading = ref(false)
const jobError = ref<string | null>(null)
const rowsJobId = ref<string | null>(null)
const sessionPresetId = ref<string | null>(null)
let runToken = 0
let runController: AbortController | null = null
let autoLoadTimer: number | null = null

const coQuery = computed(() => parseCoKwicQuery(queryStore.term))
const anchorCollocates = computed(() => coQuery.value?.collocates ?? [])
const anchorCollocateKey = computed(() => anchorCollocates.value.join('|'))
const useCoAnchors = computed(() => anchorCollocates.value.length > 0)
const anchorLabel = computed(() => anchorCollocates.value.join(' + '))
const analysisTerm = computed(() => {
  const raw = queryStore.term?.trim() ?? ''
  if (!raw) return ''
  const parsed = coQuery.value
  if (parsed?.term) return parsed.term.trim()
  return raw
})

const activeDocsetId = computed(() =>
  docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined
)
const hasDetachedResultScope = computed(() => {
  const scope = resultScopeOverride.value
  if (!scope) return false
  return scope.corpus !== docsetStore.activeCorpus || scope.docsetId !== activeDocsetId.value
})
const resultCorpus = computed(() => resultScopeOverride.value?.corpus ?? docsetStore.activeCorpus)
const resultDocsetId = computed(() => resultScopeOverride.value?.docsetId ?? activeDocsetId.value)
const detachedScopeReason = computed(() => {
  if (!hasDetachedResultScope.value) return null
  return resultDocsetId.value
    ? t('analysis.collocations.detachedWithDocset', { corpus: resultCorpus.value, docset: resultDocsetId.value })
    : t('analysis.collocations.detached', { corpus: resultCorpus.value })
})

// Counts for an active subcorpus come from its resolved docset; the whole-corpus
// case uses the catalogue. A detached Copilot scope has no local UI statistics,
// so an export must say that rather than borrowing the active corpus numbers.
const exportDocCount = computed<number | null>(() => {
  if (hasDetachedResultScope.value) return null
  return docsetStore.hasActiveDocset ? docsetStore.stats.docCount : corpusCapabilities.activeCorpusDocCount
})
const exportTokenCount = computed<number | null>(() => {
  if (hasDetachedResultScope.value) return null
  return docsetStore.hasActiveDocset ? docsetStore.stats.tokenCount : corpusCapabilities.activeCorpusTokenCount
})

watch(
  () => coQuery.value,
  (next) => {
    if (!next) return
    const nextWindow = Math.max(1, Math.round(next.window))
    if (windowSize.value !== nextWindow) {
      windowSize.value = nextWindow
    }
    if (typeof next.withinSentence === 'boolean' && withinSentence.value !== next.withinSentence) {
      withinSentence.value = next.withinSentence
    }
  },
  { immediate: true }
)

const scopeText = computed(() => {
  if (hasDetachedResultScope.value) {
    return resultDocsetId.value
      ? t('analysis.collocations.scopeCorpusDocset', { corpus: resultCorpus.value, docset: resultDocsetId.value })
      : t('analysis.collocations.scopeCorpus', { corpus: resultCorpus.value })
  }
  if (!docsetStore.hasActiveDocset) return t('analysis.shared.wholeCorpus')
  const docs = formatNumber(docsetStore.stats.docCount)
  const tokens = formatNumber(docsetStore.stats.tokenCount)
  return t('analysis.shared.docsTokens', { docs, tokens })
})

function measureLabelFor(value: string): string {
  switch (value) {
    case 'mi': return 'MI'
    case 'mi3': return 'MI3'
    case 'lmi': return 'LMI'
    case 'npmi': return 'NPMI'
    case 'z': return t('analysis.measureOptions.zScore')
    case 'chi2_cell': return t('analysis.measureOptions.chi2Cell')
    case 'logdice': return 'logDice'
    case 'dice': return 'Dice'
    case 'tscore': return t('analysis.measureOptions.tScore')
    case 'll': return t('analysis.measureOptions.logLikelihoodG2')
    case 'f': return t('analysis.measureOptions.cooccurrenceShort')
    case 'delta_p_nc': return t('analysis.measureOptions.deltaPNc')
    case 'delta_p_cn': return t('analysis.measureOptions.deltaPCn')
    default: return value.toUpperCase()
  }
}

const measureLabel = computed(() => measureLabelFor(measure.value))

// Lemma-Zählung ist nur mit Lemma-Postings im Index möglich (token_attributes.lemma).
const canUseLemmaAttribute = computed(() => corpusCapabilities.canUseTokenAttribute('lemma'))
const lemmaToggleTitle = computed(() =>
  canUseLemmaAttribute.value
    ? t('analysis.measureOptions.countLemmaTitle')
    : t('analysis.measureOptions.lemmaUnavailable'),
)

function setAttribute(next: CollocationAttribute) {
  if (next === 'lemma' && !canUseLemmaAttribute.value) return
  if (attribute.value !== next) attribute.value = next
}

// Korpuswechsel kann das Lemma-Feature entziehen; ehrlich auf Wortform zurückfallen.
watch(canUseLemmaAttribute, (available) => {
  if (!available && attribute.value === 'lemma') {
    attribute.value = 'word'
    uiStore.showToast(t('analysis.collocations.lemmaFallback'), 'info', 2500)
  }
})

/** Display a measure score in the active locale (matches FreeContrastPanel). */
function formatScore(value: number): string {
  return formatNumber(value, { minimumFractionDigits: 3, maximumFractionDigits: 3 })
}

/** Directional explanation for the active delta-P measure (tooltip + legend). */
function deltaPTooltipFor(value: string): string {
  if (value === 'delta_p_nc') return t('analysis.collocations.deltaPNcTooltip')
  if (value === 'delta_p_cn') return t('analysis.collocations.deltaPCnTooltip')
  return ''
}

const isDeltaP = computed(
  () => measure.value === 'delta_p_nc' || measure.value === 'delta_p_cn'
)
const deltaPTooltip = computed(() => deltaPTooltipFor(measure.value))
const jobSnapshot = computed(() =>
  analysisJobs.snapshotFor(rowsJobId.value) ?? analysisJobs.activeSnapshot(COLLOCATIONS_JOB_SCOPE)
)

const isJobRunning = computed(() => {
  const status = jobSnapshot.value?.status
  return status === 'running' || status === 'queued'
})

const hasMoreRows = computed(() => {
  if (!totalRows.value) return false
  return nextOffset.value < totalRows.value
})
const collocationCompletenessNotice = computed(() =>
  analysisCompletenessNotice(collocationCompleteness.value, t('analysis.collocations.listLabel'))
)
const collocationNotices = computed(() => [
  detachedScopeReason.value,
  collocationCompletenessNotice.value,
  restoredProvenanceUnknown.value
    ? t('analysis.collocations.restoredWithoutProvenance')
    : null,
].filter((notice): notice is string => Boolean(notice)))

const collocationVirtualizer = useVirtualizer(
  computed(() => ({
    count: data.value.length,
    getScrollElement: () => tableContainerRef.value,
    estimateSize: () => COLLOCATION_ROW_ESTIMATE_PX,
    initialRect: { width: 1200, height: 600 },
    overscan: 12,
    getItemKey: (index: number) => data.value[index]?.word ?? index,
  }))
)

const virtualCollocationRows = computed<CollocationVirtualRow[]>(() => {
  const rows: CollocationVirtualRow[] = []
  const virtualItems = collocationVirtualizer.value.getVirtualItems()
  if (!virtualItems.length && data.value.length) {
    const count = Math.min(data.value.length, COLLOCATION_FALLBACK_VIRTUAL_ROWS)
    for (let index = 0; index < count; index += 1) {
      const row = data.value[index]
      if (row) {
        rows.push({
          virtualRow: {
            index,
            start: index * COLLOCATION_ROW_ESTIMATE_PX,
            end: (index + 1) * COLLOCATION_ROW_ESTIMATE_PX,
          },
          row,
        })
      }
    }
    return rows
  }
  for (const virtualRow of virtualItems) {
    const row = data.value[virtualRow.index]
    if (row) rows.push({ virtualRow, row })
  }
  return rows
})
const collocationTopPadding = computed(() => virtualCollocationRows.value[0]?.virtualRow.start ?? 0)
const collocationBottomPadding = computed(() => {
  const rows = virtualCollocationRows.value
  const last = rows.length ? rows[rows.length - 1]?.virtualRow : undefined
  const totalSize = Math.max(
    collocationVirtualizer.value.getTotalSize(),
    data.value.length * COLLOCATION_ROW_ESTIMATE_PX,
  )
  return Math.max(0, totalSize - (last?.end ?? 0))
})

const docsetSnapshot = computed(() =>
  !hasDetachedResultScope.value && docsetStore.hasActiveDocset && docsetStore.activeDocsetId
    ? {
        corpus: docsetStore.activeCorpus,
        docsetId: docsetStore.activeDocsetId,
        stats: docsetStore.stats,
        filters: docsetStore.filters,
        includeAi: docsetStore.includeAi,
        includeHuman: docsetStore.includeHuman,
        filterSpec: docsetStore.activeFilterSpec ?? undefined,
        metadataSchemaHash: docsetStore.metaSchemaHash ?? undefined,
        query: analysisTerm.value,
      }
    : null
)

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

function isCurrentRun(token: number): boolean {
  return token === runToken
}

function resetForNewRun(scopeOverride: CollocationResultScope | null) {
  runToken += 1
  runController?.abort()
  runController = new AbortController()
  analysisJobs.clearScope(COLLOCATIONS_JOB_SCOPE)
  rowsJobId.value = null
  syncPagingParams.value = null
  jobError.value = null
  data.value = []
  collocationMethod.value = null
  collocationCompleteness.value = null
  restoredProvenanceUnknown.value = false
  resultScopeOverride.value = scopeOverride
  if (scopeOverride) sessionPresetId.value = null
  totalRows.value = 0
  nextOffset.value = 0
  isLoading.value = true
  return { token: runToken, signal: runController.signal }
}

function restoredCompletenessState(raw: unknown): AnalysisCompletenessState | null {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const value = raw as Record<string, unknown>
  const number = (key: string): number | null => {
    const candidate = value[key]
    return typeof candidate === 'number' && Number.isFinite(candidate) && candidate >= 0
      ? candidate
      : null
  }
  const state: AnalysisCompletenessState = {
    rowLimit: number('rowLimit'),
    totalCandidates: number('totalCandidates'),
    loadedRows: number('loadedRows'),
    availableRows: number('availableRows'),
    truncated: typeof value.truncated === 'boolean' ? value.truncated : undefined,
  }
  return Object.values(state).some((entry) => entry !== null && entry !== undefined)
    ? state
    : null
}

function savedResultMeta(term: string, collocateAnchor: string): Record<string, unknown> {
  return {
    term,
    anchorCollocate: collocateAnchor || null,
    window: windowSize.value,
    withinSentence: withinSentence.value,
    measure: measure.value,
    attribute: attribute.value,
    limit: limit.value,
    minFreq: minimumFrequency.value,
    corpus: docsetStore.activeCorpus,
    docsetId: docsetStore.activeDocsetId ?? null,
    docCount: docsetStore.stats.docCount,
    tokenCount: docsetStore.stats.tokenCount,
    method: collocationMethod.value ?? null,
    completeness: collocationCompleteness.value ?? null,
    generatedAt: Date.now(),
  }
}

// Prepare graph data for ForceGraph
const graphData = computed(() => {
  if (!data.value?.length || !analysisTerm.value) {
    return { nodes: [], links: [] }
  }

  const nodes = [
    { id: analysisTerm.value, group: 'center' as const, size: 20 },
    ...data.value.slice(0, 30).map(r => ({
      id: r.word,
      group: 'collocate' as const,
      size: Math.max(6, Math.sqrt(r.frequency) * 2)
    }))
  ]

  const links = data.value.slice(0, 30).map(r => ({
    source: analysisTerm.value,
    target: r.word,
    value: r.score
  }))

  return { nodes, links }
})

function applyRowsResponse(
  response: AnalysisJobRows<RawCollocationRow>,
  reset = false,
): void {
  const rows = response.rows ?? []
  const rawCount = rows.length
  const mapped = mapRowsToCollocations(rows, measure.value)
  if (reset) {
    // F1: capture the provenance block on the first page of a job.
    collocationMethod.value = coerceMethodBlock((response as { method?: unknown }).method) ?? null
    data.value = mapped
  } else if (mapped.length) {
    data.value.push(...mapped)
  }
  const total = response.total_rows ?? totalRows.value
  totalRows.value = typeof total === 'number' ? total : totalRows.value
  const offsetAfterPage = (reset ? 0 : nextOffset.value) + rawCount
  nextOffset.value = offsetAfterPage
  collocationCompleteness.value = completenessStateFromJobRows(response, {
    loadedRows: offsetAfterPage,
    fallbackRowLimit: limit.value,
  })
}

async function loadMoreRows(reset = false) {
  const activeRowsJobId = rowsJobId.value
  const syncParams = syncPagingParams.value
  if ((!activeRowsJobId && !syncParams) || isLoadingMore.value) return
  if (!reset && !hasMoreRows.value) return
  isLoadingMore.value = true
  try {
    const offset = reset ? 0 : nextOffset.value
    const response = activeRowsJobId
      ? await analysisJobs.rows<RawCollocationRow>(activeRowsJobId, offset, limit.value)
      // Lemma-/sync-Pfad: Offset-Paging direkt gegen GET /analysis/collocates.
      : await getCollocationsPage({ ...syncParams!, offset, limit: limit.value })
    applyRowsResponse(response, reset)
  } catch (err) {
    const message = await extractApiDetail(err)
    uiStore.showToast(message, 'error')
  } finally {
    isLoadingMore.value = false
  }
}

function handleTableScroll() {
  const el = tableContainerRef.value
  if (!el || isLoadingMore.value || !hasMoreRows.value) return
  const remaining = el.scrollHeight - (el.scrollTop + el.clientHeight)
  if (remaining > 600) return
  if (autoLoadTimer !== null) return
  autoLoadTimer = window.setTimeout(async () => {
    autoLoadTimer = null
    await loadMoreRows()
  }, 80)
}

async function openCooccurrenceKwic(collocateWord: string) {
  const term = analysisTerm.value.trim()
  if (!term || !collocateWord || isLoadingCoKwic.value) return
  if (hasDetachedResultScope.value) {
    uiStore.showToast(
      t('analysis.collocations.coKwicDetached'),
      'warning',
    )
    return
  }
  isLoadingCoKwic.value = true

  try {
    const existing = coQuery.value?.collocates ?? []
    const nextCollocates = Array.from(new Set([...existing, collocateWord]))
    const coQueryString = buildCoKwicQuery({
      term,
      collocates: nextCollocates,
      window: windowSize.value,
      withinSentence: withinSentence.value,
      attribute: attribute.value,
    })
    queryStore.setLoading(true)
    queryStore.setTerm(coQueryString)
    queryStore.setFilters({ corpus: docsetStore.activeCorpus })
    queryStore.deselectAll()
    queryStore.setHighlightedRow(null)
    queryStore.setScrollPosition(0)
    queryStore.setPendingScrollPosition(null)

    const result = await loadCollocateKwic({
      term,
      collocates: nextCollocates,
      window: windowSize.value,
      withinSentence: withinSentence.value,
      attribute: attribute.value,
      ctx: queryStore.contextSize,
      corpus: docsetStore.activeCorpus,
      docsetId: docsetStore.activeDocsetId ?? undefined,
      limit: 1000,
    })
    const windowState = coKwicWindowState(result)
    queryStore.setResults(mapCoKwicHits(result), result.total, windowState.totalKnown, windowState.totalPartial)
    queryStore.setCoKwicCounts(result.coKwic)
    queryStore.setResultOffsetStart(0)
    queryStore.setHasPrevious(false)
    queryStore.setHasMore(windowState.hasMore)
    queryStore.setNextOffset(windowState.nextOffset)
    queryStore.setTotalHits(result.total, windowState.totalKnown, windowState.totalPartial)
    queryStore.setLastExecutedAt(Date.now())
    queryStore.finishStreaming()
    await dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
    const label = nextCollocates.join(' + ')
    uiStore.showToast(`Co-KWIC: ${term} + ${label}`, 'info', 2500)
  } catch (err) {
    const message = await extractApiDetail(err)
    queryStore.setError(message)
    queryStore.finishStreaming()
    uiStore.showToast(message, 'error')
  } finally {
    queryStore.setLoading(false)
    isLoadingCoKwic.value = false
  }
}

/**
 * Serialize the server `method` provenance block into CSV comment lines (F1).
 * Returns an empty list when the backend supplied no method block.
 */
function methodBlockToCsvLines(method: MethodBlock | null): string[] {
  if (!method) return []
  const lines: string[] = [`# ${t('analysis.collocations.csvMethodHeader')}`]
  for (const stat of methodStatEntries(method)) {
    const name = typeof stat?.name === 'string' && stat.name ? stat.name : stat.key
    const formula = typeof stat?.latex_formula === 'string' ? ` = ${stat.latex_formula}` : ''
    lines.push(`# ${name}${formula}`)
  }
  for (const key of ['node_frequency', 'window_union_size', 'scope_tokens']) {
    if (typeof method[key] === 'number') lines.push(`# ${key}: ${method[key]}`)
  }
  if (typeof method.window === 'number') lines.push(`# window: ${method.window}`)
  if (typeof method.within_sentence === 'boolean') lines.push(`# within_sentence: ${method.within_sentence}`)
  const fp = method.indexFingerprint ?? method.index_fingerprint
  if (fp) lines.push(`# indexFingerprint: ${fp}`)
  return lines
}

async function saveCompletedSessionResult(term: string, collocateAnchor: string) {
  if (hasDetachedResultScope.value || !sessionPresetId.value) return
  const cacheKey = await presetsStore.buildCacheKey({
    type: 'collocations',
    corpus: docsetStore.activeCorpus,
    docset: docsetSnapshot.value,
    queryTerm: term,
    params: {
      windowSize: windowSize.value,
      withinSentence: withinSentence.value,
      measure: measure.value,
      attribute: attribute.value,
      limit: limit.value,
      minFreq: minimumFrequency.value,
      viewMode: viewMode.value,
      anchorCollocate: collocateAnchor || null,
    },
  })
  void presetsStore.updateResult(
    sessionPresetId.value,
    { rows: data.value },
    {
      ...savedResultMeta(term, collocateAnchor),
      cacheKey,
      cacheVersion: presetsStore.cacheVersion,
    }
  )
}

function requestedRunScope(options: CollocationRunOptions): {
  corpus: string
  docsetId?: string
  scopeOverride: CollocationResultScope | null
  usesActiveScope: boolean
} {
  const corpus = options.corpus?.trim() || docsetStore.activeCorpus
  const explicitDocsetId = options.docsetId?.trim() || undefined
  const docsetId = explicitDocsetId ?? (corpus === docsetStore.activeCorpus ? activeDocsetId.value : undefined)
  const usesActiveScope = corpus === docsetStore.activeCorpus && docsetId === activeDocsetId.value
  return {
    corpus,
    docsetId,
    scopeOverride: usesActiveScope ? null : { corpus, ...(docsetId ? { docsetId } : {}) },
    usesActiveScope,
  }
}

function normalizedMinimumFrequency(value: unknown): number {
  const numeric = typeof value === 'number' ? value : Number(value)
  if (!Number.isFinite(numeric)) return COLLOCATION_DEFAULT_MIN_FREQUENCY
  return Math.max(2, Math.round(numeric))
}

function requestedMinimumFrequency(value: number | undefined): number {
  return normalizedMinimumFrequency(value ?? minimumFrequency.value)
}

function applyActionParameters(payload: RunCollocationsAction['payload']): string | null {
  if (typeof payload.windowSize === 'number') {
    if (!Number.isFinite(payload.windowSize) || !Number.isInteger(payload.windowSize)
      || payload.windowSize < 1 || payload.windowSize > COLLOCATION_MAX_WINDOW) {
      return t('analysis.collocations.invalidWindow', { max: COLLOCATION_MAX_WINDOW })
    }
    windowSize.value = payload.windowSize
  }
  if (typeof payload.withinSentence === 'boolean') {
    withinSentence.value = payload.withinSentence
  }
  if (payload.measure) {
    if (!COLLOCATION_MEASURES.includes(payload.measure)) {
      return t('analysis.collocations.unsupportedMeasure')
    }
    measure.value = payload.measure
  }
  if (typeof payload.minFreq === 'number') {
    if (!Number.isFinite(payload.minFreq) || !Number.isInteger(payload.minFreq) || payload.minFreq < 0) {
      return t('analysis.collocations.invalidMinFreq')
    }
    minimumFrequency.value = normalizedMinimumFrequency(payload.minFreq)
  }
  if (typeof payload.limit === 'number') {
    if (!Number.isFinite(payload.limit) || !Number.isInteger(payload.limit) || payload.limit < 1) {
      return t('analysis.collocations.invalidLimit')
    }
    limit.value = payload.limit
  }
  return null
}

let preparedHandoffId: number | null = null
let skipNextAutomaticRun = false

function prepareActionHandoff(handoff: CollocationActionHandoff): string | null {
  if (preparedHandoffId === handoff.id) return null
  const parameterError = applyActionParameters(handoff.request)
  if (parameterError) return parameterError
  queryStore.setTerm(handoff.request.term)
  const scope = requestedRunScope({
    corpus: handoff.request.corpus,
    docsetId: handoff.request.docsetId,
  })
  resetForNewRun(scope.scopeOverride)
  preparedHandoffId = handoff.id
  return null
}

function applyCompletedActionHandoff(handoff: CollocationActionHandoff): void {
  const result = handoff.result
  const preparationError = prepareActionHandoff(handoff)
  if (!result || preparationError) {
    jobError.value = preparationError ?? t('analysis.collocations.noResult')
    isLoading.value = false
    clearCollocationActionHandoff(handoff.id)
    preparedHandoffId = null
    skipNextAutomaticRun = true
    return
  }
  const rows = result.rows
  data.value = mapRowsToCollocations(rows, measure.value)
  totalRows.value = typeof result.totalRows === 'number' ? result.totalRows : data.value.length
  nextOffset.value = rows.length
  rowsJobId.value = null
  collocationMethod.value = coerceMethodBlock(result.method) ?? null
  collocationCompleteness.value = completenessStateFromJobRows({
    rows,
    total_rows: result.totalRows,
    row_limit: result.rowLimit,
    total_candidates: result.totalCandidates,
    truncated: result.truncated,
  }, {
    loadedRows: rows.length,
    fallbackRowLimit: limit.value,
  })
  if (typeof result.rowLimit === 'number' && result.rowLimit > 0) {
    limit.value = Math.round(result.rowLimit)
  }
  restoredProvenanceUnknown.value = false
  jobError.value = null
  isLoading.value = false
  clearCollocationActionHandoff(handoff.id)
  preparedHandoffId = null
  // The tab mounts after a global action. Do not immediately replace the
  // delivered result with its own active-scope watcher run.
  skipNextAutomaticRun = true
}

watch(
  collocationActionHandoff,
  (handoff) => {
    if (!handoff) return
    const preparationError = prepareActionHandoff(handoff)
    if (preparationError) {
      jobError.value = preparationError
      isLoading.value = false
      clearCollocationActionHandoff(handoff.id)
      preparedHandoffId = null
      skipNextAutomaticRun = true
      return
    }
    if (handoff.status === 'completed') {
      applyCompletedActionHandoff(handoff)
      return
    }
    if (handoff.status === 'failed') {
      jobError.value = handoff.error || t('analysis.collocations.failed')
      isLoading.value = false
      clearCollocationActionHandoff(handoff.id)
      preparedHandoffId = null
      skipNextAutomaticRun = true
    }
  },
  { immediate: true },
)

async function runCollocationsJob(options: CollocationRunOptions = {}) {
  const term = analysisTerm.value.trim()
  const collocateAnchor = useCoAnchors.value ? anchorCollocateKey.value : ''
  if (!term) return
  let requestedScope = requestedRunScope(options)
  const minFreq = requestedMinimumFrequency(options.minFreq)
  if (!options.docsetId && requestedScope.usesActiveScope && docsetStore.hasActiveDocset && docsetStore.isDirty) {
    const rebuilt = await docsetStore.buildDocset(true, term)
    if (!rebuilt || !docsetStore.activeDocsetId) {
      jobError.value = docsetStore.error || t('analysis.collocations.docsetStale')
      isLoading.value = false
      return
    }
    requestedScope = requestedRunScope(options)
  }
  const run = resetForNewRun(requestedScope.scopeOverride)
  try {
    const sortBy = collocationSortKeyForMeasure(measure.value)
    const { corpus, docsetId } = requestedScope
    const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
    if (attribute.value === 'lemma') {
      // Lemma-Zählung: die Job-Route kennt kein `attribute` und würde still
      // Wortform-Statistiken rechnen. Deshalb läuft dieser Pfad über die
      // synchrone GET-Route (paged, inkl. method-Provenienz).
      if (collocateAnchor) {
        jobError.value = t('analysis.collocations.coAnchorLemma')
        isLoading.value = false
        return null
      }
      await lemmaStatsGate.assertAvailable({
        target: corpus ? t('analysis.shared.corpusNamed', { name: corpus }) : t('analysis.shared.activeCorpus'),
        impact: t('analysis.collocations.lemmaImpact'),
        contextualConfirmation: {
          surfaceId: 'analysis.collocations',
          interaction: 'collocations.tab.lemma',
          source: 'native_surface',
        },
      })
      const requestParams = {
        term,
        window: windowSize.value,
        withinSentence: withinSentence.value,
        sortBy,
        minFreq,
        attribute: 'lemma' as const,
        corpus,
        docsetId,
      }
      const rowsResponse = await getCollocationsPage({ ...requestParams, limit: limit.value })
      if (!isCurrentRun(run.token)) return null
      syncPagingParams.value = requestParams
      applyRowsResponse(rowsResponse, true)
      await saveCompletedSessionResult(term, collocateAnchor)
      return { rows: data.value, executionScope }
    }
    const rowsResponse = await analysisJobs.runJobRows<RawCollocationRow>({
      scope: COLLOCATIONS_JOB_SCOPE,
      kind: 'collocates',
      corpus,
      signal: run.signal,
      rowsLimit: limit.value,
      queuedMessage: t('analysis.collocations.jobStarted'),
      productOperation: {
        operationId: COLLOCATION_OPERATIONS.job,
        surfaceId: 'analysis.collocations',
        label: t('analysis.operations.collocationJob'),
        detail: analysisTerm.value || corpus,
      },
      start: () => createCollocationJob({
        term,
        collocate: collocateAnchor || undefined,
        window: windowSize.value,
        minFreq,
        limit: limit.value,
        withinSentence: withinSentence.value,
        sortBy,
        corpus,
        docsetId,
      }, {
        target: corpus ? t('analysis.shared.corpusNamed', { name: corpus }) : t('analysis.shared.activeCorpus'),
        impact: t('analysis.collocations.jobImpact'),
        contextualConfirmation: {
          surfaceId: 'analysis.collocations',
          interaction: 'collocations.tab.job',
          source: 'native_surface',
        },
      }),
      onStarted: async (start) => {
        rowsJobId.value = start.job_id
        if (requestedScope.scopeOverride) return
        try {
          const session = await presetsStore.upsertJobSession({
            id: sessionPresetId.value ?? undefined,
            name: t('analysis.collocations.defaultName', { query: term || t('analysis.collocations.noQuery') }),
            type: 'collocations',
            corpus: docsetStore.activeCorpus,
            docset: docsetSnapshot.value,
            queryTerm: term,
            params: {
              windowSize: windowSize.value,
              withinSentence: withinSentence.value,
              measure: measure.value,
              attribute: attribute.value,
              limit: limit.value,
              minFreq,
              viewMode: viewMode.value,
              anchorCollocate: collocateAnchor || null,
            },
            status: 'queued',
            jobId: start.job_id,
            kind: sessionPresetId.value ? undefined : 'session',
          })
          sessionPresetId.value = session.id
        } catch (err) {
          console.warn('Analysis session could not be saved', err)
        }
      },
      onSnapshot: (snapshot) => {
        if (isCurrentRun(run.token) && sessionPresetId.value) {
          void presetsStore.updateJobStatus(sessionPresetId.value, snapshot)
        }
      },
    })
    if (!isCurrentRun(run.token)) return null
    applyRowsResponse(rowsResponse, true)
    await saveCompletedSessionResult(term, collocateAnchor)
    return { rows: data.value, executionScope }
  } catch (err) {
    if (isAbortError(err)) return null
    jobError.value = await extractApiDetail(err)
    return null
  } finally {
    if (isCurrentRun(run.token)) {
      isLoading.value = false
    }
  }
}

async function resumeJob(existingJobId: string) {
  runToken += 1
  runController?.abort()
  runController = new AbortController()
  const token = runToken
  jobError.value = null
  rowsJobId.value = existingJobId
  data.value = []
  collocationMethod.value = null
  collocationCompleteness.value = null
  restoredProvenanceUnknown.value = false
  resultScopeOverride.value = null
  totalRows.value = 0
  nextOffset.value = 0
  isLoading.value = true
  try {
    const rowsResponse = await analysisJobs.resumeJobRows<RawCollocationRow>({
      scope: COLLOCATIONS_JOB_SCOPE,
      jobId: existingJobId,
      signal: runController.signal,
      rowsLimit: limit.value,
      onSnapshot: (snapshot) => {
        if (isCurrentRun(token) && sessionPresetId.value) {
          void presetsStore.updateJobStatus(sessionPresetId.value, snapshot)
        }
      },
    })
    if (!isCurrentRun(token)) return
    applyRowsResponse(rowsResponse, true)
  } catch (err) {
    if (isAbortError(err)) return
    jobError.value = await extractApiDetail(err)
  } finally {
    if (isCurrentRun(token)) {
      isLoading.value = false
    }
  }
}

async function cancelJob() {
  const activeJobId = analysisJobs.activeJobId(COLLOCATIONS_JOB_SCOPE) ?? rowsJobId.value
  if (!activeJobId || !isJobRunning.value) return
  try {
    const snap = await analysisJobs.cancelJob(activeJobId)
    rowsJobId.value = activeJobId
    analysisJobs.clearScope(COLLOCATIONS_JOB_SCOPE)
    if (!hasDetachedResultScope.value && sessionPresetId.value) {
      void presetsStore.updateJobStatus(sessionPresetId.value, snap)
    }
    runController?.abort()
    jobError.value = null
    isLoading.value = false
    uiStore.showToast(t('analysis.collocations.cancelling'), 'info')
  } catch (err) {
    uiStore.showToast(t('analysis.collocations.cancelFailed'), 'error')
  }
}

// Export CSV
function exportCSV() {
  if (!data.value?.length && !rowsJobId.value) return

  void (async () => {
    const filters = docsetStore.filters
    const filterLines = hasDetachedResultScope.value
      ? [`# UI-Filter: ${t('analysis.collocations.csvFilterDetached')}`]
      : [
          `# Filter.prompting_method: ${filters.prompting_method.length ? filters.prompting_method.join(' | ') : 'all'}`,
          `# Filter.model: ${filters.model.length ? filters.model.join(' | ') : 'all'}`,
          `# Filter.register: ${filters.register.length ? filters.register.join(' | ') : 'all'}`,
          `# Filter.source: ${filters.source.length ? filters.source.join(' | ') : 'all'}`,
          `# IncludeAI: ${docsetStore.includeAi}`,
          `# IncludeHuman: ${docsetStore.includeHuman}`,
        ]
    // F1: provenance comes from the SERVER `method` block (single source of
    // truth) rather than hand-maintained formula strings. Empty when absent.
    const formulaLines = methodBlockToCsvLines(collocationMethod.value)
    let rowsToExport = data.value
    const exportJobId = rowsJobId.value
    if (exportJobId && jobSnapshot.value?.status === 'done') {
      try {
        const allRows: Collocation[] = []
        let offset = 0
        const pageSize = 1000
        while (true) {
          const resp = await analysisJobs.rows<RawCollocationRow>(exportJobId, offset, pageSize)
          const rows = resp.rows ?? []
          const mapped = mapRowsToCollocations(rows, measure.value)
          if (!rows.length) break
          allRows.push(...mapped)
          offset += rows.length
          const total = resp.total_rows ?? totalRows.value
          if (typeof total === 'number' && offset >= total) break
          if (rows.length < pageSize) break
        }
        if (allRows.length) {
          rowsToExport = allRows
          collocationCompleteness.value = collocationCompleteness.value
            ? { ...collocationCompleteness.value, loadedRows: allRows.length }
            : { loadedRows: allRows.length, truncated: false }
        }
      } catch (err) {
        console.warn('Collocation export fallback to loaded rows', err)
      }
    }

    const meta = [
      '# CandyConc Export',
      '# Analysis: Collocations',
      `# Term: ${analysisTerm.value}`,
      ...(useCoAnchors.value ? [`# AnchorCollocate: ${anchorCollocateKey.value}`] : []),
      `# Window: ${windowSize.value}`,
      `# WithinSentence: ${withinSentence.value}`,
      `# Measure: ${measure.value}`,
      `# Attribute: ${attribute.value}`,
      `# MinFreq: ${minimumFrequency.value}`,
      `# Corpus: ${resultCorpus.value}`,
      `# Docset: ${resultDocsetId.value ?? 'all'}`,
      `# Docs: ${exportDocCount.value ?? t('analysis.collocations.csvNotResolved')}`,
      `# Tokens: ${exportTokenCount.value ?? t('analysis.collocations.csvNotResolved')}`,
      ...filterLines,
      ...formulaLines,
      ...analysisCompletenessHeaderLines(collocationCompleteness.value),
      `# Exported: ${new Date().toISOString()}`,
    ]

    const csv = buildCsv({
      meta,
      headers: ['word', 'observed', 'expected', 'score', 'measure', 'chi2_cell', 'delta_p_nc', 'delta_p_cn', 'f2'],
      rows: rowsToExport.map((r) => [
        r.word,
        r.observed ?? r.frequency,
        typeof r.expected === 'number' ? r.expected.toFixed(4) : '',
        r.score.toFixed(4),
        r.measure,
        typeof r.chi2Cell === 'number' ? r.chi2Cell.toFixed(4) : '',
        typeof r.deltaPNc === 'number' ? r.deltaPNc.toFixed(6) : '',
        typeof r.deltaPCn === 'number' ? r.deltaPCn.toFixed(6) : '',
        r.corpusFrequency ?? '',
      ]),
    })
    downloadCsv(csv, `collocations_${analysisTerm.value}.csv`)
  })()
}

// Register action handler for Copilot
useActions({
  'analysis/collocations': async (action) => {
    const { payload } = action
    const rawTerm = payload.term?.trim()
    if (rawTerm) {
      queryStore.setTerm(rawTerm)
      // Let a co(...) query initialize its defaults before explicit tool fields
      // take precedence below. This keeps the visible controls reproducible.
      await nextTick()
    }
    const parameterError = applyActionParameters(payload)
    if (parameterError) return { success: false, error: parameterError }
    const result = await runCollocationsJob({
      corpus: payload.corpus,
      docsetId: payload.docsetId,
      minFreq: payload.minFreq,
    })
    if (!result) {
      return { success: false, error: jobError.value ?? t('analysis.collocations.failed') }
    }
    return { success: true, data: result.rows, executionScope: result.executionScope }
  }
})

// Refetch when term changes
watch(
  () => [analysisTerm.value, anchorCollocateKey.value],
  () => {
    if (skipNextAutomaticRun) {
      skipNextAutomaticRun = false
      return
    }
    if (actionBus.isActionInProgress('analysis/collocations') || collocationActionHandoff.value) return
    if (analysisTerm.value) {
      runCollocationsJob()
    }
  },
  { immediate: true }
)

// A corpus switch keeps the search term, but the collocates belong to the
// corpus they were computed on. The tab computes them again for the new
// corpus, like frequency, dispersion and n-grams, and is empty without a term.
watch(
  () => docsetStore.activeCorpus,
  (corpus, previous) => {
    if (corpus === previous) return
    if (actionBus.isActionInProgress('analysis/collocations') || collocationActionHandoff.value) return
    if (analysisTerm.value) {
      runCollocationsJob()
    } else {
      resetForNewRun(null)
    }
  }
)

watch(
  () => presetsStore.pendingPreset,
  async (preset) => {
    if (!preset || preset.type !== 'collocations') return
    sessionPresetId.value = preset.id
    let hasValidResult = false
    const params = preset.params as {
      windowSize?: number
      withinSentence?: boolean
      measure?: CollocMeasure
      attribute?: CollocationAttribute
      limit?: number
      minFreq?: number
      viewMode?: 'table' | 'graph'
      anchorCollocate?: string | null
    }
    if (params.windowSize) windowSize.value = params.windowSize
    if (typeof params.withinSentence === 'boolean') withinSentence.value = params.withinSentence
    if (params.measure) measure.value = params.measure
    if (params.attribute === 'word' || (params.attribute === 'lemma' && canUseLemmaAttribute.value)) {
      attribute.value = params.attribute
    }
    if (params.limit) limit.value = params.limit
    if (typeof params.minFreq === 'number' && Number.isFinite(params.minFreq)) {
      minimumFrequency.value = normalizedMinimumFrequency(params.minFreq)
    }
    if (params.viewMode) viewMode.value = params.viewMode
    presetsStore.setPending(null)
    if (preset.result && typeof preset.result === 'object' && (preset.result as any).rows) {
      const valid = await presetsStore.isResultValid(preset)
      if (valid) {
        data.value = ((preset.result as any).rows ?? []) as Collocation[]
        const savedMeta = preset.resultMeta
        collocationMethod.value = coerceMethodBlock(savedMeta?.method) ?? null
        collocationCompleteness.value = restoredCompletenessState(savedMeta?.completeness)
        restoredProvenanceUnknown.value = !collocationMethod.value || !collocationCompleteness.value
        jobError.value = null
        isLoading.value = false
        rowsJobId.value = null
        analysisJobs.clearScope(COLLOCATIONS_JOB_SCOPE)
        totalRows.value = data.value.length
        nextOffset.value = data.value.length
        hasValidResult = true
      } else {
        uiStore.showToast(t('analysis.shared.staleSaved'), 'info', 2500)
      }
    }
    if (preset.jobId && (preset.status === 'running' || preset.status === 'queued')) {
      await resumeJob(preset.jobId)
    } else if (!hasValidResult) {
      await runCollocationsJob()
    }
  }
)

watch([windowSize, withinSentence, measure, limit, minimumFrequency, attribute], () => {
  const normalizedMinFreq = normalizedMinimumFrequency(minimumFrequency.value)
  if (minimumFrequency.value !== normalizedMinFreq) {
    minimumFrequency.value = normalizedMinFreq
    return
  }
  if (collocationActionHandoff.value || actionBus.isActionInProgress('analysis/collocations')) return
  if (analysisTerm.value) {
    runCollocationsJob()
  }
})

onBeforeUnmount(() => {
  if (preparedHandoffId !== null) {
    clearCollocationActionHandoff(preparedHandoffId)
  }
  runToken += 1
  runController?.abort()
  analysisJobs.clearScope(COLLOCATIONS_JOB_SCOPE)
  if (autoLoadTimer !== null) {
    window.clearTimeout(autoLoadTimer)
    autoLoadTimer = null
  }
})
</script>

<template>
  <div class="collocations-tab">
    <!-- Toolbar -->
    <AnalysisToolbar>
      <template #left>
        <div
          class="scope-pill"
          :class="{
            active: docsetStore.hasActiveDocset && !hasDetachedResultScope,
            stale: docsetStore.isDirty && !hasDetachedResultScope,
            external: hasDetachedResultScope,
          }"
        >
          {{ scopeText }}
        </div>
        <div v-if="useCoAnchors" class="co-anchor-pill">
          {{ t('analysis.collocations.coAnchor', { term: analysisTerm, anchors: anchorLabel }) }}
        </div>

        <label class="slider-label">
          <span class="label-text">{{ t('analysis.measureOptions.windowLabel') }}</span>
          <input
            v-model="windowSize"
            type="range"
            min="1"
            :max="COLLOCATION_MAX_WINDOW"
            class="slider"
          />
          <span class="slider-value">{{ windowSize }}</span>
        </label>

        <label class="scope-toggle" :title="t('analysis.collocations.withinSentenceTitle')">
          <input v-model="withinSentence" type="checkbox" />
          <span>{{ t('analysis.measureOptions.withinSentence') }}</span>
        </label>

        <label class="min-frequency" :title="t('analysis.collocations.minFreqTitle')">
          <span>{{ t('analysis.collocations.minFreqLabel') }}</span>
          <input
            v-model.number="minimumFrequency"
            type="number"
            min="2"
            step="1"
            inputmode="numeric"
            :aria-label="t('analysis.collocations.minFreqAria')"
          />
        </label>

        <select v-model="measure" class="select" :aria-label="t('analysis.measureOptions.associationMeasure')">
          <option value="logdice">logDice</option>
          <option value="dice">Dice</option>
          <option value="mi">{{ t('analysis.measureOptions.mutualInformation') }}</option>
          <option value="mi3">{{ t('analysis.measureOptions.mi3') }}</option>
          <option value="lmi">LMI</option>
          <option value="npmi">NPMI</option>
          <option value="z">{{ t('analysis.measureOptions.zScore') }}</option>
          <option value="tscore">{{ t('analysis.measureOptions.tScore') }}</option>
          <option value="ll">{{ t('analysis.measureOptions.logLikelihoodG2') }}</option>
          <option value="f">{{ t('analysis.measureOptions.cooccurrence') }}</option>
          <option value="chi2_cell">{{ t('analysis.measureOptions.chi2CellDiagnostic') }}</option>
          <option value="delta_p_nc">{{ t('analysis.measureOptions.deltaPNc') }}</option>
          <option value="delta_p_cn">{{ t('analysis.measureOptions.deltaPCn') }}</option>
        </select>
        <MeasureInfo
          :measure-key="measure"
          :method="collocationMethod"
          :fallback-label="measureLabel"
        />

        <div class="attribute-toggle" role="group" :aria-label="t('analysis.measureOptions.countAttribute')">
          <button
            type="button"
            :class="{ active: attribute === 'word' }"
            :aria-pressed="attribute === 'word'"
            :title="t('analysis.measureOptions.countWordTitle')"
            @click="setAttribute('word')"
          >
            {{ t('analysis.measureOptions.wordForm') }}
          </button>
          <button
            type="button"
            :class="{ active: attribute === 'lemma' }"
            :aria-pressed="attribute === 'lemma'"
            :disabled="!canUseLemmaAttribute"
            :title="lemmaToggleTitle"
            @click="setAttribute('lemma')"
          >
            {{ t('analysis.measureOptions.lemma') }}
          </button>
        </div>
      </template>

      <template #right>
        <JobStatusPill
          v-if="jobSnapshot && isJobRunning"
          :status="jobSnapshot.status"
          :progress="jobSnapshot.progress"
          :message="jobSnapshot.message"
          :canCancel="analysisJobs.canCancelJobs"
          @cancel="cancelJob"
        />
        <div class="view-toggle">
          <button
            :class="{ active: viewMode === 'table' }"
            @click="viewMode = 'table'"
          >
            <List class="w-4 h-4" />
            <span class="hidden md:inline">{{ t('analysis.collocations.table') }}</span>
          </button>
          <button
            :class="{ active: viewMode === 'graph' }"
            @click="viewMode = 'graph'"
          >
            <Network class="w-4 h-4" />
            <span class="hidden md:inline">{{ t('analysis.collocations.network') }}</span>
          </button>
        </div>

        <SaveAnalysisButton
          type="collocations"
          :defaultName="t('analysis.collocations.defaultName', { query: analysisTerm || t('analysis.collocations.noQuery') })"
          :corpus="docsetStore.activeCorpus"
          :docset="docsetSnapshot"
          :queryTerm="analysisTerm"
          :params="{ windowSize, withinSentence, measure, attribute, limit, minFreq: minimumFrequency, viewMode, anchorCollocate: anchorCollocateKey }"
          :result="data.length ? { rows: data } : undefined"
          :resultMeta="data.length ? {
            ...savedResultMeta(analysisTerm, anchorCollocateKey),
          } : undefined"
          :disabled="hasDetachedResultScope"
          :disabledReason="detachedScopeReason ?? undefined"
        />

        <button
          class="btn-icon"
          @click="() => void runCollocationsJob()"
          :disabled="isLoading"
          :aria-label="t('analysis.collocations.recompute')"
          :title="t('analysis.collocations.recompute')"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': isLoading }" />
        </button>

        <button
          class="btn-icon"
          @click="exportCSV"
          :disabled="!data?.length"
          :aria-label="t('analysis.collocations.exportCsv')"
          :title="t('analysis.collocations.exportCsv')"
        >
          <Download class="w-4 h-4" />
        </button>
      </template>
    </AnalysisToolbar>

    <CapabilityBoundaryPanel
      capability-id="analysis.collocations"
      :method="collocationMethod"
      class="colloc-method"
    />
    <div v-for="notice in collocationNotices" :key="notice" class="result-warning" role="status" aria-live="polite">
      {{ notice }}
    </div>

    <!-- No Query State -->
    <EmptyState
      v-if="!analysisTerm"
      :icon="Network"
      :title="t('analysis.collocations.noQueryTitle')"
      :description="t('analysis.collocations.noQueryDescription')"
      size="sm"
    />

    <!-- Loading -->
    <div v-else-if="isLoading" class="loading-container">
      <Skeleton v-for="i in 8" :key="i" height="48px" class="mb-2" />
    </div>

    <!-- Error -->
    <EmptyState
      v-else-if="jobError"
      :icon="AlertTriangle"
      :title="t('analysis.collocations.errorTitle')"
      :description="jobError"
      :action-label="t('analysis.shared.retry')"
      :secondary-action-label="t('analysis.shared.checkSubcorpus')"
      size="sm"
      @action="runCollocationsJob"
      @secondaryAction="uiStore.openSubcorpus()"
    />

    <!-- Empty Results -->
    <EmptyState
      v-else-if="!data?.length"
      :icon="Network"
      :title="t('analysis.collocations.emptyTitle')"
      :description="t('analysis.collocations.emptyDescription', { term: analysisTerm })"
      :action-label="t('analysis.shared.recompute')"
      size="sm"
      @action="runCollocationsJob"
    />

    <!-- Graph View -->
    <div v-else-if="viewMode === 'graph'" class="graph-container">
      <ForceGraph :data="graphData" :height="isMobile ? 350 : 500" />
    </div>

    <!-- Table View -->
    <div
      v-else
      ref="tableContainerRef"
      class="table-container"
      @scroll="handleTableScroll"
    >
      <table class="coll-table">
        <thead>
          <tr>
            <th class="rank">#</th>
            <th class="word">{{ t('analysis.collocations.collocate') }}</th>
            <th
              class="freq"
              :title="t('analysis.collocations.frequencyTitle')"
            >{{ t('analysis.collocations.frequency') }}</th>
            <th class="freq" :title="t('analysis.collocations.corpusFrequencyTitle')">f(v)</th>
            <th
              class="score"
              :title="isDeltaP ? deltaPTooltip : (measure === 'logdice' ? t('analysis.collocations.logDiceTitle') : undefined)"
            >{{ measureLabel }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="collocationTopPadding > 0" class="virtual-spacer" aria-hidden="true">
            <td colspan="5" :style="{ height: `${collocationTopPadding}px` }" />
          </tr>
          <tr
            v-for="{ row, virtualRow } in virtualCollocationRows"
            :key="row.word"
            class="data-row"
            :class="{ 'is-busy': isLoadingCoKwic }"
            @click="openCooccurrenceKwic(row.word)"
          >
            <td class="rank">{{ virtualRow.index + 1 }}</td>
            <td class="word">{{ row.word }}</td>
            <td class="freq">{{ formatNumber(row.frequency) }}</td>
            <td class="freq corpus-freq">{{ row.corpusFrequency == null ? '-' : formatNumber(row.corpusFrequency) }}</td>
            <td class="score">{{ formatScore(row.score) }}</td>
          </tr>
          <tr v-if="collocationBottomPadding > 0" class="virtual-spacer" aria-hidden="true">
            <td colspan="5" :style="{ height: `${collocationBottomPadding}px` }" />
          </tr>
          <tr v-if="hasMoreRows || isLoadingMore" class="load-more-row">
            <td colspan="5">
              <div class="load-more">
                <span v-if="isLoadingMore">{{ t('analysis.collocations.loadingMore') }}</span>
                <button v-else type="button" class="link-btn" @click="loadMoreRows()">
                  {{ t('analysis.collocations.loadMore') }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <i18n-t v-if="measure === 'logdice'" keypath="analysis.collocations.logDiceLegend" tag="p" class="measure-legend" scope="global">
        <template #name><strong>logDice</strong></template>
        <template #formula><code>14 + log2(2·O11 / (f(u) + f(v)))</code></template>
      </i18n-t>
      <p v-else-if="isDeltaP" class="measure-legend">
        {{ deltaPTooltip }}
      </p>
      <i18n-t v-else-if="measure === 'chi2_cell'" keypath="analysis.collocations.chi2Legend" tag="p" class="measure-legend" scope="global">
        <template #name><strong>{{ t('analysis.measureOptions.chi2Cell') }}</strong></template>
        <template #e11><code>E11</code></template>
        <template #observed><code>observed</code></template>
        <template #expected><code>expected</code></template>
        <template #chi2cell><code>chi2_cell</code></template>
      </i18n-t>

    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.collocations-tab {
  /* At least as high as the tab, grows with its content: the tab area
     scrolls (App.vue .tab-content). */
  @apply flex flex-col min-h-full;
}

.scope-pill {
  @apply px-2.5 py-1 rounded-full text-xs md:text-sm font-medium;
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
  white-space: nowrap;
}

.scope-pill.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

  .scope-pill.stale {
  @apply ring-1 ring-amber-400/70;
}

.scope-pill.external {
  @apply bg-amber-100 text-amber-900 border border-amber-300;
  @apply dark:bg-amber-950/40 dark:text-amber-100 dark:border-amber-700;
}

.co-anchor-pill {
  @apply px-2.5 py-1 rounded-full text-xs md:text-sm font-medium;
  @apply bg-indigo-50 text-indigo-700 border border-indigo-200;
  @apply dark:bg-indigo-900/30 dark:text-indigo-200 dark:border-indigo-800;
  white-space: nowrap;
}

.result-warning {
  @apply mx-4 mt-3 px-3 py-2 rounded-lg text-xs font-medium;
  @apply bg-amber-50 text-amber-800 border border-amber-200;
  @apply dark:bg-amber-950/30 dark:text-amber-200 dark:border-amber-800;
}

.scope-toggle {
  @apply inline-flex items-center gap-1.5 text-xs md:text-sm;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply px-2 py-1 rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
}

.min-frequency {
  @apply inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-xs md:text-sm;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900;
}

.min-frequency input {
  @apply w-12 bg-transparent text-right font-mono outline-none;
}

.attribute-toggle {
  @apply flex rounded-lg overflow-hidden;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.attribute-toggle button {
  @apply px-2 md:px-3 py-1.5 text-xs md:text-sm transition-colors;
}

.attribute-toggle button.active {
  @apply bg-primary-500 text-white;
}

.attribute-toggle button:not(.active) {
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.attribute-toggle button:disabled {
  @apply opacity-50 cursor-not-allowed;
}

.slider-label {
  @apply flex items-center gap-2 text-sm;
}

.label-text {
  @apply text-neutral-600 dark:text-neutral-400;
}

.slider {
  @apply w-20 md:w-24 h-2 rounded-full;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply accent-primary-500;
}

.slider-value {
  @apply w-6 text-center font-mono text-neutral-700 dark:text-neutral-300;
}

.select {
  @apply px-2 md:px-3 py-1.5 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border-none text-sm;
  @apply focus:ring-2 focus:ring-primary-500;
}

.view-toggle {
  @apply flex rounded-lg overflow-hidden;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.view-toggle button {
  @apply flex items-center gap-1 px-2 md:px-3 py-1.5 text-sm;
  @apply transition-colors;
}

.view-toggle button.active {
  @apply bg-primary-500 text-white;
}

.view-toggle button:not(.active) {
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.btn-icon {
  @apply p-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

.loading-container,
.error-container,
.empty-state {
  @apply flex-1 flex flex-col items-center justify-center p-4;
}

.btn-retry {
  @apply mt-4 px-4 py-2 rounded-lg;
  @apply bg-primary-500 text-white;
  @apply hover:bg-primary-600;
}

.graph-container {
  /* Results in the flow of the tab, which scrolls as a whole. */
  flex: 1 0 auto;
  @apply p-4;
}

.table-container {
  /* Result table: its natural height, at most the visible tab (100cqh).
     Toolbars above it scroll away with the tab. */
  flex: 1 0 auto;
  max-height: 100cqh;
  @apply overflow-auto;
}

.coll-table {
  @apply w-full text-sm;
}

.coll-table th {
  @apply sticky top-0 px-3 md:px-4 py-2 md:py-3 text-left;
  @apply bg-neutral-50 dark:bg-neutral-900;
  @apply font-medium;
  @apply border-b border-neutral-200 dark:border-neutral-800;
}

.coll-table td {
  @apply px-3 md:px-4 py-2;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.coll-table tbody tr.virtual-spacer:hover {
  @apply bg-transparent;
}

.coll-table .virtual-spacer td {
  @apply p-0 border-0;
}

.data-row {
  @apply cursor-pointer transition-colors;
}

.data-row:hover {
  @apply bg-neutral-50 dark:bg-neutral-800/60;
}

.data-row.is-busy {
  @apply opacity-70 pointer-events-none;
}

.load-more-row td {
  @apply px-3 md:px-4 py-3;
}

.load-more {
  @apply flex items-center justify-center;
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.load-more .link-btn {
  @apply text-primary-600 dark:text-primary-400;
  @apply hover:underline;
}

.rank {
  @apply w-12 text-neutral-500;
}

.word {
  @apply font-medium;
}

.freq {
  @apply w-24 text-right font-mono;
}

.score {
  @apply w-24 text-right font-mono text-primary-600 dark:text-primary-400;
}

.measure-legend {
  @apply px-3 md:px-4 py-2 text-xs text-neutral-500 dark:text-neutral-400;
}
</style>
