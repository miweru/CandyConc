import { beforeAll, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  getCollocationNetwork: vi.fn(),
  getMetaSchema: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getCorpusCapabilities: (...args: unknown[]) => apiMocks.getCorpusCapabilities(...args),
    getCollocationNetwork: (...args: unknown[]) => apiMocks.getCollocationNetwork(...args),
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
    effects: ['read'],
    handler_key: 'collocation_network',
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

function productContract(options: { includeGraphOperation?: boolean } = {}) {
  const includeGraphOperation = options.includeGraphOperation ?? true
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
      capability('analysis.collocation_network', {
        backend_routes: ['/api/v1/analysis/collocation_network'],
        backend_route_descriptors: [route('/api/v1/analysis/collocation_network', 'GET')],
        operations: includeGraphOperation
          ? [
              operation(
                'analysis.collocation_network',
                'analysis.collocation_network.graph',
                '/api/v1/analysis/collocation_network',
                'GET',
                'Kollokationsnetzwerk',
              ),
            ]
          : [],
        action_types: ['analysis/collocationNetwork'],
        copilot_tools: ['collocation_network'],
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

describe('analysis/collocationNetwork action lifecycle', () => {
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
    apiMocks.getCollocationNetwork.mockResolvedValue({
      term: 'Klima',
      measure: 'logdice',
      nodes: [{ id: 'Klima', freq: 10, depth: 0 }],
      edges: [],
      diagnostics: { truncated: false },
    })
  })

  it('runs the collocation network through the ProductOperation facade and returns evidence', async () => {
    const uiStore = useUiStore()

    const result = await actionBus.dispatch({
      type: 'analysis/collocationNetwork',
      payload: {
        term: 'Klima',
        windowSize: 4,
        measure: 'logdice',
        maxNodes: 25,
        expandDepth: 2,
        withinSentence: false,
      },
    })

    expect(result.success).toBe(true)
    expect(uiStore.activeTab).toBe('collocation_network')
    expect(apiMocks.getCollocationNetwork).toHaveBeenCalledWith({
      term: 'Klima',
      window: 4,
      measure: 'logdice',
      maxNodes: 25,
      expandDepth: 2,
      minCount: undefined,
      withinSentence: false,
      corpus: 'default',
      docsetId: undefined,
    })
    expect(result.data).toMatchObject({
      term: 'Klima',
      nodes: [{ id: 'Klima', freq: 10, depth: 0 }],
      diagnostics: { truncated: false },
    })
    expect(result.executionScope).toMatchObject({ corpusId: 'default', scopeStatus: 'corpus' })
  })

  it('does not run the backend when the graph ProductOperation is missing', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(productContract({ includeGraphOperation: false }))
    const uiStore = useUiStore()
    uiStore.setActiveTab('kwic')

    const result = await actionBus.dispatch({
      type: 'analysis/collocationNetwork',
      payload: { term: 'Klima' },
    })

    expect(result).toMatchObject({ success: false, blocked: true })
    expect(result.error).toContain('Serverfunktion')
    expect(apiMocks.getCollocationNetwork).not.toHaveBeenCalled()
    expect(uiStore.activeTab).toBe('kwic')
  })
})
