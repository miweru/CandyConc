import { describe, expect, it } from 'vitest'

import { cqlLiteral, frequencyRowQuery, ngramRowQuery, wordSketchRowQuery } from '@/utils/backPathQuery'

describe('concordance queries behind analysis rows', () => {
  it('folds a word row and escapes regex metacharacters', () => {
    expect(frequencyRowQuery({ item: 'U.S.', groupBy: 'word', caseFolded: true }))
      .toBe('cql:[word="U\\.S\\."%c]')
  })

  it('carries the POS prefix of the list as a prefix condition', () => {
    expect(frequencyRowQuery({ item: 'freedom', groupBy: 'word', posPrefix: 'NOUN', caseFolded: true }))
      .toBe('cql:[word="freedom"%c & pos="NOUN.*"]')
  })

  it('uses the lemma column and the exact tag for POS rows', () => {
    expect(frequencyRowQuery({ item: 'Freiheit', groupBy: 'lemma', caseFolded: true }))
      .toBe('cql:[lemma="Freiheit"%c]')
    expect(frequencyRowQuery({ item: 'NOUN', groupBy: 'pos', caseFolded: false }))
      .toBe('cql:[pos="NOUN"]')
  })

  it('keeps an n-gram inside one document, across sentences', () => {
    expect(ngramRowQuery('u. s. w.')).toBe('cql:within(<doc>, [word="u\\."] [word="s\\."] [word="w\\."])')
  })

  it('escapes quotes and backslashes', () => {
    expect(cqlLiteral('a"b\\c')).toBe('a\\"b\\\\c')
  })

  it('opens a word sketch row as the dependency search of its pairs', () => {
    // Node is head: freedom >amod political (sotu_en: 5 pairs, 5 hits).
    expect(wordSketchRowQuery('freedom', 'amod', 'political'))
      .toEqual({ term: '[word=freedom] >amod [word=political]', exact: true })
    // Node is dependent: the collocate is the head (defend >dobj freedom, 12).
    expect(wordSketchRowQuery('freedom', 'dobj_rev', 'defend'))
      .toEqual({ term: '[word=defend] >dobj [word=freedom]', exact: true })
    // Spelling stays exact, a collocate that is a query keyword stays a word.
    expect(wordSketchRowQuery('is', 'prep', 'Within'))
      .toEqual({ term: '[word=is] >prep [word=Within]', exact: true })
    expect(wordSketchRowQuery('U.S.', 'compound_rev', 'policy'))
      .toEqual({ term: '[word=policy] >compound [word=U.S.]', exact: true })
  })

  it('writes a word with a quotation mark as a plain word in front', () => {
    // [word=n't] would turn the query into the query language.
    expect(wordSketchRowQuery('do', 'neg', "n't"))
      .toEqual({ term: "n't <neg [word=do]", exact: false })
    expect(wordSketchRowQuery("Sappho's", 'nk', 'Lied'))
      .toEqual({ term: "Sappho's >nk [word=Lied]", exact: false })
    expect(wordSketchRowQuery("gehe'n", 'oc_rev', "z'weg'n"))
      .toEqual({ term: "z'weg'n >oc gehe'n", exact: false })
  })

  it('gives no query for a word the dependency search cannot hold', () => {
    expect(wordSketchRowQuery('freedom', 'amod', '[laughter]--but')).toBeNull()
    expect(wordSketchRowQuery('freedom', 'amod', 'men"--the')).toBeNull()
    expect(wordSketchRowQuery('freedom', '_rev', 'defend')).toBeNull()
  })
})
