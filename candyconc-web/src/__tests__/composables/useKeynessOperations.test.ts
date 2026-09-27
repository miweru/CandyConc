import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { KEYNESS_OPERATIONS, useKeynessOperations } from '@/composables/useKeynessOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  createKeynessJob: vi.fn(),
  getKeyness: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    createKeynessJob: (...args: unknown[]) => apiMocks.createKeynessJob(...args),
    getKeyness: (...args: unknown[]) => apiMocks.getKeyness(...args),
  }
})

function route(path: string) {
  return {
    path,
    methods: ['POST'],
    mutates: true,
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
    capability_id: 'analysis.keyness',
    label,
    description: '',
    route: routeDescriptor,
    effects: id.endsWith('.job') ? ['read' as const, 'long_running' as const] : ['read' as const],
    handler_key: id.endsWith('.job') ? 'keyness_job' : 'keyness_stats',
    surface_slot: id.endsWith('.job') ? 'analysis.keyness.job' : 'analysis.keyness.sync',
    priority: id.endsWith('.job') ? 20 : 10,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  return {
    id: 'analysis.keyness',
    title: 'Keyness with inferential statistics',
    area: 'analysis',
    maturity: 'guarded',
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
  const statsRoute = route('/api/v1/analysis/keyness')
  return {
    ...capability({
      id: 'analysis.sync_keyness_api',
      title: 'Synchronous Keyness API',
      visibility: 'expert_api',
      backend_routes: [statsRoute.path],
      backend_route_descriptors: [statsRoute],
    }),
    operations: [{
      ...operation(KEYNESS_OPERATIONS.stats, 'Synchrone Keyness-Statistik', statsRoute),
      capability_id: 'analysis.sync_keyness_api',
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

describe('useKeynessOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks Keyness jobs when the semantic operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const { createKeynessAnalysisJob } = useKeynessOperations()

    await expect(createKeynessAnalysisJob({ targetDocsetId: 'target' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.createKeynessJob).not.toHaveBeenCalled()
  })

  it('routes job Keyness calls through first-class operation availability', async () => {
    const jobRoute = route('/api/v1/analysis/keyness/job')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [jobRoute.path],
      backend_route_descriptors: [jobRoute],
      operations: [
        operation(KEYNESS_OPERATIONS.job, 'Keyness-Job', jobRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.createKeynessJob.mockResolvedValue({
      job_id: 'job-keyness-1',
      status_url: '/api/v1/analysis/jobs/job-keyness-1',
      rows_url: '/api/v1/analysis/jobs/job-keyness-1/rows',
    })

    const { createKeynessAnalysisJob } = useKeynessOperations()

    await expect(createKeynessAnalysisJob({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      corpus: 'default',
      minFreq: 5,
    })).resolves.toMatchObject({ job_id: 'job-keyness-1' })
    expect(apiMocks.getKeyness).not.toHaveBeenCalled()
    expect(apiMocks.createKeynessJob).toHaveBeenCalledWith({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      corpus: 'default',
      minFreq: 5,
    })
  })

  it('does not expose synchronous Keyness stats as first-class UI', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability(), expertSyncCapability())
    productCapabilities.status = 'ready'

    const { loadKeynessStats } = useKeynessOperations()

    await expect(loadKeynessStats({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      corpus: 'default',
      limit: 50,
    })).rejects.toThrow(
      'Synchrone Keyness-Statistik ist im Fähigkeitskatalog nicht als Oberfläche freigegeben.',
    )
    expect(apiMocks.getKeyness).not.toHaveBeenCalled()
  })
})
