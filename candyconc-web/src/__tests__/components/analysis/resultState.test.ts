import { describe, expect, it } from 'vitest'
import {
  analysisCompletenessHeaderLines,
  analysisCompletenessNotice,
  completenessStateFromJobRows,
} from '@/components/analysis/resultState'

describe('analysis result completeness state', () => {
  it('keeps available rows separate from the full candidate pool', () => {
    const state = completenessStateFromJobRows(
      {
        rows: Array.from({ length: 200 }, (_, i) => ({ i })),
        total_rows: 200,
        row_limit: 200,
        total_candidates: 1250,
        truncated: true,
      },
      { loadedRows: 200 },
    )

    expect(state.availableRows).toBe(200)
    expect(state.loadedRows).toBe(200)
    expect(state.rowLimit).toBe(200)
    expect(state.totalCandidates).toBe(1250)
    expect(state.truncated).toBe(true)
  })

  it('renders a prominent warning for capped scientific rankings', () => {
    const notice = analysisCompletenessNotice({ rowLimit: 500, totalCandidates: 2800, truncated: true }, 'Keyness-Liste')

    expect(notice).toContain('Top 500 von 2.800 Kandidaten')
    expect(notice).toContain('Sortierung und Export')
  })

  it('reports every loaded page instead of only the page size', () => {
    const notice = analysisCompletenessNotice({
      rowLimit: 500,
      totalCandidates: 1250,
      availableRows: 1001,
      loadedRows: 1001,
      truncated: true,
    }, 'Keyness-Liste')

    expect(notice).toContain('Top 1.001 von 1.250 Kandidaten')
  })

  it('writes CSV provenance fields instead of relying on UI-only warnings', () => {
    const lines = analysisCompletenessHeaderLines(
      {
        rowLimit: 200,
        totalCandidates: 1250,
        availableRows: 200,
        loadedRows: 200,
        truncated: true,
      },
      'CollocationsResult',
    )

    expect(lines).toEqual([
      '# CollocationsResult.truncated: true',
      '# CollocationsResult.row_limit: 200',
      '# CollocationsResult.total_candidates: 1250',
      '# CollocationsResult.available_rows: 200',
      '# CollocationsResult.loaded_rows: 200',
    ])
  })
})
