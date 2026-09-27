import type { CorpusImportReportsResponse } from '@/api/client'
import { formatNumber } from '@/i18n/format'
import { t } from '@/i18n'

export type ImportReportPayload = CorpusImportReportsResponse['reports'] | Record<string, unknown> | unknown[] | undefined
export type ImportReportDiagnosticSeverity = 'info' | 'warning' | 'error' | 'success'
export type ImportReportRole = 'build' | 'quality' | 'manifest' | 'metadata' | 'debug' | 'unknown'

export interface ImportReportDiagnostic {
  key: string
  label: string
  severity: ImportReportDiagnosticSeverity
  value?: string
  note?: string
}

export interface ImportReportEntry {
  key: string
  label: string
  role: ImportReportRole
  known: boolean
  expertOnly: boolean
  summary: string
  snippet: string | null
  fullText: string | null
  diagnostics: ImportReportDiagnostic[]
}

export interface ImportReportOutcome {
  partialInput: boolean
  rejectedRows: number
  warningCount: number
  warnings: string[]
  readiness: 'complete' | 'partial_input' | 'unknown'
}

const ENVELOPE_KEYS = new Set(['schema_version', 'job_id', 'corpus', 'path'])
const RAW_SNIPPET_LIMIT = 360
const DEFAULT_SNIPPET_LIMIT = 700

interface ReportDescriptor {
  label: string
  role: ImportReportRole
  order: number
  expertOnly?: boolean
  summary?: string
}

// Getters resolve labels at read time so a language switch relabels reports.
function describe(labelKey: string, summaryKey: string, role: ImportReportRole, order: number, expertOnly = false): ReportDescriptor {
  return {
    get label() { return t(labelKey) },
    get summary() { return t(summaryKey) },
    role,
    order,
    ...(expertOnly ? { expertOnly } : {}),
  }
}

const REPORT_DESCRIPTORS: Record<string, ReportDescriptor> = {
  build_report: describe('corpus.reports.buildReport', 'corpus.reports.buildReportSummary', 'build', 10),
  build_report_md: describe('corpus.reports.buildReportMd', 'corpus.reports.buildReportMdSummary', 'build', 20),
  reject_report: describe('corpus.reports.rejectReport', 'corpus.reports.rejectReportSummary', 'quality', 30),
  vrt_import_report: describe('corpus.reports.vrtReport', 'corpus.reports.vrtReportSummary', 'quality', 40),
  manifest: describe('corpus.reports.manifest', 'corpus.reports.manifestSummary', 'manifest', 50),
  build_meta: describe('corpus.reports.buildMeta', 'corpus.reports.buildMetaSummary', 'metadata', 60),
  import_outcome: describe('corpus.reports.importOutcome', 'corpus.reports.importOutcomeSummary', 'quality', 35),
  raw: describe('corpus.reports.raw', 'corpus.reports.rawSummary', 'debug', 900, true),
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null
}

function unwrapReportPayload(reports: ImportReportPayload): ImportReportPayload {
  const record = asRecord(reports)
  if (!record || !('reports' in record)) return reports
  if (!('schema_version' in record) && !('job_id' in record) && !('corpus' in record)) return reports
  return record.reports as ImportReportPayload
}

function formatBytes(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function formatScalar(value: unknown): string | null {
  if (value === undefined || value === null || value === '') return null
  if (typeof value === 'number') return Number.isFinite(value) ? formatNumber(value) : null
  if (typeof value === 'boolean') return value ? t('corpus.shared.yes') : t('corpus.shared.no')
  if (Array.isArray(value)) return value.length ? value.map((item) => String(item)).join(', ') : null
  if (typeof value === 'object') return null
  return String(value)
}

function firstValue(record: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    if (record[key] !== undefined && record[key] !== null && record[key] !== '') return record[key]
  }
  return undefined
}

function reportData(value: unknown): unknown {
  const record = asRecord(value)
  if (!record) return value
  return record.data ?? record
}

function nonnegativeInteger(value: unknown): number | null {
  if (typeof value === 'boolean' || value === undefined || value === null || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? Math.max(0, Math.trunc(parsed)) : null
}

function firstInteger(record: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = nonnegativeInteger(record[key])
    if (value !== null) return value
  }
  return null
}

function appendWarning(warnings: string[], message: string): void {
  const text = message.trim()
  if (text && !warnings.includes(text)) warnings.push(text)
}

