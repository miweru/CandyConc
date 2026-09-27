import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SubcorpusPanel from '@/components/search/SubcorpusPanel.vue'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, useQueryStore } from '@/stores'

const apiMocks = vi.hoisted(() => ({
  createDocsetFromSearch: vi.fn(),
  docsetFromMeta: vi.fn(),
  getMetaCounts: vi.fn(),
  getMetaSchema: vi.fn(),
  getMetaValues: vi.fn(),
}))

const actionMocks = vi.hoisted(() => ({
  dispatch: vi.fn(),
}))

vi.mock('@/actions/bus', () => ({
  actionBus: {
    dispatch: (...args: unknown[]) => actionMocks.dispatch(...args),
  },
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

const operationSpecs = [
  ['meta_schema', 'GET', '/api/v1/analysis/meta_schema', 'research.subcorpora.meta_schema'],
  ['meta_values', 'POST', '/api/v1/analysis/meta_values', 'research.subcorpora.meta_values'],
  ['meta_counts', 'POST', '/api/v1/analysis/meta_counts', 'research.subcorpora.meta_counts'],
  ['docset_from_meta', 'POST', '/api/v1/analysis/docset_from_meta', 'research.subcorpora.docset_from_meta'],
  ['docset_from_search', 'POST', '/api/v1/analysis/docset_from_search', 'research.subcorpora.docset_from_search'],
] as const

function contract() {
  const operations = operationSpecs.map(([suffix, method, path, slot]) => ({
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
    surface_slot: slot,
    priority: 10,
  }))
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [{
      id: 'research.subcorpora_docsets',
      title: 'Subkorpora und Docsets',
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

function seedStores({ paired, query = '' }: { paired: boolean; query?: string }) {
  setActivePinia(createPinia())
  useProductCapabilitiesStore().contract = contract()
  useProductCapabilitiesStore().status = 'ready'
  useQueryStore().setFilters({ corpus: 'default' })
  useQueryStore().setTerm(query)
  useCorpusCapabilitiesStore().corpora = [{
    name: 'default',
    active: true,
    doc_count: 3,
    token_count: 100,
    capabilities: {},
    features: { alignment: { paired, parallel_groups: paired, parallel_kwic: paired, pair_axes: [] } },
  } as any]
}

function mockMetadata(fields: Array<{
  name: string
  kind: string
  hasString?: boolean
  hasNumber?: boolean
  stringValueCount?: number | null
}>) {
  apiMocks.getMetaSchema.mockResolvedValue({ metadataSchemaHash: 'meta-fp', metadataFields: fields })
  apiMocks.getMetaValues.mockImplementation(({ fields: requested }) => Promise.resolve(
    Object.fromEntries(requested.map((field: string) => [field, field === 'register' ? ['Zeitung'] : ['demo']]))
  ))
  apiMocks.getMetaCounts.mockResolvedValue({})
}

describe('Subcorpus drawer workflow', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    actionMocks.dispatch.mockResolvedValue({ success: true })
    apiMocks.createDocsetFromSearch.mockResolvedValue({ docset_id: 'search-scope', doc_count: 2, hit_doc_count: 2, ref_doc_count: 0, token_count: 80 })
    apiMocks.docsetFromMeta.mockResolvedValue({ docset_id: 'meta-scope', doc_count: 1, token_count: 40 })
  })

  it('creates a query-based docset from the drawer when a search term is active', async () => {
    seedStores({ paired: true, query: 'Merkel' })
    mockMetadata(['prompting_method', 'model', 'register', 'source'].map((name) => ({ name, kind: 'enum' })))

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()
    expect(wrapper.text()).toContain('Ohne Auswahl durchsucht die KWIC das Gesamtkorpus.')
    expect(wrapper.text()).toContain('gilt anschließend für KWIC und Analysen')
    expect(wrapper.text()).toContain('Kernfilter: Prompttyp · Modell · Register · Quelle')
    expect(wrapper.text()).not.toContain('Pflichtfelder:')
    await wrapper.findAll('button').find((button) => button.text().includes('Anwenden'))!.trigger('click')
    await flushPromises()
    wrapper.unmount()

    expect(apiMocks.createDocsetFromSearch).toHaveBeenCalledWith(expect.objectContaining({ query: 'Merkel', corpus: 'default' }))
    expect(actionMocks.dispatch).toHaveBeenCalledWith({
      type: 'query/execute',
      payload: { term: 'Merkel', docsetId: 'search-scope' },
    })
  })

  it('creates a metadata-only docset from generic corpus metadata', async () => {
    seedStores({ paired: false })
    mockMetadata([{ name: 'register', kind: 'enum' }, { name: 'year', kind: 'number' }])

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()
    await wrapper.findAll('select').find((select) => select.text().includes('Zeitung'))!.setValue(['Zeitung'])
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Subkorpus erstellen'))!.trigger('click')
    await flushPromises()
    wrapper.unmount()

    expect(apiMocks.docsetFromMeta).toHaveBeenCalledWith({ register: ['Zeitung'] }, 'default')
  })

  it('refreshes a visible query inside a newly applied metadata scope', async () => {
    seedStores({ paired: false, query: 'Merkel' })
    mockMetadata([{ name: 'register', kind: 'enum' }])

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()
    await wrapper.findAll('select').find((select) => select.text().includes('Zeitung'))!.setValue(['Zeitung'])
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Subkorpus erstellen'))!.trigger('click')
    await flushPromises()

    expect(actionMocks.dispatch).toHaveBeenCalledWith({
      type: 'query/execute',
      payload: { term: 'Merkel', docsetId: 'meta-scope' },
    })
    wrapper.unmount()
  })

  it('requires a KWIC query before the paired scope can be applied', async () => {
    seedStores({ paired: true })
    mockMetadata(['prompting_method', 'model', 'register', 'source'].map((name) => ({ name, kind: 'enum' })))

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()

    const apply = wrapper.findAll('button').find((button) => button.text().includes('Anwenden'))!
    expect((apply.element as HTMLButtonElement).disabled).toBe(true)
    expect(apply.attributes('title')).toContain('zuerst eine KWIC-Suche')
    expect(apiMocks.createDocsetFromSearch).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('hides relationship pointers and keeps high-cardinality metadata exact-value only', async () => {
    seedStores({ paired: true })
    mockMetadata([
      ...['prompting_method', 'model', 'register', 'source'].map((name) => ({ name, kind: 'string', hasString: true, stringValueCount: 2 })),
      { name: 'profile_name', kind: 'string', hasString: true, stringValueCount: 2 },
      { name: 'author', kind: 'string', hasString: true, stringValueCount: 251 },
      { name: 'paired_with', kind: 'unknown', hasString: false, stringValueCount: 0 },
      { name: 'ref_doc', kind: 'number', hasNumber: true },
    ])

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()

    const requestedFields = apiMocks.getMetaValues.mock.calls.flatMap(([params]) =>
      (params as { fields?: string[] }).fields ?? [],
    )
    expect(requestedFields).not.toContain('paired_with')
    expect(requestedFields).not.toContain('ref_doc')
    expect(wrapper.text()).toContain('Weitere Metadaten mit exaktem Wert')
    expect(wrapper.text()).toContain('author')
    expect(wrapper.text()).not.toContain('paired_with')
    expect(wrapper.text()).not.toContain('ref_doc')
    wrapper.unmount()
  })

  it('uses the generic exact-value flow instead of loading a huge paired model list', async () => {
    seedStores({ paired: true })
    mockMetadata([
      { name: 'prompting_method', kind: 'string', hasString: true, stringValueCount: 2 },
      { name: 'model', kind: 'string', hasString: true, stringValueCount: 10_000 },
      { name: 'register', kind: 'string', hasString: true, stringValueCount: 2 },
      { name: 'source', kind: 'string', hasString: true, stringValueCount: 2 },
    ])

    const wrapper = mount(SubcorpusPanel, { props: { variant: 'drawer' } })
    await flushPromises()

    const requestedFields = apiMocks.getMetaValues.mock.calls.flatMap(([params]) =>
      (params as { fields?: string[] }).fields ?? [],
    )
    expect(requestedFields).not.toContain('model')
    expect(wrapper.text()).toContain('Weitere Metadaten mit exaktem Wert')
    expect(wrapper.text()).toContain('model')
    expect(wrapper.text()).not.toContain('Modelle passend zum Prompttyp')
    wrapper.unmount()
  })
})
