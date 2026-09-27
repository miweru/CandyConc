import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'

import { COLLOCATION_OPERATIONS, useCollocationOperations } from '@/composables/useCollocationOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  createCollocatesJob: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    createCollocatesJob: (...args: unknown[]) => apiMocks.createCollocatesJob(...args),
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

// Simulate a stale server contract that still advertises confirmation for a job.
function confirmedJobCapability(): ProductCapability {
  const jobRoute = route('/api/v1/analysis/collocates/job', 'POST')
  return {
    id: 'analysis.collocations',
    title: 'Collocation analysis',
    area: 'analysis',
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [jobRoute.path],
    backend_route_descriptors: [jobRoute],
    operations: [{
      id: COLLOCATION_OPERATIONS.job,
      capability_id: 'analysis.collocations',
      label: 'Kollokationsjob',
      description: '',
      route: jobRoute,
      effects: ['read', 'long_running'],
      handler_key: 'collocates_job',
      surface_slot: 'analysis.collocations.job',
      priority: 20,
      ui_execution_policy: 'confirmed_contextual_ui',
    }],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  } as never
}

function contract(...items: ProductCapability[]): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: items,
  } as ProductCapabilityContract
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

describe('collocation job confirmation (ANALYSIS-CORE-02 / DESIGN-UX-GLOBAL-5)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(confirmedJobCapability())
    productCapabilities.status = 'ready'
    apiMocks.createCollocatesJob.mockResolvedValue({
      job_id: 'job-1',
      status_url: '/s',
      rows_url: '/r',
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('satisfies a confirmed operation via in-app contextualConfirmation, never touching window.confirm', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { createCollocationJob } = useCollocationOperations()

    await expect(createCollocationJob({ term: 'Hase' }, {
      contextualConfirmation: {
        surfaceId: 'analysis.collocations',
        interaction: 'collocations.tab.job',
        source: 'native_surface',
      },
    })).resolves.toMatchObject({ job_id: 'job-1' })

    // The in-app confirmation bypasses the native dialog entirely.
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(apiMocks.createCollocatesJob).toHaveBeenCalledTimes(1)
  })

  it('ignores a stale confirmation policy instead of opening a native dialog for a research job', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)
    const { createCollocationJob } = useCollocationOperations()

    await expect(createCollocationJob({ term: 'Hase' })).resolves.toMatchObject({ job_id: 'job-1' })
    expect(confirmSpy).not.toHaveBeenCalled()
    expect(apiMocks.createCollocatesJob).toHaveBeenCalledTimes(1)
  })
})
