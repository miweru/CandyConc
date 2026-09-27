import { describe, expect, it } from 'vitest'

import {
  analysisJobRowsReadiness,
  analysisResultAvailabilityLabel,
} from '@/lib/productOperationReadiness'

describe('productOperationReadiness', () => {
  it('marks discarded analysis rows as terminal but not loadable', () => {
    const readiness = analysisJobRowsReadiness({
      status: 'done',
      result_available: false,
      result_discarded: true,
      rows_state: 'discarded',
      result_warnings: ['Ergebnis zu groß für Job-Speicher.'],
    })

    expect(readiness).toMatchObject({
      readiness: 'Ergebnis verworfen',
      rowsState: 'discarded',
      rowsLoadable: false,
      blockReason: 'Analyse abgeschlossen, aber das Ergebnis wurde nicht im Job gespeichert.',
      warnings: ['Ergebnis zu groß für Job-Speicher.'],
    })
  })

  it('requires explicit availability before loading completed analysis rows', () => {
    const readiness = analysisJobRowsReadiness({
      status: 'done',
      result_available: true,
      rows_state: 'available',
    })

    expect(readiness.rowsLoadable).toBe(true)
    expect(readiness.blockReason).toBeNull()
    expect(analysisResultAvailabilityLabel({
      job_id: 'analysis-ready',
      status: 'done',
      result_available: true,
      rows_state: 'available',
    })).toBe('Ergebnis abrufbar')
  })

})
