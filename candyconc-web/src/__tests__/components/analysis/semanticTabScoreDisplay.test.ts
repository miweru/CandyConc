import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SemanticTab from '@/components/analysis/SemanticTab.vue'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, useQueryStore, useSessionStore } from '@/stores'
import { semanticSearchWithMeta } from '@/api/client'
import { guardNetwork } from '../../helpers/networkGuard'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    semanticSearchWithMeta: vi.fn(),
    getSimilarWords: vi.fn(),
    getMcpTools: vi.fn().mockResolvedValue({ tools: [] }),
  }
})

vi.mock('@/actions', () => ({ actionBus: { dispatch: vi.fn() } }))

vi.mock('@/composables', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables')>()
  return {
    ...actual,
    useActions: vi.fn(),
    useMobileDetection: () => ({ isMobile: false }),
  }
})

enableAutoUnmount(afterEach)
guardNetwork()

const stubs = {
  AnalysisToolbar: { template: '<div class="toolbar"><slot name="left" /><slot name="right" /></div>' },
  SaveAnalysisButton: { template: '<div />' },
  JobStatusPill: { template: '<div />' },
  Skeleton: { template: '<div />' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state"><strong>{{ title }}</strong>{{ description }}<slot /></div>' },
}

function passageRoute() {
  return {
    path: '/api/v1/analysis/embedding_search',
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: ['semantic.passage_search'],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
}

function seedProductCapabilities() {
  const productCapabilities = useProductCapabilitiesStore()
  const passage = passageRoute()
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    capabilities: [{
      id: 'analysis.semantic_similarity',
      title: 'Semantic similarity',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [passage.path],
      backend_route_descriptors: [passage],
      operations: [{
        id: 'analysis.semantic_similarity.passage_search',
        capability_id: 'analysis.semantic_similarity',
        label: 'Semantische Passagensuche',
        description: '',
        route: passage,
        effects: ['read'],
        handler_key: 'semantic_passage_search',
        surface_slot: 'analysis.semantic_similarity.passages',
        priority: 20,
      }],
      frontend_evidence: [],
      action_types: ['analysis/semantic'],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as never
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

function seedCorpusFeatures() {
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
      semantic: { passage_search: true, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]
}

function mountTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return mount(SemanticTab, { global: { plugins: [[VueQueryPlugin, { queryClient }]], stubs } })
}

describe('SemanticTab — kind-aware score display (ANALYSIS-DISTRIBUTIONAL-01 / SEM-01)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedProductCapabilities()
    seedUserSession()
    seedCorpusFeatures()
  })

  async function runSearch() {
    const wrapper = mountTab()
    await flushPromises()
    await wrapper.find('input.search-input').setValue('Klimawandel')
    await wrapper.find('button.search-btn').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('renders a TRUE cosine path as percentages capped at 100 with honest colour bands', async () => {
    // A pure-vector method in meta proves the score IS a cosine.
    vi.mocked(semanticSearchWithMeta).mockResolvedValue({
      rows: [
        { doc_id: 'd1', chunk_id: 'c1', text: 'sehr ähnlich', score: 0.95 },
        { doc_id: 'd2', chunk_id: 'c2', text: 'mittel', score: 0.7 },
        { doc_id: 'd3', chunk_id: 'c3', text: 'schwach', score: 0.5 },
      ],
      meta: { rerank: { enabled: true, method: 'vector_score' } },
    })

    const wrapper = await runSearch()
    const scores = wrapper.findAll('.result-score')
    expect(scores.length).toBe(3)
    // Bounded cosine -> percentage, capped band classes (unit label prefixes the value).
    expect(scores[0].text()).toContain('95,0\u00a0%')
    expect(scores[0].text()).toContain('Kosinus')
    expect(scores[0].classes()).toContain('score-high')
    expect(scores[1].text()).toContain('70,0\u00a0%')
    expect(scores[1].classes()).toContain('score-medium')
    expect(scores[2].text()).toContain('50,0\u00a0%')
    expect(scores[2].classes()).toContain('score-low')
  })

  it('empties the passages after a corpus switch instead of showing those of the previous corpus', async () => {
    // Store handles are taken before the mount, so the switch below goes to
    // the stores the tab reads.
    const queryStore = useQueryStore()
    const corpusCapabilities = useCorpusCapabilitiesStore()
    vi.mocked(semanticSearchWithMeta).mockResolvedValue({
      rows: [{ doc_id: 'd1', chunk_id: 'c1', text: 'Passage aus dem vorigen Korpus', score: 0.9 }],
      meta: { rerank: { enabled: true, method: 'vector_score' } },
    })
    const wrapper = await runSearch()
    expect(wrapper.text()).toContain('Passage aus dem vorigen Korpus')

    corpusCapabilities.corpora = [
      ...corpusCapabilities.corpora,
      { ...corpusCapabilities.corpora[0]!, name: 'other', active: false },
    ]
    queryStore.setFilters({ corpus: 'other' })
    await flushPromises()

    expect(wrapper.text()).not.toContain('Passage aus dem vorigen Korpus')
    expect(wrapper.findAll('.result-score')).toHaveLength(0)
  })

  it('SEM-01: a lexical RERANK score of 1.0 is NOT painted as a green 100% perfect match', async () => {
    // This is the bench reality: lexical_overlap rerank emits relevance counts
    // like 1.0 / 2.0 that fall inside [-1,1] but are NOT cosines.
    vi.mocked(semanticSearchWithMeta).mockResolvedValue({
      rows: [
        { doc_id: 'd1', chunk_id: 'c1', text: 'phrase hit', score: 2.0 },
        { doc_id: 'd2', chunk_id: 'c2', text: 'token hit', score: 1.0 },
      ],
      meta: { rerank: { enabled: true, method: 'lexical_overlap_then_vector_score' } },
    })

    const wrapper = await runSearch()
    const scores = wrapper.findAll('.result-score')
    expect(scores.length).toBe(2)
    for (const s of scores) {
      // No percent sign, no green "high" band — it is a relevance rank.
      expect(s.text()).not.toContain('%')
      expect(s.text()).toContain('Relevanz')
      expect(s.classes()).not.toContain('score-high')
      expect(s.classes()).toContain('score-low')
    }
    // The 1.0 rerank value renders as a raw "1,00" (German interface), never "100,0 %".
    expect(scores[1].text()).toContain('1,00')
    expect(scores[1].text()).not.toContain('100')
  })

  it('defaults to the honest rerank treatment when the score kind is unknown', async () => {
    vi.mocked(semanticSearchWithMeta).mockResolvedValue({
      rows: [{ doc_id: 'd1', chunk_id: 'c1', text: 'unlabelled', score: 1.0 }],
      meta: {},
    })

    const wrapper = await runSearch()
    const score = wrapper.find('.result-score')
    // Unknown kind must never be dressed up as a 100% cosine.
    expect(score.text()).not.toContain('%')
    expect(score.text()).toContain('1,00')
    expect(score.classes()).toContain('score-low')
  })
})
