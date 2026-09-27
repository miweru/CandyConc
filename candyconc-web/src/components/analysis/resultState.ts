import { formatNumber } from '@/i18n/format'
import { t } from '@/i18n'
export interface AnalysisCompletenessState {
  rowLimit?: number | null
  totalCandidates?: number | null
  loadedRows?: number | null
  availableRows?: number | null
  truncated?: boolean
}

function finiteNonNegative(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0
    ? value
    : null
}

export function completenessStateFromJobRows(
  response: {
    rows?: unknown[]
    total_rows?: number | null
    row_limit?: number | null
    total_candidates?: number | null
    truncated?: boolean
  },
  options: { loadedRows?: number | null; fallbackRowLimit?: number | null } = {},
): AnalysisCompletenessState {
  const rowsReturned = Array.isArray(response.rows) ? response.rows.length : 0
  const availableRows = finiteNonNegative(response.total_rows) ?? rowsReturned
  const loadedRows = finiteNonNegative(options.loadedRows) ?? rowsReturned
  const rowLimit = finiteNonNegative(response.row_limit) ?? finiteNonNegative(options.fallbackRowLimit)
  const totalCandidates = finiteNonNegative(response.total_candidates) ?? availableRows
  const truncated = response.truncated === true || totalCandidates > Math.max(availableRows, loadedRows)
  return {
    rowLimit,
    totalCandidates,
    loadedRows,
    availableRows,
    truncated,
  }
}

export function analysisCompletenessHeaderLines(
  state: AnalysisCompletenessState | null,
  prefix = 'Result',
): string[] {
  if (!state) return []
  const lines: string[] = []
  if (typeof state.truncated === 'boolean') lines.push(`# ${prefix}.truncated: ${state.truncated}`)
  if (typeof state.rowLimit === 'number') lines.push(`# ${prefix}.row_limit: ${state.rowLimit}`)
  if (typeof state.totalCandidates === 'number') lines.push(`# ${prefix}.total_candidates: ${state.totalCandidates}`)
  if (typeof state.availableRows === 'number') lines.push(`# ${prefix}.available_rows: ${state.availableRows}`)
  if (typeof state.loadedRows === 'number') lines.push(`# ${prefix}.loaded_rows: ${state.loadedRows}`)
  return lines
}

export function analysisCompletenessNotice(
  state: AnalysisCompletenessState | null,
  label = t('analysis.resultState.resultList'),
): string | null {
  if (!state?.truncated) return null
  const visible = state.loadedRows ?? state.availableRows ?? state.rowLimit ?? null
  const total = state.totalCandidates ?? null
  if (typeof visible === 'number' && visible > 0 && typeof total === 'number' && total > 0) {
    return t('analysis.resultState.cappedTopOf', { label, visible: formatNumber(visible), total: formatNumber(total) })
  }
  if (typeof visible === 'number' && visible > 0) {
    return t('analysis.resultState.cappedTop', { label, visible: formatNumber(visible) })
  }
  return t('analysis.resultState.cappedMore', { label })
}
