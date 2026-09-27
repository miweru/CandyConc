/**
 * Run Record Service
 *
 * Manages run records for scientific reproducibility.
 * Features:
 * - Local storage persistence
 * - Export to JSON/CSV
 * - Run grouping and filtering (projects)
 * - Notes and annotations
 */

import { ref, watch } from 'vue'
import type { ActionRequestV1, ActionResultPayload, RunRecordResearchScopeEvidence, RunRecordV1, TraceEventV1 } from '@/types/copilot-protocol'
import { generateRunId, quickHash } from '@/utils/hashing'
import { downloadText } from '@/utils/download'
import { createRunEvidenceV2, normalizeRunEvidenceV2, stableResultHash } from '@/utils/runEvidence'
import { csvEscape } from '@/utils/csv'
import {
  traceHistory,
  runRecords as traceRunRecords,
  createRunRecord as createTraceRunRecord,
  addRunNote,
  getRunRecord,
  getRunsForQuery,
  getRecentRuns,
  clearTraceData,
  getTraceSummary,
} from '@/actions/traceRecorder'

// ============================================================================
// Storage Keys
// ============================================================================

const STORAGE_KEY_RUNS = 'candyconc_run_records'
const STORAGE_KEY_TRACES = 'candyconc_trace_history'
const STORAGE_KEY_PROJECTS = 'candyconc_run_projects'

// ============================================================================
// Project Grouping
// ============================================================================

export interface RunProject {
  id: string
  name: string
  description?: string
  createdAt: number
  runIds: string[]
  tags?: string[]
}

const runProjects = ref<RunProject[]>([])

// ============================================================================
// Persistence
// ============================================================================

/**
 * Save run records to local storage
 */
export function saveRunRecords(): void {
  try {
    localStorage.setItem(STORAGE_KEY_RUNS, JSON.stringify(traceRunRecords.value))
    localStorage.setItem(STORAGE_KEY_TRACES, JSON.stringify(traceHistory.value))
    localStorage.setItem(STORAGE_KEY_PROJECTS, JSON.stringify(runProjects.value))
  } catch (e) {
    console.warn('[RunRecordService] Failed to save to localStorage:', e)
  }
}

/**
 * Load run records from local storage
 */
export function loadRunRecords(): void {
  try {
    const runsJson = localStorage.getItem(STORAGE_KEY_RUNS)
    if (runsJson) {
      traceRunRecords.value = parseRunRecordList(JSON.parse(runsJson))
    }

    const tracesJson = localStorage.getItem(STORAGE_KEY_TRACES)
    if (tracesJson) {
      traceHistory.value = JSON.parse(tracesJson)
    }

    const projectsJson = localStorage.getItem(STORAGE_KEY_PROJECTS)
    if (projectsJson) {
      runProjects.value = JSON.parse(projectsJson)
    }
  } catch (e) {
    console.warn('[RunRecordService] Failed to load from localStorage:', e)
  }
}

function parseRunRecordList(data: unknown): RunRecordV1[] {
  const rawRuns = Array.isArray(data)
    ? data
    : isRecord(data) && Array.isArray(data.runs)
      ? data.runs
      : []

  return rawRuns
    .map(normalizeRunRecord)
    .filter((run): run is RunRecordV1 => Boolean(run))
}

