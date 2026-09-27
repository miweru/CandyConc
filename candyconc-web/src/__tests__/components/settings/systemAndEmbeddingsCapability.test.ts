import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import EmbeddingsManager from '@/components/settings/EmbeddingsManager.vue'
import SystemInfo from '@/components/settings/SystemInfo.vue'
import {
  clearCache,
  deleteEmbeddingModel,
  getLocalSemanticIndexBuild,
  getLocalSemanticIndexPreflight,
  getSystemInfo,
  startLocalSemanticIndexBuild,
} from '@/api/client'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(),
    getAuthSession: vi.fn(),
    getPrefs: vi.fn(async () => ({ prefs: {} })),
    getSystemInfo: vi.fn(),
    clearCache: vi.fn(),
    getLocalSemanticIndexPreflight: vi.fn(),
    startLocalSemanticIndexBuild: vi.fn(),
    getLocalSemanticIndexBuild: vi.fn(),
    cancelLocalSemanticIndexBuild: vi.fn(),
    getEmbeddingModels: vi.fn(async () => []),
    downloadEmbeddingModel: vi.fn(),
    deleteEmbeddingModel: vi.fn(),
    setActiveEmbeddingModel: vi.fn(),
  }
})

const operationSpecs: Record<string, Record<string, { path: string; method: string; label: string }>> = {
  'admin.system_operations': {
    'admin.system_operations.info': { path: '/api/v1/system/info', method: 'GET', label: 'Systemverwaltung' },
    'admin.system_operations.clear_cache': { path: '/api/v1/system/clear-cache', method: 'POST', label: 'Cache leeren' },
  },
  'settings.embedding_management': {
    'settings.embedding_management.list': { path: '/api/v1/embeddings/list', method: 'GET', label: 'Embedding-Modelle' },
    'settings.embedding_management.local_index_preflight': { path: '/api/v1/embeddings/local-index/preflight', method: 'GET', label: 'Lokalen Index prüfen' },
    'settings.embedding_management.local_index_build': { path: '/api/v1/embeddings/local-index/build', method: 'POST', label: 'Lokalen Index erstellen' },
    'settings.embedding_management.local_index_status': { path: '/api/v1/embeddings/local-index/builds/{run_id}', method: 'GET', label: 'Build-Status' },
    'settings.embedding_management.local_index_cancel': { path: '/api/v1/embeddings/local-index/builds/{run_id}/cancel', method: 'POST', label: 'Build abbrechen' },
    'settings.embedding_management.download': { path: '/api/v1/embeddings/download', method: 'POST', label: 'Embedding-Download' },
    'settings.embedding_management.remove': { path: '/api/v1/embeddings/remove', method: 'POST', label: 'Embedding-Entfernung' },
    'settings.embedding_management.set_active': { path: '/api/v1/settings/embeddings', method: 'POST', label: 'Aktives Embedding-Modell' },
  },
}

function operationsForCapability(
  id: string,
  routes: ProductCapability['backend_route_descriptors'],
): ProductCapability['operations'] {
  return Object.entries(operationSpecs[id] ?? {}).flatMap(([operationId, spec]) => {
    const descriptor = routes.find((route) =>
      route.path === spec.path &&
      route.methods.map((method) => method.toUpperCase()).includes(spec.method)
    )
    if (!descriptor) return []
    return [{
      id: operationId,
      capability_id: id,
      label: spec.label,
      description: '',
      route: { ...descriptor, methods: [spec.method] },
      effects: spec.method === 'GET' ? ['read'] : ['write'],
      handler_key: operationId,
      surface_slot: operationId,
      priority: 100,
    }]
  })
}

function capability(id: string, routes: ProductCapability['backend_route_descriptors']): ProductCapability {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: routes.map((route) => route.path),
    backend_route_descriptors: routes,
    operations: operationsForCapability(id, routes),
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    notes: '',
  }
}

function contract(capabilities: ProductCapability[]): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities,
  }
}

