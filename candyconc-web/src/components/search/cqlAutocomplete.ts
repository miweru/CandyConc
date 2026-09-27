import type { SuggestionItem } from '@/api/client'
import { t } from '@/i18n'
import { isCqlfQuery } from '@/lib/cqlDetection'

// Server hints (normalized) mapped to catalog keys for their display label.
// The server sends its own hints in the interface language, so German and
// English forms of the same hint share one key (and one salience below).
const HINT_LABEL_KEYS: Record<string, string> = {
  'token lemma set': 'search.cqlAssist.hintLemmaSet',
  'token lemma equals': 'search.cqlAssist.hintLemmaEquals',
  'token word equals': 'search.cqlAssist.hintWordEquals',
  'token pos equals': 'search.cqlAssist.hintPosEquals',
  'token semantic similarity': 'search.cqlAssist.hintSemantic',
  'wrapper within sentence': 'search.cqlAssist.hintWithinSentence',
  'wrapper doc filter + query': 'search.cqlAssist.hintDocFilter',
  // Wording of the where() snippet in cqlhpc/capabilities.py.
  'wrapper metadata filter + query': 'search.cqlAssist.hintDocFilter',
  'wrapper across sentences': 'search.cqlAssist.hintAcrossSentences',
  'token word equals (case-insensitive)': 'search.cqlAssist.hintWordEqualsCi',
  'token any token (wildcard)': 'search.cqlAssist.hintAnyToken',
  'gap 1 to 3 arbitrary tokens': 'search.cqlAssist.hintGap',
  'group': 'search.cqlAssist.hintGroup',
  'stringliteral': 'search.cqlAssist.hintString',
  'zahl': 'search.cqlAssist.hintNumber',
  'anzahl ähnlicher wörter': 'search.cqlAssist.hintTopK',
  'weitere bedingung': 'search.cqlAssist.hintMoreCondition',
  'string literal': 'search.cqlAssist.hintString',
  'number': 'search.cqlAssist.hintNumber',
  'number of similar words': 'search.cqlAssist.hintTopK',
  'another condition': 'search.cqlAssist.hintMoreCondition',
}

const HINT_SALIENCE: Record<string, number> = {
  'token semantic similarity': 100,
  'wrapper within sentence': 96,
  'wrapper doc filter + query': 94,
  'wrapper metadata filter + query': 94,
  'token lemma set': 92,
  'group': 90,
  'anzahl ähnlicher wörter': 88,
  'token lemma equals': 84,
  'token word equals': 82,
  'token pos equals': 80,
  'weitere bedingung': 72,
  'stringliteral': 60,
  'zahl': 58,
  'number of similar words': 88,
  'another condition': 72,
  'string literal': 60,
  'number': 58,
}

function kindRank(kind?: SuggestionItem['kind']): number {
  if (kind === 'fix') return -10
  if (kind === 'complete') return 1
  return 0
}

export function normalizeSuggestionHint(value: string): string {
  return value
    .toLowerCase()
    .replace(/[:]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
}

export function humanizeSuggestionHint(hint?: string): string | undefined {
  if (!hint) return undefined
  const normalized = normalizeSuggestionHint(hint)
  const key = HINT_LABEL_KEYS[normalized]
  return key ? t(key) : hint
}

export function getSuggestionSalience(item: SuggestionItem): number {
  const normalized = normalizeSuggestionHint(item.hint ?? '')
  if (normalized && normalized in HINT_SALIENCE) {
    return HINT_SALIENCE[normalized] ?? 0
  }
  if (normalized.startsWith('wrapper ')) return 78
  if (normalized.startsWith('token ')) return 70
  if (item.text.includes('[sim=')) return 96
  if (item.text.startsWith('cql:within(') || item.text.startsWith('within(')) return 92
  if (item.text.startsWith('cql:where(') || item.text.startsWith('where(')) return 90
  if (item.text.includes(' in {')) return 88
  return 0
}

export function isSalientCqlSuggestion(item: SuggestionItem): boolean {
  return getSuggestionSalience(item) >= 80
}

export function sortSuggestionsBySalience(items: SuggestionItem[]): SuggestionItem[] {
  return [...items].sort((left, right) => {
    const salienceDelta = getSuggestionSalience(right) - getSuggestionSalience(left)
    if (salienceDelta !== 0) return salienceDelta

    const kindDelta = kindRank(right.kind) - kindRank(left.kind)
    if (kindDelta !== 0) return kindDelta

    const leftPlaceholders = left.hasPlaceholders ? 1 : 0
    const rightPlaceholders = right.hasPlaceholders ? 1 : 0
    if (rightPlaceholders !== leftPlaceholders) {
      return rightPlaceholders - leftPlaceholders
    }

    return left.text.localeCompare(right.text, 'de')
  })
}

export function isRepairSuggestion(item: SuggestionItem, raw: string): boolean {
  if (!item.text) return false
  if (item.kind === 'fix') return true
  const candidate = item.text.trim()
  const trimmed = raw.trim()
  if (!candidate || candidate === trimmed) return false
  if (candidate.startsWith(trimmed)) {
    const suffix = candidate.slice(trimmed.length)
    if (/^[\s\]\)\}"]+$/.test(suffix)) return true
  }
  if (trimmed.startsWith(candidate)) {
    const removed = trimmed.slice(candidate.length)
    if (/^[\]\)\}"]+$/.test(removed)) return true
  }
  const hint = item.hint?.toLowerCase() ?? ''
  if (
    hint.includes('klammer') ||
    hint.includes('bracket') ||
    hint.includes('quote') ||
    hint.includes('anführ') || // i18n-ignore: matches German server hints
    hint.includes('schließ') || // i18n-ignore: matches German server hints
    hint.includes('close')
  ) {
    return true
  }
  return false
}

