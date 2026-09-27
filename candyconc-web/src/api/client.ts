/**
 * API Client - HTTP communication with FastAPI backend
 */

import ky from 'ky'
import type { z } from 'zod'
import {
  collocationSortKeyForMeasure,
  type CollocationMeasure,
  type CollocationSortKey,
} from '@/lib/collocationMeasure'
import { getAuthToken, waitForAuthBootstrap, withAuthHeadersReady } from './auth'
import { acceptLanguageHeader } from '@/i18n/locale'
import { rawSpacing, type TokenStarts } from '@/utils/sourceSpacing'
import {
  validateResponse,
  DocSnippetSchema,
  AlignmentRefDocResultSchema,
  CollocationsResponseSchema,
  CollocationNetworkResponseSchema,
  DocumentListSchema,
  DocumentSchema,
  FrequencyResponseSchema,
  NgramsResponseSchema,
  KeynessResponseSchema,
  SemanticSearchResponseSchema,
  SimilarWordsResponseSchema,
  AnnotationRecordSchema,
  AnnotationsResponseSchema,
  AnnotationSchemeSchema,
  AnnotationSchemePreviewSchema,
  ModelRouteSchema,
  PrefsStateSchema,
  SystemInfoSchema,
  DocsetFromSearchResultSchema,
  DocsetIntersectionResultSchema,
  ParallelGroupsResultSchema,
  ParallelKwicResultSchema,
  MetaCountsResponseSchema,
  MetaSchemaResponseSchema,
  MetaValuesResponseSchema,
  AnalysisJobSnapshotSchema,
  AnalysisJobStartSchema,
  AnalysisJobRowsSchema,
  ProductCapabilityContractSchema,
  McpToolsResponseSchema,
  AuthSessionSchema,
  AuthLoginResponseSchema,
  AuthLogoutResponseSchema,
  RebuildIndexResponseSchema,
  DispersionResultSchema,
  DispersionOffsetsResponseSchema,
  RawEmbeddingModelSchema,
  LocalSemanticIndexPreflightSchema,
  OperationRunLaunchResponseSchema,
  OperationRunSnapshotSchema,
  OperationRunStatusSchema,
  CorpusImportMethodsResponseSchema,
  CorpusImportPreflightResponseSchema,
  CorpusImportJobsResponseSchema,
  CorpusImportJobSchema,
  CorpusImportReportsResponseSchema,
  CorpusBuildReportSchema,
  AnalysisPresetSchema,
  AnalysisPresetsResponseSchema,
  TrendResponseSchema,
  type MetaSchemaResponse,
  type ProductCapabilityContract,
  type McpToolsResponse,
  type AuthSession,
  type AuthLoginResponse,
  type AuthLogoutResponse,
  type CorpusImportMethod,
  type CorpusImportPreflightResponse,
  type CorpusImportJob,
  type CorpusImportJobsResponse,
  type CorpusImportReportsResponse,
  type CorpusBuildReport,
  type RebuildIndexResponse,
  type ModelRoute,
} from './schemas'
import { t } from '@/i18n'

export type {
  ProductCapability,
  ProductCapabilityBackendRouteDescriptor,
  ProductCapabilityContract,
  ProductOperationLifecycle,
  ProductCapabilityOperation,
  McpToolStatus,
  McpToolRuntime,
  McpToolsResponse,
  AuthSession,
  AuthLoginResponse,
  AuthLogoutResponse,
  CorpusImportMethod,
  CorpusImportPreflightCheck,
  CorpusImportPreflightEvidence,
  CorpusImportPreflightResponse,
  CorpusImportOptionChoice,
  CorpusImportOptionSpec,
  CorpusImportInputSpec,
  CorpusImportColumnSpec,
  CorpusImportOutputSpec,
  CorpusImportReportSpec,
  CorpusImportJob,
  CorpusImportJobsResponse,
  CorpusImportReports,
  CorpusImportReportsResponse,
  CorpusBuildReport,
  RebuildIndexResponse,
  ModelRoute,
} from './schemas'

const API_PREFIX_URL = typeof window !== 'undefined' && window.location?.origin
  ? new URL('/api/v1', window.location.origin).toString()
  : 'http://localhost/api/v1'

// API Base Configuration
export const api = ky.create({
  prefixUrl: API_PREFIX_URL,
  timeout: 30000,
  hooks: {
    beforeRequest: [
      async (request) => {
        await waitForAuthBootstrap()
        request.headers.set('Accept-Language', acceptLanguageHeader())
        const token = getAuthToken()
        if (token) {
          request.headers.set('Authorization', `Bearer ${token}`)
        }
      }
    ],
    afterResponse: [
      async (_request, _options, response) => {
        if (!response.ok) {
          // Expected, user-actionable states — auth (401/403) and rate-limit
          // (429) — are surfaced to the user via translateHttpError; logging them
          // as errors floods the console on every unauthenticated page load and
          // can mask real failures. Keep loud logging only for genuinely
          // unexpected statuses.
          const expected =
            response.status === 401 || response.status === 403 || response.status === 409 || response.status === 429
          if (!expected) {
            // Clone so the body stays readable for HTTPError consumers downstream.
            const body = await response.clone().json().catch(() => ({}))
            console.error('[API Error]', response.status, body)
          } else if (import.meta.env?.DEV) {
            console.debug('[API]', response.status, response.url)
          }
        }
        return response
      }
    ]
  }
})

const longRunningApi = api.extend({
  timeout: 120000,
})

const presetApi = api.extend({
  timeout: 180000,
})


export interface NotApplicableEnvelope {
  status: 'not_applicable'
  reason?: string
  feature?: string
  detail?: string
}

export class NotApplicableError extends Error {
  readonly envelope: NotApplicableEnvelope

  constructor(envelope: NotApplicableEnvelope, endpoint: string) {
    super(envelope.detail || t('errors.client.notApplicable', { endpoint }))
    this.name = 'NotApplicableError'
    this.envelope = envelope
  }
}

function isAbortError(error: unknown): boolean {
  return Boolean(error && typeof error === 'object' && 'name' in error && error.name === 'AbortError')
}

function responseStatus(error: unknown): number | null {
  const response = (error as { response?: unknown } | null)?.response
  if (response instanceof Response) return response.status
  if (
    response &&
    typeof response === 'object' &&
    'status' in response &&
    typeof response.status === 'number'
  ) {
    return response.status
  }
  return null
}

export function isLegacyEndpointUnavailable(error: unknown): boolean {
  const status = responseStatus(error)
  return status === 404 || status === 501
}

/**
 * Paired-only analysis endpoints return a graceful
 * `{ status: "not_applicable", reason: "corpus_not_paired", ... }` envelope
 * (HTTP 200) when invoked against an unpaired corpus. Treat this as a typed
 * non-success so UI callers do not mistake a guard response for "keine Daten".
 */
function notApplicableEnvelope(data: unknown): NotApplicableEnvelope | null {
  if (
    typeof data !== 'object' ||
    data === null ||
    (data as { status?: unknown }).status !== 'not_applicable'
  ) {
    return null
  }
  const raw = data as Record<string, unknown>
  return {
    status: 'not_applicable',
    reason: typeof raw.reason === 'string' ? raw.reason : undefined,
    feature: typeof raw.feature === 'string' ? raw.feature : undefined,
    detail: typeof raw.detail === 'string' ? raw.detail : undefined,
  }
}

function throwIfNotApplicable(data: unknown, endpoint: string): void {
  const envelope = notApplicableEnvelope(data)
  if (envelope) {
    throw new NotApplicableError(envelope, endpoint)
  }
}

// ============================================
// Query API
// ============================================

/**
 * Sort field for KWIC results, matching the backend `sort_by` contract:
 * `1L`/`2L`/`3L` (left context, AntConc convention), `node` (the match),
 * `1R`/`2R`/`3R` (right context), or `meta:FIELD` (e.g. `meta:source`).
 * `'position'` / undefined means the default unsorted order.
 */
export type QuerySortBy = '1L' | '2L' | '3L' | 'node' | '1R' | '2R' | '3R' | 'position' | (string & {})
export type QuerySortDir = 'asc' | 'desc'

export interface QueryParams {
  term: string
  context?: number
  corpus?: string
  date?: string
  genre?: string
  offset?: number
  limit?: number
  sortBy?: QuerySortBy | null
  sortDir?: QuerySortDir
  /**
   * Case-insensitive matching. CONTRACT (Track D8): the backend
   * query/count/stream + export endpoints accept a `caseInsensitive` boolean
   * and default to case-INsensitive when omitted. Callers send
   * `caseInsensitive = !caseSensitive`.
   */
  caseInsensitive?: boolean
  /**
   * Zufallsstichprobe (Thinning, T1): uniforme Stichprobe ohne Zurücklegen der
   * Größe min(sample, Treffermenge) über die GESAMTE Treffermenge; Sortierung
   * und Paging operieren danach auf der Stichprobe. Backend-Cap: 10000.
   */
  sample?: number
  /**
   * Deterministischer RNG-Seed (>= 0). PFLICHT, sobald `sample` gesetzt ist —
   * das Backend antwortet sonst mit 422 (Reproduzierbarkeitskontrakt, kein
   * impliziter Zufalls-Seed).
   */
  seed?: number
}

/**
 * Provenienz einer KWIC-Zufallsstichprobe, gespiegelt aus dem
 * `X-CandyConc-Sample`-Header von GET /query bzw. dem `done.sample`-Block des
 * Streams: {requested, drawn, seed, population, population_partial}.
 */
export interface KwicSampleProvenance {
  requested: number
  drawn: number
  seed: number
  population: number
  populationPartial: boolean
}

/**
 * Normalize a raw provenance object (`X-CandyConc-Sample` header payload or the
 * stream's `done.sample` block) into {@link KwicSampleProvenance}; null when the
 * value is absent or malformed. Never fabricates fields.
 */
export function coerceSampleProvenance(value: unknown): KwicSampleProvenance | null {
  if (!value || typeof value !== 'object') return null
  const data = value as Record<string, unknown>
  const num = (raw: unknown): number | null =>
    typeof raw === 'number' && Number.isFinite(raw) ? raw : null
  const requested = num(data.requested)
  const drawn = num(data.drawn)
  const seed = num(data.seed)
  const population = num(data.population)
  if (requested === null || drawn === null || seed === null || population === null) return null
  return {
    requested,
    drawn,
    seed,
    population,
    populationPartial: Boolean(data.population_partial),
  }
}

/** Parse the compact JSON `X-CandyConc-Sample` header (null when absent/invalid). */
export function parseSampleProvenanceHeader(raw: string | null): KwicSampleProvenance | null {
  if (!raw) return null
  try {
    return coerceSampleProvenance(JSON.parse(raw))
  } catch {
    return null
  }
}

export interface QueryResult {
  hits: Array<{
    position: number
    left: string
    match: string
    right: string
    doc_id: string
    doc_title?: string
    metadata?: Record<string, string>
    collocate_offsets?: number[]
    match_offsets?: number[]
    /** Rows with the original spacing of the corpus (utils/sourceSpacing.ts). */
    token_starts?: TokenStarts
    ws_before_kw?: boolean
    ws_after_kw?: boolean
  }>
  total: number
  query_time_ms: number
  next_offset?: number | null
  backendQueryTraceId?: string
  /** Backend window was truncated (X-CandyConc-Truncated): more matches exist beyond `total`. */
  truncated?: boolean
  /** Sort order covers only a bounded prefix of the match set (X-CandyConc-Sort-Approximate). */
  sortApproximate?: boolean
  /** Stichproben-Provenienz (X-CandyConc-Sample), nur bei sample+seed gesetzt. */
  sample?: KwicSampleProvenance | null
  /** Co-KWIC only: what a row is and the collocate tokens (O11) behind it. */
  coKwic?: CoKwicCounts | null
}

/**
 * Counting provenance of a Co-KWIC answer. A row is a node hit with the
 * collocate in its window. `collocateTokens` counts collocate tokens in the
 * union of all node windows, the O11 of the collocation row.
 */
export interface CoKwicCounts {
  rowUnit: string
  nodeHits: number | null
  collocateTokens: Record<string, number>
  attribute: 'word' | 'lemma'
  window: number | null
  withinSentence: boolean | null
}

export async function executeQuery(params: QueryParams): Promise<QueryResult> {
  const start = performance.now()
  const searchParams: Record<string, string | number> = { term: params.term }
  // Backend expects `ctx` instead of `context`
  if (params.context !== undefined) searchParams.ctx = params.context
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.date) searchParams.date = params.date
  if (params.genre) searchParams.genre = params.genre
  if (params.offset !== undefined) searchParams.offset = Math.max(0, params.offset)
  if (params.limit !== undefined) searchParams.limit = Math.max(1, params.limit)
  if (params.sortBy && params.sortBy !== 'position') searchParams.sort_by = params.sortBy
  if (params.sortDir) searchParams.sort_dir = params.sortDir
  if (params.caseInsensitive !== undefined) searchParams.case_insensitive = params.caseInsensitive ? 'true' : 'false'
  if (params.sample !== undefined) searchParams.sample = params.sample
  if (params.seed !== undefined) searchParams.seed = params.seed
  const response = await api.get('query', { searchParams })
  const backendQueryTraceId = response.headers.get('X-CandyConc-Query-Trace-Id') ?? undefined
  const truncated = response.headers.get('X-CandyConc-Truncated') === 'true'
  const sortApproximate = response.headers.get('X-CandyConc-Sort-Approximate') === 'true'
  const sampleProvenance = parseSampleProvenanceHeader(response.headers.get('X-CandyConc-Sample'))
  const nextOffsetHeader = response.headers.get('X-CandyConc-Next-Offset')
  const next_offset = nextOffsetHeader !== null && nextOffsetHeader !== ''
    ? Number(nextOffsetHeader)
    : null
  const totalHeader = response.headers.get('X-CandyConc-Total')
  const backendTotal = totalHeader !== null && totalHeader !== ''
    ? Number(totalHeader)
    : null
  const rows = await response.json<Array<{
    left: string
    kw: string
    right: string
    pos?: number
    doc_id?: number | string
    doc?: string
    meta?: Record<string, unknown>
  }>>()

  const offset = params.offset ?? 0
  const total = typeof backendTotal === 'number' && Number.isFinite(backendTotal)
    ? backendTotal
    : offset + rows.length

  const hits = rows.map((row, idx) => {
    const rowAny = row as Record<string, unknown>
    const matchOffsets = Array.isArray(rowAny.match_offsets)
      ? (rowAny.match_offsets as unknown[])
          .map((val) => Number(val))
          .filter((val) => Number.isFinite(val))
      : undefined
    return {
      position: row.pos ?? offset + idx,
      left: row.left,
      // `match` holds the node token (`kw`). The other tokens of the hit are
      // in `match_offsets`, lib/kwicCitation.ts `kwicHitSpan` joins them.
      match: row.kw,
      right: row.right,
      doc_id: row.doc_id !== undefined ? String(row.doc_id) : 'unknown',
      doc_title: row.doc,
      metadata: row.meta as Record<string, string> | undefined,
      match_offsets: matchOffsets,
      ...rawSpacing(rowAny),
    }
  })

  const query_time_ms = Math.round(performance.now() - start)

  return {
    hits,
    total,
    query_time_ms,
    next_offset: Number.isFinite(next_offset) ? next_offset : null,
    backendQueryTraceId,
    truncated,
    sortApproximate,
    sample: sampleProvenance,
  }
}

// ============================================
// Sampled KWIC (Thinning, T1)
// ============================================

/** Page size for collecting a full sample (backend hard-caps GET /query at 5000). */
const SAMPLED_KWIC_PAGE_LIMIT = 1000

/**
 * Collect the COMPLETE drawn sample for a sampled KWIC request by paging
 * GET /query until the backend reports no further offset. The sample itself is
 * bounded (backend cap 10000), so this terminates after a handful of pages.
 *
 * `runPage` defaults to {@link executeQuery} and is injectable so callers can
 * route each page through their product-operation gate (and tests through a
 * fake) without re-implementing the paging loop.
 */
export async function executeSampledQuery(
  params: QueryParams,
  runPage: (pageParams: QueryParams) => Promise<QueryResult> = executeQuery,
): Promise<QueryResult> {
  if (typeof params.sample !== 'number' || params.sample <= 0) {
    throw new Error(t('errors.client.sampleSize'))
  }
  if (typeof params.seed !== 'number' || params.seed < 0) {
    throw new Error(t('errors.client.sampleSeed'))
  }
  const pageLimit = Math.max(1, Math.min(params.limit ?? SAMPLED_KWIC_PAGE_LIMIT, SAMPLED_KWIC_PAGE_LIMIT))
  const hits: QueryResult['hits'] = []
  let sample: KwicSampleProvenance | null = null
  let backendQueryTraceId: string | undefined
  let queryTimeMs = 0
  let offset = 0
  // The drawn sample is capped at 10000; loop guard mirrors that bound.
  for (let page = 0; page < 32; page += 1) {
    const result = await runPage({ ...params, offset, limit: pageLimit })
    hits.push(...result.hits)
    queryTimeMs += result.query_time_ms ?? 0
    if (!sample) sample = result.sample ?? null
    if (!backendQueryTraceId) backendQueryTraceId = result.backendQueryTraceId
    const nextOffset = result.next_offset
    if (nextOffset === null || nextOffset === undefined || nextOffset <= offset) break
    offset = nextOffset
  }
  return {
    hits,
    total: sample?.drawn ?? hits.length,
    query_time_ms: queryTimeMs,
    next_offset: null,
    backendQueryTraceId,
    // The full drawn sample is loaded — the RESULT SET (the sample) is complete.
    truncated: false,
    sortApproximate: false,
    sample,
  }
}

// ============================================
// Streaming Query API
// ============================================

// NOTE: deliberately no sortBy/sortDir here — the stream endpoint rejects
// sort_by with 400 (sorting requires a full scan before the first event).
// Sorted KWIC requests must go through `executeQuery` (GET /query) instead.
export interface StreamingQueryParams {
  term: string
  context?: number
  corpus?: string
  docsetId?: string
  date?: string
  genre?: string
  batchSize?: number
  limit?: number
  offset?: number
  /** Case-insensitive matching (default insensitive); see {@link QueryParams.caseInsensitive}. */
  caseInsensitive?: boolean
  /**
   * Zufallsstichprobe (Thinning, T1): der Stream spiegelt die sample/seed-
   * Parameter von GET /query. Anders als GET ist der Stream docset-fähig; die
   * Provenienz kommt im `done`-Event unter `sample`.
   */
  sample?: number
  /** Deterministischer RNG-Seed (Pflicht, sobald `sample` gesetzt ist; sonst 422). */
  seed?: number
}

export interface QueryCountParams {
  term: string
  context?: number
  corpus?: string
  docsetId?: string
  date?: string
  genre?: string
  waitMs?: number
  start?: boolean
  /** Case-insensitive matching (default insensitive); see {@link QueryParams.caseInsensitive}. */
  caseInsensitive?: boolean
}

export interface QueryCountResult {
  status: 'ready' | 'running' | 'missing' | 'error'
  total?: number
  partial?: boolean
  elapsed_ms?: number
  message?: string
}

export interface QueryHit {
  position: number
  left: string
  match: string
  right: string
  doc_id: string
  doc_title?: string
  metadata?: Record<string, string>
  collocate_offsets?: number[]
  match_offsets?: number[]
  /** Rows with the original spacing of the corpus (utils/sourceSpacing.ts). */
  token_starts?: TokenStarts
  ws_before_kw?: boolean
  ws_after_kw?: boolean
}

export interface QueryStreamEvent {
  type: 'batch' | 'progress' | 'done' | 'count' | 'error'
  hits?: QueryHit[]
  count?: number
  total?: number
  partial?: boolean
  /** Backend window was truncated: more matches exist beyond the streamed page. */
  truncated?: boolean
  next_offset?: number | null
  elapsed_ms?: number
  query_time_ms?: number
  backendQueryTraceId?: string
  error?: string
  /** Stichproben-Provenienz des `done`-Events (nur bei sample+seed gesetzt). */
  sample?: KwicSampleProvenance | null
}

/**
 * Execute a streaming query using Server-Sent Events.
 * Results are delivered progressively in batches.
 *
 * @example
 * ```ts
 * const controller = new AbortController()
 * for await (const event of executeQueryStreaming({ term: 'Klimawandel' }, controller.signal)) {
 *   if (event.type === 'batch') {
 *     // Add hits to display
 *     addHits(event.hits)
 *   } else if (event.type === 'progress') {
 *     // Update progress indicator
 *     setProgress(event.count)
 *   } else if (event.type === 'done') {
 *     // Query complete
 *     setTotal(event.total)
 *   }
 * }
 * ```
 */
