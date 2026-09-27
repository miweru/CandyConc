import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  createCollocatesJob: vi.fn(),
  getAnalysisJob: vi.fn(),
  getAnalysisJobRows: vi.fn(),
  getMetaSchema: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getCorpusCapabilities: (...args: unknown[]) => apiMocks.getCorpusCapabilities(...args),
    createCollocatesJob: (...args: unknown[]) => apiMocks.createCollocatesJob(...args),
    getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
    getAnalysisJobRows: (...args: unknown[]) => apiMocks.getAnalysisJobRows(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
  }
})

import { actionBus } from '@/actions/bus'
import { clearCollocationActionHandoff, collocationActionHandoff } from '@/actions/collocationHandoff'
import { registerActionHandlers } from '@/actions/handlers'
import { useAnalysisJobsStore } from '@/stores/analysisJobs'
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

function productContract(options: { includeRowsOperation?: boolean } = {}) {
  const includeRowsOperation = options.includeRowsOperation ?? true
  const asyncBackendRoutes = includeRowsOperation
    ? [
        '/api/v1/analysis/jobs/{job_id}',
        '/api/v1/analysis/jobs/{job_id}/rows',
      ]
    : ['/api/v1/analysis/jobs/{job_id}']
  const asyncDescriptors = includeRowsOperation
    ? [
        route('/api/v1/analysis/jobs/{job_id}', 'GET'),
        route('/api/v1/analysis/jobs/{job_id}/rows', 'GET'),
      ]
    : [route('/api/v1/analysis/jobs/{job_id}', 'GET')]
  const asyncOperations = [
    operation(
      'analysis.async_jobs',
      'analysis.async_jobs.status',
      '/api/v1/analysis/jobs/{job_id}',
      'GET',
      'Analysejob-Status',
    ),
    ...(includeRowsOperation
      ? [
          operation(
            'analysis.async_jobs',
            'analysis.async_jobs.rows',
            '/api/v1/analysis/jobs/{job_id}/rows',
            'GET',
            'Analysejob-Zeilen',
          ),
        ]
      : []),
  ]
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
      capability('analysis.collocations', {
        backend_routes: ['/api/v1/analysis/collocates/job'],
        backend_route_descriptors: [route('/api/v1/analysis/collocates/job', 'POST')],
        operations: [
          operation(
            'analysis.collocations',
            'analysis.collocations.job',
            '/api/v1/analysis/collocates/job',
            'POST',
            'Kollokationsjob',
          ),
        ],
        action_types: ['analysis/collocations'],
      }),
      capability('analysis.async_jobs', {
        backend_routes: asyncBackendRoutes,
        backend_route_descriptors: asyncDescriptors,
        operations: asyncOperations,
      }),
    ],
  }
}

function corpusSummary() {
  return {
    name: 'default',
    path: '/corpora/default',
    token_count: 1000,
    doc_count: 10,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }
}

