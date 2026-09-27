import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  createContrastJob: vi.fn(),
  getAnalysisJob: vi.fn(),
  getAnalysisJobRows: vi.fn(),
  getMetaSchema: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    createContrastJob: (...args: unknown[]) => apiMocks.createContrastJob(...args),
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

function productContract(options: { includeFreeOperation?: boolean } = {}) {
  const includeFreeOperation = options.includeFreeOperation ?? true
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
        backend_routes: includeFreeOperation ? ['/api/v1/analysis/contrast'] : [],
        backend_route_descriptors: includeFreeOperation
          ? [route('/api/v1/analysis/contrast', 'POST')]
          : [],
        operations: includeFreeOperation
          ? [operation(
              'analysis.contrast',
              'analysis.contrast.free_job',
              '/api/v1/analysis/contrast',
              'POST',
              'Freier Kontrastjob',
            )]
          : [],
        action_types: ['analysis/freeContrast'],
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

describe('analysis/freeContrast action lifecycle', () => {
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
    apiMocks.createContrastJob.mockResolvedValue({ job_id: 'job-free-contrast-1' })
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-free-contrast-1',
      kind: 'contrast',
      corpus: 'demo',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
  })

  it('runs free contrast through the declared backend operation and shared job lifecycle', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-free-contrast-1',
      rows: [
        { word: 'Sprache', target_per_million: 120, reference_per_million: 40, log_ratio: 1.58 },
      ],
      total_rows: 1,
      row_limit: 75,
      total_candidates: 12,
      truncated: false,
      offset: 0,
      limit: 75,
      status: 'done',
      method: { name: 'collocates_diff', completeness: 'complete' },
    })
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/freeContrast',
      payload: {
        term: 'Sprache',
        targetSubcorpus: 'Zeitung',
        referenceSubcorpus: 'Blog',
        windowSize: 5,
        withinSentence: true,
        measure: 'logdice',
        limit: 75,
        corpus: 'demo',
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('contrast')
    expect(apiMocks.createContrastJob).toHaveBeenCalledWith({
      term: 'Sprache',
      targetDocsetId: undefined,
      targetSubcorpus: 'Zeitung',
      referenceDocsetId: undefined,
      referenceSubcorpus: 'Blog',
      window: 5,
      withinSentence: true,
      sortBy: 'logdice',
      limit: 75,
      corpus: 'demo',
    })
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-free-contrast-1', 0, 75)
    expect(result.data).toMatchObject({
      rows: [{ word: 'Sprache', target_per_million: 120, reference_per_million: 40, log_ratio: 1.58 }],
      measure: 'logdice',
      rowLimit: 75,
      totalCandidates: 12,
      totalRows: 1,
      truncated: false,
      targetSubcorpus: 'Zeitung',
      referenceSubcorpus: 'Blog',
    })
  })

  it('blocks before backend execution when the free contrast ProductOperation is missing', async () => {
    apiMocks.getProductCapabilities.mockResolvedValue(productContract({ includeFreeOperation: false }))

    const result = await actionBus.dispatch({
      type: 'analysis/freeContrast',
      payload: {
        term: 'Sprache',
        targetSubcorpus: 'Zeitung',
        referenceSubcorpus: 'Blog',
      },
    })

    expect(result.success).toBe(false)
    expect(result.blocked).toBe(true)
    expect(String(result.error)).toContain('Freier Kontrastjob')
    expect(apiMocks.createContrastJob).not.toHaveBeenCalled()
  })

  it('rejects the retired mi2 measure before starting a free contrast job', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/freeContrast',
      payload: {
        term: 'Sprache',
        targetSubcorpus: 'Zeitung',
        referenceSubcorpus: 'Blog',
        measure: 'mi2',
      } as unknown as { term: string; targetSubcorpus: string; referenceSubcorpus: string },
    })

    expect(result.success).toBe(false)
    expect(String(result.error)).toContain('chi2_cell')
    expect(apiMocks.createContrastJob).not.toHaveBeenCalled()
  })
})
