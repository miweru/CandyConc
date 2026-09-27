/**
 * Hardened CSV helpers — single source of truth for CSV serialization.
 *
 * Two distinct attack/corruption classes are handled here:
 *
 * 1. **Formula injection** (CSV/spreadsheet injection): a cell whose first
 *    character is one of `= + - @` (or a leading TAB/CR that a spreadsheet
 *    strips before re-evaluating the next char) is treated by Excel / Google
 *    Sheets / LibreOffice as a formula. A corpus token like `=cmd|...` or
 *    `-2+3` would then execute or be silently mutated. We neutralise this by
 *    prefixing such cells with a single quote `'`, the OWASP-recommended guard.
 *
 * 2. **Column corruption**: a cell containing `,`/`"`/newline/CR/TAB breaks the
 *    row structure unless quote-wrapped (with `"` doubled). German corpus text
 *    routinely contains commas, so the previous raw `${a},${b}` templates
 *    silently shifted every column after the first comma.
 *
 * `buildCsv` / `downloadCsv` compose these into a complete, comment-header
 * aware document. Comment/meta lines (starting with `#`) are passed through
 * verbatim — they are author-controlled provenance, never user data.
 */

import { downloadText } from './download'

export type CsvCell = string | number | boolean | null | undefined

/** Characters that make a spreadsheet interpret a leading cell as a formula. */
const FORMULA_LEAD = /^[=+\-@\t\r]/

/** Characters that require the whole cell to be quote-wrapped. */
const NEEDS_QUOTING = /[",\n\r\t]/

/**
 * Escape a single CSV cell defensively.
 *
 * - Coerces `null`/`undefined` to an empty string and numbers/booleans to text.
 * - Prefixes a `'` when the value would otherwise be parsed as a formula.
 * - Quote-wraps (and doubles inner quotes) when the value contains a
 *   structural character (`,`, `"`, newline, CR, TAB).
 */
export function csvEscape(value: CsvCell): string {
  const raw = value === null || value === undefined ? '' : String(value)
  // Neutralise spreadsheet formula injection. We guard the raw string before
  // any quoting so the leading char is what a spreadsheet actually sees.
  const guarded = FORMULA_LEAD.test(raw) ? `'${raw}` : raw
  if (NEEDS_QUOTING.test(guarded)) {
    return `"${guarded.replace(/"/g, '""')}"`
  }
  return guarded
}

/** Join one row of already-typed cells into an escaped CSV line. */
export function csvRow(cells: CsvCell[]): string {
  return cells.map(csvEscape).join(',')
}

/**
 * Build a single comment/meta line (`# label: value`) with the DYNAMIC `value`
 * sanitised so untrusted content (e.g. a user search term) cannot break out of
 * the comment line.
 *
 * Two corruption classes are neutralised on the value:
 *  - **Newline / CR injection**: a `\n` or `\r` in the value would otherwise
 *    terminate the comment and inject arbitrary CSV rows. We collapse all line
 *    breaks (including the line/paragraph separators U+2028/U+2029) to a single
 *    space so the meta line stays one physical line.
 *  - **Formula injection**: a spreadsheet ignores a leading `#`, so the FIRST
 *    real character of the value can still be re-interpreted as a formula
 *    (`=`, `+`, `-`, `@`, or a leading TAB). We prefix a `'` guard in that case,
 *    matching {@link csvEscape}'s OWASP-recommended neutralisation.
 *
 * The `label` is author-controlled provenance and emitted verbatim.
 */
export function csvMeta(label: string, value: CsvCell): string {
  const raw = value === null || value === undefined ? '' : String(value)
  // Collapse every newline variant to a space so the comment cannot span rows.
  const singleLine = raw.replace(/[\r\n\u2028\u2029]+/g, ' ')
  // Guard a leading formula trigger (also strip a leading TAB that a sheet eats).
  const guarded = FORMULA_LEAD.test(singleLine) ? `'${singleLine}` : singleLine
  return `# ${label}: ${guarded}`
}

export interface BuildCsvOptions {
  /** Verbatim comment/meta lines emitted before the header (e.g. `# Corpus: …`). */
  meta?: string[]
  /** Column headers; escaped like any other cell. */
  headers: string[]
  /** Data rows. */
  rows: CsvCell[][]
}

/**
 * Assemble a complete CSV document: optional verbatim meta lines, then an
 * escaped header row, then escaped data rows.
 */
export function buildCsv(options: BuildCsvOptions): string {
  const { meta = [], headers, rows } = options
  const lines: string[] = [...meta, csvRow(headers)]
  for (const row of rows) {
    lines.push(csvRow(row))
  }
  return lines.join('\n')
}

/**
 * Trigger a browser download of CSV content as a Blob.
 * Delegates to the canonical download helper (no-op without DOM).
 */
export function downloadCsv(content: string, filename: string): void {
  downloadText(content, filename, 'text/csv;charset=utf-8;')
}
