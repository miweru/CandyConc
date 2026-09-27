import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import type { RunRecordV1 } from '@/types/copilot-protocol'

const mocks = vi.hoisted(() => ({
  dispatch: vi.fn(),
  enterCopilotContext: vi.fn(),
  exitCopilotContext: vi.fn(),
}))

vi.mock('@/actions/bus', () => ({
  actionBus: {
    dispatch: mocks.dispatch,
  },
}))

vi.mock('@/actions/policyGate', () => ({
  enterCopilotContext: mocks.enterCopilotContext,
  exitCopilotContext: mocks.exitCopilotContext,
}))

import { runRecords, clearTraceData } from '@/actions/traceRecorder'
import { exportReportAsMarkdown, generateReproducibilityReport, reproduceRun } from '@/services/reproducibilityService'
import { stableResultHash } from '@/utils/runEvidence'
import { executionScopeForApi } from '@/lib/researchScope'
import { useDocsetStore } from '@/stores/docset'

function addRun(overrides: Partial<RunRecordV1> = {}): RunRecordV1 {
  const run: RunRecordV1 = {
    schemaVersion: '2.0',
    runId: 'run_1',
    ts: 1,
    kind: 'analysis',
    actionType: 'analysis/frequency',
    actionPayload: { limit: 10 },
    corpus: {
      corpusId: 'test-corpus',
      subcorpusHash: 'subhash',
    },
    resultRef: {
      type: 'analysis/frequency',
      hash: 'original-hash',
      rows: 2,
    },
    summary: 'Frequency analysis',
    notes: [],
    evidence: {
      schemaVersion: '2.0',
      provenance: 'frontend_actionbus',
      completeness: 'partial',
      corpusFingerprint: {
        corpusId: 'test-corpus',
        subcorpusHash: 'subhash',
      },
      toolFingerprint: {
        actionType: 'analysis/frequency',
      },
      resultFingerprint: {
        resultType: 'analysis/frequency',
        resultHash: 'original-hash',
        rows: 2,
      },
      warnings: ['Missing index fingerprint.'],
    },
    ...overrides,
  }

  runRecords.value.push(run)
  return run
}

