/**
 * Action Handlers - Connect actions to stores and API
 */

import { actionBus } from './bus'
import {
  beginCollocationActionHandoff,
  clearCollocationActionHandoff,
  completeCollocationActionHandoff,
  failCollocationActionHandoff,
} from './collocationHandoff'
import {
  useQueryStore,
  useUiStore,
  useCopilotStore,
  useHistoryStore,
  useSearchHistoryStore,
  useBookmarksStore,
  useExportStore,
  useSettingsStore,
  useDocsetStore,
  useProductCapabilitiesStore,
  useCorpusCapabilitiesStore,
  useSessionStore,
  useAnalysisJobsStore,
  useProductOperationRunsStore,
  type ActiveTab,
  type ProductOperationRunRecord,
} from '@/stores'
import * as api from '@/api/client'
import type { CorpusSummary } from '@/api/client'
import { readRowSpacing } from '@/utils/sourceSpacing'
import { analysisSurfaceForTab } from '@/lib/productCapabilities'
import { humanizeCqlParseError, isCqlfQuery } from '@/lib/cqlDetection'
import type { ProductOperationAccessOptions } from '@/stores/productCapabilities'
import {
  corpusFeatureDecisionReason,
} from '@/lib/productCorpusFeatures'
import { buildResearchScopeEvidence, executionScopeForApi } from '@/lib/researchScope'
import { collocationScoreForRow, collocationSortKeyForMeasure } from '@/lib/collocationMeasure'
import {
  unsupportedCqlAttributes,
  type CorpusFrequencyGroup,
} from '@/lib/corpusFeatureOptions'
import { QUERY_OPERATIONS, useQueryOperations } from '@/composables/useQueryOperations'
import { COLLOCATION_OPERATIONS, useCollocationOperations } from '@/composables/useCollocationOperations'
import { useCollocationNetworkOperations } from '@/composables/useCollocationNetworkOperations'
import { CONTRAST_OPERATIONS, useContrastOperations } from '@/composables/useContrastOperations'
import { useDispersionOperations } from '@/composables/useDispersionOperations'
import { FREQUENCY_OPERATIONS, useFrequencyOperations } from '@/composables/useFrequencyOperations'
import { KEYNESS_OPERATIONS, useKeynessOperations } from '@/composables/useKeynessOperations'
import { NGRAM_OPERATIONS, useNgramOperations } from '@/composables/useNgramOperations'
import { useSemanticOperations } from '@/composables/useSemanticOperations'
import { useWordSketchOperations } from '@/composables/useWordSketchOperations'
import { useCopilot } from '@/composables/useCopilot'
import { NGRAM_SIZES, mapNgramFrequencyRows, sortNgramRows } from '@/components/analysis/ngrams'
import { coKwicWindowState, mapCoKwicHits, parseCoKwicQuery } from '@/utils/coKwic'
import type { ActionDispatchContext, QueryFilters } from './types'
import type { ExportFormat, ExportOptions } from '@/stores/export'
import { createTraceRecorderMiddleware, setCurrentActionSource } from './traceRecorder'
import { createProductCapabilityGateMiddleware } from './productGate'
import { createPolicyGateMiddleware } from './policyGate'
import { quickHash } from '@/utils/hashing'
import { getMetaSchemaEvidenceForCorpus } from '@/services/metaSchemaEvidenceService'
import { formatDateTime } from '@/i18n/format'
import { kwicLoadWindow } from '@/lib/kwicLoadWindow'
import { t } from '@/i18n'

const isDev = import.meta.env.DEV
const debugLog = (...args: unknown[]) => {
  if (isDev) console.log(...args)
}

const NGRAM_ACTION_DEFAULT_LIMIT = 500
const NGRAM_ACTION_MAX_LIMIT = 2000
const KEYNESS_ACTION_DEFAULT_LIMIT = 500
const KEYNESS_ACTION_MAX_LIMIT = 2000

const resolveStreamWindow = kwicLoadWindow

function normalizeNgramRange(payload: { n?: number; minN?: number; maxN?: number }): { n: number | null; minN: number; maxN: number } {
  const requestedMin = payload.minN ?? payload.n
  const requestedMax = payload.maxN ?? payload.n ?? requestedMin
  const minN = normalizePositiveInteger(requestedMin, NGRAM_SIZES[0])
  const maxN = normalizePositiveInteger(requestedMax, minN)
  const orderedMin = Math.min(minN, maxN)
  const orderedMax = Math.max(minN, maxN)
  return {
    n: orderedMin === orderedMax ? orderedMin : null,
    minN: orderedMin,
    maxN: orderedMax,
  }
}

function normalizeNgramLimit(value: number | undefined): number {
  if (!Number.isFinite(value) || !value) return NGRAM_ACTION_DEFAULT_LIMIT
  return Math.min(NGRAM_ACTION_MAX_LIMIT, Math.max(1, Math.round(value)))
}

function normalizeKeynessLimit(value: number | undefined): number {
  if (!Number.isFinite(value) || !value) return KEYNESS_ACTION_DEFAULT_LIMIT
  return Math.min(KEYNESS_ACTION_MAX_LIMIT, Math.max(1, Math.round(value)))
}

function normalizePositiveInteger(value: number | undefined, fallback: number): number {
  if (!Number.isFinite(value) || !value) return fallback
  return Math.max(1, Math.round(value))
}

type GateOk<T extends object = object> = { success: true } & T
type GateBlocked = { success: false; blocked: true; error: string; policyReason?: string }
type GateResult<T extends object = object> = GateOk<T> | GateBlocked

const ACTION_EXPORT_FORMATS = new Set<ExportFormat>([
  'pdf',
  'docx',
  'csv',
  'tsv',
  'json',
  'jsonl',
  'latex',
  'evidence-json',
])

function exportOptionsForAction(
  payload: { format: string; selection?: 'all' | 'selected' | 'filtered'; scope?: 'loaded' | 'all-server' },
  defaults: ExportOptions,
): ExportOptions {
  if (!ACTION_EXPORT_FORMATS.has(payload.format as ExportFormat)) {
    throw new Error(t('actions.handlers.exportFormatUnsupported', { format: payload.format }))
  }
  const format = payload.format as ExportFormat
  const options: ExportOptions = {
    ...defaults,
    format,
  }
  if (payload.selection === 'selected') {
    options.rowRange = 'selected'
    options.scope = 'loaded'
  } else if (payload.selection === 'all') {
    options.scope = 'all-server'
  } else if (payload.selection === 'filtered') {
    options.scope = 'all-server'
  } else if (payload.scope === 'all-server') {
    options.scope = 'all-server'
  } else if (payload.scope === 'loaded') {
    options.scope = 'loaded'
  }
  if (format === 'tsv' || format === 'json' || format === 'jsonl' || format === 'evidence-json') {
    options.scope = 'all-server'
  }
  if (format === 'evidence-json') {
    options.includeReproMeta = true
  }
  return options
}

async function ensureProductContractAndSession() {
  const productCapabilities = useProductCapabilitiesStore()
  const sessionStore = useSessionStore()
  if (!productCapabilities.hasContract) {
    await productCapabilities.load()
  }
  const needsSession = productCapabilities.capabilities.some((capability) =>
    (capability.backend_route_descriptors ?? []).some((route) =>
      Boolean(route.required_role || (route.access && route.access !== 'public'))
    )
  )
  if (needsSession && !sessionStore.isAuthoritative) {
    await sessionStore.load()
  }
  return productCapabilities
}

const buildKwicEvidenceRows = (rows: Array<Record<string, unknown>>) =>
  rows.slice(0, 50).map(row => ({
    position: row.position,
    docId: row.docId,
    left: row.left,
    match: row.match,
    right: row.right,
  }))

const resolveQueryFilters = (filters: QueryFilters) => {
  let date: string | undefined
  let genre: string | undefined

  if (filters.dateRange) {
    const from = filters.dateRange.from?.trim()
    const to = filters.dateRange.to?.trim()
    if (from && to && from !== to) {
      date = `${from}..${to}`
    } else {
      date = from || to || undefined
    }
  }

  const meta = filters.metadata ?? {}
  if (!date && typeof meta.date === 'string' && meta.date.trim()) {
    date = meta.date.trim()
  }
  if (typeof meta.genre === 'string' && meta.genre.trim()) {
    genre = meta.genre.trim()
  }

  return { date, genre }
}

/**
 * Decide whether a KWIC request must use the sorting GET /query endpoint.
 *
 * Sorting is only served by GET /query — the stream endpoint rejects
 * `sort_by` with an explicit 400. GET /query in turn has no docset support,
 * so with an active docset we reset the sort (announcing it via toast)
 * instead of silently dropping the docset filter.
 */
const isSortedKwicRequest = (
  queryStore: ReturnType<typeof useQueryStore>,
  docsetId: string | undefined,
  uiStore: ReturnType<typeof useUiStore>
): boolean => {
  if (!queryStore.sortBy) return false
  if (docsetId) {
    queryStore.resetSort()
    uiStore.showToast(
      t('actions.handlers.sortWithSubcorpus'),
      'warning'
    )
    return false
  }
  return true
}

const mapSortedQueryHit = (hit: api.QueryResult['hits'][number]) => ({
  position: hit.position,
  left: hit.left,
  match: hit.match,
  right: hit.right,
  docId: hit.doc_id,
  docTitle: hit.doc_title,
  metadata: hit.metadata,
  matchOffsets: hit.match_offsets,
  ...readRowSpacing(hit),
})

type KwicStreamDirection = 'initial' | 'next' | 'prev'

interface KwicStreamRunContext {
  term: string
  corpus?: string
  docsetId?: string
  offset: number
  limit: number
  direction: KwicStreamDirection
}

function kwicStreamEvidence(
  context: KwicStreamRunContext,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    term: context.term,
    corpus: context.corpus ?? null,
    docsetId: context.docsetId ?? null,
    offset: context.offset,
    limit: context.limit,
    direction: context.direction,
    ...extra,
  }
}

function startKwicStreamRun(context: KwicStreamRunContext): ProductOperationRunRecord {
  const operationRuns = useProductOperationRunsStore()
  const startedAt = new Date().toISOString()
  const sourceId = `kwic-stream:${quickHash({ ...context, startedAt })}`
  const directionLabel = context.direction === 'initial'
    ? t('actions.handlers.streamInitial')
    : context.direction === 'prev'
      ? t('actions.handlers.streamPrev')
      : t('actions.handlers.streamNext')

  return operationRuns.startRun({
    operationId: QUERY_OPERATIONS.stream,
    sourceId,
    kind: 'operation',
    surfaceId: 'query.kwic',
    label: directionLabel,
    detail: context.term,
    phase: 'streaming',
    evidence: kwicStreamEvidence(context),
    status: 'running',
    progress: null,
    message: t('actions.handlers.streamRunning'),
    readiness: 'pending',
    warnings: [],
    startedAt,
    updatedAt: startedAt,
    canRefresh: false,
    canCancel: false,
  })
}

function updateKwicStreamRun(
  run: ProductOperationRunRecord | null,
  context: KwicStreamRunContext | null,
  patch: Partial<ProductOperationRunRecord> & { evidence?: Record<string, unknown> },
): void {
  if (!run || !context) return
  useProductOperationRunsStore().updateRun(run.id, {
    ...patch,
    evidence: kwicStreamEvidence(context, patch.evidence ?? {}),
  })
}

function finishKwicStreamRun(
  run: ProductOperationRunRecord | null,
  context: KwicStreamRunContext | null,
  message: string,
  extraEvidence: Record<string, unknown> = {},
): void {
  updateKwicStreamRun(run, context, {
    status: 'succeeded',
    phase: 'window_loaded',
    progress: 100,
    message,
    error: null,
    readiness: 'window_loaded',
    warnings: [],
    completedAt: new Date().toISOString(),
    canCancel: false,
    evidence: extraEvidence,
  })
}

function staleKwicStreamRun(
  run: ProductOperationRunRecord | null,
  context: KwicStreamRunContext | null,
  message: string,
  extraEvidence: Record<string, unknown> = {},
): void {
  updateKwicStreamRun(run, context, {
    status: 'stale',
    phase: 'stream_incomplete',
    progress: null,
    message,
    error: message,
    readiness: 'stale',
    warnings: [message],
    completedAt: new Date().toISOString(),
    canCancel: false,
    evidence: extraEvidence,
  })
}