function setUserSession(role = 'user') {
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

describe('settings route-specific capability gates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.mocked(window.localStorage.getItem).mockReturnValue(null)
  })

  afterEach(() => {
    useSettingsStore().stopLocalSemanticIndexPolling()
    vi.unstubAllGlobals()
  })

  it('blocks system admin actions for non-admin sessions using the route descriptors', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('admin.system_operations', [
        {
          path: '/api/v1/system/info',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
        {
          path: '/api/v1/system/clear-cache',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
      ]),
    ])
    productCapabilities.status = 'ready'
    setUserSession('user')

    const wrapper = mount(SystemInfo, {
      global: {
        stubs: {
          Button: { props: ['disabled', 'title'], template: '<button :disabled="disabled" :title="title"><slot /></button>' },
        },
      },
    })

    expect(wrapper.text()).toContain('Systemverwaltung benötigt mindestens Rolle Admin')
    expect(wrapper.find('.info-grid').exists()).toBe(false)
    expect(wrapper.findAll('button').every((button) => button.attributes('disabled') !== undefined)).toBe(true)
  })

  it('keeps embedding read state visible while blocking mutating model actions by route', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('settings.embedding_management', [
        {
          path: '/api/v1/embeddings/list',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
        {
          path: '/api/v1/embeddings/download',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
        {
          path: '/api/v1/embeddings/remove',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
        {
          path: '/api/v1/settings/embeddings',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
      ]),
    ])
    productCapabilities.status = 'ready'
    setUserSession('user')
    const settings = useSettingsStore()
    settings.embeddings = [
      { id: 'installed', name: 'Installed', size: '1 MB', downloaded: true },
      { id: 'available', name: 'Available', size: '2 MB', downloaded: false, url: 'https://example.invalid/model.bin' },
    ]

    const wrapper = mount(EmbeddingsManager, {
      global: {
        stubs: {
          LoadingSpinner: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Installed')
    expect(wrapper.text()).toContain('Available')
    expect(wrapper.find('.btn-download').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.btn-remove').attributes('disabled')).toBeDefined()
  })

  it('marks stale cached embedding catalogues and blocks all model mutations', () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('settings.embedding_management', [
        {
          path: '/api/v1/embeddings/list',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
        {
          path: '/api/v1/embeddings/download',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
        {
          path: '/api/v1/embeddings/remove',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
        {
          path: '/api/v1/settings/embeddings',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
      ]),
    ])
    productCapabilities.status = 'ready'
    setUserSession('admin')
    const settings = useSettingsStore()
    settings.embeddings = [
      { id: 'installed', name: 'Installed', size: '1 MB', downloaded: true },
      { id: 'available', name: 'Available', size: '2 MB', downloaded: false, url: 'https://example.invalid/model.bin' },
    ]
    settings.embeddingCatalogueProvenance = {
      freshness: 'stale_cache',
      source: 'local_cache',
      message: 'Embedding-Katalog stammt aus lokalem Cache.',
    }

    const wrapper = mount(EmbeddingsManager, {
      global: {
        stubs: {
          LoadingSpinner: true,
        },
      },
    })

    expect(wrapper.get('[data-testid="embedding-provenance"]').text()).toContain('lokalem Cache')
    expect(wrapper.find('.btn-download').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.btn-remove').attributes('disabled')).toBeDefined()
  })

  it('marks stale cached system info and blocks destructive system actions', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('admin.system_operations', [
        {
          path: '/api/v1/system/info',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
        {
          path: '/api/v1/system/clear-cache',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
      ]),
    ])
    productCapabilities.status = 'ready'
    setUserSession('admin')
    vi.mocked(getSystemInfo).mockRejectedValueOnce(new Error('backend offline'))
    vi.mocked(window.localStorage.getItem).mockImplementation((key: string) => {
      if (key !== 'candyconc_system_info') return null
      return JSON.stringify({
        backendVersion: '0.1.0',
        uptime: 'stale',
        faissStatus: 'ready',
        vectorCount: 99,
        cacheSize: '9 MB',
        corpusName: 'cached-corpus',
        tokenCount: 123,
        documentCount: 12,
      })
    })

    const wrapper = mount(SystemInfo, {
      global: {
        stubs: {
          Button: { props: ['disabled', 'title', 'loading'], template: '<button :disabled="disabled" :title="title"><slot /></button>' },
        },
      },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="system-info-provenance"]').text()).toContain('lokalem Cache')
    expect(wrapper.text()).toContain('Systemdaten werden erst angezeigt')
    expect(wrapper.text()).not.toContain('cached-corpus')
    expect(wrapper.find('.info-grid').exists()).toBe(false)
    expect(wrapper.findAll('button')).toHaveLength(0)
  })

  it('removes an installed embedding model without a native confirmation loop', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('settings.embedding_management', [
        {
          path: '/api/v1/embeddings/list',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
        {
          path: '/api/v1/embeddings/remove',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
      ]),
    ])
    productCapabilities.status = 'ready'
    setUserSession('admin')
    const settings = useSettingsStore()
    settings.embeddings = [
      { id: 'installed', name: 'Installed', size: '1 MB', downloaded: true },
    ]
    settings.embeddingCatalogueProvenance = {
      freshness: 'fresh',
      source: 'backend',
      message: 'test',
    }
    vi.stubGlobal('confirm', vi.fn(() => false))
    vi.mocked(deleteEmbeddingModel).mockResolvedValueOnce(undefined)

    const wrapper = mount(EmbeddingsManager, {
      global: {
        stubs: {
          LoadingSpinner: true,
        },
      },
    })
    await wrapper.find('.btn-remove').trigger('click')
    await flushPromises()

    expect(window.confirm).not.toHaveBeenCalled()
    expect(deleteEmbeddingModel).toHaveBeenCalledWith('installed')
  })

  it('starts a resumable Apple-Silicon document index from the embeddings surface', async () => {
    const semanticRoutes: ProductCapability['backend_route_descriptors'] = [
      {
        path: '/api/v1/embeddings/local-index/preflight',
        methods: ['GET'],
        mutates: false,
        requires_corpus_features: [],
        access: 'admin',
        required_role: 'admin',
        transport: 'http',
        route_class: 'admin_surface',
      },
      {
        path: '/api/v1/embeddings/local-index/build',
        methods: ['POST'],
        mutates: true,
        requires_corpus_features: [],
        access: 'admin',
        required_role: 'admin',
        transport: 'http',
        route_class: 'admin_surface',
      },
      {
        path: '/api/v1/embeddings/local-index/builds/{run_id}',
        methods: ['GET'],
        mutates: false,
        requires_corpus_features: [],
        access: 'admin',
        required_role: 'admin',
        transport: 'http',
        route_class: 'admin_surface',
      },
      {
        path: '/api/v1/embeddings/local-index/builds/{run_id}/cancel',
        methods: ['POST'],
        mutates: true,
        requires_corpus_features: [],
        access: 'admin',
        required_role: 'admin',
        transport: 'http',
        route_class: 'admin_surface',
      },
    ]
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('settings.embedding_management', semanticRoutes),
    ])
    productCapabilities.status = 'ready'
    setUserSession('admin')
    useCorpusCapabilitiesStore().loaded = true
    vi.mocked(getLocalSemanticIndexPreflight).mockResolvedValueOnce({
      schema_version: 'candyconc-semantic-index-preflight-v1',
      corpus: 'default',
      corpus_path: '/tmp/default',
      platform: {
        system: 'Darwin',
        machine: 'arm64',
        supported: true,
        memory_bytes: 64 * 1024 ** 3,
      },
      runtime: {
        installed: false,
        python: '/tmp/candyconc-mlx/bin/python',
        model: 'mlx-community/embeddinggemma-300m-4bit',
        model_cached: true,
      },
      counts: { documents: 2, sentences: 5, tokens: 19 },
      disk: { free_bytes: 100 * 1024 ** 3, total_bytes: 200 * 1024 ** 3 },
      estimates: {
        doc: { final_bytes: 4096, peak_build_bytes: 8192, warm_search_bytes: 2048 },
        sentence: { final_bytes: 8192, peak_build_bytes: 16_384, warm_search_bytes: 4096 },
        both: { final_bytes: 12_288, peak_build_bytes: 24_576, warm_search_bytes: 6144 },
        runtime_download_bytes: 512,
        model_download_bytes: 1024,
      },
      available_levels: { doc: false, sentence: false },
      options: {
        doc: { can_build: true, required_free_bytes: 8192 },
        sentence: { can_build: true, required_free_bytes: 16_384 },
        both: { can_build: true, required_free_bytes: 24_576 },
      },
      resumable_run: null,
      warnings: [],
    })
    vi.mocked(startLocalSemanticIndexBuild).mockResolvedValueOnce({
      status: 'queued',
      run_id: 'semantic-run-1',
      job_id: 'semantic-run-1',
      status_url: '/api/v1/embeddings/local-index/builds/semantic-run-1',
      operation_id: 'settings.embedding_management.local_index_build',
    })
    vi.mocked(getLocalSemanticIndexBuild).mockResolvedValueOnce({
      run_id: 'semantic-run-1',
      job_id: 'semantic-run-1',
      operation_id: 'settings.embedding_management.local_index_build',
      source_id: 'default',
      kind: 'semantic_index_build',
      label: 'Semantischer Index: default',
      status: 'running',
      phase: 'embed_doc',
      progress: 12,
      message: 'Dokumente werden eingebettet.',
      error: null,
      result_ref: null,
      readiness: 'building',
      warnings: [],
      evidence: { cancellable: true, eta_seconds: 90 },
      created_at: '2026-07-16T10:00:00Z',
      updated_at: '2026-07-16T10:01:00Z',
      finished_at: null,
    })

    const wrapper = mount(EmbeddingsManager, {
      global: { stubs: { LoadingSpinner: true } },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="local-semantic-index"]').text()).toContain('2 Dokumente')
    expect(wrapper.text()).toContain('EmbeddingGemma 300M')
    await wrapper.get('.btn-local-build').trigger('click')
    await flushPromises()

    expect(startLocalSemanticIndexBuild).toHaveBeenCalledWith('default', ['doc'])
    expect(getLocalSemanticIndexBuild).toHaveBeenCalledWith('semantic-run-1')
    expect(wrapper.get('[data-testid="local-semantic-index-run"]').text()).toContain('12 %')
    expect(wrapper.text()).toContain('Abbrechen')
  })

  it('names the working corpus of the interface and the server catalog entry separately', async () => {
    // The card showed the active entry of the server catalog as "Corpus",
    // while the interface worked with another corpus.
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('admin.system_operations', [{
        path: '/api/v1/system/info',
        methods: ['GET'],
        mutates: false,
        requires_corpus_features: [],
        access: 'admin',
        required_role: 'admin',
        transport: 'http',
        route_class: 'admin_surface',
      }]),
    ])
    productCapabilities.status = 'ready'
    setUserSession('admin')
    const corpusCapabilities = useCorpusCapabilitiesStore()
    corpusCapabilities.corpora = [
      { name: 'sotu_en', display_name: 'State of the Union', token_count: 403284, doc_count: 65, capabilities: {} } as never,
      { name: 'dta_de', token_count: 624227, doc_count: 30, capabilities: {} } as never,
    ]
    corpusCapabilities.loaded = true
    const { useQueryStore } = await import('@/stores/query')
    useQueryStore().setFilters({ corpus: 'dta_de' })
    vi.mocked(getSystemInfo).mockResolvedValue({
      version: '0.1.0',
      backendVersion: '0.1.0',
      uptime: '1m',
      corpusName: 'sotu_en',
      tokenCount: 403284,
      documentCount: 65,
      indexStatus: 'ready',
      faissStatus: 'ready',
      vectorCount: 0,
      cacheSize: '1 MB',
    })

    const wrapper = mount(SystemInfo)
    await flushPromises()

    const card = wrapper.findAll('.info-card').find((node) => node.text().includes('Arbeitskorpus'))
    expect(card).toBeTruthy()
    expect(card!.get('.card-value').text()).toBe('dta_de')
    expect(card!.text()).toContain('624.227 Tokens')
    expect(card!.text()).toContain('Aktiv im Serverkatalog: sotu_en')

    useQueryStore().setFilters({ corpus: 'sotu_en' })
    await flushPromises()
    expect(card!.get('.card-value').text()).toBe('State of the Union')
    expect(card!.text()).not.toContain('Aktiv im Serverkatalog')
    // A known version gets its v, the "unknown" of a source checkout does not.
    expect(wrapper.text()).toContain('v0.1.0')
    vi.mocked(getSystemInfo).mockResolvedValue({
      version: 'unknown', backendVersion: 'unknown', uptime: '1m', corpusName: 'sotu_en', tokenCount: 1, documentCount: 1,
      indexStatus: 'ready', faissStatus: 'ready', vectorCount: 0, cacheSize: '1 MB',
    })
    await useSettingsStore().loadSystemInfo()
    await flushPromises()
    expect(wrapper.text()).not.toContain('vunknown')
  })

  it('runs system maintenance from its explicit controls without native confirmation', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract([
      capability('admin.system_operations', [
        {
          path: '/api/v1/system/info',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
        {
          path: '/api/v1/system/clear-cache',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
      ]),
    ])
    productCapabilities.status = 'ready'
    setUserSession('admin')
    vi.mocked(getSystemInfo).mockResolvedValue({
      version: '0.1.0',
      backendVersion: '0.1.0',
      uptime: '1m',
      corpusName: 'demo',
      tokenCount: 12,
      documentCount: 2,
      indexStatus: 'ready',
      faissStatus: 'ready',
      vectorCount: 42,
      cacheSize: '1 MB',
    })
    vi.stubGlobal('confirm', vi.fn(() => false))
    vi.mocked(clearCache).mockResolvedValueOnce(undefined)

    const wrapper = mount(SystemInfo, {
      global: {
        stubs: {
          Button: { props: ['disabled', 'title', 'loading'], template: '<button :disabled="disabled" :title="title"><slot /></button>' },
        },
      },
    })
    await flushPromises()
    const buttons = wrapper.findAll('button')
    await buttons[0].trigger('click')
    await flushPromises()

    expect(window.confirm).not.toHaveBeenCalled()
    expect(clearCache).toHaveBeenCalled()
    expect(wrapper.text()).not.toContain('FAISS Index neu erstellen')
  })
})
