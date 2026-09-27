import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'

import { useDocsetStore } from '@/stores/docset'
import { useQueryStore } from '@/stores/query'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useProductOperationRunsStore } from '@/stores/productOperationRuns'
import { useSessionStore } from '@/stores/session'
import { useSubcorporaStore } from '@/stores/subcorpora'

const apiMocks = vi.hoisted(() => ({
  listSubcorpora: vi.fn(),
  saveSubcorpus: vi.fn(),
  deleteSubcorpus: vi.fn(),
  resolveSubcorpus: vi.fn(),
  docsetFromMeta: vi.fn(),
  createDocsetFromSearch: vi.fn(),
  getMetaSchema: vi.fn(),
  getMetaValues: vi.fn(),
  getProductCapabilities: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  activateCorpus: vi.fn(),
  getSystemInfo: vi.fn(),
  getAuthSession: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    listSubcorpora: (...args: unknown[]) => apiMocks.listSubcorpora(...args),
    saveSubcorpus: (...args: unknown[]) => apiMocks.saveSubcorpus(...args),
    deleteSubcorpus: (...args: unknown[]) => apiMocks.deleteSubcorpus(...args),
    resolveSubcorpus: (...args: unknown[]) => apiMocks.resolveSubcorpus(...args),
    docsetFromMeta: (...args: unknown[]) => apiMocks.docsetFromMeta(...args),
    createDocsetFromSearch: (...args: unknown[]) => apiMocks.createDocsetFromSearch(...args),
    getMetaSchema: (...args: unknown[]) => apiMocks.getMetaSchema(...args),
    getMetaValues: (...args: unknown[]) => apiMocks.getMetaValues(...args),
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getCorpusCapabilities: (...args: unknown[]) => apiMocks.getCorpusCapabilities(...args),
    activateCorpus: (...args: unknown[]) => apiMocks.activateCorpus(...args),
    getSystemInfo: (...args: unknown[]) => apiMocks.getSystemInfo(...args),
    getAuthSession: (...args: unknown[]) => apiMocks.getAuthSession(...args),
  }
})

function seedBrowserStorage() {
  localStorage.clear()
  sessionStorage.clear()
}

function subcorporaDocsetOperations(
  descriptors: Array<{
    path: string
    methods: string[]
    mutates: boolean
    requires_corpus_features: unknown[]
    access: string | null
    required_role: string | null
    transport: string
    route_class: string
  }>,
) {
  return [
    { id: 'research.subcorpora_docsets.meta_schema', path: '/api/v1/analysis/meta_schema', method: 'GET', label: 'Metadatenschema' },
    { id: 'research.subcorpora_docsets.meta_values', path: '/api/v1/analysis/meta_values', method: 'POST', label: 'Metadatenwerte' },
    { id: 'research.subcorpora_docsets.docset_from_meta', path: '/api/v1/analysis/docset_from_meta', method: 'POST', label: 'Metadaten-Docset' },
    { id: 'research.subcorpora_docsets.docset_from_search', path: '/api/v1/analysis/docset_from_search', method: 'POST', label: 'Query-basiertes Docset' },
    { id: 'research.subcorpora_docsets.subcorpora_list', path: '/api/v1/subcorpora', method: 'GET', label: 'Subkorpora laden' },
    { id: 'research.subcorpora_docsets.subcorpora_save', path: '/api/v1/subcorpora', method: 'POST', label: 'Subkorpus speichern' },
    { id: 'research.subcorpora_docsets.subcorpora_delete', path: '/api/v1/subcorpora/{name}', method: 'DELETE', label: 'Subkorpus löschen' },
    { id: 'research.subcorpora_docsets.subcorpora_resolve', path: '/api/v1/subcorpora/{name}/resolve', method: 'POST', label: 'Subkorpus-Auflösung' },
  ].flatMap((spec) => {
    const descriptor = descriptors.find((route) =>
      route.path === spec.path &&
      route.methods.map((method) => method.toUpperCase()).includes(spec.method)
    )
    if (!descriptor) return []
    const confirmed = [
      'research.subcorpora_docsets.docset_from_meta',
      'research.subcorpora_docsets.docset_from_search',
      'research.subcorpora_docsets.docset_intersection',
      'research.subcorpora_docsets.subcorpora_resolve',
    ].includes(spec.id)
    const operationRecord = {
      id: spec.id,
      capability_id: 'research.subcorpora_docsets',
      label: spec.label,
      description: '',
      route: { ...descriptor, methods: [spec.method] },
      effects: confirmed ? ['read', 'long_running'] : spec.method === 'GET' ? ['read'] : ['write'],
      handler_key: spec.id,
      surface_slot: spec.id,
      priority: 100,
    } as Record<string, unknown>
    if (confirmed) operationRecord.ui_execution_policy = 'confirmed_contextual_ui'
    return [operationRecord]
  })
}

