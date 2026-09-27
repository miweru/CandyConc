import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import {
  surfaceForCapability,
} from '@/lib/productCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useCopilotStore } from '@/stores/copilot'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ActiveTab } from '@/stores/ui'
import type { CorpusSummary, ProductCapabilityContract } from '@/api/client'

const getProductCapabilities = vi.fn()
const getAuthSession = vi.fn()
const actionBusDispatch = vi.fn()

vi.mock('@/api/client', () => ({
  getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
  getAuthSession: (...args: unknown[]) => getAuthSession(...args),
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
}))

vi.mock('@/actions', () => ({
  actionBus: {
    dispatch: (...args: unknown[]) => actionBusDispatch(...args),
  },
}))

vi.mock('@/actions/bus', () => ({
  actionBus: {
    dispatch: (...args: unknown[]) => actionBusDispatch(...args),
  },
}))

const firstClassCapabilityIds = [
  'query.kwic',
  'query.cqlf',
  'query.document_access',
  'analysis.frequency',
  'analysis.async_jobs',
  'analysis.collocations',
  'analysis.collocation_network',
  'analysis.dispersion',
  'analysis.ngrams',
  'analysis.keyness',
  'analysis.contrast',
  'analysis.wordsketch',
  'analysis.semantic_similarity',
  'admin.system_operations',
  'settings.embedding_management',
  'settings.preferences',
  'corpus.catalogue',
  'corpus.import',
  'corpus.alignment_parallel',
  'research.subcorpora_docsets',
  'research.annotations',
  'research.bookmarks',
  'research.analysis_presets',
  'research.copilot_grounding',
  'research.replay_export',
  'platform.session',
]

function capability(id: string, overrides: Record<string, unknown> = {}) {
  const fallbackRoute = {
    path: `/api/v1/test/${id.replaceAll('.', '/')}`,
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
  const backendRouteDescriptors = [fallbackRoute]
  const operations = [
    {
      id: `${id}.read`,
      capability_id: id,
      label: `${id} lesen`,
      description: '',
      route: fallbackRoute,
      effects: ['read'],
      handler_key: '',
      surface_slot: id,
      priority: 100,
      input_schema_ref: 'operation.no_input',
      required_context: [],
      response_shape: 'data',
      run_semantics: 'instant',
      ui_execution_policy: 'contextual_ui',
      requires_parameters: false,
    },
  ]
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: backendRouteDescriptors.map((route) => route.path),
    backend_route_descriptors: backendRouteDescriptors,
    operations,
    frontend_evidence: [{ path: `candyconc-web/src/${id}.vue`, contains: id }],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

function contract() {
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
      ...firstClassCapabilityIds.map((id) => capability(id)),
      capability('product.capability_contract', {
        visibility: 'expert_api',
      }),
      capability('analysis.semantic_clustering', {
        maturity: 'experimental',
        visibility: 'hidden_experimental',
      }),
    ],
  }
}

function corpusWithTokenAttributes(attributes: string[]): CorpusSummary {
  return {
    name: 'test',
    path: '/tmp/test',
    active: true,
    token_count: 100,
    doc_count: 1,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: attributes.map((id) => ({
        id,
        cql_attribute: id,
        label: id,
      })),
      frequency_groups: [],
      semantic: {
        passage_search: false,
        word_similarity: false,
        sentence_alignment: false,
      },
      alignment: {
        paired: false,
        pair_axes: [],
        parallel_groups: false,
        parallel_kwic: false,
      },
    },
  } as CorpusSummary
}

