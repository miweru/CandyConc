import { describe, it, expect, beforeAll, beforeEach, vi, type Mock } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const getProductCapabilities = vi.hoisted(() => vi.fn())
const getCorpusCapabilities = vi.hoisted(() => vi.fn())

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
    getCorpusCapabilities: (...args: unknown[]) => getCorpusCapabilities(...args),
    semanticSearchWithMeta: vi.fn(async () => ({
      rows: [
        {
          doc_id: '7',
          chunk_id: '7:0',
          text: 'Klima und Energie',
          score: 0.91,
          metadata: { source: 'news', year: 2026, flags: ['ai'] },
        },
      ],
      meta: {
        exactness: 'approximate',
        candidateGeneration: {
          method: 'faiss_passage',
          searchMode: 'approximate',
          candidateCount: 12,
        },
        rerank: { enabled: true, inputCount: 12, outputCount: 1 },
        filtering: { docsetApplied: false },
      },
    })),
    semanticSearch: vi.fn(async () => {
      throw new Error('analysis/semantic must use semanticSearchWithMeta')
    }),
    getSimilarWords: vi.fn(async () => ({
      term: 'Klima',
      backend: 'faiss',
      neighbours: [
        { word: 'Energie', score: 0.82, corpusFrequency: 12 },
      ],
      unavailable: false,
    })),
    getMetaSchema: vi.fn(async () => ({ fields: [] })),
  }
})

import * as api from '@/api/client'
import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'

function semanticOperation(
  id: string,
  path: string,
  label: string,
  methods: string[],
  requiresCorpusFeatures: string[],
) {
  return {
    id,
    capability_id: 'analysis.semantic_similarity',
    label,
    description: '',
    route: {
      path,
      methods,
      mutates: methods.some((method) => method !== 'GET'),
      requires_corpus_features: requiresCorpusFeatures,
    },
    effects: ['read'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: id,
    priority: 10,
  }
}

describe('analysis/semantic metadata propagation', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getProductCapabilities.mockResolvedValue({
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
            {
              path: '/api/v1/corpora/{corpus}/capabilities',
              methods: ['GET'],
              mutates: false,
              requires_corpus_features: [],
            },
          ],
          operations: [
            {
              id: 'corpus.catalogue.capabilities',
              capability_id: 'corpus.catalogue',
              label: 'Korpusfähigkeiten laden',
              description: '',
              route: {
                path: '/api/v1/corpora/{corpus}/capabilities',
                methods: ['GET'],
                mutates: false,
                requires_corpus_features: [],
              },
              effects: ['read'],
              handler_key: 'corpus_catalogue_capabilities',
              surface_slot: 'corpus.catalogue.capabilities',
              priority: 10,
            },
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
          backend_routes: [],
          frontend_evidence: [],
          action_types: [],
          copilot_tools: [],
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
            {
              path: '/api/v1/semantic/similar_words',
              methods: ['GET'],
              mutates: false,
              requires_corpus_features: ['semantic.word_similarity'],
            },
            {
              path: '/api/v1/analysis/embedding_search',
              methods: ['POST'],
              mutates: false,
              requires_corpus_features: ['semantic.passage_search'],
            },
          ],
          operations: [
            semanticOperation(
              'analysis.semantic_similarity.similar_words',
              '/api/v1/semantic/similar_words',
              'Distributioneller Thesaurus',
              ['GET'],
              ['semantic.word_similarity'],
            ),
            semanticOperation(
              'analysis.semantic_similarity.passage_search',
              '/api/v1/analysis/embedding_search',
              'Semantische Passagensuche',
              ['POST'],
              ['semantic.passage_search'],
            ),
          ],
          frontend_evidence: [],
          action_types: ['analysis/semantic'],
          copilot_tools: [],
          preconditions: [],
          limits: [],
        },
      ],
    })
    getCorpusCapabilities.mockResolvedValue({
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
        token_attributes: [
          { id: 'word', cql_attribute: 'word', label: 'Wortform' },
          { id: 'sim', cql_attribute: 'sim', label: 'Semantik' },
        ],
        frequency_groups: [{ id: 'word', label: 'Wortform' }],
        semantic: { passage_search: true, word_similarity: true, sentence_alignment: false },
      },
    })
  })

  it('returns semantic rows together with backend metadata', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/semantic',
      payload: { query: 'Klima', topK: 3 },
    })

    expect(result.success).toBe(true)
    expect(api.semanticSearchWithMeta).toHaveBeenCalledTimes(1)
    expect(api.semanticSearch).not.toHaveBeenCalled()
    expect((api.semanticSearchWithMeta as Mock).mock.calls[0][0]).toMatchObject({
      query: 'Klima',
      top_k: 3,
    })
    expect(result.data).toMatchObject({
      rows: [{ doc_id: '7', metadata: { source: 'news', year: 2026, flags: ['ai'] } }],
      meta: {
        exactness: 'approximate',
        candidateGeneration: { method: 'faiss_passage', searchMode: 'approximate', candidateCount: 12 },
        rerank: { enabled: true, inputCount: 12, outputCount: 1 },
        filtering: { docsetApplied: false },
      },
    })
  })

  it('routes thesaurus mode to similar_words instead of passage embedding search', async () => {
    const result = await actionBus.dispatch({
      type: 'analysis/semantic',
      payload: { query: 'Klima', topK: 8, mode: 'thesaurus' },
    })

    expect(result.success).toBe(true)
    expect(api.getSimilarWords).toHaveBeenCalledTimes(1)
    expect(api.semanticSearchWithMeta).not.toHaveBeenCalled()
    expect((api.getSimilarWords as Mock).mock.calls[0][0]).toMatchObject({
      term: 'Klima',
      k: 8,
    })
    expect(result.data).toMatchObject({
      term: 'Klima',
      neighbours: [{ word: 'Energie' }],
    })
  })
})
