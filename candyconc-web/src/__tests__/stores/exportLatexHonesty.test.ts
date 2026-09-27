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

import { useExportStore, type ExportOptions } from '@/stores/export'
import { useQueryStore } from '@/stores/query'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'

/**
 * EXPORT-02 (P2 honesty): a >200-row EvidencePackage LaTeX export used to slice
 * to 200 rows silently while still printing "Vollständig innerhalb Exportgrenze:
 * ja". The report must instead be HONEST — mark the excerpt and flip the
 * completeness claim — when it cannot render every row.
 */

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
  } as never
}

function evidencePackage(
  rowCount: number,
  totals: { totalMatches?: number; exportedRows?: number; exportCap?: number; truncated?: boolean } = {},
) {
  const totalMatches = totals.totalMatches ?? rowCount
  const exportedRows = totals.exportedRows ?? rowCount
  return {
    schema_version: 'candyconc-evidence-package-v1',
    package_id: 'evp_latex',
    generated_at: '2026-06-22T00:00:00Z',
    query_trace_id: 'qtr_latex',
    scope: { query: 'Hase', docset_id: 'docset-alpha' },
    corpus: {
      name: 'default',
      fingerprint_sha256: 'b'.repeat(64),
      docset_fingerprint_sha256: 'c'.repeat(64),
    },
    result_summary: {
      observed_hit_count: rowCount,
      total_matches: totalMatches,
      exported_rows: exportedRows,
      export_cap: totals.exportCap ?? exportedRows,
      rows_included: rowCount,
      truncated: totals.truncated ?? false,
      complete_within_export_cap: !totals.truncated,
      row_hash_sha256: 'a'.repeat(64),
    },
    method_blocks: [{ id: 'kwic_query_runtime' }],
    rows: Array.from({ length: rowCount }, (_, i) => ({
      left: `links ${i}`,
      node: `NODE_${i}`,
      right: `rechts ${i}`,
      docId: `d${i}`,
    })),
  }
}

function readBlobText(blob: Blob): Promise<string> {
  // jsdom Blob lacks .text(); FileReader is available.
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
}

async function runLatexExport(
  rowCount: number,
  options: Partial<ExportOptions> = {},
  totals: { totalMatches?: number; exportedRows?: number; exportCap?: number; truncated?: boolean } = {},
): Promise<string> {
  // Capture the .tex Blob that downloadBlob() hands to URL.createObjectURL.
  let capturedBlob: Blob | null = null
  vi.spyOn(URL, 'createObjectURL').mockImplementation((blob: Blob) => {
    if (blob.type.includes('tex')) capturedBlob = blob
    return 'blob:mock'
  })
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n as never)
  vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n as never)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

  const queryStore = useQueryStore()
  queryStore.setTerm('Hase')

  const exportStore = useExportStore()
  clientMocks.getExportEvidencePackage.mockResolvedValue(evidencePackage(rowCount, totals))
  await exportStore.exportData({
    ...exportStore.defaultOptions,
    format: 'latex',
    includeResults: true,
    scope: 'loaded',
    ...options,
  })

  return capturedBlob ? await readBlobText(capturedBlob) : ''
}

describe('export store — LaTeX EvidencePackage honesty (EXPORT-02)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedReplayExportContract()
    vi.clearAllMocks()
    clientMocks.getExportEvidencePackage.mockReset()
  })

  it('marks a >500-row LaTeX report as a truncated excerpt and flips the vollständig claim', async () => {
    const latex = await runLatexExport(640)

    // Honest excerpt marker present.
    expect(latex).toMatch(/Auszug: erste 500 von 640/)
    // The completeness claim must now read "nein", not "ja".
    expect(latex).toContain('Vollständige Trefferliste im Bericht: nein')
    expect(latex).not.toContain('Vollständige Trefferliste im Bericht: ja')
    // The integrity anchor stays cited.
    expect(latex).toMatch(/row\\_hash\\_sha256/)
    // Only the first 500 rows are emitted (LaTeX escapes "_" to "\_"); row index
    // 500 is absent, 499 present.
    expect(latex).toContain('NODE\\_499 ')
    expect(latex).not.toContain('NODE\\_500 ')
  })

  it('keeps the vollständig claim true and adds no excerpt note when all rows fit', async () => {
    const latex = await runLatexExport(12)

    expect(latex).toContain('Generiert: 2026-06-22T00:00:00Z')
    expect(latex).toContain('Query-Trace-ID: qtr\\_latex')
    expect(latex).toContain('Docset: docset-alpha')
    expect(latex).toContain(`Corpus-Fingerprint: \\texttt{${'b'.repeat(64)}}`)
    expect(latex).toContain(`Docset-Fingerprint: \\texttt{${'c'.repeat(64)}}`)
    expect(latex).toContain('Vollständige Trefferzahl: 12')
    expect(latex).toContain('Zeilen im Bericht: 12')
    expect(latex).toContain('Abgeschnitten: nein')
    expect(latex).toContain('Vollständige Trefferliste im Bericht: ja')
    expect(latex).not.toMatch(/Auszug: erste/)
    expect(latex).toContain('NODE\\_11 ')
  })

  it('keeps total matches distinct from the bounded row payload', async () => {
    const latex = await runLatexExport(3, {}, {
      totalMatches: 5,
      exportedRows: 3,
      exportCap: 3,
      truncated: true,
    })

    expect(latex).toContain('Vollständige Trefferzahl: 5')
    expect(latex).toContain('Serverseitig erfasste KWIC-Zeilen: 3')
    expect(latex).toContain('Exportgrenze: 3')
    expect(latex).toContain('Vollständige Trefferliste im Bericht: nein')
    expect(latex).toContain('Der Server hat 3 von 5 Trefferzeilen ausgegeben')
  })

  it('names requested sections that are not part of the EvidencePackage report', async () => {
    const latex = await runLatexExport(12, {
      includeFrequency: true,
      includeAnnotations: true,
      includeCollocations: true,
    })

    expect(latex).toContain('Nicht gerenderte gewünschte Abschnitte')
    expect(latex).toContain('Frequenzliste, Annotationen, Kollokationen')
    expect(latex).toContain('nicht clientseitig aus Browserzustand ergänzt')
  })
})
