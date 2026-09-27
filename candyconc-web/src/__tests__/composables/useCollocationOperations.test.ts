import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { COLLOCATION_OPERATIONS, useCollocationOperations } from '@/composables/useCollocationOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  createCollocatesJob: vi.fn(),
  getCollocateKwic: vi.fn(),
  getCollocations: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    createCollocatesJob: (...args: unknown[]) => apiMocks.createCollocatesJob(...args),
    getCollocateKwic: (...args: unknown[]) => apiMocks.getCollocateKwic(...args),
    getCollocations: (...args: unknown[]) => apiMocks.getCollocations(...args),
  }
})

function route(path: string, method: string) {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
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
    capability_id: 'analysis.collocations',
    label,
    description: '',
    route: routeDescriptor,
    effects: routeDescriptor.methods[0] === 'GET' ? ['read' as const] : ['read' as const, 'long_running' as const],
    handler_key: id.endsWith('.job')
      ? 'collocates_job'
      : id.endsWith('.kwic')
        ? 'collocate_kwic'
        : 'collocate_stats',
    surface_slot: id.endsWith('.job')
      ? 'analysis.collocations.job'
      : id.endsWith('.kwic')
        ? 'analysis.collocations.evidence'
        : 'analysis.collocations.sync',
    priority: id.endsWith('.job') ? 20 : id.endsWith('.kwic') ? 30 : 10,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  return {
    id: 'analysis.collocations',
    title: 'Collocation analysis',
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

function expertSyncCapability(): ProductCapability {
  const statsRoute = route('/api/v1/analysis/collocates', 'GET')
  return {
    ...capability({
      id: 'analysis.sync_collocations_api',
      title: 'Synchronous collocation API',
      visibility: 'expert_api',
      backend_routes: [statsRoute.path],
      backend_route_descriptors: [statsRoute],
    }),
    operations: [{
      ...operation(COLLOCATION_OPERATIONS.stats, 'Synchrone Kollokationsstatistik', statsRoute),
      capability_id: 'analysis.sync_collocations_api',
    }],
  }
}

function contract(...items: ProductCapability[]): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: items,
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

describe('useCollocationOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks collocation jobs when the operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const { createCollocationJob } = useCollocationOperations()

    await expect(createCollocationJob({ term: 'Hase' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.createCollocatesJob).not.toHaveBeenCalled()
  })

  it('routes job and Co-KWIC through first-class operation availability', async () => {
    const jobRoute = route('/api/v1/analysis/collocates/job', 'POST')
    const kwicRoute = route('/api/v1/analysis/collocates/kwic', 'GET')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [jobRoute.path, kwicRoute.path],
      backend_route_descriptors: [jobRoute, kwicRoute],
      operations: [
        operation(COLLOCATION_OPERATIONS.job, 'Kollokationsjob', jobRoute),
        operation(COLLOCATION_OPERATIONS.kwic, 'Co-KWIC', kwicRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.createCollocatesJob.mockResolvedValue({
      job_id: 'job-colloc-1',
      status_url: '/api/v1/analysis/jobs/job-colloc-1',
      rows_url: '/api/v1/analysis/jobs/job-colloc-1/rows',
    })
    apiMocks.getCollocateKwic.mockResolvedValue({ hits: [], total: 0 })

    const {
      createCollocationJob,
      loadCollocateKwic,
    } = useCollocationOperations()

    await expect(createCollocationJob({ term: 'Hase' })).resolves.toMatchObject({
      job_id: 'job-colloc-1',
    })
    await expect(loadCollocateKwic({ term: 'Hase', collocate: 'läuft' })).resolves.toMatchObject({
      total: 0,
    })
    expect(apiMocks.getCollocations).not.toHaveBeenCalled()
    expect(apiMocks.createCollocatesJob).toHaveBeenCalledWith({ term: 'Hase' })
    expect(apiMocks.getCollocateKwic).toHaveBeenCalledWith({ term: 'Hase', collocate: 'läuft' })
  })

  it('does not expose synchronous collocation stats as first-class UI', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability(), expertSyncCapability())
    productCapabilities.status = 'ready'

    const { loadCollocations } = useCollocationOperations()

    await expect(loadCollocations({ term: 'Hase' })).rejects.toThrow(
      'Synchrone Kollokationsstatistik ist im Fähigkeitskatalog nicht als Oberfläche freigegeben.',
    )
    expect(apiMocks.getCollocations).not.toHaveBeenCalled()
  })
})
