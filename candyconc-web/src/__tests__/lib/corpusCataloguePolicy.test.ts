import { describe, expect, it } from 'vitest'

import {
  canActivateCorpusWithPartialImportAcknowledgement,
  canActivateCorpusSummary,
  canUnregisterCorpusSummary,
  corpusActivationBlockReason,
  corpusRequiresPartialImportAcknowledgement,
  corpusUnregisterBlockReason,
} from '@/lib/corpusCataloguePolicy'
import type { CorpusSummary } from '@/api/client'

function corpus(overrides: Partial<CorpusSummary> = {}): CorpusSummary {
  return {
    name: 'demo',
    path: '/corpora/demo',
    status: 'ready',
    source: 'registry',
    active: false,
    token_count: 10,
    doc_count: 1,
    import_mode: 'parquet',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    ...overrides,
  }
}

describe('corpus catalogue UI policy', () => {
  it('allows activation only for catalogue-visible ready corpora', () => {
    expect(canActivateCorpusSummary(corpus({ status: 'ready' }))).toBe(true)
    expect(canActivateCorpusSummary(corpus({ status: 'incomplete', status_reason: 'Manifest fehlt' }))).toBe(false)
    expect(corpusActivationBlockReason(corpus({ status: 'corrupt' }))).toContain('Nur bereite Korpora')
    expect(corpusActivationBlockReason(null)).toContain('noch nicht im Katalog')
  })

  it('keeps a partial import out of generic activation until it is explicitly acknowledged', () => {
    const partial = corpus({
      partial_input: true,
      rejected_rows: 2,
      import_warnings: ['2 Eingabezeilen wurden verworfen.'],
    })

    expect(corpusRequiresPartialImportAcknowledgement(partial)).toBe(true)
    expect(canActivateCorpusSummary(partial)).toBe(false)
    expect(corpusActivationBlockReason(partial)).toContain('Teilimport')
    expect(canActivateCorpusWithPartialImportAcknowledgement(partial, false)).toBe(false)
    expect(canActivateCorpusWithPartialImportAcknowledgement(partial, true)).toBe(true)
  })

  it('allows unregister only for non-default registry entries', () => {
    expect(canUnregisterCorpusSummary(corpus({ name: 'registered', source: 'registry' }))).toBe(true)
    expect(canUnregisterCorpusSummary(corpus({ name: 'default', source: 'registry' }))).toBe(false)
    expect(canUnregisterCorpusSummary(corpus({ name: 'managed', source: 'managed' }))).toBe(false)
    expect(corpusUnregisterBlockReason(corpus({ name: 'managed', source: 'managed' }))).toContain('Nur Registry-Einträge')
  })
})
