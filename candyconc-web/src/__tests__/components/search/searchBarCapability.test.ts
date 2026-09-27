import { mount, flushPromises } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import SearchBar from '@/components/search/SearchBar.vue'
import { actionBus } from '@/actions/bus'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

const getProductCapabilities = vi.fn()
const getCorpora = vi.fn()
const getSuggestions = vi.fn()
const getLexiconSuggestions = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
    getCorpora: (...args: unknown[]) => getCorpora(...args),
    getSuggestions: (...args: unknown[]) => getSuggestions(...args),
    getLexiconSuggestions: (...args: unknown[]) => getLexiconSuggestions(...args),
  }
})

function capability(
  id: string,
  visibility: 'first_class_ui' | 'hidden_experimental' = 'first_class_ui',
  routes: Array<{ path: string; methods: string[]; mutates?: boolean }> = [],
) {
  const descriptors = routes.map((route) => ({
    path: route.path,
    methods: route.methods,
    mutates: route.mutates ?? false,
    requires_corpus_features: [],
    access: null,
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }))
  const operationSpecs = id === 'query.cqlf'
      ? [
        { id: 'query.cqlf.analyse', path: '/api/v1/query/analyse', method: 'POST', label: 'CQLF-Diagnostik' },
        { id: 'query.cqlf.lexicon_suggest', path: '/api/v1/query/lexicon/suggest', method: 'POST', label: 'CQLF-Lexikonvorschläge' },
      ]
    : []
  const operations = operationSpecs.flatMap((spec) => {
    const descriptor = descriptors.find((route) =>
      route.path === spec.path &&
      route.methods.map((method) => method.toUpperCase()).includes(spec.method)
    )
    if (!descriptor) return []
    return [{
      id: spec.id,
      capability_id: id,
      label: spec.label,
      description: '',
      route: { ...descriptor, methods: [spec.method] },
      effects: ['read'],
      handler_key: spec.id,
      surface_slot: spec.id,
      priority: 100,
    }]
  })
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: visibility === 'first_class_ui' ? 'guarded' : 'experimental',
    visibility,
    backend_routes: routes.map((route) => route.path),
    backend_route_descriptors: descriptors,
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    limits: [],
  }
}

function contract(
  cqlfVisibility: 'first_class_ui' | 'hidden_experimental',
  cqlfRoutes: Array<{ path: string; methods: string[]; mutates?: boolean }> = [],
): ProductCapabilityContract {
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
      capability('query.kwic'),
      capability('query.cqlf', cqlfVisibility, cqlfRoutes),
    ],
  }
}

function seedProductContract(
  cqlfVisibility: 'first_class_ui' | 'hidden_experimental',
  cqlfRoutes: Array<{ path: string; methods: string[]; mutates?: boolean }> = [],
) {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = contract(cqlfVisibility, cqlfRoutes)
  productCapabilities.status = 'ready'
  getProductCapabilities.mockResolvedValue(contract(cqlfVisibility, cqlfRoutes))
}

