import { t } from '@/i18n'
import { intlLocale } from '@/i18n/locale'

export type SimpleSearchIntent = 'exact' | 'lemma' | 'similar'

export interface SimpleSearchState {
  intent: SimpleSearchIntent
  term: string
  tokenAttribute: string
  tokenAttributeLabel: string
  similarityK: number
  /**
   * Exact-value metadata filters keyed by field name. The fields come from
   * the metadata schema of the active corpus, not from a fixed list.
   */
  filters: Record<string, string>
}

const DEFAULT_SIMILARITY_K = 20
export const DEFAULT_TOKEN_ATTRIBUTE = 'word'
const STRUCTURED_QUERY_RE = /^(?:\[|\(|within\s*\(|where\s*\()/i
const QUOTED_TERM_RE = /^"((?:[^"\\]|\\.)+)"$/
const SIMILAR_RE =
  /^\[\s*(?:sim\s*=\s*"((?:[^"\\]|\\.)+)"\s*&\s*k\s*=\s*(\d+)|k\s*=\s*(\d+)\s*&\s*sim\s*=\s*"((?:[^"\\]|\\.)+)")\s*\]$/i
// A metadata field is a query language identifier (cqlhpc/lexer.py): a letter,
// underscore or hyphen first, then letters, digits, underscores, hyphens, dots.
const META_FIELD_SOURCE = '[\\p{L}_-][\\p{L}\\p{N}_.-]*'
const META_FIELD_RE = new RegExp(`^${META_FIELD_SOURCE}$`, 'u')
const META_COND_RE = new RegExp(`^(${META_FIELD_SOURCE})\\s*=\\s*"((?:[^"\\\\]|\\\\.)+)"$`, 'u')
const QUERY_KEYWORDS = new Set(['where', 'within', 'in'])
const TOKEN_SEQUENCE_RE = /\[\s*([a-z_][\w-]*)\s*=\s*"((?:[^"\\]|\\.)+)"\s*\]/gi
const TOKEN_ATTRIBUTE_RE = /^[a-z_][\w-]*$/i

export function createDefaultSimpleSearchState(): SimpleSearchState {
  return {
    intent: 'exact',
    term: '',
    tokenAttribute: DEFAULT_TOKEN_ATTRIBUTE,
    tokenAttributeLabel: labelSimpleTokenAttribute(DEFAULT_TOKEN_ATTRIBUTE),
    similarityK: DEFAULT_SIMILARITY_K,
    filters: {},
  }
}

/** Whether a metadata field name can stand in a quick search where() condition. */
export function isSimpleFilterField(name: string): boolean {
  return META_FIELD_RE.test(name) && !QUERY_KEYWORDS.has(name)
}

/** The filters that restrict the search: valid field names with a value, in insertion order. */
export function activeSimpleFilters(state: Pick<SimpleSearchState, 'filters'>): Array<[string, string]> {
  return Object.entries(state.filters ?? {})
    .map(([field, value]) => [field, normalizeWhitespace(String(value ?? ''))] as [string, string])
    .filter(([field, value]) => value !== '' && isSimpleFilterField(field))
}

type ListFormatConstructor = new (
  locale: string,
  options: { style: 'long'; type: 'conjunction' },
) => { format(items: string[]): string }

/** "a, b and c" in the interface language. Intl.ListFormat is ES2021, the type library here is ES2020. */
function joinConjunction(items: string[]): string {
  const ListFormat = (Intl as unknown as { ListFormat?: ListFormatConstructor }).ListFormat
  if (ListFormat) return new ListFormat(intlLocale(), { style: 'long', type: 'conjunction' }).format(items)
  return items.join(', ')
}

function normalizeWhitespace(value: string): string {
  return value.trim().replace(/\s+/g, ' ')
}

function escapeLiteral(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')
}

