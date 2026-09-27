/**
 * A word sketch row opens the concordance of node, relation and collocate.
 * Before, the rows were plain text and the guide described a detour through
 * the search bar.
 */
import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import WordSketchTab from '@/components/analysis/WordSketchTab.vue'
import { getWordSketch, getWordSketchDiff } from '@/api/client'
import { actionBus } from '@/actions/bus'
import {
  useCorpusCapabilitiesStore,
  useDocsetStore,
  useProductCapabilitiesStore,
  useQueryStore,
  useSessionStore,
  useUiStore,
} from '@/stores'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getWordSketch: vi.fn(),
    getWordSketchDiff: vi.fn(),
  }
})

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  Button: { template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  EmptyState: { props: ['description'], template: '<div class="empty-state">{{ description }}</div>' },
  JobStatusPill: { template: '<div />' },
  SaveAnalysisButton: { template: '<div />' },
  Skeleton: { template: '<div />' },
  MethodPanel: { template: '<div />' },
  CapabilityBoundaryPanel: { template: '<div />' },
}

function mountTab() {
  return mount(WordSketchTab, { global: { stubs } })
}

function seedWordSketchAvailability() {
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
  const diffRoute = { ...route, path: '/api/v1/analysis/wordsketch_diff' } as const
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    capabilities: [{
      id: 'analysis.wordsketch',
      title: 'Word Sketch',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [route.path, diffRoute.path],
      backend_route_descriptors: [route, diffRoute],
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
      }, {
        id: 'analysis.wordsketch.diff',
        capability_id: 'analysis.wordsketch',
        label: 'Word Sketch Diff',
        description: '',
        route: diffRoute,
        effects: ['read'],
        handler_key: 'word_sketch_diff',
        surface_slot: 'analysis.wordsketch.diff',
        priority: 20,
      }],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  }
  productCapabilities.status = 'ready'

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
      token_attributes: [{ id: 'rel', cql_attribute: 'rel', label: 'Relation' }],
    },
  }]

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

async function runSearch(wrapper: ReturnType<typeof mount>, term: string) {
  const input = wrapper.find('input.search-input')
  await input.setValue(term)
  await input.trigger('keyup.enter')
  await flushPromises()
}

const SKETCH = {
  term: 'freedom',
  node: 'freedom',
  relations: [
    { relation: 'amod', words: [{ word: 'political', score: 8.1, frequency: 5 }, { word: 'men"--the', score: 1, frequency: 3 }] },
    { relation: 'dobj_rev', words: [{ word: 'defend', score: 9.5, frequency: 12 }, { word: "n't", score: 2, frequency: 3 }] },
  ],
  relationLabels: { amod: 'adjectival modifier', dobj_rev: 'direct object of' },
}

function rowFor(wrapper: ReturnType<typeof mount>, word: string) {
  const row = wrapper.findAll('[data-testid="wordsketch-row"]').find((candidate) => candidate.find('.item-word').text() === word)
  expect(row, word).toBeTruthy()
  return row!
}

