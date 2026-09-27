/**
 * A collocation card sorted by frequency shows the count once.
 *
 * Englischprobe 2026-09-27, collocate_stats with sort_by "f": every tile read
 * "251× 251.000". The score of the measure f is the co-occurrence count
 * itself, the card printed it a second time as a measure with three decimals.
 */
import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

import CollocationsRenderer from '@/components/copilot/tools/CollocationsRenderer.vue'
import { collocationRowsForDisplay } from '@/lib/collocationMeasure'
import { applyLocale } from '@/i18n/locale'

afterEach(() => applyLocale('de'))

function card(sortBy: string) {
  const rows = [
    { f: 251, rank: 1, word: 'the', f2: 19193, expected: 178.61, logdice: 8.7108, lrc: 0.0697, log_ratio: 0.4992 },
    { f: 181, rank: 2, word: 'our', f2: 5139, expected: 47.82, logdice: 10.0551, lrc: 1.4462, log_ratio: 1.9623 },
  ]
  return mount(CollocationsRenderer, {
    props: { data: collocationRowsForDisplay(rows, { wirksamesMass: sortBy }) },
    global: { stubs: { Network: true } },
  })
}

describe('collocation card', () => {
  it('sorted by f: the count once, no measure value', () => {
    applyLocale('en')
    const text = card('f').text()
    expect(text).toContain('251×')
    expect(text).not.toContain('251.000')
    expect(text).not.toContain('181.000')
  })

  it('sorted by logDice: count and measure value', () => {
    applyLocale('en')
    const text = card('logdice').text()
    expect(text).toContain('251×')
    expect(text).toContain('8.711')
  })
})
