import { afterEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'

import { describeCqlParserReason, humanizeCqlParseError, localizeCqlDiagnostic } from '@/lib/cqlDetection'
import { useCqlSuggestions } from '@/composables/queryBuilder/useCqlSuggestions'
import { applyLocale } from '@/i18n/locale'

// The German CQL assistant showed the parser's token errors as they come from
// cqlhpc/parser.py, "expected IDENT, got EOF" or "unexpected token IDENT:pos".
// The server sends these reasons in English for every request language.

// Every reason observed at /api/v1/query/analyse on the sample corpora, plus
// every shape the parser can produce.
const PARSER_REASONS = [
  'expected IDENT, got EOF',
  'expected IDENT, got RBRACK',
  'expected RBRACK, got EOF',
  'expected RBRACK, got PIPE',
  'expected RPAREN, got EOF',
  'expected RBRACE, got EOF',
  'expected OP, got EOF',
  'expected OP, got ERROR',
  'expected COMMA, got STRING',
  'expected NUMBER, got IDENT',
  'expected LANGLE, got IDENT',
  'expected EOF, got RPAREN',
  'expected KW, got IDENT',
  'expected within, got where',
  'expected value, got IDENT:freedom',
  'expected value, got RBRACK:]',
  'expected value, got EOF:',
  'unexpected token IDENT:pos',
  'unexpected token AMP:&',
  'unexpected token LANGLE:<',
  'unexpected token ERROR::',
  'unexpected token ERROR:!',
  'unexpected token STRING:freedom',
  'unexpected token NUMBER:5',
  'unexpected token FLAG:c',
  'unexpected token STRING_UNTERM:abc',
  'unexpected token OP:=',
  'unexpected token KW:in',
  'unexpected token EOF:',
  'empty sequence',
  'invalid meta operator',
  'Unbalanced brackets',
  'Wrong quotes',
]

const PARSER_JARGON = /\b(?:IDENT|EOF|RBRACK|LBRACK|RPAREN|LPAREN|RBRACE|LBRACE|PIPE|AMP|COMMA|LANGLE|RANGLE|STRING_UNTERM|STRING|NUMBER|FLAG|ERROR|OP|KW|expected|unexpected token|got)\b/

afterEach(() => {
  applyLocale('de')
})

describe('parser token errors in the interface language', () => {
  it.each(PARSER_REASONS)('describes %s in German without parser jargon', (reason) => {
    const text = describeCqlParserReason(reason)
    expect(text).toBeTruthy()
    expect(text).not.toMatch(PARSER_JARGON)
  })

  it.each(PARSER_REASONS)('describes %s in English without parser jargon', (reason) => {
    applyLocale('en')
    const text = describeCqlParserReason(reason)
    expect(text).toBeTruthy()
    expect(text).not.toMatch(PARSER_JARGON)
  })

  it('names what is missing and what was found', () => {
    expect(localizeCqlDiagnostic('expected IDENT, got EOF')).toBe(
      'Die Abfrage endet zu früh. Es fehlt ein Attribut- oder Feldname.',
    )
    expect(localizeCqlDiagnostic('expected RBRACK, got PIPE')).toBe('Hier fehlt „]“. Gefunden: „|“.')
    expect(localizeCqlDiagnostic('unexpected token ERROR:!')).toBe('Unerwartet an dieser Stelle: das Zeichen „!“.')
    expect(localizeCqlDiagnostic('expected value, got IDENT:freedom')).toBe(
      'Der Wert „freedom“ braucht Anführungszeichen: "freedom".',
    )
    applyLocale('en')
    expect(localizeCqlDiagnostic('expected IDENT, got EOF')).toBe(
      'The query ends too early. Missing: an attribute or field name.',
    )
    expect(localizeCqlDiagnostic('expected RBRACK, got PIPE')).toBe('Missing here: "]". Found: "|".')
    expect(localizeCqlDiagnostic('unexpected token IDENT:pos')).toBe(
      'Unexpected at this point: the name pos. Conditions go in square brackets, for example [pos="NOUN"].',
    )
  })

  it('leaves messages the server already localized unchanged', () => {
    expect(localizeCqlDiagnostic('Fehlende schließende Klammer(n)')).toBe('Fehlende schließende Klammer(n)')
    expect(describeCqlParserReason("Unerwartetes Zeichen: '!'")).toBeNull()
  })

  it('explains a token error on the search path with the parser position removed', () => {
    expect(humanizeCqlParseError('CQL Parse Fehler: expected IDENT, got EOF at 12:12')).toBe(
      'CQL-Syntaxfehler: Die Abfrage endet zu früh. Es fehlt ein Attribut- oder Feldname.',
    )
    applyLocale('en')
    expect(humanizeCqlParseError('CQL parse error: expected RBRACK, got EOF at 9:9')).toBe(
      'Query syntax error: The query ends too early. Missing: "]".',
    )
  })

  it('keeps a localized parser reason instead of a generic message', () => {
    const reason = 'within(...) erwartet die Form within(<s>, <Muster>) oder within(<doc>, <Muster>), z.B. within(<s>, [pos="NOUN"])'
    expect(humanizeCqlParseError(`CQL Parse Fehler: ${reason} at 11:17`)).toBe(`CQL-Syntaxfehler: ${reason}`)
  })
})

describe('CQL assistant shows parser errors in the interface language', () => {
  it('translates the errors of /query/analyse before the studio shows them', async () => {
    setActivePinia(createPinia())
    vi.useFakeTimers()
    try {
      const analyseCqlQuery = vi.fn().mockResolvedValue({
        suggestions: [],
        errors: ['Fehlende schließende Klammer(n)', 'expected IDENT, got EOF'],
        warnings: [],
        builder: null,
      })
      const suggestions = useCqlSuggestions({
        mode: ref<'simple' | 'advanced'>('advanced'),
        generatedCql: ref(''),
        enabled: ref(true),
        analyseCqlQuery,
        queueHistoryLabel: vi.fn(),
        commitHydratedNode: vi.fn(),
      })
      suggestions.scheduleSuggest('where(')
      await vi.advanceTimersByTimeAsync(300)
      expect(analyseCqlQuery).toHaveBeenCalledWith('cql:where(', expect.anything(), undefined)
      expect(suggestions.analysisErrors.value).toEqual([
        'Fehlende schließende Klammer(n)',
        'Die Abfrage endet zu früh. Es fehlt ein Attribut- oder Feldname.',
      ])
    } finally {
      vi.useRealTimers()
    }
  })
})
