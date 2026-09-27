/**
 * The quick search narrows by the metadata fields of the active corpus.
 *
 * Before, the quick search offered two fixed selects "Source" and "Register"
 * and could only write and read `source=` and `register=` inside `where()`.
 * Those are fields of one project. A corpus with `party` and `president`
 * could not be narrowed at all, and a `where(party=...)` query did not open
 * in the quick search.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import QueryBuilder from '@/components/search/QueryBuilder.vue'
import {
  buildSimpleSearchQuery,
  buildSimpleSearchSummary,
  createDefaultSimpleSearchState,
  hydrateSimpleSearchQuery,
} from '@/lib/queryBuilder/simple'
import { applyLocale } from '@/i18n/locale'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useDocsetStore } from '@/stores/docset'
import { useQueryStore } from '@/stores/query'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { CorpusSummary, ProductCapabilityContract } from '@/api/client'

const getProductCapabilities = vi.fn()
const getMcpTools = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
    getMcpTools: (...args: unknown[]) => getMcpTools(...args),
  }
})

if (!('scrollIntoView' in HTMLElement.prototype)) {
  // @ts-expect-error augmenting prototype for jsdom
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

function corpus(): CorpusSummary {
  return {
    name: 'sotu_en',
    path: '/corpora/sotu_en',
    token_count: 1000,
    doc_count: 65,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: { lemma_lex: true, pos_lex: true },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [],
      frequency_groups: [],
      semantic: { passage_search: false, word_similarity: true, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], pairing_schema: null, parallel_groups: false, parallel_kwic: false },
    },
  }
}

function contract(): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [],
  }
}

const wrappers: Array<ReturnType<typeof mount>> = []
let fetchMetaValues: ReturnType<typeof vi.fn>

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  getProductCapabilities.mockResolvedValue(contract())
  getMcpTools.mockResolvedValue({ tools: [] })
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = contract()
  productCapabilities.status = 'ready'
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [corpus()]
  corpusCapabilities.loaded = true

  // The schema of the State of the Union sample corpus as the server reports it.
  const docsetStore = useDocsetStore()
  docsetStore.loadMetaOptions = vi.fn(async () => {})
  docsetStore.metaFields = [
    { name: 'party', kind: 'enum' },
    { name: 'president', kind: 'enum' },
    { name: 'source', kind: 'enum' },
    { name: 'title', kind: 'text' },
  ]
  docsetStore.metaFieldValueCounts = { doc_id: 65, party: 2, president: 11, source: 1, title: 300 }
  fetchMetaValues = vi.fn(async (params: { fields: string[] }) =>
    Object.fromEntries(params.fields.map((field) => [
      field,
      field === 'party' ? ['Republican', 'Democratic'] : ['Harry S. Truman', 'Ronald Reagan'],
    ])),
  )
  docsetStore.fetchMetaValues = fetchMetaValues as unknown as typeof docsetStore.fetchMetaValues
})

afterEach(() => {
  while (wrappers.length) wrappers.pop()?.unmount()
  applyLocale('de')
})

async function openFilters(wrapper: ReturnType<typeof mount>) {
  const toggle = wrapper.find('[aria-controls="quick-search-filters"]')
  expect(toggle.exists()).toBe(true)
  await toggle.trigger('click')
  await flushPromises()
}

describe('quick search filters from the corpus schema', () => {
  it('writes and reads where() conditions on any metadata field', () => {
    expect(buildSimpleSearchQuery({
      ...createDefaultSimpleSearchState(),
      term: 'freedom',
      filters: { party: 'Republican', decade: '1980s' },
    })).toBe('where(party="Republican" & decade="1980s", [word="freedom"])')

    expect(hydrateSimpleSearchQuery('where(party="Republican" & decade="1980s", [word="freedom"])')).toMatchObject({
      intent: 'exact',
      term: 'freedom',
      filters: { party: 'Republican', decade: '1980s' },
    })
  })

  it('names the corpus fields in the summary', () => {
    applyLocale('en')
    expect(buildSimpleSearchSummary({
      ...createDefaultSimpleSearchState(),
      term: 'freedom',
      filters: { party: 'Republican', president: 'Ronald Reagan', decade: '1980s' },
    })).toBe('Search for the exact word form "freedom", restricted to party "Republican", president "Ronald Reagan", and decade "1980s".')
  })

  it('offers one select per distinguishing field of the active corpus', async () => {
    applyLocale('en')
    const wrapper = mount(QueryBuilder, { props: { modelValue: '' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    await openFilters(wrapper)

    const labels = wrapper.findAll('.simple-select-label').map((node) => node.text())
    // source has one value and title is not enumerable, so neither narrows anything here.
    expect(labels).toEqual(['party', 'president'])
    expect(wrapper.text()).not.toContain('All sources')
    expect(wrapper.text()).not.toContain('All registers')
    expect(fetchMetaValues).toHaveBeenCalledWith(
      expect.objectContaining({ fields: ['party', 'president'] }),
      expect.anything(),
      expect.any(String),
    )

    await wrapper.find('#quick-search-term').setValue('freedom')
    await wrapper.find('[data-filter-field="party"]').setValue('Republican')
    await flushPromises()
    expect(wrapper.find('.simple-translation-panel code').text()).toBe('where(party="Republican", [word="freedom"])')
    expect(wrapper.text()).toContain('restricted to party "Republican"')
  })

  it('opens a where() query on a corpus field in the quick search with the value selected', async () => {
    const wrapper = mount(QueryBuilder, {
      props: { modelValue: 'where(president="Ronald Reagan", [word="freedom"])' },
      attachTo: document.body,
    })
    wrappers.push(wrapper)
    await flushPromises()

    expect(wrapper.find('#quick-search-term').exists()).toBe(true)
    expect((wrapper.find('#quick-search-term').element as HTMLInputElement).value).toBe('freedom')
    expect(wrapper.find('[data-filter-field="president"]').exists()).toBe(true)
    expect((wrapper.find('[data-filter-field="president"]').element as HTMLSelectElement).value).toBe('Ronald Reagan')
  })

  it('keeps the filter area open while typing when the query is bound with v-model', async () => {
    // The search bar binds the builder with v-model. Each keystroke comes back
    // as modelValue and was hydrated with "filters open only if one is set",
    // so the open filter area closed on the first letter.
    const Host = defineComponent({
      setup() {
        const term = ref('')
        return () => h(QueryBuilder, { modelValue: term.value, 'onUpdate:modelValue': (value: string) => { term.value = value } })
      },
    })
    const wrapper = mount(Host, { attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    await openFilters(wrapper)
    expect(wrapper.find('#quick-search-filters').exists()).toBe(true)

    await wrapper.find('#quick-search-term').setValue('freedom')
    await flushPromises()
    expect(wrapper.find('#quick-search-filters').exists()).toBe(true)
    await wrapper.find('[data-filter-field="party"]').setValue('Republican')
    await flushPromises()
    expect(wrapper.find('.simple-translation-panel code').text()).toBe('where(party="Republican", [word="freedom"])')
  })
})

describe('quick search cards', () => {
  it('show the sim macro of the similar-words card as code, not in backticks', async () => {
    useQueryStore().setFilters({ corpus: 'sotu_en' })
    const wrapper = mount(QueryBuilder, { props: { modelValue: '' }, attachTo: document.body })
    wrappers.push(wrapper)
    await flushPromises()
    const texts = wrapper.findAll('.simple-intent-text')
    const similar = texts.find((text) => text.find('code').exists())
    expect(texts.map((text) => text.text()).join(' ')).not.toContain('`')
    expect(similar?.find('code').text()).toBe('sim')
  })
})
