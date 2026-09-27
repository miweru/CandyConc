import { beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'

import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSettingsStore } from '@/stores/settings'
import { applyLocale } from '@/i18n/locale'

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

describe('corpus activation single source of truth', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getCorpora.mockResolvedValue({
      corpora: [summary('A', true), summary('B', false)],
      count: 2,
    })
    getSystemInfo.mockResolvedValue({
      corpusName: 'B',
      tokenCount: 2000,
      documentCount: 10,
    })
    activateCorpus.mockImplementation(async (name: string) => summary(name, true))
    registerCorpus.mockImplementation(async (path: string, active: boolean) => ({
      ...summary('registered-index', active),
      path,
      source: 'registered',
    }))
    unregisterCorpus.mockResolvedValue({ status: 'ok', path: '/corpora/B' })
    getProductCapabilities.mockResolvedValue(productContract())
    getCorpusBuildReport.mockResolvedValue({
      schema_version: 'corpus-build-report-v1',
      corpus: 'B',
      reports: {
        build_report: { token_count: 2000 },
        manifest: { import_mode: 'parquet' },
      },
      build_report: { token_count: 2000 },
      manifest: { import_mode: 'parquet' },
    })
  })

  it('reloads localized corpus labels without changing the selected corpus', async () => {
    const store = useCorpusCapabilitiesStore()
    useQueryStore().setFilters({ corpus: 'A' })
    getCorpora.mockResolvedValueOnce({ corpora: [{ ...summary('A', true), features: {
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
    } }] })
    await store.fetchCorpora()
    expect(store.queryAttributes[0]?.label).toBe('Wortform')
    getCorpora.mockResolvedValueOnce({ corpora: [{ ...summary('A', true), features: {
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Word form' }],
    } }] })
    applyLocale('en')
    await flushPromises()
    expect(store.queryAttributes[0]?.label).toBe('Word form')
    expect(store.activeCorpus).toBe('A')
    expect(activateCorpus).not.toHaveBeenCalled()
    store.$dispose()
    applyLocale('de')
  })

  it('calls the backend activate endpoint when switching corpus', async () => {
    const store = useCorpusCapabilitiesStore()
    await store.fetchCorpora()
    await store.setActive('B')
    expect(activateCorpus).toHaveBeenCalledWith('B')
  })

  it('keeps the notice when a start-time pin leaves the copilot on another corpus', async () => {
    activateCorpus.mockImplementationOnce(async (name: string) => ({
      ...summary(name, true),
      activation_notice: 'The copilot keeps using the corpus the server was started with.',
    }))
    const store = useCorpusCapabilitiesStore()
    await store.fetchCorpora()
    await store.setActive('B')
    expect(store.activeCorpus).toBe('B')
    expect(store.activationNotice).toContain('copilot keeps using')

    await store.setActive('A')
    expect(store.activationNotice).toBeNull()
  })

  it('makes switcher, query filter, status bar and badge agree after a switch', async () => {
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    const settings = useSettingsStore()
    await corpus.fetchCorpora()

    await corpus.setActive('B')

    // 1. switcher / store truth
    expect(corpus.activeCorpus).toBe('B')
    // 2. query filter (drives all search consumers)
    expect(query.filters.corpus).toBe('B')
    // 3. status bar / footer (systemInfo refreshed from backend)
    expect(settings.systemInfo.corpusName).toBe('B')
    // 4. manager catalogue badge — exactly one active, and it is B
    const active = corpus.corpora.filter((c) => c.active)
    expect(active.map((c) => c.name)).toEqual(['B'])
  })

  it('uses the backend catalogue active corpus as initial UI search scope instead of hardcoded default', async () => {
    getCorpora.mockResolvedValueOnce({
      corpora: [summary('registered-index', true), summary('default', false)],
      count: 2,
    })
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()

    await corpus.fetchCorpora()

    expect(corpus.activeCorpus).toBe('registered-index')
    expect(query.filters.corpus).toBe('registered-index')
    expect(corpus.activeSummary?.name).toBe('registered-index')
  })

  it('does not overwrite an explicit client corpus scope while refreshing the catalogue', async () => {
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    query.setFilters({ corpus: 'explicit-scope' })

    await corpus.fetchCorpora()

    expect(corpus.activeCorpus).toBe('explicit-scope')
    expect(query.filters.corpus).toBe('explicit-scope')
  })

  it('resets stale query scope on a real corpus change', async () => {
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    await corpus.fetchCorpora()
    query.setFilters({ corpus: 'A' })
    query.setResults(
      [{ position: 1, left: 'der', match: 'Hase', right: 'rennt', docId: 'd1' }],
      42,
      true,
      false,
    )

    await corpus.setActive('B')

    expect(query.results).toEqual([])
    expect(query.totalHits).toBe(0)
  })

  it('keeps the current client corpus and records activationError when /activate fails', async () => {
    activateCorpus.mockRejectedValueOnce(new Error('Not Found'))
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    await corpus.fetchCorpora()
    query.setFilters({ corpus: 'A' })

    await corpus.setActive('B')

    expect(corpus.activeCorpus).toBe('A')
    expect(query.filters.corpus).toBe('A')
    expect(corpus.corpora.filter((item) => item.active).map((item) => item.name)).toEqual(['A'])
    expect(corpus.activationError).toBe('Not Found')
  })

  it('lets the last of overlapping switches decide the corpus in the client and at the backend', async () => {
    // A slow activation of B finished after a later choice and used to
    // switch the client back to B.
    getCorpora.mockResolvedValue({
      corpora: [summary('A', true), summary('B', false), summary('C', false), summary('D', false)],
      count: 4,
    })
    let finishB: () => void = () => {}
    activateCorpus.mockImplementation((name: string) => (name === 'B'
      ? new Promise((resolve) => { finishB = () => resolve(summary('B', true)) })
      : Promise.resolve(summary(name, true))))
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    await corpus.fetchCorpora()

    const first = corpus.setActive('B')
    await flushPromises()
    const second = corpus.setActive('C')
    const third = corpus.setActive('D')
    await flushPromises()
    expect(activateCorpus.mock.calls.map(([name]) => name)).toEqual(['B'])
    expect(corpus.isActivating).toBe(true)

    finishB()
    await Promise.all([first, second, third])

    // C was replaced by D before it was sent. B was sent and is followed by D.
    expect(activateCorpus.mock.calls.map(([name]) => name)).toEqual(['B', 'D'])
    expect(query.filters.corpus).toBe('D')
    expect(corpus.corpora.filter((item) => item.active).map((item) => item.name)).toEqual(['D'])
    expect(corpus.isActivating).toBe(false)
  })

  it('stays on the corpus the backend activated when a later switch fails', async () => {
    let finishB: () => void = () => {}
    activateCorpus.mockImplementation((name: string) => (name === 'B'
      ? new Promise((resolve) => { finishB = () => resolve(summary('B', true)) })
      : Promise.reject(new Error('Conflict'))))
    getCorpora.mockResolvedValue({
      corpora: [summary('A', true), summary('B', false), summary('C', false)],
      count: 3,
    })
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    await corpus.fetchCorpora()

    const first = corpus.setActive('B')
    await flushPromises()
    const second = corpus.setActive('C')
    finishB()
    await Promise.all([first, second])

    expect(activateCorpus.mock.calls.map(([name]) => name)).toEqual(['B', 'C'])
    expect(query.filters.corpus).toBe('B')
    expect(corpus.activationError).toBe('Conflict')
    expect(corpus.isActivating).toBe(false)
  })

  it('keeps the active badge on a corpus switched to while an older catalogue request was running', async () => {
    // Several components load the catalogue. A response requested before a
    // switch carried the old active flag and moved the manager badge back.
    let finishLate: (value: unknown) => void = () => {}
    getCorpora
      .mockResolvedValueOnce({ corpora: [summary('A', true), summary('B', false)], count: 2 })
      .mockImplementationOnce(() => new Promise((resolve) => { finishLate = resolve }))
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()
    await corpus.fetchCorpora()

    const late = corpus.fetchCorpora()
    await corpus.setActive('B')
    finishLate({ corpora: [summary('A', true), summary('B', false)], count: 2 })
    await late

    expect(query.filters.corpus).toBe('B')
    expect(corpus.corpora.filter((item) => item.active).map((item) => item.name)).toEqual(['B'])
  })

  it('unregisters via the backend and falls back to the new default when active', async () => {
    const corpus = useCorpusCapabilitiesStore()
    await corpus.fetchCorpora()
    await corpus.setActive('B')
    expect(corpus.activeCorpus).toBe('B')

    // After unregister, backend returns only A (now active/default).
    getCorpora.mockResolvedValue({ corpora: [summary('A', true)], count: 1 })
    getSystemInfo.mockResolvedValue({ corpusName: 'A', tokenCount: 1000, documentCount: 10 })

    await corpus.unregister('B')

    expect(unregisterCorpus).toHaveBeenCalledWith('B')
    expect(corpus.activeCorpus).toBe('A')
  })

  it('registers an existing index through the catalogue route without importing files', async () => {
    const corpus = useCorpusCapabilitiesStore()
    await corpus.fetchCorpora()

    const result = await corpus.registerExisting('/indexes/registered-index', true)

    expect(registerCorpus).toHaveBeenCalledWith('/indexes/registered-index', true)
    expect(result?.name).toBe('registered-index')
    expect(corpus.activeCorpus).toBe('registered-index')
    expect(corpus.registerError).toBeNull()
  })

  it('loads build reports for registered corpora as visible corpus evidence', async () => {
    const corpus = useCorpusCapabilitiesStore()

    await corpus.loadBuildReport('B')

    expect(getCorpusBuildReport).toHaveBeenCalledWith('B')
    expect(corpus.buildReportsByCorpus.B).toEqual({
      schema_version: 'corpus-build-report-v1',
      corpus: 'B',
      reports: {
        build_report: { token_count: 2000 },
        manifest: { import_mode: 'parquet' },
      },
      build_report: { token_count: 2000 },
      manifest: { import_mode: 'parquet' },
    })
    expect(corpus.buildReportError).toBeNull()
  })

  it('does not treat pair axes alone as paired because backend paired routes require paired=true', async () => {
    getCorpora.mockResolvedValueOnce({
      corpora: [{
        ...summary('default', true),
        paired: false,
        pair_axes: ['model'],
        capabilities: { parallel: false },
      }],
      count: 1,
    })
    const corpus = useCorpusCapabilitiesStore()

    await corpus.fetchCorpora()

    expect(corpus.isPaired).toBe(false)
    expect(corpus.pairAxes).toEqual(['model'])
    expect(corpus.canUseParallelGroups).toBe(false)
    expect(corpus.canUseParallelKwic).toBe(false)
  })

  it('fails closed instead of inheriting pairing from a different active corpus', async () => {
    getCorpora.mockResolvedValueOnce({
      corpora: [{
        ...summary('paired-source', true),
        paired: true,
        pair_axes: ['model'],
        capabilities: { parallel: true },
      }],
      count: 1,
    })
    const corpus = useCorpusCapabilitiesStore()
    const query = useQueryStore()

    await corpus.fetchCorpora()
    query.setFilters({ corpus: 'missing-corpus' })

    expect(corpus.activeSummary).toBeNull()
    expect(corpus.isPaired).toBe(false)
    expect(corpus.pairAxes).toEqual([])
    expect(corpus.canUseParallelGroups).toBe(false)
    expect(corpus.canUseParallelKwic).toBe(false)
  })

  it('prefers descriptor alignment gates over broad legacy parallel flags', async () => {
    getCorpora.mockResolvedValueOnce({
      corpora: [{
        ...summary('default', true),
        paired: true,
        pair_axes: ['legacy-axis'],
        capabilities: { parallel: true },
        features: {
          schema_version: 'corpus-features-v1',
          token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
          frequency_groups: [{ id: 'word', label: 'Wortform' }],
          alignment: {
            paired: true,
            pair_axes: ['model'],
            parallel_groups: true,
            parallel_kwic: false,
          },
        },
      }],
      count: 1,
    })
    const corpus = useCorpusCapabilitiesStore()

    await corpus.fetchCorpora()

    expect(corpus.isPaired).toBe(true)
    expect(corpus.pairAxes).toEqual(['model'])
    expect(corpus.canUseParallelGroups).toBe(true)
    expect(corpus.canUseParallelKwic).toBe(false)
  })
})
