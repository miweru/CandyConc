import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import QueryBuilderStudio from '@/components/search/query-builder/QueryBuilderStudio.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
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

function corpusWithTokenAttributes(): CorpusSummary {
  return {
    name: 'default',
    path: '/corpora/default',
    token_count: 1000,
    doc_count: 12,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: { lemma_lex: true, pos_lex: true, ent_lex: true },
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [
        { id: 'word', cql_attribute: 'word', label: 'Wortform' },
        { id: 'lemma', cql_attribute: 'lemma', label: 'Lemma' },
        { id: 'pos', cql_attribute: 'pos', label: 'POS' },
      ],
      frequency_groups: [],
      semantic: {
        passage_search: false,
        word_similarity: false,
        sentence_alignment: false,
      },
      alignment: {
        paired: false,
        pair_axes: [],
        pairing_schema: null,
        parallel_groups: false,
        parallel_kwic: false,
      },
    },
  }
}

function contractWithoutDiagnostics(): ProductCapabilityContract {
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

function setupStores() {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  const contract = contractWithoutDiagnostics()
  getProductCapabilities.mockResolvedValue(contract)
  getMcpTools.mockResolvedValue({ tools: [] })

  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = contract
  productCapabilities.status = 'ready'

  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [corpusWithTokenAttributes()]
  corpusCapabilities.loaded = true
}

function mountStudio(props: Record<string, unknown> = {}) {
  return mount(QueryBuilderStudio, {
    props: {
      modelValue: '',
      initialMode: 'advanced',
      ...props,
    },
  })
}

describe('QueryBuilderStudio', () => {
  beforeEach(setupStores)

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('shows incoming CQL unchanged in the direct editor and preview', async () => {
    const wrapper = mountStudio({ modelValue: '[word="Hase"]{0,2}' })
    await flushPromises()

    expect(wrapper.find<HTMLTextAreaElement>('.cql-textarea').element.value)
      .toBe('[word="Hase"]{0,2}')
    expect(wrapper.find('.preview-code').text()).toBe('[word="Hase"]{0,2}')
  })

  it('emits the generated CQL when the visible AST editor changes', async () => {
    const wrapper = mountStudio()
    await flushPromises()

    await wrapper.find('[data-role="primary-input"]').setValue('Igel')
    await flushPromises()

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['[word="Igel"]'])
    expect(wrapper.find<HTMLTextAreaElement>('.cql-textarea').element.value)
      .toBe('[word="Igel"]')
  })

  it('applies a real AST template and restores it through visible undo and redo controls', async () => {
    const wrapper = mountStudio()
    await flushPromises()

    const tokenTemplate = wrapper.findAll('.starter-card')
      .find((button) => button.text().includes('Tokenklausel'))
    expect(tokenTemplate).toBeTruthy()
    await tokenTemplate!.trigger('click')
    await flushPromises()

    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['[word="Hase"]'])
    expect(wrapper.find('[data-role="primary-input"]').element.value).toBe('Hase')

    const undo = wrapper.findAll('.history-btn')
      .find((button) => button.text().includes('Rückgängig'))
    expect(undo).toBeTruthy()
    await undo!.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([''])

    const redo = wrapper.findAll('.history-btn')
      .find((button) => button.text().includes('Wiederholen'))
    expect(redo).toBeTruthy()
    await redo!.trigger('click')
    await flushPromises()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['[word="Hase"]'])
  })

  it('emits submit only for a non-empty CQL preview', async () => {
    const wrapper = mountStudio()
    await flushPromises()

    const submit = wrapper.find('.submit-row button')
    expect((submit.element as HTMLButtonElement).disabled).toBe(true)

    await wrapper.find('.cql-textarea').setValue('[lemma="gehen"]')
    await flushPromises()
    await submit.trigger('click')

    expect(wrapper.emitted('submit')).toHaveLength(1)
  })

  it('delegates return to quick search to the production wrapper', async () => {
    const wrapper = mountStudio({ embeddedStudio: true })
    await flushPromises()

    await wrapper.find('.studio-entry-btn').trigger('click')

    expect(wrapper.emitted('request-quick-mode')).toHaveLength(1)
  })
})
