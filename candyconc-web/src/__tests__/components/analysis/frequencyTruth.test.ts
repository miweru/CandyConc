import { mount, flushPromises } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import FrequencyTab from '@/components/analysis/FrequencyTab.vue'
import {
  createAnalysisPreset,
  createFrequencyListJob,
  getAnalysisJob,
  getAnalysisJobRows,
  getFrequencyResult,
  updateAnalysisPreset,
  type ProductCapabilityContract,
} from '@/api/client'
import { useCorpusCapabilitiesStore, useProductCapabilitiesStore, useSessionStore } from '@/stores'

const getCorpora = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getCorpora: (...args: unknown[]) => getCorpora(...args),
    createFrequencyListJob: vi.fn(async () => ({
      job_id: 'job-frequency-1',
      status_url: '/api/v1/analysis/jobs/job-frequency-1',
      rows_url: '/api/v1/analysis/jobs/job-frequency-1/rows?offset=0&limit=200',
    })),
    getAnalysisJob: vi.fn(async () => ({
      job_id: 'job-frequency-1',
      kind: 'frequency_list',
      corpus: 'default',
      status: 'done',
      progress: 100,
      message: 'Fertig',
      result_available: true,
      rows_state: 'available',
      result_readiness: 'available',
    })),
    getAnalysisJobRows: vi.fn(async () => ({
      job_id: 'job-frequency-1',
      status: 'done',
      row_limit: 50,
      total_candidates: 125,
      truncated: true,
      rows: [{ word: 'Hase', f: 3 }],
    })),
    getFrequencyResult: vi.fn(async () => ({
      rows: [{ item: 'Hase', frequency: 3, relative: 0.03 }],
      groupBy: 'word',
      basis: 'analyst_token_frequency',
      casePolicy: 'case_insensitive (lowercase)',
      filteredTokenPolicy: 'Leere Werte, reine Nicht-Alnum-Werte und |Marker|-Werte sind ausgeschlossen',
      rowLimit: 50,
      totalCandidates: 125,
      truncated: true,
    })),
    createAnalysisPreset: vi.fn(async (preset: Record<string, unknown>) => ({
      ...preset,
      id: 'preset-frequency-auto',
      created_at: 1000,
      updated_at: 1000,
      last_accessed_at: 1000,
    })),
    updateAnalysisPreset: vi.fn(async (id: string, patch: Record<string, unknown>) => ({
      id,
      name: 'patched',
      type: 'frequency',
      corpus: 'default',
      docset: null,
      query_term: null,
      params: {},
      result: patch.result ?? null,
      result_meta: patch.result_meta ?? null,
      status: patch.status ?? 'done',
      job_id: null,
      kind: 'session',
      created_at: 1000,
      updated_at: 2000,
      last_accessed_at: 2000,
    })),
  }
})