function redactedSnippetData(value: unknown): unknown {
  if (Array.isArray(value)) return value.map((item) => redactedSnippetData(item))
  const record = asRecord(value)
  if (!record) return value
  const next: Record<string, unknown> = {}
  for (const [key, item] of Object.entries(record)) {
    if (['samples', 'examples', 'sample_rows'].includes(key)) {
      const count = Array.isArray(item) ? item.length : undefined
      next[key] = count === undefined ? t('corpus.reports.redacted') : t('corpus.reports.redactedSamples', { count: String(count) }, count)
    } else {
      next[key] = redactedSnippetData(item)
    }
  }
  return next
}

function reportSnippet(value: unknown, limit = DEFAULT_SNIPPET_LIMIT): string | null {
  const data = reportData(value)
  if (data === null || data === undefined) return null
  const text = typeof data === 'string' ? data : JSON.stringify(redactedSnippetData(data), null, 2)
  return text.length > limit ? `${text.slice(0, limit)} …` : text
}

function reportFullText(value: unknown): string | null {
  if (value === null || value === undefined) return null
  return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
}

function reportSummary(value: unknown, descriptor?: ReportDescriptor): string {
  const record = asRecord(value)
  if (!record) return typeof value === 'string' ? t('corpus.reports.textReport') : descriptor?.summary ?? t('corpus.reports.report')
  if (record.error) return t('corpus.reports.limited', { error: String(record.error) })
  const parts = [
    record.content_type ? String(record.content_type) : null,
    formatBytes(record.bytes),
    record.path ? t('corpus.reports.path', { path: String(record.path) }) : null,
    record.url ? `URL: ${String(record.url)}` : null,
  ].filter((part): part is string => Boolean(part))
  return parts.join(' · ') || descriptor?.summary || t('corpus.reports.reportLoaded')
}

function readableReportLabel(key: string, fallback?: unknown): string {
  const record = asRecord(fallback)
  const explicit = record?.label ?? record?.kind
  if (explicit) return String(explicit)
  return REPORT_DESCRIPTORS[key]?.label ?? t('corpus.reports.untyped', { key })
}

function pushDiagnostic(
  out: ImportReportDiagnostic[],
  key: string,
  label: string,
  severity: ImportReportDiagnosticSeverity,
  value?: unknown,
  note?: string
) {
  const formatted = formatScalar(value)
  if (!formatted && !note) return
  out.push({ key, label, severity, value: formatted ?? undefined, note })
}

function rejectDiagnostics(key: string, data: Record<string, unknown>): ImportReportDiagnostic[] {
  const out: ImportReportDiagnostic[] = []
  const rejected = firstValue(data, ['rejected_rows', 'rejected', 'reject_count', 'rows_rejected'])
  const total = firstValue(data, ['total_rows', 'rows_total', 'processed_rows', 'rows_seen'])
  const rejectionRate = firstValue(data, ['rejection_rate', 'reject_rate'])
  const byReason = firstValue(data, ['by_reason', 'reasons', 'reject_reasons'])
  const samples = firstValue(data, ['samples', 'examples', 'sample_rows'])
  const rejectedNumber = typeof rejected === 'number' ? rejected : Number(rejected)
  const hasRejects = Number.isFinite(rejectedNumber) && rejectedNumber > 0
  pushDiagnostic(
    out,
    `${key}:rejected_rows`,
    t('corpus.reports.rejectedRows'),
    hasRejects ? 'warning' : 'success',
    rejected ?? 0,
    hasRejects
      ? t('corpus.reports.rejectedRowsNote')
      : t('corpus.reports.noRejectedRows')
  )
  pushDiagnostic(out, `${key}:total_rows`, t('corpus.reports.checkedRows'), 'info', total)
  pushDiagnostic(out, `${key}:rejection_rate`, t('corpus.reports.rejectRate'), hasRejects ? 'warning' : 'info', rejectionRate)
  if (byReason && typeof byReason === 'object') {
    const reasonCount = Array.isArray(byReason) ? byReason.length : Object.keys(byReason as Record<string, unknown>).length
    pushDiagnostic(out, `${key}:by_reason`, t('corpus.reports.rejectReasons'), hasRejects ? 'warning' : 'info', reasonCount, t('corpus.reports.rejectReasonsNote'))
  }
  if (Array.isArray(samples)) {
    pushDiagnostic(out, `${key}:samples`, t('corpus.reports.rejectSamples'), 'warning', samples.length, t('corpus.reports.rejectSamplesNote'))
  }
  pushDiagnostic(out, `${key}:policy`, t('corpus.reports.rejectPolicy'), 'info', firstValue(data, ['reject_policy', 'policy']))
  return out
}

