/**
 * Trace Recorder Middleware
 *
 * Records all actions for audit trail and reproducibility.
 * Integrates with the UIContextSnapshot system.
 */

import { ref } from 'vue'
import type { Action, ActionDispatchContext, ActionResult, ActionSource } from './types'
import type { TraceEventV1, RunRecordV1, RunRecordResearchScopeEvidence } from '@/types/copilot-protocol'
import { getActionMeta, hasScientificRisk } from './registry'
import { generateTraceId, generateRunId, payloadHash } from '@/utils/hashing'
import { recordActionTrace } from '@/composables/useContextSnapshot'
import { createRunEvidenceV2, stableResultHash, withEvidenceQueryTraceId } from '@/utils/runEvidence'

// ============================================================================
// Trace Storage
// ============================================================================

// Full trace history
export const traceHistory = ref<TraceEventV1[]>([])

// Run records (for reproducibility)
export const runRecords = ref<RunRecordV1[]>([])

// Current UI state hash (updated by snapshot builder)
export const currentStateHash = ref<string>('')

// Max entries to keep
const MAX_TRACE_ENTRIES = 500
const MAX_RUN_RECORDS = 100

export interface RunEvidenceFingerprintInfo {
  indexFingerprint?: string
  metadataSchemaHash?: string
  warnings?: string[]
}

export interface CreateRunRecordOptions extends RunEvidenceFingerprintInfo {
  requestId?: string
  runId?: string
  backendQueryTraceId?: string
  researchScope?: Partial<RunRecordResearchScopeEvidence>
}

export interface TraceRecorderCorpusInfo {
  corpusId: string
  subcorpusHash: string
  researchScope?: Partial<RunRecordResearchScopeEvidence>
}

// ============================================================================
// State Hash Tracking
// ============================================================================

/**
 * Update the current UI state hash
 * Called by the snapshot builder after state changes
 */
export function updateStateHash(hash: string): void {
  currentStateHash.value = hash
}

// ============================================================================
// Trace Recording
// ============================================================================

/**
 * Record a trace event
 */
function recordTrace(
  action: Action,
  result: ActionResult,
  context: ActionDispatchContext,
  stateHashBefore: string,
  stateHashAfter: string,
  runId?: string
): TraceEventV1 {
  const source = result.source ?? context.source
  const event: TraceEventV1 = {
    id: generateTraceId(),
    ts: Date.now(),
    actor: source === 'copilot' ? 'copilot' : 'user',
    source,
    requestId: result.requestId ?? context.requestId,
    actionType: action.type,
    payloadHash: payloadHash('payload' in action ? (action.payload as Record<string, unknown>) : {}),
    ok: result.success,
    policyDecision: result.policyDecision,
    policyReason: result.policyReason,
    uiStateHashBefore: stateHashBefore,
    uiStateHashAfter: stateHashAfter,
    linkRunId: runId,
  }

  traceHistory.value.push(event)

  // Trim if needed
  if (traceHistory.value.length > MAX_TRACE_ENTRIES) {
    traceHistory.value = traceHistory.value.slice(-MAX_TRACE_ENTRIES)
  }

  // Also record to the context snapshot's recent actions
  const meta = getActionMeta(action.type)
  recordActionTrace(
    source === 'copilot' ? 'copilot' : 'user',
    action.type,
    'payload' in action ? (action.payload as Record<string, unknown>) : {},
    result.success,
    meta?.label
  )

  return event
}

// ============================================================================
// Run Recording
// ============================================================================

/**
 * Check if an action should create a run record
 */
export function shouldCreateRun(action: Action): boolean {
  const meta = getActionMeta(action.type)
  if (!meta) return false

  // High cost actions (queries, analyses) create runs
  if (meta.cost === 'high') return true

  // Actions with scientific risks create runs
  if (hasScientificRisk(action)) return true

  return false
}

/**
 * Create a run record for an action
 */
