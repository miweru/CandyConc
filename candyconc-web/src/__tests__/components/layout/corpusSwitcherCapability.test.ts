import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import CorpusSwitcher from '@/components/layout/CorpusSwitcher.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSessionStore } from '@/stores/session'
import type { ProductCapability, ProductCapabilityContract } from '@/api/client'

const apiMocks = vi.hoisted(() => ({
  getCorpora: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  activateCorpus: vi.fn(),
  getProductCapabilities: vi.fn(),
  getAuthSession: vi.fn(),
  getSystemInfo: vi.fn(),
}))

const uiMocks = vi.hoisted(() => ({
  showToast: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getCorpora: (...args: unknown[]) => apiMocks.getCorpora(...args),
    getCorpusCapabilities: (...args: unknown[]) => apiMocks.getCorpusCapabilities(...args),
    activateCorpus: (...args: unknown[]) => apiMocks.activateCorpus(...args),
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getAuthSession: (...args: unknown[]) => apiMocks.getAuthSession(...args),
    getSystemInfo: (...args: unknown[]) => apiMocks.getSystemInfo(...args),
  }
})

vi.mock('@/components/ui/Dropdown.vue', () => ({
  default: { template: '<div><slot name="trigger" /><slot /></div>' },
}))

vi.mock('@/components/ui/DropdownItem.vue', () => ({
  default: {
    props: ['disabled'],
    emits: ['click'],
    template: '<button class="dropdown-item" :disabled="disabled" @click="$emit(\'click\', $event)"><slot /></button>',
  },
}))

function capability(id: string, routes: ProductCapability['backend_route_descriptors']): ProductCapability {
  const operations = id === 'corpus.catalogue'
    ? [
        { id: 'corpus.catalogue.list', path: '/api/v1/corpora', method: 'GET', label: 'Korpuskatalog' },
        { id: 'corpus.catalogue.activate', path: '/api/v1/corpora/{corpus}/activate', method: 'POST', label: 'Korpusaktivierung' },
      ].flatMap((spec) => {
        const descriptor = routes.find((route) =>
          route.path === spec.path &&
          route.methods.map((method) => method.toUpperCase()).includes(spec.method)
        )
        if (!descriptor) return []
        return [{
          id: spec.id,
          capability_id: id,
          label: spec.label,
          description: '',
          route: { ...descriptor, methods: [spec.method] },
          effects: spec.method === 'GET' ? ['read'] : ['write'],
          handler_key: spec.id,
          surface_slot: spec.id,
          priority: 100,
        }]
      })
    : []
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: routes.map((route) => route.path),
    backend_route_descriptors: routes,
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    notes: '',
  }
}

function contract(): ProductCapabilityContract {
  const systemInfoRoute = {
    path: '/api/v1/system/info',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'admin' as const,
    required_role: 'admin' as const,
    transport: 'http' as const,
    route_class: 'admin_surface' as const,
  }
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      capability('corpus.catalogue', [
        {
          path: '/api/v1/corpora',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
        {
          path: '/api/v1/corpora/{corpus}/activate',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'admin',
          required_role: 'admin',
          transport: 'http',
          route_class: 'admin_surface',
        },
      ]),
      {
        id: 'admin.system_operations',
        title: 'System operations',
        area: 'admin',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/system/info'],
        backend_route_descriptors: [systemInfoRoute],
        operations: [{
          id: 'admin.system_operations.info',
          capability_id: 'admin.system_operations',
          label: 'Systeminformationen laden',
          description: '',
          route: systemInfoRoute,
          effects: ['read'],
          handler_key: 'info',
          surface_slot: 'settings.system.info',
          priority: 100,
        }],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
    ],
  }
}

