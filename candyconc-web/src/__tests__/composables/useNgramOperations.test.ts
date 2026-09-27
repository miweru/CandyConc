import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { NGRAM_OPERATIONS, useNgramOperations } from '@/composables/useNgramOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  createNgramsDiffJob: vi.fn(),
  createNgramsJob: vi.fn(),
  getNgrams: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    createNgramsDiffJob: (...args: unknown[]) => apiMocks.createNgramsDiffJob(...args),
    createNgramsJob: (...args: unknown[]) => apiMocks.createNgramsJob(...args),
    getNgrams: (...args: unknown[]) => apiMocks.getNgrams(...args),
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
  const isDiffJob = id.endsWith('.diff_job')
  const isFrequencyJob = id.endsWith('.frequency_job')
  return {
    id,
    capability_id: 'analysis.ngrams',
    label,
    description: '',
    route: routeDescriptor,
    effects: isFrequencyJob || isDiffJob ? ['read' as const, 'long_running' as const] : ['read' as const],
    handler_key: isDiffJob
      ? 'ngram_contrast_job'
      : isFrequencyJob
        ? 'ngram_frequency_job'
        : 'ngram_frequency',
    surface_slot: isDiffJob
      ? 'analysis.ngrams.diff'
      : isFrequencyJob
        ? 'analysis.ngrams.job'
        : 'analysis.ngrams.frequency',
    priority: isDiffJob ? 30 : isFrequencyJob ? 20 : 10,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  return {
    id: 'analysis.ngrams',
    title: 'N-gram analysis',
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
  const frequencyRoute = route('/api/v1/analysis/ngrams')
  return {
    ...capability({
      id: 'analysis.sync_ngrams_api',
      title: 'Synchronous N-gram API',
      visibility: 'expert_api',
      backend_routes: [frequencyRoute.path],
      backend_route_descriptors: [frequencyRoute],
    }),
    operations: [{
      ...operation(NGRAM_OPERATIONS.frequency, 'Synchrone N-Gramm-Frequenz', frequencyRoute),
      capability_id: 'analysis.sync_ngrams_api',
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

describe('useNgramOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks N-gram jobs when the operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const { createNgramFrequencyJob } = useNgramOperations()

    await expect(createNgramFrequencyJob({ n: 2 })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.createNgramsJob).not.toHaveBeenCalled()
  })

  it('routes frequency and diff jobs through operation availability', async () => {
    const freqRoute = route('/api/v1/analysis/ngrams/job')
    const diffRoute = route('/api/v1/analysis/ngrams_diff/job')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [freqRoute.path, diffRoute.path],
      backend_route_descriptors: [freqRoute, diffRoute],
      operations: [
        operation(NGRAM_OPERATIONS.frequencyJob, 'N-Gramm-Frequenzjob', freqRoute),
        operation(NGRAM_OPERATIONS.diffJob, 'N-Gramm-Kontrastjob', diffRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.createNgramsJob.mockResolvedValue({
      job_id: 'job-ngram-1',
      status_url: '/api/v1/analysis/jobs/job-ngram-1',
      rows_url: '/api/v1/analysis/jobs/job-ngram-1/rows',
    })
    apiMocks.createNgramsDiffJob.mockResolvedValue({
      job_id: 'job-ngram-diff-1',
      status_url: '/api/v1/analysis/jobs/job-ngram-diff-1',
      rows_url: '/api/v1/analysis/jobs/job-ngram-diff-1/rows',
    })

    const { createNgramFrequencyJob, createNgramDiffJob } = useNgramOperations()

    await expect(createNgramFrequencyJob({ n: 2, limit: 500 })).resolves.toMatchObject({
      job_id: 'job-ngram-1',
    })
    await expect(createNgramDiffJob({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      n: 2,
      limit: 500,
    })).resolves.toMatchObject({
      job_id: 'job-ngram-diff-1',
    })
    expect(apiMocks.getNgrams).not.toHaveBeenCalled()
    expect(apiMocks.createNgramsJob).toHaveBeenCalledWith({ n: 2, limit: 500 })
    expect(apiMocks.createNgramsDiffJob).toHaveBeenCalledWith({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      n: 2,
      limit: 500,
    })
  })

  it('does not expose synchronous frequency as first-class UI', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability(), expertSyncCapability())
    productCapabilities.status = 'ready'

    const { loadNgramFrequency } = useNgramOperations()

    await expect(loadNgramFrequency({ n: 2, limit: 10 })).rejects.toThrow(
      'Synchrone N-Gramm-Frequenz ist im Fähigkeitskatalog nicht als Oberfläche freigegeben.',
    )
    expect(apiMocks.getNgrams).not.toHaveBeenCalled()
  })
})
