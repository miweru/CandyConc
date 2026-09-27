import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useCqlfOperations } from '@/composables/useCqlfOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  analyseQuery: vi.fn(),
  getSuggestions: vi.fn(),
  getLexiconSuggestions: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    analyseQuery: (...args: unknown[]) => apiMocks.analyseQuery(...args),
    getSuggestions: (...args: unknown[]) => apiMocks.getSuggestions(...args),
    getLexiconSuggestions: (...args: unknown[]) => apiMocks.getLexiconSuggestions(...args),
  }
})

function route(path: string, method: string) {
  return {
    path,
    methods: [method],
    mutates: false,
    requires_corpus_features: [],
    access: null,
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function cqlfCapability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const descriptors = overrides.backend_route_descriptors ?? []
  const operations = [
    {
      id: 'query.cqlf.analyse',
      path: '/api/v1/query/analyse',
      method: 'POST',
      label: 'CQLF-Diagnostik',
    },
    {
      id: 'query.cqlf.lexicon_suggest',
      path: '/api/v1/query/lexicon/suggest',
      method: 'POST',
      label: 'CQLF-Lexikonvorschläge',
    },
  ].flatMap((spec) => {
    const descriptor = descriptors.find((item) =>
      item.path === spec.path &&
      item.methods.map((method) => method.toUpperCase()).includes(spec.method)
    )
    if (!descriptor) return []
    return [{
      id: spec.id,
      capability_id: 'query.cqlf',
      label: spec.label,
      description: '',
      route: { ...descriptor, methods: [spec.method] },
      effects: spec.method === 'GET' ? ['read'] : ['read'],
      handler_key: spec.id,
      surface_slot: spec.id,
      priority: 100,
    }]
  })
  return {
    id: 'query.cqlf',
    title: 'CQLF',
    area: 'search',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: [],
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

function contract(capability: ProductCapability): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [capability],
  }
}

describe('useCqlfOperations', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('blocks CQLF analysis when the concrete route is not offered', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(cqlfCapability())
    productCapabilities.status = 'ready'

    const { analyseCqlQuery } = useCqlfOperations()

    await expect(analyseCqlQuery('cql:[word="Hase"]')).rejects.toThrow('nicht als Serverfunktion verfügbar')
    expect(apiMocks.analyseQuery).not.toHaveBeenCalled()
  })

  it('blocks lexicon suggestions when only analysis is offered', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(cqlfCapability({
      backend_routes: ['/api/v1/query/analyse'],
      backend_route_descriptors: [route('/api/v1/query/analyse', 'POST')],
    }))
    productCapabilities.status = 'ready'

    const { loadLexiconSuggestions } = useCqlfOperations()

    await expect(loadLexiconSuggestions('word', 'Ha')).rejects.toThrow('nicht als Serverfunktion verfügbar')
    expect(apiMocks.getLexiconSuggestions).not.toHaveBeenCalled()
  })

})
