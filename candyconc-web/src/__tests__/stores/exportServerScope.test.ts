import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const clientMocks = vi.hoisted(() => ({
  exportPdf: vi.fn(),
  exportDocx: vi.fn(),
  getFrequency: vi.fn(async () => []),
  getCollocations: vi.fn(async () => []),
  getExportConcordance: vi.fn(),
  getExportEvidencePackage: vi.fn(),
}))

vi.mock('@/api/client', () => clientMocks)

import { useExportStore } from '@/stores/export'
import { useQueryStore } from '@/stores/query'
import { useDocsetStore } from '@/stores/docset'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'

function route(path: string, method: string) {
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

function operation(id: string, label: string, routeDescriptor: ReturnType<typeof route>) {
  return {
    id,
    capability_id: 'research.replay_export',
    label,
    description: '',
    route: routeDescriptor,
    effects: ['read', 'long_running'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 10,
  }
}

function seedReplayExportContract(): void {
  const concordancePost = route('/api/v1/export/concordance', 'POST')
  const evidence = route('/api/v1/export/evidence-package', 'POST')
  const pdf = route('/api/v1/export/pdf', 'POST')
  const docx = route('/api/v1/export/docx', 'POST')
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [{
      id: 'research.replay_export',
      title: 'Replay export',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [concordancePost.path, evidence.path, pdf.path, docx.path],
      backend_route_descriptors: [concordancePost, evidence, pdf, docx],
      operations: [
        operation('research.replay_export.concordance', 'Vollständige Konkordanz exportieren', concordancePost),
        operation('research.replay_export.evidence_package', 'EvidencePackage exportieren', evidence),
        operation('research.replay_export.pdf', 'PDF-Report exportieren', pdf),
        operation('research.replay_export.docx', 'DOCX-Report exportieren', docx),
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
      notes: '',
    }],
  } as never

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

describe('export store — server full-concordance scope (F2)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedReplayExportContract()
    vi.clearAllMocks()
    clientMocks.exportPdf.mockReset()
    clientMocks.exportDocx.mockReset()
    clientMocks.getExportConcordance.mockReset()
    clientMocks.getExportEvidencePackage.mockReset()
    // jsdom: stub object-URL plumbing used by downloadBlob.
    if (!('createObjectURL' in URL)) {
      // @ts-expect-error test shim
      URL.createObjectURL = () => 'blob:mock'
      // @ts-expect-error test shim
      URL.revokeObjectURL = () => undefined
    } else {
      vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:mock')
      vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    }
    vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n as never)
    vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n as never)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })

  it('replays the full query and reports the server count when the browser holds a sample', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['word,freq\n'], { type: 'text/csv' }),
      filename: 'concordance.csv',
      total: 20907,
      exportedRows: 20907,
      truncated: false,
    })

    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setCaseSensitive(false)
    queryStore.setResults([], 200, true, false)
    queryStore.setSampleProvenance({ requested: 200, drawn: 200, seed: 526085, population: 20907, populationPartial: false })

    const exportStore = useExportStore()
    const job = await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'all-server',
    })

    expect(clientMocks.getExportConcordance).toHaveBeenCalledTimes(1)
    const params = clientMocks.getExportConcordance.mock.calls[0][0]
    expect(params).toMatchObject({ query: 'Hase', caseInsensitive: true, format: 'csv' })
    expect(job.status).toBe('completed')
    expect(job.filename).toBe('concordance.csv')
    expect(params).not.toHaveProperty('sample')
    expect(params).not.toHaveProperty('seed')
    expect(job.total).toBe(20907)
    expect(job.exportedRows).toBe(20907)
  })

  it('supports every backend-declared full-concordance stream format', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['payload'], { type: 'text/plain' }),
      filename: 'concordance.tsv',
      total: 3,
      truncated: false,
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'tsv',
      scope: 'loaded',
    })
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'json',
      scope: 'loaded',
    })
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'jsonl',
      scope: 'loaded',
    })

    expect(clientMocks.getExportConcordance).toHaveBeenCalledTimes(3)
    expect(clientMocks.getExportConcordance.mock.calls.map((call) => call[0].format)).toEqual(['tsv', 'json', 'jsonl'])
  })

  it('streams XLSX through the server concordance export', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['xlsx-bytes'], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
      filename: 'concordance.xlsx',
      total: 5,
      truncated: false,
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    const job = await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'xlsx',
      scope: 'loaded',
    })

    expect(clientMocks.getExportConcordance).toHaveBeenCalledTimes(1)
    expect(clientMocks.getExportConcordance.mock.calls[0][0]).toMatchObject({
      query: 'Hase',
      format: 'xlsx',
    })
    expect(job.status).toBe('completed')
    expect(job.filename).toBe('concordance.xlsx')
  })

  it('passes the Excel CSV dialect switch through and keeps the default off', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['word;freq\n'], { type: 'text/csv' }),
      filename: 'concordance.csv',
      total: 2,
      truncated: false,
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'all-server',
      excelDe: true,
    })
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'all-server',
    })

    expect(clientMocks.getExportConcordance).toHaveBeenCalledTimes(2)
    expect(clientMocks.getExportConcordance.mock.calls[0][0]).toMatchObject({
      format: 'csv',
      excelDe: true,
    })
    expect(clientMocks.getExportConcordance.mock.calls[1][0]).toMatchObject({
      format: 'csv',
      excelDe: false,
    })
  })

  it('never sends the Excel CSV dialect with a non-CSV stream format', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['xlsx-bytes'], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }),
      filename: 'concordance.xlsx',
      total: 5,
      truncated: false,
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'xlsx',
      scope: 'all-server',
      excelDe: true,
    })

    expect(clientMocks.getExportConcordance.mock.calls[0][0]).toMatchObject({
      format: 'xlsx',
      excelDe: false,
    })
  })

  it('keeps server truncation evidence on the export job', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['word,freq\n'], { type: 'text/csv' }),
      filename: 'concordance.csv',
      total: 1_000_001,
      totalMatches: 1_000_001,
      exportedRows: 1_000_000,
      exportCap: 1_000_000,
      truncated: true,
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    const job = await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'all-server',
    })

    expect(job.truncated).toBe(true)
    expect(job.total).toBe(1_000_001)
    expect(job.exportedRows).toBe(1_000_000)
    expect(job.exportCap).toBe(1_000_000)
    expect(job.warning).toContain('1.000.000 von 1.000.001')
    expect(job.warning).toContain('Exportgrenze')
    expect(exportStore.exportHistory[0]?.warning).toContain('Exportgrenze')
  })

  it('blocks pure loaded-browser CSV instead of treating it as a ProductOperation export', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' }],
      1,
      true,
      false
    )

    const exportStore = useExportStore()
    await expect(exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'loaded',
      includeResults: true,
      includeFrequency: false,
      includeCollocations: false,
    })).rejects.toThrow('lokaler Auszug')

    expect(clientMocks.getExportConcordance).not.toHaveBeenCalled()
  })

  it('blocks all-server export instead of reusing a dirty active docset', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'stale-docset'
    docsetStore.isDirty = true

    const exportStore = useExportStore()
    await expect(exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'all-server',
    })).rejects.toThrow('angewendeten Subkorpus')

    expect(clientMocks.getExportConcordance).not.toHaveBeenCalled()
  })

  it('exports an EvidencePackage through the server provenance endpoint', async () => {
    clientMocks.getExportEvidencePackage.mockResolvedValue({
      schema_version: 'candyconc-evidence-package-v1',
      package_id: 'evp_test123',
      generated_at: '2026-06-19T00:00:00Z',
      query_trace_id: 'qtr_test',
      scope: { query: 'Hase' },
      corpus: { name: 'default' },
      result_summary: {
        observed_hit_count: 2,
        total_matches: 2,
        exported_rows: 2,
        export_cap: 1_000_000,
        rows_included: 2,
        truncated: false,
        complete_within_export_cap: true,
        row_hash_sha256: 'a'.repeat(64),
      },
      method_blocks: [{ id: 'kwic_query_runtime' }],
      rows: [],
    })

    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setCaseSensitive(false)

    const exportStore = useExportStore()
    const job = await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'evidence-json',
      scope: 'loaded',
    })

    expect(clientMocks.getExportEvidencePackage).toHaveBeenCalledTimes(1)
    expect(clientMocks.getExportEvidencePackage.mock.calls[0][0]).toMatchObject({
      query: 'Hase',
      caseInsensitive: true,
      includeRows: true,
    })
    expect(clientMocks.getExportConcordance).not.toHaveBeenCalled()
    expect(job.status).toBe('completed')
    expect(job.filename).toBe('evp_test123.json')
    expect(job.total).toBe(2)
    expect(job.exportedRows).toBe(2)
    expect(job.exportCap).toBe(1_000_000)
  })

  it('passes the visible KWIC-row choice through to EvidencePackage include_rows', async () => {
    clientMocks.getExportEvidencePackage.mockResolvedValue({
      schema_version: 'candyconc-evidence-package-v1',
      package_id: 'evp_no_rows',
      generated_at: '2026-06-19T00:00:00Z',
      query_trace_id: 'qtr_no_rows',
      scope: { query: 'Hase' },
      corpus: { name: 'default' },
      result_summary: {
        observed_hit_count: 2,
        total_matches: 2,
        exported_rows: 2,
        export_cap: 1_000_000,
        rows_included: 0,
        truncated: false,
        complete_within_export_cap: true,
        row_hash_sha256: 'a'.repeat(64),
      },
      method_blocks: [{ id: 'kwic_query_runtime' }],
      rows: [],
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'evidence-json',
      includeResults: false,
      scope: 'loaded',
    })

    expect(clientMocks.getExportEvidencePackage.mock.calls[0][0]).toMatchObject({
      includeRows: false,
    })
  })

  it('renders PDF reports from EvidencePackage instead of browser-loaded rows', async () => {
    clientMocks.getExportEvidencePackage.mockResolvedValue({
      schema_version: 'candyconc-evidence-package-v1',
      package_id: 'evp_report',
      generated_at: '2026-06-19T00:00:00Z',
      query_trace_id: 'qtr_report',
      scope: { query: 'Hase', corpus: 'default' },
      corpus: { name: 'default', fingerprint_sha256: 'b'.repeat(64) },
      result_summary: {
        observed_hit_count: 1,
        total_matches: 1,
        exported_rows: 1,
        export_cap: 1_000_000,
        rows_included: 1,
        truncated: false,
        complete_within_export_cap: true,
        row_hash_sha256: 'c'.repeat(64),
      },
      method_blocks: [{
        id: 'kwic_query_runtime',
        label: 'KWIC query runtime',
        parameters: { query: 'Hase' },
        limits: ['server evidence'],
      }],
      rows: [{ left: 'server links', node: 'SERVER_HASE', right: 'server rechts', docId: 'd1' }],
    })
    clientMocks.exportPdf.mockResolvedValue(new Blob(['pdf'], { type: 'application/pdf' }))

    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 1, left: 'browser links', match: 'BROWSER_ONLY', right: 'browser rechts', docId: 'd-browser' }],
      1,
      true,
      false,
    )

    const exportStore = useExportStore()
    const job = await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'pdf',
      includeResults: true,
      includeFrequency: true,
      scope: 'loaded',
    })

    expect(clientMocks.getExportEvidencePackage).toHaveBeenCalledTimes(1)
    expect(clientMocks.getFrequency).not.toHaveBeenCalled()
    expect(clientMocks.exportPdf).toHaveBeenCalledTimes(1)
    const markdown = clientMocks.exportPdf.mock.calls[0][0] as string
    expect(markdown).toContain('evp_report')
    expect(markdown).toContain('SERVER_HASE')
    expect(markdown).toContain('row_hash_sha256')
    expect(markdown).toContain('Frequenzliste')
    expect(markdown).not.toContain('BROWSER_ONLY')
    expect(job.status).toBe('completed')
  })

  it('blocks report export before any server call when the concrete ProductOperation is missing', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    const replay = productCapabilities.contract!.capabilities[0]!
    replay.operations = replay.operations.filter(
      (operation) => operation.id !== 'research.replay_export.pdf',
    )

    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    await expect(exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'pdf',
      includeResults: true,
      scope: 'loaded',
    })).rejects.toThrow('Serverfunktion')

    expect(clientMocks.getExportEvidencePackage).not.toHaveBeenCalled()
    expect(clientMocks.exportPdf).not.toHaveBeenCalled()
  })
})