describe('product capability UI registry', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    actionBusDispatch.mockImplementation(async (action: { type?: string; payload?: { tab?: string } }) => {
      if (action.type === 'nav/switchTab' && action.payload?.tab) {
        useUiStore().setActiveTab(action.payload.tab as ActiveTab)
      }
      return { success: true }
    })
    getProductCapabilities.mockResolvedValue(contract())
    getAuthSession.mockResolvedValue({
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
    })
  })

  it('distinguishes an unloaded contract from a missing backend operation', () => {
    const store = useProductCapabilitiesStore()

    const decision = store.productOperationAvailability(
      'analysis.frequency.list',
      'Frequenzliste',
    )

    expect(decision.enabled).toBe(false)
    expect(decision.disabledReason).toContain('wartet auf den Fähigkeitskatalog')
    expect(decision.disabledReason).not.toContain('analysis.frequency.list')
    expect(decision.disabledReason).not.toContain('im geladenen Fähigkeitskatalog nicht')
  })

  it('reloads a loaded contract when the interface language changes', async () => {
    const { i18n } = await import('@/i18n')
    const { nextTick } = await import('vue')
    const store = useProductCapabilitiesStore()
    await store.load()
    expect(getProductCapabilities).toHaveBeenCalledTimes(1)

    const before = i18n.global.locale.value
    i18n.global.locale.value = before === 'en' ? 'de' : 'en'
    try {
      await nextTick()
      expect(getProductCapabilities).toHaveBeenCalledTimes(2)
    } finally {
      i18n.global.locale.value = before
      await nextTick()
    }
  })

  it('loads the contract again when the session signs in or out', async () => {
    const { nextTick } = await import('vue')
    const session = useSessionStore()
    const store = useProductCapabilitiesStore()
    const base = {
      schema_version: 'auth-session-v1',
      token_present: false,
      rbac_enabled: true,
      security_mode: 'release',
      release_mode: true,
      unsafe_token_transport: false,
      dev_token_available: false,
      can_access_all_roles: false,
    }
    const signedOut = { ...base, authenticated: false, username: null, role: null, effective_role: null }
    const reader = { ...base, authenticated: true, token_present: true, username: 'reader1', role: 'user', effective_role: 'user' }
    const admin = { ...reader, username: 'admin1', role: 'admin', effective_role: 'admin' }

    // Release mode before sign-in: the catalog answers 401, no tab is shown.
    getProductCapabilities.mockRejectedValueOnce(new Error('401 Unauthorized'))
    session.session = signedOut as never
    await store.load()
    await nextTick()
    expect(store.hasContract).toBe(false)
    expect(store.discoverableAnalysisTabs).toEqual([])
    const callsBefore = getProductCapabilities.mock.calls.length

    session.session = reader as never
    await nextTick()
    await vi.waitFor(() => expect(store.status).toBe('ready'))
    expect(getProductCapabilities.mock.calls.length).toBe(callsBefore + 1)
    expect(store.discoverableAnalysisTabs.map((surface) => surface.tab)).toContain('kwic')

    // Sign-out: the contract of the previous account does not stay on screen.
    getProductCapabilities.mockRejectedValueOnce(new Error('401 Unauthorized'))
    session.session = signedOut as never
    await nextTick()
    await vi.waitFor(() => expect(store.status).toBe('error'))
    expect(getProductCapabilities.mock.calls.length).toBe(callsBefore + 2)
    expect(store.hasContract).toBe(false)
    expect(store.discoverableAnalysisTabs).toEqual([])

    // The next account signs in: its contract is loaded.
    session.session = admin as never
    await nextTick()
    await vi.waitFor(() => expect(store.status).toBe('ready'))
    expect(getProductCapabilities.mock.calls.length).toBe(callsBefore + 3)
    expect(store.hasContract).toBe(true)
  })

  it('loads the backend contract and filters navigable analysis tabs through it', async () => {
    const store = useProductCapabilitiesStore()

    await store.ensureAccessContext()

    expect(getProductCapabilities).toHaveBeenCalledOnce()
    expect(store.status).toBe('ready')
    expect(store.discoverableAnalysisTabs.map((surface) => surface.tab)).toContain('contrast')
    expect(store.discoverableAnalysisTabs.map((surface) => surface.tab)).not.toContain('document')
  })

  it('fails analysis-tab visibility closed before a product contract or non-release fallback is available', () => {
    const store = useProductCapabilitiesStore()

    expect(store.hasContract).toBe(false)
    expect(store.isAnalysisTabVisible('kwic')).toBe(false)
    expect(store.discoverableAnalysisTabs).toEqual([])
  })

  it('opens the first-class surface for analysis capabilities', async () => {
    const store = useProductCapabilitiesStore()
    const uiStore = useUiStore()
    await store.load()

    expect(store.surfaceAvailability('analysis.frequency').openLabel).toBe('Analyse öffnen')
    expect(await store.openSurface('analysis.frequency')).toBe(true)
    expect(uiStore.activeTab).toBe('frequency')
    expect(actionBusDispatch).toHaveBeenCalledWith(
      { type: 'nav/switchTab', payload: { tab: 'frequency' } },
      { source: 'user' },
    )
  })

  it('keeps document access scoped to KWIC evidence instead of advertising a standalone document browser', async () => {
    const store = useProductCapabilitiesStore()
    const uiStore = useUiStore()
    await store.load()

    expect(surfaceForCapability('query.document_access')).toMatchObject({
      kind: 'kwic_layer',
      label: 'KWIC-Dokumentbelege',
      openTarget: { kind: 'kwic_tab' },
    })
    expect(store.surfaceAvailability('query.document_access').openLabel).toBe('KWIC öffnen')
    expect(await store.openSurface('query.document_access')).toBe(true)
    expect(uiStore.activeTab).toBe('kwic')
  })

  it('opens first-class corpus and copilot surfaces from the same contract mapping', async () => {
    const store = useProductCapabilitiesStore()
    const uiStore = useUiStore()
    const copilotStore = useCopilotStore()
    await store.load()

    expect(await store.openSurface('corpus.import')).toBe(true)
    expect(uiStore.settingsOpen).toBe(true)
    expect(uiStore.corpusManagerOpen).toBe(true)

    expect(await store.openSurface('research.copilot_grounding')).toBe(true)
    expect(copilotStore.isOpen).toBe(true)
  })

  it('opens the first-class session surface as the auth panel', async () => {
    const store = useProductCapabilitiesStore()
    const uiStore = useUiStore()
    await store.load()

    expect(store.surfaceAvailability('platform.session').openLabel).toBe('Session öffnen')
    expect(await store.openSurface('platform.session')).toBe(true)
    expect(uiStore.authOpen).toBe(true)
  })

  it('does not expose hidden experimental or API-only surfaces as first-class open targets', async () => {
    const store = useProductCapabilitiesStore()
    await store.load()

    expect(store.surfaceAvailability('analysis.semantic_clustering')).toMatchObject({
      status: 'hidden',
      visible: false,
      enabled: false,
    })
    expect(await store.openSurface('analysis.semantic_clustering')).toBe(false)
  })

  it('indexes semantic product operations as route-aware availability decisions', async () => {
    const next = contract()
    next.capabilities = next.capabilities.map((item) => item.id === 'corpus.alignment_parallel'
      ? {
          ...item,
          backend_routes: ['/api/v1/analysis/kwic_parallel'],
          backend_route_descriptors: [{
            path: '/api/v1/analysis/kwic_parallel',
            methods: ['POST'],
            mutates: false,
            requires_corpus_features: ['alignment.parallel_kwic'],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          }],
          operations: [{
            id: 'corpus.alignment_parallel.parallel_kwic',
            capability_id: 'corpus.alignment_parallel',
            label: 'Parallel-KWIC',
            description: '',
            route: {
              path: '/api/v1/analysis/kwic_parallel',
              methods: ['POST'],
              mutates: false,
              requires_corpus_features: ['alignment.parallel_kwic'],
              access: 'user',
              required_role: 'user',
              transport: 'http',
              route_class: 'product_surface',
            },
            effects: ['read', 'long_running'],
            handler_key: 'parallel_kwic',
            surface_slot: 'kwic.row.parallel',
            priority: 10,
          }],
        }
      : item)
    getProductCapabilities.mockResolvedValueOnce(next)

    const store = useProductCapabilitiesStore()
    const sessionStore = useSessionStore()
    sessionStore.status = 'ready'
    sessionStore.session = {
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
    await store.load()

    expect(store.operationFor('corpus.alignment_parallel.parallel_kwic')?.handler_key).toBe('parallel_kwic')
    const decision = store.productOperationAvailability('corpus.alignment_parallel.parallel_kwic')
    expect(decision.enabled).toBe(true)
    expect(decision.operations).toEqual([
      { path: '/api/v1/analysis/kwic_parallel', method: 'POST' },
    ])
  })

  it('uses the loaded session role as an effective UI access gate', async () => {
    const next = contract()
    next.capabilities = next.capabilities.map((item) => item.id === 'corpus.import'
      ? {
          ...item,
          backend_routes: ['/api/v1/corpora/imports'],
          backend_route_descriptors: [{
            path: '/api/v1/corpora/imports',
            methods: ['POST'],
            mutates: true,
            requires_corpus_features: [],
            access: 'admin',
            required_role: 'admin',
            transport: 'http',
            route_class: 'admin_surface',
          }],
        }
      : item)
    getProductCapabilities.mockResolvedValueOnce(next)
    getAuthSession.mockResolvedValueOnce({
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
    })

    const store = useProductCapabilitiesStore()
    const sessionStore = useSessionStore()
    await store.load()
    expect(store.isVisible('corpus.import')).toBe(false)

    await sessionStore.load()
    expect(store.isVisible('corpus.import')).toBe(false)
    expect(store.accessBlockReason('corpus.import', 'Korpusimport')).toContain('Rolle Admin')

    getAuthSession.mockResolvedValueOnce({
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
      can_access_all_roles: false,
    })
    await sessionStore.load(true)
    expect(store.isVisible('corpus.import')).toBe(true)
  })

  it('keeps first-class surfaces discoverable when role access blocks execution', async () => {
    const next = contract()
    next.capabilities = next.capabilities.map((item) => item.id === 'corpus.import'
      ? {
          ...item,
          backend_routes: ['/api/v1/corpora/imports'],
          backend_route_descriptors: [{
            path: '/api/v1/corpora/imports',
            methods: ['POST'],
            mutates: true,
            requires_corpus_features: [],
            access: 'admin',
            required_role: 'admin',
            transport: 'http',
            route_class: 'admin_surface',
          }],
        }
      : item)
    getProductCapabilities.mockResolvedValueOnce(next)
    getAuthSession.mockResolvedValueOnce({
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
    })

    const store = useProductCapabilitiesStore()
    await store.ensureAccessContext()

    expect(store.isVisible('corpus.import')).toBe(false)
    expect(store.surfaceAvailability('corpus.import')).toMatchObject({
      status: 'disabled',
      visible: true,
      enabled: false,
      disabledReason: expect.stringContaining('Rolle Admin'),
      openLabel: 'Korpusverwaltung öffnen',
    })
  })

  it('keeps role-blocked analysis tabs discoverable while execution stays disabled', async () => {
    const next = contract()
    next.capabilities = next.capabilities.map((item) => item.id === 'analysis.frequency'
      ? {
          ...item,
          backend_routes: ['/api/v1/analysis/frequency_list'],
          backend_route_descriptors: [{
            path: '/api/v1/analysis/frequency_list',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'admin',
            required_role: 'admin',
            transport: 'http',
            route_class: 'admin_surface',
          }],
        }
      : item)
    getProductCapabilities.mockResolvedValueOnce(next)
    getAuthSession.mockResolvedValueOnce({
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
    })

    const store = useProductCapabilitiesStore()
    await store.ensureAccessContext()

    expect(store.isAnalysisTabVisible('frequency')).toBe(false)
    expect(store.discoverableAnalysisTabs.map((surface) => surface.tab)).toContain('frequency')
    expect(store.surfaceAvailability('analysis.frequency')).toMatchObject({
      status: 'disabled',
      visible: true,
      enabled: false,
      disabledReason: expect.stringContaining('Rolle Admin'),
      openLabel: 'Analyse öffnen',
    })
  })

  it('checks ProductOperation route roles directly instead of broad capability routes', async () => {
    const next = contract()
    next.capabilities = next.capabilities.map((item) => item.id === 'research.subcorpora_docsets'
      ? {
          ...item,
          backend_routes: ['/api/v1/subcorpora'],
          backend_route_descriptors: [{
            path: '/api/v1/subcorpora',
            methods: ['POST'],
            mutates: true,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          }],
          operations: [{
            id: 'research.subcorpora_docsets.subcorpora_save',
            capability_id: 'research.subcorpora_docsets',
            label: 'Subkorpus speichern',
            description: 'Speichert ein Subkorpus.',
            route: {
              path: '/api/v1/subcorpora',
              methods: ['POST'],
              mutates: true,
              requires_corpus_features: [],
              access: 'admin',
              required_role: 'admin',
              transport: 'http',
              route_class: 'admin_surface',
            },
            effects: ['write'],
            input_schema_ref: 'operation.generic_request',
            response_shape: 'data',
            ui_execution_policy: 'contextual_ui',
            required_context: [],
            handler_key: 'saveSubcorpus',
            surface_slot: 'workspace.subcorpora.save',
            priority: 10,
          }],
        }
      : item)
    getProductCapabilities.mockResolvedValueOnce(next)

    const store = useProductCapabilitiesStore()
    await store.ensureAccessContext()

    expect(
      store.productOperationAvailability('research.subcorpora_docsets.subcorpora_save'),
    ).toMatchObject({
      visible: true,
      enabled: false,
      disabledReason: expect.stringContaining('Rolle Admin'),
      operations: [{ path: '/api/v1/subcorpora', method: 'POST' }],
    })

    expect(
      store.operationForRoute(
        'research.subcorpora_docsets',
        '/api/v1/subcorpora',
        'POST',
      )?.id,
    ).toBe('research.subcorpora_docsets.subcorpora_save')

    await expect(
      store.assertProductOperationAccess('research.subcorpora_docsets.subcorpora_save', 'Subkorpus speichern'),
    ).rejects.toThrow('Rolle Admin')
  })

  it('applies corpus feature requirements to operation UI records when a corpus summary is supplied', async () => {
    const wordSketchRoute = {
      path: '/api/v1/analysis/wordsketch',
      methods: ['POST'],
      mutates: false,
      requires_corpus_features: ['token_attributes.rel'],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    }
    const next = contract()
    next.capabilities = next.capabilities.map((item) => item.id === 'analysis.wordsketch'
      ? {
          ...item,
          backend_routes: ['/api/v1/analysis/wordsketch'],
          backend_route_descriptors: [wordSketchRoute],
          operations: [{
            id: 'analysis.wordsketch.profile',
            capability_id: 'analysis.wordsketch',
            label: 'Word Sketch berechnen',
            description: 'Berechnet ein Word Sketch Profil.',
            route: wordSketchRoute,
            effects: ['read'],
            input_schema_ref: 'analysis.wordsketch_request',
            response_shape: 'data',
            ui_execution_policy: 'contextual_ui',
            required_context: ['active_query', 'corpus_features'],
            handler_key: 'loadWordSketch',
            surface_slot: 'analysis.wordsketch.profile',
            priority: 10,
          }],
        }
      : item)
    getProductCapabilities.mockResolvedValueOnce(next)

    const store = useProductCapabilitiesStore()
    await store.ensureAccessContext()

    const blocked = store.operationUiRecordFor(
      'analysis.wordsketch.profile',
      corpusWithTokenAttributes(['word', 'lemma', 'pos']),
    )
    expect(blocked).toMatchObject({
      corpusFeatureDecision: {
        status: 'blocked',
        missing: ['token_attributes.rel'],
      },
      availability: {
        enabled: false,
        disabledReason: expect.stringContaining('Tokenattribut rel'),
      },
    })

    const enabled = store.operationUiRecordFor(
      'analysis.wordsketch.profile',
      corpusWithTokenAttributes(['word', 'lemma', 'pos', 'rel']),
    )
    expect(enabled).toMatchObject({
      corpusFeatureDecision: {
        status: 'pass',
        missing: [],
      },
      availability: {
        enabled: true,
        disabledReason: null,
      },
    })
  })

  it('hides planned or unsupported tab capabilities once the backend contract says so', async () => {
    const next = contract()
    next.capabilities = next.capabilities.map((item) => item.id === 'analysis.wordsketch'
      ? { ...item, maturity: 'planned' }
      : item)
    getProductCapabilities.mockResolvedValueOnce(next)

    const store = useProductCapabilitiesStore()
    await store.load()

    expect(store.discoverableAnalysisTabs.map((surface) => surface.tab)).not.toContain('wordsketch')
    expect(store.analysisTabAvailability('wordsketch')).toMatchObject({
      status: 'hidden',
      enabled: false,
    })
  })
})
