import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProductOperationRunsStore } from '@/stores/productOperationRuns'

const getOperationRun = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getOperationRun: (...args: unknown[]) => getOperationRun(...args),
  }
})

describe('product operation runs store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('preserves backend OperationRun provenance instead of flattening it into detail', async () => {
    getOperationRun.mockResolvedValue({
      run_id: 'backend-run-1',
      job_id: 'backend-job-1',
      operation_id: 'analysis.frequency.job',
      source_id: 'analysis-job-1',
      kind: 'analysis',
      label: 'Frequenzjob',
      status: 'running',
      phase: 'aggregating',
      progress: 42,
      message: 'Frequenzen werden aggregiert.',
      error: null,
      result_ref: 'analysis://frequency/backend-run-1',
      readiness: 'pending',
      warnings: ['Resultat noch nicht vollständig.'],
      evidence: {
        checksum: 'abc123',
        rows: 200,
      },
      created_at: '2026-06-20T10:00:00.000Z',
      updated_at: '2026-06-20T10:01:00.000Z',
      finished_at: null,
    })

    const runs = useProductOperationRunsStore()
    const record = await runs.refreshBackendRun('backend-run-1')

    expect(getOperationRun).toHaveBeenCalledWith('backend-run-1')
    expect(record).toMatchObject({
      operationId: 'analysis.frequency.job',
      sourceId: 'analysis-job-1',
      backendRunId: 'backend-run-1',
      backendJobId: 'backend-job-1',
      kind: 'analysis',
      label: 'Frequenzjob',
      detail: 'analysis://frequency/backend-run-1',
      phase: 'aggregating',
      resultRef: 'analysis://frequency/backend-run-1',
      evidence: {
        checksum: 'abc123',
        rows: 200,
      },
      readiness: 'pending',
      warnings: ['Resultat noch nicht vollständig.'],
    })
  })
})
