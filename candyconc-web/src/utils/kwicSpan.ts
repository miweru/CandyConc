/**
 * Display form of a KWIC row whose match spans several tokens.
 *
 * The backend centres a row on one pivot token (`kw`) and lists the other
 * match tokens as `match_offsets` relative to it (negative = left, positive =
 * right). For display the match column should hold the whole contiguous span
 * around the pivot, so a phrase like `[word="edlen"] [word="Freiheit"]` reads
 * "edlen Freiheit" in the match column and not "edlen" with "Freiheit" in the
 * right context.
 *
 * Tokens are whitespace separated, the same split the backend uses when it
 * moves match tokens (`_apply_cql_span_to_row`). A row with the original
 * spacing of its corpus ("soul. No") carries `tokenStarts` instead, the start
 * of every token, and the tokens come from there (utils/sourceSpacing.ts).
 * Offsets that are not part of the contiguous span (a gap in a
 * variable-length match) stay highlights in the context, shifted to the
 * shortened context.
 */

import { spansFromTokenStarts, type TextSpan, type TokenStarts } from './sourceSpacing'

export interface KwicSpanInput {
  left: string
  match: string
  right: string
  matchOffsets?: number[]
  collocateOffsets?: number[]
  tokenStarts?: TokenStarts
  wsBeforeKw?: boolean
  wsAfterKw?: boolean
}

export interface KwicSpanDisplay {
  left: string
  match: string
  right: string
  matchOffsets: number[]
  collocateOffsets: number[]
  /** Tokens moved from the left and right context into the match column. */
  before: number
  after: number
  /** Token spans of `left` and `right`, only for rows with `tokenStarts`. */
  leftSpans?: TextSpan[]
  rightSpans?: TextSpan[]
}

type Span = TextSpan

function tokenSpans(text: string): Span[] {
  const spans: Span[] = []
  const re = /\S+/g
  let m: RegExpExecArray | null
  while ((m = re.exec(text)) !== null) spans.push({ start: m.index, end: m.index + m[0].length })
  return spans
}

function shift(offsets: number[], before: number, after: number): number[] {
  const out: number[] = []
  for (const o of offsets) {
    if (!Number.isFinite(o) || o === 0) continue
    if (o < 0) {
      if (-o <= before) continue
      out.push(o + before)
    } else {
      if (o <= after) continue
      out.push(o - after)
    }
  }
  return out
}

export function kwicSpanDisplay(row: KwicSpanInput): KwicSpanDisplay {
  const matchOffsets = (row.matchOffsets ?? []).filter((o) => Number.isFinite(o))
  const collocateOffsets = (row.collocateOffsets ?? []).filter((o) => Number.isFinite(o))
  const set = new Set(matchOffsets)
  const leftText = row.left ?? ''
  const rightText = row.right ?? ''
  const spacedLeft = spansFromTokenStarts(leftText, row.tokenStarts?.left)
  const spacedRight = spansFromTokenStarts(rightText, row.tokenStarts?.right)
  if (spacedLeft && spacedRight) {
    return spacedSpanDisplay(row, leftText, rightText, spacedLeft, spacedRight, set, matchOffsets, collocateOffsets)
  }
  const leftSpans = tokenSpans(leftText)
  const rightSpans = tokenSpans(rightText)
  let before = 0
  while (set.has(-(before + 1)) && before < leftSpans.length) before += 1
  let after = 0
  while (set.has(after + 1) && after < rightSpans.length) after += 1
  if (before === 0 && after === 0) {
    return {
      left: row.left ?? '',
      match: row.match ?? '',
      right: row.right ?? '',
      matchOffsets,
      collocateOffsets,
      before: 0,
      after: 0,
    }
  }
  // Cut the raw strings at token boundaries so the remaining context keeps
  // its own spacing and line breaks.
  const leftCut = before > 0 ? leftSpans[leftSpans.length - before]!.start : leftText.length
  const rightCut = after > 0 ? rightSpans[after - 1]!.end : 0
  const matchParts = [
    leftText.slice(leftCut).trim(),
    row.match ?? '',
    rightText.slice(0, rightCut).trim(),
  ].filter((t) => t.length > 0)
  return {
    left: leftText.slice(0, leftCut).replace(/\s+$/, ''),
    match: matchParts.join(' '),
    right: rightText.slice(rightCut).replace(/^\s+/, ''),
    matchOffsets: shift(matchOffsets, before, after),
    collocateOffsets: shift(collocateOffsets, before, after),
    before,
    after,
  }
}

/** `kwicSpanDisplay` for a row with the original spacing and token starts. */
function spacedSpanDisplay(
  row: KwicSpanInput,
  leftText: string,
  rightText: string,
  leftSpans: Span[],
  rightSpans: Span[],
  set: Set<number>,
  matchOffsets: number[],
  collocateOffsets: number[],
): KwicSpanDisplay {
  let before = 0
  while (set.has(-(before + 1)) && before < leftSpans.length) before += 1
  let after = 0
  while (set.has(after + 1) && after < rightSpans.length) after += 1
  if (before === 0 && after === 0) {
    return {
      left: leftText,
      match: row.match ?? '',
      right: rightText,
      matchOffsets,
      collocateOffsets,
      before: 0,
      after: 0,
      leftSpans,
      rightSpans,
    }
  }
  // Cut at token boundaries. The one space between two tokens goes with the
  // cut, every other character (line breaks included) stays where it was.
  const leftCut = before > 0 ? leftSpans[leftSpans.length - before]!.start : leftText.length
  const rightCut = after > 0 ? rightSpans[after - 1]!.end : 0
  let left = leftText.slice(0, leftCut)
  if (before > 0 && left.endsWith(' ')) left = left.slice(0, -1)
  let rightStart = rightCut
  if (after > 0 && rightText[rightStart] === ' ') rightStart += 1
  const right = rightText.slice(rightStart)
  const movedLeft = leftText.slice(leftCut)
  const movedRight = rightText.slice(0, rightCut)
  let match = row.match ?? ''
  if (movedLeft) match = movedLeft + (row.wsBeforeKw ? ' ' : '') + match
  if (movedRight) match = match + (row.wsAfterKw ? ' ' : '') + movedRight
  return {
    left,
    match,
    right,
    matchOffsets: shift(matchOffsets, before, after),
    collocateOffsets: shift(collocateOffsets, before, after),
    before,
    after,
    leftSpans: leftSpans.slice(0, leftSpans.length - before),
    rightSpans: rightSpans.slice(after).map((span) => ({ start: span.start - rightStart, end: span.end - rightStart })),
  }
}