export function createRunRecord(
  action: Action,
  result: ActionResult,
  corpusId: string,
  subcorpusHash: string,
  queryHashValue?: string,
  options: CreateRunRecordOptions = {}
): RunRecordV1 {
  const meta = getActionMeta(action.type)
  const payload = 'payload' in action ? (action.payload as Record<string, unknown>) : {}

  // Determine run kind
  let kind: 'query' | 'analysis' = 'analysis'
  if (action.type.startsWith('query/')) {
    kind = 'query'
  }

  // Build result reference
  const resultRef: RunRecordV1['resultRef'] = {
    type: action.type,
    hash: result.data ? stableResultHash(result.data) : undefined,
  }

  const rows = extractResultRows(result.data)
  if (rows !== undefined) {
    resultRef.rows = rows
  }

  const runId = options.runId ?? result.runId ?? generateRunId()
  const existing = runRecords.value.find(r => r.runId === runId)
  if (existing) return existing

  const run: RunRecordV1 = {
    schemaVersion: '2.0',
    runId,
    requestId: options.requestId ?? result.requestId,
    ts: Date.now(),
    kind,
    actionType: action.type,
    actionPayload: payload,
    corpus: {
      corpusId,
      subcorpusHash,
    },
    queryHash: queryHashValue,
    resultRef,
    summary: meta?.label ?? action.type,
    notes: [],
    evidence: createRunEvidenceV2({
      provenance: 'frontend_actionbus',
      corpusId,
      subcorpusHash,
      queryHash: queryHashValue,
      actionType: action.type,
      resultType: resultRef.type,
      resultHash: resultRef.hash,
      rows: resultRef.rows,
      backendQueryTraceId: options.backendQueryTraceId,
      indexFingerprint: options.indexFingerprint,
      metadataSchemaHash: options.metadataSchemaHash,
      researchScope: options.researchScope,
      warnings: options.warnings,
    }),
  }

  runRecords.value.push(run)

  // Trim if needed
  if (runRecords.value.length > MAX_RUN_RECORDS) {
    runRecords.value = runRecords.value.slice(-MAX_RUN_RECORDS)
  }

  return run
}

/**
 * Add a note to a run record
 */
export function addRunNote(runId: string, note: string): void {
  const run = runRecords.value.find(r => r.runId === runId)
  if (run) {
    run.notes = run.notes ?? []
    run.notes.push(note)
  }
}

/**
 * Get a run record by ID
 */
export function getRunRecord(runId: string): RunRecordV1 | undefined {
  return runRecords.value.find(r => r.runId === runId)
}

/**
 * Get all run records for a query hash
 */
export function getRunsForQuery(queryHash: string): RunRecordV1[] {
  return runRecords.value.filter(r => r.queryHash === queryHash)
}

/**
 * Get recent runs
 */
export function getRecentRuns(limit = 20): RunRecordV1[] {
  return runRecords.value.slice(-limit)
}

function extractResultRows(data: unknown): number | undefined {
  if (Array.isArray(data)) return data.length
  if (!data || typeof data !== 'object') return undefined

  const record = data as Record<string, unknown>
  if (typeof record.total === 'number' && Number.isFinite(record.total)) return record.total
  if (typeof record.rows === 'number' && Number.isFinite(record.rows)) return record.rows
  if (Array.isArray(record.rows)) return record.rows.length
  if (Array.isArray(record.evidenceRows)) return record.evidenceRows.length
  return undefined
}

// ============================================================================
// Trace Recorder Middleware
// ============================================================================

/**
 * Track the source of the current action dispatch
 * This is set by the action bus before calling middleware
 */
let currentActionSource: ActionSource = 'user'

/**
 * Set the current action source (called by action bus)
 */
export function setCurrentActionSource(source: ActionSource): void {
  currentActionSource = source
}

/**
 * Get the current action source
 */
export function getCurrentActionSource(): ActionSource {
  return currentActionSource
}

