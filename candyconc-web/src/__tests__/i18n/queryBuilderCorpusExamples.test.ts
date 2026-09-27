/**
 * Query builder examples come from the active corpus. Before, the quick search
 * offered fixed German words (Demokratie, künstliche intelligenz, Hase) and
 * the POS placeholder "NN oder NOUN", the studio guide `pos="NN"` (STTS) and
 * `source="mlsum"` from a research project, on every corpus and in both
 * interface languages.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import QueryBuilder from '@/components/search/QueryBuilder.vue'
import QueryBuilderStudio from '@/components/search/query-builder/QueryBuilderStudio.vue'
import { clearCorpusExampleCache } from '@/composables/useCorpusExamples'
import { clearCorpusPosTagCache } from '@/composables/useCorpusPosTagset'
import { applyLocale } from '@/i18n/locale'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useDocsetStore } from '@/stores/docset'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { CorpusSummary, FrequencyParams, ProductCapabilityContract } from '@/api/client'

const getProductCapabilities = vi.fn()
const getMcpTools = vi.fn()
const getLexiconSuggestions = vi.fn()
const getFrequencyResult = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
    getMcpTools: (...args: unknown[]) => getMcpTools(...args),
    getLexiconSuggestions: (...args: unknown[]) => getLexiconSuggestions(...args),
    getFrequencyResult: (...args: unknown[]) => getFrequencyResult(...args),
  }
})

if (!('scrollIntoView' in HTMLElement.prototype)) {
  // @ts-expect-error augmenting prototype for jsdom
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

function capability(id: string, ops: Array<{ id: string; path: string; method: string }>) {
  const descriptors = ops.map((op) => ({
    path: op.path,
    methods: [op.method],
    mutates: false,
    requires_corpus_features: [],
    access: null,
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }))
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: ops.map((op) => op.path),
    backend_route_descriptors: descriptors,
    operations: ops.map((op, index) => ({
      id: op.id,
      capability_id: id,
      label: op.id,
      description: '',
      route: descriptors[index],
      effects: ['read'],
      handler_key: op.id,
      surface_slot: op.id,
      priority: 100,
    })),
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    limits: [],
  }
}

function contract(): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [
      capability('query.cqlf', [{ id: 'query.cqlf.lexicon_suggest', path: '/api/v1/query/lexicon/suggest', method: 'POST' }]),
      capability('analysis.frequency', [{ id: 'analysis.frequency.list', path: '/api/v1/analysis/frequency_list', method: 'GET' }]),
    ],
  } as unknown as ProductCapabilityContract
}

function corpus(): CorpusSummary {
  return {
    name: 'default',
    path: '/corpora/default',
    token_count: 403284,
    doc_count: 65,
    import_mode: 'jsonl',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: { lemma_lex: true, pos_lex: true },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Word form' },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma' },
        { id: 'pos', cql_attribute: 'pos', label: 'POS', tagset: null },
      ],
      frequency_groups: [],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], pairing_schema: null, parallel_groups: false, parallel_kwic: false },
    },
  } as unknown as CorpusSummary
}

const FREQUENCIES: Record<string, string[]> = {
  'word:NOUN': ['people', 'world', 'year'],
  'word:ADJ': ['new', 'more', 'American'],
  'lemma:VERB': ['make', 'work', 'help'],
}

const wrappers: Array<ReturnType<typeof mount>> = []

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  clearCorpusPosTagCache()
  clearCorpusExampleCache()
  getProductCapabilities.mockResolvedValue(contract())
  getMcpTools.mockResolvedValue({ tools: [] })
  getLexiconSuggestions.mockImplementation(async (attr: string) =>
    attr === 'pos' ? ['NOUN', 'PUNCT', 'VERB', 'ADP', 'DET', 'ADJ'] : [])
  getFrequencyResult.mockImplementation(async (params: FrequencyParams) => ({
    rows: (FREQUENCIES[`${params.groupBy}:${params.posPrefix}`] ?? []).map((item, index) => ({
      item,
      frequency: 1000 - index,
      relative: 0,
    })),
    groupBy: params.groupBy ?? 'word',
  }))
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = contract()
  productCapabilities.status = 'ready'
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [corpus()]
  corpusCapabilities.loaded = true
})

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
})

describe('query builder examples from the active corpus', () => {
  it('offers frequent nouns and verbs of the corpus and a tag of its tagset', async () => {
    applyLocale('en')
    const wrapper = mount(QueryBuilder, { props: { modelValue: '' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()

    const chips = wrapper.findAll('.simple-example-chip').map((chip) => chip.text())
    expect(chips).toEqual(['people', 'world', 'year'])
    expect(wrapper.text()).toContain('[word="people"]')
    expect(wrapper.text()).toContain('[lemma="make"]')
    expect(wrapper.text()).toContain('Search by lemma, e.g. go, went, gone.')
    expect(wrapper.find('#quick-search-term').attributes('placeholder')).toBe('e.g. people')

    await wrapper.find('#quick-search-token-attribute').setValue('pos')
    await flushPromises()
    expect(wrapper.find('#quick-search-term').attributes('placeholder')).toBe('e.g. NOUN')
    // The chips follow the attribute: tags of the corpus instead of nouns.
    expect(wrapper.findAll('.simple-example-chip').map((chip) => chip.text())).toEqual(['NOUN', 'VERB', 'ADP'])
    expect(wrapper.text()).toContain('[pos="NOUN"]')
    expect(wrapper.text()).not.toMatch(/Demokratie|künstliche|Hase|gehen|NN oder/)
  })

  it('builds the studio guide and starter templates from the corpus and its schema fields', async () => {
    applyLocale('en')
    useDocsetStore().metaFields = [
      { name: 'party', kind: 'enum' },
      { name: 'year', kind: 'date' },
    ]
    const wrapper = mount(QueryBuilderStudio, { props: { modelValue: '' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('[word="people" & pos="NOUN"]')
    expect(text).toContain('within(<s>, [lemma="make"])')
    expect(text).toContain('[word="new"] [word="people"]')
    expect(text).not.toMatch(/mlsum|Hase|pos="NN"/)
    const fieldOptions = wrapper.findAll('datalist option').map((option) => option.attributes('value'))
    expect(fieldOptions).toEqual(expect.arrayContaining(['party', 'year']))
    expect(fieldOptions).not.toContain('prompting_method')
  })
})
