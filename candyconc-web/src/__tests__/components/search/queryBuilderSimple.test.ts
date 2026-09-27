import { describe, expect, it } from 'vitest'

import {
  buildSimpleSearchQuery,
  buildSimpleSearchSummary,
  canHydrateSimpleSearchQuery,
  createDefaultSimpleSearchState,
  hydrateSimpleSearchQuery,
} from '@/lib/queryBuilder/simple'

describe('queryBuilderSimple', () => {
  it('builds exact word and phrase searches as explicit token sequences', () => {
    expect(
      buildSimpleSearchQuery({
        ...createDefaultSimpleSearchState(),
        term: 'Hase',
      })
    ).toBe('[word="Hase"]')

    expect(
      buildSimpleSearchQuery({
        ...createDefaultSimpleSearchState(),
        term: 'klima wandel',
      })
    ).toBe('[word="klima"] [word="wandel"]')
  })

  it('builds descriptor-backed token attribute searches without falling back to word', () => {
    expect(
      buildSimpleSearchQuery({
        ...createDefaultSimpleSearchState(),
        term: 'NN',
        tokenAttribute: 'pos',
        tokenAttributeLabel: 'POS',
      })
    ).toBe('[pos="NN"]')

    expect(
      buildSimpleSearchQuery({
        ...createDefaultSimpleSearchState(),
        term: 'PERSON ORG',
        tokenAttribute: 'ner',
        tokenAttributeLabel: 'NER',
      })
    ).toBe('[ner="PERSON"] [ner="ORG"]')
  })

  it('builds lemma and similarity searches with optional metadata filters', () => {
    expect(
      buildSimpleSearchQuery({
        ...createDefaultSimpleSearchState(),
        intent: 'lemma',
        term: 'gehen',
        filters: { source: 'mlsum', register: 'news' },
      })
    ).toBe('where(source="mlsum" & register="news", [lemma="gehen"])')

    expect(
      buildSimpleSearchQuery({
        ...createDefaultSimpleSearchState(),
        intent: 'similar',
        term: 'Krise',
        similarityK: 30,
      })
    ).toBe('[sim="Krise" & k=30]')
  })

  it('hydrates simple-compatible CQL back into the guided composer state', () => {
    expect(hydrateSimpleSearchQuery('[lemma="gehen"]')).toMatchObject({
      intent: 'lemma',
      term: 'gehen',
      similarityK: 20,
      filters: {},
    })

    expect(hydrateSimpleSearchQuery('where(source="mlsum" & register="news", [word="klima"] [word="wandel"])')).toMatchObject({
      intent: 'exact',
      term: 'klima wandel',
      filters: { source: 'mlsum', register: 'news' },
    })

    expect(hydrateSimpleSearchQuery('"Haus"')).toMatchObject({
      intent: 'exact',
      term: 'Haus',
    })
  })

  it('hydrates single-attribute token sequences beyond word and lemma', () => {
    expect(hydrateSimpleSearchQuery('[pos="NN"]')).toMatchObject({
      intent: 'exact',
      term: 'NN',
      tokenAttribute: 'pos',
      tokenAttributeLabel: 'POS',
    })

    expect(hydrateSimpleSearchQuery('where(register="news", [ner="PERSON"])')).toMatchObject({
      intent: 'exact',
      term: 'PERSON',
      tokenAttribute: 'ner',
      tokenAttributeLabel: 'NER',
      filters: { register: 'news' },
    })
  })

  it('distinguishes supported quick searches from real studio-only queries', () => {
    expect(canHydrateSimpleSearchQuery('[sim="Hase" & k=20]')).toBe(true)
    expect(canHydrateSimpleSearchQuery('[pos="NN"]')).toBe(true)
    expect(canHydrateSimpleSearchQuery('within(<s>, [word="Haus"])')).toBe(false)
    expect(canHydrateSimpleSearchQuery('[lemma="Haus" & pos="NN"]')).toBe(false)
  })

  it('explains the quick search in plain language', () => {
    expect(
      buildSimpleSearchSummary({
        ...createDefaultSimpleSearchState(),
        intent: 'similar',
        term: 'Krise',
        similarityK: 15,
        filters: { source: 'mlsum', register: '' },
      })
    ).toBe('Suche nach ähnlichen Begriffen zu "Krise" (Top 15), eingeschränkt auf source "mlsum".')

    expect(
      buildSimpleSearchSummary({
        ...createDefaultSimpleSearchState(),
        term: 'NN',
        tokenAttribute: 'pos',
        tokenAttributeLabel: 'POS',
      })
    ).toBe('Suche nach dem POS-Wert "NN".')
  })
})
