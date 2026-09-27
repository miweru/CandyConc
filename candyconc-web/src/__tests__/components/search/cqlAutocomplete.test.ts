import { afterEach, describe, expect, it } from 'vitest'

import type { SuggestionItem } from '@/api/client'
import {
  analyseQuery,
  getAutocompleteSeedQuery,
  getSuggestionSalience,
  humanizeSuggestionHint,
  looksLikeCqlEntry,
  mergeAutocompleteSuggestions,
  sortSuggestionsBySalience,
} from '@/components/search/cqlAutocomplete'
import { applyLocale } from '@/i18n/locale'
import { humanizeCqlParseError } from '@/lib/cqlDetection'

function suggestion(text: string, hint: string, kind: SuggestionItem['kind'] = 'complete'): SuggestionItem {
  return { text, hint, kind, hasPlaceholders: /\$\d+/.test(text) }
}

describe('cqlAutocomplete', () => {
  it('keeps salient backend snippets ahead of repairs', () => {
    const merged = mergeAutocompleteSuggestions({
      rawQuery: 'cql:',
      assistSuggestions: [
        suggestion('cql:[word="', 'Token beginnen: Wort'),
      ],
      backendSuggestions: [
        suggestion('cql:[sim="$1"&k=20]', 'Token: semantic similarity'),
        suggestion('cql:within(<s>, $1)', 'Wrapper: within sentence'),
        suggestion('cql:[lemma in {"$1","$2"}]', 'Token: lemma set'),
        suggestion('cql:[word="Haus"]', 'Token schließen', 'fix'),
      ],
      maxSuggestions: 10,
    })

    expect(merged.slice(0, 3).map((item) => item.text)).toEqual([
      'cql:[sim="$1"&k=20]',
      'cql:within(<s>, $1)',
      'cql:[lemma in {"$1","$2"}]',
    ])
    expect(merged[merged.length - 1]?.kind).toBe('fix')
  })

  it('provides a top-level cql seed query for empty builder input', () => {
    expect(getAutocompleteSeedQuery('')).toBe('cql:')
    expect(getAutocompleteSeedQuery('[lemma="Haus"]')).toBe('cql:[lemma="Haus"]')
  })

  it('sorts salient snippet hints before generic completions', () => {
    const sorted = sortSuggestionsBySalience([
      suggestion('cql:[lemma="$1"]', 'Token: lemma equals'),
      suggestion('cql:where($1, $2)', 'Wrapper: doc filter + query'),
      suggestion('cql:"$1"', 'Stringliteral'),
    ])

    expect(sorted.map((item) => item.text)).toEqual([
      'cql:where($1, $2)',
      'cql:[lemma="$1"]',
      'cql:"$1"',
    ])
  })

  describe('looksLikeCqlEntry (DT-FE-UX-CORE)', () => {
    it('detects bare CQL without the cql: prefix', () => {
      expect(looksLikeCqlEntry('[word="Haus"]')).toBe(true)
      expect(looksLikeCqlEntry('pos="NN"')).toBe(true)
      expect(looksLikeCqlEntry('morph="Number=Plur"')).toBe(true)
      expect(looksLikeCqlEntry('rel="nsubj"')).toBe(true)
      expect(looksLikeCqlEntry('<s>')).toBe(true)
    })

    it('leaves plain attribute and dependency searches without the prefix hint', () => {
      // Plain search reads [attribute=value] without quotes and HEAD >rel DEP.
      // With cql: in front both fail, the query language has neither form.
      expect(looksLikeCqlEntry('[lemma=freedom]')).toBe(false)
      expect(looksLikeCqlEntry('[word=freedom] >amod [word=political]')).toBe(false)
      expect(looksLikeCqlEntry('[pos=VERB] >nsubj [lemma=freedom]')).toBe(false)
      expect(looksLikeCqlEntry("n't <neg [word=do]")).toBe(false)
      expect(looksLikeCqlEntry('[]')).toBe(true)
    })

    it('ignores plain words and already-prefixed queries', () => {
      expect(looksLikeCqlEntry('Klimawandel')).toBe(false)
      expect(looksLikeCqlEntry('cql:[word="Haus"]')).toBe(false)
      expect(looksLikeCqlEntry('')).toBe(false)
    })
  })

  describe('analyseQuery (DT-FE-UX-CORE)', () => {
    it('flags an unbalanced token bracket', () => {
      const diags = analyseQuery('cql:[word="Haus"')
      expect(diags.some((d) => d.severity === 'error' && d.message.includes(']'))).toBe(true)
    })

    it('flags an unclosed quote', () => {
      const diags = analyseQuery('cql:[word="Haus]')
      expect(diags.some((d) => d.severity === 'error' && d.message.includes('Anführungszeichen'))).toBe(true)
    })

    it('suggests the cql: prefix for bare CQL', () => {
      // The server runs this as plain text: it starts with a plain word.
      const diags = analyseQuery('Haus [word="Hütte"]')
      expect(diags.some((d) => d.severity === 'info' && d.message.includes('cql:'))).toBe(true)
    })

    it.each([
      '[word="Haus"]',
      'where(party="Republican", [word="freedom"])',
      'within(<s>, [word="Haus"])',
      '([word="Haus"] | [word="Hütte"])',
    ])('does not suggest the prefix for %s, which the server already runs as query language', (query) => {
      // The query builder hands over where(...) without cql:. The query ran,
      // and the search bar still said "put cql: in front".
      const diags = analyseQuery(query)
      expect(diags.filter((d) => d.severity === 'info')).toEqual([])
    })

    it('returns no diagnostics for a clean prefixed query', () => {
      expect(analyseQuery('cql:[word="Haus"]')).toEqual([])
    })

    it('returns no diagnostics for an empty input', () => {
      expect(analyseQuery('')).toEqual([])
    })

    it('explains an empty attribute value before the backend has to reject it', () => {
      const diags = analyseQuery('cql:[word=]')
      expect(diags).toContainEqual(expect.objectContaining({
        severity: 'error',
        message: expect.stringContaining('fehlt ein Wert'),
      }))
    })
  })

  describe('server hints in both request languages', () => {
    // The backend sends each hint in the request language. A German and an
    // English hint for the same suggestion must get the same label and rank.
    const pairs: Array<[string, string]> = [
      ['Stringliteral', 'String literal'],
      ['Zahl', 'Number'],
      ['Anzahl ähnlicher Wörter', 'Number of similar words'],
      ['weitere Bedingung', 'Another condition'],
    ]

    afterEach(() => applyLocale('de'))

    it.each(pairs)('%s and %s share one catalog label', (german, english) => {
      for (const locale of ['de', 'en'] as const) {
        applyLocale(locale)
        const label = humanizeSuggestionHint(german)
        expect(label).not.toBe(german)
        expect(humanizeSuggestionHint(english)).toBe(label)
      }
    })

    it.each(pairs)('%s and %s share one salience', (german, english) => {
      const rank = getSuggestionSalience(suggestion('cql:x', german))
      expect(rank).toBeGreaterThan(0)
      expect(getSuggestionSalience(suggestion('cql:x', english))).toBe(rank)
    })
  })

  it('labels the where() snippet hint the server sends ("Wrapper: metadata filter + query")', () => {
    // cqlhpc/capabilities.py sends this hint for the where() snippet. Only the
    // older wording "doc filter + query" was known, so the raw English hint
    // appeared in the German interface.
    const hint = 'Wrapper: metadata filter + query'
    expect(humanizeSuggestionHint(hint)).toBe('Metadatenfilter + Query')
    expect(getSuggestionSalience(suggestion('cql:where(model="x", $1)', hint)))
      .toBe(getSuggestionSalience(suggestion('cql:where(model="x", $1)', 'Wrapper: doc filter + query')))
    applyLocale('en')
    expect(humanizeSuggestionHint(hint)).toBe('Metadata filter + query')
    applyLocale('de')
  })

  it.each([
    ['Wrapper: across sentences', 'Über Satzgrenzen im Dokument', 'Across sentences within the document'],
    ['Token: word equals (case-insensitive)', 'Wortform-Filter ohne Groß-/Kleinschreibung', 'Word form filter, case-insensitive'],
    ['Token: any token (wildcard)', 'Beliebiges Token', 'Any token'],
    ['Gap: 1 to 3 arbitrary tokens', 'Lücke von 1 bis 3 Token', 'Gap of 1 to 3 tokens'],
  ])('labels the snippet hint %s in both languages', (hint, german, english) => {
    // Snippet hints of cqlhpc/capabilities.py that stayed English in the German interface.
    expect(humanizeSuggestionHint(hint)).toBe(german)
    applyLocale('en')
    expect(humanizeSuggestionHint(hint)).toBe(english)
    applyLocale('de')
  })

  it('recognizes the English parser prefix the server sends to an English request', () => {
    expect(humanizeCqlParseError('CQL parse error: expected value, got RBRACK:] at 6:7')).toBe(
      humanizeCqlParseError('CQL Parse Fehler: expected value, got RBRACK:] at 6:7'),
    )
    expect(humanizeCqlParseError('CQL parse error: expected value, got RBRACK:] at 6:7')).not.toContain(
      'CQL parse error',
    )
  })

  it('turns a backend-confirmed parser token error into a German repair hint', () => {
    expect(humanizeCqlParseError('CQL Parse Fehler: expected value, got RBRACK:] at 6:7')).toBe(
      'CQL-Syntaxfehler: Nach „=“ fehlt ein Wert. Beispiel: cql:[word="Hase"].',
    )
  })
})
