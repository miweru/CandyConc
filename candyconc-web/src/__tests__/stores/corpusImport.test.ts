/**
 * Corpus import store tests — specify the intended Pinia behavior around job
 * lifecycle updates. If the store is not implemented yet, these fail against the
 * intended `useCorpusImportStore` export.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { useCorpusImportStore } from '@/stores/corpusImports'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useQueryStore } from '@/stores/query'
import { useSettingsStore } from '@/stores/settings'
import {
  activateCorpus,
  cancelCorpusImportJob,
  createCorpusImportJob,
  getCorpora,
  getCorpusCapabilities,
  getCorpusImportJob,
  getCorpusImportMethods,
  getCorpusImportReports,
  getSystemInfo,
  listCorpusImportJobs,
  preflightCorpusImport,
} from '@/api/client'

vi.mock('@/api/client', () => ({
  activateCorpus: vi.fn(),
  cancelCorpusImportJob: vi.fn(),
  createCorpusImportJob: vi.fn(),
  getCorpora: vi.fn(),
  getCorpusBuildReport: vi.fn(),
  getCorpusCapabilities: vi.fn(),
  getCorpusImportJob: vi.fn(),
  getCorpusImportMethods: vi.fn(),
  getCorpusImportReports: vi.fn(),
  getAuthSession: vi.fn(),
  getProductCapabilities: vi.fn(),
  getSystemInfo: vi.fn(),
  loginUser: vi.fn(),
  logoutUser: vi.fn(),
  listCorpusImportJobs: vi.fn(),
  preflightCorpusImport: vi.fn(),
  registerCorpus: vi.fn(),
  unregisterCorpus: vi.fn(),
}))

const queuedJob = {
  job_id: 'import-123',
  status: 'queued',
  progress: 0,
  corpus: 'bundestag-2026',
  message: 'Queued',
}

const runningJob = {
  ...queuedJob,
  status: 'running',
  progress: 35,
  message: 'Tokenizing documents',
}

const doneJob = {
  ...queuedJob,
  status: 'done',
  progress: 100,
  message: 'Ready',
}

const preflightResult = {
  schema_version: 'corpus-import-preflight-v1',
  method: 'prealigned_csv',
  input_path: '/safe/imports/paired.csv',
  status: 'warning',
  ok: true,
  blocking: false,
  max_severity: 'warning',
  summary: 'Preflight mit Warnungen abgeschlossen.',
  errors: [],
  warnings: ['Reject-Policy collect kann verworfene Zeilen sammeln.'],
  checks: [
    {
      key: 'reject_policy',
      label: 'Reject-Policy',
      status: 'warn',
      severity: 'warning',
      blocking: false,
      message: 'collect',
      evidence: {},
    },
  ],
  evidence: { path: '/safe/imports/paired.csv', exists: true, columns: ['text', 'pair_id', 'pair_role'] },
}

const operationSpecs: Record<string, Record<string, { path: string; method: string; label: string }>> = {
  'corpus.import': {
    'corpus.import.methods': { path: '/api/v1/corpora/import-methods', method: 'GET', label: 'Importmethoden' },
    'corpus.import.preflight': { path: '/api/v1/corpora/import-preflight', method: 'POST', label: 'Import-Preflight' },
    'corpus.import.jobs_list': { path: '/api/v1/corpora/imports', method: 'GET', label: 'Importjobs' },
    'corpus.import.start': { path: '/api/v1/corpora/imports', method: 'POST', label: 'Korpusimport starten' },
    'corpus.import.job_status': { path: '/api/v1/corpora/imports/{job_id}', method: 'GET', label: 'Importjob-Status' },
    'corpus.import.job_cancel': { path: '/api/v1/corpora/imports/{job_id}/cancel', method: 'POST', label: 'Importjob-Abbruch' },
    'corpus.import.job_reports': { path: '/api/v1/corpora/imports/{job_id}/reports', method: 'GET', label: 'Importjob-Reports' },
  },
  'corpus.catalogue': {
    'corpus.catalogue.list': { path: '/api/v1/corpora', method: 'GET', label: 'Korpuskatalog' },
    'corpus.catalogue.activate': { path: '/api/v1/corpora/{corpus}/activate', method: 'POST', label: 'Korpus aktivieren' },
    'corpus.catalogue.capabilities': { path: '/api/v1/corpora/{corpus}/capabilities', method: 'GET', label: 'Korpusfähigkeiten' },
  },
  'admin.system_operations': {
    'admin.system_operations.info': { path: '/api/v1/system/info', method: 'GET', label: 'Systeminformationen' },
  },
}

function operationsForCapability(
  id: string,
  descriptors: Array<{
    path: string
    methods: string[]
    mutates: boolean
    requires_corpus_features: string[]
    access: string
    required_role: string
    transport: string
    route_class: string
  }>,
) {
  return Object.entries(operationSpecs[id] ?? {}).flatMap(([operationId, spec]) => {
    const descriptor = descriptors.find((route) =>
      route.path === spec.path &&
      route.methods.map((method) => method.toUpperCase()).includes(spec.method)
    )
    if (!descriptor) return []
    return [{
      id: operationId,
      capability_id: id,
      label: spec.label,
      description: '',
      route: { ...descriptor, methods: [spec.method] },
      effects: spec.method === 'GET' ? ['read'] : ['write'],
      handler_key: operationId,
      surface_slot: operationId,
      priority: 100,
    }]
  })
}

function seedImportContracts(role: 'user' | 'admin' = 'admin') {
  const productCapabilities = useProductCapabilitiesStore()
  const importRouteDescriptors = [
    { path: '/api/v1/corpora/import-methods', methods: ['GET'], mutates: false },
    { path: '/api/v1/corpora/import-preflight', methods: ['POST'], mutates: false },
    { path: '/api/v1/corpora/imports', methods: ['GET', 'POST'], mutates: true },
    { path: '/api/v1/corpora/imports/{job_id}', methods: ['GET'], mutates: false },
    { path: '/api/v1/corpora/imports/{job_id}/cancel', methods: ['POST'], mutates: true },
    { path: '/api/v1/corpora/imports/{job_id}/reports', methods: ['GET'], mutates: false },
  ].map((route) => ({
    ...route,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }))
  const catalogueRouteDescriptors = [{
    path: '/api/v1/corpora',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }, {
    path: '/api/v1/corpora/{corpus}/activate',
    methods: ['POST'],
    mutates: true,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }, {
    path: '/api/v1/corpora/{corpus}/capabilities',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'user',
    required_role: 'user',
    transport: 'http',
    route_class: 'product_surface',
  }]
  const systemRouteDescriptors = [{
    path: '/api/v1/system/info',
    methods: ['GET'],
    mutates: false,
    requires_corpus_features: [],
    access: 'admin',
    required_role: 'admin',
    transport: 'http',
    route_class: 'admin_surface',
  }]
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [
      {
        id: 'corpus.import',
        title: 'Observable corpus import',
        area: 'corpus',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [
          '/api/v1/corpora/import-methods',
          '/api/v1/corpora/import-preflight',
          '/api/v1/corpora/imports',
          '/api/v1/corpora/imports/{job_id}',
          '/api/v1/corpora/imports/{job_id}/cancel',
          '/api/v1/corpora/imports/{job_id}/reports',
        ],
        backend_route_descriptors: importRouteDescriptors,
        operations: operationsForCapability('corpus.import', importRouteDescriptors),
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
      {
        id: 'corpus.catalogue',
        title: 'Corpus catalogue',
        area: 'corpus',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/corpora', '/api/v1/corpora/{corpus}/activate', '/api/v1/corpora/{corpus}/capabilities'],
        backend_route_descriptors: catalogueRouteDescriptors,
        operations: operationsForCapability('corpus.catalogue', catalogueRouteDescriptors),
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
      {
        id: 'admin.system_operations',
        title: 'System operations',
        area: 'admin',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/system/info'],
        backend_route_descriptors: systemRouteDescriptors,
        operations: operationsForCapability('admin.system_operations', systemRouteDescriptors),
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
    ],
  } as never

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

describe('useCorpusImportStore', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    seedImportContracts()
    vi.mocked(createCorpusImportJob).mockResolvedValue(queuedJob)
    vi.mocked(getCorpusImportJob).mockResolvedValue(runningJob)
    vi.mocked(cancelCorpusImportJob).mockResolvedValue({
      ...runningJob,
      status: 'cancelled',
      message: 'Cancelled',
    })
    vi.mocked(getCorpusImportReports).mockResolvedValue({
      schema_version: 'corpus-import-reports-v1',
      job_id: 'import-123',
      reports: {
        manifest: { label: 'Manifest', url: '/reports/manifest' },
        build_report: { status: 'ok', token_count: 12 },
        reject_report: { rejected_rows: 0 },
      },
    })
    vi.mocked(listCorpusImportJobs).mockResolvedValue([runningJob])
    vi.mocked(preflightCorpusImport).mockResolvedValue(preflightResult)
    vi.mocked(getSystemInfo).mockResolvedValue({
      corpusName: 'imported-demo',
      tokenCount: 2000,
      documentCount: 20,
    })
    vi.mocked(getCorpusCapabilities).mockResolvedValue({
      name: 'imported-demo',
      path: '/corpora/imported-demo',
      status: 'ready',
      active: true,
      token_count: 2000,
      doc_count: 20,
      import_mode: 'parquet',
      paired: false,
      pair_axes: [],
      is_legacy: false,
      capabilities: {},
    })
    vi.mocked(activateCorpus).mockImplementation(async (corpus: string) => ({
      name: corpus,
      path: `/corpora/${corpus}`,
      status: 'ready',
      active: true,
      token_count: 2000,
      doc_count: 20,
      import_mode: 'parquet',
      paired: false,
      pair_axes: [],
      is_legacy: false,
      capabilities: {},
    }))
    vi.mocked(getCorpusImportMethods).mockResolvedValue([
      {
        schema_version: 'corpus-import-method-v1',
        method: 'parquet',
        label: 'Parquet',
        description: 'Serverseitiger Parquet-Pfad',
        input: { kind: 'server_file', extensions: ['.parquet'], accepts_directories: false },
        option_keys: ['spacy_model'],
        option_specs: [{ key: 'spacy_model', label: 'spaCy-Modell', type: 'string', required: false, default: 'de_core_news_md', choices: [], aliases: [] }],
        expected_columns: [{ key: 'input_text', required: true }],
        output: { paired: false, paired_data_dependent: true, pairing_kind: 'row_metadata_if_present', emitted_features: ['kwic_ready'], guarantees: [], limitations: [] },
        emitted_features: ['kwic_ready'],
        reports: [{ key: 'build_report', label: 'Build-Report' }],
      },
      {
        schema_version: 'corpus-import-method-v1',
        method: 'prealigned_csv',
        label: 'Pre-grouped CSV',
        description: 'Extern gepaarte CSV-Daten',
        input: { kind: 'server_file', extensions: ['.csv', '.tsv'], accepts_directories: false },
        option_keys: ['pair_key_column', 'reject_policy'],
        option_specs: [
          { key: 'pair_key_column', label: 'Pair-Key-Spalte', type: 'string', required: true, default: 'pair_id', choices: [], aliases: [] },
          { key: 'reject_policy', label: 'Reject-Policy', type: 'choice', required: false, default: 'collect', choices: ['collect', 'fail_fast'], aliases: [] },
        ],
        expected_columns: [{ key: 'pair_id', required: true, configured_by: 'pair_key_column' }],
        output: { paired: true, pairing_kind: 'external_pair_keys', emitted_features: ['pair_metadata'], guarantees: [], limitations: ['Keine inhaltliche Alignmentprüfung.'] },
        emitted_features: ['pair_metadata'],
        reports: [{ key: 'reject_report', label: 'Reject-Report' }],
      },
    ])
    vi.mocked(getCorpora).mockResolvedValue({ corpora: [], count: 0 })
  })

  afterEach(() => {
    useCorpusImportStore().stopPolling()
  })

  it('starts an import, stores the active job, and clears stale errors', async () => {
    const store = useCorpusImportStore()
    store.error = 'previous failure'
    const input = {
      method: 'vrt',
      inputPath: '/safe/imports/bundestag.vrt',
      targetName: 'bundestag-2026',
      activateOnSuccess: true,
    }

    await store.runPreflight(input)
    await store.startImport(input)

    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'vrt',
      input_path: '/safe/imports/bundestag.vrt',
      target_name: 'bundestag-2026',
      activate_on_success: true,
    })
    expect(store.activeJob?.job_id).toBe('import-123')
    expect(store.jobs['import-123']?.status).toBe('queued')
    expect(store.error).toBeNull()
    expect(store.isStarting).toBe(false)
    expect(store.isPolling).toBe(true)
  })

  it('accepts backend-compatible payload aliases without leaking reserved path fields into options', async () => {
    const store = useCorpusImportStore()
    const input = {
      method: 'prealigned_csv',
      path: '/safe/imports/paired.csv',
      target: 'paired-demo',
      target_path: '/ignored/from/override',
      staging_path: '/ignored/staging',
      activate: true,
      pair_key_column: 'pair_id',
    }

    await store.runPreflight(input)
    await store.startImport(input)

    expect(preflightCorpusImport).toHaveBeenCalledWith({
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      activate_on_success: true,
      pair_key_column: 'pair_id',
    })
    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      activate_on_success: true,
      pair_key_column: 'pair_id',
    })
  })

  it('fails closed when starting an import without fresh non-blocking preflight', async () => {
    const store = useCorpusImportStore()
    const input = {
      method: 'vrt',
      inputPath: '/safe/imports/demo.vrt',
      targetName: 'demo',
    }

    await expect(store.startImport(input)).rejects.toThrow('Import-Preflight fehlt')
    expect(createCorpusImportJob).not.toHaveBeenCalled()
    expect(store.error).toContain('Import-Preflight fehlt')

    await store.runPreflight(input)
    await expect(store.startImport({ ...input, targetName: 'changed-demo' })).rejects.toThrow('Import-Preflight ist veraltet')
    expect(createCorpusImportJob).not.toHaveBeenCalled()

    vi.mocked(preflightCorpusImport).mockResolvedValueOnce({
      ...preflightResult,
      ok: false,
      blocking: true,
      status: 'error',
      errors: ['Dateiendung passt nicht.'],
    })
    const blockedInput = { ...input, targetName: 'blocked-demo' }
    await store.runPreflight(blockedInput)
    await expect(store.startImport(blockedInput)).rejects.toThrow('Import-Preflight blockiert')
    expect(createCorpusImportJob).not.toHaveBeenCalled()
  })

  it('validates local preflight state before checking mutating import access', async () => {
    const store = useCorpusImportStore()
    const productCapabilities = useProductCapabilitiesStore()
    const accessSpy = vi.spyOn(productCapabilities, 'assertProductOperationAccess')

    await expect(store.startImport({
      method: 'vrt',
      inputPath: '/safe/imports/demo.vrt',
      targetName: 'demo',
    })).rejects.toThrow('Import-Preflight fehlt')

    expect(accessSpy).not.toHaveBeenCalledWith(
      'corpus.import.start',
      expect.anything(),
      expect.anything(),
    )
    expect(createCorpusImportJob).not.toHaveBeenCalled()
  })

  it('applies progress snapshots without regressing progress for the same job', async () => {
    const store = useCorpusImportStore()

    store.applyProgress({ ...runningJob, progress: 60 })
    store.applyProgress({ ...runningJob, progress: 40, message: 'Late duplicate event' })

    expect(store.jobs['import-123']?.progress).toBe(60)
    expect(store.jobs['import-123']?.message).toBe('Late duplicate event')
  })

  it('cancels the active job through the API and records the cancelled snapshot', async () => {
    const store = useCorpusImportStore()
    store.applyProgress(runningJob)

    await store.cancelJob('import-123')

    expect(cancelCorpusImportJob).toHaveBeenCalledWith('import-123')
    expect(store.jobs['import-123']?.status).toBe('cancelled')
    expect(store.cancellingJobIds).not.toContain('import-123')
  })

  it('refreshes corpora and reports once a job reaches done', async () => {
    const store = useCorpusImportStore()

    await store.refreshJob('import-123')
    vi.mocked(getCorpusImportJob).mockResolvedValueOnce(doneJob)
    await store.refreshJob('import-123')
    await nextTick()

    expect(getCorpusImportJob).toHaveBeenCalledWith('import-123')
    expect(getCorpora).toHaveBeenCalledTimes(1)
    expect(getCorpusImportReports).toHaveBeenCalledWith('import-123')
    expect(store.jobs['import-123']?.status).toBe('done')
    expect(store.reportsByJobId['import-123']?.manifest).toEqual({ label: 'Manifest', url: '/reports/manifest' })
    expect(store.reportsByJobId['import-123']?.reject_report).toEqual({ rejected_rows: 0 })
  })

  it('uses terminal snapshot reports immediately but still fetches canonical report evidence', async () => {
    const store = useCorpusImportStore()
    vi.mocked(getCorpusImportReports).mockClear()
    vi.mocked(getCorpusImportJob).mockResolvedValueOnce({
      ...doneJob,
      reports: {
        manifest: { data: { import_mode: 'prealigned_csv', paired: true, pair_axes: ['pair_id'] } },
        reject_report: { rejected_rows: 2, total_rows: 20, reject_policy: 'collect' },
      },
    })

    await store.refreshJob('import-123')
    await nextTick()

    expect(getCorpusImportJob).toHaveBeenCalledWith('import-123')
    expect(getCorpusImportReports).toHaveBeenCalledWith('import-123')
    expect(store.jobs['import-123']?.status).toBe('done')
    expect(store.reportsByJobId['import-123']?.manifest).toEqual({ label: 'Manifest', url: '/reports/manifest' })
    expect(store.reportsByJobId['import-123']?.reject_report).toEqual({ rejected_rows: 0 })
  })

  it('loads backend import methods and falls back with a visible limitation state', async () => {
    const store = useCorpusImportStore()

    await store.loadMethods()

    expect(getCorpusImportMethods).toHaveBeenCalled()
    expect(store.methodOptions.map((item) => item.method)).toEqual(['parquet', 'prealigned_csv'])
    expect(store.methodOptions[1]?.option_specs.map((item) => item.key)).toContain('reject_policy')
    expect(store.methodOptions[1]?.output?.limitations[0]).toContain('Alignmentprüfung')
    expect(store.methodError).toBeNull()

    vi.mocked(getCorpusImportMethods).mockRejectedValueOnce(new Error('403 admin only'))
    await store.loadMethods()

    expect(store.methodOptions).toHaveLength(0)
    expect(store.methodError).toContain('403 admin only')
  })

  it('fails closed before starting import methods that are not first-class UI', async () => {
    vi.mocked(getCorpusImportMethods).mockResolvedValueOnce([
      {
        schema_version: 'corpus-import-method-v1',
        method: 'embed_alignment',
        label: 'Embedding Alignment',
        description: 'CLI/API-only sentence alignment build',
        input: { kind: 'server_file', extensions: ['.parquet'], accepts_directories: false },
        ui_workflow: {
          status: 'expert_api',
          label: 'Expert/API',
          reason: 'Sentence-Embedding-/Hybrid-Alignment braucht einen kuratierten CLI-Build.',
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
    const store = useCorpusImportStore()

    await store.loadMethods()
    await expect(store.startImport({
      method: 'embed_alignment',
      inputPath: '/safe/imports/alignment.parquet',
      targetName: 'aligned-demo',
    })).rejects.toThrow('Expert/API')

    expect(store.error).toContain('Sentence-Embedding-/Hybrid-Alignment')
    expect(createCorpusImportJob).not.toHaveBeenCalled()
    expect(preflightCorpusImport).not.toHaveBeenCalledWith(expect.objectContaining({ method: 'embed_alignment' }))
  })

  it('hydrates retained import jobs from the backend list after reload', async () => {
    const store = useCorpusImportStore()

    await store.loadJobs()

    expect(listCorpusImportJobs).toHaveBeenCalled()
    expect(store.recentJobs.map((job) => job.job_id)).toEqual(['import-123'])
    expect(store.activeJob?.status).toBe('running')
    expect(store.isPolling).toBe(true)
    expect(store.isLoadingJobs).toBe(false)
  })

  it('normalizes retained terminal job reports through the canonical reports endpoint', async () => {
    const store = useCorpusImportStore()
    vi.mocked(getCorpusImportReports).mockClear()
    vi.mocked(listCorpusImportJobs).mockResolvedValueOnce([{
      ...doneJob,
      reports: {
        build_report: { status: 'ok', token_count: 99 },
        reject_report: { rejected_rows: 0 },
      },
    }])

    await store.loadJobs()
    await nextTick()

    expect(listCorpusImportJobs).toHaveBeenCalled()
    expect(getCorpusImportReports).toHaveBeenCalledWith('import-123')
    expect(store.recentJobs.map((job) => job.job_id)).toEqual(['import-123'])
    expect(store.reportsByJobId['import-123']?.build_report).toEqual({ status: 'ok', token_count: 12 })
    expect(store.reportsByJobId['import-123']?.reject_report).toEqual({ rejected_rows: 0 })
  })

  it('polls running jobs and automatically loads reports when they become terminal', async () => {
    const store = useCorpusImportStore()
    store.applyProgress(runningJob)
    vi.mocked(getCorpusImportJob).mockResolvedValueOnce(doneJob)
    vi.mocked(getCorpora).mockClear()

    await store.pollRunningJobs()
    await nextTick()

    expect(getCorpusImportJob).toHaveBeenCalledWith('import-123')
    expect(getCorpusImportReports).toHaveBeenCalledWith('import-123')
    expect(getCorpora).toHaveBeenCalledTimes(1)
    expect(store.jobs['import-123']?.status).toBe('done')
    expect(store.reportsByJobId['import-123']?.build_report).toEqual({ status: 'ok', token_count: 12 })
    expect(store.isPolling).toBe(false)
  })

  it('syncs query, catalogue and status bar when an activate-on-success job finishes', async () => {
    const store = useCorpusImportStore()
    const query = useQueryStore()
    const settings = useSettingsStore()
    query.setFilters({ corpus: 'old-demo' })
    store.applyProgress({ ...runningJob, activate_on_success: true, target_name: 'imported-demo' })
    vi.mocked(getCorpusImportJob).mockResolvedValueOnce({
      ...doneJob,
      activate_on_success: true,
      target_name: 'imported-demo',
    })
    vi.mocked(getCorpora).mockResolvedValueOnce({
      corpora: [
        {
          name: 'old-demo',
          path: '/corpora/old-demo',
          status: 'ready',
          active: false,
          token_count: 100,
          doc_count: 1,
          import_mode: 'parquet',
          paired: false,
          pair_axes: [],
          is_legacy: false,
          capabilities: {},
        },
        {
          name: 'imported-demo',
          path: '/corpora/imported-demo',
          status: 'ready',
          active: true,
          token_count: 2000,
          doc_count: 20,
          import_mode: 'parquet',
          paired: false,
          pair_axes: [],
          is_legacy: false,
          capabilities: {},
        },
      ],
      count: 2,
    })

    await store.pollRunningJobs()
    await nextTick()

    expect(query.filters.corpus).toBe('imported-demo')
    expect(settings.systemInfo.corpusName).toBe('imported-demo')
    expect(getSystemInfo).toHaveBeenCalled()
    expect(getCorpora).toHaveBeenCalledTimes(1)
    expect(store.jobs['import-123']?.status).toBe('done')
  })

  it('falls back to explicit activation when activate-on-success leaves the runtime scope on default', async () => {
    const store = useCorpusImportStore()
    const query = useQueryStore()
    query.setFilters({ corpus: 'default' })
    store.applyProgress({ ...runningJob, activate_on_success: true, target_name: 'imported-demo' })
    vi.mocked(getCorpusImportJob).mockResolvedValueOnce({
      ...doneJob,
      activate_on_success: true,
      target_name: 'imported-demo',
    })
    vi.mocked(getCorpora).mockResolvedValueOnce({
      corpora: [
        {
          name: 'default',
          path: '/corpora/default',
          status: 'ready',
          active: true,
          token_count: 100,
          doc_count: 1,
          import_mode: 'parquet',
          paired: false,
          pair_axes: [],
          is_legacy: false,
          capabilities: {},
        },
        {
          name: 'imported-demo',
          path: '/corpora/imported-demo',
          status: 'ready',
          active: false,
          token_count: 2000,
          doc_count: 20,
          import_mode: 'parquet',
          paired: false,
          pair_axes: [],
          is_legacy: false,
          capabilities: {},
        },
      ],
      count: 2,
    })
    vi.mocked(getSystemInfo)
      .mockResolvedValueOnce({
        corpusName: 'default',
        tokenCount: 100,
        documentCount: 1,
      })
      .mockResolvedValue({
        corpusName: 'imported-demo',
        tokenCount: 2000,
        documentCount: 20,
      })

    await store.pollRunningJobs()
    await nextTick()

    expect(activateCorpus).toHaveBeenCalledWith('imported-demo')
    expect(query.filters.corpus).toBe('imported-demo')
    expect(store.jobs['import-123']?.status).toBe('done')
  })

  it('syncs the frontend scope when the backend catalogue marks a completed import active', async () => {
    const store = useCorpusImportStore()
    const query = useQueryStore()
    const settings = useSettingsStore()
    query.setFilters({ corpus: 'default' })
    store.applyProgress({ ...runningJob, activate_on_success: false, target_name: 'imported-demo' })
    vi.mocked(getCorpusImportJob).mockResolvedValueOnce({
      ...doneJob,
      activate_on_success: false,
      target_name: 'imported-demo',
    })
    vi.mocked(getCorpora).mockResolvedValueOnce({
      corpora: [
        {
          name: 'imported-demo',
          path: '/corpora/imported-demo',
          status: 'ready',
          active: true,
          token_count: 2000,
          doc_count: 20,
          import_mode: 'parquet',
          paired: false,
          pair_axes: [],
          is_legacy: false,
          capabilities: {},
        },
      ],
      count: 1,
    })

    await store.pollRunningJobs()
    await nextTick()

    expect(query.filters.corpus).toBe('imported-demo')
    expect(settings.systemInfo.corpusName).toBe('imported-demo')
    expect(getSystemInfo).toHaveBeenCalled()
    expect(getCorpora).toHaveBeenCalledTimes(2)
    expect(store.jobs['import-123']?.status).toBe('done')
  })

  it('runs preflight, stores evidence, and keys it to the exact payload', async () => {
    const store = useCorpusImportStore()
    const input = {
      method: 'prealigned_csv',
      inputPath: '/safe/imports/paired.csv',
      targetName: 'paired-demo',
      options: { reject_policy: 'collect' },
    }

    await store.runPreflight(input)

    expect(preflightCorpusImport).toHaveBeenCalledWith({
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      activate_on_success: false,
      reject_policy: 'collect',
    })
    expect(store.preflightResult?.warnings).toHaveLength(1)
    expect(store.preflightPayloadKey).toBe(store.payloadKey(input))
    expect(store.isPreflighting).toBe(false)
    expect(store.preflightError).toBeNull()
  })

  it('keeps backend-flat option payloads when callers do not use the UI options wrapper', async () => {
    const store = useCorpusImportStore()
    const input = {
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      reject_policy: 'fail_fast',
      pair_key_column: 'pair',
    }

    await store.runPreflight(input)
    await store.startImport(input)

    expect(preflightCorpusImport).toHaveBeenCalledWith({
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      activate_on_success: false,
      reject_policy: 'fail_fast',
      pair_key_column: 'pair',
    })
    expect(createCorpusImportJob).toHaveBeenCalledWith({
      method: 'prealigned_csv',
      input_path: '/safe/imports/paired.csv',
      target_name: 'paired-demo',
      activate_on_success: false,
      reject_policy: 'fail_fast',
      pair_key_column: 'pair',
    })
  })

  it('blocks import lifecycle endpoints when the route operations are not available to the session', async () => {
    seedImportContracts('user')
    vi.clearAllMocks()
    const store = useCorpusImportStore()

    await expect(store.loadMethods()).resolves.toEqual([])
    expect(getCorpusImportMethods).not.toHaveBeenCalled()
    expect(store.methodError).toContain('Rolle Admin')

    await expect(store.loadJobs()).resolves.toEqual([])
    expect(listCorpusImportJobs).not.toHaveBeenCalled()
    expect(store.error).toContain('Rolle Admin')

    await expect(store.runPreflight({
      method: 'vrt',
      inputPath: '/safe/imports/demo.vrt',
      targetName: 'demo',
    })).rejects.toThrow('Rolle Admin')
    expect(preflightCorpusImport).not.toHaveBeenCalled()

    const startInput = {
      method: 'vrt',
      inputPath: '/safe/imports/demo.vrt',
      targetName: 'demo',
    }
    store.preflightResult = {
      ...preflightResult,
      method: startInput.method,
      input_path: startInput.inputPath,
    }
    store.preflightPayloadKey = store.payloadKey(startInput)
    await expect(store.startImport(startInput)).rejects.toThrow('Rolle Admin')
    expect(createCorpusImportJob).not.toHaveBeenCalled()

    await expect(store.refreshJob('import-123')).rejects.toThrow('Rolle Admin')
    expect(getCorpusImportJob).not.toHaveBeenCalled()

    await expect(store.cancelJob('import-123')).rejects.toThrow('Rolle Admin')
    expect(cancelCorpusImportJob).not.toHaveBeenCalled()

    await expect(store.loadReports('import-123')).rejects.toThrow('Rolle Admin')
    expect(getCorpusImportReports).not.toHaveBeenCalled()
  })
})