export async function* executeQueryStreaming(
  params: StreamingQueryParams,
  signal?: AbortSignal
): AsyncGenerator<QueryStreamEvent, void, unknown> {
  const searchParams = new URLSearchParams()
  searchParams.set('term', params.term)
  if (params.context !== undefined) searchParams.set('ctx', String(params.context))
  if (params.corpus) searchParams.set('corpus', params.corpus)
  if (params.docsetId) searchParams.set('docset_id', params.docsetId)
  if (params.date) searchParams.set('date', params.date)
  if (params.genre) searchParams.set('genre', params.genre)
  if (params.batchSize) searchParams.set('batch_size', String(params.batchSize))
  if (params.limit !== undefined) searchParams.set('limit', String(params.limit))
  if (params.offset !== undefined) searchParams.set('offset', String(params.offset))
  if (params.caseInsensitive !== undefined) {
    searchParams.set('case_insensitive', params.caseInsensitive ? 'true' : 'false')
  }
  if (params.sample !== undefined) searchParams.set('sample', String(params.sample))
  if (params.seed !== undefined) searchParams.set('seed', String(params.seed))

  const url = `/api/v1/query/stream?${searchParams.toString()}`

  const response = await fetch(url, {
    method: 'GET',
    headers: await withAuthHeadersReady({
      'Accept': 'text/event-stream',
    }),
    signal,
  })

  if (!response.ok) {
    const detail = await errorDetailFromFetchResponse(response)
    yield {
      type: 'error',
      error: detail ?? `HTTP ${response.status}: ${response.statusText}`,
    }
    return
  }
  const backendQueryTraceIdFromHeader = response.headers.get('X-CandyConc-Query-Trace-Id') ?? undefined

  const reader = response.body?.getReader()
  if (!reader) {
    yield { type: 'error', error: 'No response body' }
    return
  }

  const decoder = new TextDecoder()
  let buffer = ''
  let currentEvent: string | null = null
  let currentDataLines: string[] = []

  const flushEvent = () => {
    if (currentDataLines.length === 0) {
      currentEvent = null
      return null
    }
    let parsedEvent: QueryStreamEvent | null = null
    try {
      const data = JSON.parse(currentDataLines.join('\n'))
      const eventType = currentEvent ?? 'batch'

      if (eventType === 'batch' && Array.isArray(data)) {
        // Transform raw rows to QueryHit format
        const hits: QueryHit[] = data.map((row: {
          left: string
          kw: string
          right: string
          pos?: number
          doc_id?: number | string
          doc?: string
          meta?: Record<string, unknown>
          match_offsets?: unknown
          token_starts?: unknown
          ws_before_kw?: unknown
          ws_after_kw?: unknown
        }, idx: number) => ({
          position: row.pos ?? idx,
          left: row.left,
          // The node token. The whole hit follows from `match_offsets` (kwicHitSpan).
          match: row.kw,
          right: row.right,
          doc_id: row.doc_id !== undefined ? String(row.doc_id) : 'unknown',
          doc_title: row.doc,
          metadata: row.meta as Record<string, string> | undefined,
          match_offsets: Array.isArray(row.match_offsets)
            ? row.match_offsets.map((val) => Number(val)).filter((val) => Number.isFinite(val))
            : undefined,
          ...rawSpacing(row),
        }))

        parsedEvent = { type: 'batch', hits }
      } else if (eventType === 'progress') {
        parsedEvent = {
          type: 'progress',
          count: data.count,
          elapsed_ms: data.elapsed_ms,
        }
      } else if (eventType === 'done') {
        const doneEvent: QueryStreamEvent = {
          type: 'done',
          total: data.total,
          partial: data.partial ?? false,
          truncated: data.truncated ?? false,
          next_offset: data.next_offset ?? null,
          query_time_ms: data.query_time_ms,
        }
        const backendQueryTraceId = readOptionalString(data.queryTraceId)
          ?? readOptionalString(data.query_trace_id)
          ?? backendQueryTraceIdFromHeader
        if (backendQueryTraceId) doneEvent.backendQueryTraceId = backendQueryTraceId
        // Sampled streams carry the drawn-sample provenance on done.sample.
        const sampleProvenance = coerceSampleProvenance(data.sample)
        if (sampleProvenance) doneEvent.sample = sampleProvenance
        parsedEvent = doneEvent
      } else if (eventType === 'count') {
        parsedEvent = {
          type: 'count',
          total: data.total,
          elapsed_ms: data.elapsed_ms,
          partial: data.partial ?? false,
        }
      } else if (eventType === 'error') {
        parsedEvent = {
          type: 'error',
          error: data.message ?? 'Unknown error',
        }
      }
    } catch (parseError) {
      console.warn('[QueryStream] Failed to parse event data:', parseError)
    }

    currentEvent = null
    currentDataLines = []
    return parsedEvent
  }

  try {
    while (true) {
      const { done, value } = await reader.read()

      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Parse SSE events from buffer
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? '' // Keep incomplete line in buffer

      for (const rawLine of lines) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          let dataLine = line.slice(5)
          if (dataLine.startsWith(' ')) dataLine = dataLine.slice(1)
          currentDataLines.push(dataLine)
        } else if (line.startsWith(':')) {
          continue
        } else if (line === '') {
          // Empty line = end of event
          const parsedEvent = flushEvent()
          if (parsedEvent) {
            yield parsedEvent
          }
        }
      }
    }

    if (buffer.length) {
      const trailingLines = buffer.split('\n')
      for (const rawLine of trailingLines) {
        const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
        if (line.startsWith('event:')) {
          currentEvent = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          let dataLine = line.slice(5)
          if (dataLine.startsWith(' ')) dataLine = dataLine.slice(1)
          currentDataLines.push(dataLine)
        }
      }
    }
    if (currentDataLines.length) {
      const parsedEvent = flushEvent()
      if (parsedEvent) {
        yield parsedEvent
      }
    }
  } finally {
    reader.releaseLock()
  }
}

export async function getQueryCount(params: QueryCountParams): Promise<QueryCountResult> {
  const searchParams: Record<string, string | number | boolean> = { term: params.term }
  if (params.context !== undefined) searchParams.ctx = params.context
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  if (params.date) searchParams.date = params.date
  if (params.genre) searchParams.genre = params.genre
  if (params.waitMs !== undefined) searchParams.wait_ms = params.waitMs
  if (params.start !== undefined) searchParams.start = params.start
  if (params.caseInsensitive !== undefined) searchParams.case_insensitive = params.caseInsensitive
  return api.get('query/count', { searchParams }).json<QueryCountResult>()
}

/**
 * Helper to collect all streaming results into a single QueryResult.
 * Useful for backwards compatibility or when you need all results at once.
 */
export async function executeQueryStreamingToResult(
  params: StreamingQueryParams,
  signal?: AbortSignal
): Promise<QueryResult> {
  const allHits: QueryHit[] = []
  let total = 0
  let queryTimeMs = 0
  let backendQueryTraceId: string | undefined

  for await (const event of executeQueryStreaming(params, signal)) {
    if (event.type === 'batch' && event.hits) {
      allHits.push(...event.hits)
    } else if (event.type === 'done') {
      total = event.total ?? allHits.length
      queryTimeMs = event.query_time_ms ?? 0
      backendQueryTraceId = event.backendQueryTraceId
    } else if (event.type === 'error') {
      throw new Error(event.error)
    }
  }

  return {
    hits: allHits,
    total,
    query_time_ms: queryTimeMs,
    backendQueryTraceId,
  }
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

async function errorDetailFromFetchResponse(response: Response): Promise<string | null> {
  try {
    const body = await response.clone().json() as {
      detail?: unknown
      message?: unknown
    }
    if (typeof body.detail === 'string' && body.detail.trim()) {
      return body.detail.trim()
    }
    if (body.detail && typeof body.detail === 'object') {
      const nested = (body.detail as { message?: unknown }).message
      if (typeof nested === 'string' && nested.trim()) {
        return nested.trim()
      }
    }
    if (typeof body.message === 'string' && body.message.trim()) {
      return body.message.trim()
    }
  } catch {
    // Non-JSON or already-consumed bodies fall back to status text.
  }
  return null
}

export type SuggestionKind = 'fix' | 'complete' | 'history'

export interface SuggestionItem {
  text: string
  hint?: string
  hasPlaceholders?: boolean
  kind?: SuggestionKind
}

export interface QueryAnalysisResult {
  errors: string[]
  warnings: string[]
  diagnostics: Array<{
    severity: 'error' | 'warning' | 'info' | string
    message: string
    start: number
    end: number
    fixes?: Array<{
      label: string
      start: number
      end: number
      replacement: string
    }>
  }>
  suggestions: SuggestionItem[]
  hints: string[]
  kinds: string[]
  spans: Array<[number, number]>
  builder?: unknown | null
}

export async function getLexiconSuggestions(
  attr: string,
  prefix: string,
  limit = 20,
  signal?: AbortSignal,
  corpus?: string
): Promise<string[]> {
  const payload: Record<string, string | number> = { attr, prefix, limit }
  if (corpus) payload.corpus = corpus
  const response = await api.post('query/lexicon/suggest', {
    json: payload,
    signal,
  }).json<{ values?: string[] }>()
  return response.values ?? []
}

export async function getSuggestions(term: string, signal?: AbortSignal, corpus?: string): Promise<SuggestionItem[]> {
  const analysis = await analyseQuery(term, signal, corpus)
  return analysis.suggestions
}

export async function analyseQuery(term: string, signal?: AbortSignal, corpus?: string): Promise<QueryAnalysisResult> {
  const trimmed = term.trim()
  if (!trimmed || trimmed.length < 2) {
    return {
      errors: [],
      warnings: [],
      diagnostics: [],
      suggestions: [],
      hints: [],
      kinds: [],
      spans: [],
      builder: null,
    }
  }
  if (!trimmed.toLowerCase().startsWith('cql:')) {
    return {
      errors: [],
      warnings: [],
      diagnostics: [],
      suggestions: [],
      hints: [],
      kinds: [],
      spans: [],
      builder: null,
    }
  }
  const payload: Record<string, string> = { query: trimmed }
  if (corpus) payload.corpus = corpus
  const response = await api.post('query/analyse', { json: payload, signal }).json<{
    errors?: string[]
    warnings?: string[]
    diagnostics?: QueryAnalysisResult['diagnostics']
    suggestions: string[]
    hints?: string[]
    kinds?: string[]
    spans?: Array<[number, number]>
    builder?: unknown | null
  }>()
  const suggestions = response.suggestions ?? []
  const hints = response.hints ?? []
  const kinds = response.kinds ?? []
  const seen = new Set<string>()
  const items: SuggestionItem[] = []
  suggestions.forEach((suggestion, index) => {
    const text = suggestion.trim()
    if (!text) return
    if (/within\([^,]+,\s*\)/.test(text)) return
    if (/^\s*\|/.test(text) || /\|\s*$/.test(text)) return
    if (seen.has(text)) return
    seen.add(text)
    const hasPlaceholders = /\$\d+/.test(text)
    const hint = hints[index]
    const rawKind = kinds[index]?.toLowerCase()
    const kind: SuggestionKind | undefined =
      rawKind === 'fix' ? 'fix' : rawKind === 'complete' ? 'complete' : undefined
    items.push({
      text,
      hint,
      hasPlaceholders,
      kind,
    })
  })
  return {
    errors: response.errors ?? [],
    warnings: response.warnings ?? [],
    diagnostics: response.diagnostics ?? [],
    suggestions: items,
    hints,
    kinds,
    spans: response.spans ?? [],
    builder: response.builder ?? null,
  }
}

export interface DocSnippetParams {
  pos: number
  ctx?: number
  corpus?: string
}

export interface DocSnippet {
  doc_id: number
  doc: string
  meta: Record<string, string>
  pos: number
  ctx: number
  doc_start: number
  doc_end: number
  start_pos: number
  end_pos: number
  left: string
  kw: string
  right: string
  text: string
}

export async function getDocSnippet(params: DocSnippetParams): Promise<DocSnippet> {
  const searchParams: Record<string, string | number> = { pos: params.pos }
  if (params.ctx !== undefined) searchParams.ctx = params.ctx
  if (params.corpus) searchParams.corpus = params.corpus
  const data = await api.get('doc/snippet', { searchParams }).json()
  return validateResponse(DocSnippetSchema, data, 'doc/snippet')
}

export interface AlignmentRefDocParams {
  refDoc: number
  corpus?: string
  focusPos?: number
  windowSentences?: number
  variantMargin?: number
  includeModels?: string[]
  /** Restrict the comparison to concrete variant document IDs. */
  includeDocIds?: number[]
  maxVariants?: number
  maxTokens?: number
}

export interface AlignmentSentence {
  index: number
  start_pos: number
  end_pos: number
  text: string
  token_count: number
}

export interface AlignmentReference {
  doc_id: number
  doc: string
  meta: Record<string, string>
  sentence_count: number
  window_start: number
  window_end: number
  focus_sentence_index: number | null
  sentences: AlignmentSentence[]
}

export interface AlignmentPair {
  ref_index: number | null
  var_index: number | null
  ref_text: string
  var_text: string
  ref_start: number | null
  ref_end: number | null
  var_start: number | null
  var_end: number | null
  med: number | null
  similarity: number | null
  norm_med: number | null
}

export interface AlignmentSummary {
  alignment_cost: number
  aligned_pairs: number
  avg_med: number | null
  avg_similarity: number | null
}

export interface AlignmentVariant {
  doc_id: number
  doc: string
  meta: Record<string, string>
  model: string
  axis?: string
  axis_value?: string
  label?: string
  text_type: string
  sentence_count: number
  window_start: number
  window_end: number
  summary: AlignmentSummary
  pairs: AlignmentPair[]
}

export interface AlignmentRefDocResult {
  ref_doc: number
  corpus: string
  focus_pos: number | null
  focus_doc_id: number | null
  focus_resolution?: 'not_requested' | 'reference_sentence' | 'variant_sentence_resolved'
  /** The backend aligned complete documents before returning this display window. */
  alignment_scope?: 'complete_document'
  /** Minimum lexical similarity required for a displayed sentence counterpart. */
  confidence_threshold?: number
  reference: AlignmentReference
  variants: AlignmentVariant[]
  variant_count: number
}

export async function getAlignmentRefDoc(params: AlignmentRefDocParams): Promise<AlignmentRefDocResult> {
  const payload: Record<string, unknown> = {
    ref_doc: params.refDoc,
    corpus: params.corpus ?? 'default',
  }
  if (params.focusPos !== undefined) payload.focus_pos = params.focusPos
  if (params.windowSentences !== undefined) payload.window_sentences = params.windowSentences
  if (params.variantMargin !== undefined) payload.variant_margin = params.variantMargin
  if (params.includeModels && params.includeModels.length > 0) payload.include_models = params.includeModels
  if (params.includeDocIds && params.includeDocIds.length > 0) payload.include_doc_ids = params.includeDocIds
  if (params.maxVariants !== undefined) payload.max_variants = params.maxVariants
  if (params.maxTokens !== undefined) payload.max_tokens = params.maxTokens
  const data = await api.post('analysis/alignment/ref_doc', { json: payload }).json()
  throwIfNotApplicable(data, 'analysis/alignment/ref_doc')
  return validateResponse(AlignmentRefDocResultSchema, data, 'analysis/alignment/ref_doc')
}

export interface ParallelKwicParams {
  pos: number
  keyword?: string
  ctx?: number
  corpus?: string
  includeModels?: string[]
  maxVariants?: number
  sentenceMargin?: number
  excludeBase?: boolean
}

export interface ParallelKwicVariant {
  doc_id: number
  model: string
  axis?: string
  axis_value?: string
  label?: string
  prompting_method?: string
  text_type: string
  left: string
  kw: string
  right: string
  matched: boolean
  med: number | null
  norm_med: number | null
  similarity: number | null
}

export interface ParallelKwicResult {
  ref_doc: number
  base_doc_id: number
  variants: ParallelKwicVariant[]
}

export async function getParallelKwic(params: ParallelKwicParams): Promise<ParallelKwicResult> {
  const payload: Record<string, unknown> = {
    pos: params.pos,
  }
  if (params.keyword) payload.keyword = params.keyword
  if (params.ctx !== undefined) payload.ctx = params.ctx
  if (params.corpus) payload.corpus = params.corpus
  if (params.includeModels && params.includeModels.length > 0) {
    payload.include_models = params.includeModels
  }
  if (params.maxVariants !== undefined) payload.max_variants = params.maxVariants
  if (params.sentenceMargin !== undefined) payload.sentence_margin = params.sentenceMargin
  if (params.excludeBase !== undefined) payload.exclude_base = params.excludeBase
  const data = await api.post('analysis/kwic_parallel', { json: payload }).json()
  throwIfNotApplicable(data, 'analysis/kwic_parallel')
  return validateResponse(ParallelKwicResultSchema, data, 'analysis/kwic_parallel')
}

// ============================================
// Analysis API
// ============================================

/**
 * Zählattribut der Kollokationsroute: 'word' (Oberflächenformen, Default)
 * oder 'lemma' (Kookkurrenz über die Lemma-Spalte des Index; 422 mit
 * Capability-Hinweis, wenn das Korpus kein Lemma-Attribut trägt).
 */
export type CollocationAttribute = 'word' | 'lemma'

export interface CollocationsParams {
  term: string
  window?: number
  measure?: CollocationMeasure
  limit?: number
  withinSentence?: boolean
  sortBy?: CollocationSortKey
  /** Zählattribut (nur die sync GET-Route unterstützt 'lemma'). */
  attribute?: CollocationAttribute
  minFreq?: number
  offset?: number
  corpus?: string
  docsetId?: string
}

export interface Collocation {
  word: string
  /** Collocate frequency f(v) in the analysis scope, from the server f2. */
  corpusFrequency?: number | null
  frequency: number
  score: number
  measure: string
  rank?: number
  /** Observed co-occurrences O11; equals `frequency` for a single result row. */
  observed?: number
  /** Expected co-occurrences E11 in the displayed analysis scope. */
  expected?: number | null
  /** Pearson chi-square contribution of the O11 cell, not a full test statistic. */
  chi2Cell?: number | null
  /** Directional delta-P (F3): P(collocate|node) − P(collocate|¬node). */
  deltaPNc?: number | null
  /** Directional delta-P (F3): P(node|collocate) − P(node|¬collocate). */
  deltaPCn?: number | null
}

/**
 * Statistical provenance block (F1) attached to analysis responses. Mirrors
 * {@link MethodBlockSchema}; every field is optional (defensive).
 */
export interface MethodStat {
  key?: string
  name?: string
  latex_formula?: string
  /** Presentation MathML of latex_formula (analysis_defaults.METHOD_META). */
  formula_mathml?: string
  smoothing?: string | null
  sort_key?: string | null
  [key: string]: unknown
}

export interface MethodBlock {
  family?: string
  // Authoritative backend shape: an ordered array of stat descriptors, each
  // carrying its own `key` (analysis_defaults.build_method_block).
  statistics?: MethodStat[]
  default_sort?: string | null
  // Back-compat: legacy object-keyed `stats` map from an older backend.
  stats?: Record<string, MethodStat>
  target_total?: number | null
  reference_total?: number | null
  window?: number | null
  within_sentence?: boolean | null
  indexFingerprint?: string | null
  index_fingerprint?: string | null
  [key: string]: unknown
}

/** A stat descriptor with its key guaranteed present (UI-normalized). */
export type MethodStatEntry = MethodStat & { key: string }

/**
 * Iterate a method block's statistic descriptors regardless of wire shape.
 * Prefers the authoritative `statistics` array; falls back to the legacy
 * object-keyed `stats` map. Always returns entries with a `key`.
 */
export function methodStatEntries(method: MethodBlock | null | undefined): MethodStatEntry[] {
  if (!method) return []
  const arr = method.statistics
  if (Array.isArray(arr) && arr.length) {
    return arr.map((stat, i) => ({
      ...stat,
      key: typeof stat?.key === 'string' && stat.key ? stat.key : String(i),
    }))
  }
  const stats = method.stats
  if (stats && typeof stats === 'object') {
    return Object.entries(stats).map(([key, stat]) => ({ ...stat, key }))
  }
  return []
}

/** Normalize a raw `method` payload into a {@link MethodBlock}, or undefined. */
export function coerceMethodBlock(raw: unknown): MethodBlock | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined
  const block = raw as MethodBlock
  // Fold the snake_case fingerprint alias into the camelCase field for the UI.
  if (block.indexFingerprint == null && typeof block.index_fingerprint === 'string') {
    block.indexFingerprint = block.index_fingerprint
  }
  return block
}

function collocationsSearchParams(params: CollocationsParams): Record<string, string | number> {
  const searchParams: Record<string, string | number> = { term: params.term }
  const sortBy = params.sortBy ?? collocationSortKeyForMeasure(params.measure ?? 'logdice')
  if (params.window) searchParams.window = params.window
  if (params.limit) searchParams.limit = params.limit
  if (params.withinSentence !== undefined) {
    searchParams.within_sentence = params.withinSentence ? 'true' : 'false'
  }
  if (sortBy) searchParams.sort_by = sortBy
  if (params.attribute) searchParams.attribute = params.attribute
  if (typeof params.minFreq === 'number' && params.minFreq > 0) searchParams.min_freq = params.minFreq
  if (typeof params.offset === 'number' && params.offset > 0) searchParams.offset = params.offset
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  return searchParams
}

export async function getCollocations(params: CollocationsParams): Promise<Collocation[]> {
  const raw = await api
    .get('analysis/collocates', { searchParams: collocationsSearchParams(params) })
    .json()
  const response = validateResponse(CollocationsResponseSchema, raw, 'analysis/collocates')

  const measure = params.measure ?? 'logdice'
  const scoreKey = collocationSortKeyForMeasure(measure)

  return (response.rows ?? []).map((row) => {
    return mapCollocationRow(row, measure, scoreKey)
  })
}

/**
 * Full-fidelity page of the sync GET /analysis/collocates route: raw rows plus
 * the server `method` provenance block and the bounded-result meta, shaped like
 * {@link AnalysisJobRows} so job-based consumers can reuse their row pipeline.
 *
 * Used by the lemma counting path (`attribute=lemma`): the collocates JOB route
 * does not accept `attribute`, so lemma-based counting must go through the
 * sync route to avoid silently computing surface-form statistics.
 */
export async function getCollocationsPage(
  params: CollocationsParams,
): Promise<AnalysisJobRows<Record<string, any>>> {
  const raw = await api
    .get('analysis/collocates', { searchParams: collocationsSearchParams(params) })
    .json()
  const response = validateResponse(CollocationsResponseSchema, raw, 'analysis/collocates')
  const totalCandidates = typeof response.total_candidates === 'number'
    ? response.total_candidates
    : null
  return {
    job_id: '',
    status: 'done',
    rows: response.rows ?? [],
    method: response.method ? coerceMethodBlock(response.method) : undefined,
    row_limit: typeof response.row_limit === 'number' ? response.row_limit : null,
    total_candidates: totalCandidates,
    truncated: typeof response.truncated === 'boolean' ? response.truncated : undefined,
    total_rows: totalCandidates,
    offset: typeof response.offset === 'number' ? response.offset : params.offset ?? 0,
    limit: typeof response.limit === 'number' ? response.limit : params.limit,
  }
}

