import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { FREQUENCY_OPERATIONS, useFrequencyOperations } from '@/composables/useFrequencyOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  createFrequencyDiffJob: vi.fn(),
  createFrequencyListJob: vi.fn(),
  getFrequencyResult: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    createFrequencyDiffJob: (...args: unknown[]) => apiMocks.createFrequencyDiffJob(...args),
    createFrequencyListJob: (...args: unknown[]) => apiMocks.createFrequencyListJob(...args),
    getFrequencyResult: (...args: unknown[]) => apiMocks.getFrequencyResult(...args),
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
    capability_id: 'analysis.frequency',
    label,
    description: '',
    route: routeDescriptor,
    effects: routeDescriptor.methods[0] === 'GET' ? ['read' as const] : ['read' as const, 'long_running' as const],
    handler_key: id === FREQUENCY_OPERATIONS.diffJob
      ? 'frequency_diff_job'
      : id.endsWith('.job') ? 'frequency_list_job' : 'frequency_list',
    surface_slot: id === FREQUENCY_OPERATIONS.diffJob
      ? 'analysis.contrast.frequency_diff'
      : id.endsWith('.job') ? 'analysis.frequency.job' : 'analysis.frequency.sync',
    priority: id === FREQUENCY_OPERATIONS.diffJob ? 30 : id.endsWith('.job') ? 20 : 10,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  return {
    id: 'analysis.frequency',
    title: 'Frequency lists',
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

describe('useFrequencyOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks synchronous frequency loading when the operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const { loadFrequencyResult } = useFrequencyOperations()

    await expect(loadFrequencyResult({ groupBy: 'word' })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.getFrequencyResult).not.toHaveBeenCalled()
  })

  it('routes synchronous and job frequency calls through operation availability', async () => {
    const listRoute = route('/api/v1/analysis/frequency_list', 'GET')
    const jobRoute = route('/api/v1/analysis/frequency_list/job', 'POST')
    const diffJobRoute = route('/api/v1/analysis/frequency_diff/job', 'POST')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [listRoute.path, jobRoute.path, diffJobRoute.path],
      backend_route_descriptors: [listRoute, jobRoute, diffJobRoute],
      operations: [
        operation(FREQUENCY_OPERATIONS.list, 'Frequenzliste', listRoute),
        operation(FREQUENCY_OPERATIONS.job, 'Frequenzjob', jobRoute),
        operation(FREQUENCY_OPERATIONS.diffJob, 'Frequenz-Kontrastjob', diffJobRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.getFrequencyResult.mockResolvedValue({ rows: [], groupBy: 'word' })
    apiMocks.createFrequencyListJob.mockResolvedValue({
      job_id: 'job-1',
      status_url: '/api/v1/analysis/jobs/job-1',
      rows_url: '/api/v1/analysis/jobs/job-1/rows',
    })
    apiMocks.createFrequencyDiffJob.mockResolvedValue({ job_id: 'job-diff-1' })

    const { loadFrequencyResult, createFrequencyJob, createFrequencyDiffJob } = useFrequencyOperations()

    await expect(loadFrequencyResult({ groupBy: 'word', limit: 10 })).resolves.toMatchObject({
      groupBy: 'word',
    })
    await expect(createFrequencyJob({ groupBy: 'word', limit: 10 })).resolves.toMatchObject({
      job_id: 'job-1',
    })
    await expect(createFrequencyDiffJob({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      limit: 30,
    })).resolves.toMatchObject({ job_id: 'job-diff-1' })
    expect(apiMocks.getFrequencyResult).toHaveBeenCalledWith({ groupBy: 'word', limit: 10 }, {})
    expect(apiMocks.createFrequencyListJob).toHaveBeenCalledWith({ groupBy: 'word', limit: 10 })
    expect(apiMocks.createFrequencyDiffJob).toHaveBeenCalledWith({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      limit: 30,
    })
  })

  it('blocks an exact frequency difference when the capability contract omits it', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const { createFrequencyDiffJob } = useFrequencyOperations()

    await expect(createFrequencyDiffJob({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
    })).rejects.toThrow('Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.')
    expect(apiMocks.createFrequencyDiffJob).not.toHaveBeenCalled()
  })
})
