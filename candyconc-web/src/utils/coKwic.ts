import type { QueryResult } from '@/api/client'
import type { KwicRow } from '@/stores/query'
import { readRowSpacing } from '@/utils/sourceSpacing'

export interface CoKwicQuery {
  term: string
  collocates: string[]
  window: number
  withinSentence?: boolean
  /** Counting attribute of the collocation table the row came from. */
  attribute?: 'word' | 'lemma'
}

export interface CoKwicBuildParams {
  term: string
  collocate?: string
  collocates?: string[]
  window: number
  withinSentence?: boolean
  attribute?: 'word' | 'lemma'
}

export interface CoKwicWindowState {
  hasMore: boolean
  nextOffset: number
  totalKnown: boolean
  totalPartial: boolean
}

/**
 * Window state of a Co-KWIC page. The route counts every matching node hit
 * before paging, so `total` is exact (`totalKnown`). `totalPartial` says that
 * more rows exist than this page holds.
 */
export function coKwicWindowState(result: Pick<QueryResult, 'next_offset' | 'truncated'>): CoKwicWindowState {
  const hasMore = result.next_offset !== null && result.next_offset !== undefined
  const totalPartial = Boolean(result.truncated) || hasMore
  return {
    hasMore,
    nextOffset: hasMore ? result.next_offset ?? 0 : 0,
    totalKnown: true,
    totalPartial,
  }
}

export function mapCoKwicHits(result: Pick<QueryResult, 'hits'>): KwicRow[] {
  return result.hits.map((hit) => ({
    position: hit.position,
    left: hit.left,
    match: hit.match,
    right: hit.right,
    docId: hit.doc_id,
    docTitle: hit.doc_title,
    metadata: hit.metadata,
    collocateOffsets: hit.collocate_offsets,
    matchOffsets: hit.match_offsets,
    ...readRowSpacing(hit),
  }))
}

function escapeValue(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/"/g, '\\"')
}

function unescapeValue(value: string): string {
  let out = ''
  let escaped = false
  for (const ch of value) {
    if (escaped) {
      out += ch
      escaped = false
      continue
    }
    if (ch === '\\') {
      escaped = true
      continue
    }
    out += ch
  }
  return out
}

function normalizeCollocates(params: CoKwicBuildParams): string[] {
  const raw = params.collocates?.length
    ? params.collocates
    : params.collocate
      ? [params.collocate]
      : []
  const out: string[] = []
  const seen = new Set<string>()
  raw.forEach((entry) => {
    const trimmed = (entry ?? '').trim()
    if (!trimmed) return
    if (seen.has(trimmed)) return
    seen.add(trimmed)
    out.push(trimmed)
  })
  return out
}

export function buildCoKwicQuery(params: CoKwicBuildParams): string {
  const window = Math.max(1, Math.round(params.window || 5))
  const term = escapeValue(params.term.trim())
  const collocates = normalizeCollocates(params)
  const collocate = collocates.map(value => escapeValue(value)).join('|')
  const within = params.withinSentence !== undefined ? params.withinSentence : true
  const attribute = params.attribute === 'lemma' ? ', attribute=lemma' : ''
  return `co(term="${term}", collocate="${collocate}", window=${window}, within_sentence=${within}${attribute})`
}

function splitOutsideQuotes(text: string): string[] {
  const parts: string[] = []
  let current = ''
  let inQuotes = false
  let escaped = false

  for (const ch of text) {
    if (escaped) {
      current += ch
      escaped = false
      continue
    }
    if (ch === '\\') {
      current += ch
      escaped = true
      continue
    }
    if (ch === '"') {
      current += ch
      inQuotes = !inQuotes
      continue
    }
    if (ch === ',' && !inQuotes) {
      parts.push(current)
      current = ''
      continue
    }
    current += ch
  }

  if (current) parts.push(current)
  return parts
}

export function parseCoKwicQuery(input: string): CoKwicQuery | null {
  const trimmed = input.trim()
  if (!trimmed.toLowerCase().startsWith('co(') || !trimmed.endsWith(')')) {
    return null
  }

  const inside = trimmed.slice(trimmed.indexOf('(') + 1, -1).trim()
  if (!inside) return null

  const parts = splitOutsideQuotes(inside)
  const values: Record<string, string> = {}

  for (const part of parts) {
    const idx = part.indexOf('=')
    if (idx === -1) continue
    const key = part.slice(0, idx).trim().toLowerCase()
    const rawValue = part.slice(idx + 1).trim()
    if (!key || !rawValue) continue
    values[key] = rawValue
  }

  const termRaw = values.term
  const collocateRaw = values.collocate ?? values.collocates
  if (!termRaw || !collocateRaw) return null

  const term = termRaw.startsWith('"') && termRaw.endsWith('"')
    ? unescapeValue(termRaw.slice(1, -1))
    : termRaw
  const collocateValue = collocateRaw.startsWith('"') && collocateRaw.endsWith('"')
    ? collocateRaw.slice(1, -1)
    : collocateRaw

  const collocates: string[] = []
  let current = ''
  let escaped = false
  for (const ch of collocateValue) {
    if (escaped) {
      current += ch
      escaped = false
      continue
    }
    if (ch === '\\') {
      escaped = true
      continue
    }
    if (ch === '|') {
      const trimmed = unescapeValue(current).trim()
      if (trimmed) collocates.push(trimmed)
      current = ''
      continue
    }
    current += ch
  }
  const last = unescapeValue(current).trim()
  if (last) collocates.push(last)

  const windowRaw = values.window ?? values.w ?? ''
  const windowNum = Number.parseInt(windowRaw, 10)
  const window = Number.isFinite(windowNum) && windowNum > 0 ? windowNum : 5
  const withinRaw = values.within_sentence ?? values.within ?? values.withinsentence ?? ''
  const withinSentence = withinRaw === ''
    ? undefined
    : ['1', 'true', 'yes'].includes(withinRaw.toLowerCase())

  const attributeRaw = (values.attribute ?? values.attr ?? '').replace(/"/g, '').trim().toLowerCase()
  const attribute: 'word' | 'lemma' = attributeRaw === 'lemma' ? 'lemma' : 'word'

  const uniq = Array.from(new Set(collocates))
  if (!term.trim() || uniq.length === 0) return null
  return { term: term.trim(), collocates: uniq, window, withinSentence, attribute }
}
