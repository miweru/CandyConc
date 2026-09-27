/**
 * Pure n-gram analysis helpers (extracted from NgramsTab.vue for testability).
 *
 * Backend contract (app/src/candyconc/services/backend/routes/analysis.py):
 * - POST /analysis/ngrams/job        → rows: { ngram, freq, n }
 * - POST /analysis/ngrams_diff/job   → rows: { ngram, n, target_freq, reference_freq,
 *                                       target_per_million, reference_per_million,
 *                                       diff_per_million, diff_abs }
 * - max_n is capped server-side via CANDYCONC_ANALYSIS_NGRAM_MAX_N (default 5).
 */

import { buildCsv } from '@/utils/csv'
import { formatNumber } from '@/i18n/format'
import { t } from '@/i18n'
import { methodStatEntries, type MethodBlock } from '@/api/client'

/** Product UI choices matching the backend's release default max_n=5. */
export const NGRAM_SIZES = [2, 3, 4, 5] as const

export interface NgramRow {
  ngram: string
  frequency: number
  relative: number
}

export interface NgramDiffRow {
  ngram: string
  targetFreq: number
  referenceFreq: number
  targetPerMillion: number
  referencePerMillion: number
  diffPerMillion: number
  diffAbs: number
}

export interface NgramResultState {
  truncated?: boolean
  rowLimit?: number | null
  totalCandidates?: number | null
  loadedRows?: number | null
}

export interface NgramResultSummaryOptions {
  displayedRows?: number | null
  minFreq?: number | null
  mode?: 'frequency' | 'diff'
}

function asNumber(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

/**
 * Map raw `/analysis/jobs/{id}/rows` rows of an `ngrams` job into table rows.
 * Applies the min-frequency filter and computes the relative frequency
 * against the server-reported target total when present.
 */
export function mapNgramFrequencyRows(
  rows: Array<Record<string, unknown>>,
  options: { minFreq: number; tokenCount: number; targetTotal?: number | null }
): NgramRow[] {
  const mapped = rows
    .map((row) => ({
      ngram: String(row.ngram ?? '').trim(),
      frequency: asNumber(row.freq),
      relative: 0,
    }))
    .filter((row) => row.ngram && row.frequency >= options.minFreq)
  // Prefer the server-reported scope total; else the scope/corpus token count.
  // REFUSE to silently divide by the sum of the displayed freqs — that
  // denominator is not the scope size and inflates per-million ~15x
  // (NGRAMS-METASUBCORPUS-PERMILLION). With no real denominator we emit NaN so
  // the UI renders '—' rather than a wrong number.
  const tokenCount = typeof options.targetTotal === 'number' && options.targetTotal > 0
    ? options.targetTotal
    : options.tokenCount > 0
      ? options.tokenCount
      : 0
  if (tokenCount <= 0) {
    return mapped.map((row) => ({ ...row, relative: Number.NaN }))
  }
  return mapped.map((row) => ({ ...row, relative: row.frequency / tokenCount }))
}

/**
 * Map raw `/analysis/jobs/{id}/rows` rows of an `ngrams_diff` job into table rows.
 * Keeps rows where target OR reference frequency reaches `minFreq`
 * (same semantics as the keyness contrast dashboard).
 */
export function mapNgramDiffRows(
  rows: Array<Record<string, unknown>>,
  options: { minFreq: number; limit: number }
): NgramDiffRow[] {
  return rows
    .map((row) => {
      const diffPerMillion = asNumber(row.diff_per_million)
      const diffAbsRaw = asNumber(row.diff_abs)
      return {
        ngram: String(row.ngram ?? '').trim(),
        targetFreq: asNumber(row.target_freq),
        referenceFreq: asNumber(row.reference_freq),
        targetPerMillion: asNumber(row.target_per_million),
        referencePerMillion: asNumber(row.reference_per_million),
        diffPerMillion,
        diffAbs: diffAbsRaw > 0 ? diffAbsRaw : Math.abs(diffPerMillion),
      }
    })
    .filter(
      (row) =>
        row.ngram && (row.targetFreq >= options.minFreq || row.referenceFreq >= options.minFreq)
    )
    .sort((a, b) => b.diffAbs - a.diffAbs)
    .slice(0, options.limit)
}

export function sortNgramRows(rows: NgramRow[], sortBy: 'frequency' | 'relative'): NgramRow[] {
  // `relative` may be NaN when no scope denominator was available; fall back to
  // frequency order there so NaN rows don't scramble the table (NaN comparisons
  // are always false).
  return [...rows].sort((a, b) => {
    if (sortBy === 'relative' && Number.isFinite(a.relative) && Number.isFinite(b.relative)) {
      return b.relative - a.relative
    }
    return b.frequency - a.frequency
  })
}

/** Relative frequency → occurrences per million tokens. */
export function perMillion(relative: number): number {
  return relative * 1_000_000
}

/**
 * Render a per-million value for display. A NaN `relative` means no valid scope
 * denominator was available (see mapNgramFrequencyRows) — render '—' rather than
 * a wrong number. `digits` defaults to 2 (table); pass 4 for CSV provenance.
 */
export function formatPerMillion(relative: number, digits = 2): string {
  if (!Number.isFinite(relative)) return '—'
  return perMillion(relative).toFixed(digits)
}


export function buildNgramResultStateHeader(state: NgramResultState | null): string[] {
  if (!state) return []
  const lines: string[] = []
  if (typeof state.truncated === 'boolean') {
    lines.push(`# Result.truncated: ${state.truncated}`)
  }
  if (typeof state.rowLimit === 'number') {
    lines.push(`# Result.row_limit: ${state.rowLimit}`)
  }
  if (typeof state.totalCandidates === 'number') {
    lines.push(`# Result.total_candidates: ${state.totalCandidates}`)
  }
  if (typeof state.loadedRows === 'number') {
    lines.push(`# Result.loaded_rows: ${state.loadedRows}`)
  }
  return lines
}

export function buildNgramResultStateNotice(state: NgramResultState | null): string | null {
  if (!state?.truncated) return null
  const visible = state.rowLimit ?? state.loadedRows ?? null
  const total = state.totalCandidates ?? null
  if (typeof visible === 'number' && visible > 0 && typeof total === 'number' && total > 0) {
    return t('analysis.ngramResult.cappedOf', { visible: formatNumber(visible), total: formatNumber(total) })
  }
  if (typeof visible === 'number' && visible > 0) {
    return t('analysis.ngramResult.capped', { visible: formatNumber(visible) })
  }
  return t('analysis.ngramResult.cappedMore')
}

function formatCount(value: number): string {
  return formatNumber(value)
}

export function buildNgramResultStateSummary(
  state: NgramResultState | null,
  options: NgramResultSummaryOptions = {}
): string | null {
  if (!state) return null
  const displayedRows = typeof options.displayedRows === 'number'
    ? Math.max(0, options.displayedRows)
    : null
  const loadedRows = typeof state.loadedRows === 'number' ? Math.max(0, state.loadedRows) : null
  const totalCandidates = typeof state.totalCandidates === 'number'
    ? Math.max(0, state.totalCandidates)
    : null
  const rowLimit = typeof state.rowLimit === 'number' ? Math.max(0, state.rowLimit) : null
  const rowLabel = options.mode === 'diff' ? t('analysis.ngramResult.contrastRows') : t('analysis.ngramResult.ngrams')
  const displayPart = displayedRows !== null
    ? t('analysis.ngramResult.displayed', { count: formatCount(displayedRows), rows: rowLabel })
    : t('analysis.ngramResult.resultList')
  const minFreqPart = typeof options.minFreq === 'number'
    ? ` ${t('analysis.ngramResult.afterMinFreq', { min: formatCount(options.minFreq) })}`
    : ''
  const backendParts = [
    loadedRows !== null ? t('analysis.ngramResult.loadedCandidates', { count: formatCount(loadedRows) }) : null,
    totalCandidates !== null ? t('analysis.ngramResult.totalCandidates', { count: formatCount(totalCandidates) }) : null,
    rowLimit !== null ? t('analysis.ngramResult.rowLimit', { limit: formatCount(rowLimit) }) : null,
  ].filter((part): part is string => Boolean(part))
  const separator = t('analysis.ngramResult.separator')
  const backendPart = backendParts.length ? `${separator}${backendParts.join(' · ')}` : ''
  const truncationPart = separator + (state.truncated
    ? t('analysis.ngramResult.serverCapped')
    : t('analysis.ngramResult.serverNotCapped'))
  return `${displayPart}${minFreqPart}${backendPart}${truncationPart}.`
}

/** CSV formula lines when the backend supplied no method block. */
export const NGRAM_FORMULA_FALLBACK: Record<'frequency' | 'diff', readonly string[]> = {
  frequency: [
    '# Formulae:',
    '# per_million = frequency * 1e6 / tokenCount',
  ],
  // The contrast divides by the n-gram positions of each side and order:
  // a document of L tokens has L - n + 1 positions for n-grams of order n.
  diff: [
    '# Formulae:',
    '# per_million = freq * 1e6 / n-gram positions of the subcorpus, the sum of (tokens - n + 1) over its documents (server-side)',
    '# diff_per_million = target_per_million - reference_per_million',
  ],
}

function positionLines(label: string, value: unknown): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return []
  const parts = Object.entries(value as Record<string, unknown>)
    .filter(([, count]) => typeof count === 'number')
    .map(([order, count]) => `${order}=${count}`)
  return parts.length ? [`# ${label}: ${parts.join(' ')}`] : []
}

