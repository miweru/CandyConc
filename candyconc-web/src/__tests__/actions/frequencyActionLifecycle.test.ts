import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  createFrequencyListJob: vi.fn(),
  getFrequencyResult: vi.fn(),
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
    createFrequencyListJob: (...args: unknown[]) => apiMocks.createFrequencyListJob(...args),
    getFrequencyResult: (...args: unknown[]) => apiMocks.getFrequencyResult(...args),
    getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
    getAnalysisJobRows: (...args: unknown[]) => apiMocks.getAnalysisJobRows(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
  }
})

import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useAnalysisJobsStore } from '@/stores/analysisJobs'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
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
    input_schema_ref: method === 'GET' ? 'operation.query_params' : 'analysis.frequency_job_request',
    required_context: [],
    response_shape: method === 'GET' ? 'data' : 'job',
    run_semantics: method === 'GET' ? 'bounded_sync' : 'job_lifecycle',
    ui_execution_policy: 'contextual_ui',
    requires_parameters: true,
    lifecycle: method === 'GET'
      ? null
      : {
          kind: 'http_poll',
          job_id_field: 'job_id',
          polling: 'http_poll',
          status_operation_id: 'analysis.async_jobs.status',
          rows_operation_id: 'analysis.async_jobs.rows',
          cancel_operation_id: null,
          reports_operation_id: null,
          status_field: 'status',
          progress_field: 'progress',
          message_field: 'message',
          error_field: 'error',
          terminal_statuses: ['done', 'error', 'cancelled'],
        },
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

function productContract(options: { includeJob?: boolean; includeAsyncRows?: boolean } = {}) {
  const includeJob = options.includeJob ?? true
  const includeAsyncRows = options.includeAsyncRows ?? true
  const frequencyRoutes = [
    '/api/v1/analysis/frequency_list',
    ...(includeJob ? ['/api/v1/analysis/frequency_list/job'] : []),
  ]
  const frequencyDescriptors = [
    route('/api/v1/analysis/frequency_list', 'GET'),
    ...(includeJob ? [route('/api/v1/analysis/frequency_list/job', 'POST')] : []),
  ]
  const asyncRoutes = [
    '/api/v1/analysis/jobs/{job_id}',
    ...(includeAsyncRows ? ['/api/v1/analysis/jobs/{job_id}/rows'] : []),
  ]
  const asyncDescriptors = [
    route('/api/v1/analysis/jobs/{job_id}', 'GET'),
    ...(includeAsyncRows ? [route('/api/v1/analysis/jobs/{job_id}/rows', 'GET')] : []),
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
      capability('analysis.frequency', {
        backend_routes: frequencyRoutes,
        backend_route_descriptors: frequencyDescriptors,
        operations: [
          operation(
            'analysis.frequency',
            'analysis.frequency.list',
            '/api/v1/analysis/frequency_list',
            'GET',
            'Frequenzliste',
          ),
          ...(includeJob
            ? [operation(
                'analysis.frequency',
                'analysis.frequency.job',
                '/api/v1/analysis/frequency_list/job',
                'POST',
                'Frequenzjob',
              )]
            : []),
        ],
        action_types: ['analysis/frequency'],
        copilot_tools: ['frequency_list'],
      }),
      capability('analysis.async_jobs', {
        backend_routes: asyncRoutes,
        backend_route_descriptors: asyncDescriptors,
        operations: [
          operation(
            'analysis.async_jobs',
            'analysis.async_jobs.status',
            '/api/v1/analysis/jobs/{job_id}',
            'GET',
            'Analysejob-Status',
          ),
          ...(includeAsyncRows
            ? [operation(
                'analysis.async_jobs',
                'analysis.async_jobs.rows',
                '/api/v1/analysis/jobs/{job_id}/rows',
                'GET',
                'Analysejob-Zeilen',
              )]
            : []),
        ],
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
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Wortform' },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma' },
      ],
      frequency_groups: [
        { id: 'word', label: 'Wortform' },
        { id: 'lemma', label: 'Lemma' },
      ],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }
}

describe('analysis/frequency action lifecycle', () => {
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
    apiMocks.createFrequencyListJob.mockResolvedValue({ job_id: 'job-frequency-1' })
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-frequency-1',
      kind: 'frequency_list',
      corpus: 'default',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-frequency-1',
      rows: [
        { word: 'Hase', f: 8 },
        { word: 'läuft', f: 3 },
      ],
      total_rows: 2,
      row_limit: 50,
      total_candidates: 42,
      truncated: true,
      offset: 0,
      limit: 50,
      status: 'done',
    })
    apiMocks.getFrequencyResult.mockResolvedValue({
      rows: [{ item: 'Lemma', frequency: 4, relative: 0.004 }],
      groupBy: 'lemma',
      truncated: false,
    })
    useCorpusCapabilitiesStore().corpora = [corpusSummary()]
  })

  it('runs word frequency through the observable job lifecycle when the contract exposes it', async () => {
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/frequency',
      payload: { groupBy: 'word', limit: 50 },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('frequency')
    expect(apiMocks.createFrequencyListJob).toHaveBeenCalledWith(expect.objectContaining({
      groupBy: 'word',
      corpus: 'default',
      limit: 50,
    }))
    expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-frequency-1')
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-frequency-1', 0, 50)
    expect(apiMocks.getFrequencyResult).not.toHaveBeenCalled()
    expect(analysisJobs.snapshotFor('job-frequency-1')).toMatchObject({
      job_id: 'job-frequency-1',
      status: 'done',
    })
    expect(result.data).toMatchObject({
      groupBy: 'word',
      rowLimit: 50,
      totalCandidates: 42,
      truncated: true,
    })
    expect(result.data?.rows?.[0]).toMatchObject({ item: 'Hase', frequency: 8, relative: 8 / 11 })
    expect(result.executionScope).toMatchObject({ corpusId: 'default', scopeStatus: 'corpus' })
  })

  it('falls back to the synchronous list endpoint for non-word frequency groups', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/frequency',
      payload: { groupBy: 'lemma', limit: 20 },
    })

    expect(result.success).toBe(true)
    expect(apiMocks.createFrequencyListJob).not.toHaveBeenCalled()
    expect(apiMocks.getFrequencyResult).toHaveBeenCalledWith(
      expect.objectContaining({
        groupBy: 'lemma',
        corpus: 'default',
        limit: 20,
      }),
      expect.any(Object),
    )
  })
})
