import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { WORD_SKETCH_OPERATIONS, WORD_SKETCH_ROUTES, useWordSketchOperations } from '@/composables/useWordSketchOperations'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getWordSketch: vi.fn(),
  getWordSketchDiff: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getWordSketch: (...args: unknown[]) => apiMocks.getWordSketch(...args),
    getWordSketchDiff: (...args: unknown[]) => apiMocks.getWordSketchDiff(...args),
  }
})

function route(path: string) {
  return {
    path,
    methods: ['POST'],
    mutates: false,
    requires_corpus_features: ['token_attributes.rel'],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const profileRoute = route(WORD_SKETCH_ROUTES.profile)
  const diffRoute = route(WORD_SKETCH_ROUTES.diff)
  return {
    id: 'analysis.wordsketch',
    title: 'Word Sketch',
    area: 'analysis',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [profileRoute, diffRoute],
    backend_route_descriptors: [profileRoute, diffRoute],
    operations: [
      {
        id: WORD_SKETCH_OPERATIONS.profile,
        capability_id: 'analysis.wordsketch',
        label: 'Word Sketch',
        description: '',
        route: profileRoute,
        effects: ['read'],
        handler_key: 'word_sketch',
        surface_slot: 'analysis.wordsketch.profile',
        priority: 10,
      },
      {
        id: WORD_SKETCH_OPERATIONS.diff,
        capability_id: 'analysis.wordsketch',
        label: 'Word-Sketch-Vergleich',
        description: '',
        route: diffRoute,
        effects: ['read'],
        handler_key: 'word_sketch_diff',
        surface_slot: 'analysis.wordsketch.diff',
        priority: 20,
      },
    ],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

function contract(item: ProductCapability): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [item],
  }
}

function seedUserSession() {
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

function seedWordSketchCorpusFeatures() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'rel', cql_attribute: 'rel', label: 'Relation' }],
    },
  }]
}

describe('useWordSketchOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
    seedWordSketchCorpusFeatures()
  })

  it('blocks profile loading when the ProductOperation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({ operations: [] }))
    productCapabilities.status = 'ready'

    const { loadWordSketch } = useWordSketchOperations()

    await expect(loadWordSketch({ term: 'Sprache' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.getWordSketch).not.toHaveBeenCalled()
  })

  it('routes diff loading through ProductOperation availability', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'
    apiMocks.getWordSketchDiff.mockResolvedValue({ termA: 'A', termB: 'B', relations: [] })

    const { loadWordSketchDiff, canLoadWordSketchDiff } = useWordSketchOperations()

    await expect(loadWordSketchDiff({ termA: 'A', termB: 'B', corpus: 'demo' })).resolves.toEqual({
      termA: 'A',
      termB: 'B',
      relations: [],
    })
    expect(canLoadWordSketchDiff.value).toBe(true)
    expect(apiMocks.getWordSketchDiff).toHaveBeenCalledWith({ termA: 'A', termB: 'B', corpus: 'demo' })
  })
})
