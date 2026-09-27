/**
 * The part-of-speech help of the search bar describes the tags the active
 * corpus really has. Before, descriptions and groups existed only for STTS
 * and only when the manifest declared a tagset, so a spaCy corpus (Universal
 * POS, no tagset in the manifest) got neither (erprobung B16, inventar 17).
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SearchBar from '@/components/search/SearchBar.vue'
import { clearCorpusPosTagCache } from '@/composables/useCorpusPosTagset'
import { applyLocale } from '@/i18n/locale'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { CorpusSummary, ProductCapabilityContract } from '@/api/client'

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

const ROUTES = [
  { path: '/api/v1/query/analyse', method: 'POST', id: 'query.cqlf.analyse' },
  { path: '/api/v1/query/lexicon/suggest', method: 'POST', id: 'query.cqlf.lexicon_suggest' },
]

function cqlfContract(): ProductCapabilityContract {
  const descriptors = ROUTES.map((route) => ({
    path: route.path,
    methods: [route.method],
    mutates: false,
    requires_corpus_features: [],
    access: null,
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }))
  const capability = (id: string, withRoutes: boolean) => ({
    id,
    title: id,
    area: 'query',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: withRoutes ? ROUTES.map((route) => route.path) : [],
    backend_route_descriptors: withRoutes ? descriptors : [],
    operations: withRoutes
      ? ROUTES.map((route, index) => ({
        id: route.id,
        capability_id: id,
        label: route.id,
        description: '',
        route: descriptors[index],
        effects: ['read'],
        handler_key: route.id,
        surface_slot: route.id,
        priority: 100,
      }))
      : [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    limits: [],
  })
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [capability('query.kwic', false), capability('query.cqlf', true)],
  } as unknown as ProductCapabilityContract
}

function corpusWithPos(name: string): CorpusSummary {
  return {
    name,
    path: `/corpora/${name}`,
    token_count: 1000,
    doc_count: 3,
    import_mode: 'jsonl',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: { pos_lex: true },
    features: {
      schema_version: 'corpus-features-v1',
      // A spaCy import: the pos attribute carries no tagset in the manifest.
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Wortform' },
        { id: 'pos', cql_attribute: 'pos', label: 'POS', tagset: null },
      ],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  } as unknown as CorpusSummary
}

function lexiconOf(tags: string[]) {
  getLexiconSuggestions.mockImplementation(async (attr: string, prefix: string) =>
    attr === 'pos' ? tags.filter((tag) => tag.toLowerCase().startsWith(String(prefix ?? '').toLowerCase())) : [],
  )
}

async function mountAndTypePos(name: string) {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = cqlfContract()
  productCapabilities.status = 'ready'
  getProductCapabilities.mockResolvedValue(cqlfContract())
  const corpus = useCorpusCapabilitiesStore()
  corpus.corpora = [corpusWithPos(name)]
  corpus.loaded = true
  getCorpora.mockResolvedValue({ corpora: [corpusWithPos(name)], count: 1 })
  getSuggestions.mockResolvedValue([])

  const wrapper = mount(SearchBar, { global: { stubs: { Modal: true, Button: true } } })
  await flushPromises()
  const input = wrapper.find('[data-search-input]')
  await input.trigger('focus')
  await input.setValue('cql:[pos="')
  await vi.advanceTimersByTimeAsync(300)
  await flushPromises()
  return wrapper
}

describe('SearchBar part-of-speech help follows the corpus tagset', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    clearCorpusPosTagCache()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('describes and groups Universal POS tags of a spaCy corpus', async () => {
    lexiconOf(['NOUN', 'PUNCT', 'VERB', 'ADP', 'DET', 'ADJ', 'PROPN'])
    const wrapper = await mountAndTypePos('default')

    expect(wrapper.text()).toContain('NOUN · Substantiv')
    expect(wrapper.text()).toContain('PROPN · Eigenname')
    // The full tag list is read once, within the route limit (le=200).
    expect(getLexiconSuggestions).toHaveBeenCalledWith('pos', '', 200, undefined, 'default')
    expect(wrapper.text()).toContain('POS · Nominal')
    expect(wrapper.text()).toContain('POS · Verbal')

    applyLocale('en')
    await flushPromises()
    expect(wrapper.text()).toContain('NOUN · Noun')
    expect(wrapper.text()).toContain('ADP · Adposition')
    expect(wrapper.text()).not.toContain('Substantiv')
    wrapper.unmount()
  })

  it('keeps the STTS descriptions for a corpus whose tags are STTS', async () => {
    lexiconOf(['NN', '$.', 'VVFIN', 'ART', 'ADJA'])
    const wrapper = await mountAndTypePos('default')

    expect(wrapper.text()).toContain('NN · Substantiv')
    expect(wrapper.text()).toContain('ADJA · Adjektiv (attributiv)')
    wrapper.unmount()
  })

  it('shows the raw tags without descriptions for an unrecognised tagset', async () => {
    // Penn Treebank tags: NN would otherwise be described as an STTS noun.
    lexiconOf(['NN', 'IN', 'DT', 'JJ', 'VBD'])
    const wrapper = await mountAndTypePos('default')

    expect(wrapper.text()).toContain('POS: NN')
    expect(wrapper.text()).not.toContain('Substantiv')
    expect(wrapper.text()).not.toContain('POS · Nominal')
    wrapper.unmount()
  })
})
