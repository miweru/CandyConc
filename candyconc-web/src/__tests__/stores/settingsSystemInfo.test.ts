import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useSettingsStore } from '@/stores/settings'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useProductOperationRunsStore } from '@/stores/productOperationRuns'
import { useSessionStore } from '@/stores/session'
import type { ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getPrefs: vi.fn(async () => ({ prefs: {} })),
  updatePrefs: vi.fn(),
  getEmbeddingModels: vi.fn(async () => []),
  downloadEmbeddingModel: vi.fn(),
  getOperationRun: vi.fn(),
  deleteEmbeddingModel: vi.fn(),
  setActiveEmbeddingModel: vi.fn(),
  getSystemInfo: vi.fn(),
  clearCache: vi.fn(),
  getLocalSemanticIndexPreflight: vi.fn(),
  startLocalSemanticIndexBuild: vi.fn(),
  getLocalSemanticIndexBuild: vi.fn(),
  cancelLocalSemanticIndexBuild: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  getPrefs: (...args: unknown[]) => apiMocks.getPrefs(...args),
  updatePrefs: (...args: unknown[]) => apiMocks.updatePrefs(...args),
  getEmbeddingModels: (...args: unknown[]) => apiMocks.getEmbeddingModels(...args),
  downloadEmbeddingModel: (...args: unknown[]) => apiMocks.downloadEmbeddingModel(...args),
  getOperationRun: (...args: unknown[]) => apiMocks.getOperationRun(...args),
  deleteEmbeddingModel: (...args: unknown[]) => apiMocks.deleteEmbeddingModel(...args),
  setActiveEmbeddingModel: (...args: unknown[]) => apiMocks.setActiveEmbeddingModel(...args),
  getSystemInfo: (...args: unknown[]) => apiMocks.getSystemInfo(...args),
  clearCache: (...args: unknown[]) => apiMocks.clearCache(...args),
  getLocalSemanticIndexPreflight: (...args: unknown[]) => apiMocks.getLocalSemanticIndexPreflight(...args),
  startLocalSemanticIndexBuild: (...args: unknown[]) => apiMocks.startLocalSemanticIndexBuild(...args),
  getLocalSemanticIndexBuild: (...args: unknown[]) => apiMocks.getLocalSemanticIndexBuild(...args),
  cancelLocalSemanticIndexBuild: (...args: unknown[]) => apiMocks.cancelLocalSemanticIndexBuild(...args),
}))

