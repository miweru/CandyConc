/**
 * Run Export Service
 *
 * Lokaler Evidenz- und Zitations-Export für RunRecords: JSON-Pakete
 * (mit Payload-Redaktion) als Datei-Download sowie BibTeX-Einträge.
 * Es gibt keinen Sharing- oder Kollaborationskanal — Exporte verlassen
 * die Anwendung ausschließlich als lokale Dateien.
 */

import type { RunRecordV1 } from '@/types/copilot-protocol'
import { getRunRecord } from './runRecordService'
import { downloadText } from '@/utils/download'
import { t } from '@/i18n'
import { formatNumber } from '@/i18n/format'

// ============================================================================
// Types
// ============================================================================

export interface RunExportPackage {
  version: string
  type: 'run' | 'runs'
  createdAt: number
  createdBy?: string

  // Metadata
  title: string
  description?: string
  tags?: string[]

  // Content (one of these will be set)
  run?: RunRecordV1
  runs?: RunRecordV1[]
}

// ============================================================================
// Redaction
// ============================================================================

const REDACTED_ACTION_PAYLOAD = Object.freeze({
  redacted: true,
  reason: 'run_export_default',
})

/**
 * Exportierte Dateien können den lokalen Rechner verlassen, deshalb werden
 * Aktions-Payloads und Trace-Historien standardmäßig auf eine
 * Metadaten-Kopie reduziert.
 */
function redactForExport<T>(value: T, keyHint?: string): T {
  if (keyHint === 'actionPayload' || keyHint === 'rawActionPayload') {
    return { ...REDACTED_ACTION_PAYLOAD } as T
  }

  if (keyHint === 'traces' || keyHint === 'traceHistory' || keyHint === 'rawTraces') {
    return [] as T
  }

  if (Array.isArray(value)) {
    return value.map(item => redactForExport(item)) as T
  }

  if (!value || typeof value !== 'object') {
    return value
  }

  const redacted: Record<string, unknown> = {}
  for (const [key, entry] of Object.entries(value as Record<string, unknown>)) {
    redacted[key] = redactForExport(entry, key)
  }
  return redacted as T
}

function redactExportPackage(pkg: RunExportPackage): RunExportPackage {
  return redactForExport(pkg)
}

// ============================================================================
// Package Creation
// ============================================================================

/**
 * Export-Paket für einen einzelnen Run erstellen (Payload redigiert).
 */
export function createRunPackage(
  runId: string,
  options: { title?: string; description?: string } = {}
): RunExportPackage | null {
  const run = getRunRecord(runId)
  if (!run) return null

  return redactExportPackage({
    version: '1.0',
    type: 'run',
    createdAt: Date.now(),
    title: options.title ?? run.summary,
    description: options.description,
    run,
  })
}

/**
 * Export-Paket für mehrere Runs erstellen (Payloads redigiert).
 */
export function createRunsPackage(
  runIds: string[],
  options: { title?: string; description?: string; tags?: string[] } = {}
): RunExportPackage | null {
  const runs = runIds
    .map(id => getRunRecord(id))
    .filter((r): r is RunRecordV1 => r !== undefined)

  if (runs.length === 0) return null

  return redactExportPackage({
    version: '1.0',
    type: 'runs',
    createdAt: Date.now(),
    title: options.title ?? t('workspace.runExport.runsTitle', { count: formatNumber(runs.length) }, runs.length),
    description: options.description,
    tags: options.tags,
    runs,
  })
}

// ============================================================================
// Export Formats
// ============================================================================

/**
 * Paket als JSON serialisieren (Redaktion wird erneut angewendet).
 */
export function exportPackageAsJson(pkg: RunExportPackage, pretty = true): string {
  const redacted = redactExportPackage(pkg)
  return pretty ? JSON.stringify(redacted, null, 2) : JSON.stringify(redacted)
}

/**
 * Paket als JSON-Datei herunterladen.
 */
export function downloadPackageAsJson(pkg: RunExportPackage, filename?: string): void {
  const safeName = pkg.title.replace(/[^a-z0-9äöüß]/gi, '_').toLowerCase()
  const defaultFilename = `candyconc_${pkg.type}_${safeName}_${new Date().toISOString().slice(0, 10)}.json`
  downloadText(exportPackageAsJson(pkg), filename ?? defaultFilename, 'application/json')
}

// ============================================================================
// BibTeX Export (for academic citation)
// ============================================================================

/**
 * Run als BibTeX-Eintrag für Zitationszwecke exportieren.
 * Enthält die echten Scope-/Evidenz-Hashes des RunRecords.
 */
export function exportRunAsBibTeX(run: RunRecordV1): string {
  const date = new Date(run.ts)
  const year = date.getFullYear()
  const month = String(date.getMonth() + 1).padStart(2, '0')
  const day = String(date.getDate()).padStart(2, '0')

  const key = `candyconc_${run.runId.replace(/[^a-z0-9]/gi, '_')}`
  const scope = run.evidence?.researchScope
  const scopeHash = scope?.scopeHash ?? run.evidence?.corpusFingerprint.subcorpusHash ?? run.corpus.subcorpusHash
  const scopeStatus = scope?.scopeStatus ?? 'unknown'
  const metadataSchemaHash = scope?.metadataSchemaHash ?? run.evidence?.corpusFingerprint.metadataSchemaHash ?? 'unknown'

  return `@misc{${key},
  title = {${run.summary}},
  howpublished = {CandyConc Corpus Analysis},
  year = {${year}},
  month = {${month}},
  day = {${day}},
  note = {Run ID: ${run.runId}, Action: ${run.actionType}, Corpus: ${run.corpus.corpusId}, ScopeHash: ${scopeHash}, ScopeStatus: ${scopeStatus}, MetadataSchemaHash: ${metadataSchemaHash}. Full reproducibility metadata is in the CandyConc run JSON export.}
}`
}