describe('WordSketchTab back path to the concordance', () => {
  let dispatch: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    ;(getWordSketch as Mock).mockReset()
    ;(getWordSketch as Mock).mockResolvedValue(SKETCH)
    seedWordSketchAvailability()
    dispatch = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
  })

  afterEach(() => {
    dispatch.mockRestore()
  })

  it('opens the dependency search of the row and records where it came from', async () => {
    const wrapper = mountTab()
    await runSearch(wrapper, 'freedom')

    await rowFor(wrapper, 'political').trigger('click')
    await flushPromises()

    expect(dispatch).toHaveBeenCalledWith({
      type: 'query/execute',
      payload: { term: '[word=freedom] >amod [word=political]', contextSize: useQueryStore().contextSize },
    })
    expect(dispatch).toHaveBeenLastCalledWith({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
    expect(useQueryStore().backPathOrigin).toMatchObject({
      kind: 'wordSketch',
      term: '[word=freedom] >amod [word=political]',
      node: 'freedom',
      relation: 'amod',
      relationLabel: 'adjectival modifier',
      collocate: 'political',
      pairs: 5,
      exact: true,
    })
  })

  it('puts the collocate first as head when the node is the dependent', async () => {
    const wrapper = mountTab()
    await runSearch(wrapper, 'freedom')
    await rowFor(wrapper, 'defend').trigger('keydown.enter')
    await flushPromises()
    expect(dispatch.mock.calls[0]![0]).toMatchObject({
      type: 'query/execute',
      payload: { term: '[word=defend] >dobj [word=freedom]' },
    })
    await rowFor(wrapper, "n't").trigger('click')
    await flushPromises()
    expect(useQueryStore().backPathOrigin).toMatchObject({ term: "n't >dobj [word=freedom]", exact: false })
  })

  it('searches in the subcorpus the sketch was computed on', async () => {
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-7'
    docsetStore.stats = { docCount: 2, hitDocCount: 2, refDocCount: 0, tokenCount: 100 }
    const wrapper = mountTab()
    await runSearch(wrapper, 'freedom')
    expect((getWordSketch as Mock).mock.calls.at(-1)![0]).toMatchObject({ docsetId: 'docset-7' })

    await rowFor(wrapper, 'political').trigger('click')
    await flushPromises()
    expect(dispatch.mock.calls[0]![0]).toMatchObject({ payload: { docsetId: 'docset-7' } })
  })

  it('refuses a row when the sketch belongs to another scope than the active one', async () => {
    const wrapper = mountTab()
    await runSearch(wrapper, 'freedom')
    useDocsetStore().activeDocsetId = 'docset-new'
    const toast = vi.spyOn(useUiStore(), 'showToast')

    await rowFor(wrapper, 'political').trigger('click')
    await flushPromises()

    expect(dispatch).not.toHaveBeenCalled()
    expect(toast).toHaveBeenCalledWith(expect.stringContaining('anderen Suchbereich'), 'warning')
  })

  it('leaves rows without a query as plain rows and says why', async () => {
    const wrapper = mountTab()
    await runSearch(wrapper, 'freedom')
    const row = rowFor(wrapper, 'men"--the')
    expect(row.classes()).not.toContain('row-link')
    expect(row.attributes('title')).toContain('Dependenzsuche kann dieses Wort nicht')
    await row.trigger('click')
    expect(dispatch).not.toHaveBeenCalled()

    // A sketch without a node form (query-language node or an older server).
    ;(getWordSketch as Mock).mockResolvedValue({ ...SKETCH, node: null })
    await runSearch(wrapper, 'liberty')
    const cqlRow = rowFor(wrapper, 'political')
    expect(cqlRow.classes()).not.toContain('row-link')
    expect(cqlRow.attributes('title')).toContain('braucht ein Wort als Knoten')
    await cqlRow.trigger('click')
    expect(dispatch).not.toHaveBeenCalled()
  })

  it('keeps the sketch of the node when the search term becomes the dependency query', async () => {
    const wrapper = mountTab()
    await runSearch(wrapper, 'freedom')
    const calls = (getWordSketch as Mock).mock.calls.length
    dispatch.mockImplementation(async (action: { type: string; payload?: { term?: string } }) => {
      if (action.type === 'query/execute' && action.payload?.term) useQueryStore().setTerm(action.payload.term)
      return { success: true }
    })

    await rowFor(wrapper, 'political').trigger('click')
    await flushPromises()

    expect(useQueryStore().term).toBe('[word=freedom] >amod [word=political]')
    expect((getWordSketch as Mock).mock.calls.length).toBe(calls)
    expect(wrapper.findAll('.relation-title').map((n) => n.text())).toContain('adjectival modifier')

    // A fresh mount (back on the tab later) shows the sketch of the node again.
    const again = mountTab()
    await flushPromises()
    expect((getWordSketch as Mock).mock.calls.at(-1)![0]).toMatchObject({ term: 'freedom' })
    expect(again.findAll('.relation-title').map((n) => n.text())).toContain('adjectival modifier')
  })

  it('opens the pairs of either word from the sketch comparison', async () => {
    ;(getWordSketchDiff as Mock).mockResolvedValue({
      termA: 'freedom',
      termB: 'liberty',
      nodeA: 'freedom',
      nodeB: 'liberty',
      relations: [{
        relation: 'conj',
        common: [{ word: 'justice', scoreA: 9, scoreB: 8, frequencyA: 8, frequencyB: 3, delta: 1 }],
        onlyA: [{ word: 'democracy', score: 9, frequency: 12 }],
        onlyB: [{ word: 'pursuit', score: 7, frequency: 4 }],
      }],
      relationLabels: { conj: 'conjunct' },
    })
    const wrapper = mountTab()
    await wrapper.get('[data-testid="diff-toggle"]').setValue(true)
    const inputs = wrapper.findAll('input.search-input')
    await inputs[0]!.setValue('freedom')
    await inputs[1]!.setValue('liberty')
    await inputs[1]!.trigger('keyup.enter')
    await flushPromises()

    await wrapper.get('[data-testid="wordsketch-diff-open-b"]').trigger('click')
    await flushPromises()
    expect(dispatch.mock.calls[0]![0]).toMatchObject({
      type: 'query/execute',
      payload: { term: '[word=liberty] >conj [word=justice]' },
    })
    expect(useQueryStore().backPathOrigin).toMatchObject({ node: 'liberty', pairs: 3, fromComparison: true })

    await wrapper.get('[data-testid="wordsketch-diff-only-a"]').trigger('click')
    await flushPromises()
    expect(useQueryStore().backPathOrigin).toMatchObject({
      term: '[word=freedom] >conj [word=democracy]',
      node: 'freedom',
      pairs: 12,
    })
  })
})
