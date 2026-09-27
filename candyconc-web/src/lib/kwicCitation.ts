import { formatNumber } from '@/i18n/format'
import { t } from '@/i18n'
/**
 * kwicCitation — pure formatting helpers for copying / citing KWIC concordance
 * lines.
 *
 * These functions are deliberately free of Vue/DOM dependencies so the exact
 * formatting (notably whitespace preservation) can be unit-tested in isolation.
 *
 * The raw `left`/`right` context strings coming from the backend may carry
 * leading/trailing ellipsis markers ("..." or "…") that denote clipped context.
 * Those markers are a *display* affordance — they must be stripped from copied
 * text — but interior whitespace inside each segment is load-bearing (it is the
 * tokenisation the linguist is citing) and is preserved verbatim.
 */

export interface KwicCitationRow {
  position?: number
  left: string
  match: string
  right: string
  docId?: string | null
  docTitle?: string | null
  metadata?: Record<string, string> | null
  /** Offsets of the other hit tokens relative to the node (`match`). */
  matchOffsets?: number[]
}

/**
 * Server-Provenienz einer KWIC-Zufallsstichprobe (Spiegel des
 * `X-CandyConc-Sample`-Headers bzw. `done.sample`); nur strukturell hier
 * dupliziert, damit dieses Modul frei von API-Client-Abhängigkeiten bleibt.
 */
export interface KwicSampleCitation {
  requested: number
  drawn: number
  seed: number
  population: number
  populationPartial: boolean
}

/**
 * Format the sample provenance as one line in the interface language, e.g.
 * `Zufallsstichprobe: 200 von 9740 Treffern · Seed 42`. Reproducibility is the
 * point of the feature, so the seed is always part of the citation. Appends an
 * honesty marker when the population itself was only partially enumerable.
 */
export function formatSampleProvenance(sample: KwicSampleCitation): string {
  const drawn = formatNumber(sample.drawn)
  const population = formatNumber(sample.population)
  const partial = sample.populationPartial ? t('kwic.citation.populationPartial') : ''
  return t('kwic.citation.sample', { drawn, population, partial, seed: sample.seed })
}

const LEADING_ELLIPSIS = /^(?:\.\.\.|…)/
const TRAILING_ELLIPSIS = /(?:\.\.\.|…)$/

/**
 * Strip a leading ellipsis marker from a left-context string while preserving
 * every other character, including interior and remaining edge whitespace that
 * is part of the citation.
 */
export function stripLeftEllipsis(text: string): string {
  if (!text) return ''
  // Drop an ellipsis marker and only the whitespace immediately attached to it.
  return text.replace(/^\s*(?:\.\.\.|…)\s?/, (match) =>
    LEADING_ELLIPSIS.test(match.trimStart()) ? '' : match
  )
}

/**
 * Strip a trailing ellipsis marker from a right-context string while preserving
 * every other character.
 */
export function stripRightEllipsis(text: string): string {
  if (!text) return ''
  return text.replace(/\s?(?:\.\.\.|…)\s*$/, (match) =>
    TRAILING_ELLIPSIS.test(match.trimEnd()) ? '' : match
  )
}

/**
 * Format a single KWIC line as plain text: `left | node | right`.
 *
 * Whitespace inside each of the three segments is preserved exactly as the
 * backend delivered it; only display ellipsis markers and a single space hugging
 * the separator are normalised so the line reads cleanly when pasted.
 */
export function formatKwicLine(row: KwicCitationRow): string {
  const left = stripLeftEllipsis(row.left ?? '')
  const match = row.match ?? ''
  const right = stripRightEllipsis(row.right ?? '')
  return `${left} | ${match} | ${right}`
}

/**
 * Build a compact, human-readable citation suffix from the metadata already
 * present on the row (source, doc id, corpus position). Returns an empty string
 * when no citable fields are available.
 */
export function formatCitationSuffix(row: KwicCitationRow): string {
  const parts: string[] = []
  const source = row.metadata?.source
  if (source) parts.push(source)

  const docLabel = row.docTitle || row.docId
  if (docLabel) parts.push(`doc ${docLabel}`)

  if (typeof row.position === 'number' && Number.isFinite(row.position)) {
    parts.push(`pos ${row.position}`)
  }

  return parts.join(', ')
}

/**
 * Format a KWIC line with an appended citation, e.g.
 * `left | node | right  [reddit, doc 42, pos 1337]`.
 *
 * Falls back to the plain line when no metadata is citable.
 */
export function formatKwicLineWithCitation(row: KwicCitationRow): string {
  const line = formatKwicLine(row)
  const suffix = formatCitationSuffix(row)
  return suffix ? `${line}  [${suffix}]` : line
}

/** The whole hit of a concordance line, as in the server exports. */
export interface KwicHitSpan {
  /** All tokens of the hit, separated by single spaces. */
  match: string
  /** Corpus position of the first token of the hit. */
  matchStart: number | null
  /** Corpus position of the last token of the hit. */
  matchEnd: number | null
}