function httpError(status: number): Error & { response: Response } {
  return Object.assign(new Error(`HTTP ${status}`), {
    response: new Response(JSON.stringify({ detail: `HTTP ${status}` }), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  })
}

function seedPreferencesContract(): void {
  const readRoute = {
    path: '/api/v1/prefs',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
  const updateRoute = {
    path: '/api/v1/prefs/update',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [{
      id: 'settings.preferences',
      title: 'Einstellungen',
      area: 'settings',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [readRoute.path, updateRoute.path],
      backend_route_descriptors: [readRoute, updateRoute],
      operations: [
        {
          id: 'settings.preferences.read',
          capability_id: 'settings.preferences',
          label: 'Einstellungen laden',
          description: '',
          route: readRoute,
          effects: ['read'],
          handler_key: 'settings_preferences_read',
          surface_slot: 'settings.preferences.read',
          priority: 10,
        },
        {
          id: 'settings.preferences.update',
          capability_id: 'settings.preferences',
          label: 'Einstellungen speichern',
          description: '',
          route: updateRoute,
          effects: ['write'],
          handler_key: 'settings_preferences_update',
          surface_slot: 'settings.preferences.update',
          priority: 10,
        },
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as ProductCapabilityContract

  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'analyst',
    role: 'user',
    effective_role: 'user',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

function seedSystemContract(): void {
  const infoRoute = {
    path: '/api/v1/system/info',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }
  const clearCacheRoute = {
    path: '/api/v1/system/cache/clear',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [{
      id: 'admin.system_operations',
      title: 'Systemoperationen',
      area: 'settings',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [infoRoute.path, clearCacheRoute.path],
      backend_route_descriptors: [infoRoute, clearCacheRoute],
      operations: [
        {
          id: 'admin.system_operations.info',
          capability_id: 'admin.system_operations',
          label: 'Systeminformationen laden',
          description: '',
          route: infoRoute,
          effects: ['read'],
          handler_key: 'system_info',
          surface_slot: 'settings.system.info',
          priority: 10,
        },
        {
          id: 'admin.system_operations.clear_cache',
          capability_id: 'admin.system_operations',
          label: 'Cache leeren',
          description: '',
          route: clearCacheRoute,
          effects: ['write', 'destructive'],
          handler_key: 'clear_cache',
          surface_slot: 'settings.system.clear_cache',
          priority: 10,
        },
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as ProductCapabilityContract

  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'admin',
    role: 'admin',
    effective_role: 'admin',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: true,
  }
}

function seedEmbeddingContract(): void {
  const listRoute = {
    path: '/api/v1/embeddings/list',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
  const downloadRoute = {
    path: '/api/v1/embeddings/download',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }
  const downloadStatusRoute = {
    path: '/api/v1/operation-runs/{run_id}',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }
  const removeRoute = {
    path: '/api/v1/embeddings/remove',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [{
      id: 'settings.embedding_management',
      title: 'Embedding-Modelle',
      area: 'settings',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [listRoute.path, downloadRoute.path, downloadStatusRoute.path, removeRoute.path],
      backend_route_descriptors: [listRoute, downloadRoute, downloadStatusRoute, removeRoute],
      operations: [
        {
          id: 'settings.embedding_management.list',
          capability_id: 'settings.embedding_management',
          label: 'Embedding-Modelle laden',
          description: '',
          route: listRoute,
          effects: ['read'],
          handler_key: 'embedding_list',
          surface_slot: 'settings.embedding_management.list',
          priority: 10,
        },
        {
          id: 'settings.embedding_management.download',
          capability_id: 'settings.embedding_management',
          label: 'Embedding-Modell herunterladen',
          description: '',
          route: downloadRoute,
          effects: ['write', 'long_running'],
          handler_key: 'embedding_download',
          surface_slot: 'settings.embedding_management.download',
          priority: 10,
        },
        {
          id: 'settings.embedding_management.download_status',
          capability_id: 'settings.embedding_management',
          label: 'Embedding-Download-Status prüfen',
          description: '',
          route: downloadStatusRoute,
          effects: ['read'],
          handler_key: 'embedding_model_download_status',
          surface_slot: 'settings.embedding_management.download.status',
          priority: 10,
        },
        {
          id: 'settings.embedding_management.remove',
          capability_id: 'settings.embedding_management',
          label: 'Embedding-Modell entfernen',
          description: '',
          route: removeRoute,
          effects: ['write', 'destructive'],
          handler_key: 'embedding_remove',
          surface_slot: 'settings.embedding_management.remove',
          priority: 10,
        },
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as ProductCapabilityContract

  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'admin',
    role: 'admin',
    effective_role: 'admin',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: true,
  }
}

describe('settings system info truth handling', () => {
  let consoleErrorSpy: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    consoleErrorSpy = vi.spyOn(console, 'error').mockImplementation(() => undefined)
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  afterEach(() => {
    const settings = useSettingsStore()
    settings.stopLocalSemanticIndexPolling()
    settings.stopEmbeddingDownloadPolling()
    consoleErrorSpy.mockRestore()
  })

  it('does not replace authorization failures with stale local system info', async () => {
    seedSystemContract()
    apiMocks.getSystemInfo.mockRejectedValueOnce(httpError(403))
    ;(window.localStorage.getItem as Mock).mockReturnValue(JSON.stringify({
      corpusName: 'stale-admin-view',
      tokenCount: 999,
      documentCount: 99,
      faissStatus: 'ready',
      faissDetail: 'stale',
    }))
    const store = useSettingsStore()

    await store.loadSystemInfo()

    expect(window.localStorage.getItem).not.toHaveBeenCalledWith('candyconc_system_info')
    expect(store.systemInfo.corpusName).toBe('Kein Korpus geladen')
    expect(store.systemInfo.tokenCount).toBe(0)
    expect(store.systemInfo.faissStatus).toBe('unavailable')
    expect(store.systemInfo.faissDetail).toContain('nicht freigegeben')
  })

  it('treats an unavailable system-info capability as an expected gated state', async () => {
    seedPreferencesContract()
    const store = useSettingsStore()

    await store.loadSystemInfo()

    expect(apiMocks.getSystemInfo).not.toHaveBeenCalled()
    expect(consoleErrorSpy).not.toHaveBeenCalled()
    expect(store.systemInfoProvenance.freshness).toBe('unavailable')
    expect(store.systemInfoProvenance.message).toContain('nicht freigegeben')
  })

  it('keeps local system-info degradation for non-auth offline errors', async () => {
    seedSystemContract()
    apiMocks.getSystemInfo.mockRejectedValueOnce(httpError(503))
    ;(window.localStorage.getItem as Mock).mockImplementation((key: string) => {
      if (key !== 'candyconc_system_info') return null
      return JSON.stringify({
        corpusName: 'cached-corpus',
        tokenCount: 123,
        documentCount: 12,
        faissStatus: 'ready',
      })
    })
    const store = useSettingsStore()

    await store.loadSystemInfo()

    expect(window.localStorage.getItem).toHaveBeenCalledWith('candyconc_system_info')
    expect(store.systemInfo.corpusName).toBe('cached-corpus')
    expect(store.systemInfo.tokenCount).toBe(123)
    expect(store.systemInfo.faissStatus).toBe('ready')
    expect(store.systemInfoProvenance.freshness).toBe('stale_cache')
    expect(store.systemInfoIsStale).toBe(true)

    await expect(store.clearCache()).resolves.toBe(false)
    expect(apiMocks.clearCache).not.toHaveBeenCalled()
  })

  it('marks legacy system-info fallback responses as degraded and blocks mutations', async () => {
    seedSystemContract()
    apiMocks.getSystemInfo.mockResolvedValueOnce({
      version: 'unknown',
      backendVersion: 'unknown',
      uptime: 'unbekannt',
      corpusName: 'default',
      tokenCount: 0,
      documentCount: 0,
      indexStatus: 'ready',
      faissStatus: 'unavailable',
      vectorCount: 0,
      cacheSize: '0 MB',
      source: 'legacy_health_fallback',
    })
    const store = useSettingsStore()

    await store.loadSystemInfo()

    expect(store.systemInfoProvenance.freshness).toBe('degraded')
    expect(store.systemInfoProvenance.source).toBe('legacy_fallback')
    await expect(store.clearCache()).resolves.toBe(false)
    expect(apiMocks.clearCache).not.toHaveBeenCalled()
  })

  it('marks cached embedding catalogues as stale and blocks model mutations', async () => {
    seedEmbeddingContract()
    apiMocks.getEmbeddingModels.mockRejectedValueOnce(httpError(503))
    ;(window.localStorage.getItem as Mock).mockImplementation((key: string) => {
      if (key !== 'candyconc_embeddings') return null
      return JSON.stringify({
        models: [
          { id: 'stale-model', name: 'Stale model', size: '1 MB', downloaded: true },
        ],
        active: 'stale-model',
      })
    })
    const store = useSettingsStore()

    await store.loadEmbeddings()

    expect(store.embeddings).toHaveLength(1)
    expect(store.embeddingCatalogueProvenance.freshness).toBe('stale_cache')
    expect(store.embeddingCatalogueIsStale).toBe(true)

    await expect(store.removeEmbedding('stale-model')).resolves.toBe(false)
    expect(apiMocks.deleteEmbeddingModel).not.toHaveBeenCalled()
  })

  it('does not replace authorization failures with stale local embedding catalogues', async () => {
    seedEmbeddingContract()
    apiMocks.getEmbeddingModels.mockRejectedValueOnce(httpError(403))
    ;(window.localStorage.getItem as Mock).mockReturnValue(JSON.stringify({
      models: [
        { id: 'hidden-model', name: 'Hidden model', size: '1 MB', downloaded: true },
      ],
      active: 'hidden-model',
    }))
    const store = useSettingsStore()

    await store.loadEmbeddings()

    expect(window.localStorage.getItem).not.toHaveBeenCalledWith('candyconc_embeddings')
    expect(store.embeddings).toEqual([])
    expect(store.embeddingCatalogueProvenance.freshness).toBe('unavailable')
    expect(store.embeddingCatalogueProvenance.message).toContain('nicht freigegeben')
  })

  it('keeps queued embedding downloads running until the backend catalogue proves installation', async () => {
    seedEmbeddingContract()
    apiMocks.downloadEmbeddingModel.mockResolvedValueOnce({
      status: 'queued',
      run_id: 'embedding-run-queued',
      job_id: 'embedding-run-queued',
      status_url: '/api/v1/operation-runs/embedding-run-queued',
      operation_id: 'settings.embedding_management.download',
    })
    apiMocks.getOperationRun.mockResolvedValueOnce({
      run_id: 'embedding-run-queued',
      job_id: 'embedding-run-queued',
      operation_id: 'settings.embedding_management.download',
      source_id: 'fasttext-de',
      kind: 'operation',
      label: 'Embedding-Download: fasttext-de',
      status: 'queued',
      phase: 'queued',
      progress: 25,
      message: 'Embedding-Download wurde serverseitig eingereiht.',
      error: null,
      result_ref: null,
      readiness: 'pending',
      warnings: [],
      evidence: {},
      created_at: '2026-06-20T10:00:00.000Z',
      updated_at: '2026-06-20T10:00:00.000Z',
      finished_at: null,
    })
    const store = useSettingsStore()
    store.embeddings = [
      {
        id: 'fasttext-de',
        name: 'fastText Deutsch',
        language: 'de',
        size: '1 MB',
        downloaded: false,
        url: 'https://example.invalid/fasttext-de.bin',
      },
    ]
    store.embeddingCatalogueProvenance = {
      freshness: 'fresh',
      source: 'backend',
      message: 'test',
    }

    const result = await store.downloadEmbedding('fasttext-de')

    expect(result).toBe('queued')
    expect(apiMocks.downloadEmbeddingModel).toHaveBeenCalledWith(
      'fasttext-de',
      'https://example.invalid/fasttext-de.bin',
      undefined,
    )
    const runs = useProductOperationRunsStore()
    const run = runs.records.find((candidate) =>
      candidate.operationId === 'settings.embedding_management.download' &&
      candidate.sourceId === 'fasttext-de',
    )
    expect(run?.status).toBe('queued')
    expect(run?.progress).toBe(25)
    expect(run?.message).toContain('eingereiht')
    expect(run?.message).not.toContain('heruntergeladen')
    expect(store.downloadProgress['fasttext-de']).toBe(25)
  })

  it('uses backend OperationRun status when embedding download returns a run id', async () => {
    seedEmbeddingContract()
    apiMocks.downloadEmbeddingModel.mockResolvedValueOnce({
      status: 'queued',
      run_id: 'embedding-run-1',
      job_id: 'embedding-run-1',
      status_url: '/api/v1/operation-runs/embedding-run-1',
      operation_id: 'settings.embedding_management.download',
    })
    apiMocks.getOperationRun.mockResolvedValueOnce({
      run_id: 'embedding-run-1',
      job_id: 'embedding-job-1',
      operation_id: 'settings.embedding_management.download',
      source_id: 'fasttext-de',
      kind: 'operation',
      label: 'Embedding-Download: fasttext-de',
      status: 'running',
      phase: 'downloading',
      progress: 40,
      message: 'Embedding-Paket wird heruntergeladen.',
      error: null,
      result_ref: 'models://fasttext-de',
      readiness: 'pending',
      warnings: ['Katalog noch nicht aktualisiert.'],
      evidence: {
        checksum: 'sha256:abc',
      },
      created_at: '2026-06-20T10:00:00.000Z',
      updated_at: '2026-06-20T10:01:00.000Z',
      finished_at: null,
    })
    const store = useSettingsStore()
    store.embeddings = [
      {
        id: 'fasttext-de',
        name: 'fastText Deutsch',
        language: 'de',
        size: '1 MB',
        downloaded: false,
        url: 'https://example.invalid/fasttext-de.bin',
      },
    ]
    store.embeddingCatalogueProvenance = {
      freshness: 'fresh',
      source: 'backend',
      message: 'test',
    }

    const result = await store.downloadEmbedding('fasttext-de')

    expect(result).toBe('queued')
    expect(apiMocks.getOperationRun).toHaveBeenCalledWith('embedding-run-1')
    const run = useProductOperationRunsStore().records.find((candidate) =>
      candidate.operationId === 'settings.embedding_management.download' &&
      candidate.sourceId === 'fasttext-de',
    )
    expect(run?.status).toBe('running')
    expect(run?.progress).toBe(40)
    expect(run?.detail).toBe('/api/v1/operation-runs/embedding-run-1')
    expect(run?.backendRunId).toBe('embedding-run-1')
    expect(run?.backendJobId).toBe('embedding-job-1')
    expect(run?.phase).toBe('downloading')
    expect(run?.resultRef).toBe('models://fasttext-de')
    expect(run?.evidence).toEqual({ checksum: 'sha256:abc' })
    expect(run?.warnings).toEqual(['Katalog noch nicht aktualisiert.'])
    expect(store.downloadProgress['fasttext-de']).toBe(40)
  })

  it('finishes embedding downloads only when the refreshed catalogue marks the model as installed', async () => {
    seedEmbeddingContract()
    apiMocks.downloadEmbeddingModel.mockResolvedValueOnce({
      status: 'queued',
      run_id: 'embedding-run-installed',
      job_id: 'embedding-run-installed',
      status_url: '/api/v1/operation-runs/embedding-run-installed',
      operation_id: 'settings.embedding_management.download',
    })
    apiMocks.getOperationRun.mockResolvedValueOnce({
      run_id: 'embedding-run-installed',
      job_id: 'embedding-run-installed',
      operation_id: 'settings.embedding_management.download',
      source_id: 'fasttext-de',
      kind: 'operation',
      label: 'Embedding-Download: fasttext-de',
      status: 'succeeded',
      phase: 'verified',
      progress: 100,
      message: 'Embedding-Paket wurde installiert und verifiziert.',
      error: null,
      result_ref: 'models://fasttext-de',
      readiness: 'verified',
      warnings: [],
      evidence: { installed: true },
      created_at: '2026-06-20T10:00:00.000Z',
      updated_at: '2026-06-20T10:01:00.000Z',
      finished_at: '2026-06-20T10:01:00.000Z',
    })
    apiMocks.getEmbeddingModels.mockResolvedValueOnce([
      {
        id: 'fasttext-de',
        name: 'fastText Deutsch',
        language: 'de',
        sizeBytes: 1_048_576,
        installed: true,
        url: 'https://example.invalid/fasttext-de.bin',
      },
    ])
    const store = useSettingsStore()
    store.embeddings = [
      {
        id: 'fasttext-de',
        name: 'fastText Deutsch',
        language: 'de',
        size: '1 MB',
        downloaded: false,
        url: 'https://example.invalid/fasttext-de.bin',
      },
    ]
    store.embeddingCatalogueProvenance = {
      freshness: 'fresh',
      source: 'backend',
      message: 'test',
    }

    const result = await store.downloadEmbedding('fasttext-de')

    expect(result).toBe('installed')
    const runs = useProductOperationRunsStore()
    const run = runs.records.find((candidate) =>
      candidate.operationId === 'settings.embedding_management.download' &&
      candidate.sourceId === 'fasttext-de',
    )
    expect(run?.status).toBe('succeeded')
    expect(run?.progress).toBe(100)
    expect(run?.message).toContain('Backend-Katalog')
    expect(store.downloadProgress['fasttext-de']).toBeUndefined()
  })

  it('loads the embedding catalogue without the unused active-embedding preference', async () => {
    // activeEmbedding was read from the preferences, cached and cleared on
    // removal, but nothing used it. Loading the catalogue asked the server for
    // the preferences on every call.
    seedPreferencesContract()
    const preferenceCapabilities = useProductCapabilitiesStore().contract!.capabilities
    seedEmbeddingContract()
    useProductCapabilitiesStore().contract!.capabilities.push(...preferenceCapabilities)
    apiMocks.getPrefs.mockResolvedValue({ prefs: { activeEmbedding: 'gemma' } })
    apiMocks.getEmbeddingModels.mockResolvedValueOnce([
      { id: 'gemma', name: 'EmbeddingGemma', size: '300 MB', downloaded: true },
    ] as never)
    const store = useSettingsStore()

    await store.loadEmbeddings()

    expect(store.embeddings).toHaveLength(1)
    expect(apiMocks.getPrefs).not.toHaveBeenCalled()
    expect('activeEmbedding' in store).toBe(false)
    const cached = (window.localStorage.setItem as Mock).mock.calls.find(([key]) => key === 'candyconc_embeddings')
    expect(cached).toBeTruthy()
    expect(JSON.parse(cached![1] as string)).not.toHaveProperty('active')
  })

  it('does not change local preferences when backend preference persistence fails', async () => {
    seedPreferencesContract()
    apiMocks.updatePrefs.mockRejectedValueOnce(new Error('offline'))
    const store = useSettingsStore()

    await store.savePreference('highlightColor', 'blue')

    expect(apiMocks.updatePrefs).toHaveBeenCalledWith({ highlightColor: 'blue' })
    expect(store.preferences.highlightColor).toBe('yellow')
    expect(window.localStorage.setItem).not.toHaveBeenCalledWith(
      'candyconc_preferences',
      expect.stringContaining('blue'),
    )
  })

})