function mapCollocationRow(
  row: Record<string, any>,
  measure: CollocationMeasure,
  scoreKey: CollocationSortKey,
): Collocation {
  const rawScore =
    row[scoreKey]
    ?? row.mi
    ?? row.lmi
    ?? row.npmi
    ?? row.z
    ?? row.chi2_cell
    ?? row.t
    ?? row.ll
    ?? 0
  let score = typeof rawScore === 'number' ? rawScore : 0
  if (measure === 'logdice') {
    // Prefer the corpus-size-comparable logDice column when present; otherwise
    // reconstruct it from the raw dice coefficient (older indexes).
    const directLogdice = row.logdice
    if (typeof directLogdice === 'number' && Number.isFinite(directLogdice)) {
      score = directLogdice
    } else {
      const dice = row.dice ?? null
      if (typeof dice === 'number' && Number.isFinite(dice) && dice > 0) {
        score = 14 + Math.log2(dice)
      } else {
        score = 0
      }
    }
  }
  const frequency = row.f ?? row.observed ?? row.frequency ?? 0
  return {
    word: row.word ?? '',
    frequency: typeof frequency === 'number' ? frequency : 0,
    score,
    measure,
    observed: typeof row.observed === 'number'
      ? row.observed
      : (typeof frequency === 'number' ? frequency : undefined),
    expected: typeof row.expected === 'number' ? row.expected : null,
    chi2Cell: typeof row.chi2_cell === 'number' ? row.chi2_cell : null,
    deltaPNc: typeof row.delta_p_nc === 'number' ? row.delta_p_nc : null,
    deltaPCn: typeof row.delta_p_cn === 'number' ? row.delta_p_cn : null,
  }
}

// ============================================
// Collocation Network API
// ============================================

export type CollocationNetworkMeasure =
  | 'logdice'
  | 'dice'
  | 'mi'
  | 'mi3'
  | 'lmi'
  | 'npmi'
  | 'z'
  | 't'
  | 'll'
  | 'chi2_cell'

export interface CollocationNetworkParams {
  term: string
  window?: number
  measure?: CollocationNetworkMeasure
  maxNodes?: number
  expandDepth?: number
  minCount?: number
  withinSentence?: boolean
  /** Zählattribut 'word' (Default) oder 'lemma' (capability-gated, 422 sonst). */
  attribute?: CollocationAttribute
  corpus?: string
  docsetId?: string
}

export interface CollocationNetworkNode {
  id: string
  /** O11 of this word in the collocate row of `freq_via`, not a corpus frequency. */
  freq: number | null
  depth: number | null
  /** The node whose collocate row provided `freq`. */
  freq_via?: string | null
}

export interface CollocationNetworkEdge {
  source: string
  target: string
  weight: number | null
  measure: string | null
}

export interface CollocationNetwork {
  term: string
  measure: string
  nodes: CollocationNetworkNode[]
  edges: CollocationNetworkEdge[]
  diagnostics: Record<string, unknown>
  /** Statistical provenance block (r7 D-routes); absent on older backends. */
  method?: MethodBlock
}

export async function getCollocationNetwork(
  params: CollocationNetworkParams
): Promise<CollocationNetwork> {
  const searchParams: Record<string, string | number> = { term: params.term }
  if (params.window) searchParams.window = params.window
  if (params.measure) searchParams.measure = params.measure
  if (params.maxNodes) searchParams.max_nodes = params.maxNodes
  if (params.expandDepth) searchParams.expand_depth = params.expandDepth
  if (params.minCount !== undefined) searchParams.min_count = params.minCount
  if (params.withinSentence !== undefined) {
    searchParams.within_sentence = params.withinSentence ? 'true' : 'false'
  }
  if (params.attribute) searchParams.attribute = params.attribute
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId

  const raw = await api.get('analysis/collocation_network', { searchParams }).json()
  const response = validateResponse(
    CollocationNetworkResponseSchema,
    raw,
    'analysis/collocation_network'
  )

  return {
    term: response.term,
    measure: response.measure,
    nodes: (response.nodes ?? []).map((n) => ({
      id: n.id,
      freq: n.freq ?? null,
      depth: n.depth ?? null,
    })),
    edges: (response.edges ?? []).map((e) => ({
      source: e.source,
      target: e.target,
      weight: e.weight ?? null,
      measure: e.measure ?? null,
    })),
    diagnostics: response.diagnostics ?? {},
    method: coerceMethodBlock((response as { method?: unknown }).method),
  }
}

// ============================================
// Trend / Diachronie API (POST /analysis/trend)
// ============================================

export type TrendGranularity = 'year' | 'month'

export interface TrendParams {
  /** Plain-Query (Backend prefixt CQL selbst, wenn `cql` genutzt wird). */
  query?: string
  /** Alternativ: rohe CQL-Abfrage (Server prefixt `cql:` automatisch). */
  cql?: string
  /** Metadatenfeld mit Datumswerten (z.B. 'date', 'year'). */
  dateField: string
  granularity?: TrendGranularity
  corpus?: string
  docsetId?: string
  /** Ask for the metadata values behind every dated period. */
  periodValues?: boolean
}

export interface TrendPeriod {
  /** Periodenlabel (YYYY bzw. YYYY-MM) oder der Bucket 'undatiert'. */
  period: string
  documents: number
  hits: number
  tokens: number
  perMillion: number
  /** Wilson-Score-Untergrenze der Token-Rate, skaliert auf pro Million. */
  ciLow: number
  /** Wilson-Score-Obergrenze der Token-Rate, skaliert auf pro Million. */
  ciHigh: number
  /**
   * Metadata values of the date field that form the period, when requested
   * with periodValues. A metadata filter on them selects the period's
   * documents. Absent for the undated bucket.
   */
  values?: Array<string | number>
}

export interface TrendResult {
  query: string
  dateField: string
  granularity: string
  periods: TrendPeriod[]
  warnings: string[]
  /** Provenienz (family 'trend', Wilson-Intervall dokumentiert). */
  method?: MethodBlock
}

export async function getAnalysisTrend(
  params: TrendParams,
  options: { signal?: AbortSignal } = {}
): Promise<TrendResult> {
  const payload: Record<string, unknown> = {
    date_field: params.dateField,
    granularity: params.granularity ?? 'year',
  }
  if (params.query !== undefined) payload.query = params.query
  if (params.cql !== undefined) payload.cql = params.cql
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.periodValues) payload.period_values = true

  const raw = await longRunningApi
    .post('analysis/trend', { json: payload, signal: options.signal })
    .json()
  const response = validateResponse(TrendResponseSchema, raw, 'analysis/trend')
  return {
    query: response.query,
    dateField: response.date_field,
    granularity: response.granularity,
    periods: (response.periods ?? []).map((row) => ({
      period: row.period,
      documents: row.documents,
      hits: row.hits,
      tokens: row.tokens,
      perMillion: row.per_million,
      ciLow: row.ci_low,
      ciHigh: row.ci_high,
      ...(row.values ? { values: row.values } : {}),
    })),
    warnings: response.warnings ?? [],
    method: coerceMethodBlock((response as { method?: unknown }).method),
  }
}

// ============================================
// Analysis Jobs API
// ============================================

export interface AnalysisJobSnapshot {
  job_id: string
  kind?: string
  corpus?: string
  params?: Record<string, any>
  status: string
  progress?: number
  message?: string
  total_rows?: number | null
  error?: string | null
  result_available?: boolean
  result_discarded?: boolean
  result_discard_reason?: string | null
  result_readiness?: string
  rows_state?: string
  result_warnings?: string[]
  result_bytes?: number | null
  result_max_bytes?: number | null
  created_at?: number
  updated_at?: number
}

export interface AnalysisJobStart {
  job_id: string
  status_url?: string
  rows_url?: string
  ws_url?: string
}

export interface AnalysisJobRows<T = any> {
  job_id: string
  status: string
  progress?: number
  message?: string
  total_rows?: number | null
  /** Some analysis tool responses (e.g. contrast) report the full result count as `total`. */
  total?: number | null
  row_limit?: number | null
  total_candidates?: number | null
  truncated?: boolean
  error?: string | null
  result_available?: boolean
  result_discarded?: boolean
  result_discard_reason?: string | null
  result_readiness?: string
  rows_state?: string
  result_warnings?: string[]
  result_bytes?: number | null
  result_max_bytes?: number | null
  offset?: number
  limit?: number
  rows?: T[]
  method?: MethodBlock
}

export async function getAnalysisJob(jobId: string): Promise<AnalysisJobSnapshot> {
  const raw = await longRunningApi.get(`analysis/jobs/${jobId}`).json()
  return validateResponse(AnalysisJobSnapshotSchema, raw, 'analysis/jobs/{job_id}')
}

export async function cancelAnalysisJob(jobId: string): Promise<AnalysisJobSnapshot> {
  const raw = await api.post(`analysis/jobs/${jobId}/cancel`).json()
  return validateResponse(AnalysisJobSnapshotSchema, raw, 'analysis/jobs/{job_id}/cancel')
}

export async function getAnalysisJobRows<T = any>(
  jobId: string,
  offset: number = 0,
  limit: number = 200
): Promise<AnalysisJobRows<T>> {
  const searchParams: Record<string, string | number> = { offset, limit }
  const raw = await longRunningApi.get(`analysis/jobs/${jobId}/rows`, { searchParams }).json()
  return validateResponse(AnalysisJobRowsSchema, raw, 'analysis/jobs/{job_id}/rows') as AnalysisJobRows<T>
}

export interface CollocatesJobParams {
  term: string
  collocate?: string
  window?: number
  minFreq?: number
  limit?: number
  withinSentence?: boolean
  sortBy?: CollocationSortKey
  corpus?: string
  docsetId?: string
}

