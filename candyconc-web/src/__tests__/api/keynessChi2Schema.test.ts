import { describe, expect, it } from 'vitest'

import { RawKeynessRowSchema, KeynessResponseSchema } from '@/api/schemas'

/**
 * T14 wire-contract gate: the keyness row schema must accept the full 2x2
 * Pearson chi-square (`chi2`) and its signed variant (`chi2_signed`) the r7
 * D-routes/D-server emit. The canonical per-cell statistic is always present.
 */
describe('RawKeynessRowSchema — chi2 / chi2_signed (T14)', () => {
  it('parses a row carrying the full 2x2 chi-square fields', () => {
    const parsed = RawKeynessRowSchema.parse({
      word: 'Mensch',
      chi2: 42.5,
      chi2_signed: -42.5,
      chi2_cell: 3.1,
      chi2_cell_signed: -3.1,
      ll_signed: -120.0,
      direction: 'reference',
    })
    expect(parsed.chi2).toBe(42.5)
    expect(parsed.chi2_signed).toBe(-42.5)
    // The per-cell chi2 stays distinct from the full statistic.
    expect(parsed.chi2_cell).toBe(3.1)
  })

  it('accepts null chi2 values defensively', () => {
    const parsed = RawKeynessRowSchema.parse({ word: 'x', chi2_cell: null, chi2: null, chi2_signed: null })
    expect(parsed.chi2).toBeNull()
    expect(parsed.chi2_signed).toBeNull()
  })

  it('parses a row without the optional full 2x2 fields', () => {
    const parsed = RawKeynessRowSchema.parse({ word: 'y', chi2_cell: 3.1, ll: 5, ll_signed: 5 })
    expect(parsed.chi2).toBeUndefined()
    expect(parsed.chi2_signed).toBeUndefined()
  })

  it('round-trips chi2 through the full keyness response envelope', () => {
    const res = KeynessResponseSchema.parse({
      rows: [
        { word: 'a', chi2_cell: 2.5, chi2: 10, chi2_signed: 10 },
        { word: 'b', chi2_cell: 1, chi2: 4, chi2_signed: -4 },
      ],
      method: { family: 'keyness' },
    })
    expect(res.rows).toHaveLength(2)
    expect(res.rows[0].chi2).toBe(10)
    expect(res.rows[1].chi2_signed).toBe(-4)
    expect(res.method?.family).toBe('keyness')
  })

  it('rejects a retired mi2 response instead of treating it as an empty score', () => {
    expect(() => RawKeynessRowSchema.parse({ word: 'alt', mi2: 3.1 })).toThrow()
  })
})