function manifestDiagnostics(key: string, data: Record<string, unknown>): ImportReportDiagnostic[] {
  const out: ImportReportDiagnostic[] = []
  pushDiagnostic(out, `${key}:import_mode`, t('corpus.reports.importMode'), 'info', firstValue(data, ['import_mode', 'mode']))
  pushDiagnostic(out, `${key}:tokens`, 'Tokens', 'info', firstValue(data, ['token_count', 'tokens', 'n_tokens']))
  pushDiagnostic(out, `${key}:docs`, t('corpus.reports.documents'), 'info', firstValue(data, ['doc_count', 'documents', 'n_docs']))
  if (data.complete !== undefined) {
    pushDiagnostic(
      out,
      `${key}:complete`,
      t('corpus.reports.manifestComplete'),
      data.complete === false ? 'error' : 'success',
      data.complete,
      data.complete === false ? t('corpus.reports.manifestIncompleteNote') : undefined
    )
  }
  const capabilities = firstValue(data, ['capabilities', 'features'])
  if (capabilities && typeof capabilities === 'object') {
    const items = Array.isArray(capabilities)
      ? capabilities.map((item) => String(item))
      : Object.entries(capabilities as Record<string, unknown>)
        .filter(([, value]) => Boolean(value))
        .map(([name]) => name)
    pushDiagnostic(out, `${key}:capabilities`, t('corpus.reports.manifestCapabilities'), 'info', items.slice(0, 12))
  }
  const alignment = asRecord(asRecord(data.features)?.alignment)
  const pairingSchema = asRecord(firstValue(data, ['pairing_schema']))
    ?? asRecord(alignment?.pairing_schema)
  const paired = data.paired ?? alignment?.paired
  const pairedDataDependent = data.paired_data_dependent ?? alignment?.paired_data_dependent
  if (paired !== undefined || pairedDataDependent !== undefined) {
    pushDiagnostic(
      out,
      `${key}:paired`,
      t('corpus.reports.pairMetadata'),
      paired || pairedDataDependent ? 'info' : 'success',
      pairedDataDependent && !paired ? t('corpus.reports.dataDependent') : paired,
      paired
        ? t('corpus.reports.pairMetadataNote')
        : pairedDataDependent
          ? t('corpus.reports.pairMetadataDependentNote')
        : undefined
    )
  }
  pushDiagnostic(out, `${key}:pairing_kind`, t('corpus.reports.pairingKind'), 'info', firstValue(data, ['pairing_kind', 'pairing_mode']))
  pushDiagnostic(out, `${key}:pairing_schema`, t('corpus.reports.pairingSchema'), 'info', pairingSchema?.schema_id)
  pushDiagnostic(out, `${key}:pair_group`, t('corpus.reports.pairingGroupField'), 'info', firstValue(data, ['group_key_field', 'pair_key_field']) ?? pairingSchema?.group_key_field)
  pushDiagnostic(out, `${key}:anchor_role_field`, t('corpus.reports.anchorRoleField'), 'info', firstValue(data, ['anchor_role_field', 'pair_role_field']) ?? pairingSchema?.anchor_role_field)
  pushDiagnostic(out, `${key}:anchor_role`, t('corpus.reports.defaultAnchorRole'), 'info', firstValue(data, ['anchor_role', 'default_anchor_role']) ?? pairingSchema?.default_anchor_role)
  pushDiagnostic(
    out,
    `${key}:pair_axes`,
    t('corpus.reports.pairAxes'),
    'info',
    firstValue(data, ['pair_axes', 'pair_axis', 'axes']) ?? pairingSchema?.variant_axis_fields
  )
  const incompletePairs = firstValue(data, ['incomplete_pairs', 'incomplete_pair_count', 'unpaired_rows', 'orphan_rows'])
  const incompletePairsNumber = typeof incompletePairs === 'number' ? incompletePairs : Number(incompletePairs)
  pushDiagnostic(
    out,
    `${key}:incomplete_pairs`,
    t('corpus.reports.incompletePairs'),
    incompletePairsNumber > 0 ? 'warning' : 'info',
    incompletePairs,
    incompletePairsNumber > 0 ? t('corpus.reports.incompletePairsNote') : undefined
  )
  pushDiagnostic(out, `${key}:pair_count`, t('corpus.reports.pairCount'), 'info', firstValue(data, ['pair_count', 'distinct_pairs', 'pairs']))
  pushDiagnostic(out, `${key}:annotation_source`, t('corpus.reports.annotationSource'), 'info', firstValue(data, ['annotation_source', 'annotations_source']))
  return out
}