export async function createCollocatesJob(params: CollocatesJobParams): Promise<AnalysisJobStart> {
  const payload: Record<string, string | number | boolean> = { term: params.term }
  if (params.collocate) payload.collocate = params.collocate
  if (params.window) payload.window = params.window
  if (typeof params.minFreq === 'number' && params.minFreq > 0) payload.min_freq = params.minFreq
  if (typeof params.limit === 'number' && params.limit > 0) payload.limit = params.limit
  if (params.withinSentence !== undefined) {
    payload.within_sentence = params.withinSentence
  }
  if (params.sortBy) payload.sort_by = params.sortBy
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  const raw = await api.post('analysis/collocates/job', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/collocates/job')
}

export interface CollocatesDiffJobParams {
  term: string
  targetDocsetId: string
  referenceDocsetId: string
  window?: number
  withinSentence?: boolean
  sortBy?: 'mi' | 'lmi' | 'npmi' | 'z' | 'chi2_cell' | 'dice' | 'logdice' | 't' | 'll' | 'f'
  limit?: number
  corpus?: string
}

export async function createCollocatesDiffJob(params: CollocatesDiffJobParams): Promise<AnalysisJobStart> {
  const payload: Record<string, string | number | boolean> = {
    term: params.term,
    target_docset_id: params.targetDocsetId,
    reference_docset_id: params.referenceDocsetId,
  }
  if (params.window) payload.window = params.window
  if (params.withinSentence !== undefined) {
    payload.within_sentence = params.withinSentence
  }
  if (params.sortBy) payload.sort_by = params.sortBy
  if (params.limit) payload.limit = params.limit
  if (params.corpus) payload.corpus = params.corpus
  const raw = await api.post('analysis/collocates_diff/job', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/collocates_diff/job')
}

/**
 * Free A-vs-B contrast on ANY corpus (no human/AI pairing required).
 *
 * Each side is identified by EITHER a transient `docsetId` (e.g. resolved from a
 * metadata filter via {@link docsetFromMeta}) OR a persistent `subcorpus` name.
 * Backend route: POST /api/v1/analysis/contrast — delegates to the pairing-free
 * collocates-diff engine and returns an async job (same result shape as
 * {@link createCollocatesDiffJob}).
 */
export interface ContrastJobParams {
  term: string
  /** Target side: a resolved docset id (preferred) or a persistent subcorpus name. */
  targetDocsetId?: string
  targetSubcorpus?: string
  /** Reference side: a resolved docset id (preferred) or a persistent subcorpus name. */
  referenceDocsetId?: string
  referenceSubcorpus?: string
  window?: number
  withinSentence?: boolean
  sortBy?: 'mi' | 'lmi' | 'npmi' | 'z' | 'chi2_cell' | 'dice' | 'logdice' | 't' | 'll' | 'f'
  limit?: number
  corpus?: string
}

export async function createContrastJob(params: ContrastJobParams): Promise<AnalysisJobStart> {
  if (!params.targetDocsetId && !params.targetSubcorpus) {
    throw new Error(t('errors.client.targetRequired'))
  }
  if (!params.referenceDocsetId && !params.referenceSubcorpus) {
    throw new Error(t('errors.client.referenceRequired'))
  }
  const payload: Record<string, string | number | boolean> = { term: params.term }
  if (params.targetDocsetId) payload.target_docset_id = params.targetDocsetId
  if (params.targetSubcorpus) payload.target_subcorpus = params.targetSubcorpus
  if (params.referenceDocsetId) payload.reference_docset_id = params.referenceDocsetId
  if (params.referenceSubcorpus) payload.reference_subcorpus = params.referenceSubcorpus
  if (params.window) payload.window = params.window
  if (params.withinSentence !== undefined) payload.within_sentence = params.withinSentence
  if (params.sortBy) payload.sort_by = params.sortBy
  if (params.limit) payload.limit = params.limit
  if (params.corpus) payload.corpus = params.corpus
  const raw = await api.post('analysis/contrast', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/contrast')
}

export interface NgramsJobParams {
  n?: number
  minN?: number
  maxN?: number
  minFreq?: number
  limit?: number
  corpus?: string
  docsetId?: string
  tokenCount?: number
}

export async function createNgramsJob(params: NgramsJobParams): Promise<AnalysisJobStart> {
  const minN = params.minN ?? params.n
  const maxN = params.maxN ?? params.n ?? minN
  if (!Number.isFinite(minN) || !Number.isFinite(maxN)) {
    throw new Error(t('errors.client.ngramSize'))
  }
  const payload: Record<string, string | number> = {
    min_n: Math.round(minN as number),
    max_n: Math.round(maxN as number),
  }
  if (typeof params.minFreq === 'number' && Number.isFinite(params.minFreq)) {
    payload.min_freq = Math.max(1, Math.round(params.minFreq))
  }
  if (params.limit) payload.limit = params.limit
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  const raw = await api.post('analysis/ngrams/job', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/ngrams/job')
}

export interface NgramsDiffJobParams {
  targetDocsetId: string
  referenceDocsetId: string
  n?: number
  minN?: number
  maxN?: number
  minFreq?: number
  limit?: number
  corpus?: string
}

export async function createNgramsDiffJob(params: NgramsDiffJobParams): Promise<AnalysisJobStart> {
  const minN = params.minN ?? params.n
  const maxN = params.maxN ?? params.n ?? minN
  if (!Number.isFinite(minN) || !Number.isFinite(maxN)) {
    throw new Error(t('errors.client.ngramContrastSize'))
  }
  const payload: Record<string, string | number> = {
    target_docset_id: params.targetDocsetId,
    reference_docset_id: params.referenceDocsetId,
    min_n: Math.round(minN as number),
    max_n: Math.round(maxN as number),
  }
  if (typeof params.minFreq === 'number' && Number.isFinite(params.minFreq)) {
    payload.min_freq = Math.max(1, Math.round(params.minFreq))
  }
  if (params.limit) payload.limit = params.limit
  if (params.corpus) payload.corpus = params.corpus
  const raw = await api.post('analysis/ngrams_diff/job', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/ngrams_diff/job')
}

export interface FrequencyDiffJobParams {
  targetDocsetId: string
  referenceDocsetId: string
  /** Minimum frequency on either side before the exact union is ranked. */
  minFreq?: number
  limit?: number
  corpus?: string
}

export async function createFrequencyDiffJob(
  params: FrequencyDiffJobParams,
): Promise<AnalysisJobStart> {
  if (!params.targetDocsetId || !params.referenceDocsetId) {
    throw new Error(t('errors.client.frequencyDiff'))
  }
  const payload: Record<string, string | number> = {
    target_docset_id: params.targetDocsetId,
    reference_docset_id: params.referenceDocsetId,
  }
  if (typeof params.minFreq === 'number' && Number.isFinite(params.minFreq)) {
    payload.min_freq = Math.max(1, Math.round(params.minFreq))
  }
  if (params.limit) payload.limit = params.limit
  if (params.corpus) payload.corpus = params.corpus
  const raw = await api.post('analysis/frequency_diff/job', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/frequency_diff/job')
}

export interface KeynessJobParams {
  targetDocsetId: string
  /** Reference docset id. Optional when an external reference source is used. */
  referenceDocsetId?: string
  pos?: string
  corpus?: string
  // ── External-reference keyness (FT-KEYNESS-RESEARCH, r9). Optional/defensive:
  // older backends ignore these and use the docset-vs-docset path. ──
  /** Discriminator: which reference the target is compared against. */
  referenceSource?: 'docset' | 'corpus' | 'whole'
  /** A second loaded corpus to use as reference (referenceSource = 'corpus'). */
  referenceCorpus?: string
  /** Minimum candidate frequency before the keyness test (FDR-m honest). */
  minFreq?: number
}

export async function createKeynessJob(params: KeynessJobParams): Promise<AnalysisJobStart> {
  const payload: Record<string, string | number> = {
    target_docset_id: params.targetDocsetId,
  }
  if (params.referenceDocsetId) payload.reference_docset_id = params.referenceDocsetId
  if (params.pos) payload.pos = params.pos
  if (params.corpus) payload.corpus = params.corpus
  // Additive, defensive reference-source fields. The backend route adds these
  // in r9; absent them the server falls back to docset-vs-docset.
  if (params.referenceSource) payload.reference_source = params.referenceSource
  if (params.referenceCorpus) payload.reference_corpus = params.referenceCorpus
  if (typeof params.minFreq === 'number' && params.minFreq > 0) payload.min_freq = params.minFreq
  const raw = await api.post('analysis/keyness/job', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/keyness/job')
}

export interface CollocateKwicParams {
  term: string
  collocate?: string
  collocates?: string[]
  attribute?: 'word' | 'lemma'
  window?: number
  ctx?: number
  limit?: number
  offset?: number
  withinSentence?: boolean
  corpus?: string
  docsetId?: string
}

export async function getCollocateKwic(params: CollocateKwicParams): Promise<QueryResult> {
  const start = performance.now()
  const collocateValue = params.collocates?.length
    ? params.collocates.join('|')
    : params.collocate
      ? params.collocate
      : ''
  const searchParams: Record<string, string | number> = {
    term: params.term,
    collocate: collocateValue,
  }
  if (params.window) searchParams.window = params.window
  if (params.ctx) searchParams.ctx = params.ctx
  if (params.limit) searchParams.limit = params.limit
  if (params.offset !== undefined) searchParams.offset = params.offset
  if (params.withinSentence !== undefined) {
    searchParams.within_sentence = params.withinSentence ? 'true' : 'false'
  }
  if (params.attribute === 'lemma') searchParams.attribute = 'lemma'
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  const response = await api.get('analysis/collocates/kwic', { searchParams }).json() as
    | Array<{ pos?: number; left: string; kw: string; right: string; doc_id?: string | number; doc?: string; meta?: Record<string, unknown>; coll_offsets?: unknown[]; match_offsets?: unknown[] }>
    | { rows?: unknown[]; total?: number; next_offset?: number | null; truncated?: boolean }
  const rows = Array.isArray(response)
    ? response
    : (Array.isArray((response as { rows?: unknown[] }).rows) ? (response as { rows: unknown[] }).rows : [])
  const total = Array.isArray(response)
    ? rows.length
    : (typeof (response as { total?: number }).total === 'number' ? (response as { total: number }).total : rows.length)
  const next_offset = Array.isArray(response)
    ? null
    : ((response as { next_offset?: number | null }).next_offset ?? null)
  const truncated = Array.isArray(response)
    ? false
    : Boolean((response as { truncated?: boolean }).truncated)

  const hits = (rows as Array<Record<string, unknown>>).map((row, index) => ({
    position: (row.pos as number | undefined) ?? index,
    left: row.left as string,
    // The first token of the node hit. Its other tokens are in `match_offsets`.
    match: row.kw as string,
    right: row.right as string,
    doc_id: row.doc_id !== undefined ? String(row.doc_id) : `co-${index}`,
    doc_title: row.doc as string | undefined,
    metadata: row.meta as Record<string, string> | undefined,
    collocate_offsets: Array.isArray(row.coll_offsets)
      ? (row.coll_offsets as unknown[]).map((val: unknown) => Number(val)).filter((val: number) => Number.isFinite(val))
      : undefined,
    match_offsets: Array.isArray(row.match_offsets)
      ? (row.match_offsets as unknown[]).map((val: unknown) => Number(val)).filter((val: number) => Number.isFinite(val))
      : undefined,
    ...rawSpacing(row),
  }))

  const query_time_ms = Math.round(performance.now() - start)

  return {
    hits,
    total,
    query_time_ms,
    next_offset,
    truncated,
    coKwic: Array.isArray(response) ? null : coKwicCountsFromResponse(response as Record<string, unknown>),
  }
}

function coKwicCountsFromResponse(response: Record<string, unknown>): CoKwicCounts | null {
  const raw = response.collocate_tokens
  if (!raw || typeof raw !== 'object') return null
  const collocateTokens: Record<string, number> = {}
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const num = Number(value)
    if (Number.isFinite(num)) collocateTokens[key] = num
  }
  const nodeHits = Number(response.node_hits)
  const window = Number(response.window)
  return {
    rowUnit: typeof response.row_unit === 'string' ? response.row_unit : 'node_hit',
    nodeHits: Number.isFinite(nodeHits) ? nodeHits : null,
    collocateTokens,
    attribute: response.attribute === 'lemma' ? 'lemma' : 'word',
    window: Number.isFinite(window) ? window : null,
    withinSentence: typeof response.within_sentence === 'boolean' ? response.within_sentence : null,
  }
}

export interface MetaValuesParams {
  fields: string[]
  corpus?: string
  filters?: Record<string, string | string[]>
  limit?: number
}

export interface MetaValuesPage {
  values: Record<string, string[]>
  truncatedFields: string[]
  limit: number | null
}

export async function getMetaValuesPage(
  params: MetaValuesParams,
  options: { signal?: AbortSignal } = {}
): Promise<MetaValuesPage> {
  const payload: Record<string, unknown> = { fields: params.fields }
  if (params.corpus) payload.corpus = params.corpus
  if (params.filters) payload.filters = params.filters
  if (params.limit !== undefined) payload.limit = params.limit
  const raw = await longRunningApi.post('analysis/meta_values', { json: payload, signal: options.signal }).json()
  const response = validateResponse(MetaValuesResponseSchema, raw, 'analysis/meta_values')
  return {
    values: response.values ?? {},
    truncatedFields: response.truncated_fields ?? [],
    limit: response.limit ?? null,
  }
}

export async function getMetaValues(
  params: MetaValuesParams,
  options: { signal?: AbortSignal } = {}
): Promise<Record<string, string[]>> {
  return (await getMetaValuesPage(params, options)).values
}

export interface MetaCountsParams {
  fields: string[]
  corpus?: string
  filters?: Record<string, string | string[]>
}

export async function getMetaCounts(
  params: MetaCountsParams,
  options: { signal?: AbortSignal } = {}
): Promise<Record<string, Record<string, number>>> {
  const payload: Record<string, unknown> = { fields: params.fields }
  if (params.corpus) payload.corpus = params.corpus
  if (params.filters) payload.filters = params.filters
  const raw = await longRunningApi.post('analysis/meta_counts', { json: payload, signal: options.signal }).json()
  const response = validateResponse(MetaCountsResponseSchema, raw, 'analysis/meta_counts')
  return response.counts ?? {}
}

export interface MetaSchemaParams {
  corpus?: string
}

export async function getMetaSchema(
  params: MetaSchemaParams = {},
  options: { signal?: AbortSignal; timeout?: number } = {}
): Promise<MetaSchemaResponse> {
  const searchParams: Record<string, string> = {}
  if (params.corpus && params.corpus !== 'default') {
    searchParams.corpus = params.corpus
  }
  const raw = await api.get('analysis/meta_schema', {
    searchParams,
    signal: options.signal,
    timeout: options.timeout ?? 5000,
  }).json()
  return validateResponse(MetaSchemaResponseSchema, raw, 'analysis/meta_schema')
}

export interface DocsetFromSearchParams {
  query: string
  corpus?: string
  includeAi?: boolean
  includeHuman?: boolean
  aiFilters?: Record<string, string | string[]>
  /** Same shape as a subcorpus filter_spec (the resolve route replays it as meta_filters). */
  metaFilters?: FilterSpec
  limit?: number
}

export interface DocsetFromSearchResult {
  docset_id: string
  doc_count: number
  hit_doc_count?: number
  ref_doc_count?: number
  token_count?: number
}

export async function createDocsetFromSearch(
  params: DocsetFromSearchParams
): Promise<DocsetFromSearchResult> {
  const payload: Record<string, unknown> = {
    query: params.query,
    include_ai: params.includeAi ?? true,
    include_human: params.includeHuman ?? true,
  }
  if (params.corpus) payload.corpus = params.corpus
  if (params.aiFilters) payload.ai_filters = params.aiFilters
  if (params.metaFilters) payload.meta_filters = params.metaFilters
  if (params.limit) payload.limit = params.limit
  const data = await api.post('analysis/docset_from_search', { json: payload }).json()
  return validateResponse(DocsetFromSearchResultSchema, data, 'analysis/docset_from_search')
}

// ============================================
// Subcorpora API (durable, named definitions)
// ============================================

/**
 * Op-tagged metadata filter spec, as understood by the backend
 * `docset_from_meta` / subcorpus resolve endpoints. A field maps to:
 * - a single value or list of values (equality / membership)
 * - `{ op: '>=' | '<=' | '>' | '=' , value }` (comparison)
 * - `{ op: 'between', lo, hi }` (range)
 */
export type FilterSpecValue =
  | string
  | number
  | Array<string | number>
  | { op: '>=' | '<=' | '>' | '='; value: string | number }
  | { op: 'between'; lo: string | number; hi: string | number }

export type FilterSpec = Record<string, FilterSpecValue>

/**
 * Durable, named subcorpus definition. This is the identity of a subcorpus;
 * `docset_id` is a transient cache hint resolved at runtime (see resolveSubcorpus).
 */
export interface SubcorpusDefinition {
  name: string
  corpus: string
  query?: string | null
  filter_spec?: FilterSpec
  filter?: Record<string, string | string[]> | null
  include_ai?: boolean
  include_human?: boolean
  ai_filters?: Record<string, string | string[]> | null
  metadata_schema_hash?: string | null
  created_at?: number
  creator?: string | null
}

export interface SaveSubcorpusInput {
  name: string
  corpus: string
  filter_spec?: FilterSpec
  query?: string | null
  include_ai?: boolean
  include_human?: boolean
  ai_filters?: Record<string, string | string[]> | null
}

export interface ResolveSubcorpusResult {
  docset_id: string
  doc_count: number
  token_count: number
  stale: boolean
}

export async function listSubcorpora(): Promise<SubcorpusDefinition[]> {
  const response = await api.get('subcorpora').json<{ subcorpora?: SubcorpusDefinition[] }>()
  return response.subcorpora ?? []
}

export async function getSubcorpus(name: string): Promise<SubcorpusDefinition> {
  return api.get(`subcorpora/${encodeURIComponent(name)}`).json<SubcorpusDefinition>()
}

export async function saveSubcorpus(def: SaveSubcorpusInput): Promise<SubcorpusDefinition> {
  const payload: Record<string, unknown> = {
    name: def.name,
    corpus: def.corpus,
  }
  if (def.filter_spec) payload.filter_spec = def.filter_spec
  if (def.query !== undefined) payload.query = def.query
  if (def.include_ai !== undefined) payload.include_ai = def.include_ai
  if (def.include_human !== undefined) payload.include_human = def.include_human
  if (def.ai_filters !== undefined) payload.ai_filters = def.ai_filters
  return api.post('subcorpora', { json: payload }).json<SubcorpusDefinition>()
}

export async function deleteSubcorpus(name: string): Promise<{ status: string }> {
  return api.delete(`subcorpora/${encodeURIComponent(name)}`).json<{ status: string }>()
}

export async function resolveSubcorpus(
  name: string,
  corpus?: string
): Promise<ResolveSubcorpusResult> {
  const payload: Record<string, unknown> = {}
  if (corpus) payload.corpus = corpus
  return api
    .post(`subcorpora/${encodeURIComponent(name)}/resolve`, { json: payload })
    .json<ResolveSubcorpusResult>()
}

export interface DocsetFromMetaResult {
  docset_id: string
  doc_count: number
  token_count?: number
}

export async function docsetFromMeta(
  filters: FilterSpec,
  corpus?: string,
  // Opt in to the real scope token count. The backend treats a truthy
  // `token_count` as "compute it" and returns idx.docset_token_count(doc_ids)
  // — the same real total docset_from_search always returns. Default on, so a
  // metadata-built scope reports a true denominator (per-million, scope chip)
  // instead of falling back to 0 (NGRAMS-METASUBCORPUS-PERMILLION / SUBC-02).
  withTokenCount = true
): Promise<DocsetFromMetaResult> {
  const payload: Record<string, unknown> = { filters }
  if (corpus) payload.corpus = corpus
  if (withTokenCount) payload.token_count = 1
  return api.post('analysis/docset_from_meta', { json: payload }).json<DocsetFromMetaResult>()
}

export interface DocsetIntersectionGroup {
  label: string
  filters: Record<string, string | string[]>
}

export interface DocsetIntersectionParams {
  groups: DocsetIntersectionGroup[]
  corpus?: string
  includeHuman?: boolean
  textType?: string
}

export interface DocsetIntersectionResult {
  intersection_count: number
  groups: Array<{
    label: string
    docset_id: string
    doc_count: number
    ref_count: number
    token_count?: number
  }>
  human?: {
    docset_id: string
    doc_count: number
    token_count?: number
  }
}

export async function getDocsetIntersection(
  params: DocsetIntersectionParams
): Promise<DocsetIntersectionResult> {
  const payload: Record<string, unknown> = {
    groups: params.groups.map((g) => ({ label: g.label, filters: g.filters })),
    include_human: params.includeHuman ?? false,
  }
  if (params.corpus) payload.corpus = params.corpus
  if (params.textType) payload.text_type = params.textType
  const data = await api.post('analysis/docset_intersection', { json: payload }).json()
  return validateResponse(DocsetIntersectionResultSchema, data, 'analysis/docset_intersection')
}

export interface ParallelGroupModel {
  model: string
  axis?: string
  axis_value?: string
  label?: string
  count: number
}

export interface ParallelGroupVariant {
  doc_id: number
  label: string
  provenance?: string
}

export interface ParallelGroup {
  ref_doc: number
  doc_count: number
  doc_ids: number[]
  human_doc_id: number | null
  variant_doc_ids: number[]
  /** Lightweight metadata for a full-text comparison picker. */
  variants?: ParallelGroupVariant[]
  models: ParallelGroupModel[]
  text_types: Record<string, number>
  sources: string[]
  label?: string
}

export interface ParallelGroupsParams {
  corpus?: string
  /** Limit the response to one known reference-document group. */
  refDoc?: number
  docsetId?: string
  includeAllVariants?: boolean
  limit?: number
  offset?: number
  sort?: 'ref_doc' | 'variant_count'
}

export interface ParallelGroupsResult {
  total: number
  groups: ParallelGroup[]
}

export async function getParallelGroups(
  params: ParallelGroupsParams
): Promise<ParallelGroupsResult> {
  const payload: Record<string, unknown> = {}
  if (params.corpus) payload.corpus = params.corpus
  if (params.refDoc !== undefined) payload.ref_doc = params.refDoc
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.includeAllVariants !== undefined) payload.include_all_variants = params.includeAllVariants
  if (params.limit !== undefined) payload.limit = params.limit
  if (params.offset !== undefined) payload.offset = params.offset
  if (params.sort) payload.sort = params.sort
  const data = await longRunningApi.post('analysis/parallel_groups', { json: payload }).json()
  throwIfNotApplicable(data, 'analysis/parallel_groups')
  return validateResponse(ParallelGroupsResultSchema, data, 'analysis/parallel_groups')
}

export interface FrequencyParams {
  groupBy?: 'word' | 'lemma' | 'pos'
  /** Backend POS-prefix filter for word frequencies, e.g. "N" or "NN". */
  posPrefix?: string
  sortBy?: 'freq' | 'alpha'
  limit?: number
  tokenCount?: number
  stopwords?: string[] | string
  corpus?: string
  docsetId?: string
}

export interface FrequencyItem {
  item: string
  frequency: number
  relative: number
}

export interface FrequencyResult {
  rows: FrequencyItem[]
  groupBy: 'word' | 'lemma' | 'pos'
  posPrefix?: string
  basis?: string
  /** Documents whether surface forms were merged ignoring case (str.lower, ß and ss stay distinct). */
  casePolicy?: string
  filteredTokenPolicy?: string
  rowLimit?: number
  totalCandidates?: number
  truncated?: boolean
}

type RawFrequencyRow = {
  word: string
  f: number
}

function frequencyRowsToResult(
  rows: RawFrequencyRow[],
  params: FrequencyParams,
  meta: {
    groupBy?: 'word' | 'lemma' | 'pos'
    posPrefix?: string
    basis?: string
    casePolicy?: string
    filteredTokenPolicy?: string
    rowLimit?: number | null
    totalCandidates?: number | null
    truncated?: boolean
  } = {}
): FrequencyResult {
  let orderedRows = rows

  // Client-side sorting preserves existing UI behavior; the backend still does
  // the full count before returning the bounded display page.
  if (params.sortBy === 'alpha') {
    orderedRows = [...orderedRows].sort((a, b) => a.word.localeCompare(b.word))
  } else {
    orderedRows = [...orderedRows].sort((a, b) => b.f - a.f)
  }

  if (params.limit && params.limit > 0) {
    orderedRows = orderedRows.slice(0, params.limit)
  }

  const totalTokensFromRows = orderedRows.reduce((sum, row) => sum + row.f, 0)
  const tokenCount = params.tokenCount && params.tokenCount > 0
    ? params.tokenCount
    : totalTokensFromRows
  const safeTokenCount = tokenCount > 0 ? tokenCount : 1

  return {
    rows: orderedRows.map((row) => ({
      item: row.word,
      frequency: row.f,
      relative: row.f / safeTokenCount,
    })),
    groupBy: meta.groupBy ?? params.groupBy ?? 'word',
    posPrefix: meta.posPrefix ?? params.posPrefix,
    basis: meta.basis,
    casePolicy: meta.casePolicy,
    filteredTokenPolicy: meta.filteredTokenPolicy,
    rowLimit: meta.rowLimit ?? undefined,
    totalCandidates: meta.totalCandidates ?? undefined,
    truncated: meta.truncated,
  }
}

export async function getFrequencyResult(
  params: FrequencyParams,
  options: { signal?: AbortSignal } = {}
): Promise<FrequencyResult> {
  const searchParams: Record<string, string | number> = {}
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  if (params.groupBy) searchParams.group_by = params.groupBy
  if (params.posPrefix?.trim()) searchParams.pos = params.posPrefix.trim()
  if (params.limit && params.limit > 0) searchParams.limit = params.limit
  if (params.stopwords) {
    searchParams.stopwords = Array.isArray(params.stopwords)
      ? params.stopwords.join(',')
      : params.stopwords
  }

  const raw = await api.get('analysis/frequency_list', { searchParams, signal: options.signal }).json()
  const response = validateResponse(FrequencyResponseSchema, raw, 'analysis/frequency_list')

  return frequencyRowsToResult(response.rows ?? [], params, {
    groupBy: response.group_by ?? params.groupBy ?? 'word',
    posPrefix: response.pos ?? params.posPrefix,
    basis: response.basis,
    casePolicy: response.case_policy,
    filteredTokenPolicy: response.filtered_token_policy,
    rowLimit: response.row_limit,
    totalCandidates: response.total_candidates,
    truncated: response.truncated,
  })
}

export function canCreateFrequencyListJob(params: FrequencyParams): boolean {
  return !params.groupBy || params.groupBy === 'word'
}

export async function createFrequencyListJob(params: FrequencyParams): Promise<AnalysisJobStart> {
  if (!canCreateFrequencyListJob(params)) {
    throw new Error(t('errors.client.frequencyJobWordOnly'))
  }
  const payload: Record<string, unknown> = {}
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.posPrefix?.trim()) payload.pos_prefix = params.posPrefix.trim()
  if (params.limit && params.limit > 0) payload.limit = params.limit
  if (params.stopwords) payload.stopwords = params.stopwords

  const raw = await longRunningApi.post('analysis/frequency_list/job', { json: payload }).json()
  return validateResponse(AnalysisJobStartSchema, raw, 'analysis/frequency_list/job')
}

export function frequencyJobRowsToResult(
  response: AnalysisJobRows<RawFrequencyRow>,
  params: FrequencyParams,
): FrequencyResult {
  return frequencyRowsToResult(response.rows ?? [], params, {
    groupBy: 'word',
    posPrefix: params.posPrefix,
    basis: 'analyst_token_frequency',
    casePolicy: 'case_insensitive (lowercase)', // i18n-ignore: technical policy value
    filteredTokenPolicy: t('errors.client.filteredTokenPolicy'),
    rowLimit: response.row_limit,
    totalCandidates: response.total_candidates ?? response.total_rows ?? null,
    truncated: response.truncated,
  })
}

export async function getFrequency(
  params: FrequencyParams,
  options: { signal?: AbortSignal } = {}
): Promise<FrequencyItem[]> {
  const result = await getFrequencyResult(params, options)
  return result.rows
}

export interface DispersionParams {
  term: string
  partitions?: number
  tokenCount?: number
  corpus?: string
  docsetId?: string
}

export interface DispersionResult {
  term: string
  partitions: number[]
  /** Raw Gries DP over documents: 0 = evenly dispersed, 1 = clustered. */
  dp: number
  /** Normalized Gries DP (corrects for number of parts). Optional for older indexes. */
  dpnorm?: number | null
  /** Classification derived from dp: even / fairly_even / fairly_clustered / clustered. */
  classification?: string | null
  /** Per-document token counts the DP was computed over. */
  doc_sizes?: number[] | null
  /** Unit the dispersion was computed over (e.g. "document"). */
  unit?: string | null
  /** Optional legacy DP over equal-width positional windows. */
  positional_dp_windowed?: number | null
  /** Number of positional windows used for positional_dp_windowed. */
  positional_window_count?: number | null
  basis?: string
  token_count?: number
  fallback?: boolean
  partial?: boolean
  // ── Dispersion family (FT-DISPERSION-FAMILY, r9). All optional: older
  // backends emit only DP/DPnorm, so every consumer must degrade gracefully. ──
  /** Juilland's D: 1 = perfectly even, 0 = maximally clustered. */
  juilland_d?: number | null
  /** Carroll's D2 (normalised entropy): 1 = even, 0 = clustered. */
  carroll_d2?: number | null
  /** Range: proportion of parts in which the term occurs (0..1). */
  range_prop?: number | null
  /** Variation coefficient of the normalised per-part frequencies. */
  vc?: number | null
  // detail is nullable: the backend's honest 'not_found' limitation sends detail:null.
  limitations?: Array<{ code?: string; message?: string; detail?: string | null; [key: string]: unknown }>
}

export interface DispersionOffsetsResult {
  offsets: number[]
  basis?: string
  token_count?: number | null
  fallback?: boolean
  partial?: boolean
  truncated?: boolean
  total?: number
  next_offset?: number | null
  limitations?: Array<{ code?: string; message?: string; detail?: string | null; [key: string]: unknown }>
}

export async function getDispersionOffsets(
  params: DispersionParams,
  options: { signal?: AbortSignal } = {},
): Promise<DispersionOffsetsResult> {
  const searchParams: Record<string, string | number> = { term: params.term }
  if (params.partitions) searchParams.partitions = params.partitions
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId

  const raw = await api.get('analysis/dispersion_offsets', {
    searchParams,
    signal: options.signal,
  }).json()
  return validateResponse(DispersionOffsetsResponseSchema, raw, 'analysis/dispersion_offsets')
}

export async function getDispersion(
  params: DispersionParams,
  options: { signal?: AbortSignal } = {}
): Promise<DispersionResult> {
  const searchParams: Record<string, string | number> = { term: params.term }
  if (params.partitions) searchParams.partitions = params.partitions
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId

  const data = await api.get('analysis/dispersion', { searchParams, signal: options.signal }).json()
  return validateResponse(DispersionResultSchema, data, 'analysis/dispersion')
}

// ============================================
// Semantic Search API
// ============================================

export interface SemanticSearchParams {
  query: string
  top_k?: number
  corpus?: string
  docsetId?: string
  backend?: string
  level?: string
}

export interface SemanticResult {
  doc_id: string
  chunk_id: string
  text: string
  score: number
  metadata?: Record<string, unknown>
}

export interface SemanticCandidateGenerationMeta {
  backend?: string
  level?: string
  method?: string
  indexType?: string
  searchMode?: 'exact' | 'approximate' | 'unknown'
  requestedTopN?: number
  requestedContext?: number
  candidateLimit?: number
  candidateCount?: number
  totalVectors?: number
  lexicalSeedCount?: number
  oversample?: number
  [key: string]: unknown
}

export interface SemanticRerankMeta {
  enabled?: boolean
  method?: string
  inputCount?: number
  outputCount?: number
  [key: string]: unknown
}

export interface SemanticFilteringMeta {
  docsetApplied?: boolean
  docsetDocCount?: number | null
  minScore?: number
  postFilterCandidateCount?: number
  [key: string]: unknown
}

export interface SemanticSearchMeta {
  exactness?: 'exact' | 'approximate' | 'unknown'
  candidateGeneration?: SemanticCandidateGenerationMeta
  rerank?: SemanticRerankMeta
  filtering?: SemanticFilteringMeta
  [key: string]: unknown
}

export interface SemanticSearchResultSet {
  rows: SemanticResult[]
  meta?: SemanticSearchMeta
}

export interface SemanticSearchErrorInfo {
  code?: string
  backend?: string
  level?: string
  faissStatus?: string
  missingAssets?: string[]
}

export class SemanticSearchError extends Error {
  code?: string
  backend?: string
  level?: string
  faissStatus?: string
  missingAssets: string[]

  constructor(message: string, info: SemanticSearchErrorInfo = {}) {
    super(message)
    this.name = 'SemanticSearchError'
    this.code = info.code
    this.backend = info.backend
    this.level = info.level
    this.faissStatus = info.faissStatus
    this.missingAssets = info.missingAssets ?? []
  }
}

async function throwSemanticSearchError(error: unknown): Promise<never> {
  const response = (error as { response?: unknown } | null)?.response
  if (response instanceof Response) {
    const body = await response.clone().json().catch(() => ({})) as {
      detail?: unknown
      message?: unknown
    }
    const detail = body.detail && typeof body.detail === 'object'
      ? body.detail as Record<string, unknown>
      : {}
    const message = typeof detail.message === 'string'
      ? detail.message
      : typeof body.message === 'string'
        ? body.message
        : t('errors.client.semanticFailed', { status: response.status })
    throw new SemanticSearchError(message, {
      code: typeof detail.code === 'string' ? detail.code : undefined,
      backend: typeof detail.backend === 'string' ? detail.backend : undefined,
      level: typeof detail.level === 'string' ? detail.level : undefined,
      faissStatus: typeof detail.faissStatus === 'string' ? detail.faissStatus : undefined,
      missingAssets: Array.isArray(detail.missingAssets)
        ? detail.missingAssets.map((value) => String(value))
        : [],
    })
  }
  throw error
}

export async function semanticSearchWithMeta(
  params: SemanticSearchParams,
  options: { signal?: AbortSignal } = {}
): Promise<SemanticSearchResultSet> {
  const payload: Record<string, string | number> = { term: params.query }
  if (params.top_k) payload.top_n = params.top_k
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.backend) payload.backend = params.backend
  if (params.level) payload.level = params.level

  let raw: unknown
  try {
    raw = await api.post('analysis/embedding_search', { json: payload, signal: options.signal }).json()
  } catch (error) {
    return throwSemanticSearchError(error)
  }
  const response = validateResponse(SemanticSearchResponseSchema, raw, 'analysis/embedding_search')

  return {
    rows: response.rows.map((row, index) => ({
      doc_id: row.doc_id !== undefined ? String(row.doc_id) : `semantic-${index}`,
      chunk_id: row.chunk_id !== undefined ? String(row.chunk_id) : String(index),
      text: row.kw,
      score: row.score ?? 0,
      metadata: row.meta ?? undefined,
    })),
    meta: response.meta,
  }
}

export async function semanticSearch(
  params: SemanticSearchParams,
  options: { signal?: AbortSignal } = {}
): Promise<SemanticResult[]> {
  const result = await semanticSearchWithMeta(params, options)
  return result.rows
}

// ============================================
// Distributional Thesaurus (F8)
// ============================================

export interface SimilarWordsParams {
  term: string
  k?: number
  minScore?: number
  corpus?: string
  docsetId?: string
}

export interface SimilarWord {
  word: string
  /** Cosine similarity to the query term (0..1). Null if the backend omits it. */
  score: number | null
  /** Raw corpus frequency of the neighbour, joined from the frequency list. */
  corpusFrequency: number | null
  /** Explicit vector equality evidence from the backend, absent when unknown. */
  sharedQueryVector?: boolean | null
}

export interface SimilarWordsResult {
  term: string
  /** The embedding backend that produced the neighbours (e.g. `faiss`, `spacy`). */
  backend: string | null
  neighbours: SimilarWord[]
  /** True when embeddings are unavailable (404/501/503) — surface a soft message. */
  unavailable: boolean
}

/**
 * Thrown when the similar-words endpoint reports embeddings are unavailable
 * (HTTP 404/501/503), or the backend is missing the thesaurus surface entirely,
 * or it returns a 200 `{status:"unavailable"}` envelope. Callers should degrade
 * softly to an "Embeddings nicht verfügbar" state rather than treating this as a
 * hard error.
 */
export class SimilarWordsUnavailableError extends Error {
  readonly status: number
  /** The server's reason (`detail`), for example the pipeline without vectors. */
  readonly reason: string | null
  constructor(status: number, message: string = t('errors.client.embeddingsUnavailable'), reason: string | null = null) {
    super(message)
    this.name = 'SimilarWordsUnavailableError'
    this.status = status
    this.reason = reason
  }
}

/** Codes of a corpus without usable word vectors (422 and 503). */
const WORD_VECTORS_UNAVAILABLE_CODES = new Set(['word_vectors.unavailable', 'word_vectors.service_error'])

/**
 * Fetch a ranked distributional-thesaurus neighbour list for a term (F8).
 *
 * Backend contract: GET /api/v1/semantic/similar_words?term=&k=&min_score=&corpus=&docset_id=
 * → { status, term, backend, neighbours: [{ word, score, corpus_frequency }] }.
 *
 * Degrades softly: a 404/501/503 (no embeddings / route absent / index not
 * loaded) throws a typed {@link SimilarWordsUnavailableError} so the UI can show
 * a calm message.
 */
export async function getSimilarWords(
  params: SimilarWordsParams,
  options: { signal?: AbortSignal } = {}
): Promise<SimilarWordsResult> {
  const term = params.term.trim()
  if (!term) {
    return { term: '', backend: null, neighbours: [], unavailable: false }
  }
  const searchParams: Record<string, string | number> = { term }
  if (params.k !== undefined) searchParams.k = params.k
  if (params.minScore !== undefined) searchParams.min_score = params.minScore
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId

  let raw: unknown
  try {
    raw = await api.get('semantic/similar_words', { searchParams, signal: options.signal }).json()
  } catch (error) {
    const response = (error as { response?: unknown } | null)?.response
    // 404/501 = route absent, 503 = the server cannot load the word vectors,
    // 422 word_vectors.unavailable = the corpus has none. All of them mean
    // "no thesaurus": soft-degrade with the server's reason, not a hard error.
    if (response instanceof Response) {
      const code = await response.clone().json()
        .then((body: { code?: unknown }) => (typeof body?.code === 'string' ? body.code : null))
        .catch(() => null)
      const noVectors = response.status === 422 && code !== null && WORD_VECTORS_UNAVAILABLE_CODES.has(code)
      if (response.status === 404 || response.status === 501 || response.status === 503 || noVectors) {
        const reason = code !== null && WORD_VECTORS_UNAVAILABLE_CODES.has(code)
          ? await errorDetailFromFetchResponse(response)
          : null
        throw new SimilarWordsUnavailableError(response.status, undefined, reason)
      }
    }
    throw error
  }

  const response = validateResponse(SimilarWordsResponseSchema, raw, 'semantic/similar_words')
  // Backends report unavailability either as a 404/501 (handled above) or as a
  // 200 envelope with an explicit status. Treat the latter as a soft signal too.
  const status = (response.status ?? '').toLowerCase()
  if (status === 'unavailable' || status === 'not_available' || status === 'embeddings_unavailable') {
    throw new SimilarWordsUnavailableError(200)
  }
  const rawNeighbours = response.neighbours.length ? response.neighbours : (response.neighbors ?? [])
  const neighbours: SimilarWord[] = rawNeighbours.map((n) => ({
    word: n.word,
    sharedQueryVector: typeof n.shared_query_vector === 'boolean' ? n.shared_query_vector : null,
    score: typeof n.score === 'number' && Number.isFinite(n.score) ? n.score : null,
    corpusFrequency:
      typeof n.corpus_frequency === 'number' && Number.isFinite(n.corpus_frequency)
        ? n.corpus_frequency
        : null,
  }))

  return {
    term: response.term ?? term,
    backend: response.backend ?? null,
    neighbours,
    unavailable: false,
  }
}

// ============================================
// KWIC Annotation Layer (F7)
// ============================================

export interface AnnotationCategory {
  id: string
  label: string
  color?: string
  shortcut?: string | null
}

export interface AnnotationScheme {
  categories: AnnotationCategory[]
  revision: number
}

export interface AnnotationSchemeRemovalImpact {
  categoryId: string
  label: string
  annotationCount: number
  corpusCount: number
  annotatorCount: number
}

export interface AnnotationSchemePreview {
  status: 'ready' | 'stale'
  categories: AnnotationCategory[]
  revision: number
  removals: AnnotationSchemeRemovalImpact[]
  confirmationToken: string | null
}

export interface AnnotationRecord {
  categoryId: string | null
  note: string | null
  annotator: string | null
  updatedAt: number | string | null
}

export interface AnnotationsPayload {
  /** Keyed by stable `row_id` (`${file}:${pos}`, fallback text hash). */
  annotations: Record<string, AnnotationRecord>
  scheme: AnnotationScheme
}

export interface AnnotationWriteInput {
  categoryId?: string | null
  note?: string | null
  annotator?: string | null
}

function normalizeAnnotationRecord(raw: {
  category_id?: string | null
  note?: string | null
  annotator?: string | null
  updated_at?: number | string | null
}): AnnotationRecord {
  return {
    categoryId: raw.category_id ?? null,
    note: raw.note ?? null,
    annotator: raw.annotator ?? null,
    updatedAt: raw.updated_at ?? null,
  }
}

function annotationRecordPayload(raw: unknown): z.infer<typeof AnnotationRecordSchema> {
  const envelope = raw && typeof raw === 'object' && !Array.isArray(raw)
    ? raw as Record<string, unknown>
    : {}
  const payload = envelope.annotation && typeof envelope.annotation === 'object' && !Array.isArray(envelope.annotation)
    ? envelope.annotation
    : envelope
  return validateResponse(AnnotationRecordSchema, payload, 'annotations/{row_id}.annotation')
}

function normalizeScheme(raw: {
  categories?: Array<{ id: string; label: string; color?: string; shortcut?: string | null }>
  revision?: number
} | undefined): AnnotationScheme {
  return {
    categories: (raw?.categories ?? []).map((c) => ({
      id: c.id,
      label: c.label,
      color: c.color,
      shortcut: c.shortcut ?? null,
    })),
    revision: Number.isInteger(raw?.revision) && (raw?.revision ?? 0) >= 0
      ? raw?.revision ?? 0
      : 0,
  }
}

/**
 * Load all row-level annotations + the coding scheme for a corpus/docset (F7).
 *
 * Contract: GET /api/v1/annotations?corpus=&docset_id=&annotator=
 * → { status, annotations: { row_id: {category_id?, note?, annotator?, updated_at} },
 *     scheme: { categories: [{id,label,color,shortcut?}] } }.
 *
 * Defensive: a 404 (no annotations route / empty project) degrades to an empty
 * payload rather than throwing, so the KWIC table still renders.
 */
export async function getAnnotations(params: { corpus?: string; docsetId?: string; annotator?: string } = {}): Promise<AnnotationsPayload> {
  const searchParams: Record<string, string> = {}
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  if (params.annotator) searchParams.annotator = params.annotator
  let raw: unknown
  try {
    raw = await api.get('annotations', { searchParams }).json()
  } catch (error) {
    const response = (error as { response?: unknown } | null)?.response
    if (response instanceof Response && response.status === 404) {
      return { annotations: {}, scheme: { categories: [], revision: 0 } }
    }
    throw error
  }
  const response = validateResponse(AnnotationsResponseSchema, raw, 'annotations')
  const annotations: Record<string, AnnotationRecord> = {}
  for (const [rowId, record] of Object.entries(response.annotations ?? {})) {
    annotations[rowId] = normalizeAnnotationRecord(record)
  }
  return {
    annotations,
    scheme: normalizeScheme(response.scheme),
  }
}

/**
 * Create/update a single row annotation. Contract:
 * PUT /api/v1/annotations/{row_id}?corpus= with `{category_id?, note?, annotator?}`.
 *
 * `rowId` is the BARE backend id (`${docId}:${pos}` / `h:${hash}`); the active
 * corpus is sent as a separate `corpus` query param so the backend scopes
 * persistence per corpus. The UI keeps a corpus-namespaced key locally — see
 * `rowIdFor` / the annotations store — to prevent cross-corpus aliasing.
 */
export async function putAnnotation(
  rowId: string,
  input: AnnotationWriteInput,
  corpus?: string
): Promise<AnnotationRecord> {
  const payload: Record<string, unknown> = {}
  if (input.categoryId !== undefined) payload.category_id = input.categoryId
  if (input.note !== undefined) payload.note = input.note
  if (input.annotator !== undefined) payload.annotator = input.annotator
  const searchParams: Record<string, string> = {}
  if (corpus) searchParams.corpus = corpus
  const raw = await api
    .put(`annotations/${encodeURIComponent(rowId)}`, { json: payload, searchParams })
    .json<unknown>()
  return normalizeAnnotationRecord(annotationRecordPayload(raw))
}

/**
 * Delete a single row annotation. Contract:
 * DELETE /api/v1/annotations/{row_id}?corpus=&annotator=. `rowId` is the bare
 * backend id; `corpus` scopes the deletion to the active corpus. `annotator`
 * names the coder slot so the delete targets the SAME named slot the PUT wrote
 * (multi-coder / RBAC-off); without it the default "" slot is cleared instead
 * and IAA breaks (ANN-IAA-DELETE). The backend ignores it under a real RBAC
 * principal (it derives the annotator server-side), exactly like PUT.
 */
export async function deleteAnnotation(
  rowId: string,
  corpus?: string,
  annotator?: string
): Promise<{ status: string }> {
  const searchParams: Record<string, string> = {}
  if (corpus) searchParams.corpus = corpus
  if (annotator) searchParams.annotator = annotator
  return api.delete(`annotations/${encodeURIComponent(rowId)}`, { searchParams }).json<{ status: string }>()
}

/**
 * Load the coding scheme of a corpus. Contract: GET /api/v1/annotations/scheme.
 * Without a corpus the server answers with the project scheme, which applies to
 * every corpus that has no scheme of its own.
 */
export async function getAnnotationScheme(corpus?: string): Promise<AnnotationScheme> {
  let raw: unknown
  try {
    raw = await api.get('annotations/scheme', { searchParams: corpus ? { corpus } : {} }).json()
  } catch (error) {
    const response = (error as { response?: unknown } | null)?.response
    if (response instanceof Response && response.status === 404) {
      return { categories: [], revision: 0 }
    }
    throw error
  }
  const response = validateResponse(AnnotationSchemeSchema, raw, 'annotations/scheme')
  return normalizeScheme(response)
}

/** Review every schema change before persisting it. */
export async function previewAnnotationScheme(
  scheme: AnnotationScheme,
  expectedRevision = scheme.revision,
  corpus?: string,
): Promise<AnnotationSchemePreview> {
  const payload = {
    categories: scheme.categories.map((c) => ({
      id: c.id,
      label: c.label,
      color: c.color,
      shortcut: c.shortcut ?? null,
    })),
    expected_revision: expectedRevision,
  }
  const raw = await api.post('annotations/scheme/preview', {
    json: payload,
    searchParams: corpus ? { corpus } : {},
  }).json()
  const response = validateResponse(AnnotationSchemePreviewSchema, raw, 'annotations/scheme/preview')
  return {
    status: response.status,
    categories: normalizeScheme(response).categories,
    revision: response.revision,
    removals: response.removals.map((removal) => ({
      categoryId: removal.category_id,
      label: removal.label,
      annotationCount: removal.annotation_count,
      corpusCount: removal.corpus_count,
      annotatorCount: removal.annotator_count,
    })),
    confirmationToken: response.confirmation_token ?? null,
  }
}

/** Persist a reviewed coding scheme. The backend rejects stale or unconfirmed removals. */
export async function putAnnotationScheme(
  scheme: AnnotationScheme,
  options: { expectedRevision?: number; confirmationToken?: string | null; corpus?: string } = {},
): Promise<AnnotationScheme> {
  const payload = {
    categories: scheme.categories.map((c) => ({
      id: c.id,
      label: c.label,
      color: c.color,
      shortcut: c.shortcut ?? null,
    })),
    expected_revision: options.expectedRevision ?? scheme.revision,
    ...(options.confirmationToken ? { confirmation_token: options.confirmationToken } : {}),
  }
  const raw = await api.put('annotations/scheme', {
    json: payload,
    searchParams: options.corpus ? { corpus: options.corpus } : {},
  }).json()
  const response = validateResponse(AnnotationSchemeSchema, raw, 'annotations/scheme')
  return normalizeScheme(response)
}

// ============================================
// Inter-Annotator Agreement (FT-ANNOTATION-RESEARCH, r9)
// ============================================

/** Per-category percentage agreement across rows coded by ≥ 2 annotators. */
export interface AgreementPerCategory {
  categoryId: string
  agreement: number
}

/**
 * Inter-annotator agreement for the active corpus/docset. Every field is
 * optional/defensive: the endpoint is new in r9, so a 404 (or an older backend)
 * degrades to an empty, "no multi-coded rows" result rather than throwing.
 */
export interface AgreementResult {
  /** Number of rows coded by ≥ 2 annotators (the agreement denominator). */
  comparableRows: number
  /** Distinct annotators that contributed codings. */
  annotators: string[]
  /** Overall observed percentage agreement (0..1). */
  percentAgreement: number | null
  /** Cohen's kappa (exactly 2 annotators) or null when N/A. */
  cohensKappa: number | null
  /** Fleiss' kappa (≥ 2 annotators) or null when N/A. */
  fleissKappa: number | null
  /** Per-category percentage agreement. */
  perCategory: AgreementPerCategory[]
}

function normalizeAgreement(raw: Record<string, unknown> | null | undefined): AgreementResult {
  const r = raw ?? {}
  const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null)

  // The backend (routes/annotations.AgreementResponse) emits ONE `kappa` value
  // plus a `kappa_method` discriminator ("cohen" for exactly 2 coders, "fleiss"
  // for ≥3). Route it into the matching UI slot so Cohen's/Fleiss' κ never both
  // disappear (the previous reader looked for non-existent
  // `cohens_kappa`/`fleiss_kappa` fields, so kappa was always null).
  const kappa = num(r.kappa)
  const kappaMethod = typeof r.kappa_method === 'string' ? r.kappa_method.toLowerCase() : ''
  const isFleiss = kappaMethod.includes('fleiss')
  const cohensKappa = kappa !== null && !isFleiss ? kappa : null
  const fleissKappa = kappa !== null && isFleiss ? kappa : null

  // `per_category_agreement` is a backend DICT {category_id: agreement}; flatten
  // it to the UI's array shape. (Older/never-shipped shapes used a
  // `per_category[]` array — keep that as a defensive fallback.)
  const perCategoryObj = r.per_category_agreement
  let perCategory: AgreementPerCategory[]
  if (perCategoryObj && typeof perCategoryObj === 'object' && !Array.isArray(perCategoryObj)) {
    perCategory = Object.entries(perCategoryObj as Record<string, unknown>).map(([categoryId, agreement]) => ({
      categoryId: String(categoryId),
      agreement: num(agreement) ?? 0,
    }))
  } else {
    const perCategoryRaw = Array.isArray(r.per_category) ? (r.per_category as Array<Record<string, unknown>>) : []
    perCategory = perCategoryRaw.map((entry) => ({
      categoryId: String(entry.category_id ?? ''),
      agreement: num(entry.agreement) ?? 0,
    }))
  }

  return {
    // Backend field is `n_rows_overlap` (rows ≥2 coders both coded). Accept the
    // legacy `comparable_rows` name as a fallback.
    comparableRows: num(r.n_rows_overlap) ?? num(r.comparable_rows) ?? 0,
    annotators: Array.isArray(r.annotators) ? (r.annotators as unknown[]).map(String) : [],
    percentAgreement: num(r.percent_agreement),
    cohensKappa,
    fleissKappa,
    perCategory,
  }
}

/**
 * Raised when the backend declines a docset-scoped agreement request (422):
 * agreement is computed corpus-wide, not per docset. The store catches this to
 * show an informational notice and recompute without the docset filter.
 */
export class AnnotationAgreementDocsetUnsupportedError extends Error {
  constructor() {
    super(t('errors.client.agreementCorpusWide'))
    this.name = 'AnnotationAgreementDocsetUnsupportedError'
  }
}

/**
 * Load inter-annotator agreement. Contract:
 * GET /api/v1/annotations/agreement?corpus=. Defensive: a 404/501 (no route /
 * single-coder project) degrades to an empty agreement result. A backend 422
 * (docset scoping not supported) raises {@link AnnotationAgreementDocsetUnsupportedError}
 * so the store can recompute corpus-wide instead of showing a bare red error.
 */
export async function getAnnotationAgreement(
  params: { corpus?: string; docsetId?: string } = {}
): Promise<AgreementResult> {
  const searchParams: Record<string, string> = {}
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  try {
    const raw = await api.get('annotations/agreement', { searchParams }).json<Record<string, unknown>>()
    return normalizeAgreement(raw)
  } catch (error) {
    const response = (error as { response?: unknown } | null)?.response
    if (response instanceof Response && (response.status === 404 || response.status === 501)) {
      return normalizeAgreement(null)
    }
    if (response instanceof Response && response.status === 422) {
      throw new AnnotationAgreementDocsetUnsupportedError()
    }
    throw error
  }
}

// ── Multi-coder annotations, import, and settings (FT-ANNOTATION-RESEARCH) ──

/**
 * Full multi-coder annotation view for a corpus. Contract:
 * GET /api/v1/annotations/multi?corpus=&docset_id=
 * → { status, annotations: { row_id: { annotator: {category_id?, note?, …} } },
 *     scheme: { categories: [...] }, multi_coder: bool }.
 *
 * Unlike {@link getAnnotations} (one representative coding per row), this returns
 * EVERY coder's coding nested by annotator. The default/unnamed coder is the `""`
 * annotator key. Defensive: a 404 degrades to an empty multi-coder view.
 */
export interface MultiCoderAnnotationsPayload {
  /** `row_id -> { annotator -> record }`. The unnamed coder is the `""` key. */
  annotations: Record<string, Record<string, AnnotationRecord>>
  scheme: AnnotationScheme
  multiCoder: boolean
}

export async function getAnnotationsMulti(
  params: { corpus?: string; docsetId?: string } = {}
): Promise<MultiCoderAnnotationsPayload> {
  const searchParams: Record<string, string> = {}
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  let raw: unknown
  try {
    raw = await api.get('annotations/multi', { searchParams }).json()
  } catch (error) {
    const response = (error as { response?: unknown } | null)?.response
    if (response instanceof Response && (response.status === 404 || response.status === 501)) {
      return { annotations: {}, scheme: { categories: [], revision: 0 }, multiCoder: false }
    }
    throw error
  }
  const r = (raw ?? {}) as {
    annotations?: Record<string, Record<string, Record<string, unknown>>>
    scheme?: { categories?: Array<{ id: string; label: string; color?: string; shortcut?: string | null }> }
    multi_coder?: unknown
  }
  const annotations: Record<string, Record<string, AnnotationRecord>> = {}
  for (const [rowId, coders] of Object.entries(r.annotations ?? {})) {
    const perCoder: Record<string, AnnotationRecord> = {}
    for (const [annotator, record] of Object.entries(coders ?? {})) {
      perCoder[annotator] = normalizeAnnotationRecord(record ?? {})
    }
    annotations[rowId] = perCoder
  }
  return {
    annotations,
    scheme: normalizeScheme(r.scheme),
    multiCoder: r.multi_coder === true,
  }
}

/** One record in a bulk annotation import (exporter schema). */
export interface AnnotationImportRecord {
  rowId: string
  categoryId?: string | null
  note?: string | null
  annotator?: string
}

export interface AnnotationImportResult {
  status: string
  imported: number
  skipped: number
  dryRun: boolean
  errors: Array<Record<string, unknown>>
  previews: Array<Record<string, unknown>>
}

/**
 * Bulk-import row annotations (multi-coder aware). Contract:
 * POST /api/v1/annotations/import?corpus= with
 * `{ records: [{row_id, category_id?, note?, annotator?}], dry_run?, validate_categories? }`.
 */
export async function importAnnotations(
  records: AnnotationImportRecord[],
  options: { corpus?: string; dryRun?: boolean; validateCategories?: boolean } = {}
): Promise<AnnotationImportResult> {
  const searchParams: Record<string, string> = {}
  if (options.corpus) searchParams.corpus = options.corpus
  const payload: Record<string, unknown> = {
    records: records.map((rec) => {
      const out: Record<string, unknown> = { row_id: rec.rowId }
      if (rec.categoryId !== undefined) out.category_id = rec.categoryId
      if (rec.note !== undefined) out.note = rec.note
      if (rec.annotator !== undefined) out.annotator = rec.annotator
      return out
    }),
  }
  if (options.dryRun !== undefined) payload.dry_run = options.dryRun
  if (options.validateCategories !== undefined) payload.validate_categories = options.validateCategories
  const raw = await api.post('annotations/import', { json: payload, searchParams }).json<{
    status?: string
    imported?: number
    skipped?: number
    dry_run?: boolean
    errors?: Array<Record<string, unknown>>
    previews?: Array<Record<string, unknown>>
  }>()
  return {
    status: raw.status ?? 'ok',
    imported: typeof raw.imported === 'number' ? raw.imported : 0,
    skipped: typeof raw.skipped === 'number' ? raw.skipped : 0,
    dryRun: raw.dry_run === true,
    errors: Array.isArray(raw.errors) ? raw.errors : [],
    previews: Array.isArray(raw.previews) ? raw.previews : [],
  }
}

/**
 * Read the project's multi-coder annotation setting. Contract:
 * GET /api/v1/annotations/settings → { status, multi_coder: bool }. Defensive:
 * a 404 (older backend) degrades to `false` (single-coder default).
 */
export async function getAnnotationSettings(): Promise<{ multiCoder: boolean }> {
  try {
    const raw = await api.get('annotations/settings').json<{ multi_coder?: unknown }>()
    return { multiCoder: raw?.multi_coder === true }
  } catch (error) {
    const response = (error as { response?: unknown } | null)?.response
    if (response instanceof Response && (response.status === 404 || response.status === 501)) {
      return { multiCoder: false }
    }
    throw error
  }
}

/**
 * Toggle the project's multi-coder annotation mode. Contract:
 * PUT /api/v1/annotations/settings with `{ enabled: bool }` → { status, multi_coder }.
 * Manager-gated server-side. Returns the authoritative resulting state.
 */
export async function putAnnotationSettings(enabled: boolean): Promise<{ multiCoder: boolean }> {
  const raw = await api
    .put('annotations/settings', { json: { enabled } })
    .json<{ multi_coder?: unknown }>()
  return { multiCoder: raw?.multi_coder === true }
}

// ============================================
// Document API
// ============================================

export interface Document {
  doc_id: number
  doc: string
  meta: Record<string, string>
  text: string
  doc_start?: number
  doc_end?: number
}

export interface DocumentListItem {
  doc_id: number
  doc: string
  meta: Record<string, string>
  token_count: number
  preview: string
}

/** Fields the server names for the reader (see ReaderFieldsSchema). */
export interface ReaderFields {
  title_field: string | null
  label_fields: string[]
  basis?: string
}

export interface DocumentList {
  total: number
  offset: number
  limit: number
  items: DocumentListItem[]
  reader_fields?: ReaderFields
}

/**
 * Das Verzeichnis der Dokumente eines Korpus, blaetterbar.
 *
 * Bis heute gab es keinen Weg, die Texte eines Korpus einfach zu SEHEN:
 * die Dokumentsuche verlangt einen Begriff, der Volltext eine Nummer.
 */
export async function listDocuments(
  options: {
    corpus?: string
    offset?: number
    limit?: number
    docsetId?: string
    /** The active scope of the interface. The list holds documents in both docsets. */
    scopeDocsetId?: string
  } = {},
): Promise<DocumentList> {
  const searchParams: Record<string, string> = {}
  if (options.corpus) searchParams.corpus = options.corpus
  if (options.offset != null) searchParams.offset = String(options.offset)
  if (options.limit != null) searchParams.limit = String(options.limit)
  if (options.docsetId) searchParams.docset_id = options.docsetId
  if (options.scopeDocsetId) searchParams.scope_docset_id = options.scopeDocsetId
  const raw = await api.get('docs/list', { searchParams }).json()
  return validateResponse(DocumentListSchema, raw, 'docs/list')
}

export async function getDocument(docId: string, corpus?: string): Promise<Document> {
  const searchParams: Record<string, string> = {}
  if (corpus) searchParams.corpus = corpus
  const raw = await api.get(`document/${docId}`, { searchParams }).json()
  return validateResponse(DocumentSchema, raw, 'document/{doc_id}')
}

// ============================================
// N-Grams API
// ============================================

export interface NgramsParams {
  n?: number
  minFreq?: number
  limit?: number
  pos?: string
  corpus?: string
  docsetId?: string
  tokenCount?: number
}

export interface Ngram {
  tokens: string[]
  frequency: number
  relative: number
  n: number
}

export async function getNgrams(params: NgramsParams = {}): Promise<Ngram[]> {
  const n = params.n ?? 2
  const payload: Record<string, string | number> = {
    min_n: n,
    max_n: n,
  }
  if (typeof params.minFreq === 'number' && Number.isFinite(params.minFreq)) {
    payload.min_freq = Math.max(1, Math.round(params.minFreq))
  }
  if (params.limit) payload.limit = params.limit
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId

  const raw = await api.post('analysis/ngrams', { json: payload }).json()
  const response = validateResponse(NgramsResponseSchema, raw, 'analysis/ngrams')

  const rows = response.rows ?? []

  const totalFreqFromRows = rows.reduce((sum, row) => sum + row.freq, 0)
  const tokenCount = params.tokenCount && params.tokenCount > 0
    ? params.tokenCount
    : totalFreqFromRows
  const safeTokenCount = tokenCount > 0 ? tokenCount : 1

  return rows.map((row) => ({
    tokens: row.ngram.split(' ').filter(Boolean),
    frequency: row.freq,
    relative: row.freq / safeTokenCount,
    n: row.n,
  }))
}

// ============================================
// Keyness API
// ============================================

export interface KeynessParams {
  targetCorpus?: string
  referenceCorpus?: string
  targetDocsetId?: string
  referenceDocsetId?: string
  corpus?: string
  pos?: string
  limit?: number
}

export interface KeynessItem {
  word: string
  chi2_cell: number | null
  ll: number | null
  target_freq?: number
  reference_freq?: number
  target_per_million?: number
  reference_per_million?: number
  diff_per_million?: number
  direction?: string
  chi2_cell_signed?: number | null
  /** Signed log-likelihood (positive = over-represented in target). Default ordering key. */
  ll_signed?: number | null
  /** Effect size (log ratio) with its 95% confidence interval. */
  log_ratio?: number | null
  log_ratio_ci_low?: number | null
  log_ratio_ci_high?: number | null
  /** Significance and multiple-comparison correction. */
  p_value?: number | null
  q_value?: number | null
  bic?: number | null
}

export async function getKeyness(params: KeynessParams): Promise<KeynessItem[]> {
  const payload: Record<string, string | number> = {}
  if (params.targetDocsetId && params.referenceDocsetId) {
    payload.target_docset_id = params.targetDocsetId
    payload.reference_docset_id = params.referenceDocsetId
    payload.corpus = params.corpus ?? 'default'
  } else {
    payload.target_corpus = params.targetCorpus ?? 'default'
    payload.reference_corpus = params.referenceCorpus ?? 'default'
  }
  if (params.pos) payload.pos = params.pos
  if (params.limit && params.limit > 0) payload.limit = params.limit

  const raw = await api.post('analysis/keyness', { json: payload }).json()
  const response = validateResponse(KeynessResponseSchema, raw, 'analysis/keyness')
  if (response.limitations?.length) {
    const message = response.limitations.map((item) => item.message).filter(Boolean).join(' · ')
    throw new Error(message || t('errors.client.keynessLimited'))
  }

  let rows = response.rows ?? []
  // Default ordering by signed log-likelihood (over-represented words lead);
  // the unsigned chi-square cell contribution is the fallback.
  const orderKey = (row: { ll_signed?: number | null; chi2_cell?: number | null }) =>
    row.ll_signed ?? row.chi2_cell ?? -Infinity
  rows = [...rows].sort((a, b) => orderKey(b) - orderKey(a))

  if (params.limit && params.limit > 0) {
    rows = rows.slice(0, params.limit)
  }

  return rows.map((row) => ({
    word: row.word,
    chi2_cell: row.chi2_cell ?? null,
    ll: row.ll ?? null,
    target_freq: row.target_freq,
    reference_freq: row.reference_freq,
    target_per_million: row.target_per_million,
    reference_per_million: row.reference_per_million,
    diff_per_million: row.diff_per_million,
    direction: row.direction,
    chi2_cell_signed: row.chi2_cell_signed ?? null,
    ll_signed: row.ll_signed ?? null,
    log_ratio: row.log_ratio ?? null,
    log_ratio_ci_low: row.log_ratio_ci_low ?? null,
    log_ratio_ci_high: row.log_ratio_ci_high ?? null,
    p_value: row.p_value ?? null,
    q_value: row.q_value ?? null,
    bic: row.bic ?? null,
  }))
}

// ============================================
// Word Sketch API
// ============================================

export interface WordSketchParams {
  term: string
  limit?: number
  docsetId?: string
  corpus?: string
}

export interface WordSketchRelation {
  relation: string
  words: Array<{ word: string; score: number | null; frequency: number | null }>
  rowLimit?: number | null
  totalCandidates?: number | null
  totalRows?: number | null
  truncated?: boolean | null
  minFreq?: number | null
}

export interface WordSketchResult {
  term: string
  /**
   * The word form the sketch counts (exact, else lower case), null for a
   * query-language node or an older server. Rows open the concordance of
   * node, relation and collocate from it.
   */
  node?: string | null
  relations: WordSketchRelation[]
  /**
   * Backend-provided gloss map: relation code -> human-readable German label.
   * The r9 backend returns this as a sibling `relations` block
   * (`relations[code] = { relation, label }`). May be empty for older backends.
   */
  relationLabels: Record<string, string>
  method?: MethodBlock
}

/** Keys in the wordsketch response that are NOT grammatical relations. */
const WORD_SKETCH_RESERVED_KEYS = new Set(['sketches', 'relations', 'method', 'node'])

export async function getWordSketch(
  params: WordSketchParams,
  options: { signal?: AbortSignal } = {}
): Promise<WordSketchResult> {
  const payload: Record<string, string | number> = { term: params.term }
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.limit !== undefined && params.limit > 0) payload.limit = Math.max(1, params.limit)
  const response = await api.post('analysis/wordsketch', {
    json: payload,
    signal: options.signal,
  }).json<Record<string, unknown>>()

  // The r7 backend reshape nests the relations under `sketches` and attaches a
  // sibling `method` block: {sketches: {<rel>: [...]}, method: {...}, ...}.
  // Older backends returned the relation map at the top level. Prefer the
  // nested `sketches` object when present; otherwise treat the whole response
  // as the relation map (back-compat). Either way, skip reserved keys and only
  // map array-valued entries so an object value never reaches `.slice`.
  const sketches = (response as { sketches?: unknown })?.sketches
  const relationMap: Record<string, unknown> =
    sketches && typeof sketches === 'object' && !Array.isArray(sketches)
      ? (sketches as Record<string, unknown>)
      : ((response ?? {}) as Record<string, unknown>)

  // r9 sibling gloss map: relations[code] = { relation, label }. Flatten it to
  // a plain code -> label record so the UI can show "Subjekt von" instead of
  // raw parser codes like "SB REV". Tolerate missing/odd shapes (older
  // backends omit it; only string labels are kept).
  const relationLabels: Record<string, string> = {}
  const relationMeta: Record<string, Omit<WordSketchRelation, 'relation' | 'words'>> = {}
  const rawRelations = (response as { relations?: unknown })?.relations
  if (rawRelations && typeof rawRelations === 'object' && !Array.isArray(rawRelations)) {
    for (const [code, value] of Object.entries(rawRelations as Record<string, unknown>)) {
      const record = value as Record<string, unknown>
      const label = record?.label
      if (typeof label === 'string' && label.length > 0) {
        relationLabels[code] = label
      }
      relationMeta[code] = {
        rowLimit: typeof record?.row_limit === 'number' ? record.row_limit : null,
        totalCandidates: typeof record?.total_candidates === 'number' ? record.total_candidates : null,
        totalRows: typeof record?.total_rows === 'number' ? record.total_rows : null,
        truncated: typeof record?.truncated === 'boolean' ? record.truncated : null,
        minFreq: typeof record?.min_freq === 'number' ? record.min_freq : null,
      }
    }
  }

  const relations: WordSketchRelation[] = Object.entries(relationMap)
    .filter(([relation, rows]) => !WORD_SKETCH_RESERVED_KEYS.has(relation) && Array.isArray(rows))
    .map(([relation, rows]) => {
      const list = rows as Array<{
        word: string
        score?: number
        f?: number
        frequency?: number
      }>
      return {
        relation,
        ...relationMeta[relation],
        words: list
          .slice(0, params.limit && params.limit > 0 ? params.limit : list.length)
          .map((row) => ({
            word: row.word,
            score: row.score ?? null,
            frequency: row.frequency ?? row.f ?? null,
          })),
      }
    })

  const node = (response as { node?: unknown })?.node
  return {
    term: params.term,
    node: typeof node === 'string' && node ? node : null,
    relations,
    relationLabels,
    method: coerceMethodBlock((response as { method?: unknown })?.method),
  }
}

// ============================================
// Word Sketch Difference API (FT-SKETCH-DIFF-DISTRIBUTION, r9)
// ============================================

export interface WordSketchDiffParams {
  termA: string
  termB: string
  limit?: number
  corpus?: string
  docsetId?: string
}

/** A collocate that appears for both terms, with per-term scores and a delta. */
export interface WordSketchDiffCommon {
  word: string
  scoreA: number | null
  scoreB: number | null
  frequencyA: number | null
  frequencyB: number | null
  /** scoreA − scoreB (positive = stronger for term A). */
  delta: number | null
}

export interface WordSketchDiffOnly {
  word: string
  score: number | null
  frequency: number | null
}

export interface WordSketchDiffRelation {
  relation: string
  onlyA: WordSketchDiffOnly[]
  onlyB: WordSketchDiffOnly[]
  common: WordSketchDiffCommon[]
}

export interface WordSketchDiffResult {
  termA: string
  termB: string
  /** The word forms the two sides count, null for a query-language node. */
  nodeA?: string | null
  nodeB?: string | null
  relations: WordSketchDiffRelation[]
  relationLabels: Record<string, string>
  method?: MethodBlock
}

function diffRelationsClientSide(
  a: WordSketchResult,
  b: WordSketchResult,
  limit?: number
): WordSketchDiffRelation[] {
  const byRelationB = new Map(b.relations.map((rel) => [rel.relation, rel]))
  const relations: WordSketchDiffRelation[] = []
  const seenRelations = new Set<string>()
  const buildFor = (relation: string, relA?: WordSketchRelation, relB?: WordSketchRelation) => {
    const wordsA = new Map((relA?.words ?? []).map((w) => [w.word, w]))
    const wordsB = new Map((relB?.words ?? []).map((w) => [w.word, w]))
    const common: WordSketchDiffCommon[] = []
    const onlyA: WordSketchDiffOnly[] = []
    const onlyB: WordSketchDiffOnly[] = []
    for (const [word, rowA] of wordsA) {
      if (wordsB.has(word)) {
        const rowB = wordsB.get(word)
        const scoreA = rowA.score ?? null
        const scoreB = rowB?.score ?? null
        common.push({
          word,
          scoreA,
          scoreB,
          frequencyA: rowA.frequency ?? null,
          frequencyB: rowB?.frequency ?? null,
          delta: typeof scoreA === 'number' && typeof scoreB === 'number' ? scoreA - scoreB : null,
        })
      } else {
        onlyA.push({ word, score: rowA.score ?? null, frequency: rowA.frequency ?? null })
      }
    }
    for (const [word, rowB] of wordsB) {
      if (!wordsA.has(word)) {
        onlyB.push({ word, score: rowB.score ?? null, frequency: rowB.frequency ?? null })
      }
    }
    common.sort((x, y) => Math.abs(y.delta ?? 0) - Math.abs(x.delta ?? 0))
    const cap = limit && limit > 0 ? limit : undefined
    relations.push({
      relation,
      onlyA: cap ? onlyA.slice(0, cap) : onlyA,
      onlyB: cap ? onlyB.slice(0, cap) : onlyB,
      common: cap ? common.slice(0, cap) : common,
    })
  }
  for (const relA of a.relations) {
    seenRelations.add(relA.relation)
    buildFor(relA.relation, relA, byRelationB.get(relA.relation))
  }
  for (const relB of b.relations) {
    if (seenRelations.has(relB.relation)) continue
    buildFor(relB.relation, undefined, relB)
  }
  return relations
}

/**
 * Two-term word-sketch contrast (FT-SKETCH-DIFF-DISTRIBUTION). Uses the
 * dedicated `POST /analysis/wordsketch_diff` contract. Only a clearly missing
 * legacy endpoint (404/501) degrades to two single-term sketches; other errors
 * must stay visible because a client-side diff is different method evidence.
 */
export async function getWordSketchDiff(
  params: WordSketchDiffParams,
  options: { signal?: AbortSignal } = {}
): Promise<WordSketchDiffResult> {
  const payload: Record<string, string | number> = {
    term_a: params.termA,
    term_b: params.termB,
  }
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.limit !== undefined && params.limit > 0) payload.limit = Math.max(1, params.limit)

  // Map a single only_a/only_b sketch row to the UI shape. The backend keeps the
  // raw sketch row keys (`word` + `score`/ll/chi2_cell…); `collocate` is accepted
  // as a defensive alias in case the wire field is renamed.
  const mapOnlyRow = (w: Record<string, unknown>) => ({
    word: String(w.word ?? w.collocate ?? ''),
    score:
      typeof w.score === 'number'
        ? w.score
        : typeof w.ll === 'number'
          ? w.ll
          : typeof w.chi2_cell === 'number'
            ? w.chi2_cell
            : null,
    frequency:
      typeof w.frequency === 'number'
        ? w.frequency
        : typeof w.f === 'number'
          ? w.f
          : null,
  })
  // Map a single `common` row (per-term scores + delta).
  const mapCommonRow = (w: Record<string, unknown>): WordSketchDiffCommon => {
    const scoreA = typeof w.score_a === 'number' ? w.score_a : null
    const scoreB = typeof w.score_b === 'number' ? w.score_b : null
    return {
      word: String(w.word ?? w.collocate ?? ''),
      scoreA,
      scoreB,
      frequencyA:
        typeof w.f_a === 'number'
          ? w.f_a
          : typeof w.frequency_a === 'number'
            ? w.frequency_a
            : null,
      frequencyB:
        typeof w.f_b === 'number'
          ? w.f_b
          : typeof w.frequency_b === 'number'
            ? w.frequency_b
            : null,
      delta:
        typeof w.delta === 'number'
          ? w.delta
          : scoreA !== null && scoreB !== null
            ? scoreA - scoreB
            : null,
    }
  }
  const buildRelation = (relation: string, r: Record<string, unknown>): WordSketchDiffRelation => ({
    relation,
    onlyA: (Array.isArray(r.only_a) ? (r.only_a as Array<Record<string, unknown>>) : []).map(mapOnlyRow),
    onlyB: (Array.isArray(r.only_b) ? (r.only_b as Array<Record<string, unknown>>) : []).map(mapOnlyRow),
    common: (Array.isArray(r.common) ? (r.common as Array<Record<string, unknown>>) : []).map(mapCommonRow),
  })

  let useLegacyFallback = false
  try {
    const raw = await api
      .post('analysis/wordsketch_diff', { json: payload, signal: options.signal })
      .json<Record<string, unknown>>()
    const rawRelations = (raw as { relations?: unknown }).relations
    // The dedicated endpoint emits `label_a`/`label_b` — prefer those over the
    // request terms so the cross-docset mode ("<term> @ <docset>") labels show.
    const labelA = typeof (raw as { label_a?: unknown }).label_a === 'string'
      ? ((raw as { label_a: string }).label_a)
      : params.termA
    const labelB = typeof (raw as { label_b?: unknown }).label_b === 'string'
      ? ((raw as { label_b: string }).label_b)
      : params.termB
    const method = coerceMethodBlock((raw as { method?: unknown }).method)
    const nodeOf = (value: unknown) => (typeof value === 'string' && value ? value : null)
    const nodes = {
      nodeA: nodeOf((raw as { node_a?: unknown }).node_a),
      nodeB: nodeOf((raw as { node_b?: unknown }).node_b),
    }
    const rawRelationLabels = (raw as { relation_labels?: unknown }).relation_labels
    const relationLabels: Record<string, string> = {}
    if (rawRelationLabels && typeof rawRelationLabels === 'object' && !Array.isArray(rawRelationLabels)) {
      for (const [relation, label] of Object.entries(rawRelationLabels as Record<string, unknown>)) {
        if (typeof label === 'string' && label.length > 0) {
          relationLabels[relation] = label
        }
      }
    }

    // PRIMARY (current backend): `relations` is a DICT keyed by relation name,
    // each value an object with `common`/`only_a`/`only_b` arrays. The previous
    // `Array.isArray` guard never matched this and so always fell through to the
    // two-sketch client-side fallback — leaving the dedicated endpoint dead.
    if (rawRelations && typeof rawRelations === 'object' && !Array.isArray(rawRelations)) {
      const relations: WordSketchDiffRelation[] = Object.entries(
        rawRelations as Record<string, unknown>
      ).map(([relation, value]) =>
        buildRelation(relation, (value && typeof value === 'object' ? value : {}) as Record<string, unknown>)
      )
      return { termA: labelA, termB: labelB, ...nodes, relations, relationLabels, method }
    }

    // BACK-COMPAT: a top-level relations ARRAY where each entry carries its own
    // `relation` name.
    if (Array.isArray(rawRelations)) {
      const relations: WordSketchDiffRelation[] = rawRelations.map((rel) => {
        const r = (rel && typeof rel === 'object' ? rel : {}) as Record<string, unknown>
        return buildRelation(String(r.relation ?? ''), r)
      })
      return { termA: labelA, termB: labelB, ...nodes, relations, relationLabels, method }
    }
    throw new Error('analysis/wordsketch_diff returned an unsupported response shape')
  } catch (err) {
    if (isAbortError(err)) throw err
    if (!isLegacyEndpointUnavailable(err)) throw err
    useLegacyFallback = true
  }

  if (!useLegacyFallback) {
    throw new Error('analysis/wordsketch_diff fallback state was not reachable')
  }

  // Legacy fallback: two single-term sketches diffed locally.
  const [a, b] = await Promise.all([
    getWordSketch({ term: params.termA, limit: params.limit, corpus: params.corpus, docsetId: params.docsetId }, options),
    getWordSketch({ term: params.termB, limit: params.limit, corpus: params.corpus, docsetId: params.docsetId }, options),
  ])
  return {
    termA: params.termA,
    termB: params.termB,
    nodeA: a.node ?? null,
    nodeB: b.node ?? null,
    relations: diffRelationsClientSide(a, b, params.limit),
    relationLabels: { ...a.relationLabels, ...b.relationLabels },
  }
}

