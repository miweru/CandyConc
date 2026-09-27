import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  QUERY_OPERATIONS,
  QUERY_ROUTES,
  useQueryOperations,
} from '@/composables/useQueryOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract, ProductCapabilityOperation } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  executeQuery: vi.fn(),
  executeQueryStreaming: vi.fn(),
  getQueryCount: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    executeQuery: (...args: unknown[]) => apiMocks.executeQuery(...args),
    executeQueryStreaming: (...args: unknown[]) => apiMocks.executeQueryStreaming(...args),
    getQueryCount: (...args: unknown[]) => apiMocks.getQueryCount(...args),
  }
})

function route(path: string, method = 'GET') {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
}

function operation(
  id: string,
  label: string,
  descriptor: ReturnType<typeof route>,
): ProductCapabilityOperation {
  return {
    id,
    capability_id: 'query.kwic',
    label,
    description: '',
    route: descriptor,
    effects: ['read'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 10,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const pageRoute = route(QUERY_ROUTES.page)
  const streamRoute = route(QUERY_ROUTES.stream)
  const countRoute = route(QUERY_ROUTES.count)
  return {
    id: 'query.kwic',
    title: 'KWIC',
    area: 'search',
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [pageRoute, streamRoute, countRoute],
    backend_route_descriptors: [pageRoute, streamRoute, countRoute],
    operations: [
      operation(QUERY_OPERATIONS.page, 'KWIC-Trefferseite', pageRoute),
      operation(QUERY_OPERATIONS.stream, 'KWIC-Stream', streamRoute),
      operation(QUERY_OPERATIONS.count, 'KWIC-Zählung', countRoute),
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

async function* streamEvents() {
  yield { type: 'progress' as const, count: 1 }
  yield { type: 'done' as const, total: 1 }
}

describe('useQueryOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('runs KWIC page and count through concrete ProductOperations', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'
    apiMocks.executeQuery.mockResolvedValue({ hits: [], total: 0, query_time_ms: 1 })
    apiMocks.getQueryCount.mockResolvedValue({ status: 'ready', total: 0, partial: false })

    const { executeKwicPage, loadQueryCount, canExecuteKwicPage, canLoadQueryCount } = useQueryOperations()

    await expect(executeKwicPage({ term: 'Hase', context: 5 })).resolves.toMatchObject({ total: 0 })
    await expect(loadQueryCount({ term: 'Hase', start: true })).resolves.toMatchObject({ total: 0 })
    expect(canExecuteKwicPage.value).toBe(true)
    expect(canLoadQueryCount.value).toBe(true)
    expect(apiMocks.executeQuery).toHaveBeenCalledWith({ term: 'Hase', context: 5 })
    expect(apiMocks.getQueryCount).toHaveBeenCalledWith({ term: 'Hase', start: true })
  })

  it('gates the KWIC stream before yielding backend events', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'
    apiMocks.executeQueryStreaming.mockImplementation(() => streamEvents())

    const { streamKwic, canStreamKwic } = useQueryOperations()
    const seen = []
    for await (const event of streamKwic({ term: 'Hase', limit: 10 })) {
      seen.push(event.type)
    }

    expect(seen).toEqual(['progress', 'done'])
    expect(canStreamKwic.value).toBe(true)
    expect(apiMocks.executeQueryStreaming).toHaveBeenCalledWith({ term: 'Hase', limit: 10 }, undefined)
  })

  it('uses explicit contextual confirmation for confirmed KWIC streams', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    const kwicCapability = capability()
    kwicCapability.operations = kwicCapability.operations.map((operation) =>
      operation.id === QUERY_OPERATIONS.stream
        ? { ...operation, ui_execution_policy: 'confirmed_contextual_ui' }
        : operation
    )
    productCapabilities.contract = contract(kwicCapability)
    productCapabilities.status = 'ready'
    apiMocks.executeQueryStreaming.mockImplementation(() => streamEvents())
    vi.mocked(window.confirm).mockReturnValueOnce(false)

    const { streamKwic } = useQueryOperations()
    const seen = []
    for await (const event of streamKwic({ term: 'Hase', limit: 10 }, {
      access: {
        target: 'Korpus default',
        impact: 'Die KWIC-Fachfläche bestätigt den Stream.',
        contextualConfirmation: {
          surfaceId: 'query.kwic',
          interaction: 'query.kwic.initial',
          source: 'native_surface',
        },
      },
    })) {
      seen.push(event.type)
    }

    expect(seen).toEqual(['progress', 'done'])
    expect(window.confirm).not.toHaveBeenCalled()
    expect(apiMocks.executeQueryStreaming).toHaveBeenCalledWith({ term: 'Hase', limit: 10 }, undefined)
  })

  it('blocks page execution when the semantic ProductOperation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({ operations: [] }))
    productCapabilities.status = 'ready'

    const { executeKwicPage } = useQueryOperations()

    await expect(executeKwicPage({ term: 'Hase' })).rejects.toThrow('Serverfunktion')
    expect(apiMocks.executeQuery).not.toHaveBeenCalled()
  })
})