interface MergeAutocompleteSuggestionsArgs {
  rawQuery: string
  assistSuggestions?: SuggestionItem[]
  valueSuggestions?: SuggestionItem[]
  backendSuggestions?: SuggestionItem[]
  maxSuggestions?: number
}

export function mergeAutocompleteSuggestions({
  rawQuery,
  assistSuggestions = [],
  valueSuggestions = [],
  backendSuggestions = [],
  maxSuggestions = 20,
}: MergeAutocompleteSuggestionsArgs): SuggestionItem[] {
  const trimmed = rawQuery.trim()
  const closeSuggestions = assistSuggestions.filter(
    (item) => item.text.endsWith('"]') || item.text.endsWith(']')
  )
  const otherAssist = assistSuggestions.filter((item) => !closeSuggestions.includes(item))

  const backendFixes: SuggestionItem[] = []
  const backendCompletions: SuggestionItem[] = []

  backendSuggestions.forEach((item) => {
    if (isRepairSuggestion(item, trimmed)) {
      backendFixes.push(item)
      return
    }
    backendCompletions.push(item)
  })

  const ordered: SuggestionItem[] = [
    ...closeSuggestions,
    ...valueSuggestions,
    ...sortSuggestionsBySalience(backendCompletions),
    ...otherAssist,
    ...backendFixes,
  ]

  const unique = new Map<string, SuggestionItem>()
  ordered.forEach((item) => {
    if (!item.text || item.text === trimmed || unique.has(item.text)) return
    unique.set(item.text, item)
  })

  return Array.from(unique.values()).slice(0, maxSuggestions)
}

export function getAutocompleteSeedQuery(term: string): string | null {
  const trimmed = term.trim()
  if (!trimmed) return 'cql:'
  if (trimmed.toLowerCase().startsWith('cql:')) return trimmed
  return `cql:${trimmed}`
}

/**
 * Heuristic: does the input look like a bare CQL query that the user forgot to
 * prefix with `cql:`? We treat token brackets (`[...]`), attribute syntax
 * (`word=`, `lemma=`, `pos=`, `morph=`, `rel=`), or sentence wrappers (`<s>`)
 * as CQL signals.
 * Used by SearchBar to nudge the user to add the `cql:` prefix.
 */
export function looksLikeCqlEntry(term: string): boolean {
  const trimmed = term.trim()
  if (!trimmed) return false
  if (trimmed.toLowerCase().startsWith('cql:')) return false
  // [attribute=value] without quotes and HEAD >rel DEPENDENT are plain
  // search. The query language has neither form, so cql: would break them.
  const quoted = /["']/.test(trimmed) && /\[[^\]]*["'][^\]]*\]/.test(trimmed)
  if (/\[\s*\]/.test(trimmed)) return true
  if (/\[[^\]]*\]/.test(trimmed)) return quoted
  if (/\[(?:\s*(?:word|lemma|pos|ner|sim)\s*=)/i.test(trimmed)) return true
  if (/(?:^|\s)(?:word|lemma|pos|ner|morph|rel)\s*=\s*"/i.test(trimmed)) return true
  if (/<\/?s>/i.test(trimmed)) return true
  return false
}

export type CqlDiagnosticSeverity = 'error' | 'warning' | 'info'

export interface CqlDiagnostic {
  severity: CqlDiagnosticSeverity
  message: string
}

/**
 * Lightweight, purely structural CQL diagnostics for inline feedback in the
 * search bar. This is NOT a parser — it only flags the cheap, high-signal
 * mistakes (unbalanced brackets/quotes/parentheses, empty token, missing
 * prefix). It runs on the bare body (with any `cql:` prefix stripped).
 */
export function analyseQuery(term: string): CqlDiagnostic[] {
  const diagnostics: CqlDiagnostic[] = []
  const trimmed = term.trim()
  if (!trimmed) return diagnostics

  const hasPrefix = trimmed.toLowerCase().startsWith('cql:')
  const body = hasPrefix ? trimmed.slice(4).trim() : trimmed
  if (!body) return diagnostics

  // Bare CQL without the prefix. The server already runs some bare forms as
  // query language (where(...), within(...), a leading token with a quoted
  // value), for those the prefix changes nothing and the hint would be wrong.
  if (!hasPrefix && looksLikeCqlEntry(trimmed) && !isCqlfQuery(trimmed)) {
    diagnostics.push({
      severity: 'info',
      message: t('search.cqlAssist.diagBareCql'),
    })
  }

  const open = (body.match(/\[/g) ?? []).length
  const close = (body.match(/\]/g) ?? []).length
  if (open !== close) {
    diagnostics.push({
      severity: 'error',
      message: open > close ? t('search.cqlAssist.diagMissingBracket') : t('search.cqlAssist.diagExtraBracket'),
    })
  }

  const quotes = (body.match(/"/g) ?? []).length
  if (quotes % 2 !== 0) {
    diagnostics.push({ severity: 'error', message: t('search.cqlAssist.diagQuote') })
  }

  const parenOpen = (body.match(/\(/g) ?? []).length
  const parenClose = (body.match(/\)/g) ?? []).length
  if (parenOpen !== parenClose) {
    diagnostics.push({ severity: 'error', message: t('search.cqlAssist.diagParens') })
  }

  if (/\[\s*\]/.test(body)) {
    diagnostics.push({ severity: 'warning', message: t('search.cqlAssist.diagEmptyToken') })
  }

  if (/\[\s*[A-Za-z_][\w.-]*\s*=\s*\]/.test(body)) {
    diagnostics.push({
      severity: 'error',
      message: t('search.cqlAssist.diagMissingValue'),
    })
  }

  return diagnostics
}