// ============================================
// Lexical Diversity API (F4)
// ============================================

/**
 * Per-side lexical-diversity figures, present when the endpoint resolves a
 * Human-vs-AI (or A-vs-B) comparison. Each value is optional/defensive.
 */
export interface LexicalDiversitySide {
  label?: string
  ttr?: number | null
  sttr?: number | null
  sttr_window?: number | null
  guiraud?: number | null
  mattr?: number | null
  n_tokens?: number | null
  n_types?: number | null
}

/**
 * GET /api/v1/analysis/lexical-diversity response (F4).
 * TTR is length-confounded; STTR/MATTR are the comparable measures when the
 * sides differ in size, hence `sttr_window` is always reported.
 */
export interface LexicalDiversityResult {
  ttr?: number | null
  sttr?: number | null
  sttr_window?: number | null
  guiraud?: number | null
  mattr?: number | null
  n_tokens?: number | null
  n_types?: number | null
  per_side?: LexicalDiversitySide[]
  basis?: string
  /**
   * Backend-emitted caveat when the two compared sides differ markedly in size
   * (the reason STTR/MATTR are preferred over TTR). When present, this is the
   * authoritative warning to render; the client's `lengthConfounded` heuristic
   * is only a fallback.
   */
  size_warning?: string
  limitations?: Array<{ code?: string; message?: string; [key: string]: unknown }>
}