describe('reproducibilityService execute-only replay', () => {
  beforeEach(() => {
    clearTraceData()
    mocks.dispatch.mockReset()
    mocks.enterCopilotContext.mockReset()
    mocks.exitCopilotContext.mockReset()
  })

  it('always re-dispatches the original action through the copilot replay context', async () => {
    addRun()
    mocks.dispatch.mockResolvedValue({ success: true, data: { rows: ['a', 'b'] }, source: 'copilot' })

    const result = await reproduceRun('run_1')

    expect(result.executed).toBe(true)
    expect(mocks.enterCopilotContext).toHaveBeenCalledTimes(1)
    expect(mocks.exitCopilotContext).toHaveBeenCalledTimes(1)
    expect(mocks.dispatch).toHaveBeenCalledWith(
      { type: 'analysis/frequency', payload: { limit: 10 } },
      { source: 'copilot', requestId: expect.stringMatching(/^replay:run_1:/) }
    )
    expect(mocks.dispatch.mock.calls[0]?.[1]).not.toBe('system')
  })

  it('normalizes legacy non-object payloads before replay', async () => {
    addRun({ actionPayload: null as unknown as Record<string, unknown> })
    mocks.dispatch.mockResolvedValue({ success: false, error: 'blocked', source: 'copilot' })

    await reproduceRun('run_1')

    expect(mocks.dispatch).toHaveBeenCalledWith(
      { type: 'analysis/frequency', payload: {} },
      { source: 'copilot', requestId: expect.stringMatching(/^replay:run_1:/) }
    )
  })

  it('uses unique replay request ids across attempts', async () => {
    addRun()
    mocks.dispatch.mockResolvedValue({ success: true, data: { rows: ['a', 'b'] }, source: 'copilot' })

    await reproduceRun('run_1')
    await reproduceRun('run_1')

    const firstContext = mocks.dispatch.mock.calls[0]?.[1] as { requestId: string }
    const secondContext = mocks.dispatch.mock.calls[1]?.[1] as { requestId: string }
    expect(firstContext.requestId).toMatch(/^replay:run_1:/)
    expect(secondContext.requestId).toMatch(/^replay:run_1:/)
    expect(secondContext.requestId).not.toBe(firstContext.requestId)
  })

  it('marks replay as different when the replay run has another scope hash', async () => {
    const original = addRun()
    mocks.dispatch.mockImplementation(async (_action, context) => {
      const replayRun: RunRecordV1 = {
        ...original,
        runId: 'run_replay_scope_mismatch',
        requestId: (context as { requestId?: string }).requestId,
        corpus: {
          corpusId: 'test-corpus',
          subcorpusHash: 'different-scope',
        },
        evidence: {
          ...original.evidence,
          corpusFingerprint: {
            ...original.evidence.corpusFingerprint,
            subcorpusHash: 'different-scope',
          },
        },
      }
      runRecords.value.push(replayRun)
      return { success: true, source: 'copilot' }
    })

    const result = await reproduceRun('run_1')

    expect(result.executed).toBe(true)
    expect(result.matched).toBe(false)
    expect(result.differences).toEqual(
      expect.arrayContaining([
        {
          field: 'scopeHash',
          original: 'subhash',
          new: 'different-scope',
        },
      ])
    )
  })

  it('prefers explicit researchScope over legacy subcorpusHash during replay comparison', async () => {
    const original = addRun({
      corpus: {
        corpusId: 'test-corpus',
        subcorpusHash: 'legacy-same',
      },
      evidence: {
        schemaVersion: '2.0',
        provenance: 'frontend_actionbus',
        completeness: 'partial',
        corpusFingerprint: {
          corpusId: 'test-corpus',
          subcorpusHash: 'legacy-same',
        },
        researchScope: {
          corpusId: 'test-corpus',
          scopeHash: 'explicit-original',
          scopeStatus: 'fresh',
        },
        toolFingerprint: {
          actionType: 'analysis/frequency',
        },
        resultFingerprint: {
          resultType: 'analysis/frequency',
          resultHash: 'original-hash',
          rows: 2,
        },
        warnings: [],
      },
    })
    mocks.dispatch.mockImplementation(async (_action, context) => {
      const replayRun: RunRecordV1 = {
        ...original,
        runId: 'run_replay_explicit_scope_mismatch',
        requestId: (context as { requestId?: string }).requestId,
        evidence: {
          ...original.evidence,
          researchScope: {
            corpusId: 'test-corpus',
            scopeHash: 'explicit-replay',
            scopeStatus: 'fresh',
          },
        },
      }
      runRecords.value.push(replayRun)
      return { success: true, source: 'copilot' }
    })

    const result = await reproduceRun('run_1')

    expect(result.matched).toBe(false)
    expect(result.differences).toEqual(
      expect.arrayContaining([
        {
          field: 'scopeHash',
          original: 'explicit-original',
          new: 'explicit-replay',
        },
      ])
    )
  })

  it('blocks replay before dispatch when the current UI scope does not match the original scope', async () => {
    setActivePinia(createPinia())
    try {
      addRun({
        corpus: {
          corpusId: 'default',
          subcorpusHash: 'original-scope',
        },
        evidence: {
          schemaVersion: '2.0',
          provenance: 'frontend_actionbus',
          completeness: 'partial',
          corpusFingerprint: {
            corpusId: 'default',
            subcorpusHash: 'original-scope',
          },
          toolFingerprint: {
            actionType: 'analysis/frequency',
          },
          resultFingerprint: {
            resultType: 'analysis/frequency',
            resultHash: 'original-hash',
            rows: 2,
          },
          warnings: [],
        },
      })

      const result = await reproduceRun('run_1')

      expect(result.executed).toBe(false)
      expect(result.matched).toBe(false)
      expect(result.error).toContain('Forschungs-Scope')
      expect(result.differences).toEqual(
        expect.arrayContaining([
          expect.objectContaining({
            field: 'scopeHash',
            original: 'original-scope',
          }),
        ])
      )
      expect(mocks.dispatch).not.toHaveBeenCalled()
    } finally {
      setActivePinia(undefined)
    }
  })

  it('replays corpus-level runs even when an unused docset is active in the UI', async () => {
    setActivePinia(createPinia())
    try {
      const docsetStore = useDocsetStore()
      docsetStore.activeDocsetId = 'ui-docset-not-used'
      docsetStore.activeSubcorpusName = 'Nicht verwendeter Scope'
      docsetStore.activeFilterSpec = { genre: ['news'] }
      docsetStore.lastQuery = 'alte Query'
      docsetStore.isDirty = true
      docsetStore.metaSchemaHash = 'schema-current'

      const corpusScope = executionScopeForApi(docsetStore, 'default', undefined)
      addRun({
        corpus: {
          corpusId: 'default',
          subcorpusHash: corpusScope.scopeHash ?? '',
        },
        evidence: {
          schemaVersion: '2.0',
          provenance: 'frontend_actionbus',
          completeness: 'partial',
          corpusFingerprint: {
            corpusId: 'default',
            subcorpusHash: corpusScope.scopeHash ?? '',
          },
          researchScope: corpusScope,
          toolFingerprint: {
            actionType: 'analysis/frequency',
          },
          resultFingerprint: {
            resultType: 'analysis/frequency',
            resultHash: 'original-hash',
            rows: 2,
          },
          warnings: [],
        },
      })
      mocks.dispatch.mockResolvedValue({ success: true, data: { rows: ['a', 'b'] }, source: 'copilot' })

      const result = await reproduceRun('run_1')

      expect(result.executed).toBe(true)
      expect(result.error).toBeUndefined()
      expect(mocks.dispatch).toHaveBeenCalled()
    } finally {
      setActivePinia(undefined)
    }
  })

  it('generates reports from real replay attempts without any skipped placeholder', async () => {
    const replayData = { rows: ['a', 'b'] }
    const replayHash = stableResultHash(replayData)
    const original = addRun({
      resultRef: {
        type: 'analysis/frequency',
        hash: replayHash,
        rows: 2,
      },
      evidence: {
        schemaVersion: '2.0',
        provenance: 'frontend_actionbus',
        completeness: 'partial',
        corpusFingerprint: {
          corpusId: 'test-corpus',
          subcorpusHash: 'subhash',
        },
        toolFingerprint: {
          actionType: 'analysis/frequency',
        },
        resultFingerprint: {
          resultType: 'analysis/frequency',
          resultHash: replayHash,
          rows: 2,
        },
        warnings: [],
      },
    })
    let replayCounter = 0
    mocks.dispatch.mockImplementation(async (_action, context) => {
      replayCounter += 1
      const replayRun: RunRecordV1 = {
        ...original,
        runId: `run_replay_${replayCounter}`,
        requestId: (context as { requestId?: string }).requestId,
      }
      runRecords.value.push(replayRun)
      return { success: true, data: replayData, source: 'copilot' }
    })

    const report = await generateReproducibilityReport('run_1', 3)

    expect(mocks.dispatch).toHaveBeenCalledTimes(3)
    expect(report.summary).toEqual({
      totalAttempts: 3,
      successfulMatches: 3,
      failedMatches: 0,
      errors: 0,
      averageDurationMs: expect.any(Number),
    })
    expect(report.summary).not.toHaveProperty('skipped')
    expect(report.results).toHaveLength(3)
    for (const result of report.results) {
      expect(result.executed).toBe(true)
      expect(result.matched).toBe(true)
      expect(result).not.toHaveProperty('skippedReason')
    }
    expect(original.notes).toContain('Reproduzierbarkeit (Live-Replay): 100% (3/3)')

    const markdown = exportReportAsMarkdown(report)
    expect(markdown).toContain('### Original Research Scope')
    expect(markdown).toContain('| ScopeHash | `subhash` |')
    expect(markdown).toContain('Reproduzierbarkeitsrate:** 100.0%')
    expect(markdown).not.toContain('Übersprungen')
    expect(markdown).not.toContain('Dry-run')
  })

  it('counts failed dispatches as errors in the report summary', async () => {
    addRun()
    mocks.dispatch.mockResolvedValue({ success: false, error: 'backend down', source: 'copilot' })

    const report = await generateReproducibilityReport('run_1', 2)

    expect(mocks.dispatch).toHaveBeenCalledTimes(2)
    expect(report.summary.totalAttempts).toBe(2)
    expect(report.summary.successfulMatches).toBe(0)
    expect(report.summary.errors).toBe(2)
    expect(report.results.every(r => r.executed)).toBe(true)
  })
})
