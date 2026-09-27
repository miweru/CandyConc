import type { CorpusImportPreflightResponse } from '@/api/client'
import { t } from '@/i18n'

export interface CorpusImportEvidenceFact {
  key: string
  label: string
  value: string
}

export interface CorpusImportResolvedColumn {
  key: string
  label: string
  required: boolean
  configuredBy: string | null
  resolvedName: string | null
  resolvedBy: 'field' | 'default' | 'mapping' | 'unset'
}

export interface CorpusImportMappingSuggestion {
  missingColumn: string
  candidateColumns: string[]
  safeMapping: string | null
  fallbackBehavior: string | null
}

type UnknownRecord = Record<string, unknown>

function asRecord(value: unknown): UnknownRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as UnknownRecord
    : null
}

function valueText(value: unknown): string | null {
  if (value === undefined || value === null || value === '') return null
  if (Array.isArray(value)) return value.map((item) => String(item)).join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function firstText(record: UnknownRecord | null, keys: readonly string[]): string | null {
  if (!record) return null
  for (const key of keys) {
    const text = valueText(record[key])
    if (text) return text
  }
  return null
}

function normalizedPayloadOptions(result: CorpusImportPreflightResponse): UnknownRecord | null {
  return asRecord(asRecord(result.normalized_payload)?.options)
}

export function preflightTargetFacts(
  result: CorpusImportPreflightResponse,
): CorpusImportEvidenceFact[] {
  const evidence = asRecord(result.evidence) ?? {}
  const normalizedPayload = asRecord(result.normalized_payload)
  const normalizedOptions = normalizedPayloadOptions(result)
  const facts: CorpusImportEvidenceFact[] = []
  const targetName = firstText(evidence, ['target_name', 'targetName'])
    ?? firstText(normalizedPayload, ['target_name', 'targetName', 'target'])
    ?? firstText(normalizedOptions, ['target_name', 'targetName', 'target'])
  const managedDir = firstText(evidence, ['managed_corpus_dir', 'corpora_dir'])
    ?? firstText(normalizedPayload, ['managed_corpus_dir', 'corpora_dir'])
    ?? firstText(normalizedOptions, ['managed_corpus_dir', 'corpora_dir'])
  const targetPath = firstText(evidence, ['target_path', 'target'])
    ?? firstText(normalizedPayload, ['target_path', 'target'])
    ?? firstText(normalizedOptions, ['target_path', 'target'])
  const stagingPath = firstText(evidence, ['staging_path', 'staging'])
    ?? firstText(normalizedPayload, ['staging_path', 'staging'])
    ?? firstText(normalizedOptions, ['staging_path', 'staging'])

  if (targetName) facts.push({ key: 'target_name', label: t('corpus.importEvidence.targetName'), value: targetName })
  if (managedDir) facts.push({ key: 'managed_corpus_dir', label: t('corpus.importEvidence.managedDir'), value: managedDir })
  if (targetPath) facts.push({ key: 'target_path', label: t('corpus.importEvidence.targetPath'), value: targetPath })
  if (stagingPath) facts.push({ key: 'staging_path', label: t('corpus.importEvidence.stagingPath'), value: stagingPath })
  return facts
}

export function formatEvidenceBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return t('corpus.cataloguePolicy.unknown')
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(1)} GB`
}

/**
 * Vom Backend gemeldete Spalten-Mapping-Vorschläge (csv/jsonl/parquet), wenn die
 * konfigurierte Textspalte fehlt, aber Kandidatenspalten in der Quelle existieren.
 * Alle Texte stammen aus der Preflight-Evidenz des Backends.
 */
export function preflightMappingSuggestions(
  result: CorpusImportPreflightResponse,
): CorpusImportMappingSuggestion[] {
  const evidence = asRecord(result.evidence) ?? {}
  const raw = evidence.column_mapping_suggestions
  if (!Array.isArray(raw)) return []
  return raw.flatMap((item): CorpusImportMappingSuggestion[] => {
    const record = asRecord(item)
    const missingColumn = firstText(record, ['missing_column'])
    if (!record || !missingColumn) return []
    const candidateColumns = Array.isArray(record.candidate_columns)
      ? record.candidate_columns.map((column) => String(column)).filter(Boolean)
      : []
    return [{
      missingColumn,
      candidateColumns,
      safeMapping: firstText(record, ['safe_mapping']),
      fallbackBehavior: firstText(record, ['fallback_behavior']),
    }]
  })
}

/**
 * Bounded Plaintext-Strukturzusammenfassung aus der Preflight-Evidenz
 * (Dateizahl, Gesamtgröße, Register-Vorschau, Encoding-Stichprobe).
 */
export function preflightPlaintextFacts(
  result: CorpusImportPreflightResponse,
): CorpusImportEvidenceFact[] {
  const evidence = asRecord(result.evidence) ?? {}
  const sample = asRecord(evidence.plaintext)
  if (!sample) return []
  const facts: CorpusImportEvidenceFact[] = []
  const pattern = firstText(sample, ['pattern'])
  if (pattern) facts.push({ key: 'pattern', label: t('corpus.importEvidence.filePattern'), value: pattern })
  if (typeof sample.file_count === 'number' && Number.isFinite(sample.file_count)) {
    facts.push({
      key: 'file_count',
      label: t('corpus.importEvidence.files'),
      value: sample.file_scan_truncated === true
        ? t('corpus.importEvidence.filesAtLeast', { count: String(sample.file_count) })
        : String(sample.file_count),
    })
  }
  if (typeof sample.total_size_bytes === 'number' && Number.isFinite(sample.total_size_bytes)) {
    facts.push({
      key: 'total_size_bytes',
      label: t('corpus.importEvidence.totalSize'),
      value: formatEvidenceBytes(sample.total_size_bytes),
    })
  }
  const registers = Array.isArray(sample.registers_preview)
    ? sample.registers_preview.map((item) => String(item)).filter(Boolean)
    : []
  if (registers.length) {
    facts.push({ key: 'registers_preview', label: t('corpus.importEvidence.registerPreview'), value: registers.join(', ') })
  }
  const utf8Files = typeof sample.encoding_utf8_files === 'number' ? sample.encoding_utf8_files : null
  const fallbackFiles = typeof sample.encoding_fallback_files === 'number' ? sample.encoding_fallback_files : null
  if (utf8Files !== null || fallbackFiles !== null) {
    facts.push({
      key: 'encoding_sample',
      label: t('corpus.importEvidence.encodingSample'),
      value: t('corpus.importEvidence.encodingValue', { utf8: String(utf8Files ?? 0), fallback: String(fallbackFiles ?? 0) }),
    })
  }
  return facts
}

/**
 * Ehrliche Offline-Markierung des HF-Preflights: das Backend validiert nur den
 * Descriptor ohne Netzzugriff (evidence.hf.descriptor_only / network_access).
 */
export function preflightOfflineValidationFacts(
  result: CorpusImportPreflightResponse,
): CorpusImportEvidenceFact[] {
  const evidence = asRecord(result.evidence) ?? {}
  const hf = asRecord(evidence.hf)
  if (!hf) return []
  const facts: CorpusImportEvidenceFact[] = []
  const dataset = firstText(hf, ['dataset'])
  if (dataset) facts.push({ key: 'hf_dataset', label: t('corpus.importEvidence.datasetId'), value: dataset })
  if (hf.descriptor_only === true || hf.network_access === false) {
    facts.push({
      key: 'hf_offline_preflight',
      label: t('corpus.importEvidence.offlinePreflight'),
      value: t('corpus.importEvidence.offlineValue'),
    })
  }
  return facts
}

export function resolvedPreflightColumns(
  result: CorpusImportPreflightResponse,
): CorpusImportResolvedColumn[] {
  const evidence = asRecord(result.evidence) ?? {}
  const methodContract = asRecord(evidence.method_contract)
  const normalizedPayload = asRecord(result.normalized_payload)
  const normalizedOptions = normalizedPayloadOptions(result)
  const expectedColumns = Array.isArray(methodContract?.expected_columns)
    ? methodContract.expected_columns
    : []
  const optionSpecs = Array.isArray(methodContract?.option_specs) ? methodContract.option_specs : []

  return expectedColumns.flatMap((rawColumn): CorpusImportResolvedColumn[] => {
    const column = asRecord(rawColumn)
    const key = firstText(column, ['key'])
    if (!column || !key) return []
    const configuredBy = firstText(column, ['configured_by', 'configuredBy'])
    const configuredValue = configuredBy
      ? firstText(normalizedOptions, [configuredBy]) ?? firstText(normalizedPayload, [configuredBy])
      : null
    const optionSpec = asRecord(optionSpecs.find((rawSpec) => firstText(asRecord(rawSpec), ['key']) === configuredBy))
    const defaultValue = configuredBy
      ? firstText(column, ['default']) ?? firstText(optionSpec, ['default'])
      : null
    const resolvedName = configuredBy ? configuredValue ?? defaultValue : key
    return [{
      key,
      label: firstText(column, ['label']) ?? key,
      required: column.required === true,
      configuredBy,
      resolvedName,
      resolvedBy: configuredBy
        ? configuredValue
          ? 'mapping'
          : defaultValue
            ? 'default'
            : 'unset'
        : 'field',
    }]
  })
}
