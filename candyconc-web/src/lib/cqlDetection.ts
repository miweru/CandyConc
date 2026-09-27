import { t } from '@/i18n'
/**
 * Frontend mirror of backend CQL entry detection.
 *
 * Keep this intentionally narrower than editor diagnostics: it gates product
 * capability access and therefore should match `normalize_query_input()` rather
 * than flag every CQL-looking typo.
 */
export function looksLikeBackendBareCql(term: string): boolean {
  const raw = term.trim()
  if (!raw) return false
  const lower = raw.toLowerCase()
  if (lower.startsWith('within(') || lower.startsWith('where(')) return true
  if (lower === 'within' || lower === 'where') return true
  if (lower.startsWith('within ') || lower.startsWith('where ')) return true
  // A group counts like its first cell, as in _looks_like_bare_cql.
  if (!raw.replace(/^[( \t]+/, '').startsWith('[')) return false
  if (raw.includes('[]')) return true
  return raw.includes('"') || raw.includes("'")
}

function unescapeQuoted(value: string): string {
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

function extractCoKwicTerm(raw: string): string | null {
  const trimmed = raw.trim()
  if (!trimmed.toLowerCase().startsWith('co(') || !trimmed.endsWith(')')) return null
  const match = /(?:^|[,\s])term\s*=\s*"((?:\\.|[^"\\])*)"/i.exec(trimmed.slice(3, -1))
  return match ? unescapeQuoted(match[1] ?? '') : null
}

export function isCqlfQuery(term: string): boolean {
  const raw = term.trim()
  if (!raw) return false
  const lower = raw.toLowerCase()
  if (lower.startsWith('cql:')) return true
  if (lower.startsWith('sim(')) return true
  if (looksLikeBackendBareCql(raw)) return true

  const coKwicTerm = extractCoKwicTerm(raw)
  return coKwicTerm ? isCqlfQuery(coKwicTerm) : false
}

/**
 * A plain space-separated multi-word entry the box advertises as "Phrase"
 * (e.g. `der Klimawandel`). The backend plain-search path can only match a
 * single token and rejects this with a raw "Unexpected token", so the UI must
 * translate it to the token-sequence CQL form. We only treat it as a plain
 * phrase when it carries NO CQL structure (no brackets, quotes, `cql:`/`sim(`,
 * within/where, wildcards) — anything structural belongs to the CQL path.
 */
