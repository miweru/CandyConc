import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KeynessTab from '@/components/analysis/KeynessTab.vue'
import WorkspaceAnalysesPanel from '@/components/workspace/WorkspaceAnalysesPanel.vue'
import { useAnalysisPresetsStore, type AnalysisPreset } from '@/stores/analysisPresets'
import { actionBus } from '@/actions'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useDocsetStore } from '@/stores/docset'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSessionStore } from '@/stores/session'
import { useSubcorporaStore } from '@/stores/subcorpora'
import type { ProductCapabilityContract } from '@/api/client'
import { guardNetwork } from '../../helpers/networkGuard'

const apiMocks = vi.hoisted(() => ({
  createKeynessJob: vi.fn(),
  docsetFromMeta: vi.fn(),
  createAnalysisPreset: vi.fn(),
  updateAnalysisPreset: vi.fn(),
  getAnalysisJob: vi.fn(),
  getAnalysisJobRows: vi.fn(),
  getMetaValues: vi.fn(),
  getMetaCounts: vi.fn(),
  listSubcorpora: vi.fn(),
  resolveSubcorpus: vi.fn(),
  getSystemInfo: vi.fn(),
  downloadCsv: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    docsetFromMeta: (...args: unknown[]) => apiMocks.docsetFromMeta(...args),
    createKeynessJob: (...args: unknown[]) => apiMocks.createKeynessJob(...args),
    createAnalysisPreset: (...args: unknown[]) => apiMocks.createAnalysisPreset(...args),
    updateAnalysisPreset: (...args: unknown[]) => apiMocks.updateAnalysisPreset(...args),
    getAnalysisJob: (...args: unknown[]) => apiMocks.getAnalysisJob(...args),
    getAnalysisJobRows: (...args: unknown[]) => apiMocks.getAnalysisJobRows(...args),
    getMetaValues: (...args: unknown[]) => apiMocks.getMetaValues(...args),
    getMetaCounts: (...args: unknown[]) => apiMocks.getMetaCounts(...args),
    listSubcorpora: (...args: unknown[]) => apiMocks.listSubcorpora(...args),
    resolveSubcorpus: (...args: unknown[]) => apiMocks.resolveSubcorpus(...args),
    // The saved analysis session keys its cache on the corpus signature.
    getSystemInfo: (...args: unknown[]) => apiMocks.getSystemInfo(...args),
  }
})

vi.mock('@/utils/csv', async (importOriginal) => ({
  ...await importOriginal<typeof import('@/utils/csv')>(),
  downloadCsv: (...args: unknown[]) => apiMocks.downloadCsv(...args),
}))

// A tab left mounted kept its debounce timers (group counts after 120 ms,
// result persistence after 250 ms). They fired during a later test, and their
// store actions made the Pinia of the earlier test the active one again. The
// corpus switch of the later test then went to a store its tab did not read.
enableAutoUnmount(afterEach)

// Jobs report progress over a WebSocket after a ticket request. A server
// without tickets answers 404, and the job is polled through the mocked client.
guardNetwork((url) => (url.endsWith('/api/v1/ws-ticket') ? new Response(null, { status: 404 }) : undefined))

const stubs = {
  AnalysisToolbar: { template: '<section><slot name="left" /><slot name="center" /><slot name="right" /><slot /><slot name="actions" /></section>' },
  Button: { props: ['disabled', 'loading'], template: '<button :disabled="disabled" v-bind="$attrs"><slot /></button>' },
  CapabilityBoundaryPanel: { template: '<div class="boundary" />' },
  EmptyState: { template: '<div><slot /></div>' },
  FilterField: { props: ['label', 'hint'], template: '<label><span>{{ label }}</span><slot /></label>' },
  JobStatusPill: { template: '<span />' },
  LexicalDiversityCard: { template: '<div />' },
  Modal: { template: '<section><slot /></section>' },
  SaveAnalysisButton: { template: '<button />' },
  Skeleton: { template: '<div />' },
  ArrowUpDown: true,
  Download: true,
  Filter: true,
  Hash: true,
  Layers: true,
  Network: true,
  RefreshCw: true,
  Scale: true,
}

