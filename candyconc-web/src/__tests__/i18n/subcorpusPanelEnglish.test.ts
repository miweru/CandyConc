/**
 * The subcorpus panel with an English interface: metadata filters of a plain
 * corpus, the applied scope, and the pair tree of a paired corpus show no
 * German text of their own. Field names and values are corpus data.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SubcorpusPanel from '@/components/search/SubcorpusPanel.vue'
import { applyLocale } from '@/i18n/locale'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, useQueryStore } from '@/stores'

const apiMocks = vi.hoisted(() => ({
  createDocsetFromSearch: vi.fn(),
  docsetFromMeta: vi.fn(),
  getMetaCounts: vi.fn(),
  getMetaSchema: vi.fn(),
  getMetaValues: vi.fn(),
}))

vi.mock('@/actions/bus', () => ({
  actionBus: { dispatch: vi.fn(async () => ({ success: true })) },
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    createDocsetFromSearch: (...args: unknown[]) => apiMocks.createDocsetFromSearch(...args),
    docsetFromMeta: (...args: unknown[]) => apiMocks.docsetFromMeta(...args),
    getMetaCounts: (...args: unknown[]) => apiMocks.getMetaCounts(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
    getMetaValues: (...args: unknown[]) => apiMocks.getMetaValues(...args),
  }
})

// German words and letters that must not appear in the English panel.
const GERMAN = /[äöüÄÖÜß]|\b(Subkorpus|Gesamtkorpus|Metadaten\w*|Anwenden|Zurücksetzen|Filter aus|erstellen|Bereich|Wert|Werte|Alle|Kernfilter|Modell|Quelle|Prompttyp|einbeziehen|Mensch|Suchbereich|nutzen|diesen|und|oder|der|die|das|mit|für|nicht|keine)\b/

const operationSpecs = [
  ['meta_schema', 'GET', '/api/v1/analysis/meta_schema'],
  ['meta_values', 'POST', '/api/v1/analysis/meta_values'],
  ['meta_counts', 'POST', '/api/v1/analysis/meta_counts'],
  ['docset_from_meta', 'POST', '/api/v1/analysis/docset_from_meta'],
  ['docset_from_search', 'POST', '/api/v1/analysis/docset_from_search'],
] as const

function contract() {
  const operations = operationSpecs.map(([suffix, method, path]) => ({
    id: `research.subcorpora_docsets.${suffix}`,
    capability_id: 'research.subcorpora_docsets',
    label: suffix,
    description: suffix,
    route: {
      path,
      methods: [method],
      mutates: method !== 'GET',
      requires_corpus_features: [],
      access: 'public',
      required_role: null,
      transport: 'http',
      route_class: 'product_surface',
    },
    effects: method === 'GET' ? ['read'] : ['write'],
    input_schema_ref: 'operation.generic_request',
    response_shape: 'data',
    run_semantics: 'bounded_sync',
    ui_execution_policy: 'contextual_ui',
    required_context: [],
    handler_key: suffix,
    copilot_tools: [],
    surface_slot: `research.subcorpora.${suffix}`,
    priority: 10,
  }))
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [{
      id: 'research.subcorpora_docsets',
      title: 'Subcorpora',
      area: 'research',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: operations.map((op) => op.route.path),
      backend_route_descriptors: operations.map((op) => op.route),
      operations,
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      limits: [],
    }],
  } as any
}

function seedStores(paired: boolean) {
  setActivePinia(createPinia())
  useProductCapabilitiesStore().contract = contract()
  useProductCapabilitiesStore().status = 'ready'
  useQueryStore().setFilters({ corpus: 'default' })
  useQueryStore().setTerm('')
  useCorpusCapabilitiesStore().corpora = [{
    name: 'default',
    active: true,
    doc_count: 65,
    token_count: 403284,
    capabilities: {},
    features: { alignment: { paired, parallel_groups: paired, parallel_kwic: paired, pair_axes: [] } },
  } as any]
}

describe('subcorpus panel in English', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.docsetFromMeta.mockResolvedValue({ docset_id: 'meta-scope', doc_count: 20, token_count: 120000 })
    apiMocks.getMetaCounts.mockResolvedValue({})
  })

  it('labels metadata filters, range and exact-value fields and the applied scope', async () => {
    seedStores(false)
    applyLocale('en')
    apiMocks.getMetaSchema.mockResolvedValue({
      metadataSchemaHash: 'meta-fp',
      metadataFields: [
        { name: 'party', kind: 'string', hasString: true, stringValueCount: 2 },
        { name: 'year', kind: 'number', hasNumber: true },
        { name: 'title', kind: 'string', hasString: true, stringValueCount: 300 },
      ],
    })
    apiMocks.getMetaValues.mockResolvedValue({ party: ['Democratic', 'Republican'] })

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Subcorpus filters')
    expect(text).toContain('Without a selection the KWIC searches the whole corpus.')
    expect(text).toContain('Metadata filters')
    expect(text).toContain('year (range)')
    expect(text).toContain('More metadata with exact values')
    expect(text).toContain('Create subcorpus')
    expect(text).toContain('Reset')
    expect(wrapper.find('input[placeholder="Exact value, more separated by commas"]').exists()).toBe(true)
    expect(text).not.toMatch(GERMAN)

    await wrapper.findAll('select').find((select) => select.text().includes('Republican'))!.setValue(['Republican'])
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Create subcorpus'))!.trigger('click')
    await flushPromises()

    const applied = wrapper.text()
    expect(apiMocks.docsetFromMeta).toHaveBeenCalledWith({ party: ['Republican'] }, 'default')
    expect(applied).toContain('20 docs · 120,000 tokens')
    // An unpaired corpus has no reference documents (subcorpusRefsPairedOnly.test.ts).
    expect(applied).not.toContain('refs')
    expect(applied).toContain('The KWIC and analyses use this scope.')
    expect(applied).not.toMatch(GERMAN)
    wrapper.unmount()
  })

  it('labels the pair tree of a paired corpus', async () => {
    seedStores(true)
    applyLocale('en')
    apiMocks.getMetaSchema.mockResolvedValue({
      metadataSchemaHash: 'meta-fp',
      metadataFields: ['prompting_method', 'model', 'register', 'source'].map((name) => ({ name, kind: 'enum' })),
    })
    apiMocks.getMetaValues.mockImplementation(({ fields }: { fields: string[] }) =>
      Promise.resolve(Object.fromEntries(fields.map((field) => [field, ['demo']]))))

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Core filters: Prompting method · Model · Register · Source')
    expect(text).toContain('A subcorpus from the pair tree needs a search result.')
    expect(text).toContain('Include AI texts')
    expect(text).toContain('Path: all texts')
    const apply = wrapper.findAll('button').find((button) => button.text().includes('Apply'))!
    expect(apply.attributes('title')).toBe('Run a KWIC search first')
    expect(text).not.toMatch(GERMAN)
    wrapper.unmount()
  })
})