/**
 * Create the trace recorder middleware for the action bus
 */
export function createTraceRecorderMiddleware(
  getCorpusInfo: () => TraceRecorderCorpusInfo,
  getQueryHash?: () => string | undefined,
  getEvidenceFingerprints?: (corpusId: string) => RunEvidenceFingerprintInfo | Promise<RunEvidenceFingerprintInfo>
) {
  return async (
    action: Action,
    next: () => Promise<ActionResult>,
    context: ActionDispatchContext
  ): Promise<ActionResult> => {
    const stateHashBefore = currentStateHash.value

    // Execute action
    const result = await next()

    // Determine source
    const source = result.source ?? context.source ?? currentActionSource

    // Check if we should create a run
    let run: RunRecordV1 | undefined
    let runId: string | undefined
    if (result.success && shouldCreateRun(action)) {
      const { corpusId, subcorpusHash, researchScope } = getCorpusInfo()
      const executionScope = result.executionScope ?? researchScope
      const effectiveCorpusId = executionScope?.corpusId ?? corpusId
      const effectiveSubcorpusHash = executionScope?.scopeHash ?? subcorpusHash
      const queryHashValue = getQueryHash?.()
      const backendQueryTraceId = extractBackendQueryTraceId(result.data)
      let evidenceFingerprints: RunEvidenceFingerprintInfo | undefined
      try {
        evidenceFingerprints = await getEvidenceFingerprints?.(effectiveCorpusId)
      } catch (error) {
        console.warn('[TraceRecorder] Failed to resolve run evidence fingerprints:', error)
        evidenceFingerprints = {
          warnings: ['Metadata schema evidence unavailable from frontend provider.'],
        }
      }
      run = createRunRecord(action, result, effectiveCorpusId, effectiveSubcorpusHash, queryHashValue, {
        requestId: result.requestId ?? context.requestId,
        runId: result.runId ?? context.runId,
        backendQueryTraceId,
        indexFingerprint: evidenceFingerprints?.indexFingerprint,
        metadataSchemaHash: evidenceFingerprints?.metadataSchemaHash,
        researchScope: executionScope,
        warnings: evidenceFingerprints?.warnings,
      })
      runId = run.runId
    }

    // Record trace
    const trace = recordTrace(action, result, { ...context, source }, stateHashBefore, currentStateHash.value, runId)
    if (run) {
      run.evidence = withEvidenceQueryTraceId(run.evidence, trace.id)
    }

    return result
  }
}

function extractBackendQueryTraceId(data: unknown): string | undefined {
  if (!data || typeof data !== 'object' || Array.isArray(data)) return undefined
  const record = data as Record<string, unknown>
  const value = record.backendQueryTraceId ?? record.backend_query_trace_id ?? record.queryTraceId ?? record.query_trace_id
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

// ============================================================================
// Export / Import
// ============================================================================

/**
 * Export trace history as JSON
 */
export function exportTraceHistory(): string {
  return JSON.stringify({
    version: '2.0',
    exportedAt: Date.now(),
    traces: traceHistory.value,
    runs: runRecords.value,
  }, null, 2)
}

/**
 * Clear all trace data
 */
export function clearTraceData(): void {
  traceHistory.value = []
  runRecords.value = []
}

/**
 * Get trace summary statistics
 */
export function getTraceSummary(): {
  totalTraces: number
  totalRuns: number
  userActions: number
  copilotActions: number
  successRate: number
} {
  const traces = traceHistory.value
  const userActions = traces.filter(t => t.actor === 'user').length
  const copilotActions = traces.filter(t => t.actor === 'copilot').length
  const successfulActions = traces.filter(t => t.ok).length

  return {
    totalTraces: traces.length,
    totalRuns: runRecords.value.length,
    userActions,
    copilotActions,
    successRate: traces.length > 0 ? successfulActions / traces.length : 1,
  }
}