function unescapeLiteral(value: string): string {
  return value.replace(/\\"/g, '"').replace(/\\\\/g, '\\')
}

function quoteLiteral(value: string): string {
  return `"${escapeLiteral(value)}"`
}

function normalizeTokenAttribute(attr: string | null | undefined): string {
  const normalized = String(attr ?? '').trim().toLowerCase()
  return TOKEN_ATTRIBUTE_RE.test(normalized) ? normalized : DEFAULT_TOKEN_ATTRIBUTE
}

export function labelSimpleTokenAttribute(attr: string): string {
  const normalized = normalizeTokenAttribute(attr)
  if (normalized === 'word') return t('querybuilder.simpleSearch.attrWord')
  if (normalized === 'lemma') return t('querybuilder.simpleSearch.attrLemma')
  if (normalized === 'pos') return t('querybuilder.simpleSearch.attrPos')
  if (normalized === 'ner') return t('querybuilder.simpleSearch.attrNer')
  if (normalized === 'morph') return t('querybuilder.simpleSearch.attrMorph')
  if (normalized === 'rel') return t('querybuilder.simpleSearch.attrRel')
  return normalized.replace(/[_-]+/g, ' ')
}

function tokenAttributeForState(state: SimpleSearchState): string {
  if (state.intent === 'lemma') return 'lemma'
  if (state.intent === 'similar') return DEFAULT_TOKEN_ATTRIBUTE
  return normalizeTokenAttribute(state.tokenAttribute)
}

function splitPhraseIntoTokens(term: string): string[] {
  return normalizeWhitespace(term)
    .split(' ')
    .map((token) => token.trim())
    .filter(Boolean)
}

function buildTokenSequence(attr: string, term: string): string {
  const normalizedAttr = normalizeTokenAttribute(attr)
  const tokens = splitPhraseIntoTokens(term)
  if (!tokens.length) return ''
  return tokens.map((token) => `[${normalizedAttr}=${quoteLiteral(token)}]`).join(' ')
}

function splitTopLevel(value: string, delimiter: string): string[] {
  const parts: string[] = []
  let current = ''
  let depthParen = 0
  let depthBracket = 0
  let inString = false
  let escaped = false

  for (const char of value) {
    if (escaped) {
      current += char
      escaped = false
      continue
    }
    if (char === '\\') {
      current += char
      escaped = true
      continue
    }
    if (char === '"') {
      current += char
      inString = !inString
      continue
    }
    if (!inString) {
      if (char === '(') depthParen += 1
      if (char === ')') depthParen = Math.max(0, depthParen - 1)
      if (char === '[') depthBracket += 1
      if (char === ']') depthBracket = Math.max(0, depthBracket - 1)
      if (char === delimiter && depthParen === 0 && depthBracket === 0) {
        parts.push(current.trim())
        current = ''
        continue
      }
    }
    current += char
  }

  if (current.trim()) {
    parts.push(current.trim())
  }

  return parts
}

function unwrapSimpleWhere(raw: string): { filters: Record<string, string>; body: string } | null {
  const trimmed = raw.trim()
  if (!/^where\s*\(/i.test(trimmed) || !trimmed.endsWith(')')) return null
  const inner = trimmed.replace(/^where\s*\(/i, '').slice(0, -1).trim()
  const parts = splitTopLevel(inner, ',')
  if (parts.length !== 2) return null
  const [filterPart = '', body = ''] = parts

  const filters: Record<string, string> = {}
  for (const condition of splitTopLevel(filterPart, '&')) {
    const match = condition.match(META_COND_RE)
    if (!match) return null
    const field = match[1]
    const rawValue = match[2]
    if (!field || !rawValue || !isSimpleFilterField(field)) return null
    // One select per field: a second condition on the same field is not a quick search.
    if (field in filters) return null
    filters[field] = unescapeLiteral(rawValue)
  }

  return { filters, body }
}

function parseQuotedTerm(raw: string): string | null {
  const match = raw.match(QUOTED_TERM_RE)
  const value = match?.[1]
  return value ? unescapeLiteral(value) : null
}

function parseTokenSequence(raw: string): { attr: string; term: string } | null {
  const trimmed = raw.trim()
  let lastIndex = 0
  let sequenceAttr: string | null = null
  const tokens: string[] = []

  TOKEN_SEQUENCE_RE.lastIndex = 0
  for (const match of trimmed.matchAll(TOKEN_SEQUENCE_RE)) {
    if (match.index === undefined) return null
    if (trimmed.slice(lastIndex, match.index).trim()) return null
    const rawAttr = match[1]
    const rawValue = match[2]
    if (!rawAttr || !rawValue) return null
    const attr = normalizeTokenAttribute(rawAttr)
    if (attr === 'sim') return null
    if (sequenceAttr && attr !== sequenceAttr) return null
    sequenceAttr = attr
    tokens.push(unescapeLiteral(rawValue))
    lastIndex = match.index + match[0].length
  }

  if (!tokens.length) return null
  if (trimmed.slice(lastIndex).trim()) return null
  return {
    attr: sequenceAttr ?? DEFAULT_TOKEN_ATTRIBUTE,
    term: tokens.join(' '),
  }
}

function parseSimilar(raw: string): Pick<SimpleSearchState, 'intent' | 'term' | 'similarityK'> | null {
  const match = raw.trim().match(SIMILAR_RE)
  if (!match) return null
  const term = unescapeLiteral(match[1] || match[4] || '')
  const rawK = match[2] || match[3] || String(DEFAULT_SIMILARITY_K)
  const similarityK = Number.parseInt(rawK, 10)
  if (!term || !Number.isFinite(similarityK) || similarityK <= 0) return null
  return {
    intent: 'similar',
    term,
    similarityK,
  }
}

export function buildSimpleSearchQuery(state: SimpleSearchState): string {
  const term = normalizeWhitespace(state.term)
  if (!term) return ''

  let body = ''
  if (state.intent === 'lemma') {
    body = buildTokenSequence('lemma', term)
  } else if (state.intent === 'similar') {
    body = `[sim=${quoteLiteral(term)} & k=${Math.max(1, Math.round(state.similarityK || DEFAULT_SIMILARITY_K))}]`
  } else {
    body = buildTokenSequence(tokenAttributeForState(state), term)
  }

  const filters = activeSimpleFilters(state).map(([field, value]) => `${field}=${quoteLiteral(value)}`)
  if (!filters.length) return body
  return `where(${filters.join(' & ')}, ${body})`
}

export function buildSimpleSearchSummary(state: SimpleSearchState): string {
  const term = normalizeWhitespace(state.term)
  if (!term) return t('querybuilder.simpleSearch.summaryEmpty')

  const attr = tokenAttributeForState(state)
  const attrLabel = normalizeWhitespace(state.tokenAttributeLabel) || labelSimpleTokenAttribute(attr)
  const tokenCount = splitPhraseIntoTokens(term).length
  const scope =
    state.intent === 'lemma'
      ? t('querybuilder.simpleSearch.scopeLemma', { term })
      : state.intent === 'similar'
        ? t('querybuilder.simpleSearch.scopeSimilar', {
          term,
          k: String(Math.max(1, Math.round(state.similarityK || DEFAULT_SIMILARITY_K))),
        })
        : attr !== DEFAULT_TOKEN_ATTRIBUTE
          ? tokenCount > 1
            ? t('querybuilder.simpleSearch.scopeAttrSequence', { attr: attrLabel, term })
            : t('querybuilder.simpleSearch.scopeAttrValue', { attr: attrLabel, term })
          : tokenCount > 1
            ? t('querybuilder.simpleSearch.scopeWordSequence', { term })
            : t('querybuilder.simpleSearch.scopeExactWord', { term })

  const constraints = activeSimpleFilters(state).map(([field, value]) =>
    t('querybuilder.simpleSearch.constraintField', { field, value })
  )
  if (!constraints.length) return t('querybuilder.simpleSearch.summary', { scope })
  const joined = joinConjunction(constraints)
  return t('querybuilder.simpleSearch.summaryRestricted', { scope, constraints: joined })
}

export function hydrateSimpleSearchQuery(raw: string): SimpleSearchState | null {
  const trimmed = raw.trim()
  if (!trimmed) return createDefaultSimpleSearchState()

  const legacyQuotedTerm = parseQuotedTerm(trimmed)
  if (legacyQuotedTerm !== null) {
    return {
      ...createDefaultSimpleSearchState(),
      term: legacyQuotedTerm,
    }
  }

  if (!STRUCTURED_QUERY_RE.test(trimmed)) {
    return {
      ...createDefaultSimpleSearchState(),
      term: normalizeWhitespace(trimmed),
    }
  }

  const whereWrapper = unwrapSimpleWhere(trimmed)
  const filters = whereWrapper?.filters ?? {}
  const body = whereWrapper?.body ?? trimmed

  const tokenSequence = parseTokenSequence(body)
  if (tokenSequence) {
    const intent: SimpleSearchIntent = tokenSequence.attr === 'lemma' ? 'lemma' : 'exact'
    return {
      ...createDefaultSimpleSearchState(),
      intent,
      term: tokenSequence.term,
      tokenAttribute: tokenSequence.attr,
      tokenAttributeLabel: labelSimpleTokenAttribute(tokenSequence.attr),
      filters,
    }
  }

  const similar = parseSimilar(body)
  if (similar) {
    return {
      ...createDefaultSimpleSearchState(),
      ...similar,
      filters,
    }
  }

  return null
}

export function canHydrateSimpleSearchQuery(raw: string): boolean {
  return hydrateSimpleSearchQuery(raw) !== null
}
