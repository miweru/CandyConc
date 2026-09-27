import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  clearAllData,
  createRunRecord,
  exportRunsAsJson,
  exportRunsAsCsv,
  exportTracesAsCsv,
  getRunRecord,
  loadRunRecords,
  recordBackendActionResultRun,
} from '@/services/runRecordService'
import { traceHistory } from '@/actions/traceRecorder'

const STORAGE_KEY_RUNS = 'candyconc_run_records'

// localStorage is an inert vi.fn() mock in the test setup; feed loadRunRecords
// through getItem so the persisted-runs parsing path is exercised for real.
function seedPersistedRuns(payload: unknown): void {
  vi.mocked(window.localStorage.getItem).mockImplementation(
    (key: string) => key === STORAGE_KEY_RUNS ? JSON.stringify(payload) : null
  )
}

describe('runRecordService legacy run compatibility', () => {
  beforeEach(() => {
    vi.mocked(window.localStorage.getItem).mockReset()
    vi.mocked(window.localStorage.getItem).mockReturnValue(null)
    clearAllData()
  })

  it('normalizes legacy persisted runs with missing payload and corpus metadata', () => {
    seedPersistedRuns({
      version: '0.9',
      runs: [
        {
          runId: 'legacy_run',
          ts: 123,
          actionType: 'analysis/frequency',
          resultRef: {
            type: 'analysis/frequency',
            rows: 4,
          },
        },
      ],
    })

    loadRunRecords()

    const run = getRunRecord('legacy_run')
    expect(run?.kind).toBe('analysis')
    expect(run?.actionPayload).toEqual({})
    expect(run?.corpus).toEqual({ corpusId: 'unknown', subcorpusHash: '' })
    expect(run?.summary).toBe('analysis/frequency')
    expect(run?.resultRef.rows).toBe(4)
    expect(run?.schemaVersion).toBe('2.0')
    expect(run?.evidence).toMatchObject({
      provenance: 'imported_legacy',
      completeness: 'legacy_partial',
      corpusFingerprint: { corpusId: 'unknown', subcorpusHash: '' },
      researchScope: { corpusId: 'unknown', scopeHash: '', scopeStatus: 'unknown' },
      resultFingerprint: { resultType: 'analysis/frequency', rows: 4 },
    })
    expect(run?.evidence?.warnings).toContain('Legacy RunRecord without V2 evidence metadata.')
  })

  it('exports run request ids to keep run and trace CSV joinable', () => {
    const csv = exportRunsAsCsv([
      {
        runId: 'run-1',
        requestId: 'req-1',
        ts: 1,
        kind: 'query',
        actionType: 'query/execute',
        actionPayload: { term: 'Zeit' },
        corpus: { corpusId: 'demo', subcorpusHash: 'all' },
        resultRef: { type: 'query/execute', hash: 'hash-1', rows: 12 },
        summary: 'Query',
      },
    ])

    expect(csv.split('\n')[0]).toContain('run_id,request_id,timestamp')
    expect(csv.split('\n')[0]).toContain('research_scope_hash,research_scope_status')
    expect(csv.split('\n')[0]).toContain('evidence_provenance,evidence_completeness')
    expect(csv).toContain('run-1,req-1,')
  })

  it('loads persisted backend-owned run records with request and run ids intact', () => {
    seedPersistedRuns([
      {
        runId: 'backend-run-imported',
        requestId: 'backend-req-imported',
        ts: 456,
        kind: 'analysis',
        actionType: 'analysis/collocations',
        actionPayload: { term: 'Liebe', windowSize: 5 },
        corpus: { corpusId: 'demo-corpus', subcorpusHash: 'all' },
        resultRef: {
          type: 'analysis/collocations',
          hash: 'backend-result-hash',
          rows: 7,
        },
        summary: 'Backend collocations',
      },
    ])

    loadRunRecords()

    const run = getRunRecord('backend-run-imported')
    expect(run).toMatchObject({
      runId: 'backend-run-imported',
      requestId: 'backend-req-imported',
      actionType: 'analysis/collocations',
      schemaVersion: '2.0',
      evidence: expect.objectContaining({
        provenance: 'imported_legacy',
        completeness: 'legacy_partial',
      }),
      resultRef: {
        type: 'analysis/collocations',
        hash: 'backend-result-hash',
        rows: 7,
      },
    })
    expect(exportRunsAsCsv([run!])).toContain('backend-run-imported,backend-req-imported,')
  })

  it('creates backend-owned run records from result requestId and runId and exports request_id', () => {
    const run = createRunRecord(
      { type: 'query/execute', payload: { term: 'Friede' } } as never,
      {
        success: true,
        source: 'copilot',
        requestId: 'backend-req-created',
        runId: 'backend-run-created',
        data: { total: 3 },
      },
      'demo-corpus',
      'all',
      'query-hash'
    )

    expect(getRunRecord('backend-run-created')).toEqual(run)
    expect(run).toMatchObject({
      runId: 'backend-run-created',
      requestId: 'backend-req-created',
      kind: 'query',
      actionType: 'query/execute',
      actionPayload: { term: 'Friede' },
      schemaVersion: '2.0',
      evidence: expect.objectContaining({
        provenance: 'frontend_actionbus',
        completeness: 'partial',
        resultFingerprint: expect.objectContaining({
          resultType: 'query/execute',
          rows: 3,
        }),
      }),
      resultRef: {
        type: 'query/execute',
        rows: 3,
      },
    })

    const csv = exportRunsAsCsv([run])
    expect(csv.split('\n')[0]).toContain('run_id,request_id,timestamp')
    expect(csv).toContain('backend-run-created,backend-req-created,')
    expect(csv).toContain(',2.0,frontend_actionbus,partial,')
  })

  it('records array result row counts for frontend action runs', () => {
    const run = createRunRecord(
      { type: 'analysis/frequency', payload: { groupBy: 'word' } } as never,
      {
        success: true,
        source: 'copilot',
        requestId: 'array-req',
        runId: 'array-run',
        data: [{ term: 'a' }, { term: 'b' }],
      },
      'demo-corpus',
      'all'
    )

    expect(run.resultRef.rows).toBe(2)
    expect(run.evidence.resultFingerprint.rows).toBe(2)
  })

  it('preserves frontend evidence fingerprints in RunRecord CSV export', () => {
    const run = createRunRecord(
      { type: 'query/execute', payload: { term: 'Friede' } } as never,
      {
        success: true,
        source: 'user',
        data: { total: 1 },
      },
      'demo-corpus',
      'all',
      undefined,
      {
        runId: 'fingerprinted-run',
        requestId: 'fingerprinted-request',
        indexFingerprint: 'index-fp',
        metadataSchemaHash: 'meta-fp',
        backendQueryTraceId: 'qtr-fp',
      }
    )

    expect(run.evidence.corpusFingerprint.indexFingerprint).toBe('index-fp')
    expect(run.evidence.corpusFingerprint.metadataSchemaHash).toBe('meta-fp')
    expect(run.evidence.resultFingerprint.backendQueryTraceId).toBe('qtr-fp')
    expect(run.evidence.warnings).not.toContain('Missing index fingerprint.')
    expect(run.evidence.warnings).not.toContain('Missing metadata schema hash.')

    const csv = exportRunsAsCsv([run])
    expect(csv).toContain('query_trace_id,backend_query_trace_id')
    expect(csv).toContain('index-fp,meta-fp,,')
    expect(csv).toContain(',qtr-fp,')
  })

  it('preserves explicit research scope evidence in RunRecord CSV export', () => {
    const run = createRunRecord(
      { type: 'analysis/frequency', payload: { groupBy: 'word' } } as never,
      {
        success: true,
        source: 'user',
        data: { rows: [{ term: 'Zeit' }] },
      },
      'demo-corpus',
      'legacy-scope',
      'query-hash',
      {
        runId: 'scope-run',
        requestId: 'scope-request',
        metadataSchemaHash: 'meta-fp',
        researchScope: {
          corpusId: 'demo-corpus',
          scopeHash: 'scope-hash',
          scopeStatus: 'fresh',
          label: 'Subkorpus: Drama',
          docsetId: 'docset-1',
          subcorpusName: 'Drama',
          filterSpecHash: 'filter-spec-hash',
          metadataSchemaHash: 'meta-fp',
        },
      }
    )

    expect(run.evidence.researchScope).toMatchObject({
      corpusId: 'demo-corpus',
      scopeHash: 'scope-hash',
      scopeStatus: 'fresh',
      label: 'Subkorpus: Drama',
      docsetId: 'docset-1',
      subcorpusName: 'Drama',
      queryHash: 'query-hash',
      filterSpecHash: 'filter-spec-hash',
      metadataSchemaHash: 'meta-fp',
    })

    const csv = exportRunsAsCsv([run])
    expect(csv.split('\n')[0]).toContain('research_scope_hash,research_scope_status')
    expect(csv).toContain('legacy-scope,scope-hash,fresh,Subkorpus: Drama,docset-1,Drama,query-hash,filter-spec-hash,meta-fp')
  })

  it('exports V2 JSON package version and preserves run evidence', () => {
    const run = createRunRecord(
      { type: 'query/execute', payload: { term: 'Friede' } } as never,
      {
        success: true,
        source: 'copilot',
        requestId: 'json-req',
        runId: 'json-run',
        data: { total: 2 },
      },
      'demo-corpus',
      'all'
    )

    const exported = JSON.parse(exportRunsAsJson([run], { pretty: false }))
    expect(exported.version).toBe('2.0')
    expect(exported.runs[0]).toMatchObject({
      schemaVersion: '2.0',
      evidence: {
        provenance: 'frontend_actionbus',
        completeness: 'partial',
      },
    })
  })

  it('mirrors backend-owned action_result runs without ActionBus execution state', () => {
    const run = recordBackendActionResultRun(
      {
        requestId: 'backend-req-result',
        ok: true,
        runId: 'backend-run-result',
        resultSummary: 'Backend-owned query',
        resultRef: { type: 'query/execute', hash: 'backend-hash', rows: 8 },
        corpus: { corpusId: 'backend-corpus', subcorpusHash: 'backend-scope' },
        queryHash: 'backend-query-hash',
      },
      {
        requestId: 'backend-req-result',
        type: 'query/execute',
        payload: { term: 'Macht' },
      },
      { corpusId: 'demo-corpus', subcorpusHash: 'scope-hash' }
    )

    expect(run).toMatchObject({
      runId: 'backend-run-result',
      requestId: 'backend-req-result',
      kind: 'query',
      actionType: 'query/execute',
      actionPayload: { term: 'Macht' },
      corpus: { corpusId: 'backend-corpus', subcorpusHash: 'backend-scope' },
      queryHash: 'backend-query-hash',
      resultRef: { type: 'query/execute', hash: 'backend-hash', rows: 8 },
      summary: 'Backend-owned query',
      schemaVersion: '2.0',
      evidence: expect.objectContaining({
        provenance: 'backend_action_result',
        completeness: 'partial',
        corpusFingerprint: expect.objectContaining({
          corpusId: 'backend-corpus',
          subcorpusHash: 'backend-scope',
          queryHash: 'backend-query-hash',
        }),
        researchScope: expect.objectContaining({
          corpusId: 'backend-corpus',
          scopeHash: 'backend-scope',
          scopeStatus: 'unknown',
          queryHash: 'backend-query-hash',
        }),
        resultFingerprint: expect.objectContaining({
          resultHash: 'backend-hash',
          rows: 8,
        }),
      }),
    })
    expect(run?.evidence?.warnings).toContain('Backend-owned SSE mirror; not authoritative backend history sync.')
    expect(getRunRecord('backend-run-result')).toEqual(run)
    expect(traceHistory.value).toEqual([
      expect.objectContaining({
        actor: 'backend',
        source: 'backend',
        requestId: 'backend-req-result',
        actionType: 'query/execute',
        ok: true,
        linkRunId: 'backend-run-result',
      }),
    ])
    expect(traceHistory.value[0]).not.toHaveProperty('policyDecision')
    expect(traceHistory.value[0]?.policyReason).toContain('without local ActionBus execution')
    expect(traceHistory.value[0]).not.toHaveProperty('uiStateHashBefore')
    expect(traceHistory.value[0]).not.toHaveProperty('uiStateHashAfter')
  })

  it('does not treat backend result summaries as canonical result hashes', () => {
    const run = recordBackendActionResultRun(
      {
        requestId: 'backend-req-summary-only',
        ok: true,
        runId: 'backend-run-summary-only',
        resultSummary: 'Only a human-readable summary',
      },
      {
        requestId: 'backend-req-summary-only',
        type: 'analysis/frequency',
        payload: { groupBy: 'word' },
      }
    )

    expect(run?.resultRef.hash).toBeUndefined()
    expect(run?.evidence.resultFingerprint.resultHash).toBeUndefined()
    expect(run?.evidence.researchScope).toMatchObject({
      corpusId: 'backend-owned',
      scopeHash: '',
      scopeStatus: 'unknown',
    })
    expect(run?.evidence.warnings).toContain('Missing canonical result hash.')
    expect(run?.evidence.warnings).toContain(
      'Backend execution scope unavailable without backend V2 evidence; mirrored scope is unknown.'
    )
  })

  it('preserves backend-provided V2 evidence when mirroring action_result runs', () => {
    const run = recordBackendActionResultRun(
      {
        requestId: 'backend-req-evidence',
        ok: true,
        runId: 'backend-run-evidence',
        resultSummary: 'Backend evidence',
        resultRef: { type: 'analysis/frequency', hash: 'backend-result-hash', rows: 4 },
        evidence: {
          schemaVersion: '2.0',
          provenance: 'backend_action_result',
          completeness: 'full',
          corpusFingerprint: {
            corpusId: 'backend-corpus',
            subcorpusHash: 'backend-scope',
            indexFingerprint: 'index-fp',
            metadataSchemaHash: 'meta-fp',
          },
          toolFingerprint: {
            actionType: 'analysis/frequency',
            toolSchemaHash: 'tool-fp',
          },
          resultFingerprint: {
            resultType: 'analysis/frequency',
            resultHash: 'backend-result-hash',
            rows: 4,
            queryTraceId: 'trace-backend',
          },
          warnings: [],
        },
      },
      {
        requestId: 'backend-req-evidence',
        type: 'analysis/frequency',
        payload: { groupBy: 'word' },
      }
    )

    expect(run?.evidence).toMatchObject({
      provenance: 'backend_action_result',
      completeness: 'full',
      corpusFingerprint: {
        indexFingerprint: 'index-fp',
        metadataSchemaHash: 'meta-fp',
      },
      researchScope: {
        corpusId: 'backend-corpus',
        scopeHash: 'backend-scope',
        scopeStatus: 'unknown',
        metadataSchemaHash: 'meta-fp',
      },
      toolFingerprint: {
        toolSchemaHash: 'tool-fp',
      },
      resultFingerprint: {
        resultHash: 'backend-result-hash',
        queryTraceId: 'trace-backend',
      },
    })
  })

  it('backfills backend trace for existing mirrored run records idempotently', () => {
    const existing = createRunRecord(
      { type: 'query/execute', payload: { term: 'Macht' } } as never,
      {
        success: true,
        source: 'copilot',
        requestId: 'backend-req-existing',
        runId: 'backend-run-existing',
        data: { total: 5 },
      },
      'demo-corpus',
      'scope-hash'
    )

    expect(traceHistory.value).toHaveLength(0)

    const result = {
      requestId: 'backend-req-existing',
      ok: true,
      runId: 'backend-run-existing',
      resultSummary: 'Existing backend run',
      resultRef: { type: 'query/execute', hash: 'backend-hash', rows: 5 },
    }
    const request = {
      requestId: 'backend-req-existing',
      type: 'query/execute',
      payload: { term: 'Macht' },
    }

    expect(recordBackendActionResultRun(result, request)).toEqual(existing)
    expect(recordBackendActionResultRun(result, request)).toEqual(existing)
    expect(traceHistory.value).toHaveLength(1)
    expect(traceHistory.value[0]).toMatchObject({
      actor: 'backend',
      source: 'backend',
      requestId: 'backend-req-existing',
      linkRunId: 'backend-run-existing',
    })
  })

  it('exports trace governance fields to CSV', () => {
    const csv = exportTracesAsCsv([
      {
        id: 'trace-1',
        ts: 1,
        actor: 'copilot',
        source: 'copilot',
        requestId: 'req-1',
        actionType: 'query/execute',
        payloadHash: 'payload-hash',
        ok: false,
        policyDecision: 'preview',
        policyReason: 'needs confirmation',
      },
    ])

    expect(csv.split('\n')[0]).toContain('source,request_id')
    expect(csv.split('\n')[0]).toContain('policy_decision,policy_reason')
    expect(csv).toContain('copilot,req-1,query/execute')
    expect(csv).toContain('false,preview,needs confirmation')
  })
})
