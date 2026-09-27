import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from '@/App.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useUiStore } from '@/stores/ui'
import type { ActiveTab } from '@/stores/ui'

const counters = vi.hoisted(() => ({ frequencyMounts: 0 }))
const apiMocks = vi.hoisted(() => ({
  getProductCapabilities: vi.fn(),
  getAuthSession: vi.fn(),
  getPrefs: vi.fn(),
  getSystemInfo: vi.fn(),
  getEmbeddingModels: vi.fn(),
  getMcpTools: vi.fn(),
}))
const actionMocks = vi.hoisted(() => ({
  dispatch: vi.fn(async () => ({ success: true })),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => apiMocks.getProductCapabilities(...args),
    getAuthSession: (...args: unknown[]) => apiMocks.getAuthSession(...args),
    getPrefs: (...args: unknown[]) => apiMocks.getPrefs(...args),
    getSystemInfo: (...args: unknown[]) => apiMocks.getSystemInfo(...args),
    getEmbeddingModels: (...args: unknown[]) => apiMocks.getEmbeddingModels(...args),
    getMcpTools: (...args: unknown[]) => apiMocks.getMcpTools(...args),
  }
})

vi.mock('@/actions', () => ({
  actionBus: {
    dispatch: (...args: unknown[]) => actionMocks.dispatch(...args),
  },
}))

vi.mock('@/composables', () => ({
  useUndoRedo: vi.fn(),
}))

vi.mock('@/composables/useUrlState', () => ({
  useUrlState: vi.fn(),
}))

vi.mock('@/components/layout/AppShell.vue', () => ({
  default: {
    template: '<div><slot name="header" /><slot /><slot name="footer" /></div>',
  },
}))
vi.mock('@/components/search/SearchBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/search/ScopeHeader.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/search/SubcorpusDrawer.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/search/DocDetailDrawer.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/search/TabNav.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/search/KwicTable.vue', () => ({ default: { template: '<div>KWIC TABLE</div>' } }))
vi.mock('@/components/search/KwicPlaceholder.vue', () => ({ default: { template: '<div>KWIC PLACEHOLDER</div>' } }))
vi.mock('@/components/layout/HeaderActions.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/layout/CorpusSwitcher.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/layout/StatusBar.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/ui/lazy', () => ({
  ShortcutsOverlay: { template: '<div />' },
  CommandPalette: { template: '<div />' },
}))
vi.mock('@/components/onboarding/SpotlightTour.vue', () => ({ default: { template: '<div />' } }))
vi.mock('@/components/transitions/FadeTransition.vue', () => ({
  default: { template: '<div><slot /></div>' },
}))
vi.mock('@/components/analysis/lazy', () => ({
  ReaderTab: { template: '<div>READER TAB</div>' },
  FrequencyTab: {
    mounted() {
      counters.frequencyMounts += 1
    },
    template: '<div>FREQUENCY TAB</div>',
  },
  CollocationsTab: { template: '<div>COLLOCATIONS TAB</div>' },
  CollocationNetworkTab: { template: '<div>NETWORK TAB</div>' },
  DispersionTab: { template: '<div>DISPERSION TAB</div>' },
  SemanticTab: { template: '<div>SEMANTIC TAB</div>' },
  NgramsTab: { template: '<div>NGRAMS TAB</div>' },
  ContrastTab: { template: '<div>CONTRAST TAB</div>' },
  KeynessTab: { template: '<div>KEYNESS TAB</div>' },
  WordSketchTab: { template: '<div>WORDSKETCH TAB</div>' },
  TrendTab: { template: '<div>TREND TAB</div>' },
}))

function capability(id: string, overrides: Record<string, unknown> = {}) {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: [],
    backend_route_descriptors: [],
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
    ...overrides,
  }
}

function route(path: string, method = 'GET') {
  return {
    path,
    methods: [method],
    mutates: false,
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(
  capabilityId: string,
  id: string,
  path: string,
  label: string,
  priority: number,
) {
  return {
    id,
    capability_id: capabilityId,
    label,
    description: `${label} aus dem Fähigkeitskatalog.`,
    route: route(path),
    effects: ['read'],
    handler_key: id,
    copilot_tools: [],
    surface_slot: id,
    priority,
  }
}

function contractWithHiddenFrequency() {
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
      capability('query.kwic'),
      capability('analysis.frequency', { maturity: 'planned' }),
    ],
  }
}

function contractWithKwicWorkbenchOperations() {
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
      capability('query.kwic', {
        backend_routes: ['/api/v1/query'],
        backend_route_descriptors: [route('/api/v1/query')],
        operations: [
          operation('query.kwic', 'query.kwic.page', '/api/v1/query', 'KWIC-Trefferseite', 10),
        ],
      }),
      capability('query.document_access', {
        backend_routes: ['/api/v1/doc/snippet'],
        backend_route_descriptors: [route('/api/v1/doc/snippet')],
        operations: [
          operation('query.document_access', 'query.document_access.snippet', '/api/v1/doc/snippet', 'Dokument-Snippet', 20),
        ],
      }),
    ],
  }
}

