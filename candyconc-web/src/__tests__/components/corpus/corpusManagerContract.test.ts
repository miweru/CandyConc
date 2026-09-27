import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import CorpusManagerContent from '@/components/corpus/CorpusManagerContent.vue'
import { useCorpusImportsStore } from '@/stores/corpusImports'
import { corpusImportAdapterMethodDescriptors } from '../../fixtures/corpusImportAdapterMethods'

const getProductCapabilities = vi.fn()
const getAuthSession = vi.fn()
const getCorpora = vi.fn()
const getCorpusCapabilities = vi.fn()
const getCorpusImportMethods = vi.fn()
const getCorpusImportReports = vi.fn()
const createCorpusImportJob = vi.fn()
const preflightCorpusImport = vi.fn()
const registerCorpus = vi.fn()
const getCorpusBuildReport = vi.fn()
const listCorpusImportJobs = vi.fn()
const unregisterCorpus = vi.fn()

vi.mock('@/api/client', () => ({
  activateCorpus: vi.fn(async (name: string) => corpusSummary(name, true)),
  cancelCorpusImportJob: vi.fn(),
  createCorpusImportJob: (...args: unknown[]) => createCorpusImportJob(...args),
  getCorpora: (...args: unknown[]) => getCorpora(...args),
  getCorpusBuildReport: (...args: unknown[]) => getCorpusBuildReport(...args),
  getCorpusCapabilities: (...args: unknown[]) => getCorpusCapabilities(...args),
  getCorpusImportJob: vi.fn(),
  getCorpusImportMethods: (...args: unknown[]) => getCorpusImportMethods(...args),
  getCorpusImportReports: (...args: unknown[]) => getCorpusImportReports(...args),
  getAuthSession: (...args: unknown[]) => getAuthSession(...args),
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
  getProductCapabilities: (...args: unknown[]) => getProductCapabilities(...args),
  getSystemInfo: vi.fn(async () => ({ corpusName: 'demo', tokenCount: 12, documentCount: 2 })),
  listCorpusImportJobs: (...args: unknown[]) => listCorpusImportJobs(...args),
  preflightCorpusImport: (...args: unknown[]) => preflightCorpusImport(...args),
  registerCorpus: (...args: unknown[]) => registerCorpus(...args),
  unregisterCorpus: (...args: unknown[]) => unregisterCorpus(...args),
}))

function corpusSummary(name: string, active = false, overrides: Record<string, unknown> = {}) {
  return {
    name,
    path: `/corpora/${name}`,
    status: 'ready',
    source: name === 'default' ? 'default' : 'registry',
    active,
    token_count: 12,
    doc_count: 2,
    import_mode: 'parquet',
    paired: name === 'parallel-demo',
    pair_axes: name === 'parallel-demo' ? ['model'] : [],
    is_legacy: false,
    capabilities: { parallel: name === 'parallel-demo', free_contrast: true },
    ...overrides,
  }
}

function capability(id: string, title: string, area = 'corpus') {
  const routesByCapability: Record<string, Array<{ path: string; methods: string[]; mutates?: boolean; access?: string; required_role?: string }>> = {
    'corpus.catalogue': [
      { path: '/api/v1/corpora', methods: ['GET'], access: 'user', required_role: 'user' },
      { path: '/api/v1/corpora/register', methods: ['POST'], mutates: true, access: 'admin', required_role: 'admin' },
      { path: '/api/v1/corpora/{corpus}/activate', methods: ['POST'], mutates: true, access: 'user', required_role: 'user' },
      { path: '/api/v1/corpora/{corpus}/capabilities', methods: ['GET'], access: 'user', required_role: 'user' },
      { path: '/api/v1/corpora/{corpus}/registration', methods: ['DELETE'], mutates: true, access: 'admin', required_role: 'admin' },
    ],
    'corpus.import': [
      { path: '/api/v1/corpora/import-methods', methods: ['GET'], access: 'admin', required_role: 'admin' },
      { path: '/api/v1/corpora/import-preflight', methods: ['POST'], access: 'admin', required_role: 'admin' },
      { path: '/api/v1/corpora/imports', methods: ['GET', 'POST'], mutates: true, access: 'admin', required_role: 'admin' },
      { path: '/api/v1/corpora/imports/{job_id}', methods: ['GET'], access: 'admin', required_role: 'admin' },
      { path: '/api/v1/corpora/imports/{job_id}/cancel', methods: ['POST'], mutates: true, access: 'admin', required_role: 'admin' },
      { path: '/api/v1/corpora/imports/{job_id}/reports', methods: ['GET'], access: 'admin', required_role: 'admin' },
      { path: '/api/v1/corpora/{corpus}/build-report', methods: ['GET'], access: 'admin', required_role: 'admin' },
    ],
    'corpus.alignment_parallel': [
      { path: '/api/v1/analysis/kwic_parallel', methods: ['POST'], access: 'user', required_role: 'user' },
    ],
    'admin.system_operations': [
      { path: '/api/v1/system/info', methods: ['GET'], access: 'admin', required_role: 'admin' },
    ],
  }
  const routes = routesByCapability[id] ?? [{ path: `/api/v1/${id}`, methods: ['GET'], access: 'user', required_role: 'user' }]
  const isAlignment = id === 'corpus.alignment_parallel'
  const operationSpecs: Record<string, Array<{ id: string; label: string; path: string; methods: string[] }>> = {
    'corpus.catalogue': [
      { id: 'corpus.catalogue.list', label: 'Korpora listen', path: '/api/v1/corpora', methods: ['GET'] },
      { id: 'corpus.catalogue.register', label: 'Korpus registrieren', path: '/api/v1/corpora/register', methods: ['POST'] },
      { id: 'corpus.catalogue.activate', label: 'Korpus aktivieren', path: '/api/v1/corpora/{corpus}/activate', methods: ['POST'] },
      { id: 'corpus.catalogue.capabilities', label: 'Korpusfähigkeiten laden', path: '/api/v1/corpora/{corpus}/capabilities', methods: ['GET'] },
      { id: 'corpus.catalogue.unregister', label: 'Korpusregistrierung entfernen', path: '/api/v1/corpora/{corpus}/registration', methods: ['DELETE'] },
    ],
    'corpus.import': [
      { id: 'corpus.import.methods', label: 'Importmethoden laden', path: '/api/v1/corpora/import-methods', methods: ['GET'] },
      { id: 'corpus.import.preflight', label: 'Import-Preflight ausführen', path: '/api/v1/corpora/import-preflight', methods: ['POST'] },
      { id: 'corpus.import.jobs_list', label: 'Importjobs listen', path: '/api/v1/corpora/imports', methods: ['GET'] },
      { id: 'corpus.import.start', label: 'Importjob starten', path: '/api/v1/corpora/imports', methods: ['POST'] },
      { id: 'corpus.import.job_status', label: 'Importjob-Status laden', path: '/api/v1/corpora/imports/{job_id}', methods: ['GET'] },
      { id: 'corpus.import.job_cancel', label: 'Importjob abbrechen', path: '/api/v1/corpora/imports/{job_id}/cancel', methods: ['POST'] },
      { id: 'corpus.import.job_reports', label: 'Importjob-Reports laden', path: '/api/v1/corpora/imports/{job_id}/reports', methods: ['GET'] },
      { id: 'corpus.import.build_report', label: 'Korpus-Build-Report laden', path: '/api/v1/corpora/{corpus}/build-report', methods: ['GET'] },
    ],
    'corpus.alignment_parallel': [
      { id: 'corpus.alignment_parallel.parallel_kwic', label: 'Parallel-KWIC laden', path: '/api/v1/analysis/kwic_parallel', methods: ['POST'] },
    ],
    'admin.system_operations': [
      { id: 'admin.system_operations.info', label: 'Systeminformationen laden', path: '/api/v1/system/info', methods: ['GET'] },
    ],
  }
  const operationRoute = (path: string, methods: string[]) => {
    const route = routes.find((item) => item.path === path)
    return {
      path,
      methods,
      mutates: methods.some((method) => method !== 'GET'),
      requires_corpus_features: isAlignment ? ['alignment.parallel_kwic'] : [],
      access: route?.access,
      required_role: route?.required_role,
      transport: 'http',
      route_class: route?.access === 'admin' ? 'admin_surface' : 'product_surface',
    }
  }
  const surfaceSlotForOperation = (operationId: string) => ({
    'corpus.import.jobs_list': 'corpus.import.jobs.list',
    'corpus.import.job_status': 'corpus.import.job.status',
    'corpus.import.job_cancel': 'corpus.import.job.cancel',
    'corpus.import.job_reports': 'corpus.import.job.reports',
  }[operationId] ?? operationId)
  return {
    id,
    title,
    area,
    maturity: 'guarded',
    visibility: 'first_class_ui',
    backend_routes: routes.map((route) => route.path),
    backend_route_descriptors: routes.map((route) => ({
      path: route.path,
      methods: route.methods,
      mutates: Boolean(route.mutates),
      requires_corpus_features: isAlignment ? ['alignment.parallel_kwic'] : [],
      access: route.access,
      required_role: route.required_role,
      transport: 'http',
      route_class: route.access === 'admin' ? 'admin_surface' : 'product_surface',
    })),
    operations: (operationSpecs[id] ?? []).map((spec) => ({
      id: spec.id,
      capability_id: id,
      label: spec.label,
      description: '',
      route: operationRoute(spec.path, spec.methods),
      effects: spec.methods.some((method) => method !== 'GET') ? ['write'] : ['read'],
      handler_key: spec.id.split('.').at(-1) ?? spec.id,
      surface_slot: surfaceSlotForOperation(spec.id),
      priority: 100,
    })),
    frontend_evidence: [],
    action_types: [],
    copilot_tools: [],
    preconditions: id === 'corpus.import' ? ['Admin role is required'] : [],
    requires_corpus_features: isAlignment ? ['alignment.parallel_kwic'] : [],
    limits: id === 'corpus.import'
      ? [
          'Import jobs expose local paths and logs',
          'Import job history is runtime-bound and not durable across backend restarts or multi-process workers',
          'First-class UI covers generic Parquet/VRT imports, unpaired CSV/JSONL/plaintext/HF ingestion adapters, and externally prealigned Pair-Key imports with preflight and job monitoring.',
          'HF dataset imports download data only at import time and keep trust_remote_code hard-disabled; the preflight validates the descriptor without network access.',
        ]
      : [],
  }
}