function setSession(role = 'user') {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: role,
    role,
    effective_role: role,
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

function summary(name: string, active = false, overrides: Record<string, unknown> = {}) {
  return {
    name,
    path: `/corpora/${name}`,
    status: 'ready' as const,
    source: name === 'default' ? 'default' : 'registry',
    active,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'rows',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    ...overrides,
  }
}

describe('CorpusSwitcher capability gates', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    apiMocks.getCorpora.mockResolvedValue({
      corpora: [summary('A', true), summary('B', false)],
      count: 2,
    })
    apiMocks.getCorpusCapabilities.mockResolvedValue(summary('B'))
    apiMocks.activateCorpus.mockResolvedValue(summary('B', true))
    apiMocks.getProductCapabilities.mockResolvedValue(contract())
    apiMocks.getAuthSession.mockResolvedValue(null)
    apiMocks.getSystemInfo.mockResolvedValue({
      corpusName: 'B',
      tokenCount: 1000,
      documentCount: 10,
    })
  })

  it('loads the readable corpus catalogue but blocks activation without the route role', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    setSession('user')

    const wrapper = mount(CorpusSwitcher, {
      global: {
        mocks: {
          $toast: uiMocks.showToast,
        },
      },
    })
    await flushPromises()

    expect(apiMocks.getCorpora).toHaveBeenCalledOnce()
    const corpusButtons = wrapper.findAll('.dropdown-item')
    expect(corpusButtons.some((button) => button.text().includes('B') && button.attributes('disabled') !== undefined)).toBe(true)

    await corpusButtons.find((button) => button.text().includes('B'))?.trigger('click')

    expect(apiMocks.activateCorpus).not.toHaveBeenCalled()
  })

  it('does not fetch corpora before the catalogue route is visible', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    setSession('user')
    productCapabilities.contract = {
      ...contract(),
      capabilities: [capability('corpus.catalogue', [])],
    }

    const wrapper = mount(CorpusSwitcher)
    await flushPromises()

    expect(apiMocks.getCorpora).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Korpuskatalog')
  })

  it('loads the corpus catalogue once the catalogue route becomes visible after sign-in', async () => {
    // Release mode before sign-in: no contract, the catalogue is not readable.
    apiMocks.getProductCapabilities.mockRejectedValueOnce(new Error('401 Unauthorized'))
    const wrapper = mount(CorpusSwitcher)
    await flushPromises()
    expect(apiMocks.getCorpora).not.toHaveBeenCalled()

    // Sign-in: the contract arrives, the switcher loads the catalogue itself.
    const productCapabilities = useProductCapabilitiesStore()
    setSession('user')
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    await flushPromises()

    expect(apiMocks.getCorpora).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('A')
  })

  it('disables non-ready corpus entries before activation reaches the backend', async () => {
    apiMocks.getCorpora.mockResolvedValueOnce({
      corpora: [
        summary('A', true),
        summary('broken', false, { status: 'incomplete', status_reason: 'Manifest fehlt' }),
      ],
      count: 2,
    })
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    setSession('admin')

    const wrapper = mount(CorpusSwitcher)
    await flushPromises()

    const brokenButton = wrapper.findAll('.dropdown-item').find((button) => button.text().includes('broken'))
    expect(brokenButton?.attributes('disabled')).toBeDefined()
    expect(brokenButton?.attributes('title')).toContain('Nur bereite Korpora können aktiviert werden')
    expect(brokenButton?.text()).toContain('incomplete')

    await brokenButton?.trigger('click')
    expect(apiMocks.activateCorpus).not.toHaveBeenCalled()
  })

  it('activates a ready corpus through a direct switcher click when the route is allowed', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    setSession('admin')

    const wrapper = mount(CorpusSwitcher)
    await flushPromises()

    const targetButton = wrapper.findAll('.dropdown-item').find((button) => button.text().includes('B'))
    expect(targetButton?.attributes('disabled')).toBeUndefined()

    await targetButton?.trigger('click')
    await flushPromises()

    expect(apiMocks.activateCorpus).toHaveBeenCalledWith('B')
    expect(useQueryStore().filters.corpus).toBe('B')
  })

  it('blocks corpus activation while a KWIC query is still running', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    setSession('admin')
    const queryStore = useQueryStore()
    queryStore.setFilters({ corpus: 'A' })
    queryStore.startStreaming()

    const wrapper = mount(CorpusSwitcher)
    await flushPromises()

    expect(wrapper.text()).toContain('Korpuswechsel ist gesperrt')
    const targetButton = wrapper.findAll('.dropdown-item').find((button) => button.text().includes('B'))
    expect(targetButton?.attributes('disabled')).toBeDefined()
    expect(targetButton?.attributes('title')).toContain('Korpuswechsel ist gesperrt')

    await targetButton?.trigger('click')
    expect(apiMocks.activateCorpus).not.toHaveBeenCalled()
  })

  it('shows the language of each corpus and unknown where the index records none', async () => {
    apiMocks.getCorpora.mockResolvedValueOnce({
      corpora: [summary('sotu', true, { language: 'en' }), summary('old', false)],
      count: 2,
    })
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = contract()
    productCapabilities.status = 'ready'
    setSession('admin')

    const wrapper = mount(CorpusSwitcher)
    await flushPromises()

    const languages = wrapper.findAll('[data-testid="corpus-switcher-language"]').map((item) => item.text())
    expect(languages).toEqual(['Sprache: Englisch (en)', 'Sprache: unbekannt'])
  })
})
