import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  createCollocatesDiffJob: vi.fn(),
  getAnalysisJob: vi.fn(),
  getAnalysisJobRows: vi.fn(),
  getMetaSchema: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    createCollocatesDiffJob: (...args: unknown[]) => apiMocks.createCollocatesDiffJob(...args),
    getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
    getAnalysisJobRows: (...args: unknown[]) => apiMocks.getAnalysisJobRows(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
  }
})

import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useUiStore } from '@/stores/ui'

function route(path: string, method = 'GET') {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(capabilityId: string, id: string, path: string, method: string, label: string) {
  return {
    id,
    capability_id: capabilityId,
    label,
    description: '',
    route: route(path, method),
    effects: [method === 'GET' ? 'read' : 'long_running'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: id,
    priority: 10,
  }
}

function capability(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: [],
    operations: [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

function productContract(options: { includeContrastOperation?: boolean } = {}) {
  const includeContrastOperation = options.includeContrastOperation ?? true
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      capability('analysis.contrast', {
        backend_routes: includeContrastOperation ? ['/api/v1/analysis/collocates_diff/job'] : [],
        backend_route_descriptors: includeContrastOperation
          ? [route('/api/v1/analysis/collocates_diff/job', 'POST')]
          : [],
        operations: includeContrastOperation
          ? [operation(
              'analysis.contrast',
              'analysis.contrast.collocations_diff_job',
              '/api/v1/analysis/collocates_diff/job',
              'POST',
              'Kollokations-Kontrastjob',
            )]
          : [],
        action_types: ['analysis/collocationContrast'],
        copilot_tools: ['compare_collocates', 'contrast_collocates'],
      }),
      capability('analysis.async_jobs', {
        backend_routes: [
          '/api/v1/analysis/jobs/{job_id}',
          '/api/v1/analysis/jobs/{job_id}/rows',
        ],
        backend_route_descriptors: [
          route('/api/v1/analysis/jobs/{job_id}', 'GET'),
          route('/api/v1/analysis/jobs/{job_id}/rows', 'GET'),
        ],
        operations: [
          operation(
            'analysis.async_jobs',
            'analysis.async_jobs.status',
            '/api/v1/analysis/jobs/{job_id}',
            'GET',
            'Analysejob-Status',
          ),
          operation(
            'analysis.async_jobs',
            'analysis.async_jobs.rows',
            '/api/v1/analysis/jobs/{job_id}/rows',
            'GET',
            'Analysejob-Zeilen',
          ),
        ],
      }),
    ],
  }
}

describe('analysis/collocationContrast action lifecycle', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    actionBus.releaseLock()
    actionBus.clearHistory()
    vi.clearAllMocks()
    apiMocks.getProductCapabilities.mockResolvedValue(productContract())
    apiMocks.getMetaSchema.mockResolvedValue({ fields: [] })
    apiMocks.createCollocatesDiffJob.mockResolvedValue({ job_id: 'job-colloc-diff-1' })
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-colloc-diff-1',
      kind: 'collocates_diff',
      corpus: 'demo',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
  })

  it('runs collocation contrast through the shared async-job lifecycle', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-colloc-diff-1',
      rows: [
        { word: 'Sprache', target_f: 12, reference_f: 4, logdice: 7.2 },
      ],
      total_rows: 1,
      row_limit: 100,
      total_candidates: 14,
      truncated: false,
      offset: 0,
      limit: 100,
      status: 'done',
    })
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/collocationContrast',
      payload: {
        term: 'Sprache',
        targetDocsetId: 'target-docset',
        referenceDocsetId: 'reference-docset',
        windowSize: 5,
        withinSentence: true,
        measure: 'logdice',
        limit: 100,
        corpus: 'demo',
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('contrast')
    expect(apiMocks.createCollocatesDiffJob).toHaveBeenCalledWith({
      term: 'Sprache',
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
      window: 5,
      withinSentence: true,
      sortBy: 'logdice',
      limit: 100,
      corpus: 'demo',
    })
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-colloc-diff-1', 0, 100)
    expect(result.data).toMatchObject({
      rows: [{ word: 'Sprache', target_f: 12, reference_f: 4, logdice: 7.2 }],
      measure: 'logdice',
      rowLimit: 100,
      totalCandidates: 14,
      totalRows: 1,
      truncated: false,
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
    })
  })

  it('blocks before backend execution when the ProductOperation is missing', async () => {
    apiMocks.getProductCapabilities.mockResolvedValue(productContract({ includeContrastOperation: false }))

    const result = await actionBus.dispatch({
      type: 'analysis/collocationContrast',
      payload: {
        term: 'Sprache',
        targetDocsetId: 'target-docset',
        referenceDocsetId: 'reference-docset',
      },
    })

    expect(result.success).toBe(false)
    expect(result.blocked).toBe(true)
    expect(String(result.error)).toContain('Kollokations-Kontrastjob')
    expect(apiMocks.createCollocatesDiffJob).not.toHaveBeenCalled()
  })

  it('rejects the retired mi2 measure before starting a contrast job', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/collocationContrast',
      payload: {
        term: 'Sprache',
        targetDocsetId: 'target-docset',
        referenceDocsetId: 'reference-docset',
        measure: 'mi2',
      } as unknown as { term: string; targetDocsetId: string; referenceDocsetId: string },
    })

    expect(result.success).toBe(false)
    expect(String(result.error)).toContain('chi2_cell')
    expect(apiMocks.createCollocatesDiffJob).not.toHaveBeenCalled()
  })
})