function frequencyContract(): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [{
      id: 'analysis.frequency',
      title: 'Frequency lists',
      area: 'analysis',
      maturity: 'stable',
      visibility: 'first_class_ui',
      backend_routes: [
        '/api/v1/analysis/frequency_list',
        '/api/v1/analysis/frequency_list/job',
      ],
      backend_route_descriptors: [
        {
          path: '/api/v1/analysis/frequency_list',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
        {
          path: '/api/v1/analysis/frequency_list/job',
          methods: ['POST'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
      ],
      operations: [
        {
          id: 'analysis.frequency.list',
          capability_id: 'analysis.frequency',
          label: 'Frequenzliste',
          description: '',
          route: {
            path: '/api/v1/analysis/frequency_list',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          effects: ['read'],
          handler_key: 'frequency_list',
          surface_slot: 'analysis.frequency.sync',
          priority: 10,
        },
        {
          id: 'analysis.frequency.job',
          capability_id: 'analysis.frequency',
          label: 'Frequenzjob',
          description: '',
          route: {
            path: '/api/v1/analysis/frequency_list/job',
            methods: ['POST'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          effects: ['read', 'long_running'],
          handler_key: 'frequency_list_job',
          surface_slot: 'analysis.frequency.job',
          priority: 20,
        },
      ],
      frontend_evidence: [{
        path: 'candyconc-web/src/components/analysis/FrequencyTab.vue',
        contains: 'useFrequencyOperations',
        note: 'Frequency tab executes through product operation gates.',
      }],
      action_types: ['analysis/frequency'],
      copilot_tools: ['frequency_list'],
      preconditions: [],
      requires_corpus_features: [],
      limits: ['Frequency jobs are first-class only for groupBy=word.'],
      notes: '',
    }, {
      id: 'analysis.async_jobs',
      title: 'Analysis jobs',
      area: 'analysis',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [
        '/api/v1/analysis/jobs/{job_id}',
        '/api/v1/analysis/jobs/{job_id}/cancel',
        '/api/v1/analysis/jobs/{job_id}/rows',
      ],
      backend_route_descriptors: [
        {
          path: '/api/v1/analysis/jobs/{job_id}',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
        {
          path: '/api/v1/analysis/jobs/{job_id}/cancel',
          methods: ['POST'],
          mutates: true,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
        {
          path: '/api/v1/analysis/jobs/{job_id}/rows',
          methods: ['GET'],
          mutates: false,
          requires_corpus_features: [],
          access: 'user',
          required_role: 'user',
          transport: 'http',
          route_class: 'product_surface',
        },
      ],
      operations: [
        {
          id: 'analysis.async_jobs.status',
          capability_id: 'analysis.async_jobs',
          label: 'Analysejob-Status',
          description: '',
          route: {
            path: '/api/v1/analysis/jobs/{job_id}',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          effects: ['read'],
          handler_key: 'analysis_job_status',
          surface_slot: 'analysis.jobs.status',
          priority: 10,
        },
        {
          id: 'analysis.async_jobs.cancel',
          capability_id: 'analysis.async_jobs',
          label: 'Analysejob abbrechen',
          description: '',
          route: {
            path: '/api/v1/analysis/jobs/{job_id}/cancel',
            methods: ['POST'],
            mutates: true,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          effects: ['write'],
          handler_key: 'analysis_job_cancel',
          surface_slot: 'analysis.jobs.cancel',
          priority: 20,
        },
        {
          id: 'analysis.async_jobs.rows',
          capability_id: 'analysis.async_jobs',
          label: 'Analysejob-Zeilen',
          description: '',
          route: {
            path: '/api/v1/analysis/jobs/{job_id}/rows',
            methods: ['GET'],
            mutates: false,
            requires_corpus_features: [],
            access: 'user',
            required_role: 'user',
            transport: 'http',
            route_class: 'product_surface',
          },
          effects: ['read'],
          handler_key: 'analysis_job_rows',
          surface_slot: 'analysis.jobs.rows',
          priority: 30,
        },
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
      notes: '',
    }],
  }
}

function seedFrequencyAccess() {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.contract = frequencyContract()
  productCapabilities.status = 'ready'
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/corpora/default',
    token_count: 100,
    doc_count: 1,
    import_mode: 'generic',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    active: true,
    capabilities: { lemma_lex: true, pos_lex: true },
  }]
  corpusCapabilities.loaded = true
  const session = useSessionStore()
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    rbac_enabled: true,
    token_present: false,
    role: 'user',
    effective_role: 'user',
    username: 'tester',
    security_mode: 'test',
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: true,
    release_mode: true,
  }
  session.status = 'ready'
}

function appendAnalysisPresetAccess() {
  const productCapabilities = useProductCapabilitiesStore()
  const operation = (id: string, path: string, method: 'POST' | 'PATCH') => ({
    id,
    capability_id: 'research.analysis_presets',
    label: id,
    description: '',
    route: {
      path,
      methods: [method],
      mutates: true,
      requires_corpus_features: [],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    },
    effects: ['write'],
    handler_key: id,
    surface_slot: id,
    priority: 10,
  })
  const operations = [
    operation('research.analysis_presets.create', '/api/v1/projects/{proj}/analysis-presets', 'POST'),
    operation('research.analysis_presets.update', '/api/v1/projects/{proj}/analysis-presets/{preset_id}', 'PATCH'),
  ]
  const routes = operations.map((item) => item.route)
  productCapabilities.contract!.capabilities.push({
    id: 'research.analysis_presets',
    title: 'Analyse-Presets',
    area: 'research_workflow',
    maturity: 'guarded',
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
  } as never)
}

describe('FrequencyTab truth note', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getCorpora.mockResolvedValue({
      corpora: [{
        name: 'default',
        path: '/corpora/default',
        token_count: 100,
        doc_count: 1,
        import_mode: 'generic',
        paired: false,
        pair_axes: [],
        is_legacy: false,
        capabilities: { lemma_lex: true, pos_lex: true },
      }],
      count: 1,
    })
  })

  it('surfaces token policy and Top-N truncation in the visible UI', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    seedFrequencyAccess()
    const productCapabilities = useProductCapabilitiesStore()
    const frequency = productCapabilities.contract!.capabilities[0]!
    frequency.backend_routes = ['/api/v1/analysis/frequency_list']
    frequency.backend_route_descriptors = frequency.backend_route_descriptors.filter(
      (route) => route.path === '/api/v1/analysis/frequency_list',
    )
    frequency.operations = frequency.operations.filter(
      (operation) => operation.id === 'analysis.frequency.list',
    )
    const wrapper = mount(FrequencyTab, {
      global: {
        plugins: [
          pinia,
          [VueQueryPlugin, { queryClient }],
        ],
        stubs: {
          AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
          BarChart: true,
          EmptyState: true,
          JobStatusPill: true,
          SaveAnalysisButton: true,
          Skeleton: true,
          Download: true,
          SortAsc: true,
          SortDesc: true,
          BarChart3: true,
          List: true,
          AlertTriangle: true,
        },
      },
    })

    await flushPromises()

    expect(getFrequencyResult).toHaveBeenCalledWith(expect.objectContaining({ groupBy: 'word' }), expect.any(Object))
    expect(wrapper.text()).toContain('Tokenpolitik: Leere Werte, reine Nicht-Alnum-Werte und |Marker|-Werte sind ausgeschlossen')
    expect(wrapper.text()).toContain('Groß-/Kleinschreibung: zusammengeführt (ß und ss getrennt)')
    expect(wrapper.text()).toContain('Wortform (Groß-/Kleinschreibung zusammengeführt)')
    expect(wrapper.text()).toContain('Anzeige: 1 von 125 Kandidaten')
  })

  // Rueckweg: a row opens the concordance of exactly the tokens it counts.
  it('opens the concordance of a row with the same folding and scope', async () => {
    const { actionBus } = await import('@/actions/bus')
    const spy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true } as never)
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const pinia = createPinia()
    setActivePinia(pinia)
    seedFrequencyAccess()
    const productCapabilities = useProductCapabilitiesStore()
    const frequency = productCapabilities.contract!.capabilities[0]!
    frequency.operations = frequency.operations.filter((operation) => operation.id === 'analysis.frequency.list')
    const wrapper = mount(FrequencyTab, {
      global: {
        plugins: [pinia, [VueQueryPlugin, { queryClient }]],
        stubs: {
          AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
          BarChart: true, EmptyState: true, JobStatusPill: true, SaveAnalysisButton: true, Skeleton: true,
        },
      },
    })
    await flushPromises()
    await wrapper.find('[data-testid="frequency-row-0"]').trigger('click')
    await flushPromises()
    const call = spy.mock.calls.find(([action]) => (action as { type: string }).type === 'query/execute')
    expect(call).toBeTruthy()
    expect((call![0] as { payload: { term: string } }).payload.term).toBe('cql:[word="Hase"%c]')
    spy.mockRestore()
  })

  it('uses the observable frequency job when the product contract exposes it', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    seedFrequencyAccess()

    const wrapper = mount(FrequencyTab, {
      global: {
        plugins: [
          pinia,
          [VueQueryPlugin, { queryClient }],
        ],
        stubs: {
          AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
          BarChart: true,
          EmptyState: true,
          JobStatusPill: true,
          SaveAnalysisButton: true,
          Skeleton: true,
          Download: true,
          SortAsc: true,
          SortDesc: true,
          BarChart3: true,
          List: true,
          AlertTriangle: true,
        },
      },
    })

    await flushPromises()
    await flushPromises()

    expect(createFrequencyListJob).toHaveBeenCalledWith(expect.objectContaining({
      groupBy: 'word',
      corpus: 'default',
    }))
    expect(getAnalysisJob).toHaveBeenCalledWith('job-frequency-1')
    expect(getAnalysisJobRows).toHaveBeenCalledWith('job-frequency-1', 0, 100)
    expect(getFrequencyResult).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Tokenpolitik: Leere Werte, reine Nicht-Alnum-Werte und |Marker|-Werte sind ausgeschlossen')
    expect(wrapper.text()).toContain('Groß-/Kleinschreibung: zusammengeführt (ß und ss getrennt)')
    expect(wrapper.text()).toContain('Anzeige: 1 von 125 Kandidaten')
  })

  it('does not create or patch saved presets when frequency rows load automatically', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    seedFrequencyAccess()
    appendAnalysisPresetAccess()

    mount(FrequencyTab, {
      global: {
        plugins: [
          pinia,
          [VueQueryPlugin, { queryClient }],
        ],
        stubs: {
          AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
          BarChart: true,
          EmptyState: true,
          JobStatusPill: true,
          SaveAnalysisButton: true,
          Skeleton: true,
          Download: true,
          SortAsc: true,
          SortDesc: true,
          BarChart3: true,
          List: true,
          AlertTriangle: true,
        },
      },
    })

    await flushPromises()
    await flushPromises()

    expect(createFrequencyListJob).toHaveBeenCalled()
    expect(createAnalysisPreset).not.toHaveBeenCalled()
    expect(updateAnalysisPreset).not.toHaveBeenCalled()
  })

  it('exposes the backend POS-prefix frequency filter as a normal frequency control', async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    })
    const pinia = createPinia()
    setActivePinia(pinia)
    seedFrequencyAccess()

    const wrapper = mount(FrequencyTab, {
      global: {
        plugins: [
          pinia,
          [VueQueryPlugin, { queryClient }],
        ],
        stubs: {
          AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
          BarChart: true,
          EmptyState: true,
          JobStatusPill: true,
          SaveAnalysisButton: true,
          Skeleton: true,
          Download: true,
          SortAsc: true,
          SortDesc: true,
          BarChart3: true,
          List: true,
          AlertTriangle: true,
        },
      },
    })

    await flushPromises()
    await flushPromises()

    const posInput = wrapper.find('[data-testid="frequency-pos-prefix"]')
    expect(posInput.exists()).toBe(true)
    vi.mocked(createFrequencyListJob).mockClear()

    await posInput.setValue('NN')
    await flushPromises()
    await flushPromises()

    expect(createFrequencyListJob).toHaveBeenCalledWith(expect.objectContaining({
      groupBy: 'word',
      posPrefix: 'NN',
    }))
    expect(wrapper.text()).toContain('POS-Präfix: NN')
    expect(wrapper.text()).toContain('POS-Präfixfilter ist für Wortfrequenzen verfügbar')
  })
})