function buildDiagnostics(key: string, data: Record<string, unknown>): ImportReportDiagnostic[] {
  const out: ImportReportDiagnostic[] = []
  const status = firstValue(data, ['status', 'state'])
  const error = firstValue(data, ['error', 'exception'])
  const warnings = firstValue(data, ['warnings', 'warning'])
  pushDiagnostic(out, `${key}:status`, 'Status', error ? 'error' : 'info', status)
  pushDiagnostic(out, `${key}:error`, t('corpus.reports.error'), 'error', error)
  pushDiagnostic(out, `${key}:warnings`, t('corpus.reports.warnings'), 'warning', warnings)
  pushDiagnostic(out, `${key}:builder`, 'Builder', 'info', firstValue(data, ['builder', 'command', 'method']))
  pushDiagnostic(out, `${key}:output`, t('corpus.reports.output'), 'info', firstValue(data, ['output_path', 'target_path', 'path']))
  pushDiagnostic(out, `${key}:elapsed`, t('corpus.reports.elapsed'), 'info', firstValue(data, ['elapsed_s', 'elapsed_seconds', 'duration_s']))
  pushDiagnostic(out, `${key}:tokens`, 'Tokens', 'info', firstValue(data, ['token_count', 'tokens', 'n_tokens']))
  pushDiagnostic(out, `${key}:docs`, t('corpus.reports.documents'), 'info', firstValue(data, ['doc_count', 'documents', 'n_docs']))
  pushDiagnostic(out, `${key}:fingerprint`, t('corpus.reports.buildFingerprint'), 'info', firstValue(data, ['build_fingerprint', 'fingerprint', 'sha256']))
  pushDiagnostic(out, `${key}:created_at`, t('corpus.reports.createdAt'), 'info', firstValue(data, ['created_at', 'created', 'timestamp']))
  const preflight = firstValue(data, ['preflight', 'preflight_summary'])
  if (preflight && typeof preflight === 'object') {
    pushDiagnostic(out, `${key}:preflight`, t('corpus.reports.preflightEvidence'), 'info', t('corpus.reports.present'))
  }
  return out
}

function vrtDiagnostics(key: string, data: Record<string, unknown>): ImportReportDiagnostic[] {
  const out: ImportReportDiagnostic[] = []
  const skippedShort = firstValue(data, ['skipped_short_docs', 'short_docs_skipped'])
  const skippedOutside = firstValue(data, ['skipped_outside_docs', 'outside_docs_skipped'])
  const inconsistent = firstValue(data, ['inconsistent_column_lines', 'inconsistent_lines'])
  const skippedShortNumber = typeof skippedShort === 'number' ? skippedShort : Number(skippedShort)
  const skippedOutsideNumber = typeof skippedOutside === 'number' ? skippedOutside : Number(skippedOutside)
  const inconsistentNumber = typeof inconsistent === 'number' ? inconsistent : Number(inconsistent)
  pushDiagnostic(out, `${key}:documents`, t('corpus.reports.vrtDocuments'), 'info', firstValue(data, ['documents', 'doc_count', 'n_docs']))
  pushDiagnostic(out, `${key}:tokens`, t('corpus.reports.vrtTokens'), 'info', firstValue(data, ['tokens', 'token_count', 'n_tokens']))
  pushDiagnostic(out, `${key}:regions`, t('corpus.reports.regions'), 'info', firstValue(data, ['regions', 'structures', 'region_count']))
  pushDiagnostic(out, `${key}:annotation_mode`, t('corpus.reports.annotationMode'), 'info', firstValue(data, ['annotation_mode', 'index_annotations']))
  pushDiagnostic(out, `${key}:inferred_columns`, t('corpus.reports.inferredColumns'), 'info', firstValue(data, ['inferred_columns', 'columns']))
  pushDiagnostic(out, `${key}:skipped_short`, t('corpus.reports.skippedShort'), skippedShortNumber > 0 ? 'warning' : 'info', skippedShort)
  pushDiagnostic(out, `${key}:skipped_outside`, t('corpus.reports.skippedOutside'), skippedOutsideNumber > 0 ? 'warning' : 'info', skippedOutside)
  pushDiagnostic(out, `${key}:inconsistent_lines`, t('corpus.reports.inconsistentLines'), inconsistentNumber > 0 ? 'warning' : 'info', inconsistent)
  pushDiagnostic(out, `${key}:warnings`, t('corpus.reports.warnings'), 'warning', firstValue(data, ['warnings', 'warning']))
  pushDiagnostic(out, `${key}:errors`, t('corpus.reports.error'), 'error', firstValue(data, ['errors', 'error']))
  return out
}