function route(path: string, methods = ['POST']) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(id: string, capabilityId: string, path: string, methods = ['POST']) {
  return {
    id,
    capability_id: capabilityId,
    label: id,
    description: '',
    route: route(path, methods),
    effects: ['read'],
    handler_key: id,
    surface_slot: id,
    priority: 10,
    input_schema_ref: 'operation.test',
    required_context: [],
    response_shape: 'data',
    run_semantics: 'instant',
    ui_execution_policy: 'contextual_ui',
    requires_parameters: true,
  }
}

function capability(id: string, operations: ReturnType<typeof operation>[]) {
  return {
    id,
    title: id,
    area: id.split('.')[0],
    maturity: 'stable',
    visibility: 'first_class_ui',
    backend_routes: operations.map((item) => item.route.path),
    backend_route_descriptors: operations.map((item) => item.route),
    operations,
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function cloneContract(): ProductCapabilityContract {
  return structuredClone({
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [
      capability('research.subcorpora_docsets', [
        operation('research.subcorpora_docsets.docset_intersection', 'research.subcorpora_docsets', '/api/v1/docsets/intersection'),
        operation('research.subcorpora_docsets.subcorpora_resolve', 'research.subcorpora_docsets', '/api/v1/subcorpora/resolve'),
      ]),
      capability('analysis.keyness', [
        operation('analysis.keyness.job', 'analysis.keyness', '/api/v1/analysis/keyness/job'),
      ]),
      capability('analysis.async_jobs', [
        operation('analysis.async_jobs.status', 'analysis.async_jobs', '/api/v1/analysis/jobs/{job_id}', ['GET']),
        operation('analysis.async_jobs.rows', 'analysis.async_jobs', '/api/v1/analysis/jobs/{job_id}/rows', ['GET']),
      ]),
    ],
  }) as ProductCapabilityContract
}

function seedSession(): void {
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

function seedCorpus(): void {
  useQueryStore().setFilters({ corpus: 'default' })
  useCorpusCapabilitiesStore().corpora = [{
    name: 'default',
    path: '/corpora/default',
    active: true,
    token_count: 1000,
    doc_count: 10,
    import_mode: 'fixture',
    paired: true,
    pair_axes: ['ref_doc'],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: {
        paired: true,
        pair_axes: ['ref_doc'],
        parallel_groups: true,
        parallel_kwic: false,
      },
    },
  }]
}

function seedContract(contract = cloneContract()): void {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = contract
}

function removeIntersectionOperation(contract: ProductCapabilityContract): ProductCapabilityContract {
  const next = structuredClone(contract) as ProductCapabilityContract
  const capability = next.capabilities.find((item) => item.id === 'research.subcorpora_docsets')
  if (!capability) throw new Error('Fixture lacks research.subcorpora_docsets')
  capability.operations = capability.operations.filter((operation) =>
    operation.id !== 'research.subcorpora_docsets.docset_intersection'
  )
  return next
}

function withMetaValues(contract = cloneContract()): ProductCapabilityContract {
  const next = structuredClone(contract) as ProductCapabilityContract
  const capability = next.capabilities.find((item) => item.id === 'research.subcorpora_docsets')!
  capability.operations.push(
    operation('research.subcorpora_docsets.meta_values', 'research.subcorpora_docsets', '/api/v1/analysis/meta_values') as never,
  )
  return next
}

describe('KeynessTab Docset-Intersection workflow', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedSession()
    seedCorpus()
    seedContract()
    apiMocks.getMetaValues.mockResolvedValue({
      text_type: ['ai', 'human'],
      prompting_method: [],
      model: [],
      register: [],
      source: [],
    })
    apiMocks.getMetaCounts.mockResolvedValue({})
    apiMocks.getSystemInfo.mockResolvedValue({ backendVersion: 'test', tokenCount: 1000, documentCount: 10 })
    apiMocks.listSubcorpora.mockResolvedValue([])
    apiMocks.resolveSubcorpus.mockResolvedValue({
      docset_id: 'reference-docset',
      doc_count: 4,
      token_count: 400,
      stale: false,
    })
    apiMocks.createKeynessJob.mockResolvedValue({ job_id: 'job-keyness-1' })
    apiMocks.createAnalysisPreset.mockImplementation(async (preset: Record<string, unknown>) => ({
      ...preset,
      id: 'preset-keyness-1',
      updated_at: Date.now(),
    }))
    apiMocks.updateAnalysisPreset.mockImplementation(async (id: string, patch: Record<string, unknown>) => ({
      id,
      name: 'Keyness',
      type: 'keyness',
      params: {},
      ...patch,
      updated_at: Date.now(),
    }))
    apiMocks.getAnalysisJob.mockResolvedValue({
      job_id: 'job-keyness-1',
      kind: 'keyness',
      corpus: 'default',
      status: 'done',
      progress: 1,
      message: 'fertig',
    })
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-keyness-1',
      rows: [],
      total_rows: 0,
      row_limit: 500,
      total_candidates: 0,
      truncated: false,
      offset: 0,
      limit: 500,
      status: 'done',
      method: { family: 'keyness' },
    })
  })

  it('shows the docset-intersection workflow without a product contract card', async () => {
    const wrapper = mount(KeynessTab, {
      props: { mode: 'contrast' },
      global: { stubs },
    })

    await flushPromises()

    expect(wrapper.text()).not.toContain('Docset-Intersection-Contract')
    expect(wrapper.text()).not.toContain('research.subcorpora_docsets.docset_intersection')
    expect(wrapper.find('[aria-label="Docset-Intersection-ProductOperation"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Texte mit gemeinsamem ref_doc, die sich alignieren lassen')
    expect(wrapper.findAll('button').some((button) => button.text().includes('Intersection berechnen'))).toBe(true)
  })

  it('starts the groups on the version side the corpus has and labels anchor and version neutrally', async () => {
    // Paired imports from builder revision 2 on write anchor/version. The
    // groups defaulted to text_type ai, which such a corpus does not have.
    apiMocks.getMetaValues.mockResolvedValue({
      text_type: ['anchor', 'version'],
      prompting_method: [],
      model: [],
      register: [],
      source: [],
    })
    seedContract(withMetaValues())
    const wrapper = mount(KeynessTab, {
      props: { mode: 'contrast' },
      global: { stubs },
    })
    await flushPromises()

    const selects = wrapper.findAll('select').filter((select) =>
      select.findAll('option').some((option) => option.attributes('value') === 'version')
    )
    expect(selects).toHaveLength(2)
    for (const select of selects) {
      expect((select.element as HTMLSelectElement).value).toBe('version')
      const labels = select.findAll('option').map((option) => option.text().split(' · ')[0])
      expect(labels).toEqual(['Anker', 'Fassung'])
    }
    expect(wrapper.text()).toContain('Anker-Referenzen einbeziehen')
    expect(wrapper.text()).not.toContain('Menschliche Referenzen einbeziehen')
  })

  it('keeps the human/AI labels for a corpus whose pairs carry human and ai', async () => {
    seedContract(withMetaValues())
    const wrapper = mount(KeynessTab, {
      props: { mode: 'contrast' },
      global: { stubs },
    })
    await flushPromises()

    const select = wrapper.findAll('select').find((node) =>
      node.findAll('option').some((option) => option.attributes('value') === 'ai')
    )
    expect(select).toBeTruthy()
    expect((select!.element as HTMLSelectElement).value).toBe('ai')
    expect(select!.findAll('option').map((option) => option.text().split(' · ')[0])).toEqual(['KI', 'Mensch'])
    expect(wrapper.text()).toContain('Menschliche Referenzen einbeziehen')
  })

  it('shows a blocked workflow reason after use when the intersection operation is absent', async () => {
    seedContract(removeIntersectionOperation(cloneContract()))

    const wrapper = mount(KeynessTab, {
      props: { mode: 'contrast' },
      global: { stubs },
    })

    await flushPromises()

    expect(wrapper.text()).not.toContain('Docset-Intersection-Contract')
    expect(wrapper.find('[aria-label="Docset-Intersection-ProductOperation"]').exists()).toBe(false)

    const intersectionButton = wrapper.findAll('button').find((button) =>
      button.text().includes('Intersection berechnen')
    )
    expect(intersectionButton).toBeTruthy()
    await intersectionButton!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('nicht als Serverfunktion verfügbar')
  })

  it('keeps standalone Keyness free of the legacy Mensch/KI intersection surface', async () => {
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-target'
    docsetStore.activeSubcorpusName = 'Ziel-Subkorpus'

    const wrapper = mount(KeynessTab, {
      props: { mode: 'keyness' },
      global: { stubs },
    })

    await flushPromises()

    expect(wrapper.text()).toContain('Ziel: Ziel-Subkorpus')
    expect(wrapper.text()).toContain('Standalone-Keyness vergleicht das aktive Ziel-Subkorpus')
    expect(wrapper.text()).toContain('Keine gebündelte externe deutsche Referenzfrequenzliste')
    expect(wrapper.text()).toContain('freqlist-Referenzen bleiben API-only')
    expect(wrapper.text()).toContain('Gesamtkorpus')
    expect(wrapper.text()).not.toContain('Menschliche Referenzen einbeziehen')
    expect(wrapper.text()).not.toContain('Mensch-vs-KI')
    expect(wrapper.text()).not.toContain('Gemeinsame Referenzen')
    expect(wrapper.text()).not.toContain('Struktur: Text-/Prompttyp')
  })

  it('runs standalone Docset-vs-Docset Keyness through a generic saved reference subcorpus', async () => {
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'target-docset'
    docsetStore.activeSubcorpusName = 'Ziel-Subkorpus'
    const subcorporaStore = useSubcorporaStore()
    subcorporaStore.snapshots = [{
      id: 'ref-scope',
      name: 'Referenz-Subkorpus',
      status: 'parked',
      createdAt: Date.now(),
      corpus: 'default',
      docsetId: undefined,
      stats: { docCount: 4, tokenCount: 400, refDocCount: 0 },
      statsResolved: true,
      filters: { prompting_method: [], model: [], register: ['Zeitung'], source: [] },
      filterSpec: { register: 'Zeitung' },
      includeAi: true,
      includeHuman: true,
      origin: { type: 'filter', label: 'Register Zeitung' },
      resolution: { status: 'fresh', stale: false },
    }]
    subcorporaStore.initialized = true

    const wrapper = mount(KeynessTab, {
      props: { mode: 'keyness' },
      global: { stubs },
    })
    await flushPromises()

    await wrapper.find('select[title="Womit das Ziel verglichen wird"]').setValue('docset')
    await flushPromises()
    await wrapper.find('select[aria-label="Referenz-Subkorpus für Standalone-Keyness"]').setValue('ref-scope')
    await flushPromises()
    const keynessButton = wrapper.findAll('button').find((button) => button.text().includes('Keyness'))
    expect(keynessButton).toBeTruthy()
    await keynessButton!.trigger('click')
    await flushPromises()

    expect(apiMocks.resolveSubcorpus).toHaveBeenCalledWith('Referenz-Subkorpus', 'default')
    expect(apiMocks.createKeynessJob).toHaveBeenCalledWith(expect.objectContaining({
      targetDocsetId: 'target-docset',
      referenceDocsetId: 'reference-docset',
      corpus: 'default',
      minFreq: 5,
    }))
  })

  it.each(['whole', 'docset', 'corpus'])('exports the computed %s comparison after controls change', async (source) => {
    const docset = useDocsetStore()
    docset.activeDocsetId = 'garden-docset'
    docset.activeSubcorpusName = 'garden'
    docset.stats.docCount = 5
    docset.stats.tokenCount = 125
    docset.activeFilterSpec = { topic: ['garden'], year: { min: 1950, max: 1960 } }
    const subcorpora = useSubcorporaStore()
    subcorpora.snapshots = [{
      id: 'factory', name: 'factory', status: 'parked', createdAt: 1, corpus: 'default',
      stats: { docCount: 4, tokenCount: 400, refDocCount: 0 }, statsResolved: true,
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { topic: ['factory'] }, includeAi: true, includeHuman: true,
      origin: { type: 'filter', label: 'factory' },
    }]
    subcorpora.initialized = true
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-keyness-1', rows: [{ word: 'Rose', target_freq: 10, reference_freq: 0, ll: 12 }],
      total_rows: 1, total_candidates: 1, offset: 0, limit: 500, status: 'done',
      method: { family: 'keyness', target_total: 125, reference_total: 400 },
    })
    const wrapper = mount(KeynessTab, { props: { mode: 'keyness' }, global: { stubs } })
    await flushPromises()
    const referenceSelect = wrapper.get('select[title="Womit das Ziel verglichen wird"]')
    await referenceSelect.setValue(source)
    if (source === 'docset') {
      await wrapper.get('select[aria-label="Referenz-Subkorpus für Standalone-Keyness"]').setValue('factory')
    } else if (source === 'corpus') {
      await wrapper.get('.ref-input[type="text"]').setValue('dta_de')
    }
    await wrapper.findAll('button').find(button => button.text() === 'Keyness')!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Rose')
    expect(apiMocks.createKeynessJob).toHaveBeenCalledWith(expect.objectContaining({
      targetDocsetId: 'garden-docset', corpus: 'default', minFreq: 5,
      ...(source === 'docset' ? { referenceDocsetId: 'reference-docset' } : { referenceSource: source }),
    }))
    docset.activeDocsetId = 'changed-docset'
    docset.activeSubcorpusName = 'changed'
    docset.activeFilterSpec.topic = ['changed']
    subcorpora.snapshots[0]!.filterSpec!.topic = ['changed']
    await referenceSelect.setValue('corpus')
    await wrapper.get('.ref-input[type="text"]').setValue('changed')
    await wrapper.get('.ref-input[type="number"]').setValue('9')
    await wrapper.get('.export-actions button:last-child').trigger('click')
    const [csv, filename] = apiMocks.downloadCsv.mock.calls[0]!
    expect(filename).toContain('default_garden_vs_')
    expect(csv).toContain('# Target: garden\n')
    expect(csv).toContain('# TargetDocset: garden-docset\n')
    expect(csv).toContain('# TargetDocs: 5\n')
    expect(csv).toContain('# TargetTokens: 125\n')
    expect(csv).toContain('# TargetFilters: {"topic":["garden"],"year":{"min":1950,"max":1960}}')
    expect(csv).toContain(`# ReferenceSource: ${source}\n`)
    expect(csv).toContain('# MinFreq: 5\n')
    expect(csv).not.toContain('changed')
    expect(csv).not.toContain('# Reference: human')
    if (source === 'docset') {
      expect(csv).toContain('# Reference: factory\n')
      expect(csv).toContain('# ReferenceDocset: reference-docset\n')
      expect(csv).toContain('# ReferenceFilters: {"topic":["factory"]}')
    } else if (source === 'whole') {
      expect(csv).toContain('# ReferenceExcludedDocset: garden-docset\n')
    } else {
      expect(csv).toContain('# ReferenceCorpus: dta_de\n')
      expect(csv).toContain('# Reference: dta_de\n')
    }
  })

  it.each(['whole', 'docset', 'corpus'])('reopens saved %s keyness with its computed metadata scope and controls', async (source) => {
    const docset = useDocsetStore()
    const query = useQueryStore()
    const corpora = useCorpusCapabilitiesStore()
    const presets = useAnalysisPresetsStore()
    const contract = cloneContract()
    contract.capabilities.find(c => c.id === 'research.subcorpora_docsets')!.operations.push(
      operation('research.subcorpora_docsets.docset_from_meta', 'research.subcorpora_docsets', '/api/v1/docsets/from_meta') as never,
    )
    seedContract(contract)
    query.setTerm('harbor')
    docset.activeDocsetId = 'coast-docset'
    docset.activeFilterSpec = { text_group: ['Coast'] }
    docset.activeDocsetOrigin = { kind: 'meta' }
    docset.stats = { docCount: 8, tokenCount: 200, hitDocCount: 0, refDocCount: 0 }
    useSubcorporaStore().snapshots = [{
      id: 'hill', name: 'Hill', status: 'parked', createdAt: 1, corpus: 'default',
      stats: { docCount: 8, tokenCount: 200, refDocCount: 0 }, statsResolved: true,
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { text_group: ['Hill'] }, includeAi: true, includeHuman: true,
      origin: { type: 'filter', label: 'Hill' },
    }]
    useSubcorporaStore().initialized = true
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-keyness-1', rows: [{ word: 'Coastword', target_freq: 10, reference_freq: 0, ll: 12 }],
      total_rows: 1, offset: 0, limit: 500, status: 'done', method: { family: 'keyness' },
    })
    apiMocks.docsetFromMeta.mockResolvedValue({ docset_id: 'coast-restored', doc_count: 8, token_count: 200 })
    let saved: AnalysisPreset | undefined
    vi.spyOn(presets, 'add').mockImplementation(async (preset) => {
      saved = JSON.parse(JSON.stringify(preset)) as AnalysisPreset
      presets.presets = [saved]
      return saved
    })
    vi.spyOn(presets, 'init').mockResolvedValue()
    vi.spyOn(presets, 'touch').mockResolvedValue(undefined as never)
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
    vi.spyOn(corpora, 'setActive').mockImplementation(async name => { query.setFilters({ corpus: name }) })
    let wrapper = mount(KeynessTab, { props: { mode: 'keyness' }, global: { stubs: {
      ...stubs, SaveAnalysisButton: false,
      Modal: { props: ['modelValue'], template: '<section v-if="modelValue"><slot /></section>' },
    } } })
    await flushPromises()
    const reference = wrapper.get('select[title="Womit das Ziel verglichen wird"]')
    await reference.setValue(source)
    await wrapper.get('.ref-input[type="number"]').setValue(7)
    if (source === 'docset') await wrapper.get('select[aria-label="Referenz-Subkorpus für Standalone-Keyness"]').setValue('hill')
    if (source === 'corpus') await wrapper.get('.ref-input[type="text"]').setValue('other')
    await wrapper.findAll('button').find(button => button.text() === 'Keyness')!.trigger('click')
    await flushPromises()
    // Saving a displayed result must keep its inputs even after controls change.
    docset.activeFilterSpec = { text_group: ['Hill'] }
    await reference.setValue('corpus')
    await wrapper.get('.ref-input[type="text"]').setValue('changed')
    await wrapper.get('.ref-input[type="number"]').setValue(99)
    await wrapper.findAll('button').find(button => button.text() === 'Speichern')!.trigger('click')
    await wrapper.get('.save-input').setValue('Coast comparison')
    await wrapper.get('.save-actions button:last-child').trigger('click')
    await flushPromises()
    expect(saved?.docset?.filterSpec).toEqual({ text_group: ['Coast'] })
    expect(saved?.docset?.query).toBeUndefined()
    expect(saved?.params).toMatchObject({ referenceSource: source, keynessMinFreq: 7 })
    // Open a serialized preset after switching the corpus and query.
    corpora.corpora.push({ ...corpora.corpora[0]!, name: 'other', active: false })
    query.setFilters({ corpus: 'other' })
    query.setTerm('changed')
    await flushPromises()
    if (source === 'whole') wrapper.unmount()
    const workspace = mount(WorkspaceAnalysesPanel)
    await flushPromises()
    await workspace.get('button[aria-label="Analyse öffnen"]').trigger('click')
    await flushPromises()
    expect(actionBus.dispatch).toHaveBeenCalledWith(
      { type: 'nav/switchTab', payload: { tab: 'keyness' } }, { source: 'restore' },
    )
    if (source === 'whole') {
      // The lazy tab mounts after Workspace has queued the restore.
      expect(presets.pendingPreset?.id).toBe(saved?.id)
      wrapper = mount(KeynessTab, { props: { mode: 'keyness' }, global: { stubs } })
    }
    await flushPromises()
    expect(query.filters.corpus).toBe('default')
    expect(query.term).toBe('harbor')
    expect(apiMocks.docsetFromMeta).toHaveBeenCalledWith({ text_group: ['Coast'] }, 'default')
    expect(docset.activeDocsetId).toBe('coast-restored')
    expect(docset.activeDocsetOrigin).toEqual({ kind: 'meta' })
    expect((wrapper.get('select[title="Womit das Ziel verglichen wird"]').element as HTMLSelectElement).value).toBe(source)
    expect((wrapper.get('.ref-input[type="number"]').element as HTMLInputElement).value).toBe('7')
    if (source === 'docset') expect((wrapper.get('select[aria-label="Referenz-Subkorpus für Standalone-Keyness"]').element as HTMLSelectElement).value).toBe('hill')
    if (source === 'corpus') expect((wrapper.get('.ref-input[type="text"]').element as HTMLInputElement).value).toBe('other')
    expect(wrapper.text()).toContain('Coastword')
    expect(apiMocks.createKeynessJob).toHaveBeenCalledTimes(1)
  })

  it('empties the Keyness table after a corpus switch', async () => {
    // The table kept the rows of the previous corpus under the new corpus
    // name, while the target subcorpus of that corpus was no longer active.
    // The store handles are taken before the mount, so the switch below goes
    // to the stores the tab reads.
    const queryStore = useQueryStore()
    const corpusCapabilities = useCorpusCapabilitiesStore()
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'target-docset'
    docsetStore.activeSubcorpusName = 'Ziel-Subkorpus'
    apiMocks.getAnalysisJobRows.mockResolvedValue({
      job_id: 'job-keyness-1',
      rows: [{ word: 'Applause', target_freq: 12, reference_freq: 0, ll: 20, ll_signed: 20, direction: 'target' }],
      total_rows: 1,
      row_limit: 500,
      total_candidates: 1,
      truncated: false,
      offset: 0,
      limit: 500,
      status: 'done',
      method: { family: 'keyness' },
    })
    const wrapper = mount(KeynessTab, {
      props: { mode: 'keyness' },
      global: { stubs },
    })
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Keyness'))!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Applause')

    corpusCapabilities.corpora.push({ ...corpusCapabilities.corpora[0]!, name: 'other', active: false })
    queryStore.setFilters({ corpus: 'other' })
    await flushPromises()

    expect(wrapper.text()).toContain('· other')
    expect(wrapper.text()).not.toContain('Applause')
    expect(wrapper.findAll('tbody tr')).toHaveLength(0)
  })

  it('loads every available Keyness result page without rendering every row', async () => {
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'target-docset'
    docsetStore.activeSubcorpusName = 'Ziel-Subkorpus'
    const rows = Array.from({ length: 1001 }, (_, index) => ({
      word: `Wort ${index + 1}`,
      target_freq: index + 1,
      reference_freq: 0,
      ll: index + 1,
      ll_signed: index + 1,
      direction: 'target',
    }))
    apiMocks.getAnalysisJobRows.mockImplementation(async (
      _jobId: string,
      offset = 0,
      limit = 500,
    ) => ({
      job_id: 'job-keyness-1',
      rows: rows.slice(offset, offset + limit),
      total_rows: rows.length,
      row_limit: 500,
      total_candidates: 1250,
      truncated: true,
      offset,
      limit,
      status: 'done',
      method: { family: 'keyness' },
    }))

    const wrapper = mount(KeynessTab, {
      props: { mode: 'keyness' },
      global: { stubs },
    })
    await flushPromises()

    const keynessButton = wrapper.findAll('button').find((button) => button.text().includes('Keyness'))
    expect(keynessButton).toBeTruthy()
    await keynessButton!.trigger('click')
    await flushPromises()

    expect(apiMocks.getAnalysisJobRows).toHaveBeenLastCalledWith('job-keyness-1', 0, 500)
    expect(wrapper.text()).toContain('Top 500 von 1.250 Kandidaten')

    await wrapper.get('[aria-label="Weitere Keyness-Kandidaten laden"]').trigger('click')
    await flushPromises()
    expect(apiMocks.getAnalysisJobRows).toHaveBeenLastCalledWith('job-keyness-1', 500, 500)

    await wrapper.get('[aria-label="Weitere Keyness-Kandidaten laden"]').trigger('click')
    await flushPromises()
    expect(apiMocks.getAnalysisJobRows).toHaveBeenLastCalledWith('job-keyness-1', 1000, 500)
    expect(wrapper.find('[aria-label="Weitere Keyness-Kandidaten laden"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Top 1.001 von 1.250 Kandidaten')
    expect(wrapper.findAll('tbody tr').length).toBeLessThan(150)
  })
})
