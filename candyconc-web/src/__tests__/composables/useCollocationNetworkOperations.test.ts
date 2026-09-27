import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  COLLOCATION_NETWORK_OPERATIONS,
  COLLOCATION_NETWORK_ROUTES,
  useCollocationNetworkOperations,
} from '@/composables/useCollocationNetworkOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getCollocationNetwork: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getCollocationNetwork: (...args: unknown[]) => apiMocks.getCollocationNetwork(...args),
  }
})

function route() {
  return {
    path: COLLOCATION_NETWORK_ROUTES.graph,
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const graphRoute = route()
  return {
    id: 'analysis.collocation_network',
    title: 'Collocation network',
    area: 'analysis',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [graphRoute],
    backend_route_descriptors: [graphRoute],
    operations: [{
      id: COLLOCATION_NETWORK_OPERATIONS.graph,
      capability_id: 'analysis.collocation_network',
      label: 'Kollokationsnetzwerk',
      description: '',
      route: graphRoute,
      effects: ['read'],
      handler_key: 'collocation_network',
      surface_slot: 'analysis.collocation_network.graph',
      priority: 10,
    }],
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

describe('useCollocationNetworkOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks network loading when the semantic operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({ operations: [] }))
    productCapabilities.status = 'ready'

    const { loadCollocationNetwork } = useCollocationNetworkOperations()

    await expect(loadCollocationNetwork({ term: 'Sprache' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.getCollocationNetwork).not.toHaveBeenCalled()
  })

  it('routes network loading through ProductOperation availability', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'
    apiMocks.getCollocationNetwork.mockResolvedValue({
      term: 'Sprache',
      measure: 'logdice',
      nodes: [{ id: 'Sprache', depth: 0 }],
      edges: [],
      diagnostics: {},
    })

    const { loadCollocationNetwork, canLoadCollocationNetwork } = useCollocationNetworkOperations()

    await expect(loadCollocationNetwork({
      term: 'Sprache',
      window: 5,
      corpus: 'demo',
    })).resolves.toMatchObject({ term: 'Sprache', measure: 'logdice' })
    expect(canLoadCollocationNetwork.value).toBe(true)
    expect(apiMocks.getCollocationNetwork).toHaveBeenCalledWith({
      term: 'Sprache',
      window: 5,
      corpus: 'demo',
    })
  })
})