const OUTSIDE_CONTEXT = '…'

function contextTokens(text: string): string[] {
  return text.split(/\s+/).filter((token) => token.length > 0)
}

/**
 * The whole hit of a loaded concordance line: the fields `match`,
 * `match_start` and `match_end` of the server exports.
 *
 * A line sits at its node token (`position`, `match`) and lists the other
 * tokens of the hit as `matchOffsets` relative to it. The hit runs from the
 * lowest to the highest offset, like in the server export. Its word forms
 * come from the loaded context, split at whitespace as the server splits it.
 * Hit tokens outside the loaded context are written as one `…` per side.
 */
export function kwicHitSpan(row: KwicCitationRow): KwicHitSpan {
  const offsets = (row.matchOffsets ?? []).filter((offset) => Number.isInteger(offset))
  const low = Math.min(0, ...offsets)
  const high = Math.max(0, ...offsets)
  const node = row.match ?? ''
  const position = typeof row.position === 'number' && Number.isFinite(row.position) ? row.position : null
  const matchStart = position === null ? null : position + low
  const matchEnd = position === null ? null : position + high
  if (low === 0 && high === 0) return { match: node, matchStart, matchEnd }
  const left = contextTokens(stripLeftEllipsis(row.left ?? ''))
  const right = contextTokens(stripRightEllipsis(row.right ?? ''))
  const before = left.slice(Math.max(0, left.length + low))
  const after = right.slice(0, high)
  const parts = [
    ...(before.length < -low ? [OUTSIDE_CONTEXT] : []),
    ...before,
    node,
    ...after,
    ...(after.length < high ? [OUTSIDE_CONTEXT] : []),
  ]
  return { match: parts.join(' '), matchStart, matchEnd }
}

// match, match_start and match_end are appended like in the server exports,
// so that the earlier columns keep their place.
const TSV_HEADER = ['position', 'left', 'node', 'right', 'source', 'doc', 'match', 'match_start', 'match_end'] as const

/**
 * Escape a single field for tab-separated output: tabs, newlines and carriage
 * returns are collapsed to spaces so each row stays on one physical line.
 * Interior (non-tab) whitespace is preserved.
 */
export function escapeTsvField(value: string): string {
  return value.replace(/[\t\r\n]+/g, ' ')
}

/**
 * Render the loaded result window as a TSV table (header + one row per hit).
 * Left/right context have their display ellipsis markers stripped; all other
 * whitespace is preserved (tabs/newlines collapsed to keep the grid intact).
 *
 * When the rows are a drawn random sample, pass `options.sample`: the TSV then
 * starts with a `# `-comment line carrying the full provenance (drawn size,
 * population, seed), so pasted/exported tables stay citable as a sample.
 */
export function formatKwicTsv(
  rows: KwicCitationRow[],
  options?: { sample?: KwicSampleCitation | null },
): string {
  const lines: string[] = []
  if (options?.sample) lines.push(`# ${formatSampleProvenance(options.sample)}`)
  lines.push(TSV_HEADER.join('\t'))
  for (const row of rows) {
    const span = kwicHitSpan(row)
    const fields = [
      typeof row.position === 'number' && Number.isFinite(row.position)
        ? String(row.position)
        : '',
      escapeTsvField(stripLeftEllipsis(row.left ?? '')),
      escapeTsvField(row.match ?? ''),
      escapeTsvField(stripRightEllipsis(row.right ?? '')),
      escapeTsvField(row.metadata?.source ?? ''),
      escapeTsvField(String(row.docTitle || row.docId || '')),
      escapeTsvField(span.match),
      span.matchStart === null ? '' : String(span.matchStart),
      span.matchEnd === null ? '' : String(span.matchEnd),
    ]
    lines.push(fields.join('\t'))
  }
  return lines.join('\n')
}

/**
 * Copy text to the clipboard with a graceful fallback for environments where
 * the async Clipboard API is unavailable (insecure contexts, older browsers).
 * Resolves to `true` on success, `false` otherwise. Never throws.
 */
export async function copyTextToClipboard(text: string): Promise<boolean> {
  try {
    if (
      typeof navigator !== 'undefined' &&
      navigator.clipboard &&
      typeof navigator.clipboard.writeText === 'function'
    ) {
      await navigator.clipboard.writeText(text)
      return true
    }
  } catch {
    // Fall through to the legacy path below.
  }

  try {
    if (typeof document === 'undefined') return false
    const textarea = document.createElement('textarea')
    textarea.value = text
    textarea.setAttribute('readonly', '')
    textarea.style.position = 'absolute'
    textarea.style.left = '-9999px'
    document.body.appendChild(textarea)
    textarea.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(textarea)
    return ok
  } catch {
    return false
  }
}
