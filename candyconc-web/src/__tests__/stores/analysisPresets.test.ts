import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useAnalysisPresetsStore, type AnalysisPreset } from '@/stores/analysisPresets'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'

const apiMocks = vi.hoisted(() => ({
  createAnalysisPreset: vi.fn(),
  deleteAnalysisPreset: vi.fn(),
  getAnalysisJob: vi.fn(),
  getAnalysisPresets: vi.fn(),
  getAuthSession: vi.fn(),
  getProductCapabilities: vi.fn(),
  getSystemInfo: vi.fn(),
  touchAnalysisPreset: vi.fn(),
  updateAnalysisPreset: vi.fn(),
}))

vi.mock('@/api/client', () => ({
  createAnalysisPreset: (...args: unknown[]) => apiMocks.createAnalysisPreset(...args),
  deleteAnalysisPreset: (...args: unknown[]) => apiMocks.deleteAnalysisPreset(...args),
  getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
  getAnalysisPresets: (...args: unknown[]) => apiMocks.getAnalysisPresets(...args),
  getAuthSession: (...args: unknown[]) => apiMocks.getAuthSession(...args),
  getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
  getSystemInfo: (...args: unknown[]) => apiMocks.getSystemInfo(...args),
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
  touchAnalysisPreset: (...args: unknown[]) => apiMocks.touchAnalysisPreset(...args),
  updateAnalysisPreset: (...args: unknown[]) => apiMocks.updateAnalysisPreset(...args),
}))

function presetRecord(id = 'preset-1') {
  return {
    id,
    name: 'Frequenz Demo',
    type: 'frequency',
    corpus: 'demo',
    docset: null,
    query_term: 'Hase',
    params: { groupBy: 'word' },
    result: null,
    result_meta: null,
    status: 'idle',
    job_id: null,
    kind: 'saved',
    created_at: 1000,
    updated_at: 1000,
    last_accessed_at: 1000,
  }
}

