import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const getProductCapabilities = vi.hoisted(() => vi.fn())
const getCorpusCapabilities = vi.hoisted(() => vi.fn())
const getAuthSession = vi.hoisted(() => vi.fn())

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
    getCorpusCapabilities: (...args: unknown[]) => getCorpusCapabilities(...args),
    getAuthSession: (...args: unknown[]) => getAuthSession(...args),
    executeQueryStreaming: vi.fn(async function* () {
      yield { type: 'done', total: 0, partial: false, next_offset: null, query_time_ms: 1 }
    }),
    executeQuery: vi.fn(async () => ({
      hits: [],
      total: 0,
      query_time_ms: 1,
      next_offset: null,
      truncated: false,
      sortApproximate: false,
    })),
    getQueryCount: vi.fn(async () => ({ status: 'ready', total: 0, partial: false })),
    getFrequency: vi.fn(async () => ({ rows: [], total: 0 })),
    getFrequencyResult: vi.fn(async () => ({ rows: [], groupBy: 'word' })),
    getSimilarWords: vi.fn(async () => ({ words: [], meta: {} })),
    semanticSearchWithMeta: vi.fn(async () => ({ rows: [], meta: {} })),
    getMetaSchema: vi.fn(async () => ({ fields: [] })),
  }
})

import * as api from '@/api/client'
import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

