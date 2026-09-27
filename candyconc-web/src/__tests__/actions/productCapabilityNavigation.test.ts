import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getFrequency: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  executeQuery: vi.fn(),
  executeQueryStreaming: vi.fn(),
  getQueryCount: vi.fn(),
  getMetaSchema: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getCorpusCapabilities: (...args: unknown[]) => apiMocks.getCorpusCapabilities(...args),
    getFrequency: (...args: unknown[]) => apiMocks.getFrequency(...args),
    executeQuery: (...args: unknown[]) => apiMocks.executeQuery(...args),
    executeQueryStreaming: (...args: unknown[]) => apiMocks.executeQueryStreaming(...args),
    getQueryCount: (...args: unknown[]) => apiMocks.getQueryCount(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
  }
})

import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductOperationRunsStore } from '@/stores/productOperationRuns'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

function capability(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    limits: [],
    ...overrides,
  }
}

function route(path: string, methods = ['GET']) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(capabilityId: string, id: string, path: string, label: string) {
  return {
    id,
    capability_id: capabilityId,
    label,
    description: '',
    route: route(path),
    effects: ['read'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: id,
    priority: id.endsWith('snippet') ? 10 : 20,
  }
}

function documentAccessCapability(options: { includeSnippet?: boolean } = {}) {
  const includeSnippet = options.includeSnippet ?? true
  const backendRoutes = includeSnippet
    ? ['/api/v1/doc/snippet', '/api/v1/document/{doc_id}']
    : ['/api/v1/document/{doc_id}']
  const descriptors = includeSnippet
    ? [
        route('/api/v1/doc/snippet'),
        route('/api/v1/document/{doc_id}'),
      ]
    : [route('/api/v1/document/{doc_id}')]
  const operations = [
    ...(includeSnippet
      ? [operation('query.document_access', 'query.document_access.snippet', '/api/v1/doc/snippet', 'Dokument-Snippet')]
      : []),
    operation('query.document_access', 'query.document_access.full_text', '/api/v1/document/{doc_id}', 'Dokument öffnen'),
  ]
  return capability('query.document_access', {
    backend_routes: backendRoutes,
    backend_route_descriptors: descriptors,
    operations,
    action_types: ['nav/openDocument'],
  })
}

function kwicOperations() {
  return [
    operation('query.kwic', 'query.kwic.page', '/api/v1/query', 'KWIC-Trefferseite'),
    operation('query.kwic', 'query.kwic.stream', '/api/v1/query/stream', 'KWIC-Stream'),
    operation('query.kwic', 'query.kwic.count', '/api/v1/query/count', 'KWIC-Zählung'),
  ]
}

function contract(
  overrides: Record<string, unknown> = {},
  extraCapabilities: ReturnType<typeof capability>[] = []
) {
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
      capability('query.kwic', {
        backend_routes: ['/api/v1/query/stream', '/api/v1/query'],
        backend_route_descriptors: [
          route('/api/v1/query/stream'),
          route('/api/v1/query'),
        ],
        operations: kwicOperations(),
        action_types: ['query/execute', 'query/loadMore'],
      }),
      capability('analysis.frequency', {
        title: 'Frequenzliste',
        backend_routes: ['/api/v1/analysis/frequency_list'],
        backend_route_descriptors: [
          route('/api/v1/analysis/frequency_list'),
        ],
        action_types: ['analysis/frequency'],
        ...overrides,
      }),
      capability('analysis.collocations', {
        backend_routes: ['/api/v1/analysis/collocates/kwic'],
        backend_route_descriptors: [
          route('/api/v1/analysis/collocates/kwic'),
        ],
        action_types: ['analysis/collocations'],
      }),
      ...extraCapabilities,
    ],
  }
}

