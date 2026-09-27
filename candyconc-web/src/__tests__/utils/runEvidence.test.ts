import { describe, expect, it } from 'vitest'
import { createRunEvidenceV2, stableResultHash, withEvidenceQueryTraceId } from '@/utils/runEvidence'

describe('runEvidence utilities', () => {
  it('downgrades claimed full evidence when required fingerprints are missing', () => {
    const evidence = createRunEvidenceV2({
      provenance: 'frontend_actionbus',
      completeness: 'full',
      corpusId: 'demo',
      subcorpusHash: 'all',
      actionType: 'query/execute',
      resultType: 'query/execute',
      resultHash: 'result-hash',
    })

    expect(evidence.completeness).toBe('partial')
    expect(evidence.warnings).toContain('Missing index fingerprint.')
    expect(evidence.warnings).toContain('Missing metadata schema hash.')
    expect(evidence.warnings).toContain('Missing tool schema hash.')
    expect(evidence.warnings).toContain('Missing query trace id.')
  })

  it('deduplicates recalculated evidence warnings', () => {
    const evidence = createRunEvidenceV2({
      provenance: 'backend_action_result',
      corpusId: 'demo',
      subcorpusHash: 'all',
      actionType: 'query/execute',
      resultType: 'query/execute',
      warnings: ['Missing index fingerprint.'],
    })

    expect(evidence.warnings.filter((warning) => warning === 'Missing index fingerprint.')).toHaveLength(1)
  })

  it('stores explicit research scope evidence separate from legacy subcorpus hash', () => {
    const evidence = createRunEvidenceV2({
      provenance: 'frontend_actionbus',
      corpusId: 'demo',
      subcorpusHash: 'legacy-hash',
      actionType: 'query/execute',
      resultType: 'query/execute',
      researchScope: {
        corpusId: 'demo',
        scopeHash: 'scope-hash',
        scopeStatus: 'fresh',
        label: 'Subkorpus: Drama',
        docsetId: 'docset-1',
        subcorpusName: 'Drama',
        queryHash: 'query-hash',
        filterSpecHash: 'filter-spec-hash',
        metadataSchemaHash: 'schema-hash',
      },
    })

    expect(evidence.corpusFingerprint.subcorpusHash).toBe('legacy-hash')
    expect(evidence.researchScope).toMatchObject({
      corpusId: 'demo',
      scopeHash: 'scope-hash',
      scopeStatus: 'fresh',
      label: 'Subkorpus: Drama',
      docsetId: 'docset-1',
      subcorpusName: 'Drama',
      queryHash: 'query-hash',
      filterSpecHash: 'filter-spec-hash',
      metadataSchemaHash: 'schema-hash',
    })
  })

  it('ignores volatile timing fields in stable result hashes', () => {
    expect(stableResultHash({ total: 12, queryTime: 1 })).toBe(
      stableResultHash({ total: 12, queryTime: 999 })
    )
    expect(stableResultHash({ total: 12, nested: { durationMs: 1 } })).toBe(
      stableResultHash({ total: 12, nested: { durationMs: 999 } })
    )
    expect(stableResultHash({ total: 12, ts: 1, jobId: 'job-a' })).toBe(
      stableResultHash({ total: 12, ts: 999, jobId: 'job-b' })
    )
    expect(stableResultHash({ total: 12, queryTraceId: 'qtr-a' })).toBe(
      stableResultHash({ total: 12, queryTraceId: 'qtr-b' })
    )
    expect(stableResultHash({ total: 12, backendQueryTraceId: 'qtr-a' })).toBe(
      stableResultHash({ total: 12, backendQueryTraceId: 'qtr-b' })
    )
  })

  it('changes stable result hashes when evidence rows change', () => {
    expect(stableResultHash({
      total: 12,
      evidenceRows: [{ docId: 'doc-1', position: 1, match: 'Haus' }],
    })).not.toBe(stableResultHash({
      total: 12,
      evidenceRows: [{ docId: 'doc-2', position: 1, match: 'Haus' }],
    }))
  })

  it('patches queryTraceId without keeping stale missing-trace warnings', () => {
    const evidence = createRunEvidenceV2({
      provenance: 'frontend_actionbus',
      corpusId: 'demo',
      subcorpusHash: 'all',
      actionType: 'query/execute',
      resultType: 'query/execute',
      resultHash: 'result-hash',
    })

    const linked = withEvidenceQueryTraceId(evidence, 'trace-1')

    expect(linked.resultFingerprint.queryTraceId).toBe('trace-1')
    expect(linked.researchScope?.scopeHash).toBe('all')
    expect(linked.warnings).not.toContain('Missing query trace id.')
  })

  it('does not relink evidence when a later trace is observed for the same run', () => {
    const evidence = withEvidenceQueryTraceId(createRunEvidenceV2({
      provenance: 'frontend_actionbus',
      corpusId: 'demo',
      subcorpusHash: 'all',
      actionType: 'query/execute',
      resultType: 'query/execute',
      resultHash: 'result-hash',
    }), 'trace-original')

    const relinkAttempt = withEvidenceQueryTraceId(evidence, 'trace-later')

    expect(relinkAttempt.resultFingerprint.queryTraceId).toBe('trace-original')
    expect(relinkAttempt.warnings).toContain('Additional frontend trace observed without relinking evidence: trace-later')
  })
})