function seedContracts(role: 'user' | 'admin' = 'user', requiredRole: 'user' | 'admin' = 'user') {
  const productCapabilities = useProductCapabilitiesStore()
  const routeDescriptors = [
    { path: '/api/v1/projects/{proj}/analysis-presets', methods: ['GET'], mutates: false },
    { path: '/api/v1/projects/{proj}/analysis-presets', methods: ['POST'], mutates: true },
    { path: '/api/v1/projects/{proj}/analysis-presets/{preset_id}', methods: ['PATCH'], mutates: true },
    { path: '/api/v1/projects/{proj}/analysis-presets/{preset_id}', methods: ['DELETE'], mutates: true },
    { path: '/api/v1/projects/{proj}/analysis-presets/{preset_id}/touch', methods: ['POST'], mutates: true },
  ].map((route) => ({
    ...route,
    requires_corpus_features: [],
    access: requiredRole,
    required_role: requiredRole,
    transport: 'http',
    route_class: 'product_surface',
  }))
  const operations = [
    { id: 'research.analysis_presets.list', path: '/api/v1/projects/{proj}/analysis-presets', method: 'GET', label: 'Analyse-Presets laden' },
    { id: 'research.analysis_presets.create', path: '/api/v1/projects/{proj}/analysis-presets', method: 'POST', label: 'Analyse-Preset speichern' },
    { id: 'research.analysis_presets.update', path: '/api/v1/projects/{proj}/analysis-presets/{preset_id}', method: 'PATCH', label: 'Analyse-Preset aktualisieren' },
    { id: 'research.analysis_presets.delete', path: '/api/v1/projects/{proj}/analysis-presets/{preset_id}', method: 'DELETE', label: 'Analyse-Preset löschen' },
    { id: 'research.analysis_presets.touch', path: '/api/v1/projects/{proj}/analysis-presets/{preset_id}/touch', method: 'POST', label: 'Analyse-Preset zuletzt-verwendet markieren' },
  ].flatMap((spec) => {
    const descriptor = routeDescriptors.find((route) =>
      route.path === spec.path &&
      route.methods.map((method) => method.toUpperCase()).includes(spec.method)
    )
    if (!descriptor) return []
    return [{
      id: spec.id,
      capability_id: 'research.analysis_presets',
      label: spec.label,
      description: '',
      route: { ...descriptor, methods: [spec.method] },
      effects: spec.method === 'GET' ? ['read'] : ['write'],
      handler_key: spec.id,
      surface_slot: spec.id,
      priority: 100,
    }]
  })
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [{
      id: 'research.analysis_presets',
      title: 'Analysis presets',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [
        '/api/v1/projects/{proj}/analysis-presets',
        '/api/v1/projects/{proj}/analysis-presets/{preset_id}',
        '/api/v1/projects/{proj}/analysis-presets/{preset_id}/touch',
      ],
      backend_route_descriptors: routeDescriptors,
      operations,
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
      notes: '',
    }],
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


function appendAsyncJobsCapability(options: { includeStatus?: boolean } = {}) {
  const productCapabilities = useProductCapabilitiesStore()
  const statusRoute = {
    path: '/api/v1/analysis/jobs/{job_id}',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
  const rowsRoute = {
    path: '/api/v1/analysis/jobs/{job_id}/rows',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
  const operations = [
    ...(options.includeStatus === false
      ? []
      : [{
          id: 'analysis.async_jobs.status',
          capability_id: 'analysis.async_jobs',
          label: 'Analysejob-Status',
          description: '',
          route: statusRoute,
          effects: ['read'],
          handler_key: 'analysis_job_status',
          surface_slot: 'analysis.jobs.status',
          priority: 10,
        }]),
    {
      id: 'analysis.async_jobs.rows',
      capability_id: 'analysis.async_jobs',
      label: 'Analysejob-Zeilen',
      description: '',
      route: rowsRoute,
      effects: ['read'],
      handler_key: 'analysis_job_rows',
      surface_slot: 'analysis.jobs.rows',
      priority: 30,
    },
  ]
  productCapabilities.contract!.capabilities.push({
    id: 'analysis.async_jobs',
    title: 'Analysis jobs',
    area: 'analysis',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [statusRoute.path, rowsRoute.path],
    backend_route_descriptors: [statusRoute, rowsRoute],
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    notes: '',
  } as never)
}

function presetInput(): AnalysisPreset {
  return {
    id: 'preset-new',
    name: 'Neue Frequenz',
    type: 'frequency',
    corpus: 'demo',
    docset: null,
    queryTerm: 'Zeit',
    params: { groupBy: 'word' },
    status: 'idle',
    kind: 'saved',
    createdAt: 2000,
    updatedAt: 2000,
    lastAccessedAt: 2000,
  }
}

describe('analysis presets route-operation gates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    localStorage.clear()
    vi.clearAllMocks()
    seedContracts()
    apiMocks.getAnalysisPresets.mockResolvedValue([presetRecord()])
    apiMocks.createAnalysisPreset.mockResolvedValue(presetRecord('preset-new'))
    apiMocks.updateAnalysisPreset.mockResolvedValue({ ...presetRecord(), name: 'Umbenannt' })
    apiMocks.touchAnalysisPreset.mockResolvedValue({ ...presetRecord(), last_accessed_at: 3000 })
    apiMocks.deleteAnalysisPreset.mockResolvedValue(undefined)
    apiMocks.getSystemInfo.mockResolvedValue({ backendVersion: 'test', tokenCount: 10, documentCount: 1 })
  })

  it('uses the route-specific preset operations for load, create, update, touch and delete', async () => {
    const store = useAnalysisPresetsStore()

    await store.init()
    expect(apiMocks.getAnalysisPresets).toHaveBeenCalledWith('default')
    expect(store.presets.map((preset) => preset.id)).toEqual(['preset-1'])

    await store.add(presetInput())
    expect(apiMocks.createAnalysisPreset).toHaveBeenCalledWith(expect.objectContaining({
      id: 'preset-new',
      query_term: 'Zeit',
    }), 'default')

    await store.update('preset-1', { name: 'Umbenannt' })
    expect(apiMocks.updateAnalysisPreset).toHaveBeenCalledWith('preset-1', { name: 'Umbenannt' }, 'default')

    await store.touch('preset-1')
    expect(apiMocks.touchAnalysisPreset).toHaveBeenCalledWith('preset-1', 'default')

    await store.remove('preset-1')
    expect(apiMocks.deleteAnalysisPreset).toHaveBeenCalledWith('preset-1', 'default')
  })

  it('migrates only exact retired chi2 preset parameters before persisting local presets', async () => {
    const serialized = JSON.stringify([{
      ...presetInput(),
      id: 'legacy-chi2',
      params: {
        metric: 'mi2',
        measure: 'MI2',
        sortBy: 'mi2',
        note: 'mi2',
        nested: { metric: 'mi2' },
      },
      result: { rows: [{ chi2_cell: 4.2, mi2: 999 }] },
      resultMeta: { cacheKey: 'historical-cache' },
    }])
    vi.mocked(localStorage.getItem).mockImplementation((key) =>
      key === 'candyconc_analysis_presets' ? serialized : null
    )
    apiMocks.getAnalysisPresets.mockResolvedValue([])
    apiMocks.createAnalysisPreset.mockImplementation(async (preset: unknown) => preset)

    const store = useAnalysisPresetsStore()
    await store.init()

    expect(store.presets).toHaveLength(1)
    expect(localStorage.setItem).toHaveBeenCalledWith(
      'candyconc_analysis_presets',
      expect.stringContaining('chi2_cell'),
    )
    expect(apiMocks.createAnalysisPreset).toHaveBeenCalledWith(expect.objectContaining({
      params: {
        metric: 'chi2_cell',
        measure: 'MI2',
        sortBy: 'chi2_cell',
        note: 'mi2',
        nested: { metric: 'mi2' },
      },
      result: { rows: [{ chi2_cell: 4.2, mi2: 999 }] },
      result_meta: { cacheKey: 'historical-cache' },
    }), 'default')
    expect(localStorage.removeItem).toHaveBeenCalledWith('candyconc_analysis_presets')
  })

  it('invalidates cached results without the current cache version', async () => {
    const store = useAnalysisPresetsStore()
    const preset = {
      ...presetInput(),
      result: { rows: [{ word: 'Hase' }] },
      resultMeta: { cacheKey: 'legacy-cache' },
    }

    await expect(store.isResultValid(preset)).resolves.toBe(false)
  })

  it('blocks preset persistence operations before backend calls when the session lacks the route role', async () => {
    seedContracts('user', 'admin')
    vi.clearAllMocks()
    const store = useAnalysisPresetsStore()

    await store.init()
    expect(apiMocks.getAnalysisPresets).not.toHaveBeenCalled()
    expect(store.error).toContain('Rolle Admin')

    await expect(store.add(presetInput())).rejects.toThrow('Rolle Admin')
    await expect(store.update('preset-1', { name: 'x' })).rejects.toThrow('Rolle Admin')
    await expect(store.touch('preset-1')).rejects.toThrow('Rolle Admin')
    await expect(store.remove('preset-1')).rejects.toThrow('Rolle Admin')

    expect(apiMocks.createAnalysisPreset).not.toHaveBeenCalled()
    expect(apiMocks.updateAnalysisPreset).not.toHaveBeenCalled()
    expect(apiMocks.touchAnalysisPreset).not.toHaveBeenCalled()
    expect(apiMocks.deleteAnalysisPreset).not.toHaveBeenCalled()
  })

  it('refreshes running preset jobs only through the async-job status ProductOperation', async () => {
    appendAsyncJobsCapability({ includeStatus: false })
    apiMocks.getAnalysisPresets.mockResolvedValue([{ ...presetRecord(), status: 'running', job_id: 'job-running-1' }])
    const store = useAnalysisPresetsStore()

    await store.init()

    expect(apiMocks.getAnalysisJob).not.toHaveBeenCalled()
    expect(apiMocks.updateAnalysisPreset).toHaveBeenCalledWith(
      'preset-1',
      { status: 'error' },
      'default',
    )
  })

  it('keeps exploratory job sessions separate from saved presets', async () => {
    const store = useAnalysisPresetsStore()
    await store.init()
    vi.clearAllMocks()

    const session = await store.upsertJobSession({
      id: 'preset-1',
      name: 'Kollokationen · Hase',
      type: 'collocations',
      corpus: 'demo',
      docset: null,
      queryTerm: 'Hase',
      params: { windowSize: 5 },
      status: 'queued',
      jobId: 'job-1',
    })

    expect(session.id).not.toBe('preset-1')
    expect(store.presets.map((preset) => preset.id)).toEqual(['preset-1'])
    expect(store.sessionPresets.map((preset) => preset.id)).toEqual([session.id])
    expect(apiMocks.createAnalysisPreset).not.toHaveBeenCalled()
    expect(apiMocks.updateAnalysisPreset).not.toHaveBeenCalled()

    await store.updateJobStatus(session.id, { status: 'running', job_id: 'job-1' } as never)
    await store.updateResult(session.id, { rows: [{ word: 'Hase', f: 2 }] }, { cacheKey: 'cache-1' })

    expect(store.sessionPresets[0]).toMatchObject({
      id: session.id,
      kind: 'session',
      status: 'done',
      result: { rows: [{ word: 'Hase', f: 2 }] },
    })
    expect(apiMocks.updateAnalysisPreset).not.toHaveBeenCalled()
  })

  it('builds a degraded cache key instead of failing analysis results when system info is admin-denied', async () => {
    apiMocks.getSystemInfo.mockRejectedValue(new Error('HTTP 403 Forbidden'))
    const store = useAnalysisPresetsStore()

    await expect(store.buildCacheKey({
      type: 'ngrams',
      corpus: 'demo',
      docset: null,
      queryTerm: 'Zeit',
      params: { ngramSize: 2, minFreq: 2, sortBy: 'frequency' },
    })).resolves.toMatch(/^[0-9a-f]+$/)

    expect(apiMocks.getSystemInfo).toHaveBeenCalledTimes(2)
    expect(apiMocks.getSystemInfo).toHaveBeenNthCalledWith(1, 'demo')
    expect(apiMocks.getSystemInfo).toHaveBeenNthCalledWith(2)
  })

})
