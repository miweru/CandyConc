import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ActionBus } from '@/actions/bus'
import {
  clearPreviews,
  createPolicyGateMiddleware,
  currentPreview,
  resolvePreview,
} from '@/actions/policyGate'
import {
  clearTraceData,
  createTraceRecorderMiddleware,
  runRecords,
  traceHistory,
} from '@/actions/traceRecorder'
import { useCopilotStore } from '@/stores/copilot'

describe('trace governance', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    clearPreviews()
    clearTraceData()
  })

  it('records policy-blocked copilot preview actions with request id', async () => {
    const store = useCopilotStore()
    store.setAutonomyLevel(0)

    const bus = new ActionBus()
    bus.use(createTraceRecorderMiddleware(
      () => ({ corpusId: 'test-corpus', subcorpusHash: 'test-subcorpus' }),
      () => 'query-hash'
    ))
    bus.use(createPolicyGateMiddleware())
    bus.register('query/execute', async () => ({ success: true, data: { total: 1 } }))

    const resultPromise = bus.dispatch(
      { type: 'query/execute', payload: { term: 'Haus' } },
      { source: 'copilot', requestId: 'req-trace-1' }
    )

    expect(currentPreview.value?.requestId).toBe('req-trace-1')
    resolvePreview('req-trace-1', false, 'rejected')

    const result = await resultPromise

    expect(result).toMatchObject({
      success: false,
      blocked: true,
      source: 'copilot',
      requestId: 'req-trace-1',
      policyDecision: 'preview',
    })
    expect(runRecords.value).toHaveLength(0)
    expect(traceHistory.value).toHaveLength(1)
    expect(traceHistory.value[0]).toMatchObject({
      source: 'copilot',
      requestId: 'req-trace-1',
      actionType: 'query/execute',
      ok: false,
      policyDecision: 'preview',
    })
    expect(traceHistory.value[0]?.policyReason).toBeTruthy()
  })

  it('links successful run evidence to the emitted trace id', async () => {
    const bus = new ActionBus()
    bus.use(createTraceRecorderMiddleware(
      () => ({ corpusId: 'test-corpus', subcorpusHash: 'test-subcorpus' }),
      () => 'query-hash'
    ))
    bus.register('query/execute', async () => ({
      success: true,
      data: { total: 2, queryTime: 1 },
      source: 'user',
    }))

    const result = await bus.dispatch(
      { type: 'query/execute', payload: { term: 'Haus' } },
      { source: 'user', requestId: 'req-trace-success' }
    )

    expect(result.success).toBe(true)
    expect(runRecords.value).toHaveLength(1)
    expect(traceHistory.value).toHaveLength(1)
    expect(traceHistory.value[0]?.linkRunId).toBe(runRecords.value[0]?.runId)
    expect(runRecords.value[0]?.evidence.resultFingerprint.queryTraceId).toBe(traceHistory.value[0]?.id)
    expect(runRecords.value[0]?.evidence.warnings).not.toContain('Missing query trace id.')
  })

  it('keeps backend query trace id separate from frontend trace id in run evidence', async () => {
    const bus = new ActionBus()
    bus.use(createTraceRecorderMiddleware(
      () => ({ corpusId: 'test-corpus', subcorpusHash: 'test-subcorpus' }),
      () => 'query-hash'
    ))
    bus.register('query/execute', async () => ({
      success: true,
      data: { total: 2, backendQueryTraceId: 'qtr-backend' },
      source: 'user',
    }))

    await bus.dispatch(
      { type: 'query/execute', payload: { term: 'Haus' } },
      { source: 'user', requestId: 'req-backend-trace' }
    )

    expect(traceHistory.value).toHaveLength(1)
    expect(runRecords.value[0]?.evidence.resultFingerprint.queryTraceId).toBe(traceHistory.value[0]?.id)
    expect(runRecords.value[0]?.evidence.resultFingerprint.backendQueryTraceId).toBe('qtr-backend')
    expect(runRecords.value[0]?.evidence.warnings).not.toContain('Missing query trace id.')
  })

  it('adds backend metadata schema fingerprints to frontend action runs', async () => {
    const bus = new ActionBus()
    bus.use(createTraceRecorderMiddleware(
      () => ({ corpusId: 'test-corpus', subcorpusHash: 'test-subcorpus' }),
      () => 'query-hash',
      async (corpusId) => ({
        indexFingerprint: `index:${corpusId}`,
        metadataSchemaHash: `meta:${corpusId}`,
        warnings: ['Metadata schema: degraded fixture'],
      })
    ))
    bus.register('query/execute', async () => ({
      success: true,
      data: { total: 1 },
      source: 'user',
    }))

    await bus.dispatch(
      { type: 'query/execute', payload: { term: 'Haus' } },
      { source: 'user', requestId: 'req-meta-schema' }
    )

    expect(runRecords.value).toHaveLength(1)
    expect(runRecords.value[0]?.evidence.corpusFingerprint.indexFingerprint).toBe('index:test-corpus')
    expect(runRecords.value[0]?.evidence.corpusFingerprint.metadataSchemaHash).toBe('meta:test-corpus')
    expect(runRecords.value[0]?.evidence.warnings).not.toContain('Missing index fingerprint.')
    expect(runRecords.value[0]?.evidence.warnings).not.toContain('Missing metadata schema hash.')
    expect(runRecords.value[0]?.evidence.warnings).toContain('Metadata schema: degraded fixture')
  })

  it('records the backend execution scope instead of the current UI fallback scope', async () => {
    const bus = new ActionBus()
    bus.use(createTraceRecorderMiddleware(
      () => ({
        corpusId: 'fallback-corpus',
        subcorpusHash: 'fallback-scope',
        researchScope: {
          corpusId: 'fallback-corpus',
          scopeHash: 'fallback-scope',
          scopeStatus: 'fresh',
          label: 'Veralteter UI-Scope',
          docsetId: 'fallback-docset',
        },
      }),
      () => 'query-hash',
      async (corpusId) => ({
        indexFingerprint: `index:${corpusId}`,
        metadataSchemaHash: `meta:${corpusId}`,
      })
    ))
    bus.register('query/execute', async () => ({
      success: true,
      data: { total: 1 },
      source: 'user',
      executionScope: {
        corpusId: 'actual-corpus',
        scopeHash: 'actual-scope',
        scopeStatus: 'corpus',
        label: 'Gesamtkorpus',
      },
    }))

    await bus.dispatch(
      { type: 'query/execute', payload: { term: 'Haus' } },
      { source: 'user', requestId: 'req-execution-scope' }
    )

    expect(runRecords.value).toHaveLength(1)
    expect(runRecords.value[0]?.corpus).toEqual({
      corpusId: 'actual-corpus',
      subcorpusHash: 'actual-scope',
    })
    expect(runRecords.value[0]?.evidence.researchScope).toMatchObject({
      corpusId: 'actual-corpus',
      scopeHash: 'actual-scope',
      scopeStatus: 'corpus',
      label: 'Gesamtkorpus',
    })
    expect(runRecords.value[0]?.evidence.corpusFingerprint.indexFingerprint).toBe('index:actual-corpus')
    expect(runRecords.value[0]?.evidence.corpusFingerprint.metadataSchemaHash).toBe('meta:actual-corpus')
  })
})
