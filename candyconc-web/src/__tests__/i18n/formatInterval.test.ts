import { afterEach, describe, expect, it } from 'vitest'

import { formatInterval } from '@/i18n/format'
import { applyLocale } from '@/i18n/locale'

// "[0,5, 2,1]" reads as four numbers in German, where the comma separates
// decimals. Keyness (table and copilot renderer), the trend table and the
// trend chart tooltip wrote their confidence intervals that way.

afterEach(() => {
  applyLocale('de')
})

describe('formatInterval', () => {
  it('joins the bounds with a word in German', () => {
    expect(formatInterval(0.5, 2.1, 1)).toBe('0,5 bis 2,1')
    expect(formatInterval(210.12, 428.567, 2)).toBe('210,12 bis 428,57')
    expect(formatInterval(-1.25, -0.4, 2)).toBe('-1,25 bis -0,40')
  })

  it('joins the bounds with a word in English', () => {
    applyLocale('en')
    expect(formatInterval(0.5, 2.1, 1)).toBe('0.5 to 2.1')
    expect(formatInterval(1234.5, 2345.25, 2)).toBe('1,234.50 to 2,345.25')
  })

  it('uses neither brackets nor semicolons', () => {
    for (const lang of ['de', 'en'] as const) {
      applyLocale(lang)
      expect(formatInterval(0.5, 2.1, 1)).not.toMatch(/[[\];]/)
    }
  })
})