function wordOnlyCorpus() {
  return {
    name: 'default',
    path: '/corpora/default',
    token_count: 100,
    doc_count: 1,
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

describe('Product Capability navigation guard', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    actionBus.releaseLock()
    actionBus.clearHistory()
    vi.clearAllMocks()
    apiMocks.getProductCapabilities.mockResolvedValue(contract())
    apiMocks.getCorpusCapabilities.mockResolvedValue(wordOnlyCorpus())
    apiMocks.getFrequency.mockResolvedValue({ rows: [], total: 0 })
    apiMocks.executeQuery.mockResolvedValue({ hits: [], total: 0, next_offset: null, truncated: false })
    apiMocks.executeQueryStreaming.mockImplementation(async function* () {
      yield { type: 'count', total: 1, partial: false, elapsed_ms: 1 }
      yield {
        type: 'batch',
        hits: [
          {
            position: 1,
            left: 'ein',
            match: 'Hase',
            right: 'läuft',
            doc_id: 'doc-1',
            doc_title: 'Doc 1',
          },
        ],
      }
      yield { type: 'done', total: 1, partial: false, next_offset: null, query_time_ms: 2 }
    })
    apiMocks.getQueryCount.mockResolvedValue({ status: 'ready', total: 1, partial: false })
    apiMocks.getMetaSchema.mockResolvedValue({ fields: [] })
  })

  it('blocks unknown tabs fail-closed', async () => {
    const uiStore = useUiStore()
    uiStore.setActiveTab('kwic')

    const result = await actionBus.dispatch(
      { type: 'nav/switchTab', payload: { tab: 'document' } } as never,
      { source: 'restore' }
    )

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('document')
    expect(uiStore.activeTab).toBe('kwic')
  })

  it('blocks hidden analysis tabs before starting backend work', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(contract({ maturity: 'planned' }))
    const uiStore = useUiStore()
    uiStore.setActiveTab('kwic')

    const result = await actionBus.dispatch({
      type: 'analysis/frequency',
      payload: { limit: 10 },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Frequenzliste')
    expect(apiMocks.getFrequency).not.toHaveBeenCalled()
    expect(uiStore.activeTab).toBe('kwic')
  })

  it('blocks CQLF query execution before backend work when the capability is hidden', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults([{ position: 1, left: 'ein', match: 'Hase', right: 'läuft' }], 1, true, false)

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'cql:[word=\"Hase\"]' },
    })

    expect(result).toMatchObject({ success: false, blocked: true, error: 'capability_not_visible' })
    expect(apiMocks.executeQueryStreaming).not.toHaveBeenCalled()
    expect(apiMocks.executeQuery).not.toHaveBeenCalled()
    expect(apiMocks.getQueryCount).not.toHaveBeenCalled()
    // Never leave evidence for the previous query visible below a newly rejected
    // query. That would let a researcher mistake Hase hits for CQLF hits.
    expect(queryStore.term).toBe('cql:[word="Hase"]')
    expect(queryStore.results).toHaveLength(0)
    expect(queryStore.totalHits).toBe(0)
  })

  it.each([
    { term: '[word=\"Hase\"]', expectedError: 'capability_not_visible' },
    { term: 'sim(\"Hase\", k=5)', expectedError: 'capability_not_visible' },
    {
      term: 'co(term=\"cql:[word=\\\\\"Hase\\\\\"]\", collocate=\"schnell\", window=5)',
      expectedError: 'Serverfunktion',
    },
  ])('blocks CQLF-compatible query form before backend work: $term', async ({ term, expectedError }) => {
    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain(expectedError)
    expect(apiMocks.executeQueryStreaming).not.toHaveBeenCalled()
    expect(apiMocks.executeQuery).not.toHaveBeenCalled()
    expect(apiMocks.getQueryCount).not.toHaveBeenCalled()
  })

  it('keeps plain KWIC executable while CQLF is hidden', async () => {
    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'Hase' },
    })

    expect(result.success).toBe(true)
    expect(apiMocks.executeQueryStreaming).toHaveBeenCalledTimes(1)
    expect(apiMocks.executeQueryStreaming.mock.calls[0][0]).toMatchObject({ term: 'Hase' })

    const streamRun = useProductOperationRunsStore().records.find((run) =>
      run.operationId === 'query.kwic.stream'
    )
    expect(streamRun).toMatchObject({
      kind: 'operation',
      surfaceId: 'query.kwic',
      status: 'succeeded',
      phase: 'window_loaded',
      readiness: 'window_loaded',
      detail: 'Hase',
    })
    expect(streamRun?.evidence).toMatchObject({
      term: 'Hase',
      corpus: 'default',
      direction: 'initial',
      offset: 0,
      receivedHits: 1,
      total: 1,
      partial: false,
    })
  })

  it('blocks CQLF pagination before backend work when the capability is hidden', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('cql:[word=\"Hase\"]')
    queryStore.setResults([{ position: 1, left: 'ein', match: 'Hase', right: 'läuft' }], 2, false, true)
    queryStore.setHasMore(true)
    queryStore.setNextOffset(1)

    const result = await actionBus.dispatch({
      type: 'query/loadMore',
      payload: {},
    })

    expect(result).toMatchObject({ success: false, blocked: true, error: 'capability_not_visible' })
    expect(apiMocks.executeQueryStreaming).not.toHaveBeenCalled()
    expect(apiMocks.executeQuery).not.toHaveBeenCalled()
  })

  it('allows CQLF query execution when the capability is first-class', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(contract({}, [capability('query.cqlf')]))
    useCorpusCapabilitiesStore().corpora = [wordOnlyCorpus()]

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'cql:[word=\"Hase\"]' },
    })

    expect(result.success).toBe(true)
    expect(apiMocks.executeQueryStreaming).toHaveBeenCalledTimes(1)
    expect(apiMocks.executeQueryStreaming.mock.calls[0][0]).toMatchObject({ term: 'cql:[word=\"Hase\"]' })
  })

  it('opens document details with the matched KWIC position as evidential anchor', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(contract({}, [documentAccessCapability()]))
    const queryStore = useQueryStore()
    const uiStore = useUiStore()
    queryStore.setResults([
      {
        position: 42,
        left: 'von',
        match: 'Hase',
        right: 'läuft',
        docId: 'doc-1',
        docTitle: 'Doc 1',
        metadata: { source: 'test-corpus' },
      },
    ], 1, true, false)

    const result = await actionBus.dispatch({
      type: 'nav/openDocument',
      payload: { docId: 'doc-1', highlightPosition: 42 },
    })

    expect(result.success).toBe(true)
    expect(queryStore.highlightedRow).toBe(0)
    expect(uiStore.documentDetailOpen).toBe(true)
    expect(uiStore.documentDetail).toMatchObject({
      docId: 'doc-1',
      corpus: 'default',
      fallbackLabel: 'Doc 1',
      fallbackMeta: { source: 'test-corpus' },
      highlight: 'Hase',
      highlightPosition: 42,
      highlightLeft: 'von',
      highlightRight: 'läuft',
    })
  })

  it('opens positioned document details even when the optional snippet operation is not offered', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(contract({}, [
      documentAccessCapability({ includeSnippet: false }),
    ]))
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'nav/openDocument',
      payload: {
        docId: 'doc-9',
        corpus: 'corpus-a',
        highlight: 'Hase',
        highlightPosition: 99,
        highlightLeft: 'ein',
        highlightRight: 'läuft',
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.documentDetail).toMatchObject({
      docId: 'doc-9',
      corpus: 'corpus-a',
      highlight: 'Hase',
      highlightPosition: 99,
      highlightLeft: 'ein',
      highlightRight: 'läuft',
    })
  })
})
