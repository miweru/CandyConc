import type { AnalysisJobRows, AnalysisJobSnapshot } from '@/api/client'
import { t } from '@/i18n'

interface AnalysisRowsReadiness {
  readiness: string | null
  warnings: string[]
  rowsState: string
  rowsLoadable: boolean
  blockReason: string | null
}

type SnapshotRecord = Record<string, unknown>

export function compactStringList(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value
    .map((item) => String(item || '').trim())
    .filter(Boolean)
}

function asRecord(value: unknown): SnapshotRecord | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as SnapshotRecord
    : null
}

function lower(value: unknown): string {
  return String(value || '').trim().toLowerCase()
}

function analysisRowsState(snapshot: SnapshotRecord | null): string {
  const rowsState = lower(snapshot?.rows_state)
  if (rowsState) return rowsState
  const readiness = lower(snapshot?.result_readiness)
  if (readiness === 'unavailable') return 'not_stored'
  if (readiness) return readiness
  if (snapshot?.result_discarded === true) return 'discarded'
  return ''
}

export function analysisJobRowsReadiness(
  value: unknown,
  options: {
    rowsEnabled?: boolean
    disabledReason?: string | null
  } = {},
): AnalysisRowsReadiness {
  const snapshot = asRecord(value)
  const rowsState = analysisRowsState(snapshot)
  const status = lower(snapshot?.status)
  const resultAvailable = snapshot?.result_available
  const resultDiscarded = snapshot?.result_discarded === true
  const explicitWarnings = compactStringList(snapshot?.result_warnings)
  const rowsEnabled = options.rowsEnabled ?? true

  let readiness: string | null = null
  if (rowsState === 'discarded' || resultDiscarded) readiness = t('capabilities.readiness.discarded')
  else if (rowsState === 'not_stored') readiness = t('capabilities.readiness.noRows')
  else if (status === 'done' && resultAvailable === false) readiness = t('capabilities.readiness.noRows')

  let blockReason: string | null = null
  if (!rowsEnabled) {
    blockReason = options.disabledReason ?? t('capabilities.readiness.rowsNotEnabled')
  } else if (status !== 'done') {
    blockReason = t('capabilities.readiness.notDone')
  } else if (rowsState === 'discarded' || resultDiscarded) {
    blockReason = t('capabilities.readiness.doneNotStored')
  } else if (rowsState === 'not_stored' || resultAvailable === false) {
    blockReason = t('capabilities.readiness.doneNoRows')
  }

  const warnings = explicitWarnings.length
    ? explicitWarnings
    : blockReason && rowsEnabled && status === 'done'
      ? [blockReason]
      : []

  return {
    readiness,
    warnings,
    rowsState,
    rowsLoadable: blockReason === null,
    blockReason,
  }
}

export function hasUnavailableAnalysisRows(
  snapshot: AnalysisJobSnapshot,
): boolean {
  const readiness = analysisJobRowsReadiness(snapshot)
  return snapshot.status === 'done' && !readiness.rowsLoadable
}

export function analysisRowsFromTerminalSnapshot<T>(
  snapshot: AnalysisJobSnapshot,
  offset: number,
  limit: number,
): AnalysisJobRows<T> {
  const readiness = analysisJobRowsReadiness(snapshot)
  return {
    job_id: snapshot.job_id,
    status: snapshot.status,
    progress: snapshot.progress,
    message: snapshot.message,
    total_rows: snapshot.total_rows ?? null,
    total: snapshot.total_rows ?? null,
    error: snapshot.error ?? null,
    result_available: snapshot.result_available,
    result_discarded: snapshot.result_discarded,
    result_discard_reason: snapshot.result_discard_reason,
    result_readiness: snapshot.result_readiness,
    rows_state: snapshot.rows_state,
    result_warnings: readiness.warnings,
    result_bytes: snapshot.result_bytes ?? null,
    result_max_bytes: snapshot.result_max_bytes ?? null,
    offset,
    limit,
    rows: [],
  }
}

export function analysisResultLoadedMessage(response: AnalysisJobRows): string {
  const readiness = analysisJobRowsReadiness(response)
  if (readiness.rowsState === 'discarded' || response.result_discarded) {
    return t('capabilities.readiness.loadedDiscarded')
  }
  if (readiness.rowsState === 'not_stored') {
    return t('capabilities.readiness.loadedNoRows')
  }
  return t('capabilities.readiness.loaded')
}

export function analysisResultAvailabilityLabel(snapshot: AnalysisJobSnapshot): string | null {
  if (snapshot.status !== 'done') return null
  const readiness = analysisJobRowsReadiness(snapshot)
  if (readiness.readiness) return readiness.readiness
  if (snapshot.result_available === true) return t('capabilities.readiness.available')
  return null
}