function rawDiagnostics(key: string, data: Record<string, unknown>): ImportReportDiagnostic[] {
  const keys = Object.keys(data).sort()
  const out: ImportReportDiagnostic[] = []
  pushDiagnostic(
    out,
    `${key}:scope`,
    t('corpus.reports.debugScope'),
    'warning',
    t('corpus.reports.rawData'),
    t('corpus.reports.rawDataNote')
  )
  pushDiagnostic(out, `${key}:keys`, t('corpus.reports.reportKeys'), 'info', keys.length ? keys.join(', ') : t('corpus.reports.none'))
  return out
}

function genericDiagnostics(key: string, data: Record<string, unknown>): ImportReportDiagnostic[] {
  const out: ImportReportDiagnostic[] = []
  if (key === 'raw') return rawDiagnostics(key, data)
  if (key.includes('reject')) out.push(...rejectDiagnostics(key, data))
  if (key.includes('vrt')) out.push(...vrtDiagnostics(key, data))
  if (key.includes('manifest')) out.push(...manifestDiagnostics(key, data))
  if (key.includes('build') || key.includes('meta')) out.push(...buildDiagnostics(key, data))
  if (!out.length) {
    pushDiagnostic(out, `${key}:status`, 'Status', 'info', firstValue(data, ['status', 'state', 'result']))
    pushDiagnostic(out, `${key}:rows`, t('corpus.reports.rows'), 'info', firstValue(data, ['rows', 'row_count', 'count']))
  }
  return out
}

function isEmptyReportValue(value: unknown): boolean {
  if (value === undefined || value === null) return true
  if (typeof value === 'string') return value.trim() === ''
  if (Array.isArray(value)) return value.length === 0
  const record = asRecord(value)
  if (!record) return false
  if ('data' in record) return isEmptyReportValue(record.data)
  return Object.keys(record).length === 0
}

function reportDescriptor(key: string): ReportDescriptor {
  return REPORT_DESCRIPTORS[key] ?? {
    label: t('corpus.reports.untyped', { key }),
    role: 'unknown',
    order: 800,
    expertOnly: true,
    summary: t('corpus.reports.untypedSummary'),
  }
}

function reportEntry(key: string, value: unknown, index = 0): ImportReportEntry {
  const record = asRecord(value)
  const fallbackKey = key || `report-${index + 1}`
  const entryKey = String(record?.kind ?? record?.key ?? fallbackKey)
  const descriptor = reportDescriptor(entryKey)
  const data = reportData(value)
  const dataRecord = asRecord(data)
  return {
    key: entryKey,
    role: descriptor.role,
    known: Boolean(REPORT_DESCRIPTORS[entryKey]),
    expertOnly: Boolean(descriptor.expertOnly),
    label: readableReportLabel(entryKey, value),
    summary: reportSummary(value, descriptor),
    snippet: reportSnippet(value, descriptor.expertOnly ? RAW_SNIPPET_LIMIT : DEFAULT_SNIPPET_LIMIT),
    fullText: reportFullText(value),
    diagnostics: dataRecord ? genericDiagnostics(entryKey, dataRecord) : [],
  }
}

function compareReportEntries(left: ImportReportEntry, right: ImportReportEntry): number {
  return reportDescriptor(left.key).order - reportDescriptor(right.key).order || left.key.localeCompare(right.key)
}