describe('SearchBar Product-Capability gates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getCorpora.mockResolvedValue({
      corpora: [{
        name: 'default',
        path: '/corpora/default',
        token_count: 100,
        doc_count: 1,
        import_mode: 'generic',
        paired: false,
        pair_axes: [],
        is_legacy: false,
        capabilities: { lemma_lex: true, pos_lex: true, ent_lex: true, embeddings: true },
      }],
      count: 1,
    })
  })

  it('hides CQLF builder and blocks CQLF endpoint assists when query.cqlf is hidden', async () => {
    seedProductContract('hidden_experimental')
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'test' })
    const wrapper = mount(SearchBar, {
      global: {
        stubs: {
          Modal: true,
          Button: true,
        },
      },
    })
    await flushPromises()

    expect(wrapper.find('button[aria-label="Query‑Builder öffnen"]').exists()).toBe(false)

    const input = wrapper.find('[data-search-input]')
    await input.setValue('cql:[word="Hase"]')
    await input.trigger('focus')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(wrapper.text()).toContain('CQLF ist im geladenen Fähigkeitskatalog nicht freigeschaltet')
    expect(getSuggestions).not.toHaveBeenCalled()
    expect(getLexiconSuggestions).not.toHaveBeenCalled()
    expect(dispatchSpy).not.toHaveBeenCalled()
  })

  it('keeps plain KWIC submission available when query.cqlf is hidden', async () => {
    seedProductContract('hidden_experimental')
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'test' })
    const wrapper = mount(SearchBar, {
      global: {
        stubs: {
          Modal: true,
          Button: true,
        },
      },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('Hase')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({
      type: 'query/execute',
      payload: expect.objectContaining({ term: 'Hase' }),
    }))
  })

  it('returns a successful direct search to KWIC instead of leaving an unrelated analysis frontmost', async () => {
    seedProductContract('hidden_experimental')
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'test' })
    useUiStore().setActiveTab('frequency')
    const wrapper = mount(SearchBar, {
      global: {
        stubs: {
          Modal: true,
          Button: true,
        },
      },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('Hase')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({
      type: 'query/execute',
      payload: expect.objectContaining({ term: 'Hase' }),
    }))
    expect(useUiStore().activeTab).toBe('kwic')
  })

  it('keeps a tab that was chosen while the search ran', async () => {
    seedProductContract('hidden_experimental')
    let finish: (value: { success: true, source: string }) => void = () => {}
    vi.spyOn(actionBus, 'dispatch').mockImplementation(() => new Promise((resolve) => { finish = resolve as typeof finish }))
    useUiStore().setActiveTab('dispersion')
    const wrapper = mount(SearchBar, { global: { stubs: { Modal: true, Button: true } } })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('Hase')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    // The reader opens another view before the search has finished.
    useUiStore().setActiveTab('wordsketch')
    finish({ success: true, source: 'test' })
    await flushPromises()

    expect(useUiStore().activeTab).toBe('wordsketch')
  })

  it('closes the search assistant after plain KWIC submit so analysis tabs stay reachable', async () => {
    seedProductContract('hidden_experimental')
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'test' })
    const wrapper = mount(SearchBar, {
      global: {
        stubs: {
          Modal: true,
          Button: true,
        },
      },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('Merkel')
    await input.trigger('focus')
    await flushPromises()

    expect(wrapper.find('#kwic-assist').exists()).toBe(true)

    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({
      type: 'query/execute',
      payload: expect.objectContaining({ term: 'Merkel' }),
    }))
    expect(wrapper.find('#kwic-assist').exists()).toBe(false)
    expect(input.attributes('aria-expanded')).toBe('false')
  })

  it('surfaces blocked KWIC dispatches instead of becoming a silent no-op', async () => {
    seedProductContract('hidden_experimental')
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: false,
      blocked: true,
      error: 'corpus_feature_not_available',
      policyReason: 'Der aktive Korpus unterstützt diese CQLF-Attribute nicht: sim.',
      source: 'user',
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults([{
      position: 9,
      left: 'alter',
      match: 'Hase',
      right: 'läuft',
      docId: 'doc-9',
    }], 1, true)
    const wrapper = mount(SearchBar, {
      global: {
        stubs: {
          Modal: true,
          Button: true,
        },
      },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.trigger('focus')
    expect(wrapper.find('#kwic-assist').exists()).toBe(true)
    await input.setValue('Igel')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(dispatchSpy).toHaveBeenCalled()
    expect(useQueryStore().term).toBe('Igel')
    expect(useQueryStore().results).toEqual([])
    expect(useQueryStore().totalHits).toBe(0)
    expect(useQueryStore().error).toBe('Der aktive Korpus unterstützt diese CQLF-Attribute nicht: sim.')
    expect(useUiStore().toasts.at(-1)).toMatchObject({
      type: 'warning',
      message: 'Der aktive Korpus unterstützt diese CQLF-Attribute nicht: sim.',
    })
    expect(wrapper.find('#kwic-assist').exists()).toBe(false)
    expect(input.attributes('aria-expanded')).toBe('false')
  })

  it('blocks CQLF assist backend calls when concrete assist operations are not offered', async () => {
    vi.useFakeTimers()
    try {
      seedProductContract('first_class_ui')
      getSuggestions.mockResolvedValue([])
      getLexiconSuggestions.mockResolvedValue(['Hase'])
      const wrapper = mount(SearchBar, {
        global: {
          stubs: {
            Modal: true,
            Button: true,
          },
        },
      })
      await flushPromises()

      const input = wrapper.find('[data-search-input]')
      await input.trigger('focus')
      await input.setValue('cql:[word="Ha')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()

      expect(getSuggestions).not.toHaveBeenCalled()
      expect(getLexiconSuggestions).not.toHaveBeenCalled()
      expect(wrapper.text()).toContain('CQLF-Lexikonvorschläge')
    } finally {
      vi.useRealTimers()
    }
  })

  it('uses CQLF assist endpoints only when their route operations are offered', async () => {
    vi.useFakeTimers()
    try {
      seedProductContract('first_class_ui', [
        { path: '/api/v1/query/analyse', methods: ['POST'] },
        { path: '/api/v1/query/lexicon/suggest', methods: ['POST'] },
      ])
      getSuggestions.mockResolvedValue([{ text: 'cql:[word="Hase"]', hint: 'Wort: Hase', kind: 'complete' }])
      getLexiconSuggestions.mockResolvedValue(['Hase'])
      const wrapper = mount(SearchBar, {
        global: {
          stubs: {
            Modal: true,
            Button: true,
          },
        },
      })
      await flushPromises()

      const input = wrapper.find('[data-search-input]')
      await input.trigger('focus')
      await input.setValue('cql:[word="Ha')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()

      expect(getSuggestions).toHaveBeenCalled()
      expect(getLexiconSuggestions).toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it('explains that the global case toggle does not control CQL matching', async () => {
    seedProductContract('first_class_ui')
    const wrapper = mount(SearchBar, {
      global: {
        stubs: {
          Modal: true,
          Button: true,
        },
      },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('cql:[word="Haus"]')
    await flushPromises()

    expect(wrapper.text()).toContain('Aa-Schalter gilt für Plain-KWIC')
    expect(wrapper.find('.case-btn').attributes('title')).toContain('CQL nutzt %c')
  })

  it('labels morph and rel lexicon suggestions with their own groups instead of NER', async () => {
    vi.useFakeTimers()
    try {
      seedProductContract('first_class_ui', [
        { path: '/api/v1/query/analyse', methods: ['POST'] },
        { path: '/api/v1/query/lexicon/suggest', methods: ['POST'] },
      ])
      const corpusCapabilities = useCorpusCapabilitiesStore()
      corpusCapabilities.corpora = [{
        name: 'default',
        path: '/tmp/default',
        token_count: 100,
        doc_count: 1,
        import_mode: 'test',
        paired: false,
        pair_axes: [],
        is_legacy: false,
        capabilities: {},
        features: {
          schema_version: 'corpus-features-v1',
          token_attributes: [
            { id: 'word', cql_attribute: 'word', label: 'Wortform' },
            { id: 'morph', cql_attribute: 'morph', label: 'Morphologie' },
            { id: 'rel', cql_attribute: 'rel', label: 'Relation' },
          ],
          frequency_groups: [{ id: 'word', label: 'Wortform' }],
          semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
          alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
        },
      }]
      corpusCapabilities.loaded = true
      getSuggestions.mockResolvedValue([])
      getLexiconSuggestions
        .mockResolvedValueOnce(['Number=Plur'])
        .mockResolvedValueOnce(['nsubj'])

      const wrapper = mount(SearchBar, {
        global: {
          stubs: {
            Modal: true,
            Button: true,
          },
        },
      })
      await flushPromises()

      const input = wrapper.find('[data-search-input]')
      await input.trigger('focus')
      await input.setValue('cql:[morph="N')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()

      expect(wrapper.text()).toContain('Morphologie')
      expect(wrapper.text()).not.toContain('Entitäten')

      await input.setValue('cql:[rel="n')
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()

      expect(wrapper.text()).toContain('Relationen')
      expect(wrapper.text()).toContain('Relation: nsubj')
    } finally {
      vi.useRealTimers()
    }
  })

  it('translates a plain multi-word phrase to the token-sequence CQL when CQLF is available (SEARCH-KWIC-01)', async () => {
    seedProductContract('first_class_ui', [
      { path: '/api/v1/query/analyse', methods: ['POST'] },
      { path: '/api/v1/query/lexicon/suggest', methods: ['POST'] },
    ])
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'test' })
    const wrapper = mount(SearchBar, {
      global: { stubs: { Modal: true, Button: true } },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('der Klimawandel')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    // The raw phrase is rewritten to the form the engine supports, so no raw
    // "Unexpected token" can reach the backend.
    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({
      type: 'query/execute',
      payload: expect.objectContaining({ term: 'cql:[word="der"] [word="Klimawandel"]' }),
    }))
  })

  it('hands the user an actionable phrase repair when CQLF is gated (SEARCH-KWIC-01)', async () => {
    seedProductContract('hidden_experimental')
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'test' })
    const wrapper = mount(SearchBar, {
      global: { stubs: { Modal: true, Button: true } },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('der Klimawandel')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    // No raw parser error; a clear repair hint with the token form, and no dispatch.
    const error = useQueryStore().error ?? ''
    expect(error).toContain('Token-Form')
    expect(error).toContain('[word="der"] [word="Klimawandel"]')
    expect(useUiStore().toasts.at(-1)).toMatchObject({ type: 'warning' })
    expect(dispatchSpy).not.toHaveBeenCalled()
  })

  it('still submits a single plain word unchanged', async () => {
    seedProductContract('first_class_ui', [
      { path: '/api/v1/query/analyse', methods: ['POST'] },
    ])
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'test' })
    const wrapper = mount(SearchBar, {
      global: { stubs: { Modal: true, Button: true } },
    })
    await flushPromises()

    const input = wrapper.find('[data-search-input]')
    await input.setValue('Klimawandel')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()

    expect(dispatchSpy).toHaveBeenCalledWith(expect.objectContaining({
      type: 'query/execute',
      payload: expect.objectContaining({ term: 'Klimawandel' }),
    }))
  })
})