function cancelKwicStreamRun(
  run: ProductOperationRunRecord | null,
  context: KwicStreamRunContext | null,
): void {
  updateKwicStreamRun(run, context, {
    status: 'cancelled',
    phase: 'cancelled',
    progress: null,
    message: t('actions.handlers.streamCancelled'),
    error: null,
    readiness: 'cancelled',
    warnings: [],
    completedAt: new Date().toISOString(),
    canCancel: false,
  })
}

function failKwicStreamRun(
  run: ProductOperationRunRecord | null,
  context: KwicStreamRunContext | null,
  error: string,
): void {
  updateKwicStreamRun(run, context, {
    status: 'failed',
    phase: 'failed',
    progress: null,
    message: error,
    error,
    readiness: 'failed',
    warnings: [error],
    completedAt: new Date().toISOString(),
    canCancel: false,
  })
}

function shouldTrackHistory(): boolean {
  const historyStore = useHistoryStore()
  return !historyStore.isRestoring
}

function kwicStreamAccessForAction(
  context: ActionDispatchContext,
  options: {
    corpus?: string
    direction: KwicStreamDirection
  },
): ProductOperationAccessOptions {
  const directionLabel = options.direction === 'initial'
    ? t('actions.handlers.directionStart')
    : options.direction === 'prev'
      ? t('actions.handlers.directionPrev')
      : t('actions.handlers.directionNext')
  const access = {
    target: options.corpus ? t('actions.handlers.targetCorpus', { name: options.corpus }) : t('actions.handlers.targetActive'),
    impact: t('actions.handlers.kwicImpact', { direction: directionLabel }),
  }
  if (context.source !== 'user' && context.source !== 'restore' && context.source !== 'template') return access
  return {
    ...access,
    contextualConfirmation: {
      surfaceId: 'query.kwic',
      interaction: `query.kwic.${options.direction}`,
      source: 'action_context',
      dispatchSource: context.source,
      requestId: context.requestId ?? null,
      runId: context.runId ?? null,
    },
  }
}

function frequencyJobAccessForAction(
  context: ActionDispatchContext,
  corpus?: string,
): ProductOperationAccessOptions {
  const access = {
    target: corpus ? t('actions.handlers.targetCorpus', { name: corpus }) : t('actions.handlers.targetActive'),
    impact: t('actions.handlers.frequencyImpact'),
  }
  if (context.source !== 'user' && context.source !== 'restore' && context.source !== 'template') return access
  return {
    ...access,
    contextualConfirmation: {
      surfaceId: 'analysis.frequency',
      interaction: 'analysis.frequency.job',
      source: 'action_context',
      dispatchSource: context.source,
      requestId: context.requestId ?? null,
      runId: context.runId ?? null,
    },
  }
}

async function ensureAnalysisTabVisible(tab: string) {
  const surface = analysisSurfaceForTab(tab)
  const uiStore = useUiStore()

  if (!surface) {
    uiStore.showToast(t('actions.handlers.unknownTab', { tab }), 'warning')
    return { success: false, blocked: true, error: 'unknown_analysis_tab' }
  }

  const visible = await ensureProductCapabilityVisible(surface.capabilityId, surface.label)
  if (!visible.success) return visible

  return { success: true, surface }
}

async function ensureCqlfQueryVisible(term: string): Promise<GateResult> {
  if (!isCqlfQuery(term)) return { success: true }

  const uiStore = useUiStore()
  const productCapabilities = await ensureProductContractAndSession()

  if (!productCapabilities.hasContract || !productCapabilities.isVisible('query.cqlf')) {
    const policyReason = t('actions.handlers.cqlNotEnabled')
    uiStore.showToast(policyReason, 'warning')
    return { success: false, blocked: true, error: 'capability_not_visible', policyReason }
  }

  return { success: true }
}

async function ensureActiveCorpusFeatures(corpusName?: string): Promise<GateResult<{ summary: CorpusSummary }>> {
  const uiStore = useUiStore()
  const docsetStore = useDocsetStore()
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const targetCorpus = corpusName ?? docsetStore.activeCorpus
  let summary = corpusCapabilities.corpora.find((corpus) => corpus.name === targetCorpus) ?? null
  if (!summary) {
    summary = await corpusCapabilities.fetchCapabilities(targetCorpus)
  }
  if (!summary) {
    const policyReason = t('actions.handlers.corpusCapabilitiesUnchecked')
    uiStore.showToast(policyReason, 'warning')
    return { success: false, blocked: true, error: 'corpus_capabilities_unavailable', policyReason }
  }
  return { success: true, summary }
}

async function ensureCqlfCorpusFeatures(term: string, corpusName?: string): Promise<GateResult> {
  if (!isCqlfQuery(term)) return { success: true }

  const uiStore = useUiStore()
  const corpusFeatures = await ensureActiveCorpusFeatures(corpusName)
  if (!corpusFeatures.success) return corpusFeatures

  const missing = unsupportedCqlAttributes(corpusFeatures.summary, term)
  if (missing.length) {
    const policyReason = t('actions.handlers.cqlAttributesMissing', { attributes: missing.join(', ') })
    uiStore.showToast(policyReason, 'warning')
    return { success: false, blocked: true, error: 'corpus_feature_not_available', policyReason }
  }

  return { success: true }
}

async function ensureFrequencyCorpusFeature(
  groupBy: 'word' | 'lemma' | 'pos' | undefined
): Promise<GateResult<{ groupBy: 'word' | 'lemma' | 'pos' }>> {
  if (!groupBy || groupBy === 'word') return { success: true, groupBy: groupBy ?? 'word' }

  const uiStore = useUiStore()
  const corpusFeatures = await ensureActiveCorpusFeatures()
  if (!corpusFeatures.success) return corpusFeatures

  const corpusCapabilities = useCorpusCapabilitiesStore()
  if (!corpusCapabilities.canUseFrequencyGroup(groupBy as CorpusFrequencyGroup)) {
    const policyReason = t('actions.handlers.frequencyGroupMissing', { group: groupBy })
    uiStore.showToast(policyReason, 'warning')
    return { success: false, blocked: true, error: 'corpus_feature_not_available', policyReason }
  }

  return { success: true, groupBy }
}

async function ensureSemanticCorpusFeature(mode: 'passage' | 'thesaurus') {
  const uiStore = useUiStore()
  const corpusFeatureCheck = await ensureActiveCorpusFeatures()
  if (!corpusFeatureCheck.success) return corpusFeatureCheck
  const productCapabilities = await ensureProductContractAndSession()
  const routePredicate = mode === 'thesaurus'
    ? productCapabilities.routeOperationPredicate('/api/v1/semantic/similar_words', 'GET')
    : productCapabilities.routeOperationPredicate('/api/v1/analysis/embedding_search', 'POST')
  const decision = productCapabilities.corpusFeatureDecision(
    'analysis.semantic_similarity',
    corpusFeatureCheck.summary,
    routePredicate,
  )
  if (decision.status !== 'pass') {
    const label = mode === 'thesaurus' ? t('actions.handlers.thesaurus') : t('actions.handlers.passageSearch')
    const policyReason = corpusFeatureDecisionReason(label, decision) ??
      (mode === 'thesaurus'
        ? t('actions.handlers.noWordIndex')
        : t('actions.handlers.noPassageIndex'))
    uiStore.showToast(policyReason, 'warning')
    return { success: false, blocked: true, error: 'corpus_feature_not_available', policyReason }
  }
  return { success: true }
}

async function ensureProductCapabilityVisible(capabilityId: string, label: string): Promise<GateResult> {
  const uiStore = useUiStore()
  const productCapabilities = await ensureProductContractAndSession()

  if (!productCapabilities.hasContract || !productCapabilities.isVisible(capabilityId)) {
    const policyReason = t('actions.handlers.labelNotEnabled', { label })
    uiStore.showToast(policyReason, 'warning')
    return { success: false, blocked: true, error: 'capability_not_visible', policyReason }
  }

  const corpusFeatures = await ensureProductCapabilityCorpusFeatures(capabilityId, label)
  if (!corpusFeatures.success) return corpusFeatures

  return { success: true }
}

async function ensureProductCapabilityCorpusFeatures(capabilityId: string, label: string): Promise<GateResult> {
  const uiStore = useUiStore()
  const docsetStore = useDocsetStore()
  const productCapabilities = useProductCapabilitiesStore()
  const corpusCapabilities = useCorpusCapabilitiesStore()
  let decision = productCapabilities.corpusFeatureDecision(capabilityId, corpusCapabilities.activeSummary)
  if (decision.status === 'pass') return { success: true }

  const activeCorpus = docsetStore.activeCorpus
  if (!corpusCapabilities.activeSummary || corpusCapabilities.activeSummary.name !== activeCorpus) {
    await corpusCapabilities.fetchCapabilities(activeCorpus)
    decision = productCapabilities.corpusFeatureDecision(capabilityId, corpusCapabilities.activeSummary)
    if (decision.status === 'pass') return { success: true }
  }

  const reason =
    corpusFeatureDecisionReason(label, decision) ??
    t('actions.handlers.labelUnavailable', { label })
  uiStore.showToast(reason, 'warning')
  return {
    success: false,
    blocked: true,
    error: decision.status === 'unknown' ? 'corpus_feature_unknown' : 'corpus_feature_not_available',
    policyReason: reason,
  }
}

async function switchAnalysisTab(tab: ActiveTab) {
  const visible = await ensureAnalysisTabVisible(tab)
  if (!visible.success) return visible

  const uiStore = useUiStore()
  const historyStore = useHistoryStore()
  if (shouldTrackHistory() && uiStore.activeTab !== tab) {
    historyStore.pushState()
  }
  uiStore.setActiveTab(tab)
  return { success: true }
}

/**
 * Register all action handlers
 * Called once on app initialization
 */
