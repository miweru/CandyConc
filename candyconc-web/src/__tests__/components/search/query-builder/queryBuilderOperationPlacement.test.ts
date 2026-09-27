import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import QueryBuilder from '@/components/search/QueryBuilder.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useUiStore } from '@/stores/ui'
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

function route(path: string, method: string) {
  return {
    path,
    methods: [method],
    mutates: false,
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(id: string, path: string, method: string, label: string, priority: number) {
  return {
    id,
    capability_id: 'query.cqlf',
    label,
    description: `${label} aus dem Fähigkeitskatalog.`,
    route: route(path, method),
    effects: ['read'],
    handler_key: id,
    copilot_tools: [],
    surface_slot: id,
    priority,
  }
}

function cqlfContract(): ProductCapabilityContract {
  const descriptors = [
    route('/api/v1/query/analyse', 'POST'),
    route('/api/v1/query/lexicon/suggest', 'POST'),
  ]
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
      {
        id: 'query.cqlf',
        title: 'CQLF-Workbench',
        area: 'query',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: descriptors.map((descriptor) => descriptor.path),
        backend_route_descriptors: descriptors,
        operations: [
          operation('query.cqlf.analyse', '/api/v1/query/analyse', 'POST', 'CQLF-Diagnostik', 10),
          operation('query.cqlf.lexicon_suggest', '/api/v1/query/lexicon/suggest', 'POST', 'Lexikonvorschläge', 20),
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
}

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
        { id: 'ner', cql_attribute: 'ner', label: 'NER' },
      ],
      frequency_groups: [],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], pairing_schema: null, parallel_groups: false, parallel_kwic: false },
    },
  }
}

async function waitForStudioLoad(
  wrapper: ReturnType<typeof mount>,
  selector = '.advanced-mode',
): Promise<void> {
  for (let attempt = 0; attempt < 100; attempt += 1) {
    await flushPromises()
    if (wrapper.find(selector).exists()) {
      return
    }
    await new Promise((resolve) => window.setTimeout(resolve, 50))
  }
}

describe('QueryBuilder ProductOperation placement', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getMcpTools.mockResolvedValue({ tools: [] })
    const contract = cqlfContract()
    getProductCapabilities.mockResolvedValue(contract)
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract
    productCapabilities.status = 'ready'
    const corpusCapabilities = useCorpusCapabilitiesStore()
    corpusCapabilities.corpora = [corpusWithTokenAttributes()]
    corpusCapabilities.loaded = true
  })

  it('opens lexicon suggestions ProductOperation directly in the CQL assistant surface', async () => {
    const uiStore = useUiStore()
    uiStore.focusProductOperation('query.cqlf.lexicon_suggest', {
      capabilityId: 'query.cqlf',
      surfaceSlot: 'query.cqlf.suggestions',
      preferredMode: 'suggestions',
    })

    const wrapper = mount(QueryBuilder, {
      props: { modelValue: 'cql:[lemma="Haus"]' },
    })
    await waitForStudioLoad(wrapper, '.cql-suggestions')

    const assistant = wrapper.find('.cql-suggestions')
    expect(wrapper.text()).toContain('Fokus: Lexikonvorschläge')
    expect(wrapper.text()).not.toContain('query.cqlf.lexicon_suggest')
    expect(assistant.classes()).toContain('operation-focused')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('opens CQLF diagnostics ProductOperation directly in the backend diagnostics surface', async () => {
    const uiStore = useUiStore()
    uiStore.focusProductOperation('query.cqlf.analyse', {
      capabilityId: 'query.cqlf',
      surfaceSlot: 'query.cqlf.diagnostics',
      preferredMode: 'diagnostics',
    })

    const wrapper = mount(QueryBuilder, {
      props: { modelValue: 'cql:[word="Hase"]' },
    })
    await waitForStudioLoad(wrapper, '.cql-suggestions')

    const assistant = wrapper.find('.cql-suggestions')
    expect(wrapper.text()).toContain('Fokus: CQL prüfen')
    expect(wrapper.text()).not.toContain('query.cqlf.analyse')
    expect(assistant.classes()).toContain('operation-focused')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('offers descriptor-backed token attributes in quick search and emits matching CQL', async () => {
    const wrapper = mount(QueryBuilder, {
      props: { modelValue: '' },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('Tokenfeld')
    expect(wrapper.text()).toContain('POS')
    expect(wrapper.text()).toContain('NER')

    await wrapper.find('#quick-search-token-attribute').setValue('pos')
    await wrapper.find('#quick-search-term').setValue('NN')
    await flushPromises()

    expect(wrapper.text()).toContain('[pos="NN"]')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual(['[pos="NN"]'])
  })
})
