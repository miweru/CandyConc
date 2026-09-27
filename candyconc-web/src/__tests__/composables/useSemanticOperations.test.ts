import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { SEMANTIC_OPERATIONS, SEMANTIC_ROUTES, useSemanticOperations } from '@/composables/useSemanticOperations'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getSimilarWords: vi.fn(),
  semanticSearchWithMeta: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getSimilarWords: (...args: unknown[]) => apiMocks.getSimilarWords(...args),
    semanticSearchWithMeta: (...args: unknown[]) => apiMocks.semanticSearchWithMeta(...args),
  }
})

function route(path: string, method: 'GET' | 'POST', feature: string) {
  return {
    path,
    methods: [method],
    mutates: false,
    requires_corpus_features: [feature],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const similarRoute = route(SEMANTIC_ROUTES.similarWords, 'GET', 'semantic.word_similarity')
  const passageRoute = route(SEMANTIC_ROUTES.passageSearch, 'POST', 'semantic.passage_search')
  return {
    id: 'analysis.semantic_similarity',
    title: 'Semantic similarity',
    area: 'analysis',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [similarRoute, passageRoute],
    backend_route_descriptors: [similarRoute, passageRoute],
    operations: [
      {
        id: SEMANTIC_OPERATIONS.similarWords,
        capability_id: 'analysis.semantic_similarity',
        label: 'Distributioneller Wort-Thesaurus',
        description: '',
        route: similarRoute,
        effects: ['read'],
        handler_key: 'similar_words',
        surface_slot: 'analysis.semantic_similarity.words',
        priority: 10,
      },
      {
        id: SEMANTIC_OPERATIONS.passageSearch,
        capability_id: 'analysis.semantic_similarity',
        label: 'Semantische Passagensuche',
        description: '',
        route: passageRoute,
        effects: ['read'],
        handler_key: 'semantic_passage_search',
        surface_slot: 'analysis.semantic_similarity.passages',
        priority: 20,
      },
    ],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

function contract(item: ProductCapability): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [item],
  }
}

function seedUserSession() {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
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
  }
}

function seedSemanticCorpusFeatures() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      semantic: {
        passage_search: true,
        word_similarity: true,
        sentence_alignment: false,
      },
      alignment: {
        paired: false,
        pair_axes: [],
        parallel_groups: false,
        parallel_kwic: false,
      },
    },
  }]
}

describe('useSemanticOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
    seedSemanticCorpusFeatures()
  })

  it('blocks similar-words loading when the semantic operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({ operations: [] }))
    productCapabilities.status = 'ready'

    const { loadSimilarWords } = useSemanticOperations()

    await expect(loadSimilarWords({ term: 'Sprache' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.getSimilarWords).not.toHaveBeenCalled()
  })

  it('routes passage search through ProductOperation availability', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'
    apiMocks.semanticSearchWithMeta.mockResolvedValue({ rows: [], meta: {} })

    const { searchPassages, canSearchPassages } = useSemanticOperations()

    await expect(searchPassages({ query: 'Sprache', corpus: 'demo' })).resolves.toEqual({
      rows: [],
      meta: {},
    })
    expect(canSearchPassages.value).toBe(true)
    expect(apiMocks.semanticSearchWithMeta).toHaveBeenCalledWith({ query: 'Sprache', corpus: 'demo' })
  })
})
