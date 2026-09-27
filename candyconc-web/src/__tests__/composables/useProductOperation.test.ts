import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useProductOperation } from '@/composables/useProductOperation'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn().mockRejectedValue(new Error('offline')),
  }
})

function route(path = '/api/v1/analysis/demo', method = 'GET') {
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

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const demoRoute = route()
  return {
    id: 'analysis.demo',
    title: 'Demo analysis',
    area: 'analysis',
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: [demoRoute],
    backend_route_descriptors: [demoRoute],
    operations: [{
      id: 'analysis.demo.run',
      capability_id: 'analysis.demo',
      label: 'Demoanalyse',
      description: '',
      route: demoRoute,
      effects: ['read'],
      handler_key: 'demo',
      surface_slot: 'analysis.demo.run',
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

describe('useProductOperation', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedUserSession()
  })

  it('runs the executor through semantic ProductOperation availability', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'
    const executor = vi.fn().mockResolvedValue({ ok: true })

    const operation = useProductOperation<[string], { ok: boolean }>(
      'analysis.demo.run',
      executor,
    )

    await expect(operation.run('alpha')).resolves.toEqual({ ok: true })
    expect(executor).toHaveBeenCalledWith('alpha')
    expect(operation.canUse.value).toBe(true)
  })

  it('keeps the route fallback usable before a non-release contract is loaded', async () => {
    const session = useSessionStore()
    if (session.session) session.session.release_mode = false
    const executor = vi.fn().mockResolvedValue('fallback-ok')

    const operation = useProductOperation<[string], string>(
      'analysis.demo.run',
      executor,
      {
        fallbackCapabilityId: 'analysis.demo',
        fallbackLabel: 'Demoanalyse',
        fallbackOperation: { path: '/api/v1/analysis/demo', method: 'GET' },
      },
    )

    await expect(operation.run('alpha')).resolves.toBe('fallback-ok')
    expect(executor).toHaveBeenCalledWith('alpha')
  })

  it('blocks non-release offline execution without an explicit route fallback', async () => {
    const session = useSessionStore()
    if (session.session) session.session.release_mode = false
    const executor = vi.fn()

    const operation = useProductOperation<[string], unknown>(
      'analysis.demo.run',
      executor,
      {
        fallbackCapabilityId: 'analysis.demo',
        fallbackLabel: 'Demoanalyse',
      },
    )

    await expect(operation.run('alpha')).rejects.toThrow(
      'Benötigte Serverfunktion ist ohne geladenen Fähigkeitskatalog nicht nutzbar.',
    )
    expect(operation.canUse.value).toBe(false)
    expect(executor).not.toHaveBeenCalled()
  })

  it('blocks the executor when the operation is absent from the contract', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability({ operations: [] }))
    productCapabilities.status = 'ready'
    const executor = vi.fn()

    const operation = useProductOperation<[string], unknown>(
      'analysis.demo.run',
      executor,
    )

    await expect(operation.run('alpha')).rejects.toThrow(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
    expect(executor).not.toHaveBeenCalled()
  })

  it('blocks route-only gates even when the backend route is available', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const gate = useProductRouteOperationGate({
      capabilityId: 'analysis.demo',
      label: 'Demoanalyse',
      operation: { path: '/api/v1/analysis/demo', method: 'GET' },
    })

    expect(gate.canUse.value).toBe(false)
    await expect(gate.assertAvailable()).rejects.toThrow('ausführbare Serverfunktion verfügbar')
  })
})
