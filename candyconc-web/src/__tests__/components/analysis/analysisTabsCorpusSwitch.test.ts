/**
 * A corpus switch keeps the search term. Frequency, dispersion and n-grams
 * compute again for the new corpus. Collocations, the collocation network and
 * the word sketch kept the result of the previous corpus under the new
 * corpus name (sotu_en collocates of "freedom" while dta_de was active).
 */
import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import CollocationNetworkTab from '@/components/analysis/CollocationNetworkTab.vue'
import CollocationsTab from '@/components/analysis/CollocationsTab.vue'
import WordSketchTab from '@/components/analysis/WordSketchTab.vue'
import { getWordSketch } from '@/api/client'
import { clearCollocationActionHandoff } from '@/actions/collocationHandoff'
import {
  useAnalysisJobsStore,
  useCorpusCapabilitiesStore,
  useProductCapabilitiesStore,
  useQueryStore,
  useSessionStore,
} from '@/stores'
import { guardNetwork } from '../../helpers/networkGuard'

const mocks = vi.hoisted(() => ({
  createCollocationJob: vi.fn(),
  loadCollocateKwic: vi.fn(),
  loadCollocationNetwork: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, getWordSketch: vi.fn(), getWordSketchDiff: vi.fn() }
})

vi.mock('@/composables/useCollocationOperations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables/useCollocationOperations')>()
  return {
    ...actual,
    useCollocationOperations: () => ({
      createCollocationJob: mocks.createCollocationJob,
      loadCollocateKwic: mocks.loadCollocateKwic,
      canStartCollocationJob: { value: true },
      canLoadCollocateKwic: { value: true },
      collocationJobBlockReason: { value: null },
      collocationKwicBlockReason: { value: null },
    }),
  }
})

vi.mock('@/composables/useCollocationNetworkOperations', () => ({
  useCollocationNetworkOperations: () => ({
    assertCanLoadCollocationNetwork: vi.fn().mockResolvedValue(undefined),
    loadCollocationNetwork: mocks.loadCollocationNetwork,
    canLoadCollocationNetwork: { __v_isRef: true, value: true },
    collocationNetworkBlockReason: { __v_isRef: true, value: null },
  }),
}))

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  Button: { emits: ['click'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  CapabilityBoundaryPanel: { template: '<div />' },
  CollocationNetworkGraph: {
    props: ['nodes', 'edges'],
    template: '<div class="cn-graph-stub" :data-nodes="nodes.map((n) => n.id).join(\',\')" />',
  },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state">{{ title }} {{ description }}</div>' },
  ForceGraph: { template: '<div />' },
  JobStatusPill: { template: '<div />' },
  MethodPanel: { template: '<div />' },
  SaveAnalysisButton: { template: '<div />' },
  Skeleton: { template: '<div />' },
}

function corpus(name: string) {
  return {
    name,
    path: `/tmp/${name}`,
    active: name === 'sotu_en',
    token_count: 1000,
    doc_count: 10,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: { rel: true, lemma: true },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Word form' },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma' },
        { id: 'rel', cql_attribute: 'rel', label: 'Relation' },
      ],
    },
  }
}

// All three tabs read the product contract through the docset store, which
// checks the meta schema operation on every corpus change. Without a seeded
// contract that check fetched GET /api/v1/capabilities from the test process.
function seedProductAccess() {
  const route = {
    path: '/api/v1/analysis/wordsketch',
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: ['token_attributes.rel'],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  } as const
  const product = useProductCapabilitiesStore()
  product.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    capabilities: [{
      id: 'analysis.wordsketch',
      title: 'Word Sketch',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [route.path],
      backend_route_descriptors: [route],
      operations: [{
        id: 'analysis.wordsketch.profile',
        capability_id: 'analysis.wordsketch',
        label: 'Word Sketch',
        description: '',
        route,
        effects: ['read'],
        handler_key: 'word_sketch',
        surface_slot: 'analysis.wordsketch.profile',
        priority: 10,
      }],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as never
  product.status = 'ready'
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

enableAutoUnmount(afterEach)
guardNetwork()

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  clearCollocationActionHandoff()
  seedProductAccess()
  const corpora = useCorpusCapabilitiesStore()
  corpora.corpora = [corpus('sotu_en'), corpus('dta_de')] as never
  corpora.loaded = true
  const queryStore = useQueryStore()
  queryStore.setFilters({ corpus: 'sotu_en' })
  queryStore.setTerm('freedom')
})

describe('analysis tabs after a corpus switch', () => {
  it('word sketch computes the sketch again for the new corpus', async () => {
    const queryStore = useQueryStore()
    ;(getWordSketch as Mock).mockImplementation(async (params: { corpus?: string }) => (
      params.corpus === 'sotu_en'
        ? { term: 'freedom', relations: [{ relation: 'amod', words: [{ word: 'greater', score: 9.4, frequency: 14 }] }], relationLabels: {} }
        : { term: 'freedom', relations: [], relationLabels: {} }
    ))
    const wrapper = mount(WordSketchTab, { global: { stubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('greater')

    queryStore.setFilters({ corpus: 'dta_de' })
    await flushPromises()

    expect(getWordSketch).toHaveBeenLastCalledWith(expect.objectContaining({ corpus: 'dta_de' }), expect.anything())
    expect(wrapper.text()).not.toContain('greater')
  })

  it('collocations compute the collocates again for the new corpus', async () => {
    const queryStore = useQueryStore()
    const analysisJobs = useAnalysisJobsStore()
    const runJobRows = vi.fn(async (request: { corpus?: string }) => (
      request.corpus === 'sotu_en'
        ? { rows: [{ word: 'greater', f: 18, logdice: 9.8, rank: 1 }], total_rows: 1, total_candidates: 1, truncated: false }
        : { rows: [], total_rows: 0, total_candidates: 0, truncated: false }
    ))
    analysisJobs.runJobRows = runJobRows as unknown as typeof analysisJobs.runJobRows
    const wrapper = mount(CollocationsTab, { global: { stubs } })
    await flushPromises()
    expect(wrapper.text()).toContain('greater')

    queryStore.setFilters({ corpus: 'dta_de' })
    await flushPromises()

    expect(runJobRows).toHaveBeenLastCalledWith(expect.objectContaining({ corpus: 'dta_de' }))
    expect(wrapper.text()).not.toContain('greater')
  })

  it('the collocation network computes the network again for the new corpus', async () => {
    const queryStore = useQueryStore()
    mocks.loadCollocationNetwork.mockImplementation(async (params: { corpus?: string }) => ({
      term: 'freedom',
      measure: 'logdice',
      nodes: params.corpus === 'sotu_en'
        ? [{ id: 'freedom', freq: null, depth: 0 }, { id: 'greater', freq: 18, depth: 1 }]
        : [],
      edges: params.corpus === 'sotu_en' ? [{ source: 'freedom', target: 'greater', weight: 9.8, measure: 'logdice' }] : [],
      diagnostics: { node_count: 0, edge_count: 0, second_order_count: 0, truncated: false },
    }))
    const wrapper = mount(CollocationNetworkTab, { global: { stubs } })
    await flushPromises()
    expect(wrapper.find('.cn-graph-stub').attributes('data-nodes')).toContain('greater')

    queryStore.setFilters({ corpus: 'dta_de' })
    await flushPromises()

    expect(mocks.loadCollocationNetwork).toHaveBeenLastCalledWith(expect.objectContaining({ corpus: 'dta_de' }))
    expect(wrapper.find('.cn-graph-stub').exists()).toBe(false)
  })
})
