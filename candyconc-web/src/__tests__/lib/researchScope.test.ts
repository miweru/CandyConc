import { describe, expect, it } from 'vitest'

import {
  buildResearchScopeEvidence,
  ensureUsableResearchScope,
  executionScopeForApi,
  researchScopeMetaPairs,
} from '@/lib/researchScope'

describe('research scope policy', () => {
  it('blocks dirty active docsets for backend research operations', () => {
    const result = ensureUsableResearchScope({
      activeCorpus: 'demo',
      hasActiveDocset: true,
      activeDocsetId: 'old-docset',
      isDirty: true,
      activeScopeStale: false,
      activeScopeWarning: null,
      activeScopeResolvedAt: 1710000000000,
      stats: { docCount: 2, tokenCount: 200, refDocCount: 0 },
    }, { operation: 'Frequenzanalyse' })

    expect(result.ok).toBe(false)
    expect(result.docsetId).toBeUndefined()
    expect(result.message).toContain('angewendeten Subkorpus')
    expect(result.evidence.status).toBe('dirty')
  })

  it('keeps stale and generic filter evidence in reproducibility metadata', () => {
    const source = {
      activeCorpus: 'demo',
      hasActiveDocset: true,
      activeDocsetId: 'fresh-docset',
      isDirty: false,
      activeScopeStale: true,
      activeScopeWarning: 'Schema geändert',
      activeScopeResolvedAt: 1710000000000,
      metaSchemaHash: 'schema-current',
      activeFilterSpec: { year: { op: '>=', value: 2020 }, genre: ['news'] },
      stats: { docCount: 9, tokenCount: 900, refDocCount: 0 },
    } as const

    const evidence = buildResearchScopeEvidence(source)
    const pairs = Object.fromEntries(researchScopeMetaPairs(source))

    expect(evidence.status).toBe('stale')
    expect(evidence.docsetId).toBe('fresh-docset')
    expect(pairs.ScopeStatus).toBe('stale')
    expect(pairs.ScopeWarning).toBe('Schema geändert')
    expect(pairs.ScopeMetadataSchemaHash).toBe('schema-current')
    expect(pairs.ScopeFilterSpec).toContain('year')
    expect(pairs.ScopeFilterSpec).toContain('genre')
    expect(pairs.ScopeHash).toMatch(/^[0-9a-f]{8}$/)
    expect(pairs.ScopeHash).toBe(evidence.scopeHash)
  })

  it('includes query-derived docset identity in the durable scope hash', () => {
    const base = {
      activeCorpus: 'demo',
      hasActiveDocset: true,
      activeDocsetId: 'runtime-docset',
      isDirty: false,
      activeFilterSpec: { genre: ['news'] },
      metaSchemaHash: 'schema-current',
      stats: { docCount: 4, tokenCount: 400, refDocCount: 0 },
    } as const

    const first = buildResearchScopeEvidence({ ...base, lastQuery: 'Hase' })
    const second = buildResearchScopeEvidence({ ...base, lastQuery: 'Igel' })

    expect(first.scopeHash).toMatch(/^[0-9a-f]{8}$/)
    expect(second.scopeHash).toMatch(/^[0-9a-f]{8}$/)
    expect(first.scopeHash).not.toBe(second.scopeHash)
  })

  it('records corpus execution when an API request omits the active docset', () => {
    const source = {
      activeCorpus: 'demo',
      hasActiveDocset: true,
      activeDocsetId: 'runtime-docset',
      activeSubcorpusName: 'Arbeitskorpus',
      isDirty: true,
      activeScopeStale: false,
      activeScopeWarning: null,
      activeScopeResolvedAt: 1710000000000,
      metaSchemaHash: 'schema-current',
      activeFilterSpec: { genre: ['news'] },
      lastQuery: 'alte Query',
    } as const

    const scope = executionScopeForApi(source, 'demo', undefined)

    expect(scope).toMatchObject({
      corpusId: 'demo',
      scopeStatus: 'corpus',
      label: 'Gesamtkorpus',
      metadataSchemaHash: 'schema-current',
    })
    expect(scope.docsetId).toBeUndefined()
    expect(scope.subcorpusName).toBeUndefined()
  })

  it('records fresh active docset execution when that docset is sent to the API', () => {
    const source = {
      activeCorpus: 'demo',
      hasActiveDocset: true,
      activeDocsetId: 'runtime-docset',
      activeSubcorpusName: 'Arbeitskorpus',
      isDirty: false,
      activeScopeStale: false,
      activeScopeWarning: null,
      activeScopeResolvedAt: 1710000000000,
      metaSchemaHash: 'schema-current',
      activeFilterSpec: { genre: ['news'] },
      lastQuery: 'Hase',
    } as const

    const scope = executionScopeForApi(source, 'demo', 'runtime-docset')

    expect(scope).toMatchObject({
      corpusId: 'demo',
      scopeStatus: 'fresh',
      docsetId: 'runtime-docset',
      subcorpusName: 'Arbeitskorpus',
      metadataSchemaHash: 'schema-current',
    })
    expect(scope.scopeHash).toMatch(/^[0-9a-f]{8}$/)
  })
})
