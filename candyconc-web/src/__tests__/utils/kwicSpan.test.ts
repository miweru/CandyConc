import { describe, expect, it } from 'vitest'

import { kwicSpanDisplay } from '@/utils/kwicSpan'

// erprobung B15: a two-word match showed only its first token in the match
// column, the second token sat in the right context.
describe('kwicSpanDisplay', () => {
  it('moves the right match token into the match column', () => {
    const out = kwicSpanDisplay({
      left: 'welche Folge der',
      match: 'edlen',
      right: 'Freiheit ist ; Alles',
      matchOffsets: [1],
    })
    expect(out.match).toBe('edlen Freiheit')
    expect(out.left).toBe('welche Folge der')
    expect(out.right).toBe('ist ; Alles')
    expect(out.matchOffsets).toEqual([])
  })

  it('moves left match tokens and shifts collocate offsets', () => {
    const out = kwicSpanDisplay({
      left: 'of the common',
      match: 'people',
      right: '. \n In the war',
      matchOffsets: [-2, -1],
      collocateOffsets: [-3, 4],
    })
    expect(out.match).toBe('the common people')
    expect(out.left).toBe('of')
    expect(out.right).toBe('. \n In the war')
    // -3 was "of": one token left of the span start.
    expect(out.collocateOffsets).toEqual([-1, 4])
  })

  it('keeps a gap token highlighted in the context', () => {
    const out = kwicSpanDisplay({
      left: 'a b',
      match: 'x',
      right: 'y z w',
      matchOffsets: [1, 3],
    })
    expect(out.match).toBe('x y')
    expect(out.right).toBe('z w')
    expect(out.matchOffsets).toEqual([2])
  })

  it('leaves a single-token match untouched', () => {
    const row = { left: 'the cause of', match: 'freedom', right: 'and peace', collocateOffsets: [2] }
    const out = kwicSpanDisplay(row)
    expect(out).toMatchObject({ left: row.left, match: row.match, right: row.right, collocateOffsets: [2] })
  })
})
