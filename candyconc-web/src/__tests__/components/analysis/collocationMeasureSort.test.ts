/**
 * COLLOC-1 (ΔP sort order) — selecting a ΔP measure must reorder the table by the
 * ACTIVE measure, not leave it in the backend's MI rank order.
 *
 * The backend returns rows already ranked by its server-side sort_by (here MI),
 * carrying a `rank` column in that MI order. The previous client sort led with
 * `rank`, so switching the measure to ΔP_nc/ΔP_cn left the table in MI order even
 * though the per-row ΔP numbers were right — reading off the "top ΔP collocate"
 * gave the wrong word. The fix makes the active-measure score primary and demotes
 * `rank` to a tiebreak, so the order tracks the selected measure.
 */
import { describe, it, expect } from 'vitest'
import { mapRowsToCollocations } from '@/components/analysis/CollocationsTab.vue'

// Two collocates. The backend ranked them by MI (rank 1 = higher MI = "alpha"),
// but their ΔP_nc ordering is INVERTED relative to MI: "beta" has the higher ΔP.
const rows = [
  { word: 'alpha', rank: 1, f: 50, mi: 9.0, delta_p_nc: 0.10, delta_p_cn: 0.30 },
  { word: 'beta', rank: 2, f: 40, mi: 4.0, delta_p_nc: 0.80, delta_p_cn: 0.05 },
]

describe('mapRowsToCollocations active-measure ordering', () => {
  it('orders by MI (rank) when MI is the selected measure', () => {
    const sorted = mapRowsToCollocations(rows, 'mi')
    expect(sorted.map((r) => r.word)).toEqual(['alpha', 'beta'])
  })

  it('reorders by ΔP_nc when ΔP_nc is selected (beta floats to the top)', () => {
    const sorted = mapRowsToCollocations(rows, 'delta_p_nc')
    // beta has the higher ΔP_nc (0.80 > 0.10) despite the lower MI rank.
    expect(sorted.map((r) => r.word)).toEqual(['beta', 'alpha'])
    expect(sorted[0].score).toBeCloseTo(0.8)
  })

  it('reorders by ΔP_cn when ΔP_cn is selected (alpha back on top)', () => {
    const sorted = mapRowsToCollocations(rows, 'delta_p_cn')
    // alpha has the higher ΔP_cn (0.30 > 0.05) — a DIFFERENT order than ΔP_nc,
    // proving the table tracks the active measure rather than a fixed rank.
    expect(sorted.map((r) => r.word)).toEqual(['alpha', 'beta'])
  })

  it('falls back to rank only as a tiebreak when scores are equal', () => {
    const tied = [
      { word: 'zulu', rank: 2, f: 10, delta_p_nc: 0.5 },
      { word: 'alfa', rank: 1, f: 10, delta_p_nc: 0.5 },
    ]
    const sorted = mapRowsToCollocations(tied, 'delta_p_nc')
    // Equal ΔP_nc -> the server rank order (alfa rank 1 before zulu rank 2) holds.
    expect(sorted.map((r) => r.word)).toEqual(['alfa', 'zulu'])
  })

  it('keeps the observed and expected values with a chi-square-cell ranking', () => {
    const sorted = mapRowsToCollocations(
      [{ word: 'beta', rank: 1, f: 5, observed: 5, expected: 4.05, chi2_cell: 0.22 }],
      'chi2_cell',
    )

    expect(sorted).toMatchObject([
      { word: 'beta', frequency: 5, observed: 5, expected: 4.05, chi2Cell: 0.22, score: 0.22 },
    ])
  })
})