export function registerActionHandlers() {
  // ============================================
  // Query Actions
  // ============================================

  actionBus.register('query/execute', async (action, context) => {
    const queryStore = useQueryStore()
    const uiStore = useUiStore()
    const historyStore = useHistoryStore()
    const searchHistoryStore = useSearchHistoryStore()
    const settingsStore = useSettingsStore()
    const docsetStore = useDocsetStore()
    const queryOperations = useQueryOperations()
    const nextFilters = action.payload.filters ?? {}
    const targetCorpus = nextFilters.corpus ?? docsetStore.activeCorpus
    const blockQuery = (gate: GateBlocked) => {
      const policyReason = gate.policyReason ?? t('actions.handlers.searchUnavailable')
      queryStore.rejectAttempt(action.payload.term, policyReason)
      return { ...gate, policyReason }
    }

    const kwicVisible = await ensureProductCapabilityVisible('query.kwic', t('actions.handlers.kwicSearch'))
    if (!kwicVisible.success) return blockQuery(kwicVisible)
    const cqlfVisible = await ensureCqlfQueryVisible(action.payload.term)
    if (!cqlfVisible.success) return blockQuery(cqlfVisible)
    const cqlfFeatures = await ensureCqlfCorpusFeatures(action.payload.term, targetCorpus)
    if (!cqlfFeatures.success) return blockQuery(cqlfFeatures)

    const nextContextSize = action.payload.contextSize ?? queryStore.contextSize
    const basePageSize = settingsStore.preferences.resultsPerPage ?? 100
    const streamWindow = resolveStreamWindow(basePageSize)

    const coQuery = parseCoKwicQuery(action.payload.term)
    const termChanges = action.payload.term.trim() !== queryStore.term.trim()
    const explicitDocsetId = action.payload.docsetId?.trim()
    let docsetId = explicitDocsetId
    if (!docsetId && docsetStore.hasActiveDocset) {
      if (docsetStore.activeCorpus !== targetCorpus) {
        const message = t('actions.handlers.scopeOtherCorpus')
        uiStore.showToast(message, 'warning')
        return blockQuery({ success: false, blocked: true, error: 'scope_corpus_mismatch', policyReason: message })
      }

      const origin = docsetStore.activeDocsetOrigin
      if (origin?.kind === 'meta') {
        if (docsetStore.isDirty) {
          const message = t('actions.handlers.scopeMetaDirty')
          uiStore.showToast(message, 'warning')
          return blockQuery({ success: false, blocked: true, error: 'scope_reapply_required', policyReason: message })
        }
        docsetId = docsetStore.activeDocsetId ?? undefined
      } else if (origin?.kind === 'search' && (termChanges || docsetStore.isDirty)) {
        const rebuilt = await docsetStore.buildDocset(true, action.payload.term)
        docsetId = rebuilt ? docsetStore.activeDocsetId ?? undefined : undefined
        if (!docsetId) {
          const message = docsetStore.error ?? t('actions.handlers.scopeRebuildFailed')
          uiStore.showToast(message, 'warning')
          return blockQuery({ success: false, blocked: true, error: 'scope_rebuild_failed', policyReason: message })
        }
      } else if (!termChanges && !docsetStore.isDirty) {
        docsetId = docsetStore.activeDocsetId ?? undefined
      } else {
        const message = t('actions.handlers.scopeAmbiguous')
        docsetStore.markDirty()
        uiStore.showToast(message, 'warning')
        return blockQuery({ success: false, blocked: true, error: 'scope_reapply_required', policyReason: message })
      }
    }
    const executionScope = executionScopeForApi(docsetStore, targetCorpus, docsetId)

    if (shouldTrackHistory()) {
      historyStore.pushState()
    }

    // Prepare for new query
    queryStore.setLoading(true)
    queryStore.setTerm(action.payload.term)
    queryStore.setContextSize(nextContextSize)
    queryStore.setFilters(nextFilters)
    queryStore.deselectAll()
    queryStore.setHighlightedRow(null)
    queryStore.setScrollPosition(0)
    queryStore.setPendingScrollPosition(null)
    queryStore.setResults([], 0, false)  // Clear previous results
    queryStore.setHasMore(false)
    queryStore.setHasPrevious(false)
    queryStore.setNextOffset(0)
    queryStore.setResultOffsetStart(0)

    // Start streaming
    const signal = queryStore.startStreaming()

    let totalHits = 0
    let totalKnown = false
    let countPartial = false
    let queryTimeMs = 0
    let backendQueryTraceId: string | undefined
    const offset = 0
    let receivedDone = false
    let historyAdded = false

    const maybeAddHistory = () => {
      if (historyAdded || !shouldTrackHistory() || !totalKnown) return
      searchHistoryStore.add(action.payload.term, totalHits)
      historyAdded = true
    }
    let activeKwicStreamRun: ProductOperationRunRecord | null = null
    let activeKwicStreamContext: KwicStreamRunContext | null = null

    try {
      if (coQuery) {
        const { loadCollocateKwic } = useCollocationOperations()
        const result = await loadCollocateKwic({
          term: coQuery.term,
          collocates: coQuery.collocates,
          window: coQuery.window,
          ctx: nextContextSize,
          withinSentence: coQuery.withinSentence,
          attribute: coQuery.attribute,
          corpus: targetCorpus,
          docsetId,
          limit: streamWindow,
        })
        // Same completeness derivation as the sorted GET path below: a bounded
        // co-occurrence window is partial (not the complete population) when the
        // backend truncated it OR signalled more hits via next_offset. Marking
        // it complete here would let StatusBar show "N Treffer" over a page.
        const coState = coKwicWindowState(result)
        countPartial = coState.totalPartial
        totalKnown = coState.totalKnown
        queryStore.setResults(mapCoKwicHits(result), result.total, totalKnown, countPartial)
        queryStore.setCoKwicCounts(result.coKwic)
        queryStore.setResultOffsetStart(0)
        queryStore.setHasPrevious(false)
        queryStore.setHasMore(coState.hasMore)
        queryStore.setNextOffset(coState.nextOffset)
        totalHits = result.total
        queryTimeMs = result.query_time_ms ?? 0
        queryStore.setTotalHits(totalHits, totalKnown, countPartial)
        queryStore.setLastExecutedAt(Date.now())
        queryStore.finishStreaming()
        maybeAddHistory()
      } else if (isSortedKwicRequest(queryStore, docsetId, uiStore)) {
        // KWIC-Sort path: /query/stream rejects sort_by with 400 (streaming
        // cannot sort globally), so sorted searches go through GET /query,
        // which returns the sorted window plus X-CandyConc-Sort-Approximate.
        const resolvedFilters = resolveQueryFilters(nextFilters)
        const result = await queryOperations.executeKwicPage({
          term: action.payload.term,
          context: nextContextSize,
          corpus: targetCorpus,
          date: resolvedFilters.date,
          genre: resolvedFilters.genre,
          sortBy: queryStore.sortBy,
          sortDir: queryStore.sortDir,
          caseInsensitive: !queryStore.caseSensitive,
          offset: 0,
          limit: streamWindow,
        })
        backendQueryTraceId = result.backendQueryTraceId
        queryStore.setResults(
          result.hits.map(mapSortedQueryHit),
          result.total,
          !result.truncated,
          Boolean(result.truncated)
        )
        queryStore.setResultOffsetStart(0)
        queryStore.setHasPrevious(false)
        const hasMoreInWindow = result.next_offset !== null && result.next_offset !== undefined
        queryStore.setHasMore(hasMoreInWindow)
        queryStore.setNextOffset(hasMoreInWindow ? result.next_offset ?? 0 : 0)
        totalHits = result.total
        totalKnown = !result.truncated
        countPartial = Boolean(result.truncated)
        queryStore.setTotalHits(totalHits, totalKnown, countPartial)
        queryTimeMs = result.query_time_ms ?? 0
        queryStore.setLastExecutedAt(Date.now())
        queryStore.finishStreaming()
        if (result.sortApproximate) {
          uiStore.showToast(
            t('actions.handlers.sortApproximate'),
            'info'
          )
        }
        maybeAddHistory()
      } else {
        const resolvedFilters = resolveQueryFilters(nextFilters)
        let pendingHits: typeof queryStore.results = []
        let flushHandle: number | null = null
        let lastYield = performance.now()
        const maxPending = Math.max(400, basePageSize * 2)
        const maxHits = streamWindow
        let receivedHits = 0
        let stopEarly = false
        activeKwicStreamContext = {
          term: action.payload.term,
          corpus: targetCorpus,
          docsetId,
          offset,
          limit: streamWindow,
          direction: 'initial',
        }
        activeKwicStreamRun = startKwicStreamRun(activeKwicStreamContext)
        const flushPending = () => {
          if (!pendingHits.length) return
          queryStore.appendResults(pendingHits)
          pendingHits = []
        }
        const scheduleFlush = () => {
          if (flushHandle !== null) return
          flushHandle = window.requestAnimationFrame(() => {
            flushHandle = null
            flushPending()
          })
        }
        for await (const event of queryOperations.streamKwic({
          term: action.payload.term,
          context: nextContextSize,
          corpus: targetCorpus,
          docsetId,
          date: resolvedFilters.date,
          genre: resolvedFilters.genre,
          batchSize: 200,
          limit: streamWindow,
          offset,
          caseInsensitive: !queryStore.caseSensitive,
        }, {
          signal,
          access: kwicStreamAccessForAction(context, {
            corpus: targetCorpus,
            direction: 'initial',
          }),
        })) {
          if (event.type === 'batch' && event.hits) {
            // Append new hits to results
            const mapped = event.hits.map(hit => ({
              position: hit.position,
              left: hit.left,
              match: hit.match,
              right: hit.right,
              docId: hit.doc_id,
              docTitle: hit.doc_title,
              metadata: hit.metadata,
              matchOffsets: hit.match_offsets,
              ...readRowSpacing(hit),
            }))
            const remaining = Math.max(0, maxHits - receivedHits)
            const slice = remaining >= mapped.length ? mapped : mapped.slice(0, remaining)
            if (slice.length) {
              pendingHits.push(...slice)
              receivedHits += slice.length
            }
            if (pendingHits.length >= maxPending) {
              flushPending()
            } else {
              scheduleFlush()
            }
            if (receivedHits >= maxHits) {
              stopEarly = true
              queryStore.cancelStreaming()
              if (flushHandle !== null) {
                window.cancelAnimationFrame(flushHandle)
                flushHandle = null
              }
              flushPending()
              break
            }
            const now = performance.now()
            if (now - lastYield > 12) {
              lastYield = now
              await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
            }
          } else if (event.type === 'progress') {
            // Update streaming progress
            queryStore.setStreamingProgress({
              count: (event.count ?? 0) + offset,
              elapsedMs: event.elapsed_ms ?? 0,
              isStreaming: true
            })
            updateKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext, {
              phase: 'streaming',
              message: t('actions.handlers.streamedCount', { count: (event.count ?? 0) + offset }),
              evidence: {
                streamedCount: (event.count ?? 0) + offset,
                elapsedMs: event.elapsed_ms ?? null,
              },
            })
            const now = performance.now()
            if (now - lastYield > 12) {
              lastYield = now
              await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
            }
          } else if (event.type === 'count') {
            if (typeof event.total === 'number' && Number.isFinite(event.total)) {
              totalHits = event.total
              countPartial = Boolean(event.partial)
              totalKnown = !countPartial
              queryStore.setTotalHits(totalHits, totalKnown, countPartial)
              updateKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext, {
                phase: countPartial ? 'count_partial' : 'count_ready',
                readiness: countPartial ? 'partial_count' : 'complete',
                evidence: {
                  total: event.total,
                  countPartial,
                },
              })
              if (!countPartial) {
                maybeAddHistory()
              }
            }
          } else if (event.type === 'done') {
            backendQueryTraceId = event.backendQueryTraceId ?? backendQueryTraceId
            receivedDone = true
            if (flushHandle !== null) {
              window.cancelAnimationFrame(flushHandle)
              flushHandle = null
            }
            flushPending()
            const pageCount = Math.max(0, queryStore.results.length - offset)
            const inferredPartial = Boolean(event.partial) || Boolean(event.truncated) || event.next_offset !== null
            const nextOffset = event.next_offset ?? (inferredPartial ? offset + pageCount : null)
            if (inferredPartial && nextOffset !== null) {
              queryStore.setHasMore(true)
              queryStore.setNextOffset(nextOffset)
            } else {
              queryStore.setHasMore(false)
              queryStore.setNextOffset(0)
            }

            if (!totalKnown) {
              totalHits = inferredPartial
                ? queryStore.results.length
                : (event.total ?? queryStore.results.length)
              countPartial = countPartial || inferredPartial
              totalKnown = !countPartial
              queryStore.setTotalHits(totalHits, totalKnown, countPartial)
            }
            queryTimeMs = event.query_time_ms ?? 0
            queryStore.setLastExecutedAt(Date.now())
            queryStore.finishStreaming()
            queryStore.setLoading(false)
            maybeAddHistory()
            finishKwicStreamRun(
              activeKwicStreamRun,
              activeKwicStreamContext,
              inferredPartial
                ? t('actions.handlers.windowMore')
                : t('actions.handlers.streamComplete'),
              {
                total: totalHits,
                totalKnown,
                partial: countPartial || inferredPartial,
                nextOffset,
                queryTimeMs,
                backendQueryTraceId: backendQueryTraceId ?? null,
                receivedHits,
              },
            )
            activeKwicStreamRun = null
            activeKwicStreamContext = null
          } else if (event.type === 'error') {
            throw new Error(event.error)
          }
        }
        if (flushHandle !== null) {
          window.cancelAnimationFrame(flushHandle)
          flushHandle = null
        }
        flushPending()
        if (stopEarly) {
          const pageCount = Math.max(0, queryStore.results.length - offset)
          queryStore.setHasMore(true)
          queryStore.setNextOffset(offset + pageCount)
          queryStore.setResultOffsetStart(offset)
          // The UI window was truncated after `maxHits` rows: more matches exist
          // (hasMore=true). Mark the result partial so the label reads
          // "≥ N (partiell)" with load-more, even when the count event already
          // delivered the exact canonical total (totalKnown=true). Otherwise the
          // exact-count reconciliation would render a plain "N Treffer" over a
          // page-sized window. The total itself stays as known (exact when the
          // count event landed, window-length otherwise).
          if (!totalKnown) {
            totalHits = queryStore.results.length
          }
          countPartial = true
          queryStore.setTotalHits(totalHits, totalKnown, true)
          queryStore.setLastExecutedAt(Date.now())
          finishKwicStreamRun(
            activeKwicStreamRun,
            activeKwicStreamContext,
            t('actions.handlers.windowStopped'),
            {
              total: totalHits,
              totalKnown,
              partial: true,
              nextOffset: offset + pageCount,
              receivedHits,
            },
          )
          activeKwicStreamRun = null
          activeKwicStreamContext = null
        } else if (!receivedDone) {
          const canContinue = totalKnown
            ? queryStore.results.length < totalHits
            : queryStore.results.length > 0
          queryStore.setHasMore(canContinue)
          queryStore.setNextOffset(canContinue ? queryStore.results.length : 0)
          if (!totalKnown) {
            totalHits = queryStore.results.length
            queryStore.setTotalHits(totalHits, false, true)
          }
          queryStore.setLastExecutedAt(Date.now())
          staleKwicStreamRun(
            activeKwicStreamRun,
            activeKwicStreamContext,
            t('actions.handlers.streamNoDone'),
            {
              total: totalHits,
              totalKnown: false,
              partial: true,
              receivedHits,
              canContinue,
            },
          )
          activeKwicStreamRun = null
          activeKwicStreamContext = null
        }
      }

      if (!totalKnown && action.payload.term.trim()) {
        // The displayed window may be truncated even when the count is exact
        // (more matches than fit one page -> hasMore). Preserve that
        // window-partial signal so the exact-count reconciliation below renders
        // "≥ N (partiell)" with load-more, rather than wiping it to "N Treffer".
        const windowTruncated = queryStore.hasMore
        try {
          const resolvedFilters = resolveQueryFilters(nextFilters)
          const countResult = await queryOperations.loadQueryCount({
            term: action.payload.term,
            context: nextContextSize,
            corpus: targetCorpus,
            docsetId,
            date: resolvedFilters.date,
            genre: resolvedFilters.genre,
            waitMs: 800,
            start: true,
            caseInsensitive: !queryStore.caseSensitive,
          })
          if (
            countResult.status === 'ready' &&
            typeof countResult.total === 'number' &&
            !countResult.partial
          ) {
            totalHits = countResult.total
            totalKnown = true
            countPartial = windowTruncated
            queryStore.setTotalHits(totalHits, true, windowTruncated)
          } else if (
            countResult.status === 'ready' &&
            typeof countResult.total === 'number' &&
            countResult.partial
          ) {
            totalHits = countResult.total
            totalKnown = false
            countPartial = true
            queryStore.setTotalHits(totalHits, false, true)
          }
        } catch {
          // ignore count fallback errors
        }
      }

      maybeAddHistory()

      return {
        success: true,
        executionScope,
        data: {
          total: totalHits,
          queryTime: queryTimeMs,
          backendQueryTraceId,
          evidenceRows: buildKwicEvidenceRows(queryStore.results as unknown as Array<Record<string, unknown>>),
        }
      }
    } catch (error) {
      // Don't report abort errors
      if (error instanceof Error && error.name === 'AbortError') {
        if (activeKwicStreamRun && activeKwicStreamContext) {
          cancelKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext)
          activeKwicStreamRun = null
          activeKwicStreamContext = null
        }
        return { success: false, error: t('actions.handlers.queryCancelled') }
      }

      const rawMessage = error instanceof Error ? error.message : t('actions.handlers.searchFailed')
      const message = humanizeCqlParseError(rawMessage)
      if (activeKwicStreamRun && activeKwicStreamContext) {
        failKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext, message)
        activeKwicStreamRun = null
        activeKwicStreamContext = null
      }
      queryStore.setError(message)
      uiStore.showToast(message, 'error')
      return { success: false, error: message }
    } finally {
      queryStore.setLoading(false)
      queryStore.finishStreaming()
    }
  })

  actionBus.register('query/loadMore', async (action, context) => {
    const queryStore = useQueryStore()
    const uiStore = useUiStore()
    const settingsStore = useSettingsStore()
    const docsetStore = useDocsetStore()
    const queryOperations = useQueryOperations()
    const { loadCollocateKwic } = useCollocationOperations()

    const direction = action.payload?.direction ?? 'next'
    const wantsPrev = direction === 'prev'

    const kwicVisible = await ensureProductCapabilityVisible('query.kwic', t('actions.handlers.kwicSearch'))
    if (!kwicVisible.success) return kwicVisible
    const cqlfVisible = await ensureCqlfQueryVisible(queryStore.term)
    if (!cqlfVisible.success) return cqlfVisible
    const cqlfFeatures = await ensureCqlfCorpusFeatures(queryStore.term, queryStore.filters.corpus ?? docsetStore.activeCorpus)
    if (!cqlfFeatures.success) return cqlfFeatures

    if (!queryStore.term || (wantsPrev ? !queryStore.hasPrevious : !queryStore.hasMore)) {
      return { success: false, error: t('actions.handlers.noMoreHits') }
    }
    const coQuery = parseCoKwicQuery(queryStore.term)
    if (coQuery) {
      const basePageSize = settingsStore.preferences.resultsPerPage ?? 100
      const streamWindow = resolveStreamWindow(basePageSize)
      const targetCorpus = queryStore.filters.corpus ?? docsetStore.activeCorpus
      const docsetId =
        docsetStore.hasActiveDocset &&
        !docsetStore.isDirty &&
        docsetStore.activeCorpus === targetCorpus
          ? docsetStore.activeDocsetId ?? undefined
          : undefined
      queryStore.startStreaming(queryStore.results.length)
      try {
        if (wantsPrev) {
          const currentStart = queryStore.resultOffsetStart
          const prevOffset = Math.max(0, currentStart - streamWindow)
          if (prevOffset >= currentStart) {
            return { success: false, error: t('actions.handlers.noPreviousHits') }
          }
          const result = await loadCollocateKwic({
            term: coQuery.term,
            collocates: coQuery.collocates,
            window: coQuery.window,
            ctx: queryStore.contextSize,
            withinSentence: coQuery.withinSentence,
            attribute: coQuery.attribute,
            corpus: targetCorpus,
            docsetId,
            limit: streamWindow,
            offset: prevOffset,
          })
          const mapped = mapCoKwicHits(result)
          const coState = coKwicWindowState(result)
          queryStore.prependResults(mapped)
          queryStore.setTotalHits(result.total, coState.totalKnown, coState.totalPartial)
          queryStore.setResultOffsetStart(prevOffset)
          queryStore.setHasPrevious(prevOffset > 0)
          return { success: true, data: { added: mapped.length, direction: 'prev' } }
        }

        const offset = queryStore.nextOffset
        const result = await loadCollocateKwic({
          term: coQuery.term,
          collocates: coQuery.collocates,
          window: coQuery.window,
          ctx: queryStore.contextSize,
          withinSentence: coQuery.withinSentence,
          attribute: coQuery.attribute,
          corpus: targetCorpus,
          docsetId,
          limit: streamWindow,
          offset,
        })
        const mapped = mapCoKwicHits(result)
        const coState = coKwicWindowState(result)
        queryStore.appendResults(mapped)
        queryStore.setTotalHits(result.total, coState.totalKnown, coState.totalPartial)
        queryStore.setHasMore(coState.hasMore)
        queryStore.setNextOffset(coState.nextOffset)
        queryStore.setHasPrevious(queryStore.resultOffsetStart > 0)
        return { success: true, data: { added: mapped.length, direction: 'next' } }
      } catch (error) {
        const message = error instanceof Error ? error.message : t('actions.handlers.coKwicFailed')
        queryStore.setError(message)
        uiStore.showToast(message, 'error')
        return { success: false, error: message }
      } finally {
        queryStore.finishStreaming()
      }
    }

    const basePageSize = settingsStore.preferences.resultsPerPage ?? 100
    const streamWindow = resolveStreamWindow(basePageSize)
    const currentStart = queryStore.resultOffsetStart
    const offset = wantsPrev ? Math.max(0, currentStart - streamWindow) : queryStore.nextOffset
    if (wantsPrev && offset >= currentStart) {
      return { success: false, error: t('actions.handlers.noPreviousHits') }
    }
    const signal = queryStore.startStreaming(queryStore.results.length)

    let totalHits = queryStore.totalHits
    let totalKnown = queryStore.totalKnown
    let countPartial = queryStore.totalPartial
    let queryTimeMs = 0
    let receivedDone = false
    let activeKwicStreamRun: ProductOperationRunRecord | null = null
    let activeKwicStreamContext: KwicStreamRunContext | null = null
    const targetCorpus = queryStore.filters.corpus ?? docsetStore.activeCorpus
    const docsetId =
      docsetStore.hasActiveDocset &&
      !docsetStore.isDirty &&
      docsetStore.activeCorpus === targetCorpus
        ? docsetStore.activeDocsetId ?? undefined
        : undefined

    if (isSortedKwicRequest(queryStore, docsetId, uiStore)) {
      // Sorted pagination also goes through GET /query (the stream endpoint
      // rejects sort_by): the backend sorts its bounded window once and the
      // client slices the requested page out of it.
      try {
        const resolvedFilters = resolveQueryFilters(queryStore.filters)
        const result = await queryOperations.executeKwicPage({
          term: queryStore.term,
          context: queryStore.contextSize,
          corpus: targetCorpus,
          date: resolvedFilters.date,
          genre: resolvedFilters.genre,
          sortBy: queryStore.sortBy,
          sortDir: queryStore.sortDir,
          caseInsensitive: !queryStore.caseSensitive,
          offset,
          limit: streamWindow,
        })
        const mapped = result.hits.map(mapSortedQueryHit)
        if (wantsPrev) {
          queryStore.prependResults(mapped)
          queryStore.setResultOffsetStart(offset)
          queryStore.setHasPrevious(offset > 0)
        } else {
          queryStore.appendResults(mapped)
          const hasMoreInWindow = result.next_offset !== null && result.next_offset !== undefined
          queryStore.setHasMore(hasMoreInWindow)
          queryStore.setNextOffset(hasMoreInWindow ? result.next_offset ?? 0 : 0)
          queryStore.setHasPrevious(queryStore.resultOffsetStart > 0)
        }
        if (!queryStore.totalKnown) {
          queryStore.setTotalHits(result.total, !result.truncated, Boolean(result.truncated))
        }
        return {
          success: true,
          data: { added: mapped.length, direction: wantsPrev ? 'prev' : 'next' }
        }
      } catch (error) {
        const rawMessage =
          error instanceof Error ? error.message : t('actions.handlers.loadMoreFailed')
        const message = humanizeCqlParseError(rawMessage)
        queryStore.setError(message)
        uiStore.showToast(message, 'error')
        return { success: false, error: message }
      } finally {
        queryStore.finishStreaming()
      }
    }

    try {
      const resolvedFilters = resolveQueryFilters(queryStore.filters)
      let pendingHits: typeof queryStore.results = []
      let flushHandle: number | null = null
      let lastYield = performance.now()
      const maxPending = Math.max(400, basePageSize * 2)
      const maxHits = streamWindow
      let receivedHits = 0
      let stopEarly = false
      activeKwicStreamContext = {
        term: queryStore.term,
        corpus: targetCorpus,
        docsetId,
        offset,
        limit: streamWindow,
        direction: wantsPrev ? 'prev' : 'next',
      }
      activeKwicStreamRun = startKwicStreamRun(activeKwicStreamContext)
      const flushPending = () => {
        if (!pendingHits.length) return
        if (wantsPrev) {
          queryStore.prependResults(pendingHits)
        } else {
          queryStore.appendResults(pendingHits)
        }
        pendingHits = []
      }
      const scheduleFlush = () => {
        if (flushHandle !== null) return
        flushHandle = window.requestAnimationFrame(() => {
          flushHandle = null
          flushPending()
        })
      }
      for await (const event of queryOperations.streamKwic({
        term: queryStore.term,
        context: queryStore.contextSize,
        corpus: targetCorpus,
        docsetId,
        date: resolvedFilters.date,
        genre: resolvedFilters.genre,
        batchSize: 200,
        limit: streamWindow,
        offset,
        caseInsensitive: !queryStore.caseSensitive,
      }, {
        signal,
        access: kwicStreamAccessForAction(context, {
          corpus: targetCorpus,
          direction: wantsPrev ? 'prev' : 'next',
        }),
      })) {
        if (event.type === 'batch' && event.hits) {
          const mapped = event.hits.map(hit => ({
            position: hit.position,
            left: hit.left,
            match: hit.match,
            right: hit.right,
            docId: hit.doc_id,
            docTitle: hit.doc_title,
            metadata: hit.metadata,
            matchOffsets: hit.match_offsets,
            ...readRowSpacing(hit),
          }))
          const remaining = Math.max(0, maxHits - receivedHits)
          const slice = remaining >= mapped.length ? mapped : mapped.slice(0, remaining)
          if (slice.length) {
            pendingHits.push(...slice)
            receivedHits += slice.length
          }
          if (pendingHits.length >= maxPending) {
            flushPending()
          } else {
            scheduleFlush()
          }
          if (receivedHits >= maxHits) {
            stopEarly = true
            queryStore.cancelStreaming()
            if (flushHandle !== null) {
              window.cancelAnimationFrame(flushHandle)
              flushHandle = null
            }
            flushPending()
            break
          }
          const now = performance.now()
          if (now - lastYield > 12) {
            lastYield = now
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
          }
        } else if (event.type === 'progress') {
          queryStore.setStreamingProgress({
            count: (event.count ?? 0) + offset,
            elapsedMs: event.elapsed_ms ?? 0,
            isStreaming: true
          })
          updateKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext, {
            phase: 'streaming',
            message: t('actions.handlers.streamedCount', { count: (event.count ?? 0) + offset }),
            evidence: {
              streamedCount: (event.count ?? 0) + offset,
              elapsedMs: event.elapsed_ms ?? null,
            },
          })
          const now = performance.now()
          if (now - lastYield > 12) {
            lastYield = now
            await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()))
          }
        } else if (event.type === 'count') {
          if (typeof event.total === 'number' && Number.isFinite(event.total)) {
            totalHits = event.total
            countPartial = Boolean(event.partial)
            totalKnown = !countPartial
            // The visible window may still be truncated (hasMore) even once the
            // exact count lands mid-stream; keep the "≥ N (partiell)" marker so a
            // truncated window is never rendered as a bare complete total.
            const windowTruncated = queryStore.hasMore
            queryStore.setTotalHits(totalHits, totalKnown, countPartial || windowTruncated)
            updateKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext, {
              phase: countPartial ? 'count_partial' : 'count_ready',
              readiness: countPartial ? 'partial_count' : 'complete',
              evidence: {
                total: event.total,
                countPartial,
              },
            })
          }
        } else if (event.type === 'done') {
          receivedDone = true
          if (flushHandle !== null) {
            window.cancelAnimationFrame(flushHandle)
            flushHandle = null
          }
          flushPending()
          const inferredPartial = Boolean(event.partial) || Boolean(event.truncated) || event.next_offset !== null
          if (wantsPrev) {
            queryStore.setResultOffsetStart(offset)
            queryStore.setHasPrevious(offset > 0)
          } else {
            const pageCount = Math.max(0, queryStore.results.length - offset)
            const nextOffset = event.next_offset ?? (inferredPartial ? offset + pageCount : null)
            if (inferredPartial && nextOffset !== null) {
              queryStore.setHasMore(true)
              queryStore.setNextOffset(nextOffset)
            } else {
              queryStore.setHasMore(false)
              queryStore.setNextOffset(0)
            }
            queryStore.setHasPrevious(queryStore.resultOffsetStart > 0)
          }
          if (!totalKnown) {
            totalHits = queryStore.results.length
            countPartial = countPartial || inferredPartial
            totalKnown = !countPartial
            queryStore.setTotalHits(totalHits, totalKnown, countPartial)
          } else {
            // Exact count already known: reconcile the partial marker with the
            // FINAL window state so a still-truncated window keeps "(partiell)"
            // and a now-complete window renders as an exact total.
            queryStore.setTotalHits(totalHits, true, queryStore.hasMore)
          }
          queryTimeMs = event.query_time_ms ?? 0
          queryStore.setLastExecutedAt(Date.now())
          queryStore.finishStreaming()
          finishKwicStreamRun(
            activeKwicStreamRun,
            activeKwicStreamContext,
            inferredPartial
              ? t('actions.handlers.windowMore')
              : t('actions.handlers.streamComplete'),
            {
              total: totalHits,
              totalKnown,
              partial: countPartial || inferredPartial,
              queryTimeMs,
              receivedHits,
            },
          )
          activeKwicStreamRun = null
          activeKwicStreamContext = null
        } else if (event.type === 'error') {
          throw new Error(event.error)
        }
      }
      if (flushHandle !== null) {
        window.cancelAnimationFrame(flushHandle)
        flushHandle = null
      }
      flushPending()
      if (stopEarly) {
        if (wantsPrev) {
          queryStore.setResultOffsetStart(offset)
          queryStore.setHasPrevious(offset > 0)
          queryStore.setHasMore(true)
        } else {
          const pageCount = Math.max(0, queryStore.results.length - offset)
          queryStore.setHasMore(true)
          queryStore.setNextOffset(offset + pageCount)
          queryStore.setHasPrevious(queryStore.resultOffsetStart > 0)
        }
        if (!totalKnown) {
          totalHits = queryStore.results.length
          queryStore.setTotalHits(totalHits, false, true)
        }
        queryStore.setLastExecutedAt(Date.now())
        finishKwicStreamRun(
          activeKwicStreamRun,
          activeKwicStreamContext,
          t('actions.handlers.windowStopped'),
          {
            total: totalHits,
            totalKnown,
            partial: true,
            receivedHits,
          },
        )
        activeKwicStreamRun = null
        activeKwicStreamContext = null
      } else if (!receivedDone) {
        if (wantsPrev) {
          queryStore.setResultOffsetStart(offset)
          queryStore.setHasPrevious(offset > 0)
        } else {
          const canContinue = totalKnown
            ? queryStore.results.length < totalHits
            : queryStore.results.length > 0
          queryStore.setHasMore(canContinue)
          queryStore.setNextOffset(canContinue ? queryStore.results.length : 0)
          queryStore.setHasPrevious(queryStore.resultOffsetStart > 0)
        }
        if (!totalKnown) {
          totalHits = queryStore.results.length
          queryStore.setTotalHits(totalHits, false, true)
        }
        queryStore.setLastExecutedAt(Date.now())
        staleKwicStreamRun(
          activeKwicStreamRun,
          activeKwicStreamContext,
          t('actions.handlers.streamNoDone'),
          {
            total: totalHits,
            totalKnown: false,
            partial: true,
            receivedHits,
          },
        )
        activeKwicStreamRun = null
        activeKwicStreamContext = null
      }

      if (!totalKnown && queryStore.term.trim()) {
        // The visible window may still be truncated (more matches than fit ->
        // hasMore) even once the exact count resolves. Mirror the initial
        // render's reconciliation so "≥ N (partiell)" survives load-more while
        // hasMore is true; a genuinely-complete result stays exact.
        const windowTruncated = queryStore.hasMore
        try {
          const countResult = await queryOperations.loadQueryCount({
            term: queryStore.term,
            context: queryStore.contextSize,
            corpus: targetCorpus,
            docsetId,
            date: resolvedFilters.date,
            genre: resolvedFilters.genre,
            waitMs: 800,
            start: true,
            caseInsensitive: !queryStore.caseSensitive,
          })
          if (
            countResult.status === 'ready' &&
            typeof countResult.total === 'number' &&
            !countResult.partial
          ) {
            totalHits = countResult.total
            totalKnown = true
            countPartial = windowTruncated
            queryStore.setTotalHits(totalHits, true, windowTruncated)
          } else if (
            countResult.status === 'ready' &&
            typeof countResult.total === 'number' &&
            countResult.partial
          ) {
            totalHits = countResult.total
            totalKnown = false
            countPartial = true
            queryStore.setTotalHits(totalHits, false, true)
          }
        } catch {
          // ignore count fallback errors
        }
      }

      return {
        success: true,
        data: { total: totalHits, queryTime: queryTimeMs }
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        if (activeKwicStreamRun && activeKwicStreamContext) {
          cancelKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext)
          activeKwicStreamRun = null
          activeKwicStreamContext = null
        }
        return { success: false, error: t('actions.handlers.queryCancelled') }
      }

      const rawMessage = error instanceof Error ? error.message : t('actions.handlers.searchFailed')
      const message = humanizeCqlParseError(rawMessage)
      if (activeKwicStreamRun && activeKwicStreamContext) {
        failKwicStreamRun(activeKwicStreamRun, activeKwicStreamContext, message)
        activeKwicStreamRun = null
        activeKwicStreamContext = null
      }
      queryStore.setError(message)
      uiStore.showToast(message, 'error')
      return { success: false, error: message }
    } finally {
      queryStore.setLoading(false)
      queryStore.finishStreaming()
    }
  })

  actionBus.register('query/setFilters', async (action) => {
    const kwicVisible = await ensureProductCapabilityVisible('query.kwic', t('actions.handlers.kwicSearch'))
    if (!kwicVisible.success) return kwicVisible

    const queryStore = useQueryStore()
    const historyStore = useHistoryStore()

    if (shouldTrackHistory()) {
      historyStore.pushState()
    }

    queryStore.setFilters(action.payload)
    return { success: true }
  })

  actionBus.register('query/clear', async () => {
    const kwicVisible = await ensureProductCapabilityVisible('query.kwic', t('actions.handlers.kwicSearch'))
    if (!kwicVisible.success) return kwicVisible

    const queryStore = useQueryStore()
    const historyStore = useHistoryStore()

    if (shouldTrackHistory()) {
      historyStore.pushState()
    }

    queryStore.clear()
    return { success: true }
  })

  // ============================================
  // KWIC Actions
  // ============================================

  actionBus.register('kwic/scrollToRow', async (action) => {
    // Overridden by KwicTable when mounted
    debugLog('[Action] scrollToRow:', action.payload.index)
    return { success: true }
  })

  actionBus.register('kwic/selectRows', async (action) => {
    const queryStore = useQueryStore()
    queryStore.setSelectedRows(action.payload.indices)
    return { success: true }
  })

  actionBus.register('kwic/highlightRow', async (action) => {
    const queryStore = useQueryStore()
    queryStore.setHighlightedRow(action.payload.index)
    return { success: true }
  })

  actionBus.register('kwic/expandContext', async (action) => {
    const queryStore = useQueryStore()
    queryStore.setContextSize(action.payload.contextSize)
    return { success: true }
  })

  // ============================================
  // Navigation Actions
  // ============================================

  actionBus.register('nav/switchTab', async (action) => {
    return switchAnalysisTab(action.payload.tab)
  })

  actionBus.register('nav/openDocument', async (action) => {
    const visible = await ensureProductCapabilityVisible('query.document_access', t('actions.handlers.documentAccess'))
    if (!visible.success) return visible

    const queryStore = useQueryStore()
    const uiStore = useUiStore()
    const docsetStore = useDocsetStore()
    const docId = action.payload.docId?.trim()
    if (!docId) {
      return { success: false, blocked: true, error: 'missing_doc_id' }
    }
    const corpus = action.payload.corpus ?? queryStore.filters.corpus ?? docsetStore.activeCorpus

    const matchingRows = queryStore.results
      .map((row, index) => ({ row, index }))
      .filter(({ row }) => {
        if (String(row.docId) !== docId) return false
        if (action.payload.highlightPosition === undefined) return true
        return row.position === action.payload.highlightPosition
      })
    const rowIndex = action.payload.highlightPosition === undefined
      ? matchingRows.length === 1 ? matchingRows[0]!.index : -1
      : matchingRows[0]?.index ?? -1

    if (rowIndex >= 0) {
      const row = queryStore.results[rowIndex]
      queryStore.setHighlightedRow(rowIndex)
      queryStore.selectRow(rowIndex, false)
      if (uiStore.activeTab !== 'kwic') {
        uiStore.setActiveTab('kwic')
      }
      uiStore.openDocumentDetail({
        docId,
        corpus,
        fallbackLabel: row?.docTitle,
        fallbackMeta: row?.metadata,
        highlight: row?.match?.trim(),
        highlightPosition: row?.position,
        highlightLeft: row?.left,
        highlightRight: row?.right,
      })
    } else {
      uiStore.openDocumentDetail({
        docId,
        corpus,
        fallbackLabel: action.payload.fallbackLabel,
        fallbackMeta: action.payload.fallbackMeta,
        highlight: action.payload.highlight?.trim(),
        highlightPosition: action.payload.highlightPosition,
        highlightLeft: action.payload.highlightLeft,
        highlightRight: action.payload.highlightRight,
      })
    }

    debugLog('[Action] openDocument:', docId)
    return { success: true }
  })

  // ============================================
  // Copilot Actions
  // ============================================

  actionBus.register('copilot/setAutonomy', async (action) => {
    const copilotStore = useCopilotStore()
    if (!Number.isFinite(action.payload.level)) {
      return {
        success: false,
        blocked: true,
        error: 'Autonomy level must be a finite number',
      }
    }
    copilotStore.setAutonomyLevel(action.payload.level)
    return { success: true }
  })

  actionBus.register('copilot/open', async (action) => {
    const gate = await ensureProductCapabilityVisible('research.copilot_grounding', 'Copilot')
    if (!gate.success) return gate
    const copilotStore = useCopilotStore()
    copilotStore.open(action.payload?.mode)
    return { success: true }
  })

  actionBus.register('copilot/close', async () => {
    const copilotStore = useCopilotStore()
    copilotStore.close()
    return { success: true }
  })

  actionBus.register('copilot/sendMessage', async (action) => {
    const gate = await ensureProductCapabilityVisible('research.copilot_grounding', 'Copilot')
    if (!gate.success) return gate
    const message = action.payload.message.trim()
    if (!message) {
      return { success: false, error: t('actions.handlers.copilotMessageEmpty') }
    }
    await useCopilot().sendMessage(message)
    return { success: true }
  })

  actionBus.register('copilot/continue', async (action) => {
    const gate = await ensureProductCapabilityVisible('research.copilot_grounding', 'Copilot')
    if (!gate.success) return gate
    const sessionId = action.payload.sessionId.trim()
    if (!sessionId) {
      return { success: false, error: t('actions.handlers.copilotSessionMissing') }
    }
    await useCopilot().continueCopilotAfterActionResolution(sessionId)
    return { success: true, data: { sessionId } }
  })

  actionBus.register('copilot/answerClarification', async (action) => {
    const gate = await ensureProductCapabilityVisible('research.copilot_grounding', 'Copilot')
    if (!gate.success) return gate
    await useCopilot().answerClarification(action.payload.questionId, action.payload.optionId)
    return { success: true }
  })

  // ============================================
  // Analysis Actions
  // ============================================

  actionBus.register('analysis/collocations', async (action) => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()

    const rawTerm = (action.payload.term ?? queryStore.term).trim()
    if (!rawTerm) {
      return { success: false, error: t('actions.handlers.noTerm') }
    }
    const cqlfVisible = await ensureCqlfQueryVisible(rawTerm)
    if (!cqlfVisible.success) return cqlfVisible
    const requestedCorpus = action.payload.corpus?.trim() || docsetStore.activeCorpus
    const explicitDocsetId = action.payload.docsetId?.trim() || undefined
    const cqlfFeatures = await ensureCqlfCorpusFeatures(rawTerm, requestedCorpus)
    if (!cqlfFeatures.success) return cqlfFeatures
    const coQuery = parseCoKwicQuery(rawTerm)
    const term = (coQuery?.term ?? rawTerm).trim()
    const collocateAnchor = coQuery?.collocates?.length ? coQuery.collocates.join('|') : undefined
    if (!term) {
      return { success: false, error: t('actions.handlers.noTerm') }
    }

    const measure = action.payload.measure ?? 'logdice'
    const requestedMinFreq = typeof action.payload.minFreq === 'number' && Number.isFinite(action.payload.minFreq)
      ? Math.max(5, Math.round(action.payload.minFreq))
      : 5
    const requestedLimit = typeof action.payload.limit === 'number' && Number.isFinite(action.payload.limit)
      ? Math.round(action.payload.limit)
      : undefined
    if (requestedLimit !== undefined && requestedLimit < 1) {
      return { success: false, error: t('actions.handlers.limitInvalid') }
    }
    const windowSize = action.payload.windowSize ?? coQuery?.window ?? 5
    const withinSentence = action.payload.withinSentence ?? coQuery?.withinSentence ?? true
    if (!Number.isFinite(windowSize) || !Number.isInteger(windowSize) || windowSize < 1 || windowSize > 50) {
      return { success: false, error: t('actions.handlers.windowInvalid') }
    }

    // The tab is lazy-mounted. Publish the normalized request before changing
    // tabs so the component renders this exact job result instead of starting a
    // second calculation against the currently active scope while it mounts.
    const handoffId = beginCollocationActionHandoff({
      term: rawTerm,
      windowSize,
      withinSentence,
      measure,
      minFreq: requestedMinFreq,
      corpus: requestedCorpus,
      docsetId: explicitDocsetId,
      limit: requestedLimit,
    })

    // The result shown after navigation must name the term the Copilot actually
    // requested. Deliberately do not switch the active corpus here: a tool call
    // may inspect another corpus, but changing a researcher's workspace is a
    // separate, explicit action.
    queryStore.setTerm(rawTerm)

    const tabResult = await switchAnalysisTab('collocations')
    if (!tabResult.success) {
      clearCollocationActionHandoff(handoffId)
      return tabResult
    }

    try {
      const mapRows = (rows: Array<Record<string, any>>) =>
        rows.map((row) => {
          const score = collocationScoreForRow(row, measure)
          const frequency = row.f ?? row.observed ?? row.frequency ?? 0
          const rawWord = row.word ?? ''
          const word = typeof rawWord === 'string' ? rawWord.trim() : String(rawWord).trim()
          return {
            word,
            frequency: typeof frequency === 'number' ? frequency : 0,
            score,
            measure,
          }
        })

      const sortBy = collocationSortKeyForMeasure(measure)
      if (!explicitDocsetId && requestedCorpus === docsetStore.activeCorpus && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }
      const corpus = requestedCorpus
      const docsetId = explicitDocsetId
        ?? (corpus === docsetStore.activeCorpus && docsetStore.hasActiveDocset
          ? docsetStore.activeDocsetId ?? undefined
          : undefined)
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const analysisJobs = useAnalysisJobsStore()
      const { createCollocationJob } = useCollocationOperations()
      let jobId: string | null = null

      const pageSize = Math.min(requestedLimit ?? 1000, 1000)
      const firstPage = await analysisJobs.runJobRows<Record<string, any>>({
        scope: 'collocations',
        kind: 'collocates',
        corpus,
        rowsLimit: pageSize,
        queuedMessage: t('actions.handlers.collocationJobStarted'),
        productOperation: {
          operationId: COLLOCATION_OPERATIONS.job,
          surfaceId: 'analysis.collocations',
          label: t('actions.handlers.collocationJob'),
          detail: term,
        },
        start: () => createCollocationJob({
          term,
          collocate: collocateAnchor,
          window: windowSize,
          minFreq: requestedMinFreq,
          ...(requestedLimit ? { limit: requestedLimit } : {}),
          withinSentence,
          sortBy,
          corpus,
          docsetId,
        }),
        onStarted: (start) => {
          jobId = start.job_id
        },
      })

      const allRows: Array<Record<string, any>> = [...(firstPage.rows ?? [])]
      let offset = allRows.length
      const totalRows = firstPage.total_rows ?? 0
      let lastPageSize = firstPage.rows?.length ?? 0
      while (jobId && (totalRows ? offset < totalRows : lastPageSize === pageSize)) {
        const rowsResponse = await analysisJobs.rows<Record<string, any>>(jobId, offset, pageSize)
        const rows = rowsResponse.rows ?? []
        if (!rows.length) break
        allRows.push(...rows)
        offset += rows.length
        lastPageSize = rows.length
        const total = rowsResponse.total_rows ?? 0
        if (total && offset >= total) break
        if (rows.length < pageSize) break
      }

      const result = mapRows(allRows)
      completeCollocationActionHandoff(handoffId, {
        rows: allRows,
        totalRows: typeof firstPage.total_rows === 'number' ? firstPage.total_rows : allRows.length,
        rowLimit: firstPage.row_limit,
        totalCandidates: firstPage.total_candidates,
        truncated: firstPage.truncated,
        method: firstPage.method,
      })
      return { success: true, data: result, executionScope }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        failCollocationActionHandoff(handoffId, t('actions.handlers.collocationJobCancelled'))
        return { success: false, error: t('actions.handlers.collocationJobCancelled') }
      }
      const message = error instanceof Error ? error.message : String(error)
      failCollocationActionHandoff(handoffId, message)
      return { success: false, error: message }
    }
  })

  actionBus.register('analysis/collocationNetwork', async (action) => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    const rawTerm = (action.payload.term ?? queryStore.term).trim()
    const coQuery = parseCoKwicQuery(rawTerm)
    const term = (coQuery?.term ?? rawTerm).trim()
    if (!term) {
      return { success: false, error: t('actions.handlers.noTerm') }
    }

    const tabResult = await switchAnalysisTab('collocation_network')
    if (!tabResult.success) return tabResult

    try {
      if (docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }
      const corpus = docsetStore.activeCorpus
      const docsetId = docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const { loadCollocationNetwork } = useCollocationNetworkOperations()
      const result = await loadCollocationNetwork({
        term,
        window: action.payload.windowSize ?? coQuery?.window,
        measure: action.payload.measure ?? 'logdice',
        maxNodes: action.payload.maxNodes,
        expandDepth: action.payload.expandDepth,
        minCount: action.payload.minCount,
        withinSentence: action.payload.withinSentence ?? coQuery?.withinSentence ?? true,
        corpus,
        docsetId,
      })

      return { success: true, data: result, executionScope }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/frequency', async (action, context) => {
    const settingsStore = useSettingsStore()
    const docsetStore = useDocsetStore()
    const analysisJobs = useAnalysisJobsStore()
    const {
      canStartFrequencyJob,
      canCreateFrequencyJob,
      createFrequencyJob,
      loadFrequencyResult,
      rowsToFrequencyResult,
    } = useFrequencyOperations()

    const tabResult = await switchAnalysisTab('frequency')
    if (!tabResult.success) return tabResult
    const groupFeature = await ensureFrequencyCorpusFeature(action.payload.groupBy)
    if (!groupFeature.success) return groupFeature

    try {
      if (docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, useQueryStore().term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }
      const corpus = docsetStore.activeCorpus
      const docsetId = docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const tokenCount = docsetStore.hasActiveDocset && docsetStore.stats.tokenCount > 0
        ? docsetStore.stats.tokenCount
        : settingsStore.systemInfo.tokenCount
      const frequencyParams = {
        groupBy: groupFeature.groupBy,
        sortBy: action.payload.sortBy,
        limit: action.payload.limit,
        stopwords: action.payload.stopwords,
        corpus,
        docsetId,
        tokenCount,
      }
      const canUseFrequencyJob =
        canCreateFrequencyJob(frequencyParams) &&
        canStartFrequencyJob.value &&
        analysisJobs.canRefreshJobs &&
        analysisJobs.canLoadJobRows
      const result = canUseFrequencyJob
        ? rowsToFrequencyResult(
            await analysisJobs.runJobRows<{ word: string; f: number }>({
              scope: 'frequency',
              kind: 'frequency_list',
              corpus,
              rowsLimit: Math.max(frequencyParams.limit ?? 200, 1),
              queuedMessage: t('actions.handlers.frequencyJobStarted'),
              productOperation: {
                operationId: FREQUENCY_OPERATIONS.job,
                surfaceId: 'analysis.frequency',
                label: t('actions.handlers.frequencyJob'),
                detail: frequencyParams.groupBy ?? corpus ?? null,
              },
              start: () => createFrequencyJob(
                frequencyParams,
                frequencyJobAccessForAction(context, corpus),
              ),
            }),
            frequencyParams,
          )
        : await loadFrequencyResult(frequencyParams)
      if (!canUseFrequencyJob) {
        analysisJobs.clearScope('frequency')
      }
      return { success: true, data: result, executionScope }
    } catch (error) {
      return { success: false, error: String(error) }
    }
  })

  actionBus.register('analysis/ngramFrequency', async (action) => {
    const settingsStore = useSettingsStore()
    const docsetStore = useDocsetStore()
    const queryStore = useQueryStore()

    const tabResult = await switchAnalysisTab('ngrams')
    if (!tabResult.success) return tabResult

    try {
      if (docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, queryStore.term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }
      const corpus = docsetStore.activeCorpus
      const docsetId = docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const tokenCount = docsetStore.hasActiveDocset && docsetStore.stats.tokenCount > 0
        ? docsetStore.stats.tokenCount
        : settingsStore.systemInfo.tokenCount
      const ngramRange = normalizeNgramRange(action.payload)
      const minFreq = Number.isFinite(action.payload.minFreq)
        ? Math.max(1, Math.round(action.payload.minFreq ?? 1))
        : 1
      const limit = normalizeNgramLimit(action.payload.limit)
      const sortBy = action.payload.sortBy ?? 'frequency'
      const analysisJobs = useAnalysisJobsStore()
      const { createNgramFrequencyJob } = useNgramOperations()
      const rowsResponse = await analysisJobs.runJobRows<Record<string, unknown>>({
        scope: 'ngrams',
        kind: 'ngrams',
        corpus,
        rowsLimit: limit,
        queuedMessage: t('actions.handlers.ngramJobStarted'),
        productOperation: {
          operationId: NGRAM_OPERATIONS.frequencyJob,
          surfaceId: 'analysis.ngrams',
          label: t('actions.handlers.ngramJob'),
          detail: ngramRange.n ? `${ngramRange.n}-Gramme` : `${ngramRange.minN}-${ngramRange.maxN}-Gramme`,
        },
        start: () => createNgramFrequencyJob({
          minN: ngramRange.minN,
          maxN: ngramRange.maxN,
          minFreq,
          limit,
          corpus,
          docsetId,
        }),
      })
      const rawRows = (rowsResponse.rows ?? []) as Array<Record<string, unknown>>
      const method = api.coerceMethodBlock((rowsResponse as { method?: unknown }).method) ?? null
      const rows = sortNgramRows(
        mapNgramFrequencyRows(rawRows, { minFreq, tokenCount, targetTotal: method?.target_total }),
        sortBy,
      )
      return {
        success: true,
        data: {
          rows,
          n: ngramRange.n ?? ngramRange.minN,
          minN: ngramRange.minN,
          maxN: ngramRange.maxN,
          minFreq,
          sortBy,
          rowLimit: rowsResponse.row_limit,
          totalCandidates: rowsResponse.total_candidates,
          totalRows: rowsResponse.total_rows,
          truncated: rowsResponse.truncated,
          method: method ?? undefined,
        },
        executionScope,
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return { success: false, error: t('actions.handlers.ngramJobCancelled') }
      }
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/ngramContrast', async (action) => {
    const docsetStore = useDocsetStore()
    const queryStore = useQueryStore()

    const tabResult = await switchAnalysisTab('ngrams')
    if (!tabResult.success) return tabResult

    try {
      if (!action.payload.targetDocsetId && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, queryStore.term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.targetUpdateFailed') }
        }
      }

      const targetDocsetId = action.payload.targetDocsetId ?? docsetStore.activeDocsetId ?? undefined
      if (!targetDocsetId) {
        return {
          success: false,
          error: t('actions.handlers.ngramContrastTarget'),
        }
      }
      if (!action.payload.referenceDocsetId) {
        return {
          success: false,
          error: t('actions.handlers.ngramContrastReference'),
        }
      }

      const corpus = action.payload.corpus ?? docsetStore.activeCorpus
      const executionScope = executionScopeForApi(docsetStore, corpus, targetDocsetId)
      const ngramRange = normalizeNgramRange(action.payload)
      const minFreq = Number.isFinite(action.payload.minFreq)
        ? Math.max(1, Math.round(action.payload.minFreq ?? 1))
        : 1
      const limit = normalizeNgramLimit(action.payload.limit)
      const analysisJobs = useAnalysisJobsStore()
      const { createNgramDiffJob } = useNgramOperations()
      const rowsResponse = await analysisJobs.runJobRows<Record<string, unknown>>({
        scope: `ngrams-diff:${corpus}`,
        kind: 'ngrams_diff',
        corpus,
        rowsLimit: limit,
        queuedMessage: t('actions.handlers.ngramContrastStarted'),
        productOperation: {
          operationId: NGRAM_OPERATIONS.diffJob,
          surfaceId: 'analysis.ngrams',
          label: t('actions.handlers.ngramContrastJob'),
          detail: ngramRange.n ? `${ngramRange.n}-Gramme` : `${ngramRange.minN}-${ngramRange.maxN}-Gramme`,
        },
        start: () => createNgramDiffJob({
          targetDocsetId,
          referenceDocsetId: action.payload.referenceDocsetId!,
          minN: ngramRange.minN,
          maxN: ngramRange.maxN,
          minFreq,
          limit,
          corpus,
        }),
      })
      return {
        success: true,
        data: {
          rows: rowsResponse.rows ?? [],
          n: ngramRange.n ?? ngramRange.minN,
          minN: ngramRange.minN,
          maxN: ngramRange.maxN,
          minFreq,
          rowLimit: rowsResponse.row_limit,
          totalCandidates: rowsResponse.total_candidates,
          totalRows: rowsResponse.total_rows,
          truncated: rowsResponse.truncated,
          method: (rowsResponse as { method?: unknown }).method,
          targetDocsetId,
          referenceDocsetId: action.payload.referenceDocsetId,
        },
        executionScope,
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return { success: false, error: t('actions.handlers.ngramContrastCancelled') }
      }
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/collocationContrast', async (action) => {
    const docsetStore = useDocsetStore()
    const queryStore = useQueryStore()
    const rawTerm = (action.payload.term ?? queryStore.term).trim()
    if (!rawTerm) {
      return { success: false, error: t('actions.handlers.collocationContrastTerm') }
    }
    const measure = String(action.payload.measure ?? 'logdice')
    if (measure === 'mi2') {
      return { success: false, error: t('actions.handlers.mi2Removed') }
    }

    const cqlfVisible = await ensureCqlfQueryVisible(rawTerm)
    if (!cqlfVisible.success) return cqlfVisible
    const cqlfFeatures = await ensureCqlfCorpusFeatures(rawTerm, action.payload.corpus ?? docsetStore.activeCorpus)
    if (!cqlfFeatures.success) return cqlfFeatures

    const tabResult = await switchAnalysisTab('contrast')
    if (!tabResult.success) return tabResult

    try {
      if (!action.payload.targetDocsetId && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, rawTerm)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.targetUpdateFailed') }
        }
      }

      const targetDocsetId = action.payload.targetDocsetId ?? docsetStore.activeDocsetId ?? undefined
      if (!targetDocsetId) {
        return {
          success: false,
          error: t('actions.handlers.collocationContrastTarget'),
        }
      }
      if (!action.payload.referenceDocsetId) {
        return {
          success: false,
          error: t('actions.handlers.collocationContrastReference'),
        }
      }

      const corpus = action.payload.corpus ?? docsetStore.activeCorpus
      const executionScope = executionScopeForApi(docsetStore, corpus, targetDocsetId)
      const limit = normalizeNgramLimit(action.payload.limit)
      const sortBy = measure === 'tscore' ? 't' : measure === 'logdice' ? 'logdice' : measure
      const analysisJobs = useAnalysisJobsStore()
      const { createCollocationContrastJob } = useContrastOperations()
      const rowsResponse = await analysisJobs.runJobRows<Record<string, unknown>>({
        scope: `collocates-diff:${corpus}`,
        kind: 'collocates_diff',
        corpus,
        rowsLimit: limit,
        queuedMessage: t('actions.handlers.collocationContrastStarted'),
        productOperation: {
          operationId: CONTRAST_OPERATIONS.collocationsDiffJob,
          surfaceId: 'analysis.contrast',
          label: t('actions.handlers.collocationContrastJob'),
          detail: rawTerm,
        },
        start: () => createCollocationContrastJob({
          term: rawTerm,
          targetDocsetId,
          referenceDocsetId: action.payload.referenceDocsetId!,
          window: action.payload.windowSize,
          withinSentence: action.payload.withinSentence ?? true,
          sortBy: sortBy as 'mi' | 'lmi' | 'npmi' | 'z' | 'chi2_cell' | 'dice' | 'logdice' | 't' | 'll' | 'f',
          limit,
          corpus,
        }),
      })
      return {
        success: true,
        data: {
          rows: rowsResponse.rows ?? [],
          measure,
          rowLimit: rowsResponse.row_limit,
          totalCandidates: rowsResponse.total_candidates,
          totalRows: rowsResponse.total_rows,
          truncated: rowsResponse.truncated,
          method: (rowsResponse as { method?: unknown }).method,
          targetDocsetId,
          referenceDocsetId: action.payload.referenceDocsetId,
        },
        executionScope,
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return { success: false, error: t('actions.handlers.collocationContrastCancelled') }
      }
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/freeContrast', async (action) => {
    const docsetStore = useDocsetStore()
    const queryStore = useQueryStore()
    const rawTerm = (action.payload.term ?? queryStore.term).trim()
    if (!rawTerm) {
      return { success: false, error: t('actions.handlers.freeContrastTerm') }
    }
    const measure = String(action.payload.measure ?? 'logdice')
    if (measure === 'mi2') {
      return { success: false, error: t('actions.handlers.mi2Removed') }
    }

    const cqlfVisible = await ensureCqlfQueryVisible(rawTerm)
    if (!cqlfVisible.success) return cqlfVisible
    const cqlfFeatures = await ensureCqlfCorpusFeatures(rawTerm, action.payload.corpus ?? docsetStore.activeCorpus)
    if (!cqlfFeatures.success) return cqlfFeatures

    const tabResult = await switchAnalysisTab('contrast')
    if (!tabResult.success) return tabResult

    try {
      const hasExplicitTarget = Boolean(action.payload.targetDocsetId || action.payload.targetSubcorpus)
      if (!hasExplicitTarget && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, rawTerm)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.targetUpdateFailed') }
        }
      }

      const targetDocsetId = action.payload.targetDocsetId
        ?? (!action.payload.targetSubcorpus ? docsetStore.activeDocsetId ?? undefined : undefined)
      const targetSubcorpus = action.payload.targetSubcorpus
      const referenceDocsetId = action.payload.referenceDocsetId
      const referenceSubcorpus = action.payload.referenceSubcorpus
      if (!targetDocsetId && !targetSubcorpus) {
        return {
          success: false,
          error: t('actions.handlers.freeContrastTarget'),
        }
      }
      if (!referenceDocsetId && !referenceSubcorpus) {
        return {
          success: false,
          error: t('actions.handlers.freeContrastReference'),
        }
      }

      const corpus = action.payload.corpus ?? docsetStore.activeCorpus
      const executionScope = executionScopeForApi(docsetStore, corpus, targetDocsetId)
      const limit = normalizeNgramLimit(action.payload.limit)
      const sortBy = measure === 'tscore' ? 't' : measure === 'logdice' ? 'logdice' : measure
      const analysisJobs = useAnalysisJobsStore()
      const { createFreeContrastJob } = useContrastOperations()
      const rowsResponse = await analysisJobs.runJobRows<Record<string, unknown>>({
        scope: `free-contrast:${corpus}`,
        kind: 'contrast',
        corpus,
        rowsLimit: limit,
        queuedMessage: t('actions.handlers.freeContrastStarted'),
        productOperation: {
          operationId: CONTRAST_OPERATIONS.freeJob,
          surfaceId: 'analysis.contrast',
          label: t('actions.handlers.freeContrastJob'),
          detail: rawTerm,
        },
        start: () => createFreeContrastJob({
          term: rawTerm,
          targetDocsetId,
          targetSubcorpus,
          referenceDocsetId,
          referenceSubcorpus,
          window: action.payload.windowSize,
          withinSentence: action.payload.withinSentence ?? true,
          sortBy: sortBy as 'mi' | 'lmi' | 'npmi' | 'z' | 'chi2_cell' | 'dice' | 'logdice' | 't' | 'll' | 'f',
          limit,
          corpus,
        }),
      })
      return {
        success: true,
        data: {
          rows: rowsResponse.rows ?? [],
          measure,
          rowLimit: rowsResponse.row_limit,
          totalCandidates: rowsResponse.total_candidates,
          totalRows: rowsResponse.total_rows,
          truncated: rowsResponse.truncated,
          method: (rowsResponse as { method?: unknown }).method,
          targetDocsetId,
          targetSubcorpus,
          referenceDocsetId,
          referenceSubcorpus,
        },
        executionScope,
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return { success: false, error: t('actions.handlers.freeContrastCancelled') }
      }
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/keyness', async (action) => {
    const docsetStore = useDocsetStore()
    const queryStore = useQueryStore()

    const tabResult = await switchAnalysisTab('keyness')
    if (!tabResult.success) return tabResult

    try {
      if (!action.payload.targetDocsetId && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, queryStore.term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.targetUpdateFailed') }
        }
      }

      const targetDocsetId = action.payload.targetDocsetId ?? docsetStore.activeDocsetId ?? undefined
      if (!targetDocsetId) {
        return {
          success: false,
          error: t('actions.handlers.keynessTarget'),
        }
      }

      const referenceSource = action.payload.referenceSource
        ?? (action.payload.referenceDocsetId ? 'docset' : undefined)
      if (!referenceSource) {
        return {
          success: false,
          error: t('actions.handlers.keynessReference'),
        }
      }
      if (referenceSource === 'docset' && !action.payload.referenceDocsetId) {
        return {
          success: false,
          error: t('actions.handlers.keynessDocsetReference'),
        }
      }
      if (referenceSource === 'corpus' && !action.payload.referenceCorpus) {
        return {
          success: false,
          error: t('actions.handlers.keynessCorpusReference'),
        }
      }
      const corpus = action.payload.corpus ?? docsetStore.activeCorpus
      const executionScope = executionScopeForApi(docsetStore, corpus, targetDocsetId)
      const rowsLimit = normalizeKeynessLimit(action.payload.limit)
      const minFreq = normalizePositiveInteger(action.payload.minFreq, 5)
      const analysisJobs = useAnalysisJobsStore()
      const { createKeynessAnalysisJob } = useKeynessOperations()
      const rowsResponse = await analysisJobs.runJobRows<Record<string, unknown>>({
        scope: `keyness:${corpus}`,
        kind: 'keyness',
        corpus,
        rowsLimit,
        queuedMessage: t('actions.handlers.keynessStarted'),
        productOperation: {
          operationId: KEYNESS_OPERATIONS.job,
          surfaceId: 'analysis.keyness',
          label: t('actions.handlers.keynessJob'),
          detail: referenceSource,
        },
        start: () => createKeynessAnalysisJob({
          targetDocsetId,
          referenceDocsetId: referenceSource === 'docset' ? action.payload.referenceDocsetId : undefined,
          pos: action.payload.pos,
          corpus,
          referenceSource,
          referenceCorpus: action.payload.referenceCorpus,
          minFreq,
        }),
      })
      return {
        success: true,
        data: {
          rows: rowsResponse.rows ?? [],
          rowLimit: rowsResponse.row_limit,
          totalCandidates: rowsResponse.total_candidates,
          totalRows: rowsResponse.total_rows,
          truncated: rowsResponse.truncated,
          method: (rowsResponse as { method?: unknown }).method,
          referenceSource,
          targetDocsetId,
          referenceDocsetId: action.payload.referenceDocsetId,
          minFreq,
        },
        executionScope,
      }
    } catch (error) {
      if (error instanceof Error && error.name === 'AbortError') {
        return { success: false, error: t('actions.handlers.keynessCancelled') }
      }
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/lexicalDiversity', async (action) => {
    const docsetStore = useDocsetStore()
    const queryStore = useQueryStore()

    const tabResult = await switchAnalysisTab('contrast')
    if (!tabResult.success) return tabResult

    try {
      const usesExplicitComparison = Boolean(action.payload.targetDocsetId || action.payload.referenceDocsetId)
      if (!usesExplicitComparison && !action.payload.docsetId && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, queryStore.term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }

      const corpus = action.payload.corpus ?? docsetStore.activeCorpus
      const docsetId = action.payload.docsetId
        ?? (!usesExplicitComparison && docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined)
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const { loadLexicalDiversity } = useContrastOperations()
      const result = await loadLexicalDiversity({
        corpus,
        docsetId,
        targetDocsetId: action.payload.targetDocsetId,
        referenceDocsetId: action.payload.referenceDocsetId,
        window: action.payload.window,
      })

      return { success: true, data: result, executionScope }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/wordSketch', async (action) => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    const term = (action.payload.term ?? queryStore.term).trim()

    if (!term) {
      return { success: false, error: t('actions.handlers.wordSketchTerm') }
    }

    const tabResult = await switchAnalysisTab('wordsketch')
    if (!tabResult.success) return tabResult

    try {
      if (!action.payload.docsetId && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }

      const corpus = action.payload.corpus ?? docsetStore.activeCorpus
      const docsetId = action.payload.docsetId
        ?? (docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined)
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const { loadWordSketch } = useWordSketchOperations()
      const result = await loadWordSketch({
        term,
        limit: action.payload.limit,
        corpus,
        docsetId,
      })

      return { success: true, data: result, executionScope }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/wordSketchDiff', async (action) => {
    const docsetStore = useDocsetStore()
    const termA = (action.payload.termA ?? '').trim()
    const termB = (action.payload.termB ?? '').trim()

    if (!termA || !termB) {
      return { success: false, error: t('actions.handlers.wordSketchDiffTerms') }
    }

    const tabResult = await switchAnalysisTab('wordsketch')
    if (!tabResult.success) return tabResult

    try {
      if (!action.payload.docsetId && docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, `${termA} ${termB}`)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }

      const corpus = action.payload.corpus ?? docsetStore.activeCorpus
      const docsetId = action.payload.docsetId
        ?? (docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined)
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const { loadWordSketchDiff } = useWordSketchOperations()
      const result = await loadWordSketchDiff({
        termA,
        termB,
        limit: action.payload.limit,
        corpus,
        docsetId,
      })

      return { success: true, data: result, executionScope }
    } catch (error) {
      return { success: false, error: error instanceof Error ? error.message : String(error) }
    }
  })

  actionBus.register('analysis/dispersion', async (action) => {
    const queryStore = useQueryStore()
    const settingsStore = useSettingsStore()
    const docsetStore = useDocsetStore()
    const { loadDispersion } = useDispersionOperations()

    const term = (action.payload.term ?? queryStore.term).trim()
    if (!term) {
      return { success: false, error: t('actions.handlers.noTerm') }
    }
    const cqlfVisible = await ensureCqlfQueryVisible(term)
    if (!cqlfVisible.success) return cqlfVisible
    const cqlfFeatures = await ensureCqlfCorpusFeatures(term, docsetStore.activeCorpus)
    if (!cqlfFeatures.success) return cqlfFeatures

    const tabResult = await switchAnalysisTab('dispersion')
    if (!tabResult.success) return tabResult

    try {
      if (docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, term)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }
      const corpus = docsetStore.activeCorpus
      const docsetId = docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const tokenCount = docsetStore.hasActiveDocset && docsetStore.stats.tokenCount > 0
        ? docsetStore.stats.tokenCount
        : settingsStore.systemInfo.tokenCount
      const result = await loadDispersion({
        term,
        partitions: action.payload.partitions,
        tokenCount,
        corpus,
        docsetId,
      })
      return { success: true, data: result, executionScope }
    } catch (error) {
      return { success: false, error: String(error) }
    }
  })

  actionBus.register('analysis/semantic', async (action) => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    const { loadSimilarWords, searchPassages } = useSemanticOperations()

    const query = (action.payload.query ?? queryStore.term).trim()
    if (!query) {
      return { success: false, error: t('actions.handlers.noQuery') }
    }
    const cqlfVisible = await ensureCqlfQueryVisible(query)
    if (!cqlfVisible.success) return cqlfVisible
    const cqlfFeatures = await ensureCqlfCorpusFeatures(query, docsetStore.activeCorpus)
    if (!cqlfFeatures.success) return cqlfFeatures

    const semanticMode = action.payload.mode === 'thesaurus' ? 'thesaurus' : 'passage'
    const corpusFeature = await ensureSemanticCorpusFeature(semanticMode)
    if (!corpusFeature.success) return corpusFeature
    const tabResult = await switchAnalysisTab('semantic')
    if (!tabResult.success) return tabResult

    try {
      if (docsetStore.hasActiveDocset && docsetStore.isDirty) {
        const rebuilt = await docsetStore.buildDocset(true, query)
        if (!rebuilt) {
          return { success: false, error: docsetStore.error ?? t('actions.handlers.subcorpusUpdateFailed') }
        }
      }
      const corpus = docsetStore.activeCorpus
      const docsetId = docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? undefined : undefined
      const executionScope = executionScopeForApi(docsetStore, corpus, docsetId)
      const result = semanticMode === 'thesaurus'
        ? await loadSimilarWords({
            term: query,
            k: action.payload.topK,
            corpus,
            docsetId,
          })
        : await searchPassages({
            query,
            top_k: action.payload.topK,
            corpus,
            docsetId,
          })
      return { success: true, data: result, executionScope }
    } catch (error) {
      return { success: false, error: String(error) }
    }
  })

  // ============================================
  // Bookmark Actions
  // ============================================

  actionBus.register('bookmark/add', async (action) => {
    const visible = await ensureProductCapabilityVisible('research.bookmarks', t('actions.handlers.bookmarks'))
    if (!visible.success) return visible

    const bookmarksStore = useBookmarksStore()
    const queryStore = useQueryStore()
    const uiStore = useUiStore()

    const payloadPositions = Array.isArray(action.payload.positions) ? action.payload.positions : []

    const selectedRows = payloadPositions.length > 0
      ? payloadPositions
      : Array.from(queryStore.selectedRows)

    const label = action.payload.label?.trim()
    const fallbackLabel = t('actions.handlers.bookmarkFallback', { date: formatDateTime(new Date()) })

    try {
      const bookmark = await bookmarksStore.add({
        name: label || fallbackLabel,
        query: queryStore.term,
        selectedRows,
        tab: uiStore.activeTab,
        notes: action.payload.color ? `color:${action.payload.color}` : ''
      })
      uiStore.showToast(t('actions.handlers.bookmarkSaved'), 'success', 2500)
      return { success: true, data: bookmark }
    } catch (error) {
      const message = error instanceof Error ? error.message : t('actions.handlers.bookmarkFailed')
      uiStore.showToast(message, 'error')
      return { success: false, error: message }
    }
  })

  actionBus.register('bookmark/remove', async (action) => {
    const visible = await ensureProductCapabilityVisible('research.bookmarks', t('actions.handlers.bookmarks'))
    if (!visible.success) return visible

    const bookmarksStore = useBookmarksStore()
    const uiStore = useUiStore()

    try {
      const removed = await bookmarksStore.remove(action.payload.id)
      if (removed) {
        uiStore.showToast(t('actions.handlers.bookmarkRemoved'), 'info', 2000)
        return { success: true }
      }
      return { success: false, error: t('actions.handlers.bookmarkNotFound') }
    } catch (error) {
      const message = error instanceof Error ? error.message : t('actions.handlers.bookmarkRemoveFailed')
      uiStore.showToast(message, 'error')
      return { success: false, error: message }
    }
  })

  actionBus.register('bookmark/clear', async () => {
    const visible = await ensureProductCapabilityVisible('research.bookmarks', t('actions.handlers.bookmarks'))
    if (!visible.success) return visible

    const bookmarksStore = useBookmarksStore()
    const uiStore = useUiStore()

    try {
      await bookmarksStore.clear()
      uiStore.showToast(t('actions.handlers.bookmarksCleared'), 'info', 2000)
      return { success: true }
    } catch (error) {
      const message = error instanceof Error ? error.message : t('actions.handlers.bookmarksClearFailed')
      uiStore.showToast(message, 'error')
      return { success: false, error: message }
    }
  })

  // ============================================
  // Export Actions
  // ============================================

  actionBus.register('export/data', async (action) => {
    const exportStore = useExportStore()

    try {
      const options = exportOptionsForAction(action.payload, exportStore.defaultOptions)
      const job = await exportStore.exportData(options)
      return { success: true, data: { job, format: options.format } }
    } catch (error) {
      const message = error instanceof Error ? error.message : t('actions.handlers.exportFailed')
      useUiStore().showToast(message, 'error')
      return { success: false, error: message }
    }
  })

  // ============================================
  // UI Actions
  // ============================================

  actionBus.register('ui/toast', async (action) => {
    const uiStore = useUiStore()
    uiStore.showToast(
      action.payload.message,
      action.payload.type,
      action.payload.duration
    )
    return { success: true }
  })

  actionBus.register('ui/setLoading', async (action) => {
    const uiStore = useUiStore()
    uiStore.setLoading(action.payload.key, action.payload.loading)
    return { success: true }
  })

  // ============================================
  // Middleware Registration (M2: Trace Recording)
  // ============================================

  // Source tracking middleware - set from dispatch context before policy/trace run.
  actionBus.use(async (_action, next, context) => {
    setCurrentActionSource(context.source)
    const result = await next()
    const source = result.source ?? context.source
    setCurrentActionSource(source)
    return result
  })

  // Trace recorder middleware for scientific reproducibility
  const traceMiddleware = createTraceRecorderMiddleware(
    () => {
      const docsetStore = useDocsetStore()
      const scopeEvidence = buildResearchScopeEvidence(docsetStore)
      const corpusId = scopeEvidence.corpus || 'default'
      const subcorpusHash = scopeEvidence.scopeHash

      return {
        corpusId,
        subcorpusHash,
        researchScope: {
          corpusId,
          scopeHash: scopeEvidence.scopeHash,
          scopeStatus: scopeEvidence.status,
          label: scopeEvidence.label,
          docsetId: scopeEvidence.docsetId,
          subcorpusName: docsetStore.activeSubcorpusName ?? undefined,
          queryHash: undefined,
          metadataSchemaHash: scopeEvidence.metadataSchemaHash,
        },
      }
    },
    () => {
      // Get query hash
      const queryStore = useQueryStore()
      if (!queryStore.term) return undefined

      return quickHash({
        term: queryStore.term,
        context: queryStore.contextSize,
        filters: queryStore.filters,
      })
    },
    (corpusId) => getMetaSchemaEvidenceForCorpus(corpusId)
  )

  actionBus.use(traceMiddleware)
  actionBus.use(createProductCapabilityGateMiddleware())
  actionBus.use(createPolicyGateMiddleware())

  debugLog('[ActionBus] All handlers and middlewares registered')
}