export interface LexicalDiversityParams {
  corpus?: string
  docsetId?: string
  /** Optional comparison sides as resolved docset ids (e.g. human vs AI). */
  targetDocsetId?: string
  referenceDocsetId?: string
  /** STTR/MATTR sliding-window size in tokens (backend default applies if omitted). */
  window?: number
}

function asNullableNumber(value: unknown): number | null | undefined {
  if (value === null) return null
  if (typeof value === 'number' && Number.isFinite(value)) return value
  return undefined
}

function coerceDiversitySide(
  raw: Record<string, unknown>,
  labelFallback?: string
): LexicalDiversitySide {
  return {
    label: typeof raw.label === 'string' ? raw.label : labelFallback,
    ttr: asNullableNumber(raw.ttr),
    sttr: asNullableNumber(raw.sttr),
    sttr_window: asNullableNumber(raw.sttr_window),
    guiraud: asNullableNumber(raw.guiraud),
    mattr: asNullableNumber(raw.mattr),
    n_tokens: asNullableNumber(raw.n_tokens),
    n_types: asNullableNumber(raw.n_types),
  }
}

// Canonical ordering for the two-sided comparison so target renders first.
const PER_SIDE_KEY_ORDER = ['target', 'reference']

/**
 * Normalize the backend `per_side` figures into an ordered array.
 *
 * The r7 backend emits a DICT keyed by side, e.g.
 * `{target: {...}, reference: {...}}`, plus possibly extra named sides. We map
 * it to an ordered array `[target, reference, ...rest]` and inject the dict key
 * as a `label` fallback when the side carries no explicit label. The legacy
 * array form is preserved for forward/backward compatibility.
 */
