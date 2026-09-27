import type {
  RunEvidenceCompleteness,
  RunEvidenceProvenance,
  RunEvidenceResearchScopeStatus,
  RunRecordEvidenceV2,
  RunRecordResearchScopeEvidence,
  RunRecordV1,
} from '@/types/copilot-protocol'
import { quickHash } from '@/utils/hashing'

export interface CreateRunEvidenceOptions {
  provenance: RunEvidenceProvenance
  completeness?: RunEvidenceCompleteness
  corpusId: string
  subcorpusHash: string
  queryHash?: string
  actionType: string
  resultType: string
  resultHash?: string
  rows?: number
  indexFingerprint?: string
  metadataSchemaHash?: string
  researchScope?: Partial<RunRecordResearchScopeEvidence>
  scopeStatus?: RunEvidenceResearchScopeStatus
  scopeLabel?: string
  docsetId?: string
  subcorpusName?: string
  filterSpecHash?: string
  toolSchemaHash?: string
  queryTraceId?: string
  backendQueryTraceId?: string
  warnings?: string[]
}

export function createRunEvidenceV2(options: CreateRunEvidenceOptions): RunRecordEvidenceV2 {
  const completeness = normalizeCompleteness(options)
  return {
    schemaVersion: '2.0',
    provenance: options.provenance,
    completeness,
    corpusFingerprint: {
      corpusId: options.corpusId,
      subcorpusHash: options.subcorpusHash,
      queryHash: options.queryHash,
      indexFingerprint: options.indexFingerprint,
      metadataSchemaHash: options.metadataSchemaHash,
    },
    researchScope: buildResearchScopeEvidence(options),
    toolFingerprint: {
      actionType: options.actionType,
      toolSchemaHash: options.toolSchemaHash,
    },
    resultFingerprint: {
      resultType: options.resultType,
      resultHash: options.resultHash,
      rows: options.rows,
      queryTraceId: options.queryTraceId,
      backendQueryTraceId: options.backendQueryTraceId,
    },
    warnings: uniqueStrings([...(options.warnings ?? []), ...missingEvidenceWarnings(options)]),
  }
}

export function stableResultHash(value: unknown): string {
  return quickHash(stripVolatileResultFields(value))
}

export function withEvidenceQueryTraceId(
  evidence: RunRecordEvidenceV2,
  queryTraceId: string
): RunRecordEvidenceV2 {
  const existingTraceId = evidence.resultFingerprint.queryTraceId
  const nextTraceId = existingTraceId ?? queryTraceId
  const warnings = evidence.warnings.filter((warning) => warning !== 'Missing query trace id.')
  if (existingTraceId && existingTraceId !== queryTraceId) {
    // i18n-ignore-start: English warning stored in the run record, like the other evidence warnings in this file
    warnings.push(`Additional frontend trace observed without relinking evidence: ${queryTraceId}`)
    // i18n-ignore-end
  }

  return createRunEvidenceV2({
    provenance: evidence.provenance,
    completeness: evidence.completeness === 'legacy_partial' ? 'legacy_partial' : undefined,
    corpusId: evidence.corpusFingerprint.corpusId,
    subcorpusHash: evidence.corpusFingerprint.subcorpusHash,
    queryHash: evidence.corpusFingerprint.queryHash,
    indexFingerprint: evidence.corpusFingerprint.indexFingerprint,
    metadataSchemaHash: evidence.corpusFingerprint.metadataSchemaHash,
    researchScope: evidence.researchScope,
    actionType: evidence.toolFingerprint.actionType,
    toolSchemaHash: evidence.toolFingerprint.toolSchemaHash,
    resultType: evidence.resultFingerprint.resultType,
    resultHash: evidence.resultFingerprint.resultHash,
    rows: evidence.resultFingerprint.rows,
    queryTraceId: nextTraceId,
    backendQueryTraceId: evidence.resultFingerprint.backendQueryTraceId,
    warnings,
  })
}

export function normalizeRunEvidenceV2(
  rawEvidence: unknown,
  run: Pick<RunRecordV1, 'actionType' | 'corpus' | 'queryHash' | 'resultRef'>,
  provenance: RunEvidenceProvenance
): RunRecordEvidenceV2 {
  if (isRecord(rawEvidence) && rawEvidence.schemaVersion === '2.0') {
    const corpusFingerprint = isRecord(rawEvidence.corpusFingerprint)
      ? rawEvidence.corpusFingerprint
      : {}
    const toolFingerprint = isRecord(rawEvidence.toolFingerprint)
      ? rawEvidence.toolFingerprint
      : {}
    const resultFingerprint = isRecord(rawEvidence.resultFingerprint)
      ? rawEvidence.resultFingerprint
      : {}
    const researchScope = isRecord(rawEvidence.researchScope)
      ? rawEvidence.researchScope
      : {}

    return createRunEvidenceV2({
      provenance: readProvenance(rawEvidence.provenance, provenance),
      completeness: readCompleteness(rawEvidence.completeness),
      corpusId: readString(corpusFingerprint.corpusId, run.corpus.corpusId),
      subcorpusHash: readString(corpusFingerprint.subcorpusHash, run.corpus.subcorpusHash),
      queryHash: readOptionalString(corpusFingerprint.queryHash) ?? run.queryHash,
      indexFingerprint: readOptionalString(corpusFingerprint.indexFingerprint),
      metadataSchemaHash: readOptionalString(corpusFingerprint.metadataSchemaHash),
      researchScope: normalizeResearchScopeInput(researchScope),
      actionType: readString(toolFingerprint.actionType, run.actionType),
      toolSchemaHash: readOptionalString(toolFingerprint.toolSchemaHash),
      resultType: readString(resultFingerprint.resultType, run.resultRef.type),
      resultHash: readOptionalString(resultFingerprint.resultHash) ?? run.resultRef.hash,
      rows: readOptionalNumber(resultFingerprint.rows) ?? run.resultRef.rows,
      queryTraceId: readOptionalString(resultFingerprint.queryTraceId),
      backendQueryTraceId: readOptionalString(resultFingerprint.backendQueryTraceId),
      warnings: readWarnings(rawEvidence.warnings),
    })
  }

  return createRunEvidenceV2({
    provenance,
    completeness: 'legacy_partial',
    corpusId: run.corpus.corpusId,
    subcorpusHash: run.corpus.subcorpusHash,
    queryHash: run.queryHash,
    actionType: run.actionType,
    resultType: run.resultRef.type,
    resultHash: run.resultRef.hash,
    rows: run.resultRef.rows,
    warnings: ['Legacy RunRecord without V2 evidence metadata.'],
  })
}

