import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  createNgramsJob: vi.fn(),
  createNgramsDiffJob: vi.fn(),
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
    createNgramsJob: (...args: unknown[]) => apiMocks.createNgramsJob(...args),
    createNgramsDiffJob: (...args: unknown[]) => apiMocks.createNgramsDiffJob(...args),
    getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
    getAnalysisJobRows: (...args: unknown[]) => apiMocks.getAnalysisJobRows(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
  }
})

import { actionBus } from '@/actions/bus'
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
      capability('analysis.ngrams', {
        backend_routes: ['/api/v1/analysis/ngrams/job', '/api/v1/analysis/ngrams_diff/job'],
        backend_route_descriptors: [
          route('/api/v1/analysis/ngrams/job', 'POST'),
          route('/api/v1/analysis/ngrams_diff/job', 'POST'),
        ],
        operations: [
          operation(
            'analysis.ngrams',
            'analysis.ngrams.frequency_job',
            '/api/v1/analysis/ngrams/job',
            'POST',
            'N-Gramm-Frequenzjob',
          ),
          operation(
            'analysis.ngrams',
            'analysis.ngrams.diff_job',
            '/api/v1/analysis/ngrams_diff/job',
            'POST',
            'N-Gramm-Kontrastjob',
          ),
        ],
        action_types: ['analysis/ngramFrequency', 'analysis/ngramContrast'],
        copilot_tools: ['ngram_frequency', 'ngram_contrast'],
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

describe('analysis/ngramFrequency action lifecycle', () => {
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
    apiMocks.getCorpusCapabilities.mockResolvedValue(corpusSummary())
    apiMocks.getMetaSchema.mockResolvedValue({ fields: [] })
    apiMocks.createNgramsJob.mockResolvedValue({ job_id: 'job-ngrams-1' })
    apiMocks.createNgramsDiffJob.mockResolvedValue({ job_id: 'job-ngrams-diff-1' })
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-ngrams-1',
      kind: 'ngrams',
      corpus: 'default',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
  })

  it('runs n-gram contrast through the shared async-job lifecycle', async () => {
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-ngrams-diff-1',
      kind: 'ngrams_diff',
      corpus: 'demo',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-ngrams-diff-1',
      rows: [
        { ngram: 'der hase', n: 2, target_freq: 9, reference_freq: 2 },
      ],
      total_rows: 1,
      row_limit: 80,
      total_candidates: 12,
      truncated: false,
      offset: 0,
      limit: 80,
      status: 'done',
    })
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/ngramContrast',
      payload: {
        targetDocsetId: 'target-docset',
        referenceDocsetId: 'reference-docset',
        n: 2,
        limit: 80,
        corpus: 'demo',
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('ngrams')
    expect(apiMocks.createNgramsDiffJob).toHaveBeenCalledWith({
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
      minN: 2,
      maxN: 2,
      minFreq: 1,
      limit: 80,
      corpus: 'demo',
    })
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-ngrams-diff-1', 0, 80)
    expect(result.data).toMatchObject({
      rows: [{ ngram: 'der hase', n: 2, target_freq: 9, reference_freq: 2 }],
      n: 2,
      minN: 2,
      maxN: 2,
      rowLimit: 80,
      totalCandidates: 12,
      totalRows: 1,
      truncated: false,
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
    })
  })

  it('runs n-gram frequency through the shared async-job lifecycle and returns bounded evidence', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-ngrams-1',
      rows: [
        { ngram: 'der hase springt', freq: 8, n: 3 },
        { ngram: 'und in der', freq: 2, n: 3 },
      ],
      total_rows: 2,
      row_limit: 50,
      total_candidates: 42,
      truncated: true,
      offset: 0,
      limit: 50,
      status: 'done',
      method: { target_total: 56_191 },
    })
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/ngramFrequency',
      payload: { n: 3, minFreq: 3, limit: 50, sortBy: 'frequency' },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('ngrams')
    expect(apiMocks.createNgramsJob).toHaveBeenCalledWith({
      minN: 3,
      maxN: 3,
      minFreq: 3,
      limit: 50,
      corpus: 'default',
      docsetId: undefined,
    })
    expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-ngrams-1')
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-ngrams-1', 0, 50)
    expect(analysisJobs.snapshotFor('job-ngrams-1')).toMatchObject({
      job_id: 'job-ngrams-1',
      status: 'done',
    })
    expect(result.data).toEqual({
      rows: [{ ngram: 'der hase springt', frequency: 8, relative: 8 / 56_191 }],
      n: 3,
      minN: 3,
      maxN: 3,
      minFreq: 3,
      sortBy: 'frequency',
      rowLimit: 50,
      totalCandidates: 42,
      totalRows: 2,
      truncated: true,
      method: { target_total: 56_191 },
    })
    expect(result.executionScope).toMatchObject({ corpusId: 'default', scopeStatus: 'corpus' })
  })

  it('preserves requested n-gram ranges through the action layer', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-ngrams-1',
      rows: [
        { ngram: 'der', freq: 20, n: 1 },
        { ngram: 'der hase', freq: 8, n: 2 },
      ],
      total_rows: 2,
      row_limit: 40,
      total_candidates: 50,
      truncated: false,
      offset: 0,
      limit: 40,
      status: 'done',
    })

    const result = await actionBus.dispatch({
      type: 'analysis/ngramFrequency',
      payload: { minN: 1, maxN: 3, limit: 40 },
    })

    expect(result.success).toBe(true)
    expect(apiMocks.createNgramsJob).toHaveBeenCalledWith({
      minN: 1,
      maxN: 3,
      minFreq: 1,
      limit: 40,
      corpus: 'default',
      docsetId: undefined,
    })
    expect(result.data).toMatchObject({
      n: 1,
      minN: 1,
      maxN: 3,
      rowLimit: 40,
    })
  })

  it('does not start a job when async rows are not offered by the ProductOperation contract', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(productContract({ includeRowsOperation: false }))
    const uiStore = useUiStore()
    uiStore.setActiveTab('kwic')

    const result = await actionBus.dispatch({
      type: 'analysis/ngramFrequency',
      payload: { n: 2 },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Serverfunktion')
    expect(apiMocks.createNgramsJob).not.toHaveBeenCalled()
    expect(uiStore.activeTab).toBe('kwic')
  })
})