describe('analysis/collocations action lifecycle', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    actionBus.releaseLock()
    actionBus.clearHistory()
    clearCollocationActionHandoff()
    vi.clearAllMocks()
    apiMocks.getProductCapabilities.mockResolvedValue(productContract())
    apiMocks.getCorpusCapabilities.mockResolvedValue(corpusSummary())
    apiMocks.getMetaSchema.mockResolvedValue({ fields: [] })
    apiMocks.createCollocatesJob.mockResolvedValue({ job_id: 'job-colloc-1' })
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-colloc-1',
      kind: 'collocates',
      corpus: 'default',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
  })

  it('runs collocation actions through the shared async-job lifecycle and stores snapshots', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-colloc-1',
      rows: [
        { word: 'springt', f: 5, mi: 2.5 },
      ],
      total_rows: 1,
      offset: 0,
      limit: 1000,
      status: 'done',
    })
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/collocations',
      payload: { term: 'Hase', measure: 'mi', windowSize: 5, minFreq: 7 },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('collocations')
    expect(apiMocks.createCollocatesJob).toHaveBeenCalledWith({
      term: 'Hase',
      collocate: undefined,
      window: 5,
      minFreq: 7,
      withinSentence: true,
      sortBy: 'mi',
      corpus: 'default',
      docsetId: undefined,
    })
    expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-colloc-1')
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-colloc-1', 0, 1000)
    expect(analysisJobs.snapshotFor('job-colloc-1')).toMatchObject({
      job_id: 'job-colloc-1',
      status: 'done',
    })
    expect(result.data).toEqual([
      { word: 'springt', frequency: 5, score: 2.5, measure: 'mi' },
    ])
  })

  it('keeps fetching rows until the completed collocation job is fully collected', async () => {
    const firstRows = Array.from({ length: 1000 }, (_, index) => ({
      word: `w${index}`,
      f: 1,
      mi: index,
    }))
    apiMocks.getAnalysisJobRows
      .mockResolvedValueOnce({
        job_id: 'job-colloc-1',
        rows: firstRows,
        total_rows: 1001,
        offset: 0,
        limit: 1000,
        status: 'done',
      })
      .mockResolvedValueOnce({
        job_id: 'job-colloc-1',
        rows: [{ word: 'w1000', f: 2, mi: 1000 }],
        total_rows: 1001,
        offset: 1000,
        limit: 1000,
        status: 'done',
      })

    const result = await actionBus.dispatch({
      type: 'analysis/collocations',
      payload: { term: 'Hase', measure: 'mi' },
    })

    expect(result.success).toBe(true)
    expect(result.data).toHaveLength(1001)
    expect(apiMocks.getAnalysisJobRows).toHaveBeenNthCalledWith(1, 'job-colloc-1', 0, 1000)
    expect(apiMocks.getAnalysisJobRows).toHaveBeenNthCalledWith(2, 'job-colloc-1', 1000, 1000)
  })

  it('uses backend logdice scores without applying a second dice transform', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-colloc-1',
      rows: [
        { word: 'flink', f: 7, logdice: 8.2, dice: 0.01 },
      ],
      total_rows: 1,
      offset: 0,
      limit: 1000,
      status: 'done',
    })

    const result = await actionBus.dispatch({
      type: 'analysis/collocations',
      payload: { term: 'Hase', measure: 'logdice' },
    })

    expect(result.success).toBe(true)
    expect(result.data).toEqual([
      { word: 'flink', frequency: 7, score: 8.2, measure: 'logdice' },
    ])
  })

  it('forwards an explicit Copilot scope, Delta-P direction, minimum frequency, and result limit unchanged', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-colloc-1',
      rows: [{ word: 'Bau', f: 9, mi: 11, delta_p_nc: 0.7 }],
      total_rows: 1,
      offset: 0,
      limit: 10,
      status: 'done',
    })

    const result = await actionBus.dispatch({
      type: 'analysis/collocations',
      payload: {
        term: 'Hase',
        windowSize: 7,
        withinSentence: false,
        measure: 'delta_p_nc',
        minFreq: 9,
        limit: 10,
        corpus: 'vergleich',
        docsetId: 'docset-vergleich',
      },
    })

    expect(result.success).toBe(true)
    expect(apiMocks.createCollocatesJob).toHaveBeenCalledWith({
      term: 'Hase',
      collocate: undefined,
      window: 7,
      minFreq: 9,
      limit: 10,
      withinSentence: false,
      sortBy: 'delta_p_nc',
      corpus: 'vergleich',
      docsetId: 'docset-vergleich',
    })
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-colloc-1', 0, 10)
    expect(result.data).toEqual([
      { word: 'Bau', frequency: 9, score: 0.7, measure: 'delta_p_nc' },
    ])
    expect(result.executionScope).toMatchObject({ corpusId: 'vergleich', docsetId: 'docset-vergleich' })
    expect(collocationActionHandoff.value).toMatchObject({
      status: 'completed',
      request: {
        corpus: 'vergleich',
        docsetId: 'docset-vergleich',
        measure: 'delta_p_nc',
        minFreq: 9,
      },
      result: {
        totalRows: 1,
        rows: [{ word: 'Bau', f: 9, mi: 11, delta_p_nc: 0.7 }],
      },
    })
  })

  it('does not start a collocation job when async job rows are not offered as an operation', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(productContract({ includeRowsOperation: false }))
    const uiStore = useUiStore()
    uiStore.setActiveTab('kwic')

    const result = await actionBus.dispatch({
      type: 'analysis/collocations',
      payload: { term: 'Hase' },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Analysejob-Zeilen')
    expect(apiMocks.createCollocatesJob).not.toHaveBeenCalled()
    expect(uiStore.activeTab).toBe('kwic')
  })

  it('keeps the cancelled snapshot and returns a readable cancellation error', async () => {
    apiMocks.getAnalysisJob.mockResolvedValueOnce({
      job_id: 'job-colloc-1',
      kind: 'collocates',
      corpus: 'default',
      status: 'cancelled',
      progress: 0.4,
      message: 'abgebrochen',
    })
    const analysisJobs = useAnalysisJobsStore()

    const result = await actionBus.dispatch({
      type: 'analysis/collocations',
      payload: { term: 'Hase' },
    })

    expect(result).toMatchObject({
      success: false,
      error: 'Kollokations-Job abgebrochen',
    })
    expect(apiMocks.getAnalysisJobRows).not.toHaveBeenCalled()
    expect(analysisJobs.snapshotFor('job-colloc-1')).toMatchObject({
      job_id: 'job-colloc-1',
      status: 'cancelled',
    })
  })
})
