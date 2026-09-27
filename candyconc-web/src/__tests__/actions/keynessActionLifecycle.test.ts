import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  createKeynessJob: vi.fn(),
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
    createKeynessJob: (...args: unknown[]) => apiMocks.createKeynessJob(...args),
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
      capability('analysis.keyness', {
        backend_routes: ['/api/v1/analysis/keyness/job'],
        backend_route_descriptors: [route('/api/v1/analysis/keyness/job', 'POST')],
        operations: [
          operation(
            'analysis.keyness',
            'analysis.keyness.job',
            '/api/v1/analysis/keyness/job',
            'POST',
            'Keyness-Job',
          ),
        ],
        action_types: ['analysis/keyness'],
        copilot_tools: ['keyness'],
      }),
      capability('analysis.async_jobs', {
        backend_routes: includeRowsOperation
          ? ['/api/v1/analysis/jobs/{job_id}', '/api/v1/analysis/jobs/{job_id}/rows']
          : ['/api/v1/analysis/jobs/{job_id}'],
        backend_route_descriptors: includeRowsOperation
          ? [route('/api/v1/analysis/jobs/{job_id}', 'GET'), route('/api/v1/analysis/jobs/{job_id}/rows', 'GET')]
          : [route('/api/v1/analysis/jobs/{job_id}', 'GET')],
        operations: [
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
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }
}

describe('analysis/keyness action lifecycle', () => {
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
    apiMocks.createKeynessJob.mockResolvedValue({ job_id: 'job-keyness-1' })
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-keyness-1',
      kind: 'keyness',
      corpus: 'default',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
  })

  it('runs keyness through ProductOperation and async-job gates without inventing reference defaults', async () => {
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-keyness-1',
      rows: [{ item: 'Hase', score: 12.5, target: 9, reference: 1 }],
      total_rows: 1,
      row_limit: 100,
      total_candidates: 30,
      truncated: false,
      offset: 0,
      limit: 100,
      status: 'done',
      method: { family: 'keyness' },
    })
    const analysisJobs = useAnalysisJobsStore()
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/keyness',
      payload: {
        targetDocsetId: 'target-docset',
        referenceDocsetId: 'reference-docset',
        corpus: 'default',
        minFreq: 7,
        limit: 100,
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('keyness')
    expect(apiMocks.createKeynessJob).toHaveBeenCalledWith({
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
      pos: undefined,
      corpus: 'default',
      referenceSource: 'docset',
      referenceCorpus: undefined,
      minFreq: 7,
    })
    expect(apiMocks.getAnalysisJob).toHaveBeenCalledWith('job-keyness-1')
    expect(apiMocks.getAnalysisJobRows).toHaveBeenCalledWith('job-keyness-1', 0, 100)
    expect(analysisJobs.snapshotFor('job-keyness-1')).toMatchObject({
      job_id: 'job-keyness-1',
      status: 'done',
    })
    expect(result.data).toMatchObject({
      rows: [{ item: 'Hase', score: 12.5, target: 9, reference: 1 }],
      rowLimit: 100,
      totalCandidates: 30,
      totalRows: 1,
      truncated: false,
      referenceSource: 'docset',
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
      minFreq: 7,
    })
    expect(result.executionScope).toMatchObject({
      corpusId: 'default',
      docsetId: 'target-docset',
      label: 'Docset target-docset',
    })
  })

  it('blocks keyness before backend execution when no explicit reference is available', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/keyness',
      payload: {
        targetDocsetId: 'target-docset',
        corpus: 'default',
      },
    })

    expect(result.success).toBe(false)
    expect(result.error).toContain('explizite Referenz')
    expect(apiMocks.createKeynessJob).not.toHaveBeenCalled()
  })

  it('does not start keyness when async row retrieval is missing from the ProductOperation contract', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(productContract({ includeRowsOperation: false }))

    const result = await actionBus.dispatch({
      type: 'analysis/keyness',
      payload: {
        targetDocsetId: 'target-docset',
        referenceDocsetId: 'reference-docset',
        corpus: 'default',
      },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Serverfunktion')
    expect(apiMocks.createKeynessJob).not.toHaveBeenCalled()
  })
})
