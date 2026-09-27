import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SemanticTab from '@/components/analysis/SemanticTab.vue'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, useSessionStore, useUiStore } from '@/stores'
import {
  getSimilarWords,
  getProductCapabilities,
  SemanticSearchError,
  semanticSearchWithMeta,
  SimilarWordsUnavailableError,
} from '@/api/client'
import { applyLocale } from '@/i18n/locale'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    semanticSearchWithMeta: vi.fn(),
    getSimilarWords: vi.fn(),
    getProductCapabilities: vi.fn(async () => { throw new Error('offline') }),
    getMcpTools: vi.fn().mockResolvedValue({ tools: [] }),
  }
})

vi.mock('@/actions', () => ({
  actionBus: { dispatch: vi.fn() },
}))

vi.mock('@/composables', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables')>()
  return {
    ...actual,
    useActions: vi.fn(),
    useMobileDetection: () => ({ isMobile: false }),
  }
})

const stubs = {
  AnalysisToolbar: { template: '<div class="toolbar"><slot name="left" /><slot name="right" /></div>' },
  SaveAnalysisButton: { template: '<div />' },
  JobStatusPill: { template: '<div />' },
  Skeleton: { template: '<div />' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state"><strong>{{ title }}</strong>{{ description }}<slot /></div>' },
}

function seedProductCapabilities() {
  const productCapabilities = useProductCapabilitiesStore()
  const similarWordsRoute = {
    path: '/api/v1/semantic/similar_words',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: ['semantic.word_similarity'],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
  const passageRoute = {
    path: '/api/v1/analysis/embedding_search',
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: ['semantic.passage_search'],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
  const embeddingListRoute = {
    path: '/api/v1/embeddings/list',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
  const embeddingDownloadRoute = {
    path: '/api/v1/embeddings/download',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  } as const
  const embeddingActivateRoute = {
    path: '/api/v1/settings/embeddings',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  } as const
  const systemInfoRoute = {
    path: '/api/v1/system/info',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  } as const
  const rebuildRoute = {
    path: '/api/v1/system/rebuild-index',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  } as const
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    capabilities: [
      {
        id: 'analysis.semantic_similarity',
        title: 'Semantic similarity',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/semantic/similar_words', '/api/v1/analysis/embedding_search'],
        backend_route_descriptors: [similarWordsRoute, passageRoute],
        operations: [
          {
            id: 'analysis.semantic_similarity.similar_words',
            capability_id: 'analysis.semantic_similarity',
            label: 'Distributioneller Wort-Thesaurus',
            description: '',
            route: similarWordsRoute,
            effects: ['read'],
            handler_key: 'similar_words',
            surface_slot: 'analysis.semantic_similarity.words',
            priority: 10,
          },
          {
            id: 'analysis.semantic_similarity.passage_search',
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
        action_types: ['analysis/semantic'],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [
          'Semantic result lists do not have a complete CSV/EvidencePackage export path.',
          'The word thesaurus is not advertised as a saved analysis/workspace artifact.',
        ],
      },
      {
        id: 'settings.embedding_management',
        title: 'Embedding-Modelle',
        area: 'settings',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/embeddings/list', '/api/v1/embeddings/download', '/api/v1/settings/embeddings'],
        backend_route_descriptors: [embeddingListRoute, embeddingDownloadRoute, embeddingActivateRoute],
        operations: [
          {
            id: 'settings.embedding_management.list',
            capability_id: 'settings.embedding_management',
            label: 'Embedding-Modelle laden',
            description: 'Listet verfügbare Embedding-Modelle.',
            route: embeddingListRoute,
            effects: ['read'],
            handler_key: 'settings_embeddings',
            surface_slot: 'settings.embeddings.list',
            priority: 10,
          },
          {
            id: 'settings.embedding_management.download',
            capability_id: 'settings.embedding_management',
            label: 'Embedding-Modell installieren',
            description: 'Installiert ein Embedding-Modell.',
            route: embeddingDownloadRoute,
            effects: ['write', 'long_running'],
            handler_key: 'settings_embeddings_download',
            surface_slot: 'settings.embeddings.download',
            priority: 20,
          },
          {
            id: 'settings.embedding_management.set_active',
            capability_id: 'settings.embedding_management',
            label: 'Aktives Embedding-Modell setzen',
            description: 'Setzt das aktive Embedding-Modell.',
            route: embeddingActivateRoute,
            effects: ['write'],
            handler_key: 'settings_embeddings_active',
            surface_slot: 'settings.embeddings.active',
            priority: 30,
          },
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      {
        id: 'admin.system_operations',
        title: 'Systemverwaltung',
        area: 'admin',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/system/info', '/api/v1/system/rebuild-index'],
        backend_route_descriptors: [systemInfoRoute, rebuildRoute],
        operations: [
          {
            id: 'admin.system_operations.info',
            capability_id: 'admin.system_operations',
            label: 'Systeminformationen laden',
            description: 'Lädt Systemstatus und Indexzustand.',
            route: systemInfoRoute,
            effects: ['read'],
            handler_key: 'settings_system_info',
            surface_slot: 'settings.system.info',
            priority: 10,
          },
          {
            id: 'admin.system_operations.rebuild_index',
            capability_id: 'admin.system_operations',
            label: 'Index neu aufbauen',
            description: 'Startet einen beobachtbaren semantischen Index-Rebuild.',
            route: rebuildRoute,
            effects: ['write', 'long_running'],
            handler_key: 'settings_system_rebuild',
            surface_slot: 'settings.system.rebuild_index',
            priority: 20,
          },
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
    ],
  }
  productCapabilities.status = 'ready'
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

function seedAdminSession() {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'admin',
    role: 'admin',
    effective_role: 'admin',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: true,
  }
}

function mockEnglishContract() {
  const english = JSON.parse(JSON.stringify(useProductCapabilitiesStore().contract!)) as NonNullable<ReturnType<typeof useProductCapabilitiesStore>['contract']>
  const operations = english.capabilities[0]!.operations!
  operations.find((operation) => operation.id.endsWith('.passage_search'))!.label = 'Semantic search'
  operations.find((operation) => operation.id.endsWith('.similar_words'))!.label = 'Similar words'
  vi.mocked(getProductCapabilities).mockResolvedValue(english)
}

function seedCorpusFeatures(semantic: { passage_search: boolean; word_similarity: boolean; sentence_alignment: boolean }) {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 100,
    doc_count: 1,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic,
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]
}

function mountTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return mount(SemanticTab, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs,
    },
  })
}

describe('SemanticTab partial corpus availability', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(getProductCapabilities).mockRejectedValue(new Error('offline'))
    seedProductCapabilities()
    seedUserSession()
  })

  it('shows a partial availability notice when only passage search is backed', () => {
    seedCorpusFeatures({ passage_search: true, word_similarity: false, sentence_alignment: false })

    const wrapper = mountTab()

    expect(wrapper.text()).toContain('Semantik ist teilweise verfügbar')
    expect(wrapper.text()).toContain('Passagensuche ist nutzbar')
    expect(wrapper.text()).toContain('Wort-Embedding-Index')
    expect(wrapper.text()).toContain('Semantische Suche')
    expect(wrapper.text()).not.toContain('Semantik-Recovery')
    expect(wrapper.text()).not.toContain('Korpus-Anforderungen')
    expect(wrapper.text()).not.toContain('complete CSV/EvidencePackage export path')
    expect(wrapper.text()).not.toContain('not advertised as a saved analysis')
    expect(wrapper.findAll('button').find((button) => button.text().includes('Passagen'))?.attributes('disabled')).toBeUndefined()
    expect(wrapper.findAll('button').find((button) => button.text().includes('Wort-Thesaurus'))?.attributes('disabled')).toBeDefined()
  })

  it('opens the similar-words ProductOperation directly in thesaurus mode', async () => {
    seedCorpusFeatures({ passage_search: true, word_similarity: true, sentence_alignment: false })
    const uiStore = useUiStore()
    uiStore.focusProductOperation('analysis.semantic_similarity.similar_words', {
      capabilityId: 'analysis.semantic_similarity',
      surfaceSlot: 'analysis.semantic_similarity.words',
      preferredMode: 'words',
    })

    const wrapper = mountTab()
    await flushPromises()

    const thesaurusButton = wrapper.findAll('button').find((button) =>
      button.text().includes('Wort-Thesaurus'),
    )
    const passageButton = wrapper.findAll('button').find((button) =>
      button.text().includes('Passagen'),
    )
    expect(thesaurusButton?.classes()).toContain('active')
    expect(thesaurusButton?.classes()).toContain('operation-focused')
    expect(passageButton?.classes()).not.toContain('active')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('updates the blocked operation label after switching the interface language', async () => {
    seedCorpusFeatures({ passage_search: false, word_similarity: true, sentence_alignment: false })
    const wrapper = mountTab()
    expect(wrapper.text()).toContain('Semantische Passagensuche benötigt Korpus-Evidenz')
    mockEnglishContract()
    applyLocale('en')
    await flushPromises()
    expect(wrapper.text()).toContain('Semantic search needs corpus data')
    expect(wrapper.text()).not.toContain('Semantische Passagensuche')
    wrapper.unmount()
    applyLocale('de')
  })

  it('counts only confirmed shared vectors and clears the note with the results', async () => {
    seedCorpusFeatures({ passage_search: true, word_similarity: true, sentence_alignment: false })
    vi.mocked(getSimilarWords).mockResolvedValue({
      term: 'freedom', backend: 'spacy', unavailable: false,
      neighbours: [
        { word: 'liberty', score: 1, corpusFrequency: 12, sharedQueryVector: true },
        { word: 'peace', score: 1, corpusFrequency: 10, sharedQueryVector: false },
        { word: 'world', score: 1, corpusFrequency: 20 },
      ],
    })
    const wrapper = mountTab()
    await wrapper.findAll('button').find((button) => button.text().includes('Wort-Thesaurus'))!.trigger('click')
    await wrapper.find('input.search-input').setValue('freedom')
    await wrapper.find('button.search-btn').trigger('click')
    await flushPromises()
    expect(wrapper.get('[role="note"]').text()).toContain('1 der angezeigten Nachbarn')
    expect(wrapper.get('[role="note"]').text()).toContain('denselben Vektor wie „freedom“')
    applyLocale('en')
    await flushPromises()
    expect(wrapper.get('[role="note"]').text()).toContain('1 of the displayed neighbors')
    await wrapper.get('.btn-reset').trigger('click')
    expect(wrapper.find('[role="note"]').exists()).toBe(false)
    wrapper.unmount()
    applyLocale('de')
  })

  it('does not infer shared vectors from a displayed 100 percent cosine', async () => {
    seedCorpusFeatures({ passage_search: true, word_similarity: true, sentence_alignment: false })
    vi.mocked(getSimilarWords).mockResolvedValue({
      term: 'freedom', backend: 'spacy', unavailable: false,
      neighbours: [{ word: 'world', score: 1, corpusFrequency: 20 }],
    })
    const wrapper = mountTab()
    await wrapper.findAll('button').find((button) => button.text().includes('Wort-Thesaurus'))!.trigger('click')
    await wrapper.find('input.search-input').setValue('freedom')
    await wrapper.find('button.search-btn').trigger('click')
    await flushPromises()
    expect(wrapper.findAll('.neighbour-row')).toHaveLength(1)
    expect(wrapper.find('[role="note"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps the thesaurus unavailability state concise and research-facing', async () => {
    seedCorpusFeatures({ passage_search: true, word_similarity: true, sentence_alignment: false })
    vi.mocked(getSimilarWords).mockRejectedValueOnce(new SimilarWordsUnavailableError(503))
    const wrapper = mountTab()

    await wrapper.findAll('button').find((button) => button.text().includes('Wort-Thesaurus'))?.trigger('click')
    await wrapper.find('input.search-input').setValue('Klimawandel')
    await wrapper.find('button.search-btn').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Embeddings nicht verfügbar')
    expect(wrapper.text()).not.toContain('Semantik-Recovery')
    expect(wrapper.text()).not.toContain('Passagen-Embedding / FAISS')
  })

  it('renders modes, notices, placeholder and example chips in English', async () => {
    seedCorpusFeatures({ passage_search: true, word_similarity: false, sentence_alignment: false })
    mockEnglishContract()
    applyLocale('en')
    try {
      const wrapper = mountTab()
      await flushPromises()
      const text = wrapper.text()
      expect(text).toContain('Semantic features are partly available: semantic search works, similar words is missing for the active corpus.')
      expect(wrapper.findAll('button').some((button) => button.text().includes('Passages'))).toBe(true)
      expect(wrapper.findAll('button').some((button) => button.text().includes('Similar words'))).toBe(true)
      expect(text).toContain('Finds passages that are close in topic to the query.')
      expect(wrapper.find('input.search-input').attributes('placeholder')).toContain('Semantic search, for example')
      expect(text).toContain('Climate change')
      expect(text).not.toMatch(/Semantik|Passagen|Wort-Thesaurus|Klimawandel|Digitalisierung/)
    } finally {
      applyLocale('de')
    }
  })

  it('hides raw embedding transport errors behind a useful research-facing message', async () => {
    seedCorpusFeatures({ passage_search: true, word_similarity: true, sentence_alignment: false })
    vi.mocked(semanticSearchWithMeta).mockRejectedValueOnce(new SemanticSearchError(
      'Embedding request failed: <urlopen error [Errno 61] Connection refused>',
      { backend: 'gemma', level: 'doc', faissStatus: 'ready' },
    ))
    const wrapper = mountTab()

    await wrapper.find('input.search-input').setValue('Klimax')
    await wrapper.find('button.search-btn').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Semantische Suche momentan nicht erreichbar')
    expect(wrapper.text()).toContain('Der lokale Dienst für Bedeutungsähnlichkeit ist momentan nicht erreichbar')
    expect(wrapper.text()).not.toContain('Embedding request failed')
    expect(wrapper.text()).not.toContain('Connection refused')
    expect(wrapper.text()).not.toContain('Backend: gemma')
    expect(wrapper.text()).not.toContain('Subkorpus prüfen')
  })
})
