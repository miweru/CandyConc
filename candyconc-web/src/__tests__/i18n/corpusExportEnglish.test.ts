/**
 * Corpus manager, import reports and export dialog render in English when
 * the interface language is English. Before this change every label in these
 * views was a German literal, and the corpus manager rewrote role denials
 * with a German regular expression, so an English denial kept the generic
 * operation label of the capability contract.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, disposePinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CorpusManagerContent from '@/components/corpus/CorpusManagerContent.vue'
import ExportDialog from '@/components/export/ExportDialog.vue'
import { applyLocale } from '@/i18n/locale'
import { importReportEntriesFromPayload, importReportOutcomeFromPayload } from '@/lib/importReportDiagnostics'
import { useCorpusImportsStore } from '@/stores/corpusImports'
import { useExportStore } from '@/stores/export'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import type { ProductCapabilityContract } from '@/api/client'

const getProductCapabilities = vi.fn()
const getAuthSession = vi.fn()
const getCorpora = vi.fn()
const getCorpusImportMethods = vi.fn()
const listCorpusImportJobs = vi.fn()
const getCorpusImportReports = vi.fn()

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
    getAuthSession: (...args: unknown[]) => getAuthSession(...args),
    getCorpora: (...args: unknown[]) => getCorpora(...args),
    getCorpusCapabilities: vi.fn(),
    getCorpusImportMethods: (...args: unknown[]) => getCorpusImportMethods(...args),
    listCorpusImportJobs: (...args: unknown[]) => listCorpusImportJobs(...args),
    getCorpusImportReports: (...args: unknown[]) => getCorpusImportReports(...args),
    getCorpusImportJob: vi.fn(),
    getSystemInfo: vi.fn(async () => ({ corpusName: 'sotu', tokenCount: 12, documentCount: 2 })),
    getFrequency: vi.fn(async () => [{ item: 'freedom', frequency: 3, relative: 0.3 }]),
  }
})

type Route = { path: string; methods: string[]; access: string }

function descriptor(route: Route) {
  return {
    path: route.path,
    methods: route.methods,
    mutates: route.methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: route.access,
    required_role: route.access,
    transport: 'http',
    route_class: route.access === 'admin' ? 'admin_surface' : 'product_surface',
  }
}

function capability(id: string, operations: Array<{ id: string; label: string; route: Route }>) {
  return {
    id,
    title: id,
    area: 'corpus',
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: operations.map((operation) => operation.route.path),
    backend_route_descriptors: operations.map((operation) => descriptor(operation.route)),
    operations: operations.map((operation) => ({
      id: operation.id,
      capability_id: id,
      label: operation.label,
      description: '',
      route: descriptor(operation.route),
      effects: operation.route.methods.some((method) => method !== 'GET') ? ['write'] : ['read'],
      handler_key: operation.id.split('.').at(-1) ?? operation.id,
      surface_slot: operation.id,
      priority: 100,
    })),
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: [],
    requires_corpus_features: [],
    limits: [],
  }
}

function corpusContract() {
  const admin = (path: string, method = 'GET') => ({ path, methods: [method], access: 'admin' })
  const user = (path: string, method = 'GET') => ({ path, methods: [method], access: 'user' })
  return {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [
      capability('corpus.catalogue', [
        { id: 'corpus.catalogue.list', label: 'Korpora listen', route: user('/api/v1/corpora') },
        { id: 'corpus.catalogue.register', label: 'Korpus registrieren', route: admin('/api/v1/corpora/register', 'POST') },
        { id: 'corpus.catalogue.activate', label: 'Korpus aktivieren', route: user('/api/v1/corpora/{corpus}/activate', 'POST') },
        { id: 'corpus.catalogue.capabilities', label: 'Korpusfähigkeiten laden', route: user('/api/v1/corpora/{corpus}/capabilities') },
        { id: 'corpus.catalogue.unregister', label: 'Korpusregistrierung entfernen', route: admin('/api/v1/corpora/{corpus}/registration', 'DELETE') },
      ]),
      capability('corpus.import', [
        { id: 'corpus.import.methods', label: 'Importmethoden laden', route: admin('/api/v1/corpora/import-methods') },
        { id: 'corpus.import.preflight', label: 'Import-Preflight ausführen', route: admin('/api/v1/corpora/import-preflight', 'POST') },
        { id: 'corpus.import.jobs_list', label: 'Importjobs listen', route: admin('/api/v1/corpora/imports') },
        { id: 'corpus.import.start', label: 'Importjob starten', route: admin('/api/v1/corpora/imports', 'POST') },
        { id: 'corpus.import.job_status', label: 'Importjob-Status laden', route: admin('/api/v1/corpora/imports/{job_id}') },
        { id: 'corpus.import.job_cancel', label: 'Importjob abbrechen', route: admin('/api/v1/corpora/imports/{job_id}/cancel', 'POST') },
        { id: 'corpus.import.job_reports', label: 'Importjob-Reports laden', route: admin('/api/v1/corpora/imports/{job_id}/reports') },
        { id: 'corpus.import.build_report', label: 'Korpus-Build-Report laden', route: admin('/api/v1/corpora/{corpus}/build-report') },
      ]),
    ],
  }
}

function session(role: 'admin' | 'user') {
  return {
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

const importMethod = {
  schema_version: 'corpus-import-method-v1',
  method: 'csv',
  label: 'CSV/TSV',
  description: '',
  option_keys: ['spacy_model'],
  input: { kind: 'server_file', extensions: ['.csv', '.tsv'], accepts_directories: false },
  availability: { status: 'available', script: 'ingest_adapters.py', subcommand: [] },
  option_specs: [
    { key: 'spacy_model', label: 'spacy_model', type: 'string', required: false, default: 'blank:en', choices: [], aliases: [] },
  ],
  expected_columns: [{ key: 'text', label: 'text', required: true }],
  output: { paired: false, pairing_kind: 'none', emitted_features: ['word'] },
  reports: [{ key: 'build_report', label: 'build_report' }],
}

const wrappers: Array<ReturnType<typeof mount>> = []

let pinia: ReturnType<typeof createPinia>

beforeEach(() => {
  pinia = createPinia()
  setActivePinia(pinia)
  vi.clearAllMocks()
  // The settings store is the one language source and starts from the browser
  // language. Components that create it (the corpus store reads defaultCorpus)
  // would reset a bare applyLocale, so the test runs with an English browser.
  Object.defineProperty(window.navigator, 'language', { value: 'en-US', configurable: true })
  applyLocale('en')
  getProductCapabilities.mockResolvedValue(corpusContract())
  getAuthSession.mockResolvedValue(session('admin'))
  getCorpora.mockResolvedValue({
    corpora: [{
      name: 'sotu',
      path: '/corpora/sotu',
      status: 'ready',
      source: 'registry',
      active: true,
      token_count: 1234,
      doc_count: 2,
      import_mode: 'csv',
      annotation_source: 'spacy',
      paired: false,
      pair_axes: [],
      is_legacy: false,
      capabilities: {},
    }],
    count: 1,
  })
  getCorpusImportMethods.mockResolvedValue([importMethod])
  listCorpusImportJobs.mockResolvedValue([])
  getCorpusImportReports.mockResolvedValue({ schema_version: 'corpus-import-reports-v1', reports: {} })
})

afterEach(() => {
  Object.defineProperty(window.navigator, 'language', { value: 'de-DE', configurable: true })
  while (wrappers.length) wrappers.pop()?.unmount()
  useCorpusImportsStore().stopPolling()
  disposePinia(pinia)
})

const GERMAN_MANAGER_LABELS = [
  'Korpusverwaltung',
  'Serverpfad importieren',
  'Vorhandenen Index registrieren',
  'Importjobs',
  'Korpuskatalog',
  'Aktualisieren',
  'Zielname',
  'Preflight prüfen',
  'Import starten',
  'Dokumente',
  'Fähigkeiten prüfen',
  'Aus Registry entfernen',
]

describe('corpus manager in English', () => {
  it('labels the import workflow, the job monitor and the catalog in English', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [pinia] } })
    wrappers.push(wrapper)
    await flushPromises()
    const text = wrapper.text()

    expect(text).toContain('Corpus manager')
    expect(text).toContain('Import workflow')
    expect(text).toContain('Source → Preflight → Evidence → Import')
    expect(text).toContain('Import from a server path')
    expect(text).toContain('Register an existing index')
    expect(text).toContain('Import jobs')
    expect(text).toContain('Corpus catalog')
    expect(text).toContain('1 method')
    expect(text).toContain('Builder available: ingest_adapters.py')
    expect(text).toContain('This method expects a file on the server. Expected extensions: .csv, .tsv.')
    expect(text).toContain('1,234 tokens')
    expect(text).toContain('2 documents')
    expect(text).toContain('Annotation: generated by spaCy')
    expect(wrapper.find('[data-testid="corpus-import-preflight-button"]').text()).toBe('Check input')
    expect(wrapper.find('[data-testid="corpus-import-start-button"]').text()).toBe('Start import')
    expect(wrapper.find('[data-testid="corpus-import-target-name"]').attributes('placeholder')).toBe('my_corpus')
    for (const label of GERMAN_MANAGER_LABELS) expect(text).not.toContain(label)
  })

  it('names the panel in English when a role denies the import', async () => {
    getAuthSession.mockResolvedValue(session('user'))
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [pinia] } })
    wrappers.push(wrapper)
    await flushPromises()
    const text = wrapper.text()

    expect(wrapper.find('[data-testid="corpus-import-start-button"]').exists()).toBe(false)
    expect(text).toContain('Corpus import requires at least the role Admin')
    expect(text).toContain('Import job monitor requires at least the role Admin')
    expect(text).toContain('Index registration requires at least the role Admin')
    expect(text).not.toContain('Importjob starten requires')
  })

  it('renders import report diagnostics and outcome warnings in English', () => {
    const payload = {
      reject_report: { data: { rejected_rows: 3, total_rows: 10, reject_policy: 'collect' } },
      manifest: { data: { import_mode: 'csv', complete: true } },
    }
    const entries = importReportEntriesFromPayload(payload)
    expect(entries.map((entry) => entry.label)).toEqual(['Rejected rows report', 'Index manifest'])
    const reject = entries[0]!
    expect(reject.diagnostics.map((item) => item.label)).toContain('Rejected rows')
    expect(reject.diagnostics.find((item) => item.label === 'Rejected rows')?.note)
      .toBe('The import finished, but not every input row was imported.')
    expect(importReportOutcomeFromPayload(payload).warnings).toEqual(['3 input rows were not imported.'])
  })
})

function seedReplayExport(): void {
  const route = (path: string, method = 'POST') => ({
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  })
  const operation = (id: string, path: string, capabilityId = 'research.replay_export', method = 'POST') => ({
    id,
    capability_id: capabilityId,
    label: id,
    description: '',
    route: route(path, method),
    effects: ['read'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 10,
  })
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'cqlf-capabilities-v1', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [{
      id: 'research.replay_export',
      title: 'Replay export',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: ['/api/v1/export/concordance', '/api/v1/export/evidence-package'],
      backend_route_descriptors: [route('/api/v1/export/concordance'), route('/api/v1/export/evidence-package')],
      operations: [
        operation('research.replay_export.concordance', '/api/v1/export/concordance'),
        operation('research.replay_export.evidence_package', '/api/v1/export/evidence-package'),
        operation('research.replay_export.pdf', '/api/v1/export/pdf'),
        operation('research.replay_export.docx', '/api/v1/export/docx'),
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }, {
      id: 'analysis.frequency',
      title: 'Frequency',
      area: 'analysis',
      maturity: 'stable',
      visibility: 'first_class_ui',
      backend_routes: ['/api/v1/analysis/frequency_list'],
      backend_route_descriptors: [route('/api/v1/analysis/frequency_list', 'GET')],
      operations: [operation('analysis.frequency.list', '/api/v1/analysis/frequency_list', 'analysis.frequency', 'GET')],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as ProductCapabilityContract
  const sessionStore = useSessionStore()
  sessionStore.status = 'ready'
  sessionStore.session = session('user')
}

const exportStubs = {
  Modal: {
    template: '<section><h2>{{ title }}</h2><p>{{ description }}</p><slot /><slot name="footer" /></section>',
    props: ['modelValue', 'title', 'description', 'size'],
  },
  Button: {
    props: ['disabled', 'title', 'loading'],
    template: '<button :disabled="disabled" :title="title"><slot /></button>',
  },
  FileJson: true,
  FileText: true,
  FileSpreadsheet: true,
  FileCode2: true,
}

const GERMAN_EXPORT_LABELS = [
  'Konkordanzdatei',
  'Geladener Auszug',
  'Provenienz',
  'Füllstand',
  'Inhalt',
  'Optionen',
  'Trefferumfang',
  'Gesamtzählung',
  'Exportieren',
  'Abbrechen',
  'geladene Zeilen',
]

describe('export dialog in English', () => {
  it('labels formats, scope and actions in English with English number format', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExport()
    // The settings store applies the stored language when it is created, so
    // switch through it as the interface does.
    await useSettingsStore().setLanguage('en')
    useQueryStore().setResults(
      [
        { position: 1, left: 'the', match: 'freedom', right: 'of', docId: 'd1' },
        { position: 2, left: 'our', match: 'freedom', right: 'and', docId: 'd2' },
      ],
      1200,
      true,
      true,
    )
    const wrapper = mount(ExportDialog, { props: { modelValue: true }, global: { plugins: [pinia], stubs: exportStubs } })
    wrappers.push(wrapper)
    const text = wrapper.text()

    expect(text).toContain('Export loaded results and optional analysis sections')
    expect(text).toContain('Concordance file (server)')
    expect(text).toContain('Evidence package / report')
    expect(text).toContain('Loaded excerpt')
    expect(text).toContain('Provenance: server query + scope')
    expect(text).toContain('Coverage: full count, lines may be capped')
    expect(text).toContain('Hits to export')
    expect(text).toContain('Server concordance (fully counted)')
    expect(text).toContain('Total count: 1,200 hits')
    expect(wrapper.findAll('button').some((button) => button.text() === 'Export')).toBe(true)
    expect(wrapper.findAll('button').some((button) => button.text() === 'Cancel')).toBe(true)
    for (const label of GERMAN_EXPORT_LABELS) expect(text).not.toContain(label)
  })

  it('writes English metadata labels and section titles into the CSV', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExport()
    await useSettingsStore().setLanguage('en')
    const queryStore = useQueryStore()
    queryStore.setTerm('freedom')
    queryStore.setResults([{ position: 1, left: 'the', match: 'freedom', right: 'of', docId: 'd1' }], 120, true, true)

    let downloaded: Blob | null = null
    class ReadableBlob {
      readonly parts: BlobPart[]
      readonly type: string
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        this.parts = parts
        this.type = options?.type ?? ''
      }
      async text(): Promise<string> {
        return this.parts.map((part) => String(part)).join('')
      }
    }
    vi.stubGlobal('Blob', ReadableBlob)
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      downloaded = blob as Blob
      return 'blob:candyconc-test'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    try {
      await useExportStore().exportData({
        format: 'csv',
        includeResults: false,
        includeFrequency: true,
        includeCollocations: false,
        includeStatistics: false,
        includeContext: true,
        includeMetadata: true,
        includeReproMeta: false,
        rowRange: 'all',
      })
      expect(downloaded).not.toBeNull()
      const csv = await downloaded!.text()
      expect(csv).toContain('# Search term: freedom')
      expect(csv).toContain('# Total hit count of the search: ≥ 120')
      expect(csv).toContain('# Concordance line scope: all currently loaded concordance lines')
      expect(csv).toContain('# Section: Frequency list (top 50)')
      expect(csv).not.toContain('Suchterm')
      expect(csv).not.toContain('Abschnitt')
    } finally {
      vi.unstubAllGlobals()
      vi.restoreAllMocks()
    }
  })
})
