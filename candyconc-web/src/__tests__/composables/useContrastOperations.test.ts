import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { CONTRAST_OPERATIONS, useContrastOperations } from '@/composables/useContrastOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  createCollocatesDiffJob: vi.fn(),
  createContrastJob: vi.fn(),
  getLexicalDiversity: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    createCollocatesDiffJob: (...args: unknown[]) => apiMocks.createCollocatesDiffJob(...args),
    createContrastJob: (...args: unknown[]) => apiMocks.createContrastJob(...args),
    getLexicalDiversity: (...args: unknown[]) => apiMocks.getLexicalDiversity(...args),
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
    capability_id: 'analysis.contrast',
    label,
    description: '',
    route: routeDescriptor,
    effects: routeDescriptor.methods[0] === 'GET'
      ? ['read' as const]
      : ['read' as const, 'long_running' as const],
    handler_key: id.endsWith('.lexical_diversity')
      ? 'lexical_diversity'
      : id.endsWith('.collocations_diff_job')
        ? 'collocates_diff_job'
        : 'contrast_job',
    surface_slot: id,
    priority: 10,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  return {
    id: 'analysis.contrast',
    title: 'Pairing-free and paired contrast analyses',
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

describe('useContrastOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('blocks free contrast jobs when the semantic operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const { createFreeContrastJob } = useContrastOperations()

    await expect(createFreeContrastJob({
      term: 'Sprache',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
    })).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(apiMocks.createContrastJob).not.toHaveBeenCalled()
  })

  it('routes contrast jobs and lexical diversity through operation availability', async () => {
    const freeRoute = route('/api/v1/analysis/contrast', 'POST')
    const collocRoute = route('/api/v1/analysis/collocates_diff/job', 'POST')
    const diversityRoute = route('/api/v1/analysis/lexical-diversity', 'GET')
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({
      backend_routes: [freeRoute.path, collocRoute.path, diversityRoute.path],
      backend_route_descriptors: [freeRoute, collocRoute, diversityRoute],
      operations: [
        operation(CONTRAST_OPERATIONS.freeJob, 'Freier Kontrastjob', freeRoute),
        operation(CONTRAST_OPERATIONS.collocationsDiffJob, 'Kollokations-Kontrastjob', collocRoute),
        operation(CONTRAST_OPERATIONS.lexicalDiversity, 'Lexikalische Diversität', diversityRoute),
      ],
    }))
    productCapabilities.status = 'ready'
    apiMocks.createContrastJob.mockResolvedValue({ job_id: 'contrast-1', status_url: '/jobs/contrast-1' })
    apiMocks.createCollocatesDiffJob.mockResolvedValue({ job_id: 'colloc-1', status_url: '/jobs/colloc-1' })
    apiMocks.getLexicalDiversity.mockResolvedValue({ sttr: 0.42 })

    const {
      createFreeContrastJob,
      createCollocationContrastJob,
      loadLexicalDiversity,
    } = useContrastOperations()

    await expect(createFreeContrastJob({
      term: 'Sprache',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      corpus: 'demo',
    })).resolves.toMatchObject({ job_id: 'contrast-1' })
    await expect(createCollocationContrastJob({
      term: 'Sprache',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      corpus: 'demo',
    })).resolves.toMatchObject({ job_id: 'colloc-1' })
    await expect(loadLexicalDiversity({
      corpus: 'demo',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
    })).resolves.toMatchObject({ sttr: 0.42 })
    expect(apiMocks.createContrastJob).toHaveBeenCalledWith({
      term: 'Sprache',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      corpus: 'demo',
    })
    expect(apiMocks.createCollocatesDiffJob).toHaveBeenCalledWith({
      term: 'Sprache',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      corpus: 'demo',
    })
    expect(apiMocks.getLexicalDiversity).toHaveBeenCalledWith({
      corpus: 'demo',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
    }, {})
  })
})
