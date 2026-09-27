/**
 * The workspace (subcorpora, saved analyses, analysis jobs) renders in English
 * when the interface language is English. Before the translation every label
 * of these panels was a German literal and stayed German after the switch.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import WorkspaceAnalysesPanel from '@/components/workspace/WorkspaceAnalysesPanel.vue'
import WorkspaceManager from '@/components/workspace/WorkspaceManager.vue'
import WorkspaceSubcorporaPanel from '@/components/workspace/WorkspaceSubcorporaPanel.vue'
import { applyLocale } from '@/i18n/locale'
import {
  useAnalysisJobsStore,
  useAnalysisPresetsStore,
  useProductCapabilitiesStore,
  useSessionStore,
  useSubcorporaStore,
  useUiStore,
} from '@/stores'
import { useSettingsStore } from '@/stores/settings'
import { SUBCORPORA_OPERATIONS, type SubcorpusSnapshot } from '@/stores/subcorpora'
import { ANALYSIS_PRESET_OPERATIONS, type AnalysisPreset } from '@/stores/analysisPresets'
import type {
  ProductCapability,
  ProductCapabilityBackendRouteDescriptor,
  ProductCapabilityContract,
  ProductCapabilityOperation,
} from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: vi.fn(async () => { throw new Error('offline') }),
    getAuthSession: vi.fn(async () => { throw new Error('offline') }),
    getMcpTools: vi.fn(async () => ({ tools: [] })),
    listSubcorpora: vi.fn(async () => []),
    getAnalysisJob: vi.fn(),
    getAnalysisJobRows: vi.fn(),
    cancelAnalysisJob: vi.fn(),
    updatePrefs: vi.fn(async () => ({ ok: true })),
  }
})

function route(path: string, method: string): ProductCapabilityBackendRouteDescriptor {
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

function operation(
  capabilityId: string,
  id: string,
  handlerKey: string,
  routeDescriptor: ProductCapabilityBackendRouteDescriptor,
): ProductCapabilityOperation {
  return {
    id,
    capability_id: capabilityId,
    label: id,
    description: '',
    route: routeDescriptor,
    effects: routeDescriptor.mutates ? ['write'] : ['read'],
    handler_key: handlerKey,
    surface_slot: id,
    priority: 10,
  } as unknown as ProductCapabilityOperation // minimal fixture, only the fields the stores read
}

function capability(id: string, operations: ProductCapabilityOperation[]): ProductCapability {
  const routes = operations.map((op) => op.route)
  return {
    id,
    title: id,
    area: id.split('.')[0]!,
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: routes.map((r) => r.path),
    backend_route_descriptors: routes,
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function seedContract() {
  const subcorpora = 'research.subcorpora_docsets'
  const presets = 'research.analysis_presets'
  const jobs = 'analysis.async_jobs'
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      capability(subcorpora, [
        operation(subcorpora, SUBCORPORA_OPERATIONS.list, 'subcorpora_list', route('/api/v1/subcorpora', 'GET')),
        operation(subcorpora, SUBCORPORA_OPERATIONS.save, 'subcorpora_save', route('/api/v1/subcorpora', 'POST')),
        operation(subcorpora, SUBCORPORA_OPERATIONS.delete, 'subcorpora_delete', route('/api/v1/subcorpora/{name}', 'DELETE')),
        operation(subcorpora, SUBCORPORA_OPERATIONS.resolve, 'subcorpora_resolve', route('/api/v1/subcorpora/{name}/resolve', 'POST')),
      ]),
      capability(presets, [
        operation(presets, ANALYSIS_PRESET_OPERATIONS.list, 'analysis_presets_list', route('/api/v1/projects/{proj}/analysis-presets', 'GET')),
        operation(presets, ANALYSIS_PRESET_OPERATIONS.delete, 'analysis_presets_delete', route('/api/v1/projects/{proj}/analysis-presets/{preset_id}', 'DELETE')),
      ]),
      capability(jobs, [
        operation(jobs, 'analysis.async_jobs.status', 'analysis_job_status', route('/api/v1/analysis/jobs/{job_id}', 'GET')),
        operation(jobs, 'analysis.async_jobs.cancel', 'analysis_job_cancel', route('/api/v1/analysis/jobs/{job_id}/cancel', 'POST')),
        operation(jobs, 'analysis.async_jobs.rows', 'analysis_job_rows', route('/api/v1/analysis/jobs/{job_id}/rows', 'GET')),
      ]),
    ],
  } as ProductCapabilityContract
}

function seedSession() {
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

function snapshot(overrides: Partial<SubcorpusSnapshot>): SubcorpusSnapshot {
  return {
    id: 'snap-1',
    name: 'Speeches 1990s',
    status: 'parked',
    createdAt: Date.UTC(2026, 8, 26, 12, 0, 0),
    corpus: 'sotu',
    stats: { docCount: 1234, tokenCount: 56789, refDocCount: 0 },
    statsResolved: true,
    filters: { prompting_method: [], model: [], register: [], source: [] },
    includeAi: false,
    includeHuman: true,
    origin: { type: 'query', query: 'freedom' },
    resolution: { status: 'fresh', stale: false, resolvedAt: Date.UTC(2026, 8, 26, 12, 5, 0) },
    ...overrides,
  }
}

function preset(): AnalysisPreset {
  return {
    id: 'preset-1',
    name: 'freedom frequency',
    createdAt: Date.UTC(2026, 8, 25, 9, 0, 0),
    updatedAt: Date.UTC(2026, 8, 25, 9, 30, 0),
    type: 'frequency',
    corpus: 'sotu',
    docset: null,
    queryTerm: 'freedom',
    params: {},
    status: 'done',
    kind: 'saved',
  }
}

const GERMAN_LABELS = [
  'Gesamtkorpus',
  'Korpus:',
  'Geparkt',
  'Archiviert',
  'Keine Filter aktiv',
  'Filter zurücksetzen',
  'Aktiver Scope',
  'Parken',
  'Archivieren',
  'Quelle:',
  'geprüft',
  'Mensch',
  'Subkorpus',
  'Analysejobs',
  'bekannt',
  'aktiv',
  'Prüfen',
  'Zuletzt verwendet',
  'Wiederherstellen',
  'Erstellt:',
  'Frequenz',
  'Fertig',
  'Analyse',
  'Zeilen',
]

const wrappers: Array<ReturnType<typeof mount>> = []

describe('workspace in English', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    localStorage.clear()
    seedContract()
    seedSession()
    // The settings store owns the language. Setting it there keeps it from
    // resetting the locale when a panel first uses the store.
    await useSettingsStore().setLanguage('en')
  })

  afterEach(() => {
    while (wrappers.length) wrappers.pop()?.unmount()
    localStorage.clear()
    applyLocale('de')
  })

  it('labels the subcorpora panel in English', async () => {
    const subcorpora = useSubcorporaStore()
    vi.spyOn(subcorpora, 'init').mockResolvedValue()
    subcorpora.snapshots = [
      snapshot({}),
      snapshot({ id: 'snap-2', name: 'Archived set', status: 'archived', origin: { type: 'filter' }, includeHuman: false }),
    ]

    const wrapper = mount(WorkspaceSubcorporaPanel, {
      props: { active: true },
      global: { stubs: { Modal: true } },
    })
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Active scope')
    expect(text).toContain('Whole corpus')
    expect(text).toContain('Corpus: default')
    expect(text).toContain('All (2)')
    expect(text).toContain('Parked (1)')
    expect(text).toContain('Archived (1)')
    expect(text).toContain('2 subcorpora')
    expect(text).toContain('No filters active')
    expect(text).toContain('Park')
    expect(text).toContain('Archive')
    // The fixture corpus is not paired, so no reference documents (subcorpusRefsPairedOnly.test.ts).
    expect(text).toContain('1,234 docs · 56,789 tokens ·')
    expect(text).not.toContain('refs')
    expect(text).toContain('Source: query “freedom”')
    expect(text).toContain('Source: filter')
    expect(text).toContain('checked, up to date')
    expect(text).toContain('Human')
    expect(wrapper.get('input[type="search"]').attributes('placeholder')).toBe('Search subcorpora (name, query, model, register)…')
    expect(wrapper.find('button[aria-label="Rename subcorpus"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="Delete subcorpus"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="Move to archive"]').exists()).toBe(true)
    for (const german of GERMAN_LABELS) expect(text).not.toContain(german)
  })

  it('labels the saved analyses and the job monitor in English', async () => {
    const presets = useAnalysisPresetsStore()
    vi.spyOn(presets, 'init').mockResolvedValue()
    presets.presets = [preset()]
    useAnalysisJobsStore().setSnapshot({
      job_id: 'job-done-1',
      kind: 'frequency_list',
      corpus: 'sotu',
      status: 'done',
      progress: 100,
      message: 'finished',
      total_rows: 1500,
      result_available: true,
    }, 'frequency')

    const wrapper = mount(WorkspaceAnalysesPanel)
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Analysis jobs')
    expect(text).toContain('0 active')
    expect(text).toContain('1 known')
    expect(text).toContain('Check')
    expect(text).toContain('Frequency')
    expect(text).toContain('Corpus: sotu')
    expect(text).toContain('Rows: 1,500')
    expect(text).toContain('Done')
    expect(text).toContain('Recently used')
    expect(text).toContain('Whole corpus')
    expect(text).toContain('Query: freedom')
    expect(text).toContain('Created:')
    expect(text).toContain('Restore')
    expect(text).toContain('1 analysis')
    expect(wrapper.get('input[aria-label="Check an analysis job by job ID"]').attributes('placeholder')).toBe('Check or resume a job ID…')
    expect(wrapper.get('input[aria-label="Search analyses"]').attributes('placeholder')).toBe('Search analyses (name, type, query)…')
    expect(wrapper.find('button[aria-label="Open analysis"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="Delete analysis"]').exists()).toBe(true)
    for (const german of GERMAN_LABELS) expect(text).not.toContain(german)
  })

  it('labels the workspace tabs and counters in English', async () => {
    vi.spyOn(useAnalysisPresetsStore(), 'init').mockResolvedValue()
    vi.spyOn(useSubcorporaStore(), 'init').mockResolvedValue()
    const uiStore = useUiStore()
    uiStore.workspaceOpen = true
    uiStore.setWorkspaceTab('subcorpora')

    const wrapper = mount(WorkspaceManager, {
      global: {
        stubs: {
          SlideOver: { props: ['title'], template: '<div class="slide-over"><h2>{{ title }}</h2><slot /></div>' },
          WorkspaceSubcorporaPanel: { template: '<div>SUBCORPORA PANEL</div>' },
          WorkspaceAnalysesPanel: { template: '<div>ANALYSES PANEL</div>' },
        },
      },
    })
    wrappers.push(wrapper)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Workspace')
    expect(text).toContain('Corpus: default')
    expect(text).toContain('No filters active')
    expect(text).toContain('Parked:')
    expect(text).toContain('Archived:')
    expect(text).toContain('Saved analyses:')
    expect(text).toContain('Subcorpora')
    expect(text).toContain('Saved analyses')
    for (const german of ['Korpus:', 'Keine Filter aktiv', 'Geparkt:', 'Archiviert:', 'Analysen', 'Subkorpora', 'gesperrt']) {
      expect(text).not.toContain(german)
    }
  })
})