export function importReportOutcomeFromPayload(reports: ImportReportPayload): ImportReportOutcome {
  const payload = unwrapReportPayload(reports)
  const warnings: string[] = []
  let rejectedRows = 0
  let partialInput = false

  const record = asRecord(payload)
  if (!record) {
    return {
      partialInput: false,
      rejectedRows: 0,
      warningCount: 0,
      warnings,
      readiness: 'unknown',
    }
  }

  const rejectReport = asRecord(reportData(record.reject_report))
  if (rejectReport) {
    rejectedRows = firstInteger(
      rejectReport,
      ['rejected_rows', 'rows_rejected', 'reject_count', 'rejected_count', 'rejected'],
    ) ?? 0
    if (rejectedRows > 0) {
      partialInput = true
      appendWarning(warnings, t('corpus.reports.outcomeRejected', { count: formatNumber(rejectedRows) }, rejectedRows))
    }
  }

  const persistedOutcome = asRecord(reportData(record.import_outcome))
  if (persistedOutcome) {
    partialInput = partialInput || Boolean(persistedOutcome.partial_input)
    rejectedRows = Math.max(
      rejectedRows,
      firstInteger(persistedOutcome, ['rejected_rows']) ?? 0,
    )
    const persistedWarnings = persistedOutcome.import_warnings
    if (Array.isArray(persistedWarnings)) {
      for (const warning of persistedWarnings.slice(0, 5)) {
        appendWarning(warnings, String(warning))
      }
    }
  }

  const manifest = asRecord(reportData(record.manifest))
  if (manifest?.complete === false) {
    partialInput = true
    appendWarning(warnings, t('corpus.reports.outcomeManifestIncomplete'))
  }
  if (manifest) {
    const incompletePairs = firstInteger(
      manifest,
      ['incomplete_pairs', 'incomplete_pair_count', 'unpaired_rows', 'orphan_rows'],
    )
    if (incompletePairs && incompletePairs > 0) {
      appendWarning(warnings, t('corpus.reports.outcomeIncompletePairs', { count: formatNumber(incompletePairs) }, incompletePairs))
    }
  }

  const vrtReport = asRecord(reportData(record.vrt_import_report))
  if (vrtReport) {
    const skipped = (
      (firstInteger(vrtReport, ['skipped_short_docs', 'short_docs_skipped']) ?? 0) +
      (firstInteger(vrtReport, ['skipped_outside_docs', 'outside_docs_skipped']) ?? 0)
    )
    const inconsistent = firstInteger(vrtReport, ['inconsistent_column_lines', 'inconsistent_lines']) ?? 0
    if (skipped > 0) {
      partialInput = true
      appendWarning(warnings, t('corpus.reports.outcomeVrtSkipped', { count: formatNumber(skipped) }, skipped))
    }
    if (inconsistent > 0) {
      partialInput = true
      appendWarning(warnings, t('corpus.reports.outcomeVrtInconsistent', { count: formatNumber(inconsistent) }, inconsistent))
    }
  }

  for (const key of ['build_report', 'build_meta']) {
    const data = asRecord(reportData(record[key]))
    const reportWarnings = data?.warnings
    if (Array.isArray(reportWarnings)) {
      for (const warning of reportWarnings.slice(0, 5)) {
        appendWarning(warnings, `${key}: ${String(warning)}`)
      }
    } else if (typeof reportWarnings === 'string') {
      appendWarning(warnings, `${key}: ${reportWarnings}`)
    }
  }

  return {
    partialInput,
    rejectedRows,
    warningCount: warnings.length,
    warnings,
    readiness: partialInput ? 'partial_input' : 'complete',
  }
}

export function importReportEntriesFromPayload(reports: ImportReportPayload): ImportReportEntry[] {
  const payload = unwrapReportPayload(reports)
  if (!payload) return []
  if (Array.isArray(payload)) {
    return payload
      .filter((item) => !isEmptyReportValue(item))
      .map((item, index) => reportEntry(`report-${index + 1}`, item, index))
      .sort(compareReportEntries)
  }
  return Object.entries(payload)
    .filter(([key]) => !ENVELOPE_KEYS.has(key))
    .filter(([, value]) => !isEmptyReportValue(value))
    .map(([key, value], index) => reportEntry(key, value, index))
    .sort(compareReportEntries)
}
