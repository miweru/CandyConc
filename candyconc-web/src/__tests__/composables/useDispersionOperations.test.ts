import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { DISPERSION_OPERATIONS, useDispersionOperations } from '@/composables/useDispersionOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getDispersion: vi.fn(),
  getDispersionOffsets: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getDispersion: (...args: unknown[]) => apiMocks.getDispersion(...args),
    getDispersionOffsets: (...args: unknown[]) => apiMocks.getDispersionOffsets(...args),
  }
})

function route(path: string) {
  return {
    path,
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(id: string, label: string, routeDescriptor: ReturnType<typeof route>) {
  return {
    id,
    capability_id: 'analysis.dispersion',
    label,
    description: '',
    route: routeDescriptor,
    effects: ['read' as const],
    handler_key: id.endsWith('.offsets') ? 'dispersion_offsets' : 'dispersion_stats',
    surface_slot: id.endsWith('.offsets') ? 'analysis.dispersion.offsets' : 'analysis.dispersion.stats',
    priority: id.endsWith('.offsets') ? 20 : 10,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  return {
    id: 'analysis.dispersion',
    title: 'Dispersion analysis',
    area: 'analysis',
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: [],
    operations: [],
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

describe('useDispersionOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks dispersion loading when the stats operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const { loadDispersion } = useDispersionOperations()

    await expect(loadDispersion({ term: 'Sprache' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.getDispersion).not.toHaveBeenCalled()
  })

  it('routes dispersion loading through operation availability', async () => {
    const statsRoute = route('/api/v1/analysis/dispersion')
    const offsetsRoute = route('/api/v1/analysis/dispersion_offsets')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [statsRoute.path, offsetsRoute.path],
      backend_route_descriptors: [statsRoute, offsetsRoute],
      operations: [
        operation(DISPERSION_OPERATIONS.stats, 'Dispersionsanalyse', statsRoute),
        operation(DISPERSION_OPERATIONS.offsets, 'Dispersions-Offsets', offsetsRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.getDispersion.mockResolvedValue({
      term: 'Sprache',
      partitions: [1, 0, 2],
      dp: 0.42,
    })

    const { loadDispersion, loadDispersionOffsets } = useDispersionOperations()

    await expect(loadDispersion({
      term: 'Sprache',
      partitions: 3,
      corpus: 'demo',
    })).resolves.toMatchObject({ term: 'Sprache', dp: 0.42 })
    expect(apiMocks.getDispersion).toHaveBeenCalledWith({
      term: 'Sprache',
      partitions: 3,
      corpus: 'demo',
    }, {})
    apiMocks.getDispersionOffsets.mockResolvedValue({
      offsets: [1, 9, 20],
      basis: 'token_offsets',
      token_count: 100,
    })

    await expect(loadDispersionOffsets({
      term: 'Sprache',
      partitions: 3,
      corpus: 'demo',
    })).resolves.toMatchObject({ offsets: [1, 9, 20] })
    expect(apiMocks.getDispersionOffsets).toHaveBeenCalledWith({
      term: 'Sprache',
      partitions: 3,
      corpus: 'demo',
    }, {})
  })

  it('does not manufacture document-based DP from a page of offsets', async () => {
    const statsRoute = route('/api/v1/analysis/dispersion')
    const offsetsRoute = route('/api/v1/analysis/dispersion_offsets')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [statsRoute.path, offsetsRoute.path],
      backend_route_descriptors: [statsRoute, offsetsRoute],
      operations: [
        operation(DISPERSION_OPERATIONS.stats, 'Dispersionsanalyse', statsRoute),
        operation(DISPERSION_OPERATIONS.offsets, 'Dispersions-Offsets', offsetsRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.getDispersion.mockRejectedValue({
      response: new Response(JSON.stringify({ detail: 'missing' }), { status: 404 }),
    })
    const { loadDispersion } = useDispersionOperations()

    await expect(loadDispersion({
      term: 'politik',
      partitions: 5,
      corpus: 'demo',
      tokenCount: 999,
    })).rejects.toMatchObject({ response: expect.any(Response) })
    expect(apiMocks.getDispersionOffsets).not.toHaveBeenCalled()
  })

  it('does not inspect the offsets operation when the authoritative stats route fails', async () => {
    const statsRoute = route('/api/v1/analysis/dispersion')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [statsRoute.path],
      backend_route_descriptors: [statsRoute],
      operations: [
        operation(DISPERSION_OPERATIONS.stats, 'Dispersionsanalyse', statsRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.getDispersion.mockRejectedValue({
      response: new Response(JSON.stringify({ detail: 'missing' }), { status: 404 }),
    })

    const { loadDispersion } = useDispersionOperations()

    await expect(loadDispersion({ term: 'politik' })).rejects.toMatchObject({
      response: expect.any(Response),
    })
    expect(apiMocks.getDispersionOffsets).not.toHaveBeenCalled()
  })
})
