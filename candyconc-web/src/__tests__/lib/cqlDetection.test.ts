import { describe, expect, it } from 'vitest'

import {
  isCqlfQuery,
  looksLikeBackendBareCql,
  isPlainPhraseQuery,
  plainPhraseToCql,
} from '@/lib/cqlDetection'

describe('CQLF detection mirrors backend entry normalization', () => {
  it.each([
    'cql:[word="Hase"]',
    '[word="Hase"]',
    "[lemma='gehen']",
    '[]',
    'within([word="Hase"], s)',
    'where([word="Hase"], genre="news")',
    'sim("Hase", k=5)',
    'co(term="cql:[word=\\"Hase\\"]", collocate="schnell", window=5)',
  ])('detects %s as CQLF', (query) => {
    expect(isCqlfQuery(query)).toBe(true)
  })

  it.each([
    'Hase',
    'hase und fuchs',
    '[pos=VERB] >nsubj [pos=NOUN]',
    'co(term="Hase", collocate="schnell", window=5)',
  ])('does not classify %s as backend CQLF', (query) => {
    expect(isCqlfQuery(query)).toBe(false)
  })

  it('does not treat unquoted legacy dependency brackets as backend bare CQL', () => {
    expect(looksLikeBackendBareCql('[pos=VERB] >nsubj [pos=NOUN]')).toBe(false)
  })

  it('treats a group like its first cell, as the backend does', () => {
    expect(isCqlfQuery('([word="Haus"] | [word="Hütte"])')).toBe(true)
    expect(isCqlfQuery('( [lemma="gehen"] )')).toBe(true)
    expect(looksLikeBackendBareCql('([pos=ADJ] OR cat)')).toBe(false)
  })
})

describe('plain multi-word phrase translation (SEARCH-KWIC-01)', () => {
  it.each([
    'der Klimawandel',
    'zum Klimawandel',
    'hase und fuchs',
    '  doppelte   leerzeichen  ',
  ])('classifies %s as a plain phrase', (query) => {
    expect(isPlainPhraseQuery(query)).toBe(true)
  })

  it.each([
    'Hase', // single word
    '', // empty
    '[word="der"] [word="Klimawandel"]', // already CQL
    'cql:[word="x"]',
    'sim("Hase", k=5)',
    'within([word="Hase"], s)',
    'der*', // wildcard -> not a plain phrase
  ])('does not classify %s as a plain phrase', (query) => {
    expect(isPlainPhraseQuery(query)).toBe(false)
  })

  it('translates a plain phrase to the token-sequence CQL the engine supports', () => {
    expect(plainPhraseToCql('der Klimawandel')).toBe('cql:[word="der"] [word="Klimawandel"]')
    expect(plainPhraseToCql('zum Klimawandel')).toBe('cql:[word="zum"] [word="Klimawandel"]')
  })

  it('honours a non-default word attribute', () => {
    expect(plainPhraseToCql('der Klimawandel', 'token')).toBe('cql:[token="der"] [token="Klimawandel"]')
  })

  it('escapes regex metacharacters (e.g. a dot) in each token literal', () => {
    // A regex metacharacter in a surface word (a German abbreviation like
    // "z.B.") must be escaped so the CQL value (a regex) matches verbatim.
    expect(plainPhraseToCql('z.B. heute')).toBe('cql:[word="z\\.B\\."] [word="heute"]')
  })

  it('returns null for inputs that are not plain phrases', () => {
    expect(plainPhraseToCql('Hase')).toBeNull()
    expect(plainPhraseToCql('[word="der"] [word="x"]')).toBeNull()
  })
})
