/**
 * The German search summary puts every scope in the dative that "Suche nach"
 * requires. Before, only the similarity scope was declined ("Suche nach den
 * POS-Wert", "Suche nach alle Wortformen", "Suche nach die exakte Wortform").
 */
import { describe, expect, it } from 'vitest'

import { buildSimpleSearchSummary, createDefaultSimpleSearchState } from '@/lib/queryBuilder/simple'

describe('German search summary', () => {
  it('declines each scope after "Suche nach"', () => {
    const base = createDefaultSimpleSearchState()
    expect(buildSimpleSearchSummary({ ...base, term: 'Hase' })).toBe('Suche nach der exakten Wortform "Hase".')
    expect(buildSimpleSearchSummary({ ...base, term: 'großer Hase' })).toBe('Suche nach der Wortfolge "großer Hase".')
    expect(buildSimpleSearchSummary({ ...base, intent: 'lemma', term: 'gehen' })).toBe('Suche nach allen Wortformen zu "gehen".')
  })
})