/**
 * CSV provenance lines of an n-gram export. The server `method` block is the
 * source when present, including the rate basis of the contrast. Without it
 * the export states the formula of the chosen mode.
 */
export function buildNgramFormulaLines(
  method: MethodBlock | null | undefined,
  mode: 'frequency' | 'diff',
): string[] {
  if (!method) return [...NGRAM_FORMULA_FALLBACK[mode]]
  const lines: string[] = [`# ${t('analysis.ngrams.csvMethodHeader')}`]
  for (const stat of methodStatEntries(method)) {
    const name = typeof stat?.name === 'string' && stat.name ? stat.name : stat.key
    const formula = typeof stat?.latex_formula === 'string' ? ` = ${stat.latex_formula}` : ''
    lines.push(`# ${name}${formula}`)
  }
  if (mode === 'diff') {
    if (typeof method.rate_basis === 'string') lines.push(`# rate_basis: ${method.rate_basis}`)
    lines.push(...positionLines('ngram_positions_target', method.ngram_positions_target))
    lines.push(...positionLines('ngram_positions_reference', method.ngram_positions_reference))
  }
  if (typeof method.window === 'number') lines.push(`# window: ${method.window}`)
  const fp = method.indexFingerprint ?? method.index_fingerprint
  if (fp) lines.push(`# indexFingerprint: ${fp}`)
  return lines
}

/** Assemble a CSV string from comment header lines, a column row, and data rows. */
export function buildNgramCsv(
  headerLines: string[],
  columns: string[],
  rows: Array<Array<string | number>>
): string {
  // Delegate to the hardened shared CSV builder (formula-injection + column
  // corruption guards). Comment header lines are author-controlled provenance.
  return buildCsv({ meta: headerLines, headers: columns, rows })
}