export function isPlainPhraseQuery(term: string): boolean {
  const raw = term.trim()
  if (!raw) return false
  if (isCqlfQuery(raw)) return false
  // Structural CQL characters mean this is not a plain phrase.
  if (/[[\]"'*=<>()|]/.test(raw)) return false
  // Two or more whitespace-separated tokens.
  return raw.split(/\s+/).filter(Boolean).length >= 2
}

/**
 * Escape a literal word for use inside a CQL double-quoted token value. The CQL
 * value is a regex, so regex metacharacters (and the closing quote/backslash)
 * must be escaped to match the surface form verbatim.
 */
function escapeCqlWordLiteral(word: string): string {
  return word.replace(/[\\.^$*+?()[\]{}|"]/g, '\\$&')
}

/**
 * Translate a plain multi-word phrase to the token-sequence CQL the engine
 * supports, e.g. `der Klimawandel` -> `cql:[word="der"] [word="Klimawandel"]`.
 * `attribute` is the corpus word attribute (default `word`). Returns null when
 * the input is not a plain phrase, so callers can fall through unchanged.
 */
export function plainPhraseToCql(term: string, attribute = 'word'): string | null {
  if (!isPlainPhraseQuery(term)) return null
  const words = term.trim().split(/\s+/).filter(Boolean)
  const tokens = words.map((word) => `[${attribute}="${escapeCqlWordLiteral(word)}"]`)
  return `cql:${tokens.join(' ')}`
}

// Token kinds of the cqlhpc lexer (cqlhpc/lexer.py) that stand for one
// character.
const TOKEN_SYMBOLS: Record<string, string> = {
  LBRACK: '[',
  RBRACK: ']',
  LPAREN: '(',
  RPAREN: ')',
  LBRACE: '{',
  RBRACE: '}',
  PIPE: '|',
  AMP: '&',
  COMMA: ',',
  QMARK: '?',
  STAR: '*',
  PLUS: '+',
  LANGLE: '<',
  RANGLE: '>',
}

// The shapes of the parser's token errors (cqlhpc/parser.py): Parser.eat,
// the fall-through of the atom parser and the value parser.
const EXPECTED_VALUE = /^expected value, got ([A-Z_]+):([\s\S]*)$/
const EXPECTED_KEYWORD = /^expected (within|where|in), got ([\s\S]*)$/
const EXPECTED_KIND = /^expected ([A-Z_]+), got ([A-Z_]+)$/
const UNEXPECTED_TOKEN = /^unexpected token ([A-Z_]+):([\s\S]*)$/
const POSITION_SUFFIX = /\s+at \d+:\d+$/

function describeToken(kind: string, value?: string): string | null {
  const symbol = TOKEN_SYMBOLS[kind]
  if (symbol) return t('search.cqlParse.tokens.symbol', { symbol })
  const known = value !== undefined && value !== ''
  switch (kind) {
    case 'OP':
      return known ? t('search.cqlParse.tokens.symbol', { symbol: value }) : t('search.cqlParse.tokens.op')
    case 'IDENT':
      return known ? t('search.cqlParse.tokens.identValue', { value }) : t('search.cqlParse.tokens.ident')
    case 'KW':
      return known ? t('search.cqlParse.tokens.keywordValue', { value }) : t('search.cqlParse.tokens.keyword')
    case 'STRING':
      return known ? t('search.cqlParse.tokens.stringValue', { value }) : t('search.cqlParse.tokens.string')
    case 'STRING_UNTERM':
      return t('search.cqlParse.tokens.stringUnterm')
    case 'NUMBER':
      return known ? t('search.cqlParse.tokens.numberValue', { value }) : t('search.cqlParse.tokens.number')
    case 'FLAG':
      return t('search.cqlParse.tokens.flag')
    case 'ERROR':
      return known ? t('search.cqlParse.tokens.character', { value }) : t('search.cqlParse.tokens.characterAny')
    case 'EOF':
      return t('search.cqlParse.tokens.end')
    default:
      return null
  }
}

/**
 * A readable sentence for a parser token error ("expected IDENT, got EOF",
 * "unexpected token IDENT:pos", "expected value, got IDENT:freedom") and for
 * the English-only messages of the parser and the syntax validator. Returns
 * null for any other text. The other parser messages already arrive in the
 * request language.
 */
export function describeCqlParserReason(reason: string): string | null {
  const text = reason.trim().replace(POSITION_SUFFIX, '')

  const value = EXPECTED_VALUE.exec(text)
  if (value) {
    const [, kind, raw] = value
    if (kind === 'IDENT' && raw) return t('search.cqlParse.unquotedValue', { value: raw })
    return t('search.cqlParse.missingValue')
  }

  const keyword = EXPECTED_KEYWORD.exec(text)
  if (keyword) {
    const [, expected, found] = keyword
    return found
      ? t('search.cqlParse.expectedFound', {
        expected: t('search.cqlParse.tokens.keywordValue', { value: expected }),
        found: t('search.cqlParse.tokens.keywordValue', { value: found }),
      })
      : t('search.cqlParse.endsEarly', { expected: t('search.cqlParse.tokens.keywordValue', { value: expected }) })
  }

  const kinds = EXPECTED_KIND.exec(text)
  if (kinds) {
    const [, expectedKind, foundKind] = kinds
    const found = describeToken(foundKind!)
    if (expectedKind === 'EOF') return found ? t('search.cqlParse.trailing', { found }) : null
    const expected = describeToken(expectedKind!)
    if (!expected) return null
    if (foundKind === 'EOF') return t('search.cqlParse.endsEarly', { expected })
    return found ? t('search.cqlParse.expectedFound', { expected, found }) : null
  }

  const unexpected = UNEXPECTED_TOKEN.exec(text)
  if (unexpected) {
    const [, kind, raw] = unexpected
    if (kind === 'EOF') return t('search.cqlParse.endsEarlyAny')
    const found = describeToken(kind!, raw)
    if (!found) return null
    return kind === 'IDENT'
      ? t('search.cqlParse.unexpectedName', { found })
      : t('search.cqlParse.unexpected', { found })
  }

  if (text === 'empty sequence') return t('search.cqlParse.emptySequence')
  if (text === 'invalid meta operator') return t('search.cqlParse.invalidMetaOperator')
  // English-only errors of the syntax validator behind /query/analyse.
  if (text === 'Unbalanced brackets') return t('search.cqlParse.unbalancedBrackets')
  if (text === 'Wrong quotes') return t('search.cqlParse.wrongQuotes')
  return null
}

/** A diagnostic of /query/analyse in the interface language. */
export function localizeCqlDiagnostic(message: string): string {
  return describeCqlParserReason(message) ?? message
}

/**
 * Translate a backend parser error ("CQL Parse Fehler: ... at 3:4") for the
 * research interface. The backend remains the parsing authority, this only
 * explains an error it has already confirmed.
 */
export function humanizeCqlParseError(message: string): string {
  const trimmed = message.trim()
  // The server sends the prefix in the request language.
  const prefix = /^CQL (?:Parse Fehler|parse error):\s*/i
  if (!prefix.test(trimmed)) return trimmed

  const detail = trimmed.replace(prefix, '').replace(POSITION_SUFFIX, '').trim()
  if (!detail) return t('search.cqlParse.invalid')
  const described = describeCqlParserReason(detail)
  if (described) return t('search.cqlParse.syntax', { detail: described })
  if (/\b(?:EOF|end of (?:input|file)|unexpected end)\b/i.test(detail)) {
    return t('search.cqlParse.incomplete')
  }
  // Every other parser reason is a German and English pair (lt in
  // parser.py and nfa.py) and arrives in the request language.
  return t('search.cqlParse.syntax', { detail })
}