function routeDescriptor(path: string, methods: string[], mutates: boolean) {
  return {
    path,
    methods,
    mutates,
    requires_corpus_features: [],
    access: null,
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(
  id: string,
  capabilityId: string,
  path: string,
  method: string,
  label: string,
) {
  return {
    id,
    capability_id: capabilityId,
    label,
    description: '',
    route: routeDescriptor(path, [method], method !== 'GET'),
    effects: method === 'GET' ? ['read'] : ['write'],
    handler_key: id,
    surface_slot: id,
    priority: 100,
  }
}

function corpusSummary(name: string, active = false) {
  return {
    name,
    path: `/corpora/${name}`,
    active,
    source: 'registered',
    doc_count: name === 'demo' ? 12 : 3,
    token_count: name === 'demo' ? 1200 : 300,
    capabilities: {},
    features: {},
  }
}

function capabilityContract(options: { omitDocsetFromMeta?: boolean } = {}) {
  const corpusRoutes = [
    routeDescriptor('/api/v1/corpora', ['GET'], false),
    routeDescriptor('/api/v1/corpora/{corpus}/activate', ['POST'], true),
    routeDescriptor('/api/v1/corpora/{corpus}/capabilities', ['GET'], false),
  ]
  const systemInfoRoute = routeDescriptor('/api/v1/system/info', ['GET'], false)
  const docsetRoutes = [
    { path: '/api/v1/analysis/meta_schema', methods: ['GET'], mutates: false },
    { path: '/api/v1/analysis/meta_values', methods: ['POST'], mutates: false },
    { path: '/api/v1/analysis/docset_from_meta', methods: ['POST'], mutates: true },
    { path: '/api/v1/analysis/docset_from_search', methods: ['POST'], mutates: true },
    { path: '/api/v1/subcorpora', methods: ['GET', 'POST'], mutates: true },
    { path: '/api/v1/subcorpora/{name}', methods: ['GET', 'DELETE'], mutates: true },
    { path: '/api/v1/subcorpora/{name}/resolve', methods: ['POST'], mutates: true },
  ].filter((route) => !options.omitDocsetFromMeta || route.path !== '/api/v1/analysis/docset_from_meta')
  const descriptors = docsetRoutes.map((route) => ({
    ...route,
    requires_corpus_features: [],
    access: null,
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }))
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    capabilities: [
      {
        id: 'corpus.catalogue',
        title: 'Corpus catalogue',
        area: 'corpus',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: corpusRoutes.map((route) => route.path),
        backend_route_descriptors: corpusRoutes,
        operations: [
          operation('corpus.catalogue.list', 'corpus.catalogue', '/api/v1/corpora', 'GET', 'Korpora listen'),
          operation('corpus.catalogue.activate', 'corpus.catalogue', '/api/v1/corpora/{corpus}/activate', 'POST', 'Korpus aktivieren'),
          operation('corpus.catalogue.capabilities', 'corpus.catalogue', '/api/v1/corpora/{corpus}/capabilities', 'GET', 'Korpusfähigkeiten laden'),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      {
        id: 'admin.system_operations',
        title: 'System operations',
        area: 'admin',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [systemInfoRoute.path],
        backend_route_descriptors: [systemInfoRoute],
        operations: [
          operation('admin.system_operations.info', 'admin.system_operations', '/api/v1/system/info', 'GET', 'Systeminformationen laden'),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      {
        id: 'research.subcorpora_docsets',
        title: 'Subcorpora and docsets',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: docsetRoutes.map((route) => route.path),
        backend_route_descriptors: descriptors,
        operations: subcorporaDocsetOperations(descriptors),
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      {
        id: 'query.cqlf',
        title: 'CQLF',
        area: 'query',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [],
        backend_route_descriptors: [],
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

function seedSubcorpusContracts(
  role: 'user' | 'admin' = 'admin',
  requiredRole: 'user' | 'admin' = 'user',
) {
  const productCapabilities = useProductCapabilitiesStore()
  const descriptors = [
    { path: '/api/v1/subcorpora', methods: ['GET'], mutates: false },
    { path: '/api/v1/subcorpora', methods: ['POST'], mutates: true },
    { path: '/api/v1/subcorpora/{name}', methods: ['DELETE'], mutates: true },
    { path: '/api/v1/subcorpora/{name}/resolve', methods: ['POST'], mutates: true },
  ].map((route) => ({
    ...route,
    requires_corpus_features: [],
    access: requiredRole,
    required_role: requiredRole,
    transport: 'http',
    route_class: 'product_surface',
  }))
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [
      {
        id: 'research.subcorpora_docsets',
        title: 'Subcorpora and docsets',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [
          '/api/v1/subcorpora',
          '/api/v1/subcorpora/{name}',
          '/api/v1/subcorpora/{name}/resolve',
        ],
        backend_route_descriptors: descriptors,
        operations: subcorporaDocsetOperations(descriptors),
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
    ],
  } as never

  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: role,
    role,
    effective_role: role,
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

describe('subcorpus staleness evidence', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedBrowserStorage()
    apiMocks.listSubcorpora.mockResolvedValue([])
    apiMocks.saveSubcorpus.mockResolvedValue({})
    apiMocks.deleteSubcorpus.mockResolvedValue({ status: 'ok' })
    apiMocks.resolveSubcorpus.mockResolvedValue({
      docset_id: 'docset-live',
      doc_count: 3,
      token_count: 300,
      stale: false,
    })
    apiMocks.docsetFromMeta.mockResolvedValue({ docset_id: 'meta-live', doc_count: 1, token_count: 100 })
    apiMocks.createDocsetFromSearch.mockResolvedValue({ docset_id: 'search-live', doc_count: 1, token_count: 100 })
    apiMocks.getMetaSchema.mockResolvedValue({ metadataFields: [], metadataSchemaHash: 'hash-current' })
    apiMocks.getMetaValues.mockResolvedValue({})
    apiMocks.getProductCapabilities.mockResolvedValue(capabilityContract())
    apiMocks.getCorpusCapabilities.mockImplementation(async (corpus: string) => corpusSummary(corpus, corpus === 'demo'))
    apiMocks.activateCorpus.mockImplementation(async (corpus: string) => corpusSummary(corpus, true))
    apiMocks.getSystemInfo.mockResolvedValue({
      backendVersion: 'test',
      uptime: '1s',
      corpusName: 'demo',
      tokenCount: 1200,
      documentCount: 12,
      indexStatus: 'ready',
      source: 'backend',
    })
    apiMocks.getAuthSession.mockResolvedValue({})
  })

  it('lists saved subcorpora without resolving every definition in the background', async () => {
    apiMocks.listSubcorpora.mockResolvedValueOnce([
      {
        name: 'Legacy scope',
        corpus: 'demo',
        query: null,
        filter_spec: { split: ['test'] },
        include_ai: true,
        include_human: true,
        created_at: 123,
      },
    ])

    const store = useSubcorporaStore()
    await store.init()
    await nextTick()

    expect(store.snapshots[0]).toMatchObject({
      name: 'Legacy scope',
      statsResolved: false,
      resolution: { status: 'unresolved' },
    })
    expect(apiMocks.resolveSubcorpus).not.toHaveBeenCalled()
  })

  it('keeps backend stale=true when resolving stored subcorpus statistics', async () => {
    apiMocks.listSubcorpora.mockResolvedValueOnce([
      {
        name: 'Scope A',
        corpus: 'demo',
        query: null,
        filter_spec: { register: ['news'] },
        include_ai: true,
        include_human: true,
        metadata_schema_hash: 'hash-old',
        created_at: 123,
      },
    ])
    apiMocks.resolveSubcorpus.mockResolvedValue({
      docset_id: 'docset-stale',
      doc_count: 7,
      token_count: 700,
      stale: true,
    })

    const store = useSubcorporaStore()
    await store.init()
    await store.resolveStats(true)

    expect(store.snapshots[0]).toMatchObject({
      docsetId: 'docset-stale',
      statsResolved: true,
      resolution: {
        status: 'stale',
        stale: true,
      },
    })
    expect(store.snapshots[0]?.resolution?.message).toContain('Metadatenschema')
    const operationRuns = useProductOperationRunsStore()
    expect(operationRuns.records.some((run) =>
      run.operationId === 'research.subcorpora_docsets.subcorpora_resolve' &&
      run.sourceId === 'Scope A' &&
      run.status === 'succeeded'
    )).toBe(true)
  })

  it('does not use a cached docset hint for durable named subcorpora, so stale evidence is rechecked', async () => {
    sessionStorage.setItem('candyconc_docset_hints', JSON.stringify({ 'Scope A': 'cached-docset' }))
    apiMocks.resolveSubcorpus.mockResolvedValueOnce({
      docset_id: 'fresh-from-backend',
      doc_count: 5,
      token_count: 500,
      stale: true,
    })

    const docsetStore = useDocsetStore()
    await docsetStore.applySnapshot({
      name: 'Scope A',
      corpus: 'demo',
      docsetId: 'cached-docset',
      stats: { docCount: 0, hitDocCount: 0, refDocCount: 0, tokenCount: 0 },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { register: ['news'] },
      includeAi: true,
      includeHuman: true,
      metadataSchemaHash: 'hash-old',
    })

    expect(apiMocks.resolveSubcorpus).toHaveBeenCalledWith('Scope A', 'demo')
    expect(apiMocks.activateCorpus).toHaveBeenCalledWith('demo')
    expect(useQueryStore().filters.corpus).toBe('demo')
    expect(docsetStore.activeDocsetId).toBe('fresh-from-backend')
    expect(docsetStore.stats.docCount).toBe(5)
    expect(docsetStore.stats.tokenCount).toBe(500)
    expect(docsetStore.activeScopeStale).toBe(true)
    expect(docsetStore.activeScopeWarning).toContain('Metadatenschema')
  })

  it('switches active corpus before activating a saved subcorpus from another corpus', async () => {
    const queryStore = useQueryStore()
    queryStore.setFilters({ corpus: 'default' })
    queryStore.setResults(
      [{ position: 1, left: 'alte', match: 'Zeile', right: '', docId: 'old' }],
      1,
    )
    apiMocks.resolveSubcorpus.mockResolvedValueOnce({
      docset_id: 'demo-live',
      doc_count: 11,
      token_count: 1100,
      stale: false,
    })

    const docsetStore = useDocsetStore()
    await docsetStore.applySnapshot({
      name: 'Demo-Scope',
      corpus: 'demo',
      docsetId: 'stale-demo-hint',
      stats: { docCount: 0, hitDocCount: 0, refDocCount: 0, tokenCount: 0 },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { genre: ['Essay'] },
      includeAi: true,
      includeHuman: true,
    })

    expect(apiMocks.activateCorpus).toHaveBeenCalledWith('demo')
    expect(queryStore.filters.corpus).toBe('demo')
    expect(queryStore.results).toEqual([])
    expect(apiMocks.resolveSubcorpus).toHaveBeenCalledWith('Demo-Scope', 'demo')
    expect(docsetStore.activeDocsetId).toBe('demo-live')
    expect(docsetStore.activeCorpus).toBe('demo')
    expect(docsetStore.isDirty).toBe(false)
  })

  it('drops a transient scope instead of sending its docset into another corpus', async () => {
    const queryStore = useQueryStore()
    queryStore.setFilters({ corpus: 'demo' })
    await nextTick()

    const docsetStore = useDocsetStore()
    docsetStore.setFilter('register', ['news'])
    await docsetStore.buildDocsetFromMeta({ register: ['news'] })

    expect(docsetStore.activeDocsetId).toBe('meta-live')
    expect(docsetStore.summaryParts).toContain('Register: news')

    queryStore.setFilters({ corpus: 'other' })
    await nextTick()

    expect(docsetStore.activeDocsetId).toBeNull()
    expect(docsetStore.activeFilterSpec).toBeNull()
    expect(docsetStore.summaryParts).toEqual([])
    expect(docsetStore.filters.register).toEqual([])
    expect(docsetStore.isDirty).toBe(false)
  })

  it('keeps field-agnostic filter specs as active scope evidence for generic corpora', async () => {
    apiMocks.docsetFromMeta.mockResolvedValueOnce({
      docset_id: 'generic-live',
      doc_count: 9,
      token_count: 900,
    })

    const docsetStore = useDocsetStore()
    const ok = await docsetStore.buildDocsetFromMeta({
      year: { op: '>=', value: 2020 },
      genre: ['news', 'essay'],
    })

    expect(ok).toBe(true)
    expect(docsetStore.activeDocsetId).toBe('generic-live')
    expect(docsetStore.activeFilterSpec).toEqual({
      year: { op: '>=', value: 2020 },
      genre: ['news', 'essay'],
    })
    expect(docsetStore.summaryParts).toEqual(
      expect.arrayContaining(['year: >= 2020', 'genre: news, essay'])
    )

    const subcorporaStore = useSubcorporaStore()
    const snapshot = subcorporaStore.createSnapshot({
      name: 'Generic scope',
      status: 'parked',
      corpus: 'demo',
      docsetId: docsetStore.activeDocsetId!,
      stats: {
        docCount: docsetStore.stats.docCount,
        tokenCount: docsetStore.stats.tokenCount,
        refDocCount: docsetStore.stats.refDocCount,
      },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: docsetStore.activeFilterSpec ?? undefined,
      includeAi: true,
      includeHuman: true,
      origin: { type: 'filter' },
    })

    expect(snapshot.filterSpec).toEqual({
      year: { op: '>=', value: 2020 },
      genre: ['news', 'essay'],
    })
  })

  it('builds query docsets from the subcorpus UI without a native confirm dead-end', async () => {
    vi.mocked(window.confirm).mockClear()
    vi.mocked(window.confirm).mockReturnValue(false)
    apiMocks.createDocsetFromSearch.mockResolvedValueOnce({
      docset_id: 'query-live',
      doc_count: 8,
      hit_doc_count: 8,
      ref_doc_count: 8,
      token_count: 42,
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const docsetStore = useDocsetStore()
    const ok = await docsetStore.buildDocset(true)

    expect(docsetStore.error).toBeNull()
    expect(ok).toBe(true)
    expect(window.confirm).not.toHaveBeenCalled()
    expect(apiMocks.createDocsetFromSearch).toHaveBeenCalledWith(expect.objectContaining({
      query: 'Hase',
      corpus: 'default',
    }))
    expect(docsetStore.activeDocsetId).toBe('query-live')
  })

  it('keeps generic filter specs when saving durable subcorpora', async () => {
    seedSubcorpusContracts('admin', 'user')
    const store = useSubcorporaStore()
    store.initialized = true
    const snapshot = store.createSnapshot({
      name: 'Generic persisted scope',
      status: 'parked',
      corpus: 'demo',
      docsetId: 'docset-live',
      stats: { docCount: 2, tokenCount: 200, refDocCount: 0 },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { year: { op: 'between', lo: 1800, hi: 1850 }, genre: ['Essay'] },
      includeAi: true,
      includeHuman: true,
      origin: { type: 'filter' },
    })

    expect(store.add(snapshot)).toBe(true)
    await vi.waitFor(() => expect(apiMocks.saveSubcorpus).toHaveBeenCalled())

    expect(apiMocks.saveSubcorpus).toHaveBeenCalledWith(expect.objectContaining({
      filter_spec: { year: { op: 'between', lo: 1800, hi: 1850 }, genre: ['Essay'] },
    }))
    expect(store.suggestName({
      filters: { prompting_method: [], model: [], register: [], source: [] },
      includeAi: true,
      includeHuman: true,
      filterSpec: snapshot.filterSpec,
    })).toContain('year: 1800 bis 1850')
  })

  it('does not call metadata docset API when the Product Contract hides that route', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(capabilityContract({ omitDocsetFromMeta: true }))

    const docsetStore = useDocsetStore()
    const ok = await docsetStore.buildDocsetFromMeta({ genre: ['news'] })

    expect(ok).toBe(false)
    expect(apiMocks.docsetFromMeta).not.toHaveBeenCalled()
    expect(docsetStore.error).toContain('Metadaten-Docset')
  })

  it('SUBC-01: a metadata-built docset records origin kind "meta", not the stale search term', async () => {
    const queryStore = useQueryStore()
    // A stale, unrelated search term sits in the box from a prior search.
    queryStore.setTerm('völlig anderer Suchbegriff')

    const docsetStore = useDocsetStore()
    const ok = await docsetStore.buildDocsetFromMeta({ register: ['news'] })

    expect(ok).toBe(true)
    // The origin must follow HOW the docset was built (metadata), NOT queryStore.term.
    expect(docsetStore.activeDocsetOrigin).toEqual({ kind: 'meta' })
    // And the real backend token count flows through (no per-million inflation / 0-chip).
    expect(docsetStore.stats.tokenCount).toBe(100)
    // The store no longer forwards a numeric tokenCount arg (the real client opts
    // into computing it internally); the call carries only spec + corpus.
    expect(apiMocks.docsetFromMeta).toHaveBeenCalledWith({ register: ['news'] }, 'default')
  })

  it('keeps a metadata-only scope fresh when the researcher enters another query', async () => {
    const docsetStore = useDocsetStore()
    await docsetStore.buildDocsetFromMeta({ register: ['news'] })
    expect(docsetStore.activeDocsetOrigin).toEqual({ kind: 'meta' })

    useQueryStore().setTerm('anderer Suchbegriff')
    await nextTick()

    expect(docsetStore.isDirty).toBe(false)
  })

  it('narrows no scope, a metadata scope and a query scope by one metadata condition', async () => {
    const docsetStore = useDocsetStore()

    // No scope: the condition alone becomes the scope.
    expect(await docsetStore.narrowScope('year', ['1945'])).toBe(true)
    expect(apiMocks.docsetFromMeta).toHaveBeenLastCalledWith({ year: ['1945'] }, 'default')
    expect(docsetStore.activeDocsetOrigin).toEqual({ kind: 'meta' })
    expect(docsetStore.activeFilterSpec).toEqual({ year: ['1945'] })

    // Metadata scope: the condition is added to the active filters.
    await docsetStore.buildDocsetFromMeta({ party: ['Democratic'] })
    expect(await docsetStore.narrowScope('year', ['1961'])).toBe(true)
    expect(apiMocks.docsetFromMeta).toHaveBeenLastCalledWith({ party: ['Democratic'], year: ['1961'] }, 'default')

    // Scope from the hits of a query: built again with the condition.
    useQueryStore().setTerm('war')
    await docsetStore.buildDocset(true)
    docsetStore.activeSubcorpusName = 'saved scope'
    expect(await docsetStore.narrowScope('decade', ['1950s'])).toBe(true)
    expect(apiMocks.createDocsetFromSearch).toHaveBeenLastCalledWith(expect.objectContaining({
      query: 'war',
      metaFilters: expect.objectContaining({ decade: ['1950s'] }),
    }))
    expect(docsetStore.activeDocsetOrigin).toEqual({ kind: 'search', query: 'war' })
    expect(docsetStore.activeSubcorpusName).toBeNull()
  })

  it('replaces the active scope by a metadata scope', async () => {
    const docsetStore = useDocsetStore()
    await docsetStore.buildDocsetFromMeta({ party: ['Democratic'] })
    expect(await docsetStore.setMetaScope({ party: 'Republican' })).toBe(true)
    expect(apiMocks.docsetFromMeta).toHaveBeenLastCalledWith({ party: 'Republican' }, 'default')
    expect(docsetStore.activeFilterSpec).toEqual({ party: 'Republican' })
  })

  it('marks a query-built scope dirty when the query changes', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('erste Suche')
    const docsetStore = useDocsetStore()
    await docsetStore.buildDocset(true)
    expect(docsetStore.activeDocsetOrigin).toEqual({ kind: 'search', query: 'erste Suche' })
    expect(docsetStore.isDirty).toBe(false)

    queryStore.setTerm('zweite Suche')
    await nextTick()

    expect(docsetStore.isDirty).toBe(true)
  })

  it('blocks durable subcorpus mutations before API calls when the route role is missing', async () => {
    seedSubcorpusContracts('user', 'admin')
    const store = useSubcorporaStore()
    store.initialized = true
    const snapshot = store.createSnapshot({
      name: 'Admin-only scope',
      status: 'parked',
      corpus: 'demo',
      docsetId: 'docset-live',
      stats: { docCount: 2, tokenCount: 200, refDocCount: 0 },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { genre: ['essay'] },
      includeAi: true,
      includeHuman: true,
      origin: { type: 'filter' },
    })

    expect(store.add(snapshot)).toBe(false)
    expect(store.snapshots).toEqual([])
    expect(apiMocks.saveSubcorpus).not.toHaveBeenCalled()
    expect(store.error).toContain('Rolle Admin')

    store.snapshots = [snapshot]
    expect(store.snapshots).toEqual([snapshot])
    await expect(store.remove(snapshot.id)).resolves.toBe(false)
    expect(store.snapshots).toEqual([snapshot])
    expect(apiMocks.deleteSubcorpus).not.toHaveBeenCalled()
    expect(store.error).toContain('Rolle Admin')
  })

  it('removes a durable subcorpus directly from its explicit delete action', async () => {
    seedSubcorpusContracts('admin', 'user')
    vi.mocked(window.confirm).mockReturnValueOnce(false)
    const store = useSubcorporaStore()
    const snapshot = store.createSnapshot({
      name: 'Keep me',
      status: 'parked',
      corpus: 'demo',
      docsetId: 'docset-live',
      stats: { docCount: 2, tokenCount: 200, refDocCount: 0 },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { genre: ['essay'] },
      includeAi: true,
      includeHuman: true,
      origin: { type: 'filter' },
    })
    store.initialized = true
    store.snapshots = [snapshot]

    await expect(store.remove(snapshot.id)).resolves.toBe(true)

    expect(window.confirm).not.toHaveBeenCalled()
    expect(store.snapshots).toEqual([])
    expect(apiMocks.deleteSubcorpus).toHaveBeenCalledWith('Keep me')
  })
})