function buildResearchScopeEvidence(options: CreateRunEvidenceOptions): RunRecordResearchScopeEvidence {
  const supplied = options.researchScope ?? {}
  return {
    corpusId: readString(supplied.corpusId, options.corpusId),
    scopeHash: readString(supplied.scopeHash, options.subcorpusHash),
    scopeStatus: readScopeStatus(supplied.scopeStatus, options.scopeStatus ?? 'unknown') ?? 'unknown',
    label: readOptionalString(supplied.label) ?? options.scopeLabel,
    docsetId: readOptionalString(supplied.docsetId) ?? options.docsetId,
    subcorpusName: readOptionalString(supplied.subcorpusName) ?? options.subcorpusName,
    queryHash: readOptionalString(supplied.queryHash) ?? options.queryHash,
    filterSpecHash: readOptionalString(supplied.filterSpecHash) ?? options.filterSpecHash,
    metadataSchemaHash: readOptionalString(supplied.metadataSchemaHash) ?? options.metadataSchemaHash,
  }
}

function normalizeResearchScopeInput(value: Record<string, unknown>): Partial<RunRecordResearchScopeEvidence> {
  return {
    corpusId: readOptionalString(value.corpusId),
    scopeHash: readOptionalString(value.scopeHash),
    scopeStatus: readScopeStatus(value.scopeStatus, undefined),
    label: readOptionalString(value.label),
    docsetId: readOptionalString(value.docsetId),
    subcorpusName: readOptionalString(value.subcorpusName),
    queryHash: readOptionalString(value.queryHash),
    filterSpecHash: readOptionalString(value.filterSpecHash),
    metadataSchemaHash: readOptionalString(value.metadataSchemaHash),
  }
}

function inferCompleteness(options: CreateRunEvidenceOptions): RunEvidenceCompleteness {
  return options.indexFingerprint
    && options.metadataSchemaHash
    && options.toolSchemaHash
    && options.queryTraceId
    && options.resultHash
    ? 'full'
    : 'partial'
}

function normalizeCompleteness(options: CreateRunEvidenceOptions): RunEvidenceCompleteness {
  if (options.completeness === 'legacy_partial') return 'legacy_partial'
  const inferred = inferCompleteness(options)
  if (options.completeness === 'full' && inferred !== 'full') return 'partial'
  return options.completeness ?? inferred
}

function missingEvidenceWarnings(options: CreateRunEvidenceOptions): string[] {
  const warnings: string[] = []
  if (!options.indexFingerprint) warnings.push('Missing index fingerprint.')
  if (!options.metadataSchemaHash) warnings.push('Missing metadata schema hash.')
  if (!options.toolSchemaHash) warnings.push('Missing tool schema hash.')
  if (!options.queryTraceId) warnings.push('Missing query trace id.')
  if (!options.resultHash) warnings.push('Missing canonical result hash.')
  if (options.provenance === 'backend_action_result') {
    warnings.push('Backend-owned SSE mirror; not authoritative backend history sync.')
  }
  return warnings
}

function readProvenance(value: unknown, fallback: RunEvidenceProvenance): RunEvidenceProvenance {
  return value === 'frontend_actionbus' || value === 'backend_action_result' || value === 'imported_legacy'
    ? value
    : fallback
}

function readCompleteness(value: unknown): RunEvidenceCompleteness | undefined {
  return value === 'full' || value === 'partial' || value === 'legacy_partial'
    ? value
    : undefined
}

function readScopeStatus(
  value: unknown,
  fallback: RunEvidenceResearchScopeStatus | undefined
): RunEvidenceResearchScopeStatus | undefined {
  return value === 'corpus'
    || value === 'fresh'
    || value === 'dirty'
    || value === 'stale'
    || value === 'warning'
    || value === 'unknown'
    ? value
    : fallback
}

function readString(value: unknown, fallback: string): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback
}

function readOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.length > 0 ? value : undefined
}

function readOptionalNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function readWarnings(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((warning): warning is string => typeof warning === 'string')
    : []
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function uniqueStrings(values: string[]): string[] {
  return [...new Set(values)]
}

function stripVolatileResultFields(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map(stripVolatileResultFields)
  }
  if (!isRecord(value)) return value

  const result: Record<string, unknown> = {}
  const volatileKeys = new Set([
    'queryTime',
    'query_time_ms',
    'duration',
    'durationMs',
    'elapsedMs',
    'ts',
    'timestamp',
    'requestId',
    'runId',
    'jobId',
    'traceId',
    'queryTraceId',
    'query_trace_id',
    'backendQueryTraceId',
    'backend_query_trace_id',
  ])
  for (const [key, fieldValue] of Object.entries(value)) {
    if (volatileKeys.has(key)) {
      continue
    }
    result[key] = stripVolatileResultFields(fieldValue)
  }
  return result
}