function coercePerSide(raw: unknown): LexicalDiversitySide[] | undefined {
  if (Array.isArray(raw)) {
    return raw.map((side) => coerceDiversitySide(side as Record<string, unknown>))
  }
  if (raw && typeof raw === 'object') {
    const dict = raw as Record<string, unknown>
    const keys = Object.keys(dict)
    if (keys.length === 0) return undefined
    const ordered = [
      ...PER_SIDE_KEY_ORDER.filter((k) => k in dict),
      ...keys.filter((k) => !PER_SIDE_KEY_ORDER.includes(k)),
    ]
    return ordered
      .filter((key) => dict[key] && typeof dict[key] === 'object')
      .map((key) => coerceDiversitySide(dict[key] as Record<string, unknown>, key))
  }
  return undefined
}

/**
 * Fetch lexical-diversity figures (TTR / STTR / Guiraud / MATTR), optionally
 * per comparison side. Defensive: any missing field is simply absent and the
 * caller renders what it has.
 */
export async function getLexicalDiversity(
  params: LexicalDiversityParams = {},
  options: { signal?: AbortSignal } = {}
): Promise<LexicalDiversityResult> {
  const searchParams: Record<string, string | number> = {}
  if (params.corpus) searchParams.corpus = params.corpus
  if (params.docsetId) searchParams.docset_id = params.docsetId
  if (params.targetDocsetId) searchParams.target_docset_id = params.targetDocsetId
  if (params.referenceDocsetId) searchParams.reference_docset_id = params.referenceDocsetId
  // Backend reads `sttr_window` (routes/analysis.py). A bare `window` is silently
  // ignored, so always send the canonical key.
  if (params.window !== undefined && params.window > 0) searchParams.sttr_window = params.window

  const raw = await longRunningApi
    .get('analysis/lexical-diversity', { searchParams, signal: options.signal })
    .json<Record<string, unknown>>()

  const perSideRaw = coercePerSide(raw.per_side)
  const limitations = Array.isArray(raw.limitations)
    ? (raw.limitations as Array<Record<string, unknown>>).map((item) => ({
        code: typeof item.code === 'string' ? item.code : undefined,
        message: typeof item.message === 'string' ? item.message : undefined,
        ...item,
      }))
    : undefined

  return {
    ttr: asNullableNumber(raw.ttr),
    sttr: asNullableNumber(raw.sttr),
    sttr_window: asNullableNumber(raw.sttr_window),
    guiraud: asNullableNumber(raw.guiraud),
    mattr: asNullableNumber(raw.mattr),
    n_tokens: asNullableNumber(raw.n_tokens),
    n_types: asNullableNumber(raw.n_types),
    per_side: perSideRaw,
    basis: typeof raw.basis === 'string' ? raw.basis : undefined,
    size_warning: typeof raw.size_warning === 'string' ? raw.size_warning : undefined,
    limitations,
  }
}

// ============================================
// Preferences API (/prefs)
// ============================================

export interface PrefsState {
  prefs: Record<string, string>
  bookmarks?: Array<{ left: string; kw: string; right: string }>
}

export async function getPrefs(project = 'default'): Promise<PrefsState> {
  const data = await api.get('prefs', { searchParams: { project } }).json()
  return validateResponse(PrefsStateSchema, data, 'prefs')
}

export async function updatePrefs(
  prefs: Record<string, unknown>,
  project = 'default'
): Promise<void> {
  // The backend stores values as strings. We stringify non-string values.
  const payload: Record<string, string> = { project }
  for (const [key, value] of Object.entries(prefs)) {
    payload[key] = typeof value === 'string' ? value : JSON.stringify(value)
  }
  await api.post('prefs/update', { json: payload })
}

// ============================================
// Analysis Presets API
// ============================================

export interface AnalysisPresetRecord {
  id: string
  name: string
  type: string
  corpus: string
  docset?: unknown | null
  query_term?: string
  params?: Record<string, unknown>
  result?: unknown
  result_meta?: Record<string, unknown>
  status?: string
  job_id?: string
  kind?: string
  created_at?: number
  updated_at?: number
  last_accessed_at?: number
}

export async function getAnalysisPresets(project = 'default'): Promise<AnalysisPresetRecord[]> {
  const data = await api.get(`projects/${project}/analysis-presets`).json()
  const parsed = validateResponse(AnalysisPresetsResponseSchema, data, 'analysis-presets')
  return parsed.presets ?? []
}

export async function createAnalysisPreset(
  preset: AnalysisPresetRecord,
  project = 'default'
): Promise<AnalysisPresetRecord> {
  const data = await presetApi.post(`projects/${project}/analysis-presets`, { json: preset }).json()
  return validateResponse(AnalysisPresetSchema, data, 'analysis-presets/create')
}

export async function updateAnalysisPreset(
  presetId: string,
  patch: Partial<AnalysisPresetRecord>,
  project = 'default'
): Promise<AnalysisPresetRecord> {
  const data = await presetApi.patch(`projects/${project}/analysis-presets/${presetId}`, { json: patch }).json()
  return validateResponse(AnalysisPresetSchema, data, 'analysis-presets/update')
}

export async function touchAnalysisPreset(presetId: string, project = 'default'): Promise<AnalysisPresetRecord> {
  const data = await presetApi.post(`projects/${project}/analysis-presets/${presetId}/touch`).json()
  return validateResponse(AnalysisPresetSchema, data, 'analysis-presets/touch')
}

export async function deleteAnalysisPreset(presetId: string, project = 'default'): Promise<void> {
  await api.delete(`projects/${project}/analysis-presets/${presetId}`)
}

// ============================================
// Export API
// ============================================

/**
 * Server-side concordance export (F2). Re-runs the query against the active
 * docset/sort/case, returns the exact match count, and streams bounded rows
 * rather than pretending a client-loaded window is a complete result set.
 *
 * CONTRACT (Track F2 backend): POST /api/v1/export/concordance with a JSON
 * body, returning a StreamingResponse with Content-Disposition: attachment.
 * POST keeps complex CQLF queries and long docset/sort payloads out of URL
 * limits.
 */
export type ExportConcordanceFormat = 'csv' | 'tsv' | 'json' | 'jsonl' | 'xlsx'

export interface ExportConcordanceParams {
  query: string
  corpus?: string
  docsetId?: string
  context?: number
  sort?: string | null
  sortDir?: QuerySortDir
  caseInsensitive?: boolean
  format?: ExportConcordanceFormat
  /**
   * Excel-friendly CSV dialect (`;` delimiter + UTF-8 BOM). CSV only; the
   * default output stays byte-identical when omitted.
   */
  excelDe?: boolean
}

export interface ExportConcordanceResult {
  blob: Blob
  filename: string
  /** Exact number of matches in the requested query and scope. */
  total: number | null
  /** Explicit aliases make a capped row stream impossible to mistake for total. */
  totalMatches?: number | null
  exportedRows?: number | null
  exportCap?: number | null
  truncated: boolean
}

export interface ExportEvidencePackageParams {
  query: string
  corpus?: string
  docsetId?: string
  context?: number
  sort?: string | null
  sortDir?: QuerySortDir
  caseInsensitive?: boolean
  includeRows?: boolean
}

export interface ExportEvidencePackage {
  schema_version: 'candyconc-evidence-package-v1'
  package_id: string
  generated_at: string
  query_trace_id: string
  scope: Record<string, unknown>
  corpus: Record<string, unknown>
  result_summary: {
    /** Legacy capped collection count; never use as an exact denominator. */
    observed_hit_count: number
    /** Present in current packages; absent in older packages. */
    total_matches?: number
    exported_rows?: number
    export_cap?: number
    rows_included: number
    truncated: boolean
    complete_within_export_cap: boolean
    row_hash_sha256: string
  }
  method_blocks: Array<Record<string, unknown>>
  rows?: Array<Record<string, unknown>>
}

function parseContentDispositionFilename(header: string | null): string | null {
  if (!header) return null
  // Prefer RFC 5987 filename*=UTF-8''… then fall back to plain filename="…".
  const star = header.match(/filename\*=(?:UTF-8'')?([^;]+)/i)
  if (star?.[1]) {
    try {
      return decodeURIComponent(star[1].trim().replace(/^"|"$/g, ''))
    } catch {
      return star[1].trim().replace(/^"|"$/g, '')
    }
  }
  const plain = header.match(/filename="?([^";]+)"?/i)
  return plain?.[1]?.trim() ?? null
}

function parseNonNegativeIntegerHeader(header: string | null): number | null {
  if (header === null || !/^\d+$/.test(header.trim())) return null
  const value = Number(header)
  return Number.isSafeInteger(value) ? value : null
}

export async function getExportConcordance(
  params: ExportConcordanceParams,
  options: { signal?: AbortSignal } = {}
): Promise<ExportConcordanceResult> {
  const format = params.format ?? 'csv'
  const payload: Record<string, unknown> = {
    query: params.query,
    format,
  }
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.context !== undefined) payload.ctx = params.context
  if (params.sort && params.sort !== 'position') payload.sort = params.sort
  if (params.sortDir) payload.sort_dir = params.sortDir
  if (params.caseInsensitive !== undefined) {
    payload.case_insensitive = params.caseInsensitive
  }
  if (params.excelDe && format === 'csv') payload.excel_de = true

  const response = await fetch('/api/v1/export/concordance', {
    method: 'POST',
    headers: await withAuthHeadersReady({ 'Content-Type': 'application/json' }),
    body: JSON.stringify(payload),
    signal: options.signal,
  })
  if (!response.ok) {
    const detail = await response.text().catch(() => '')
    throw new Error(detail || t('errors.client.exportFailed', { status: response.status }))
  }
  const blob = await response.blob()
  const ext = format
  const fallback = `candyconc_concordance_${new Date().toISOString().slice(0, 10)}.${ext}`
  const filename = parseContentDispositionFilename(
    response.headers.get('Content-Disposition')
  ) ?? fallback
  const totalMatches = parseNonNegativeIntegerHeader(
    response.headers.get('X-CandyConc-Export-Total-Matches')
      ?? response.headers.get('X-CandyConc-Export-Total'),
  )
  const exportedRows = parseNonNegativeIntegerHeader(
    response.headers.get('X-CandyConc-Export-Exported-Rows'),
  )
  const exportCap = parseNonNegativeIntegerHeader(
    response.headers.get('X-CandyConc-Export-Cap'),
  )
  const truncated = response.headers.get('X-CandyConc-Export-Truncated') === '1'
  return {
    blob,
    filename,
    total: totalMatches,
    totalMatches,
    exportedRows,
    exportCap,
    truncated,
  }
}

export async function exportPdf(markdown: string): Promise<Blob> {
  return api.post('export/pdf', { json: { markdown } }).blob()
}

export async function exportDocx(markdown: string): Promise<Blob> {
  return api.post('export/docx', { json: { markdown } }).blob()
}

export async function getExportEvidencePackage(
  params: ExportEvidencePackageParams,
  options: { signal?: AbortSignal } = {}
): Promise<ExportEvidencePackage> {
  const payload: Record<string, unknown> = {
    query: params.query,
    include_rows: params.includeRows ?? true,
  }
  if (params.corpus) payload.corpus = params.corpus
  if (params.docsetId) payload.docset_id = params.docsetId
  if (params.context !== undefined) payload.ctx = params.context
  if (params.sort && params.sort !== 'position') payload.sort = params.sort
  if (params.sortDir) payload.sort_dir = params.sortDir
  if (params.caseInsensitive !== undefined) {
    payload.case_insensitive = params.caseInsensitive
  }
  return api.post('export/evidence-package', {
    json: payload,
    signal: options.signal,
  }).json<ExportEvidencePackage>()
}

// ============================================
// Settings API
// ============================================

export interface UserSettings {
  language: string
  theme: 'light' | 'dark' | 'system' | 'pink'
  defaultContext: number
  defaultCorpus?: string
  fontSize: 'sm' | 'base' | 'lg'
  showLineNumbers: boolean
  highlightColor: string
}

const DEFAULT_SETTINGS: UserSettings = {
  language: 'de',
  theme: 'system',
  defaultContext: 5,
  defaultCorpus: 'default',
  fontSize: 'base',
  showLineNumbers: true,
  highlightColor: 'yellow',
}

function parseBoolean(value: string | undefined, fallback: boolean): boolean {
  if (value === undefined) return fallback
  return value === 'true' || value === '1'
}