function normalizeRunRecord(raw: unknown): RunRecordV1 | null {
  if (!isRecord(raw)) return null

  const resultRefRaw = isRecord(raw.resultRef) ? raw.resultRef : {}
  const actionType = typeof raw.actionType === 'string'
    ? raw.actionType
    : typeof resultRefRaw.type === 'string'
      ? resultRefRaw.type
      : undefined

  if (!actionType) return null

  const corpusRaw = isRecord(raw.corpus) ? raw.corpus : {}
  const resultRef: RunRecordV1['resultRef'] = {
    type: typeof resultRefRaw.type === 'string' ? resultRefRaw.type : actionType,
  }

  if (typeof resultRefRaw.hash === 'string') {
    resultRef.hash = resultRefRaw.hash
  }
  if (typeof resultRefRaw.rows === 'number' && Number.isFinite(resultRefRaw.rows)) {
    resultRef.rows = resultRefRaw.rows
  }

  const runWithoutEvidence: Omit<RunRecordV1, 'evidence'> = {
    schemaVersion: '2.0',
    runId: typeof raw.runId === 'string' ? raw.runId : generateRunId(),
    requestId: typeof raw.requestId === 'string' ? raw.requestId : undefined,
    ts: typeof raw.ts === 'number' && Number.isFinite(raw.ts) ? raw.ts : Date.now(),
    kind: raw.kind === 'query' || raw.kind === 'analysis'
      ? raw.kind
      : actionType.startsWith('query/')
        ? 'query'
        : 'analysis',
    actionType,
    actionPayload: isRecord(raw.actionPayload) ? raw.actionPayload : {},
    corpus: {
      corpusId: typeof corpusRaw.corpusId === 'string' ? corpusRaw.corpusId : 'unknown',
      subcorpusHash: typeof corpusRaw.subcorpusHash === 'string' ? corpusRaw.subcorpusHash : '',
    },
    queryHash: typeof raw.queryHash === 'string' ? raw.queryHash : undefined,
    resultRef,
    summary: typeof raw.summary === 'string' ? raw.summary : actionType,
    notes: Array.isArray(raw.notes) ? raw.notes.filter((note): note is string => typeof note === 'string') : [],
  }
  return {
    ...runWithoutEvidence,
    evidence: normalizeRunEvidenceV2(
      raw.evidence,
      runWithoutEvidence,
      isRecord(raw.evidence) && raw.schemaVersion === '2.0' ? 'frontend_actionbus' : 'imported_legacy'
    ),
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

// Auto-save on changes
let saveTimeout: ReturnType<typeof setTimeout> | null = null

function debouncedSave() {
  if (saveTimeout) clearTimeout(saveTimeout)
  saveTimeout = setTimeout(saveRunRecords, 1000)
}

watch(traceRunRecords, debouncedSave, { deep: true })
watch(traceHistory, debouncedSave, { deep: true })
watch(runProjects, debouncedSave, { deep: true })

// ============================================================================
// Run Management
// ============================================================================

/**
 * Create a new run record (delegated to traceRecorder)
 */
export { createTraceRunRecord as createRunRecord }

/**
 * Get a run record by ID
 */
export { getRunRecord }

/**
 * Get runs for a query hash
 */
export { getRunsForQuery }

/**
 * Get recent runs
 */
export { getRecentRuns }

/**
 * Add a note to a run
 */
export { addRunNote }

export function recordBackendActionResultRun(
  result: ActionResultPayload,
  request: ActionRequestV1,
  corpus: { corpusId?: string; subcorpusHash?: string; researchScope?: Partial<RunRecordResearchScopeEvidence> } = {}
): RunRecordV1 | null {
  if (!result.ok || !result.runId) return null

  const hasResultValue = result.output !== undefined || result.result !== undefined
  const resultValue = result.output ?? result.result
  const existing = getRunRecord(result.runId)
  if (existing) {
    recordBackendActionResultTrace(result, request, existing)
    return existing
  }

  const resultRef: RunRecordV1['resultRef'] = {
    type: result.resultRef?.type ?? request.type,
    hash: result.resultRef?.hash ?? (hasResultValue ? stableResultHash(resultValue) : undefined),
  }
  const rows = result.resultRef?.rows ?? (hasResultValue ? extractBackendRowCount(resultValue) : undefined)
  if (rows !== undefined) {
    resultRef.rows = rows
  }

  const runWithoutEvidence: Omit<RunRecordV1, 'evidence'> = {
    schemaVersion: '2.0',
    runId: result.runId,
    requestId: result.requestId,
    ts: typeof result.ts === 'number' && Number.isFinite(result.ts) ? result.ts : Date.now(),
    kind: request.type.startsWith('query/') ? 'query' : 'analysis',
    actionType: request.type,
    actionPayload: request.payload,
    corpus: {
      corpusId: result.corpus?.corpusId ?? corpus.corpusId ?? 'backend-owned',
      subcorpusHash: result.corpus?.subcorpusHash ?? corpus.subcorpusHash ?? '',
    },
    queryHash: result.queryHash,
    resultRef,
    summary: result.resultSummary ?? `Backend action result: ${request.type}`,
    notes: ['Backend-owned action_result mirrored without local ActionBus execution.'], // i18n-ignore: English provenance note stored in the run record and its exports, like the evidence warnings below
  }
  const evidence = result.evidence
    ? normalizeRunEvidenceV2(result.evidence, runWithoutEvidence, 'backend_action_result')
    : createRunEvidenceV2({
        provenance: 'backend_action_result',
        corpusId: runWithoutEvidence.corpus.corpusId,
        subcorpusHash: runWithoutEvidence.corpus.subcorpusHash,
        queryHash: result.queryHash,
        actionType: request.type,
        resultType: resultRef.type,
        resultHash: resultRef.hash,
        rows: resultRef.rows,
        researchScope: corpus.researchScope,
        warnings: [
          'No frontend policy decision was made for this backend-owned mirror.',
          ...(corpus.researchScope
            ? []
            : ['Backend execution scope unavailable without backend V2 evidence; mirrored scope is unknown.']),
        ],
      })
  const run: RunRecordV1 = { ...runWithoutEvidence, evidence }

  traceRunRecords.value.push(run)
  recordBackendActionResultTrace(result, request, run)
  return run
}

function recordBackendActionResultTrace(
  result: ActionResultPayload,
  request: ActionRequestV1,
  run: RunRecordV1
): void {
  const exists = traceHistory.value.some(trace =>
    trace.requestId === result.requestId && trace.linkRunId === run.runId
  )
  if (exists) return

  traceHistory.value.push({
    id: `trace_backend_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`,
    ts: run.ts,
    actor: 'backend',
    source: 'backend',
    requestId: result.requestId,
    actionType: request.type,
    payloadHash: quickHash(request.payload),
    ok: result.ok,
    policyReason: 'Backend-owned action_result mirrored without local ActionBus execution or frontend policy decision.',
    linkRunId: run.runId,
  })
}

function extractBackendRowCount(value: unknown): number | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  const total = record.total ?? record.rows
  if (typeof total === 'number' && Number.isFinite(total)) {
    return total
  }
  if (Array.isArray(record.rows)) {
    return record.rows.length
  }
  return undefined
}

/**
 * Get trace summary
 */
export { getTraceSummary }

/**
 * Delete a run record
 */
export function deleteRunRecord(runId: string): boolean {
  const index = traceRunRecords.value.findIndex(r => r.runId === runId)
  if (index >= 0) {
    traceRunRecords.value.splice(index, 1)
    // Also remove from projects
    for (const project of runProjects.value) {
      const runIndex = project.runIds.indexOf(runId)
      if (runIndex >= 0) {
        project.runIds.splice(runIndex, 1)
      }
    }
    return true
  }
  return false
}

// ============================================================================
// Project Management
// ============================================================================

/**
 * Create a new project
 */
export function createProject(name: string, description?: string): RunProject {
  const project: RunProject = {
    id: `proj_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`,
    name,
    description,
    createdAt: Date.now(),
    runIds: [],
  }
  runProjects.value.push(project)
  return project
}

/**
 * Add run to project
 */
export function addRunToProject(projectId: string, runId: string): boolean {
  const project = runProjects.value.find(p => p.id === projectId)
  if (project && !project.runIds.includes(runId)) {
    project.runIds.push(runId)
    return true
  }
  return false
}

/**
 * Get project by ID
 */
export function getProject(projectId: string): RunProject | undefined {
  return runProjects.value.find(p => p.id === projectId)
}

/**
 * Get all projects
 */
export function getAllProjects(): RunProject[] {
  return runProjects.value
}

// ============================================================================
// Filtering and Search
// ============================================================================

export interface RunFilter {
  kind?: 'query' | 'analysis'
  actionType?: string
  corpusId?: string
  fromTs?: number
  toTs?: number
  projectId?: string
  hasNotes?: boolean
  search?: string
}

/**
 * Filter runs by criteria
 */
export function filterRuns(filter: RunFilter): RunRecordV1[] {
  let runs = [...traceRunRecords.value]

  if (filter.kind) {
    runs = runs.filter(r => r.kind === filter.kind)
  }

  if (filter.actionType) {
    runs = runs.filter(r => r.actionType === filter.actionType)
  }

  if (filter.corpusId) {
    runs = runs.filter(r => r.corpus.corpusId === filter.corpusId)
  }

  if (filter.fromTs) {
    runs = runs.filter(r => r.ts >= filter.fromTs!)
  }

  if (filter.toTs) {
    runs = runs.filter(r => r.ts <= filter.toTs!)
  }

  if (filter.projectId) {
    const project = getProject(filter.projectId)
    if (project) {
      runs = runs.filter(r => project.runIds.includes(r.runId))
    }
  }

  if (filter.hasNotes !== undefined) {
    runs = runs.filter(r =>
      filter.hasNotes ? (r.notes?.length ?? 0) > 0 : (r.notes?.length ?? 0) === 0
    )
  }

  if (filter.search) {
    const searchLower = filter.search.toLowerCase()
    runs = runs.filter(r =>
      r.summary.toLowerCase().includes(searchLower) ||
      r.actionType.toLowerCase().includes(searchLower) ||
      (r.notes?.some(n => n.toLowerCase().includes(searchLower)) ?? false)
    )
  }

  return runs.sort((a, b) => b.ts - a.ts)
}

// ============================================================================
// Export Functions
// ============================================================================

/**
 * Export runs as JSON
 */
export function exportRunsAsJson(
  runs?: RunRecordV1[],
  options: { pretty?: boolean; includeTraces?: boolean } = {}
): string {
  const runsToExport = runs ?? traceRunRecords.value
  const { pretty = true, includeTraces = false } = options

  const exportData: {
    version: string
    exportedAt: number
    runs: RunRecordV1[]
    traces?: TraceEventV1[]
  } = {
    version: '2.0',
    exportedAt: Date.now(),
    runs: runsToExport,
  }

  if (includeTraces) {
    // Include traces linked to exported runs
    const runIds = new Set(runsToExport.map(r => r.runId))
    exportData.traces = traceHistory.value.filter(t => t.linkRunId && runIds.has(t.linkRunId))
  }

  return pretty ? JSON.stringify(exportData, null, 2) : JSON.stringify(exportData)
}

/**
 * Export runs as CSV
 */
export function exportRunsAsCsv(runs?: RunRecordV1[]): string {
  const runsToExport = runs ?? traceRunRecords.value

  // CSV header
  const headers = [
    'run_id',
    'request_id',
    'timestamp',
    'kind',
    'action_type',
    'corpus_id',
    'subcorpus_hash',
    'research_scope_hash',
    'research_scope_status',
    'research_scope_label',
    'research_scope_docset_id',
    'research_scope_name',
    'research_scope_query_hash',
    'research_scope_filter_spec_hash',
    'research_scope_metadata_schema_hash',
    'query_hash',
    'result_type',
    'result_hash',
    'result_rows',
    'summary',
    'notes',
    'payload_json',
    'schema_version',
    'evidence_provenance',
    'evidence_completeness',
    'index_fingerprint',
    'metadata_schema_hash',
    'tool_schema_hash',
    'query_trace_id',
    'backend_query_trace_id',
    'evidence_warnings',
  ]

  const csvRows = [headers.join(',')]

  for (const run of runsToExport) {
    const row = [
      escapeCSV(run.runId),
      escapeCSV(run.requestId ?? ''),
      new Date(run.ts).toISOString(),
      run.kind,
      escapeCSV(run.actionType),
      escapeCSV(run.corpus.corpusId),
      escapeCSV(run.corpus.subcorpusHash),
      escapeCSV(run.evidence?.researchScope?.scopeHash ?? run.corpus.subcorpusHash),
      escapeCSV(run.evidence?.researchScope?.scopeStatus ?? ''),
      escapeCSV(run.evidence?.researchScope?.label ?? ''),
      escapeCSV(run.evidence?.researchScope?.docsetId ?? ''),
      escapeCSV(run.evidence?.researchScope?.subcorpusName ?? ''),
      escapeCSV(run.evidence?.researchScope?.queryHash ?? ''),
      escapeCSV(run.evidence?.researchScope?.filterSpecHash ?? ''),
      escapeCSV(run.evidence?.researchScope?.metadataSchemaHash ?? ''),
      escapeCSV(run.queryHash ?? ''),
      escapeCSV(run.resultRef.type),
      escapeCSV(run.resultRef.hash ?? ''),
      String(run.resultRef.rows ?? ''),
      escapeCSV(run.summary),
      escapeCSV((run.notes ?? []).join(' | ')),
      escapeCSV(JSON.stringify(run.actionPayload)),
      escapeCSV(run.schemaVersion ?? '1.0'),
      escapeCSV(run.evidence?.provenance ?? ''),
      escapeCSV(run.evidence?.completeness ?? ''),
      escapeCSV(run.evidence?.corpusFingerprint.indexFingerprint ?? ''),
      escapeCSV(run.evidence?.corpusFingerprint.metadataSchemaHash ?? ''),
      escapeCSV(run.evidence?.toolFingerprint.toolSchemaHash ?? ''),
      escapeCSV(run.evidence?.resultFingerprint.queryTraceId ?? ''),
      escapeCSV(run.evidence?.resultFingerprint.backendQueryTraceId ?? ''),
      escapeCSV((run.evidence?.warnings ?? []).join(' | ')),
    ]
    csvRows.push(row.join(','))
  }

  return csvRows.join('\n')
}

/**
 * Export traces as CSV
 */
export function exportTracesAsCsv(traces?: TraceEventV1[]): string {
  const tracesToExport = traces ?? traceHistory.value

  const headers = [
    'trace_id',
    'timestamp',
    'actor',
    'source',
    'request_id',
    'action_type',
    'payload_hash',
    'ok',
    'policy_decision',
    'policy_reason',
    'ui_state_hash_before',
    'ui_state_hash_after',
    'linked_run_id',
  ]

  const csvRows = [headers.join(',')]

  for (const trace of tracesToExport) {
    const row = [
      escapeCSV(trace.id),
      new Date(trace.ts).toISOString(),
      trace.actor,
      escapeCSV(trace.source ?? ''),
      escapeCSV(trace.requestId ?? ''),
      escapeCSV(trace.actionType),
      escapeCSV(trace.payloadHash),
      trace.ok ? 'true' : 'false',
      escapeCSV(trace.policyDecision ?? ''),
      escapeCSV(trace.policyReason ?? ''),
      escapeCSV(trace.uiStateHashBefore ?? ''),
      escapeCSV(trace.uiStateHashAfter ?? ''),
      escapeCSV(trace.linkRunId ?? ''),
    ]
    csvRows.push(row.join(','))
  }

  return csvRows.join('\n')
}

/**
 * Export a project with all its runs
 */
export function exportProjectAsJson(projectId: string, options: { pretty?: boolean } = {}): string | null {
  const project = getProject(projectId)
  if (!project) return null

  const runs = traceRunRecords.value.filter(r => project.runIds.includes(r.runId))

  const exportData = {
    version: '1.0',
    exportedAt: Date.now(),
    project: {
      ...project,
    },
    runs,
  }

  return options.pretty ? JSON.stringify(exportData, null, 2) : JSON.stringify(exportData)
}

// CSV helper — delegate to the hardened shared escaper (formula-injection +
// column-corruption guards). Thin wrapper keeps the many call sites unchanged.
function escapeCSV(value: string): string {
  return csvEscape(value)
}

// ============================================================================
// Download Helpers
// ============================================================================

/**
 * Download runs as JSON
 */
export function downloadRunsJson(runs?: RunRecordV1[], filename?: string): void {
  const json = exportRunsAsJson(runs, { pretty: true, includeTraces: true })
  const defaultFilename = `candyconc_runs_${new Date().toISOString().slice(0, 10)}.json`
  downloadText(json, filename ?? defaultFilename, 'application/json')
}

/**
 * Download runs as CSV
 */
export function downloadRunsCsv(runs?: RunRecordV1[], filename?: string): void {
  const csv = exportRunsAsCsv(runs)
  const defaultFilename = `candyconc_runs_${new Date().toISOString().slice(0, 10)}.csv`
  downloadText(csv, filename ?? defaultFilename, 'text/csv')
}

/**
 * Download project
 */
export function downloadProject(projectId: string, filename?: string): void {
  const json = exportProjectAsJson(projectId, { pretty: true })
  if (json) {
    const project = getProject(projectId)
    const safeName = project?.name.replace(/[^a-z0-9]/gi, '_').toLowerCase() ?? 'project'
    const defaultFilename = `candyconc_project_${safeName}_${new Date().toISOString().slice(0, 10)}.json`
    downloadText(json, filename ?? defaultFilename, 'application/json')
  }
}

// ============================================================================
// Clear Functions
// ============================================================================

/**
 * Clear all data
 */
export function clearAllData(): void {
  clearTraceData()
  runProjects.value = []
  localStorage.removeItem(STORAGE_KEY_RUNS)
  localStorage.removeItem(STORAGE_KEY_TRACES)
  localStorage.removeItem(STORAGE_KEY_PROJECTS)
}

// ============================================================================
// Initialize
// ============================================================================

// Load on import
loadRunRecords()
