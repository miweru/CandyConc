/**
 * Starter questions of the empty copilot chat fit the active corpus and the
 * interface language. Before, four fixed German questions named a research
 * project ("Klimawandel", "KI- und menschliche Texte") on every corpus.
 */
import { describe, expect, it } from 'vitest'

import { applyLocale } from '@/i18n/locale'
import { buildStarterPrompts, pickCategoryField, pickTimeField } from '@/lib/copilotStarters'

const SOTU_FIELDS = [
  { name: 'president', kind: 'string', hasString: true, stringValueCount: 12 },
  { name: 'party', kind: 'string', hasString: true, stringValueCount: 2 },
  { name: 'year', kind: 'number', hasNumber: true, hasString: false },
  { name: 'decade', kind: 'string', hasString: true, stringValueCount: 7 },
  { name: 'title', kind: 'string', hasString: true, stringValueCount: 65 },
  { name: 'source', kind: 'string', hasString: true, stringValueCount: 1 },
  { name: 'doc_id', kind: 'string', hasString: true, stringValueCount: 65 },
]

describe('copilot starter questions', () => {
  it('pick a small category and a year field from the corpus schema', () => {
    expect(pickCategoryField(SOTU_FIELDS)).toBe('party')
    expect(pickTimeField(SOTU_FIELDS)).toBe('year')
    expect(pickCategoryField([{ name: 'source', stringValueCount: 1 }])).toBeNull()
    expect(pickTimeField([{ name: 'genre', stringValueCount: 3 }])).toBeNull()
  })

  it('name the fields of the active corpus in the interface language', () => {
    applyLocale('en')
    const prompts = buildStarterPrompts({ hasPos: true, fields: SOTU_FIELDS })
    expect(prompts.map((prompt) => prompt.text)).toEqual([
      'Which words are most frequent in this corpus?',
      'Which words are typical of each value of “party”?',
      'How does the use of frequent words change over “year”?',
      'How does the query language work? Please give an example from this corpus.',
    ])
  })

  it('fall back to collocations when the corpus has no suitable metadata', () => {
    const prompts = buildStarterPrompts({ hasPos: false, fields: [] })
    expect(prompts.map((prompt) => prompt.id)).toEqual(['topWords', 'collocations', 'queryLanguage'])
    expect(prompts[1]!.text).toContain('Inhaltswort')
  })

  it('contain no research-project terms', () => {
    for (const locale of ['de', 'en'] as const) {
      applyLocale(locale)
      const text = buildStarterPrompts({ hasPos: true, fields: SOTU_FIELDS }).map((prompt) => prompt.text).join(' ')
      expect(text).not.toMatch(/Klimawandel|Nachhaltigkeit|KI-|menschliche|CQLF/)
    }
    applyLocale('de')
  })
})