function contractWithCorpusBlockedWordSketch() {
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
      capability('query.kwic'),
      capability('analysis.wordsketch', {
        backend_routes: ['/api/v1/analysis/wordsketch'],
        backend_route_descriptors: [{
          path: '/api/v1/analysis/wordsketch',
          methods: ['POST'],
          mutates: false,
          requires_corpus_features: ['token_attributes.rel'],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        }],
      }),
    ],
  }
}

function seedWordOnlyCorpus() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: 100,
    doc_count: 1,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }]
}

describe('App capability render gate', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    counters.frequencyMounts = 0
    actionMocks.dispatch.mockImplementation(async (action: { type?: string; payload?: { tab?: string } }) => {
      if (action.type === 'nav/switchTab' && action.payload?.tab) {
        useUiStore().setActiveTab(action.payload.tab as ActiveTab)
      }
      return { success: true }
    })
    apiMocks.getPrefs.mockResolvedValue({ prefs: {} })
    apiMocks.getSystemInfo.mockResolvedValue({
      version: 'test',
      corpusName: 'demo',
      tokenCount: 0,
      documentCount: 0,
    })
    apiMocks.getEmbeddingModels.mockResolvedValue([])
    apiMocks.getMcpTools.mockResolvedValue({ tools: [] })
    apiMocks.getAuthSession.mockResolvedValue({
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
    })
  })

  it('does not mount a hidden analysis tab before or after the product contract resolves in release mode', async () => {
    let resolveContract!: (value: ReturnType<typeof contractWithHiddenFrequency>) => void
    apiMocks.getProductCapabilities.mockImplementationOnce(() => new Promise((resolve) => {
      resolveContract = resolve
    }))

    const pinia = createPinia()
    setActivePinia(pinia)
    const uiStore = useUiStore()
    uiStore.setActiveTab('frequency')

    const wrapper = mount(App, { global: { plugins: [pinia] } })

    expect(wrapper.text()).not.toContain('KWIC PLACEHOLDER')
    expect(wrapper.text()).not.toContain('FREQUENCY TAB')
    expect(counters.frequencyMounts).toBe(0)

    resolveContract(contractWithHiddenFrequency())
    await flushPromises()

    expect(wrapper.text()).toContain('KWIC PLACEHOLDER')
    expect(wrapper.text()).not.toContain('FREQUENCY TAB')
    expect(counters.frequencyMounts).toBe(0)
    expect(uiStore.activeTab).toBe('kwic')
    expect(actionMocks.dispatch).toHaveBeenCalledWith(
      { type: 'nav/switchTab', payload: { tab: 'kwic' } },
      { source: 'system' }
    )
  })

  it('does not start remote settings/bootstrap routes before the product contract is known', async () => {
    apiMocks.getProductCapabilities.mockImplementationOnce(() => new Promise(() => undefined))

    const pinia = createPinia()
    setActivePinia(pinia)
    mount(App, { global: { plugins: [pinia] } })
    await flushPromises()

    expect(apiMocks.getProductCapabilities).toHaveBeenCalledOnce()
    expect(apiMocks.getPrefs).not.toHaveBeenCalled()
    expect(apiMocks.getSystemInfo).not.toHaveBeenCalled()
    expect(apiMocks.getEmbeddingModels).not.toHaveBeenCalled()
  })

  it('does not mount a corpus-blocked active analysis tab after the contract resolves', async () => {
    apiMocks.getProductCapabilities.mockResolvedValueOnce(contractWithCorpusBlockedWordSketch())

    const pinia = createPinia()
    setActivePinia(pinia)
    seedWordOnlyCorpus()
    const uiStore = useUiStore()
    uiStore.setActiveTab('wordsketch')

    const wrapper = mount(App, { global: { plugins: [pinia] } })
    await flushPromises()

    expect(wrapper.text()).toContain('KWIC PLACEHOLDER')
    expect(wrapper.text()).not.toContain('WORDSKETCH TAB')
    expect(uiStore.activeTab).toBe('kwic')
    expect(actionMocks.dispatch).toHaveBeenCalledWith(
      { type: 'nav/switchTab', payload: { tab: 'kwic' } },
      { source: 'system' }
    )
  })

  it('allows the missing-contract KWIC fallback only after a non-release session is authoritative', async () => {
    let resolveSession!: (value: Awaited<ReturnType<typeof apiMocks.getAuthSession>>) => void
    apiMocks.getProductCapabilities.mockRejectedValueOnce(new Error('capability contract offline'))
    apiMocks.getAuthSession.mockImplementationOnce(() => new Promise((resolve) => {
      resolveSession = resolve
    }))

    const pinia = createPinia()
    setActivePinia(pinia)
    const wrapper = mount(App, { global: { plugins: [pinia] } })

    expect(wrapper.text()).not.toContain('KWIC PLACEHOLDER')
    await flushPromises()

    resolveSession({
      schema_version: 'auth-session-v1',
      authenticated: true,
      token_present: false,
      username: 'dev',
      role: 'admin',
      effective_role: 'admin',
      rbac_enabled: false,
      security_mode: 'local-dev',
      release_mode: false,
      unsafe_token_transport: true,
      dev_token_available: true,
      can_access_all_roles: true,
    })
    await flushPromises()

    expect(wrapper.text()).toContain('KWIC PLACEHOLDER')
    expect(wrapper.text()).not.toContain('FREQUENCY TAB')
  })
})
