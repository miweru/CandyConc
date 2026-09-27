import { describe, expect, it } from 'vitest'

import { buildCoKwicQuery, coKwicWindowState, mapCoKwicHits, parseCoKwicQuery } from '@/utils/coKwic'
import { kwicHitSpan } from '@/lib/kwicCitation'

describe('Co-KWIC query', () => {
  it('keeps the lemma counting attribute through build and parse', () => {
    const term = buildCoKwicQuery({ term: 'Regen', collocate: 'stark', window: 5, attribute: 'lemma' })
    expect(term).toContain('attribute=lemma')
    expect(parseCoKwicQuery(term)).toMatchObject({ term: 'Regen', collocates: ['stark'], attribute: 'lemma' })
  })

  it('leaves the word default unchanged', () => {
    const term = buildCoKwicQuery({ term: 'freedom', collocate: 'peace', window: 5 })
    expect(term).toBe('co(term="freedom", collocate="peace", window=5, within_sentence=true)')
    expect(parseCoKwicQuery(term)?.attribute).toBe('word')
  })

  it('treats the route total as exact and only the window as partial', () => {
    expect(coKwicWindowState({ next_offset: 300, truncated: true })).toMatchObject({
      totalKnown: true,
      totalPartial: true,
      hasMore: true,
    })
  })

  it('keeps the other tokens of a node hit, so the rows name the whole hit', () => {
    // A row of /analysis/collocates/kwic for cql:[lemma="political"] [lemma="freedom"].
    const [row] = mapCoKwicHits({
      hits: [{
        position: 1103,
        left: 'search of religious tolerance ,',
        match: 'political',
        right: 'freedom and economic opportunity .',
        doc_id: '0',
        collocate_offsets: [3],
        match_offsets: [1],
      }],
    })
    expect(row!.matchOffsets).toEqual([1])
    expect(kwicHitSpan(row!)).toEqual({ match: 'political freedom', matchStart: 1103, matchEnd: 1104 })
  })
})