function productContract() {
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
      capability('corpus.catalogue', 'Corpus catalogue'),
      capability('corpus.import', 'Observable corpus import'),
      capability('corpus.alignment_parallel', 'Parallel corpus alignment helpers'),
      capability('admin.system_operations', 'System operations', 'admin'),
      capability('analysis.frequency', 'Frequency lists', 'analysis'),
    ],
  }
}

function productContractWithHiddenImport() {
  const contract = productContract()
  return {
    ...contract,
    capabilities: contract.capabilities.map((item) => item.id === 'corpus.import'
      ? { ...item, visibility: 'hidden_experimental', maturity: 'experimental' }
      : item),
  }
}

describe('CorpusManagerContent capability contract surface', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    getProductCapabilities.mockResolvedValue(productContract())
    getAuthSession.mockResolvedValue({
      schema_version: 'auth-session-v1',
      authenticated: true,
      token_present: true,
      username: 'admin',
      role: 'admin',
      effective_role: 'admin',
      rbac_enabled: true,
      security_mode: 'release',
      release_mode: true,
      unsafe_token_transport: false,
      dev_token_available: false,
      can_access_all_roles: false,
    })
    getCorpora.mockResolvedValue({
      corpora: [corpusSummary('demo', true), corpusSummary('parallel-demo')],
      count: 2,
    })
    getCorpusCapabilities.mockImplementation(async (name: string) => corpusSummary(name, name === 'demo'))
    getCorpusImportReports.mockResolvedValue({
      schema_version: 'corpus-import-reports-v1',
      reports: {
        build_report: { data: { token_count: 12 } },
      },
    })
    getCorpusImportMethods.mockResolvedValue([
      {
        schema_version: 'corpus-import-method-v1',
        method: 'parquet',
        label: 'Parquet',
        description: 'Serverseitiger Parquet-Pfad',
        option_keys: ['spacy_model', 'batch_size'],
        input: {
          kind: 'server_file',
          extensions: ['.parquet'],
          accepts_directories: false,
          path_hint: '/data/imports/korpus.parquet',
        },
        availability: {
          status: 'available',
          script: 'build_fast_index_from_parquet.py',
          script_path: '/repo/scripts/jobs/build_fast_index_from_parquet.py',
          subcommand: [],
        },
        option_specs: [
          { key: 'spacy_model', label: 'spaCy-Modell', type: 'string', required: false, default: 'de_core_news_md', choices: [], aliases: [] },
          { key: 'batch_size', label: 'Batchgröße', type: 'integer', required: false, default: 0, choices: [], aliases: [] },
        ],
        expected_columns: [{ key: 'input_text', label: 'input_text', required: true }],
        output: {
          paired: false,
          paired_data_dependent: true,
          pairing_kind: 'row_metadata_if_present',
          emitted_features: ['kwic_ready'],
          guarantees: ['vollständiger Indexbau oder fehlgeschlagener Job'],
          limitations: ['Parquet-Spaltensemantik wird nicht als Forschungsdesign validiert.'],
        },
        emitted_features: ['kwic_ready'],
        reports: [{ key: 'build_report', label: 'Build-Report' }],
      },
      {
        schema_version: 'corpus-import-method-v1',
        method: 'vrt',
        label: 'VRT/XML',
        description: 'VRT-Strukturen mit optionalem Diagnostiklauf',
        input: {
          kind: 'server_file',
          extensions: ['.vrt', '.xml'],
          accepts_directories: false,
          path_hint: '/data/imports/korpus.vrt',
        },
        availability: {
          status: 'available',
          script: 'build_fast_index_from_vrt.py',
          script_path: '/repo/scripts/jobs/build_fast_index_from_vrt.py',
          subcommand: [],
        },
        option_keys: ['inspect', 'inspect_docs'],
        option_specs: [
          { key: 'inspect', label: 'Nur inspizieren', type: 'boolean', required: false, default: false, choices: [], aliases: [] },
          { key: 'inspect_docs', label: 'Inspect-Dokumente', type: 'integer', required: false, default: 3, choices: [], aliases: [] },
        ],
        expected_columns: [],
        output: {
          paired: false,
          pairing_kind: 'none',
          emitted_features: ['vrt_import_report'],
          guarantees: ['VRT-Struktur wird geparst und dokumentiert.'],
          limitations: ['Inspect erzeugt Diagnostik statt fertigem Index.'],
        },
        emitted_features: ['vrt_import_report'],
        reports: [{ key: 'vrt_import_report', label: 'VRT-Import-Report' }],
      },
      {
        schema_version: 'corpus-import-method-v1',
        method: 'prealigned_csv',
        label: 'Pre-grouped CSV',
        description: 'Extern gepaarte CSV-Daten',
        ui_workflow: {
          status: 'first_class',
          label: 'First-class Import',
          reason: 'Prealigned-Dateien laufen über Methode, Preflight und Jobmonitoring.',
        },
        input: {
          kind: 'server_file',
          extensions: ['.csv', '.tsv'],
          accepts_directories: false,
          path_hint: '/data/imports/paired.csv',
        },
        option_keys: ['text_column', 'pair_key_column', 'reject_policy'],
        option_specs: [
          { key: 'text_column', label: 'Textspalte', type: 'string', required: true, default: 'text', choices: [], aliases: [] },
          { key: 'pair_key_column', label: 'Pair-Key-Spalte', type: 'string', required: true, default: 'pair_id', choices: [], aliases: [] },
          { key: 'reject_policy', label: 'Reject-Policy', type: 'choice', required: false, default: 'collect', choices: ['collect', 'fail_fast'], aliases: [] },
        ],
        expected_columns: [
          { key: 'text', required: true, configured_by: 'text_column' },
          { key: 'pair_id', required: true, configured_by: 'pair_key_column' },
        ],
        output: {
          paired: true,
          pairing_kind: 'external_pair_keys',
          emitted_features: ['pair_metadata', 'reject_summary'],
          guarantees: ['Pair-Key/Pair-Role-Struktur wird geprüft.'],
          limitations: ['Der Import prüft Paarstruktur, aber keine inhaltliche Alignmentqualität.'],
        },
        emitted_features: ['pair_metadata', 'reject_summary'],
        reports: [{ key: 'reject_report', label: 'Reject-Report' }],
      },
      {
        schema_version: 'corpus-import-method-v1',
        method: 'research_bundle',
        label: 'Research Bundle',
        description: 'Synthetische generische Importmethode für UI-Vertragstests',
        input: {
          kind: 'server_file',
          extensions: ['.bundle'],
          accepts_directories: false,
          path_hint: '/data/imports/research.bundle',
        },
        option_keys: ['quality_level'],
        option_specs: [
          {
            key: 'quality_level',
            label: 'Qualitätsstufe',
            type: 'choice',
            required: false,
            default: 1,
            choices: [
              { value: 1, label: 'schnell', description: 'Schneller Import mit knapper Validierung.' },
              { value: 3, label: 'präzise', description: 'Gründlichere Validierung vor dem Build.' },
            ],
            aliases: [],
          },
        ],
        expected_columns: [{ key: 'payload', required: true }],
        output: {
          paired: false,
          pairing_kind: 'none',
          emitted_features: ['research_payload'],
          guarantees: ['Synthetischer Contract ohne methodenspezifische UI-Branch.'],
          limitations: [],
        },
        emitted_features: ['research_payload'],
        reports: [{ key: 'build_report', label: 'Build-Report' }],
      },
      {
        schema_version: 'corpus-import-method-v1',
        method: 'research_directory',
        label: 'Research Directory',
        description: 'Synthetische Verzeichnis-Importmethode für Eingabetests',
        input: {
          kind: 'server_directory',
          extensions: [],
          accepts_directories: true,
          path_hint: '/data/imports/research-dir',
        },
        option_keys: [],
        option_specs: [],
        expected_columns: [],
        output: {
          paired: false,
          pairing_kind: 'none',
          emitted_features: ['research_directory_payload'],
          guarantees: ['Verzeichnis wird als serverseitige Quelle behandelt.'],
          limitations: [],
        },
        emitted_features: ['research_directory_payload'],
        reports: [{ key: 'build_report', label: 'Build-Report' }],
      },
      ...corpusImportAdapterMethodDescriptors(),
    ])
    listCorpusImportJobs.mockResolvedValue([
      {
        job_id: 'job-retained-1',
        status: 'running',
        progress: 35,
        stage: 'building',
        started_at: 1770883200,
        stdout_tail: 'indexed 12 tokens',
        stderr_tail: '',
        stdout_truncated: false,
        created_at: 1770883100,
        urls: {
          status: '/api/v1/corpora/imports/job-retained-1',
          reports: '/api/v1/corpora/imports/job-retained-1/reports',
        },
        method: 'parquet',
        input_path: '/data/imports/retained.parquet',
        target_name: 'retained-demo',
        target_path: '/data/corpora/retained-demo',
        staging_path: '/tmp/candyconc-imports/job-retained-1',
        activate_on_success: true,
      },
    ])
    registerCorpus.mockResolvedValue(corpusSummary('registered-index', true))
    unregisterCorpus.mockResolvedValue({ status: 'ok', path: '/corpora/parallel-demo' })
    getCorpusBuildReport.mockResolvedValue({
      schema_version: 'corpus-build-report-v1',
      corpus: 'demo',
      reports: {
        build_report: { data: { token_count: 12 } },
        manifest: { data: { import_mode: 'parquet' } },
      },
      build_report: { data: { token_count: 12 } },
      manifest: { data: { import_mode: 'parquet' } },
    })
    createCorpusImportJob.mockResolvedValue({
      job_id: 'job-created-1',
      status: 'queued',
      progress: 0,
      method: 'prealigned_csv',
      target_name: 'new-demo',
    })
    preflightCorpusImport.mockImplementation(async (payload: { method: string; input_path: string }) => ({
      schema_version: 'corpus-import-preflight-v1',
      method: payload.method,
      input_path: payload.input_path,
      status: payload.method === 'prealigned_csv' ? 'warning' : 'pass',
      ok: true,
      blocking: false,
      max_severity: payload.method === 'prealigned_csv' ? 'warning' : 'info',
      summary: payload.method === 'prealigned_csv' ? 'Preflight mit Warnungen abgeschlossen.' : 'Preflight erfolgreich.',
      errors: [],
      warnings: payload.method === 'prealigned_csv' ? ['Reject-Policy collect kann verworfene Zeilen sammeln.'] : [],
      checks: [
        {
          key: 'schema_read',
          label: 'Spaltenprüfung',
          status: 'pass',
          severity: 'info',
          blocking: false,
          message: 'Spalten erkannt.',
          evidence: {},
        },
      ],
      evidence: {
        path: payload.input_path,
        exists: true,
        is_file: true,
        suffix: payload.input_path.slice(payload.input_path.lastIndexOf('.')),
        columns: payload.method === 'research_bundle' ? ['payload'] : ['text', 'pair_id', 'pair_role'],
      },
    }))
  })

  afterEach(() => {
    useCorpusImportsStore().stopPolling()
  })

  it('shows the corpus import workflow without product-contract diagnostic panels', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Import-Workflow')
    expect(wrapper.text()).toContain('Quelle → Preflight → Evidenz → Import')
    expect(wrapper.text()).toContain('Serverpfad importieren')
    expect(wrapper.text()).toContain('Vorhandenen Index registrieren')
    expect(wrapper.text()).toContain('Importjobs')
    expect(wrapper.text()).not.toContain('Frequency lists')
    expect(wrapper.text()).not.toContain('Backend-Operationen im Workflow')
    expect(wrapper.text()).not.toContain('corpus.import.methods')
    expect(wrapper.text()).not.toContain('POST /api/v1/analysis/kwic_parallel')
    expect(wrapper.text()).toContain('retained-demo')
    expect(wrapper.text()).toContain('Importmethoden')
    expect(wrapper.text()).toContain('9 Methode(n)')
    expect(wrapper.text()).toContain('VRT/XML')
    expect(wrapper.text()).toContain('Research Bundle')
    expect(wrapper.text()).toContain('Research Directory')
    expect(wrapper.text()).toContain('Plaintext (Ordner/Datei)')
    expect(wrapper.text()).toContain('CSV/TSV')
    expect(wrapper.text()).toContain('JSONL')
    expect(wrapper.text()).toContain('HuggingFace-Dataset')
    expect(wrapper.text()).toContain('spaCy-Modell')
    expect(wrapper.text()).toContain('Builder verfügbar: build_fast_index_from_parquet.py')
    expect(wrapper.text()).not.toContain('Builder-Pfad: /repo/scripts/jobs/build_fast_index_from_parquet.py')
    expect(wrapper.text()).toContain('Erwartete Evidenzspalten')
    expect(wrapper.text()).toContain('Paarmetadaten')
    expect(wrapper.text()).toContain('vollständiger Indexbau oder fehlgeschlagener Job')
    expect(wrapper.text()).toContain('automatische Aktualisierung aktiv')
    expect(wrapper.text()).toContain('Job-Provenienz')
    expect(wrapper.text()).toContain('/data/imports/retained.parquet')
    expect(wrapper.text()).toContain('/data/corpora/retained-demo')
    expect(wrapper.text()).toContain('/tmp/candyconc-imports/job-retained-1')
    expect(wrapper.text()).toContain('Nach Erfolg aktivieren')
    expect(wrapper.text()).toContain('runtime-bound')
    expect(wrapper.text()).toContain('nicht über Backend-Neustart oder Mehrprozess-Worker durable')
    expect(wrapper.text()).toContain('unpaired CSV/JSONL/plaintext/HF ingestion adapters')
    expect(wrapper.text()).not.toContain('not first-class UI import methods')
    expect(wrapper.text()).toContain('höchstens 128 Jobs')
    expect(wrapper.text()).toContain('Reports bis 2 MB je Report')
    expect(wrapper.text()).toContain('Laufprotokoll')
    expect(wrapper.text()).toContain('indexed 12 tokens')
    expect(wrapper.text()).not.toContain('/api/v1/corpora/imports/job-retained-1/reports')
  })

  it('names a corpus by its display name and activates it by its identifier', async () => {
    // The corpus pinned with CANDYCONC_INDEX_PATH is "default" for the routes.
    // The server sends its directory name as display_name (erprobung B4).
    getCorpora.mockResolvedValueOnce({
      corpora: [corpusSummary('default', false, { display_name: 'sotu_en' })],
      count: 1,
    })
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const titles = wrapper.findAll('.corpus-card .corpus-name strong').map((node) => node.text())
    expect(titles).toContain('sotu_en')
    expect(titles).not.toContain('default')
  })

  it('keeps import polling alive after the manager panel closes', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const importStore = useCorpusImportsStore()
    expect(importStore.hasRunningJobs).toBe(true)
    expect(importStore.isPolling).toBe(true)

    wrapper.unmount()

    expect(importStore.isPolling).toBe(true)
  })

  it('exposes register-existing and build-report backend routes as first-class actions', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('input[placeholder="/data/corpora/mein_korpus_index"]').setValue('/indexes/registered-index')
    await wrapper.findAll('button').find((button) => button.text().includes('Registrieren'))?.trigger('click')
    await flushPromises()
    expect(registerCorpus).toHaveBeenCalledWith('/indexes/registered-index', false)

    await wrapper.findAll('button').find((button) => button.text().includes('Build-Report'))?.trigger('click')
    await flushPromises()
    expect(getCorpusBuildReport).toHaveBeenCalledWith('demo')
    expect(wrapper.text()).toContain('Build-Report und Manifest')
    expect(wrapper.text()).toContain('Importmodus')
    expect(wrapper.text()).toContain('parquet')
  })

  it('does not call import endpoints when corpus.import is hidden by the product contract', async () => {
    getProductCapabilities.mockResolvedValueOnce(productContractWithHiddenImport())

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    expect(getCorpusImportMethods).not.toHaveBeenCalled()
    expect(listCorpusImportJobs).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Korpusimport ist im Fähigkeitskatalog nicht als Oberfläche freigegeben')
    expect(wrapper.find('section.job-list').exists()).toBe(false)
  })

  it('keeps admin corpus actions visible as context but locked for non-admin sessions', async () => {
    getAuthSession.mockResolvedValueOnce({
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

    const pinia = createPinia()
    setActivePinia(pinia)
    const importStore = useCorpusImportsStore()
    importStore.applyProgress({
      job_id: 'stale-admin-job',
      status: 'running',
      progress: 50,
      method: 'parquet',
      target_name: 'stale-admin-target',
      input_path: '/sensitive/admin/import.parquet',
      stdout_tail: 'sensitive import log',
      stderr_tail: '',
      stdout_truncated: false,
    })

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [pinia] } })
    await flushPromises()

    expect(getCorpora).toHaveBeenCalled()
    expect(getCorpusImportMethods).not.toHaveBeenCalled()
    expect(listCorpusImportJobs).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Korpusimport benötigt mindestens Rolle Admin')
    expect(wrapper.text()).toContain('Importjobs')
    expect(wrapper.text()).toContain('Importjob-Monitor benötigt mindestens Rolle Admin')
    expect(wrapper.text()).toContain('Indexregistrierung benötigt mindestens Rolle Admin')
    expect(wrapper.find('input[placeholder="/data/corpora/mein_korpus_index"]').attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').find((button) => button.text().includes('Build-Report'))?.attributes('disabled')).toBeDefined()
    expect(wrapper.findAll('button').find((button) => button.text().includes('Aus Registry entfernen'))?.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).not.toContain('/sensitive/admin/import.parquet')
    expect(wrapper.text()).not.toContain('sensitive import log')
    expect(importStore.recentJobs).toEqual([])
  })

  it('gates catalogue activation and unregister by backend corpus state', async () => {
    getCorpora.mockResolvedValueOnce({
      corpora: [
        corpusSummary('demo', true),
        corpusSummary('broken-demo', false, {
          status: 'incomplete',
          status_reason: 'Manifest fehlt',
          source: 'managed',
        }),
      ],
      count: 2,
    })

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const brokenCard = wrapper.findAll('.corpus-card').find((card) => card.text().includes('broken-demo'))
    expect(brokenCard?.exists()).toBe(true)
    expect(brokenCard?.text()).toContain('unvollständig')
    expect(brokenCard?.text()).toContain('Manifest fehlt')

    const activateButton = brokenCard?.findAll('button').find((button) => button.text().includes('Aktivieren'))
    expect(activateButton?.attributes('disabled')).toBeDefined()
    expect(activateButton?.attributes('title')).toContain('Nur bereite Korpora können aktiviert werden')

    const unregisterButton = brokenCard?.findAll('button').find((button) => button.text().includes('Aus Registry entfernen'))
    expect(unregisterButton?.attributes('disabled')).toBeDefined()
    expect(unregisterButton?.attributes('title')).toContain('Nur Registry-Einträge')
  })

  it('requires an inline acknowledgement before a persisted partial import can become active', async () => {
    getCorpora.mockResolvedValueOnce({
      corpora: [
        corpusSummary('demo', true),
        corpusSummary('partial-demo', false, {
          partial_input: true,
          rejected_rows: 2,
          import_warnings: ['2 Eingabezeilen wurden verworfen.'],
        }),
      ],
      count: 2,
    })

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const partialCard = wrapper.findAll('.corpus-card').find((card) => card.text().includes('partial-demo'))
    const activateButton = partialCard?.findAll('button').find((button) => button.text().includes('Aktivieren'))
    expect(partialCard?.text()).toContain('Teilimport: erst prüfen, dann bewusst aktivieren')
    expect(partialCard?.text()).toContain('2 Eingabezeilen wurden verworfen.')
    expect(activateButton?.attributes('disabled')).toBeDefined()
    expect(activateButton?.attributes('title')).toContain('Teilimport')

    await partialCard?.find('[data-testid="partial-import-ack-partial-demo"]').setValue(true)
    await flushPromises()

    expect(activateButton?.attributes('disabled')).toBeUndefined()
    await activateButton?.trigger('click')
    await flushPromises()
    expect(partialCard?.text()).toContain('aktiv')
  })

  it('uses one central ProductOperation confirmation before unregistering a corpus', async () => {
    const confirmMock = vi.mocked(window.confirm)
    confirmMock.mockClear()
    confirmMock.mockReturnValueOnce(false)

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const parallelCard = wrapper.findAll('.corpus-card').find((card) => card.text().includes('parallel-demo'))
    const unregisterButton = parallelCard?.findAll('button').find((button) => button.text().includes('Aus Registry entfernen'))
    expect(unregisterButton?.exists()).toBe(true)

    await unregisterButton?.trigger('click')
    await flushPromises()

    expect(confirmMock).toHaveBeenCalledTimes(1)
    expect(confirmMock.mock.calls[0]?.[0]).not.toContain('corpus.catalogue.unregister')
    expect(confirmMock.mock.calls[0]?.[0]).toContain('Korpusregistrierung entfernen wirklich ausführen?')
    expect(confirmMock.mock.calls[0]?.[0]).toContain('Ziel: parallel-demo')
    expect(unregisterCorpus).not.toHaveBeenCalled()

    confirmMock.mockClear()
    confirmMock.mockReturnValueOnce(true)
    await unregisterButton?.trigger('click')
    await flushPromises()

    expect(confirmMock).toHaveBeenCalledTimes(1)
    expect(unregisterCorpus).toHaveBeenCalledWith('parallel-demo')
  })

  it('keeps the import job monitor visible when no import jobs are known', async () => {
    listCorpusImportJobs.mockResolvedValueOnce([])

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    expect(listCorpusImportJobs).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Importjobs')
    expect(wrapper.text()).toContain('Keine Importjobs bekannt.')
    expect(wrapper.text()).toContain('Fortschritt')
    expect(wrapper.text()).toContain('Reports')
    expect(wrapper.text()).toContain('nicht über Backend-Neustart oder Mehrprozess-Worker durable')
  })

  it('does not offer a false cancellation while the completed import is publishing', async () => {
    listCorpusImportJobs.mockResolvedValueOnce([
      {
        job_id: 'job-publishing-1',
        status: 'running',
        progress: 99,
        stage: 'publishing',
        message: 'publishing corpus',
        cancellable: false,
        finalization_started: true,
        target_name: 'publishing-demo',
      },
    ])

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const cancelButton = wrapper.findAll('button').find((button) => button.text().includes('Abbrechen'))
    expect(cancelButton?.attributes('disabled')).toBeDefined()
    expect(cancelButton?.attributes('title')).toContain('Importabschluss läuft')
  })

  it('guides completed import jobs into build-report and capability verification', async () => {
    listCorpusImportJobs.mockResolvedValueOnce([
      {
        job_id: 'job-done-1',
        status: 'done',
        progress: 100,
        stage: 'finished',
        started_at: 1770883200,
        finished_at: 1770883300,
        stdout_tail: 'done',
        stderr_tail: '',
        stdout_truncated: false,
        urls: {
          status: '/api/v1/corpora/imports/job-done-1',
          reports: '/api/v1/corpora/imports/job-done-1/reports',
        },
        method: 'prealigned_csv',
        target_name: 'finished-demo',
      },
    ])

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    expect(wrapper.find('[aria-label="Post-Import-Handoff"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Post-Import-Evidenz')
    // Der Satz "Naechster methodischer Schritt: Build-Report lesen, ..."
    // ist am 2026-08-31 ersatzlos entfallen. Er rahmte als Schrittfolge,
    // was daneben als Zustand steht: die Warnung bei jobPartialInput und
    // die Statuszeile. Geprueft wird jetzt die Zustandsinformation.
    expect(wrapper.text()).not.toContain('Nächster methodischer Schritt')
    expect(wrapper.text()).toContain('finished-demo')

    await wrapper.findAll('button').find((button) => button.text().includes('Build-Report prüfen'))?.trigger('click')
    await flushPromises()
    expect(getCorpusBuildReport).toHaveBeenCalledWith('finished-demo')
    expect(wrapper.text()).toContain('Build-Report des Zielkorpus')

    await wrapper.findAll('button').find((button) => button.text().includes('Fähigkeiten des Zielkorpus prüfen'))?.trigger('click')
    await flushPromises()
    expect(getCorpusCapabilities).toHaveBeenCalledWith('finished-demo')

    await wrapper.findAll('button').find((button) => button.text().includes('Zielkorpus aktivieren'))?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('aktiv')
  })

  it('renders canonical reports for retained terminal job snapshots', async () => {
    getCorpusImportReports.mockClear()
    getCorpusImportReports.mockResolvedValueOnce({
      schema_version: 'corpus-import-reports-v1',
      reports: {
        manifest: {
          import_mode: 'prealigned_csv',
          token_count: 99,
          doc_count: 6,
          paired: true,
          pair_axes: ['pair_id'],
        },
        reject_report: {
          rejected_rows: 2,
          total_rows: 48,
          reject_policy: 'collect',
        },
      },
    })
    listCorpusImportJobs.mockResolvedValueOnce([
      {
        job_id: 'job-done-with-reports',
        status: 'done',
        progress: 100,
        stage: 'finished',
        stdout_tail: 'done',
        stderr_tail: '',
        stdout_truncated: false,
        urls: {
          status: '/api/v1/corpora/imports/job-done-with-reports',
          reports: '/api/v1/corpora/imports/job-done-with-reports/reports',
        },
        method: 'prealigned_csv',
        target_name: 'finished-demo',
        reports: {
          manifest: {
            data: {
              import_mode: 'prealigned_csv',
              token_count: 99,
              doc_count: 6,
              paired: true,
              pair_axes: ['pair_id'],
            },
          },
          reject_report: {
            rejected_rows: 2,
            total_rows: 48,
            reject_policy: 'collect',
          },
        },
      },
    ])

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    expect(getCorpusImportReports).toHaveBeenCalledWith('job-done-with-reports')
    expect(wrapper.text()).toContain('Geladene Reports')
    expect(wrapper.text()).toContain('Index-Manifest')
    expect(wrapper.text()).toContain('Importmodus')
    expect(wrapper.text()).toContain('prealigned_csv')
    expect(wrapper.text()).toContain('Paarmetadaten')
    expect(wrapper.text()).toContain('Reject-Report')
    expect(wrapper.text()).toContain('Verworfene Zeilen')
    expect(wrapper.text()).toContain('Teilimport')
    expect(wrapper.text()).toContain('Dieser Job ist ein Teilimport')
  })

  it('renders typed import specs generically and submits coerced options', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('select').setValue('prealigned_csv')
    await flushPromises()

    expect(wrapper.text()).toContain('Pre-grouped CSV')
    expect(wrapper.text()).toContain('Pair-Key-Spalte')
    expect(wrapper.text()).toContain('Reject-Policy')
    expect(wrapper.text()).toContain('First-class Import')
    expect(wrapper.text()).toContain('Prealigned-Dateien laufen über Methode, Preflight und Jobmonitoring.')
    expect(wrapper.text()).toContain('Pair-Key/Pair-Role-Struktur wird geprüft')
    expect(wrapper.text()).toContain('keine inhaltliche Alignmentqualität')

    await wrapper.find('input[placeholder="/data/imports/paired.csv"]').setValue('/data/imports/paired.csv')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('new-demo')
    const rejectPolicySelect = wrapper.findAll('select').find((select) => select.text().includes('fail_fast'))
    await rejectPolicySelect?.setValue('fail_fast')

    expect(wrapper.text()).toContain('Import-Preflight fehlt')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Import-Preflight: Warnungen')
    expect(wrapper.text()).toContain('Quelle')
    expect(wrapper.text()).toContain('Spalten/Felder (3)')
    expect(wrapper.text()).toContain('text')
    expect(wrapper.text()).toContain('pair_id')
    expect(wrapper.text()).toContain('pair_role')
    expect(createCorpusImportJob).not.toHaveBeenCalled()

    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(preflightCorpusImport).toHaveBeenCalledWith({
      method: 'prealigned_csv',
      input_path: '/data/imports/paired.csv',
      target_name: 'new-demo',
      activate_on_success: false,
      reject_policy: 'fail_fast',
    })
    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'prealigned_csv',
      input_path: '/data/imports/paired.csv',
      target_name: 'new-demo',
      activate_on_success: false,
      reject_policy: 'fail_fast',
    })
  })

  it('shows expert-only import contracts but blocks first-class import start', async () => {
    getCorpusImportMethods.mockResolvedValueOnce([
      {
        schema_version: 'corpus-import-method-v1',
        method: 'embed_alignment',
        label: 'Embedding Alignment',
        description: 'Satzalignment mit Embedding-/Hybrid-Kosten',
        ui_workflow: {
          status: 'expert_api',
          label: 'Expert/API',
          reason: 'Sentence-Embedding-/Hybrid-Alignment braucht einen kuratierten CLI-Build.',
        },
        input: {
          kind: 'server_file',
          extensions: ['.parquet'],
          accepts_directories: false,
          path_hint: '/data/imports/alignment.parquet',
        },
        option_keys: [],
        option_specs: [],
        expected_columns: [],
        output: {
          paired: true,
          pairing_kind: 'sentence_embedding_alignment',
          emitted_features: ['pair_metadata'],
          guarantees: [],
          limitations: ['Nicht first-class importierbar.'],
        },
        emitted_features: ['pair_metadata'],
        reports: [],
      },
    ])
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    expect(wrapper.text()).toContain('Embedding Alignment')
    expect(wrapper.text()).toContain('Expert/API')
    expect(wrapper.text()).toContain('Sentence-Embedding-/Hybrid-Alignment')

    await wrapper.find('input[placeholder="/data/imports/alignment.parquet"]').setValue('/data/imports/alignment.parquet')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('aligned-demo')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Import-Preflight: bestanden')
    expect(wrapper.text()).toContain('nicht über den First-class-Import gestartet')
    expect(wrapper.find('[data-testid="corpus-import-start-button"]').attributes('disabled')).toBeDefined()
    expect(createCorpusImportJob).not.toHaveBeenCalled()
  })

  it('uses the backend-compatible input-stem default when target name is empty', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('input[placeholder="/data/imports/korpus.parquet"]').setValue('/data/imports/stem-demo.parquet')
    await flushPromises()

    expect(wrapper.text()).toContain('Aktuell abgeleitet: stem-demo')

    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'parquet',
      input_path: '/data/imports/stem-demo.parquet',
      target_name: 'stem-demo',
      activate_on_success: false,
    })
  })

  it('labels VRT inspect mode as a diagnostic run instead of a normal index import', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('[data-testid="corpus-import-method"]').setValue('vrt')
    await flushPromises()

    const inspectField = wrapper.findAll('.option-field').find((field) =>
      field.text().includes('Nur inspizieren')
    )
    expect(inspectField?.exists()).toBe(true)
    await inspectField?.find('input[type="checkbox"]').setValue(true)
    await flushPromises()

    expect(wrapper.text()).toContain('VRT-Option „Nur inspizieren“ ist aktiv')
    expect(wrapper.text()).toContain('Strukturdiagnostik')
    expect(wrapper.text()).toContain('Diagnostikmodus ohne Indexbau')
    expect(wrapper.find('[data-testid="corpus-import-start-button"]').text()).toContain('kein Importstart')
    expect(wrapper.find('[data-testid="corpus-import-start-button"]').attributes('disabled')).toBeDefined()

    await wrapper.find('input[type="checkbox"]').setValue(true)
    await flushPromises()

    expect(wrapper.text()).toContain('darf nicht automatisch als Arbeitskorpus aktiviert werden')
  })

  it('renders choice import options as a single select control', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('[data-testid="corpus-import-method"]').setValue('prealigned_csv')
    await flushPromises()

    const rejectPolicyField = wrapper.findAll('.option-field').find((field) =>
      field.text().includes('Reject-Policy')
    )
    expect(rejectPolicyField?.exists()).toBe(true)
    expect(rejectPolicyField?.findAll('select')).toHaveLength(1)
    expect(rejectPolicyField?.findAll('input[type="text"]')).toHaveLength(0)
  })

  it('does not start imports when preflight returns a blocking result', async () => {
    preflightCorpusImport.mockResolvedValueOnce({
      schema_version: 'corpus-import-preflight-v1',
      method: 'parquet',
      input_path: '/data/imports/broken.txt',
      status: 'error',
      ok: false,
      blocking: true,
      max_severity: 'error',
      summary: 'Preflight blockiert.',
      errors: ['Dateiendung passt nicht zum Import-Contract.'],
      warnings: [],
      checks: [
        {
          key: 'extension',
          label: 'Dateiendung',
          status: 'fail',
          severity: 'error',
          blocking: true,
          message: 'Erwartet .parquet.',
          evidence: {},
        },
      ],
      evidence: {
        path: '/data/imports/broken.txt',
        exists: true,
        is_file: true,
        suffix: '.txt',
        columns: [],
      },
    })

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('input[placeholder="/data/imports/korpus.parquet"]').setValue('/data/imports/broken.txt')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('blocked-demo')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Import-Preflight: blockiert')
    expect(wrapper.text()).toContain('Import-Preflight blockiert den Import.')

    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).not.toHaveBeenCalled()
  })

  it('uses backend/store preflight semantics when ok=false blocks without blocking=true', async () => {
    preflightCorpusImport.mockResolvedValueOnce({
      schema_version: 'corpus-import-preflight-v1',
      method: 'parquet',
      input_path: '/data/imports/not-ok.parquet',
      status: 'pass',
      ok: false,
      blocking: false,
      max_severity: 'error',
      summary: 'Preflight meldet kein nutzbares Ergebnis.',
      errors: [],
      warnings: [],
      checks: [
        {
          key: 'semantic_validity',
          label: 'Semantische Gültigkeit',
          status: 'fail',
          severity: 'error',
          blocking: false,
          message: 'ok=false',
          evidence: {},
        },
      ],
      evidence: {
        path: '/data/imports/not-ok.parquet',
        exists: true,
        is_file: true,
        suffix: '.parquet',
        columns: ['input_text'],
      },
    })

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('input[placeholder="/data/imports/korpus.parquet"]').setValue('/data/imports/not-ok.parquet')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('not-ok-demo')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Import-Preflight blockiert den Import.')

    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).not.toHaveBeenCalled()
  })

  it('shows when expert JSON overrides typed contract options', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('select').setValue('prealigned_csv')
    await flushPromises()

    const rejectPolicySelect = wrapper.findAll('select').find((select) => select.text().includes('fail_fast'))
    await rejectPolicySelect?.setValue('fail_fast')
    await wrapper.find('input[placeholder="/data/imports/paired.csv"]').setValue('/data/imports/paired.csv')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('form-demo')
    await wrapper.find('textarea').setValue('{"reject_policy":"collect","target_name":"json-demo","custom_flag":true}')
    await flushPromises()

    expect(wrapper.text()).toContain('Erweiterte Optionen überschreiben Formularwerte: reject_policy.')
    expect(wrapper.text()).toContain('Reservierte Felder werden aus dem Formular übernommen, nicht aus JSON-Optionen: target_name.')
    expect(wrapper.text()).toContain('Nicht in der Methodenliste deklarierte Optionen: custom_flag.')
    expect(wrapper.text()).toContain('Geplante Importanfrage')
    const preview = wrapper.find('.payload-review pre').text()
    expect(preview).toContain('"reject_policy": "collect"')
    expect(preview).toContain('"target_name": "form-demo"')
    expect(preview).not.toContain('"target_name": "json-demo"')
  })

  it('treats preflight evidence as stale after payload changes', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('input[placeholder="/data/imports/korpus.parquet"]').setValue('/data/imports/ok.parquet')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('fresh-demo')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Import-Preflight: bestanden')
    expect(wrapper.text()).not.toContain('Import-Preflight ist veraltet.')

    await wrapper.find('input[placeholder="mein_korpus"]').setValue('changed-demo')
    await flushPromises()

    expect(wrapper.text()).toContain('Import-Preflight ist veraltet.')

    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).not.toHaveBeenCalled()
  })

  it('renders unknown import methods from the contract and keeps numeric choices typed', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const researchBundleCard = wrapper.findAll('.method-catalogue-card').find((card) =>
      card.text().includes('Research Bundle')
    )
    expect(researchBundleCard?.exists()).toBe(true)
    await researchBundleCard?.trigger('click')
    await flushPromises()

    expect((wrapper.find('[data-testid="corpus-import-method"]').element as HTMLSelectElement).value).toBe('research_bundle')
    expect(wrapper.text()).toContain('Research Bundle')
    expect(wrapper.text()).toContain('Qualitätsstufe')
    expect(wrapper.text()).toContain('research_payload')
    expect(wrapper.text()).toContain('schnell: Schneller Import mit knapper Validierung.')
    expect(wrapper.text()).toContain('präzise: Gründlichere Validierung vor dem Build.')

    await wrapper.find('input[placeholder="/data/imports/research.bundle"]').setValue('/data/imports/research.bundle')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('research-demo')
    const qualitySelect = wrapper.findAll('select').find((select) => select.text().includes('präzise'))
    await qualitySelect?.setValue('3')

    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'research_bundle',
      input_path: '/data/imports/research.bundle',
      target_name: 'research-demo',
      activate_on_success: false,
      quality_level: 3,
    })
  })

  it('uses input.kind and accepts_directories for server-directory import semantics', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('select').setValue('research_directory')
    await flushPromises()

    expect(wrapper.text()).toContain('Research Directory')
    expect(wrapper.text()).toContain('Eingabe: Serververzeichnis')
    expect(wrapper.text()).toContain('Verzeichnisse: akzeptiert')
    expect(wrapper.text()).toContain('Serververzeichnis fehlt')
    expect(wrapper.text()).toContain('Diese Methode akzeptiert serverseitige Verzeichnisse.')

    await wrapper.find('input[placeholder="/data/imports/research-dir"]').setValue('/data/imports/research-dir')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('directory-demo')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'research_directory',
      input_path: '/data/imports/research-dir',
      target_name: 'directory-demo',
      activate_on_success: false,
    })
  })

  it('renders the plaintext adapter descriptor-driven and submits its typed options', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('[data-testid="corpus-import-method"]').setValue('plaintext')
    await flushPromises()

    expect(wrapper.text()).toContain('Plaintext (Ordner/Datei)')
    expect(wrapper.text()).toContain('First-class Import')
    expect(wrapper.text()).toContain('Eingabe: Serverdatei oder Serververzeichnis')
    expect(wrapper.text()).toContain('Verzeichnisse: akzeptiert')
    expect(wrapper.text()).toContain('Dateimuster')
    expect(wrapper.text()).toContain('Absätze als Dokumente')
    expect(wrapper.text()).toContain('register aus dem unmittelbaren Elternordner')

    await wrapper.find('input[placeholder="/data/imports/texte/"]').setValue('/data/imports/texte/')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('plaintext-demo')
    const patternField = wrapper.findAll('.option-field').find((field) => field.text().includes('Dateimuster'))
    await patternField?.find('input[type="text"]').setValue('*.md')
    await flushPromises()

    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'plaintext',
      input_path: '/data/imports/texte/',
      target_name: 'plaintext-demo',
      activate_on_success: false,
      pattern: '*.md',
    })
  })

  it('offers build_word_faiss only as descriptor option with the descriptor cost note and passes it through', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('[data-testid="corpus-import-method"]').setValue('csv')
    await flushPromises()

    expect(wrapper.text()).toContain('CSV/TSV')
    expect(wrapper.text()).toContain('CSV-Trenner')
    const faissField = wrapper.findAll('.option-field').find((field) =>
      field.text().includes('Wort-Thesaurus (Word-FAISS) nach dem Import bauen')
    )
    expect(faissField?.exists()).toBe(true)
    // Der Kosten-Hinweistext kommt unverändert aus dem Descriptor.
    expect(faissField?.text()).toContain('Kosten: zusätzliche Laufzeit und Arbeitsspeicher proportional zur Vokabulargröße')
    expect(faissField?.text()).toContain('semantic.word_similarity')
    const faissCheckbox = faissField!.find('input[type="checkbox"]')
    expect((faissCheckbox.element as HTMLInputElement).checked).toBe(false)

    await wrapper.find('input[placeholder="/data/imports/korpus.csv"]').setValue('/data/imports/korpus.csv')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('csv-demo')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    // Default aus: die Option wird nicht mitgesendet (Backend-Default bleibt maßgeblich).
    expect(createCorpusImportJob).toHaveBeenLastCalledWith({
      method: 'csv',
      input_path: '/data/imports/korpus.csv',
      target_name: 'csv-demo',
      activate_on_success: false,
    })

    await faissCheckbox.setValue(true)
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    expect(createCorpusImportJob).toHaveBeenLastCalledWith({
      method: 'csv',
      input_path: '/data/imports/korpus.csv',
      target_name: 'csv-demo',
      activate_on_success: false,
      build_word_faiss: true,
    })
  })

  it('renders the jsonl adapter with dot-path field semantics from the descriptor', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('[data-testid="corpus-import-method"]').setValue('jsonl')
    await flushPromises()

    expect(wrapper.text()).toContain('Textfeld')
    expect(wrapper.text()).toContain('Dot-Pfade wie payload.text sind erlaubt')
    expect(wrapper.text()).toContain('JSONL-Feldsemantik wird nicht als Forschungsdesign validiert.')
    expect(wrapper.text()).toContain('First-class Import')
  })

  it('treats the hf adapter as dataset-id import without server-path or trust_remote_code surface', async () => {
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    await wrapper.find('[data-testid="corpus-import-method"]').setValue('hf')
    await flushPromises()

    expect(wrapper.text()).toContain('HuggingFace-Dataset')
    expect(wrapper.text()).toContain('Eingabe: HF-Dataset-ID')
    expect(wrapper.text()).toContain('HuggingFace-Dataset-ID (kein Serverpfad)')
    expect(wrapper.text()).toContain('der Preflight bleibt ohne Netzzugriff')
    expect(wrapper.text()).toContain('trust_remote_code bleibt hart False')
    expect(wrapper.text()).not.toContain('Diese Methode erwartet eine serverseitige Datei.')
    expect(
      wrapper.findAll('.option-field').some((field) => field.text().includes('trust_remote_code'))
    ).toBe(false)

    const datasetInput = wrapper.find('input[placeholder="organisation/dataset-name"]')
    expect(datasetInput.exists()).toBe(true)
    await datasetInput.setValue('wikimedia/wikipedia')
    await flushPromises()
    expect(wrapper.text()).toContain('Aktuell abgeleitet: wikipedia')

    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()

    // Die Dataset-ID geht unverändert als input_path an Preflight und Jobstart.
    expect(preflightCorpusImport).toHaveBeenCalledWith({
      method: 'hf',
      input_path: 'wikimedia/wikipedia',
      target_name: 'wikipedia',
      activate_on_success: false,
    })
    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'hf',
      input_path: 'wikimedia/wikipedia',
      target_name: 'wikipedia',
      activate_on_success: false,
    })
  })

  it('offers the corpus language, fills in its pipeline and shows the language of each corpus', async () => {
    getCorpora.mockResolvedValue({
      corpora: [
        corpusSummary('demo', true, { language: 'en', annotation_pipeline: 'en_core_web_md' }),
        corpusSummary('parallel-demo'),
      ],
      count: 2,
    })
    const csv = corpusImportAdapterMethodDescriptors().find((item) => item.method === 'csv')!
    const languageSpec = {
      key: 'language',
      label: 'Korpussprache',
      type: 'choice',
      required: false,
      default: '',
      aliases: [],
      choices: [
        { value: '', label: '' },
        { value: 'de', label: 'de', pipeline: 'de_core_news_md' },
        { value: 'en', label: 'en', pipeline: 'en_core_web_md' },
      ],
    }
    getCorpusImportMethods.mockResolvedValueOnce([
      { ...csv, option_specs: [...csv.option_specs, languageSpec], option_keys: [...(csv.option_keys ?? []), 'language'] },
    ])
    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const languages = wrapper.findAll('[data-testid="corpus-language"]').map((item) => item.text())
    expect(languages).toEqual(['Sprache: Englisch (en)', 'Sprache: unbekannt'])
    expect(wrapper.text()).toContain('Pipeline: en_core_web_md')

    await wrapper.find('[data-testid="corpus-import-method"]').setValue('csv')
    await flushPromises()
    const languageField = wrapper.findAll('.option-field').find((field) => field.text().includes('Korpussprache'))!
    expect(languageField.find('select').text()).toContain('Englisch (en)')
    expect(languageField.find('select').text()).toContain('nicht festgelegt')
    await languageField.find('select').setValue('en')
    await flushPromises()

    expect(wrapper.find('[data-testid="language-pipeline-suggestion"]').text()).toContain('en_core_web_md')
    const modelField = wrapper.findAll('.option-field').find((field) => field.text().includes('spaCy-Modell'))!
    expect((modelField.find('input[type="text"]').element as HTMLInputElement).value).toBe('en_core_web_md')

    await wrapper.find('input[placeholder="/data/imports/korpus.csv"]').setValue('/data/imports/sotu.csv')
    await wrapper.find('input[placeholder="mein_korpus"]').setValue('sotu')
    await wrapper.findAll('button').find((button) => button.text().includes('Preflight prüfen'))?.trigger('click')
    await flushPromises()
    await wrapper.findAll('button').find((button) => button.text().includes('Import starten'))?.trigger('click')
    await flushPromises()
    expect(createCorpusImportJob).toHaveBeenCalledWith(expect.objectContaining({
      method: 'csv',
      language: 'en',
      spacy_model: 'en_core_web_md',
    }))
  })

  it('shows each import warning once, from the server', async () => {
    const reports = {
      reject_report: { rejected_rows: 2, total_rows: 48, reject_policy: 'collect' },
    }
    getCorpusImportReports.mockResolvedValueOnce({ schema_version: 'corpus-import-reports-v1', reports })
    listCorpusImportJobs.mockResolvedValueOnce([
      {
        job_id: 'job-with-rejects',
        status: 'done',
        progress: 100,
        stage: 'finished',
        stdout_tail: 'done',
        stderr_tail: '',
        stdout_truncated: false,
        urls: { reports: '/api/v1/corpora/imports/job-with-rejects/reports' },
        method: 'csv',
        target_name: 'rejects-demo',
        partial_input: true,
        rejected_rows: 2,
        warning_count: 1,
        import_warnings: ['2 Eingabezeile(n) wurden laut Reject-Report nicht übernommen.'],
        reports,
      },
    ])

    const wrapper = mount(CorpusManagerContent, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const warnings = wrapper.findAll('.job-warning-list li').map((item) => item.text())
    expect(warnings).toEqual(['2 Eingabezeile(n) wurden laut Reject-Report nicht übernommen.'])
  })
})
