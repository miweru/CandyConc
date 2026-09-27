import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CollocationNetworkTab from '@/components/analysis/CollocationNetworkTab.vue'
import { useDocsetStore, useQueryStore } from '@/stores'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getCollocationNetwork: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getCollocationNetwork: (...args: unknown[]) => apiMocks.getCollocationNetwork(...args),
  }
})

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  EmptyState: {
    props: ['title', 'description'],
    template: '<div class="empty-state">{{ title }} {{ description }}</div>',
  },
  Skeleton: { template: '<div class="skeleton" />' },
  CollocationNetworkGraph: { template: '<div class="cn-graph-stub" />' },
  MethodPanel: { template: '<div />' },
  SaveAnalysisButton: { template: '<button />' },
}

function route() {
  return {
    path: '/api/v1/analysis/collocation_network',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user' as const,
    required_role: 'user',
    transport: 'http' as const,
    route_class: 'product_surface' as const,
  }
}

function capability(overrides: Partial<ProductCapability> = {}): ProductCapability {
  const graphRoute = route()
  return {
    id: 'analysis.collocation_network',
    title: 'Collocation network',
    area: 'analysis',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [graphRoute],
    backend_route_descriptors: [graphRoute],
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

describe('CollocationNetworkTab ProductOperation gate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedUserSession()
  })

  it('does not rebuild a dirty docset or call the backend when the graph operation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract(capability())
    productCapabilities.status = 'ready'

    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-1'
    docsetStore.stats = { docCount: 2, hitDocCount: 2, refDocCount: 0, tokenCount: 100 }
    docsetStore.isDirty = true
    const buildDocset = vi.spyOn(docsetStore, 'buildDocset').mockResolvedValue(true)

    useQueryStore().setTerm('alpha')
    const wrapper = mount(CollocationNetworkTab, { global: { stubs } })
    await flushPromises()

    expect(buildDocset).not.toHaveBeenCalled()
    expect(apiMocks.getCollocationNetwork).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain(
      'Benötigte Serverfunktion ist im geladenen Fähigkeitskatalog nicht als Serverfunktion verfügbar.',
    )
  })
})