function parseNumber(value: string | undefined, fallback: number): number {
  if (value === undefined) return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

export async function getSettings(): Promise<UserSettings> {
  try {
    const state = await getPrefs()
    const prefs = state.prefs ?? {}

    const theme = prefs.theme
    const fontSize = prefs.fontSize

    return {
      language: prefs.language ?? DEFAULT_SETTINGS.language,
      theme: theme === 'light' || theme === 'dark' || theme === 'system' || theme === 'pink'
        ? theme
        : DEFAULT_SETTINGS.theme,
      defaultContext: parseNumber(prefs.defaultContext, DEFAULT_SETTINGS.defaultContext),
      defaultCorpus: prefs.defaultCorpus ?? DEFAULT_SETTINGS.defaultCorpus,
      fontSize: fontSize === 'sm' || fontSize === 'base' || fontSize === 'lg'
        ? fontSize
        : DEFAULT_SETTINGS.fontSize,
      showLineNumbers: parseBoolean(prefs.showLineNumbers, DEFAULT_SETTINGS.showLineNumbers),
      highlightColor: prefs.highlightColor ?? DEFAULT_SETTINGS.highlightColor,
    }
  } catch {
    return { ...DEFAULT_SETTINGS }
  }
}

export async function updateSettings(settings: Partial<UserSettings>): Promise<UserSettings> {
  await updatePrefs(settings)
  return getSettings()
}

// ============================================
// Embeddings API
// ============================================

export interface EmbeddingModel {
  id: string
  name: string
  installed: boolean
  dim?: number
  language?: string
  sizeBytes?: number
  url?: string
  sha256?: string
  description?: string
}

export type OperationRunStatus = z.infer<typeof OperationRunStatusSchema>
export type OperationRunSnapshot = z.infer<typeof OperationRunSnapshotSchema>
export type OperationRunLaunchResponse = z.infer<typeof OperationRunLaunchResponseSchema>
export type LocalSemanticIndexPreflight = z.infer<typeof LocalSemanticIndexPreflightSchema>

/**
 * Die Begruendung aus einer Problem-Antwort holen.
 *
 * Das Backend erklaert einen abgelehnten Modellweg praezise ("Der Endpunkt
 * braucht http:// oder https:// am Anfang."). Ohne diesen Griff bleibt davon
 * nur "Request failed with status code 400" uebrig, und der Hinweis, der die
 * Eingabe reparieren wuerde, geht verloren.
 */
async function problemDetail(fehler: unknown, ersatz: string): Promise<string> {
  const antwort = (fehler as { response?: Response } | null)?.response
  if (antwort) {
    try {
      const rumpf = (await antwort.clone().json()) as { detail?: unknown; title?: unknown }
      const text = rumpf?.detail ?? rumpf?.title
      if (typeof text === 'string' && text.trim()) return text
    } catch {
      // Keine JSON-Problemantwort. Der Ersatztext ist dann das Beste, was da ist.
    }
  }
  return fehler instanceof Error && fehler.message ? fehler.message : ersatz
}

export interface CopilotStatus {
  /** A model endpoint is set. Nothing is sent to the model server to find out. */
  configured: boolean
  model: string | null
}

/** Whether a language model is configured for the copilot (any signed-in user). */
export async function getCopilotStatus(): Promise<CopilotStatus> {
  const data = await api.get('copilot/status').json<Record<string, unknown>>()
  return {
    configured: data.configured === true,
    model: typeof data.model === 'string' && data.model ? data.model : null,
  }
}

/**
 * Den aktuellen Modellweg laden. Erfordert Admin-Rechte.
 */
export async function getModelRoute(): Promise<ModelRoute> {
  const data = await api.get('settings/model-route').json()
  return validateResponse(ModelRouteSchema, data, 'settings/model-route')
}

/**
 * Modellweg umstellen. Wirkt sofort, ohne Neustart des Backends.
 *
 * ``schluessel`` wird nur gesendet, wenn wirklich einer eingegeben wurde. Er
 * kommt nie zurueck und wird vom Backend nicht auf die Platte geschrieben.
 */
export async function setModelRoute(eingabe: {
  endpoint?: string
  modell?: string
  schluessel?: string
}): Promise<ModelRoute> {
  const nutzlast: Record<string, string> = {}
  if (eingabe.endpoint !== undefined) nutzlast.endpoint = eingabe.endpoint
  if (eingabe.modell !== undefined) nutzlast.modell = eingabe.modell
  if (eingabe.schluessel) nutzlast.schluessel = eingabe.schluessel
  let data: unknown
  try {
    data = await api.post('settings/model-route', { json: nutzlast }).json()
  } catch (fehler) {
    throw new Error(await problemDetail(fehler, t('errors.client.modelRouteFailed')))
  }
  return validateResponse(ModelRouteSchema, data, 'settings/model-route')
}

export async function getEmbeddingModels(): Promise<EmbeddingModel[]> {
  const response = await api.get('embeddings/list').json<Record<string, Record<string, unknown>>>()

  return Object.entries(response ?? {}).map(([name, info]) => {
    // Validate each model entry
    const validated = RawEmbeddingModelSchema.safeParse(info)
    const data = validated.success ? validated.data : info as Record<string, unknown>

    return {
      id: name,
      name: String(data.label ?? data.name ?? name),
      installed: Boolean(data.installed),
      dim: typeof data.dim === 'number' ? data.dim : undefined,
      language: typeof data.language === 'string' ? data.language : undefined,
      sizeBytes: typeof data.size_bytes === 'number' ? data.size_bytes : undefined,
      url: typeof data.url === 'string' ? data.url : undefined,
      sha256: typeof data.sha256 === 'string' ? data.sha256 : undefined,
      description: typeof data.description === 'string' ? data.description : undefined,
    }
  })
}

export async function downloadEmbeddingModel(
  modelId: string,
  url: string,
  sha256?: string
): Promise<OperationRunLaunchResponse> {
  const raw = await api.post('embeddings/download', {
    json: { name: modelId, url, sha256 }
  }).json()
  return validateResponse(OperationRunLaunchResponseSchema, raw, 'embeddings/download')
}

export async function getOperationRun(runId: string): Promise<OperationRunSnapshot> {
  const raw = await api.get(`operation-runs/${encodeURIComponent(runId)}`).json()
  return validateResponse(OperationRunSnapshotSchema, raw, 'operation-runs/{run_id}')
}

export async function getLocalSemanticIndexPreflight(
  corpus: string,
): Promise<LocalSemanticIndexPreflight> {
  const raw = await api.get('embeddings/local-index/preflight', {
    searchParams: { corpus },
  }).json()
  return validateResponse(
    LocalSemanticIndexPreflightSchema,
    raw,
    'embeddings/local-index/preflight',
  )
}

export async function startLocalSemanticIndexBuild(
  corpus: string,
  levels: Array<'doc' | 'sentence'>,
): Promise<OperationRunLaunchResponse> {
  const raw = await api.post('embeddings/local-index/build', {
    json: { corpus, levels },
  }).json()
  return validateResponse(
    OperationRunLaunchResponseSchema,
    raw,
    'embeddings/local-index/build',
  )
}

export async function getLocalSemanticIndexBuild(
  runId: string,
): Promise<OperationRunSnapshot> {
  const raw = await api.get(
    `embeddings/local-index/builds/${encodeURIComponent(runId)}`,
  ).json()
  return validateResponse(
    OperationRunSnapshotSchema,
    raw,
    'embeddings/local-index/builds/{run_id}',
  )
}

export async function cancelLocalSemanticIndexBuild(
  runId: string,
): Promise<OperationRunSnapshot> {
  const raw = await api.post(
    `embeddings/local-index/builds/${encodeURIComponent(runId)}/cancel`,
  ).json()
  return validateResponse(
    OperationRunSnapshotSchema,
    raw,
    'embeddings/local-index/builds/{run_id}/cancel',
  )
}

export async function deleteEmbeddingModel(modelId: string): Promise<void> {
  await api.post('embeddings/remove', { json: { name: modelId } })
}

/** Where one corpus takes its word vectors from (`word_vectors` of GET /settings/embeddings). */
export interface CorpusWordVectors {
  corpus: string
  available: boolean
  /** `word_index` (its word vector index) or `pipeline` (the pipeline that annotated it). */
  source: string | null
  pipeline: string | null
  /** Why the corpus has no word vectors, in the language of the request. */
  reason: string
}

/** The server's embedding backend: spacy (vectors of a spaCy pipeline) or none. */
export interface EmbeddingBackendState {
  backend: string
  supportedBackends: string[]
  /** The default pipeline (CANDYCONC_EMB_SPACY_MODEL). */
  spacyModel: string | null
  /** What the default pipeline embeds, as codes (`passage_queries`, `fallback`, ...). */
  spacyModelUsedFor: string[]
  wordVectors: CorpusWordVectors[]
}

function coerceCorpusWordVectors(raw: unknown): CorpusWordVectors | null {
  if (!raw || typeof raw !== 'object') return null
  const entry = raw as Record<string, unknown>
  if (typeof entry.corpus !== 'string' || !entry.corpus) return null
  return {
    corpus: entry.corpus,
    available: entry.available === true,
    source: typeof entry.source === 'string' && entry.source ? entry.source : null,
    pipeline: typeof entry.pipeline === 'string' && entry.pipeline ? entry.pipeline : null,
    reason: typeof entry.reason === 'string' ? entry.reason : '',
  }
}

function coerceEmbeddingBackend(raw: Record<string, unknown>): EmbeddingBackendState {
  return {
    backend: typeof raw.backend === 'string' ? raw.backend : '',
    supportedBackends: Array.isArray(raw.supported_backends)
      ? raw.supported_backends.map((value) => String(value))
      : [],
    spacyModel: typeof raw.spacy_model === 'string' && raw.spacy_model ? raw.spacy_model : null,
    spacyModelUsedFor: Array.isArray(raw.spacy_model_used_for)
      ? raw.spacy_model_used_for.map((value) => String(value))
      : [],
    wordVectors: Array.isArray(raw.word_vectors)
      ? raw.word_vectors.map(coerceCorpusWordVectors).filter((entry): entry is CorpusWordVectors => entry !== null)
      : [],
  }
}

export async function getEmbeddingBackend(): Promise<EmbeddingBackendState> {
  const raw = await api.get('settings/embeddings').json<Record<string, unknown>>()
  return coerceEmbeddingBackend(raw ?? {})
}

/** Sets the backend (spacy or none). The server rejects other values with 422. */
export async function setEmbeddingBackend(backend: string): Promise<EmbeddingBackendState> {
  let raw: Record<string, unknown>
  try {
    raw = await api.post('settings/embeddings', { json: { backend } }).json<Record<string, unknown>>()
  } catch (fehler) {
    throw new Error(await problemDetail(fehler, t('errors.client.embeddingBackendFailed')))
  }
  return coerceEmbeddingBackend(raw ?? {})
}

// ============================================
// Product Capability Contract API
// ============================================

export async function getProductCapabilities(): Promise<ProductCapabilityContract> {
  const raw = await api.get('capabilities').json()
  return validateResponse(ProductCapabilityContractSchema, raw, 'capabilities')
}

export async function getMcpTools(): Promise<McpToolsResponse> {
  const res = await fetch('/mcp/tools', {
    method: 'GET',
    headers: await withAuthHeadersReady({ Accept: 'application/json' }),
  })
  if (!res.ok) {
    throw new Error(`MCP tools request failed with HTTP ${res.status}`)
  }
  const raw = await res.json()
  return validateResponse(McpToolsResponseSchema, raw, 'mcp/tools')
}

export async function getAuthSession(): Promise<AuthSession> {
  const raw = await api.get('auth/session').json()
  return validateResponse(AuthSessionSchema, raw, 'auth/session')
}

export async function loginUser(payload: { username: string; password: string }): Promise<AuthLoginResponse> {
  const raw = await api.post('login', { json: payload }).json()
  return validateResponse(AuthLoginResponseSchema, raw, 'login')
}

export async function logoutUser(): Promise<AuthLogoutResponse> {
  const raw = await api.post('logout').json()
  return validateResponse(AuthLogoutResponseSchema, raw, 'logout')
}

// ============================================
// Corpora API
// ============================================

export interface CorpusSummary {
  /** Identifier the routes accept ("default" for the corpus pinned at start). */
  name: string
  /** Name to show, the directory name of the index. Older servers do not send it. */
  display_name?: string
  path: string
  /** Set by POST /corpora/{name}/activate when a start-time pin keeps the copilot on another corpus. */
  activation_notice?: string
  status?: 'ready' | 'missing' | 'incomplete' | 'corrupt'
  status_reason?: string
  source?: string
  active?: boolean
  token_count: number
  doc_count: number
  import_mode: string
  annotation_source?: string
  /** ISO 639 code of the corpus language, null when the index does not record it. */
  language?: string | null
  /** spaCy pipeline that annotated the corpus (en_core_web_md, blank:en), null when unknown. */
  annotation_pipeline?: string | null
  paired: boolean
  pair_axes: string[]
  is_legacy: boolean
  capabilities: Record<string, boolean>
  /** True when the persisted import report records skipped/rejected input. */
  partial_input?: boolean
  rejected_rows?: number
  warning_count?: number
  import_warnings?: string[]
  features?: CorpusFeatureDescriptor
}

export interface CorpusFeatureTokenAttribute {
  id: string
  cql_attribute: string
  label: string
  artifacts?: string[]
  value_domain?: string
  tagset?: string | null
}

export interface CorpusFeatureFrequencyGroup {
  id: string
  label: string
  artifacts?: string[]
}

export interface CorpusFeatureAlignmentPairingSchema {
  schema_id: string
  group_key_field: string
  anchor_role_field?: string
  default_anchor_role?: string
  variant_axis_fields: string[]
  legacy_variant_filter_field?: string
  generic_axis_filters: boolean
  legacy_response_fields?: Record<string, string>
}

export interface CorpusFeatureDescriptor {
  schema_version: string
  token_attributes?: CorpusFeatureTokenAttribute[]
  frequency_groups?: CorpusFeatureFrequencyGroup[]
  semantic?: {
    passage_search?: boolean
    word_similarity?: boolean
    sentence_alignment?: boolean
  }
  alignment?: {
    paired?: boolean
    pair_axes?: string[]
    pairing_schema?: CorpusFeatureAlignmentPairingSchema | null
    parallel_groups?: boolean
    parallel_kwic?: boolean
  }
}

export interface CorporaListResult {
  corpora: CorpusSummary[]
  count: number
}

export function coerceCorpusSummary(raw: Record<string, unknown>): CorpusSummary {
  const capabilities: Record<string, boolean> = {}
  const rawCaps = raw.capabilities
  if (rawCaps && typeof rawCaps === 'object') {
    for (const [key, value] of Object.entries(rawCaps as Record<string, unknown>)) {
      capabilities[key] = Boolean(value)
    }
  }
  const pairAxes = Array.isArray(raw.pair_axes)
    ? (raw.pair_axes as unknown[]).map((value) => String(value))
    : []
  const features = coerceCorpusFeatures(raw.features)
  return {
    name: String(raw.name ?? 'default'),
    ...(typeof raw.display_name === 'string' && raw.display_name.trim()
      ? { display_name: raw.display_name.trim() }
      : {}),
    path: typeof raw.path === 'string' ? raw.path : '',
    status: typeof raw.status === 'string' ? (raw.status as CorpusSummary['status']) : undefined,
    status_reason: typeof raw.status_reason === 'string' ? raw.status_reason : undefined,
    source: typeof raw.source === 'string' ? raw.source : undefined,
    active: typeof raw.active === 'boolean' ? raw.active : undefined,
    token_count: typeof raw.token_count === 'number' ? raw.token_count : 0,
    doc_count: typeof raw.doc_count === 'number' ? raw.doc_count : 0,
    import_mode: typeof raw.import_mode === 'string' ? raw.import_mode : '',
    annotation_source: typeof raw.annotation_source === 'string' ? raw.annotation_source : undefined,
    language: typeof raw.language === 'string' && raw.language ? raw.language : null,
    annotation_pipeline: typeof raw.annotation_pipeline === 'string' && raw.annotation_pipeline ? raw.annotation_pipeline : null,
    paired: Boolean(raw.paired),
    pair_axes: pairAxes,
    is_legacy: Boolean(raw.is_legacy),
    capabilities,
    partial_input: Boolean(raw.partial_input),
    rejected_rows: typeof raw.rejected_rows === 'number' ? Math.max(0, raw.rejected_rows) : 0,
    warning_count: typeof raw.warning_count === 'number' ? Math.max(0, raw.warning_count) : 0,
    import_warnings: Array.isArray(raw.import_warnings)
      ? raw.import_warnings.map((item) => String(item)).filter(Boolean)
      : [],
    features,
    ...(typeof raw.notice === 'string' && raw.notice ? { activation_notice: raw.notice } : {}),
  }
}

function coerceCorpusFeatures(raw: unknown): CorpusFeatureDescriptor | undefined {
  if (!raw || typeof raw !== 'object') return undefined
  const value = raw as Record<string, unknown>
  const tokenAttributes = Array.isArray(value.token_attributes)
    ? value.token_attributes
        .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === 'object')
        .map((entry) => ({
          id: String(entry.id ?? entry.cql_attribute ?? ''),
          cql_attribute: String(entry.cql_attribute ?? entry.id ?? ''),
          label: String(entry.label ?? entry.cql_attribute ?? entry.id ?? ''),
          artifacts: Array.isArray(entry.artifacts) ? entry.artifacts.map((item) => String(item)) : undefined,
          value_domain: typeof entry.value_domain === 'string' ? entry.value_domain : undefined,
          tagset: typeof entry.tagset === 'string' ? entry.tagset : null,
        }))
        .filter((entry) => entry.id && entry.cql_attribute)
    : undefined
  const frequencyGroups = Array.isArray(value.frequency_groups)
    ? value.frequency_groups
        .filter((entry): entry is Record<string, unknown> => Boolean(entry) && typeof entry === 'object')
        .map((entry) => ({
          id: String(entry.id ?? ''),
          label: String(entry.label ?? entry.id ?? ''),
          artifacts: Array.isArray(entry.artifacts) ? entry.artifacts.map((item) => String(item)) : undefined,
        }))
        .filter((entry) => entry.id)
    : undefined
  const semantic = value.semantic && typeof value.semantic === 'object'
    ? value.semantic as Record<string, unknown>
    : {}
  const alignment = value.alignment && typeof value.alignment === 'object'
    ? value.alignment as Record<string, unknown>
    : {}
  const pairingSchema = alignment.pairing_schema && typeof alignment.pairing_schema === 'object'
    ? alignment.pairing_schema as Record<string, unknown>
    : null
  const legacyResponseFields = pairingSchema?.legacy_response_fields &&
    typeof pairingSchema.legacy_response_fields === 'object'
    ? Object.fromEntries(
        Object.entries(pairingSchema.legacy_response_fields as Record<string, unknown>)
          .map(([key, entry]) => [key, String(entry)])
      )
    : undefined
  return {
    schema_version: String(value.schema_version ?? 'corpus-features-v1'),
    token_attributes: tokenAttributes,
    frequency_groups: frequencyGroups,
    semantic: {
      passage_search: Boolean(semantic.passage_search),
      word_similarity: Boolean(semantic.word_similarity),
      sentence_alignment: Boolean(semantic.sentence_alignment),
    },
    alignment: {
      paired: Boolean(alignment.paired),
      pair_axes: Array.isArray(alignment.pair_axes) ? alignment.pair_axes.map((item) => String(item)) : undefined,
      pairing_schema: pairingSchema
        ? {
            schema_id: String(pairingSchema.schema_id ?? 'unknown'),
            group_key_field: String(pairingSchema.group_key_field ?? ''),
            anchor_role_field: typeof pairingSchema.anchor_role_field === 'string' ? pairingSchema.anchor_role_field : undefined,
            default_anchor_role: typeof pairingSchema.default_anchor_role === 'string' ? pairingSchema.default_anchor_role : undefined,
            variant_axis_fields: Array.isArray(pairingSchema.variant_axis_fields)
              ? pairingSchema.variant_axis_fields.map((item) => String(item))
              : [],
            legacy_variant_filter_field: typeof pairingSchema.legacy_variant_filter_field === 'string'
              ? pairingSchema.legacy_variant_filter_field
              : undefined,
            generic_axis_filters: Boolean(pairingSchema.generic_axis_filters),
            legacy_response_fields: legacyResponseFields,
          }
        : null,
      parallel_groups: Boolean(alignment.parallel_groups),
      parallel_kwic: Boolean(alignment.parallel_kwic),
    },
  }
}

export async function getCorpora(): Promise<CorporaListResult> {
  const response = await api.get('corpora').json<{
    corpora?: Array<Record<string, unknown>>
    count?: number
  }>()
  const corpora = (response.corpora ?? []).map(coerceCorpusSummary)
  return {
    corpora,
    count: typeof response.count === 'number' ? response.count : corpora.length,
  }
}

export async function getCorpusCapabilities(corpus: string): Promise<CorpusSummary> {
  const response = await api
    .get(`corpora/${encodeURIComponent(corpus)}/capabilities`)
    .json<Record<string, unknown>>()
  return coerceCorpusSummary(response)
}

export async function registerCorpus(path: string, activate = false): Promise<CorpusSummary> {
  const response = await api
    .post('corpora/register', { json: { path, activate } })
    .json<Record<string, unknown>>()
  return coerceCorpusSummary(response)
}

export interface ActivateCorpusOptions {
  /** Required only when the backend reports an explicitly reviewed partial import. */
  acknowledgePartialInput?: boolean
}

export async function activateCorpus(
  corpus: string,
  options: ActivateCorpusOptions = {},
): Promise<CorpusSummary> {
  const acknowledgement = options.acknowledgePartialInput
    ? { json: { acknowledge_partial_input: true } }
    : undefined
  const response = await api
    .post(`corpora/${encodeURIComponent(corpus)}/activate`, acknowledgement)
    .json<Record<string, unknown>>()
  return coerceCorpusSummary(response)
}

export async function unregisterCorpus(corpus: string): Promise<{ status: string; path?: string }> {
  return api
    .delete(`corpora/${encodeURIComponent(corpus)}/registration`)
    .json<{ status: string; path?: string }>()
}

export interface CreateCorpusImportJobPayload {
  method: string
  input_path: string
  target_name?: string
  target_path?: string
  staging_path?: string
  activate_on_success?: boolean
  [key: string]: unknown
}

export type CorpusImportPreflightPayload = CreateCorpusImportJobPayload

export async function getCorpusImportMethods(): Promise<CorpusImportMethod[]> {
  const raw = await api.get('corpora/import-methods').json()
  const response = validateResponse(
    CorpusImportMethodsResponseSchema,
    raw,
    'corpora/import-methods'
  )
  return response.methods
}

export async function preflightCorpusImport(
  payload: CorpusImportPreflightPayload
): Promise<CorpusImportPreflightResponse> {
  const raw = await longRunningApi.post('corpora/import-preflight', { json: payload }).json()
  return validateResponse(CorpusImportPreflightResponseSchema, raw, 'corpora/import-preflight')
}

export async function createCorpusImportJob(
  payload: CreateCorpusImportJobPayload
): Promise<CorpusImportJob> {
  const raw = await longRunningApi.post('corpora/imports', { json: payload }).json()
  return validateResponse(CorpusImportJobSchema, raw, 'corpora/imports')
}

export async function listCorpusImportJobs(): Promise<CorpusImportJob[]> {
  const raw = await longRunningApi.get('corpora/imports').json()
  const response = validateResponse(
    CorpusImportJobsResponseSchema,
    raw,
    'corpora/imports'
  ) as CorpusImportJobsResponse
  return response.jobs
}

export async function getCorpusImportJob(jobId: string): Promise<CorpusImportJob> {
  const raw = await longRunningApi
    .get(`corpora/imports/${encodeURIComponent(jobId)}`)
    .json()
  return validateResponse(CorpusImportJobSchema, raw, 'corpora/imports/{job_id}')
}

export async function cancelCorpusImportJob(jobId: string): Promise<CorpusImportJob> {
  const raw = await api
    .post(`corpora/imports/${encodeURIComponent(jobId)}/cancel`)
    .json()
  return validateResponse(CorpusImportJobSchema, raw, 'corpora/imports/{job_id}/cancel')
}

export async function getCorpusImportReports(
  jobId: string
): Promise<CorpusImportReportsResponse> {
  const raw = await longRunningApi
    .get(`corpora/imports/${encodeURIComponent(jobId)}/reports`)
    .json()
  const normalized = raw && typeof raw === 'object' && !Array.isArray(raw) && !('schema_version' in raw)
    ? {
        schema_version: 'legacy-flattened-import-reports',
        job_id: String((raw as Record<string, unknown>).job_id ?? jobId),
        reports: Object.fromEntries(
          Object.entries(raw as Record<string, unknown>).filter(([key]) => key !== 'job_id')
        ),
        ...(raw as Record<string, unknown>),
      }
    : raw
  const response = validateResponse(
    CorpusImportReportsResponseSchema,
    normalized,
    'corpora/imports/{job_id}/reports'
  )
  return response
}

export async function getCorpusBuildReport(corpus: string): Promise<CorpusBuildReport> {
  const raw = await api
    .get(`corpora/${encodeURIComponent(corpus)}/build-report`)
    .json()
  const normalized = raw && typeof raw === 'object' && !Array.isArray(raw) && !('schema_version' in raw)
    ? {
        schema_version: 'legacy-flattened-corpus-build-report',
        corpus: String((raw as Record<string, unknown>).corpus ?? corpus),
        path: typeof (raw as Record<string, unknown>).path === 'string'
          ? String((raw as Record<string, unknown>).path)
          : undefined,
        reports: Object.fromEntries(
          Object.entries(raw as Record<string, unknown>).filter(([key]) => !['corpus', 'path'].includes(key))
        ),
        ...(raw as Record<string, unknown>),
      }
    : raw
  return validateResponse(CorpusBuildReportSchema, normalized, 'corpora/{corpus}/build-report')
}

// ============================================
// System API
// ============================================

export interface SystemInfo {
  version: string
  backendVersion?: string
  uptime?: string
  corpusName: string
  tokenCount: number
  documentCount: number
  indexStatus?: 'ready' | 'building' | 'error'
  lastUpdated?: string
  diskUsage?: {
    used: number
    total: number
  }
  faissStatus?: 'ready' | 'building' | 'error' | 'unavailable'
  faissDetail?: string
  vectorCount?: number
  cacheSize?: string
  source?: 'backend' | 'legacy_health_fallback' | 'backend_degraded_fallback'
}

export async function getSystemInfo(corpus?: string): Promise<SystemInfo> {
  try {
    const searchParams = corpus ? { corpus } : undefined
    const data = await api.get('system/info', { searchParams }).json()
    return validateResponse(SystemInfoSchema, data, 'system/info')
  } catch (error) {
    if (!isLegacyEndpointUnavailable(error)) throw error
    // Minimal fallback when the endpoint is not available yet.
    const health = await healthCheck().catch(() => ({ status: 'error' as const, services: {} }))
    return {
      version: 'unknown',
      backendVersion: 'unknown',
      uptime: 'unbekannt',
      corpusName: 'default',
      tokenCount: 0,
      documentCount: 0,
      indexStatus: health.status === 'ok' ? 'ready' : 'error',
      faissStatus: 'unavailable',
      vectorCount: 0,
      cacheSize: '0 MB',
      source: 'legacy_health_fallback',
    }
  }
}

export interface HelpStatus {
  /** The package holds the HTML documentation, served under docsUrl. */
  docsAvailable: boolean
  docsUrl: string | null
}

export async function getHelpStatus(): Promise<HelpStatus> {
  const data = await api.get('help').json<Record<string, unknown>>()
  const docsUrl = typeof data.docsUrl === 'string' && data.docsUrl.startsWith('/') ? data.docsUrl : null
  return { docsAvailable: data.docsAvailable === true && docsUrl !== null, docsUrl }
}

export async function healthCheck(): Promise<{ status: 'ok' | 'degraded' | 'error'; services: Record<string, boolean> }> {
  const response = await api.get('health').json<Record<string, unknown>>()
  const status = response.status === 'ok' ? 'ok' : 'degraded'
  // Note: healthCheck uses a simplified response format, validation handled inline
  return { status, services: { backend: status === 'ok' } }
}

export async function rebuildIndex(): Promise<RebuildIndexResponse> {
  const response = await api.post('system/rebuild-index').json()
  return validateResponse(RebuildIndexResponseSchema, response, 'system/rebuild-index')
}

export async function clearCache(): Promise<void> {
  await api.post('system/clear-cache')
}

// ---------------------------------------------------------------------------
// Rezept-Verzeichnis des Copiloten
// ---------------------------------------------------------------------------

/** Ein Analyseverfahren, so wie es sich erklaeren laesst. */
export interface CopilotRezept {
  id: string
  /** Menschenlesbarer Name, etwa "Frequenz und Verteilung". */
  name: string
  /** Wofuer das Verfahren da ist, als Frage formuliert. */
  einsatz: string
  /** Eine Beispielfrage, die es beantwortet. */
  beispiel_frage: string
  beispiel_frage_quelle?: string
  im_korpus_beantwortbar?: boolean
  /** Die Ziele der Schritte, ohne Werkzeugnamen. */
  schritte: string[]
}

/** Recipe descriptions and example questions for the selected corpus. */
export async function getCopilotRezepte(corpus?: string): Promise<CopilotRezept[]> {
  const antwort = await api.get('copilot/recipes', {
    searchParams: corpus ? { corpus } : {},
  }).json<{ recipes?: CopilotRezept[] }>()
  return Array.isArray(antwort.recipes) ? antwort.recipes : []
}
