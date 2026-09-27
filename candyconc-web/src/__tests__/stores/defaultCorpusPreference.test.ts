import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSettingsStore } from '@/stores/settings'

const activateCorpus = vi.fn()
const registerCorpus = vi.fn()
const unregisterCorpus = vi.fn()
const getCorpora = vi.fn()
const getCorpusBuildReport = vi.fn()
const getSystemInfo = vi.fn()
const getProductCapabilities = vi.fn()

vi.mock('@/api/client', () => ({
  getCorpora: (...args: unknown[]) => getCorpora(...args),
  getCorpusCapabilities: vi.fn(async (name: string) => ({
    name,
    path: `/corpora/${name}`,
    token_count: 100,
    doc_count: 10,
    import_mode: 'rows',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
  })),
  activateCorpus: (...args: unknown[]) => activateCorpus(...args),
  registerCorpus: (...args: unknown[]) => registerCorpus(...args),
  unregisterCorpus: (...args: unknown[]) => unregisterCorpus(...args),
  getCorpusBuildReport: (...args: unknown[]) => getCorpusBuildReport(...args),
  // settings store transitive imports
  getSystemInfo: (...args: unknown[]) => getSystemInfo(...args),
  getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
}))

function summary(name: string, active = false) {
  return {
    name,
    path: `/corpora/${name}`,
    status: 'ready' as const,
    active,
    token_count: name === 'B' ? 2000 : 1000,
    doc_count: 10,
    import_mode: 'rows',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
  }
}