function route(path: string, methods = ['GET'], requiresCorpusFeatures: string[] = []) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: requiresCorpusFeatures,
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(
  capabilityId: string,
  id: string,
  path: string,
  label: string,
  methods = ['GET'],
  requiresCorpusFeatures: string[] = [],
) {
  return {
    id,
    capability_id: capabilityId,
    label,
    description: '',
    route: route(path, methods, requiresCorpusFeatures),
    effects: ['read'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: id,
    priority: 10,
  }
}

function productContract() {
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
      {
        id: 'corpus.catalogue',
        title: 'corpus.catalogue',
        area: 'corpus',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/corpora/{corpus}/capabilities'],
        backend_route_descriptors: [
          route('/api/v1/corpora/{corpus}/capabilities'),
        ],
        operations: [
          operation(
            'corpus.catalogue',
            'corpus.catalogue.capabilities',
            '/api/v1/corpora/{corpus}/capabilities',
            'Korpusfähigkeiten laden',
          ),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        limits: [],
      },
      {
        id: 'query.kwic',
        title: 'query.kwic',
        area: 'query',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/query/stream', '/api/v1/query'],
        backend_route_descriptors: [
          route('/api/v1/query/stream'),
          route('/api/v1/query'),
        ],
        operations: [
          operation('query.kwic', 'query.kwic.stream', '/api/v1/query/stream', 'KWIC-Stream'),
          operation('query.kwic', 'query.kwic.page', '/api/v1/query', 'KWIC-Trefferseite'),
        ],
        frontend_evidence: [],
        action_types: ['query/execute', 'query/loadMore'],
        copilot_tools: [],
        preconditions: [],
        limits: [],
      },
      {
        id: 'query.cqlf',
        title: 'query.cqlf',
        area: 'query',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/query/analyse', '/api/v1/query/lexicon/suggest'],
        backend_route_descriptors: [
          route('/api/v1/query/analyse', ['POST']),
          route('/api/v1/query/lexicon/suggest', ['POST']),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        limits: [],
      },
      {
        id: 'analysis.frequency',
        title: 'analysis.frequency',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/analysis/frequency_list'],
        backend_route_descriptors: [
          route('/api/v1/analysis/frequency_list'),
        ],
        operations: [
          operation('analysis.frequency', 'analysis.frequency.list', '/api/v1/analysis/frequency_list', 'Frequenzliste'),
        ],
        frontend_evidence: [],
        action_types: ['analysis/frequency'],
        copilot_tools: ['frequency_list'],
        preconditions: [],
        limits: [],
      },
      {
        id: 'analysis.semantic_similarity',
        title: 'analysis.semantic_similarity',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/semantic/similar_words', '/api/v1/analysis/embedding_search'],
        backend_route_descriptors: [
          route('/api/v1/semantic/similar_words', ['GET'], ['semantic.word_similarity']),
          route('/api/v1/analysis/embedding_search', ['POST'], ['semantic.passage_search']),
        ],
        operations: [
          operation(
            'analysis.semantic_similarity',
            'analysis.semantic_similarity.similar_words',
            '/api/v1/semantic/similar_words',
            'Distributioneller Thesaurus',
            ['GET'],
            ['semantic.word_similarity'],
          ),
          operation(
            'analysis.semantic_similarity',
            'analysis.semantic_similarity.passage_search',
            '/api/v1/analysis/embedding_search',
            'Semantische Passagensuche',
            ['POST'],
            ['semantic.passage_search'],
          ),
        ],
        frontend_evidence: [],
        action_types: ['analysis/semantic'],
        copilot_tools: ['similar_words', 'document_search'],
        preconditions: [],
        requires_corpus_features: ['semantic.passage_search', 'semantic.word_similarity'],
        limits: [],
      },
      {
        id: 'analysis.wordsketch',
        title: 'analysis.wordsketch',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/analysis/wordsketch'],
        backend_route_descriptors: [
          route('/api/v1/analysis/wordsketch', ['POST'], ['token_attributes.rel']),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: ['word_sketch'],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
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

function wordSimilarityCorpus() {
  return {
    ...wordOnlyCorpus(),
    features: {
      ...wordOnlyCorpus().features,
      semantic: { passage_search: false, word_similarity: true, sentence_alignment: false },
    },
  }
}

describe('action corpus feature gates', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getProductCapabilities.mockResolvedValue(productContract())
    getCorpusCapabilities.mockResolvedValue(wordOnlyCorpus())
    getAuthSession.mockResolvedValue({
      schema_version: 'auth-session-v1',
      authenticated: true,
      token_present: true,
      username: 'analyst',
      role: 'user',
      effective_role: 'user',
      rbac_enabled: true,
      security_mode: 'release',
      release_mode: true,
      unsafe_token_transport: false,
      dev_token_available: false,
      can_access_all_roles: false,
    })
  })

  it('blocks CQLF token attributes that the active corpus does not provide', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults([{
      position: 7,
      left: 'alter',
      match: 'Hase',
      right: 'läuft',
      docId: 'doc-7',
    }], 1, true)

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'cql:[lemma="gehen"]' },
    })

    expect(result.success).toBe(false)
    expect(result.error).toBe('corpus_feature_not_available')
    expect(result.policyReason).toBe('Der aktive Korpus unterstützt diese CQLF-Attribute nicht: lemma.')
    expect(queryStore.term).toBe('cql:[lemma="gehen"]')
    expect(queryStore.results).toEqual([])
    expect(queryStore.totalHits).toBe(0)
    expect(queryStore.error).toBe('Der aktive Korpus unterstützt diese CQLF-Attribute nicht: lemma.')
    expect(api.executeQueryStreaming).not.toHaveBeenCalled()
    expect(api.executeQuery).not.toHaveBeenCalled()
  })

  it('clears stale evidence and explains backend parser errors without parser jargon', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults([{
      position: 7,
      left: 'alter',
      match: 'Hase',
      right: 'läuft',
      docId: 'doc-7',
    }], 1, true)
    vi.mocked(api.executeQueryStreaming).mockImplementationOnce(async function* () {
      yield { type: 'error', error: 'CQL Parse Fehler: expected value, got RBRACK:] at 6:7' }
    })

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'cql:[word=]' },
    })

    expect(result.success).toBe(false)
    expect(queryStore.term).toBe('cql:[word=]')
    expect(queryStore.results).toEqual([])
    expect(queryStore.totalHits).toBe(0)
    expect(queryStore.error).toBe('CQL-Syntaxfehler: Nach „=“ fehlt ein Wert. Beispiel: cql:[word="Hase"].')
    expect(queryStore.error).not.toContain('RBRACK')
  })

  it('blocks unsupported frequency groups before hitting the API', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/frequency',
      payload: { groupBy: 'lemma' },
    })

    expect(result.success).toBe(false)
    expect(result.error).toBe('corpus_feature_not_available')
    expect(api.getFrequencyResult).not.toHaveBeenCalled()
  })

  it('allows word-only frequency requests on a word-only corpus', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/frequency',
      payload: { groupBy: 'word' },
    })

    expect(result.success).toBe(true)
    expect(api.getFrequencyResult).toHaveBeenCalledTimes(1)
    expect(api.getFrequencyResult).toHaveBeenCalledWith(
      expect.objectContaining({ groupBy: 'word' }),
      {},
    )
  })

  it('blocks analysis tab navigation when the active corpus lacks required contract features', async () => {
    const result = await actionBus.dispatch({
      type: 'nav/switchTab',
      payload: { tab: 'wordsketch' },
    })

    expect(result.success).toBe(false)
    expect(result.error).toBe('corpus_feature_not_available')
  })

  it('blocks semantic passage actions before mutating the active tab', async () => {
    getCorpusCapabilities.mockResolvedValueOnce(wordSimilarityCorpus())
    const uiStore = useUiStore()
    uiStore.setActiveTab('kwic')

    const result = await actionBus.dispatch({
      type: 'analysis/semantic',
      payload: { query: 'alpha', mode: 'passage', topK: 10 },
    })

    expect(result.success).toBe(false)
    expect(result.error).toBe('corpus_feature_not_available')
    expect(uiStore.activeTab).toBe('kwic')
    expect(api.semanticSearchWithMeta).not.toHaveBeenCalled()
    expect(api.getSimilarWords).not.toHaveBeenCalled()
  })
})
