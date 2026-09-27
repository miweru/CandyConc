/**
 * Token boundaries of KWIC rows that show the original spacing.
 *
 * When a corpus index has `whitespace_after.bin`, the server joins the tokens
 * of `left`, `kw` and `right` as they were written ("soul. No" instead of
 * "soul . No"). Row offsets (`match_offsets`, `collocate_offsets`) still count
 * tokens, so a split at whitespace no longer finds them: "soul." is two
 * tokens. Such rows carry `token_starts`, the start of every token in each
 * field, counted in Unicode code points. Rows without it keep the legacy
 * form, where every token is followed by one space.
 */

export interface TokenStarts {
  left: number[]
  kw: number[]
  right: number[]
}

export interface TextSpan {
  start: number
  end: number
}

/** Spacing fields of a KWIC row as the server sends them. */
export interface RawSpacingFields {
  token_starts?: unknown
  ws_before_kw?: unknown
  ws_after_kw?: unknown
}

/** Spacing fields of a KWIC row in the store. */
export interface RowSpacing {
  tokenStarts?: TokenStarts
  wsBeforeKw?: boolean
  wsAfterKw?: boolean
}

function numberList(value: unknown): number[] | null {
  if (!Array.isArray(value)) return null
  const out: number[] = []
  for (const item of value) {
    const n = Number(item)
    if (!Number.isInteger(n) || n < 0) return null
    out.push(n)
  }
  return out
}

/** `token_starts` of a server row, or undefined when absent or malformed. */
export function readTokenStarts(value: unknown): TokenStarts | undefined {
  if (!value || typeof value !== 'object') return undefined
  const record = value as Record<string, unknown>
  const left = numberList(record.left)
  const kw = numberList(record.kw)
  const right = numberList(record.right)
  if (!left || !kw || !right) return undefined
  return { left, kw, right }
}

/** The spacing fields of a server row, to spread into a store row. */
export function readRowSpacing(row: RawSpacingFields): RowSpacing {
  const tokenStarts = readTokenStarts(row.token_starts)
  if (!tokenStarts) return {}
  return {
    tokenStarts,
    wsBeforeKw: row.ws_before_kw === true,
    wsAfterKw: row.ws_after_kw === true,
  }
}

/** Server-side spacing fields of a hit, carried over unchanged. */
export function rawSpacing(row: RawSpacingFields): { token_starts?: TokenStarts; ws_before_kw?: boolean; ws_after_kw?: boolean } {
  const tokenStarts = readTokenStarts(row.token_starts)
  if (!tokenStarts) return {}
  return {
    token_starts: tokenStarts,
    ws_before_kw: row.ws_before_kw === true,
    ws_after_kw: row.ws_after_kw === true,
  }
}

/** Code point offsets of `text` converted to string (UTF-16) indices. */
function toStringIndices(text: string, offsets: number[]): number[] {
  if (!/[\uD800-\uDFFF]/.test(text)) return offsets
  const map: number[] = []
  let index = 0
  for (const ch of text) {
    map.push(index)
    index += ch.length
  }
  map.push(index)
  return offsets.map((offset) => map[Math.min(offset, map.length - 1)]!)
}

/**
 * The span of every token of `text` from its start offsets.
 *
 * A token ends where the next one starts, without the one space that may
 * separate them. Line break tokens keep their span, so the n-th span is the
 * n-th token exactly as the server counts it. Returns null when the offsets
 * do not fit the text.
 */
export function spansFromTokenStarts(text: string, starts: number[] | undefined): TextSpan[] | null {
  if (!starts) return null
  if (!text) return starts.length === 0 ? [] : null
  if (!starts.length || starts[0] !== 0) return null
  const indices = toStringIndices(text, starts)
  const spans: TextSpan[] = []
  for (let i = 0; i < indices.length; i += 1) {
    const start = indices[i]!
    let end = i + 1 < indices.length ? indices[i + 1]! : text.length
    if (end < start || end > text.length) return null
    if (end > start && text[end - 1] === ' ') end -= 1
    spans.push({ start, end })
  }
  return spans
}