function route(path: string, methods = ['GET']) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(id: string, capabilityId: string, label: string, path: string, methods = ['GET']) {
  return {
    id,
    capability_id: capabilityId,
    label,
    description: '',
    route: route(path, methods),
    effects: methods.some((method) => method !== 'GET') ? ['write'] : ['read'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 100,
  }
}

function productContract() {
  const catalogueRoutes = [
    route('/api/v1/corpora'),
    route('/api/v1/corpora/register', ['POST']),
    route('/api/v1/corpora/{corpus}/activate', ['POST']),
    route('/api/v1/corpora/{corpus}/capabilities'),
    route('/api/v1/corpora/{corpus}/registration', ['DELETE']),
  ]
  const buildReportRoute = route('/api/v1/corpora/{corpus}/build-report')
  const systemInfoRoute = route('/api/v1/system/info')
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
      {
        id: 'corpus.catalogue',
        title: 'Corpus catalogue',
        area: 'corpus',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: catalogueRoutes,
        backend_route_descriptors: catalogueRoutes,
        operations: [
          operation('corpus.catalogue.list', 'corpus.catalogue', 'Korpora listen', '/api/v1/corpora'),
          operation('corpus.catalogue.register', 'corpus.catalogue', 'Korpus registrieren', '/api/v1/corpora/register', ['POST']),
          operation('corpus.catalogue.activate', 'corpus.catalogue', 'Korpus aktivieren', '/api/v1/corpora/{corpus}/activate', ['POST']),
          operation('corpus.catalogue.capabilities', 'corpus.catalogue', 'Korpusfähigkeiten laden', '/api/v1/corpora/{corpus}/capabilities'),
          operation('corpus.catalogue.unregister', 'corpus.catalogue', 'Korpusregistrierung entfernen', '/api/v1/corpora/{corpus}/registration', ['DELETE']),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      {
        id: 'corpus.import',
        title: 'Corpus import',
        area: 'corpus',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [buildReportRoute],
        backend_route_descriptors: [buildReportRoute],
        operations: [
          operation('corpus.import.build_report', 'corpus.import', 'Build-Report laden', '/api/v1/corpora/{corpus}/build-report'),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
      {
        id: 'admin.system_operations',
        title: 'System operations',
        area: 'admin',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [systemInfoRoute],
        backend_route_descriptors: [systemInfoRoute],
        operations: [
          operation('admin.system_operations.info', 'admin.system_operations', 'Systeminformationen laden', '/api/v1/system/info'),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
    ],
  }
}

describe('default corpus preference', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    window.history.replaceState({}, '', '/')
    getCorpora.mockResolvedValue({
      corpora: [summary('A', true), summary('B', false)],
      count: 2,
    })
    getSystemInfo.mockResolvedValue({ corpusName: 'A', tokenCount: 1000, documentCount: 10 })
    activateCorpus.mockImplementation(async (name: string) => summary(name, true))
    getProductCapabilities.mockResolvedValue(productContract())
  })

  it('activates the preferred corpus at the first catalogue load', async () => {
    useSettingsStore().preferences.defaultCorpus = 'B'
    const store = useCorpusCapabilitiesStore()
    await store.fetchCorpora()
    expect(activateCorpus).toHaveBeenCalledWith('B')
    expect(useQueryStore().filters.corpus).toBe('B')
  })

  it('follows the catalogue with the placeholder value', async () => {
    useSettingsStore().preferences.defaultCorpus = 'default'
    const store = useCorpusCapabilitiesStore()
    await store.fetchCorpora()
    expect(activateCorpus).not.toHaveBeenCalled()
    expect(useQueryStore().filters.corpus).toBe('A')
  })

  it('lets a corpus in the address outrank the preference', async () => {
    window.history.replaceState({}, '', '/?corpus=A')
    useSettingsStore().preferences.defaultCorpus = 'B'
    const store = useCorpusCapabilitiesStore()
    await store.fetchCorpora()
    expect(activateCorpus).not.toHaveBeenCalled()
    expect(useQueryStore().filters.corpus).toBe('A')
  })

  it('applies the preference only once per session', async () => {
    useSettingsStore().preferences.defaultCorpus = 'B'
    const store = useCorpusCapabilitiesStore()
    await store.fetchCorpora()
    await store.setActive('A')
    activateCorpus.mockClear()
    useQueryStore().setFilters({ corpus: undefined })
    await store.fetchCorpora()
    expect(activateCorpus).not.toHaveBeenCalled()
  })

  it('keeps a corpus chosen while the preferred corpus is still being activated', async () => {
    // The switcher lists the catalogue as soon as it arrives, while the
    // preferred corpus is still activating. The later activation response
    // used to decide the corpus, so the preference overwrote the choice.
    getCorpora.mockResolvedValue({
      corpora: [summary('A', true), summary('B', false), summary('C', false)],
      count: 3,
    })
    let finishStartup: () => void = () => {}
    activateCorpus.mockImplementation((name: string) => (name === 'B'
      ? new Promise((resolve) => { finishStartup = () => resolve(summary('B', true)) })
      : Promise.resolve(summary(name, true))))
    useSettingsStore().preferences.defaultCorpus = 'B'
    const store = useCorpusCapabilitiesStore()

    const startup = store.fetchCorpora()
    await flushPromises()
    expect(activateCorpus).toHaveBeenCalledWith('B')
    const choice = store.setActive('C')
    await flushPromises()
    // The choice is not sent while the preferred corpus is still activating,
    // so the backend receives it last.
    expect(activateCorpus).toHaveBeenCalledTimes(1)

    finishStartup()
    await Promise.all([startup, choice])

    expect(activateCorpus.mock.calls.map(([name]) => name)).toEqual(['B', 'C'])
    expect(useQueryStore().filters.corpus).toBe('C')
    expect(store.corpora.filter((corpus) => corpus.active).map((corpus) => corpus.name)).toEqual(['C'])
    expect(store.isActivating).toBe(false)
  })

  it('ignores a preferred corpus that is not in the catalogue', async () => {
    useSettingsStore().preferences.defaultCorpus = 'gone'
    const store = useCorpusCapabilitiesStore()
    await store.fetchCorpora()
    expect(activateCorpus).not.toHaveBeenCalled()
    expect(useQueryStore().filters.corpus).toBe('A')
  })
})
