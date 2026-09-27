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
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'

/**
 * EXPORT-02 (P2 honesty): the Markdown EvidencePackage report (which PDF and
 * DOCX are rendered FROM) printed "Vollständig: ja" and the full server
 * rows_included count while only the first 500 rows actually render. The LaTeX
 * builder was already honest. This test pins the Markdown builder to the same
 * honesty: when rows are capped it must read "Vollständig: nein" + an
 * "Auszug: erste 500 von N" marker, and a <=500-row package stays "ja".
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
    package_id: 'evp_md',
    generated_at: '2026-06-22T00:00:00Z',
    query_trace_id: 'qtr_md',
    scope: { query: 'Hase' },
    corpus: { name: 'default' },
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

/** Run a PDF export and return the Markdown string handed to exportPdf(). */
async function runMarkdownExport(
  rowCount: number,
  totals: { totalMatches?: number; exportedRows?: number; exportCap?: number; truncated?: boolean } = {},
): Promise<string> {
  vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'blob:mock')
  vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
  vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n as never)
  vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n as never)
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)

  clientMocks.exportPdf.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
  clientMocks.getExportEvidencePackage.mockResolvedValue(evidencePackage(rowCount, totals))

  const queryStore = useQueryStore()
  queryStore.setTerm('Hase')

  const exportStore = useExportStore()
  await exportStore.exportData({
    ...exportStore.defaultOptions,
    format: 'pdf',
    includeResults: true,
    scope: 'loaded',
  })

  // The Markdown the report builder produced is the single string argument
  // PDF/DOCX are rendered FROM.
  return String(clientMocks.exportPdf.mock.calls.at(-1)?.[0] ?? '')
}

describe('export store — Markdown EvidencePackage honesty (EXPORT-02)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedReplayExportContract()
    vi.clearAllMocks()
    clientMocks.getExportEvidencePackage.mockReset()
  })

  it('marks a >500-row Markdown report as a truncated excerpt and flips the vollständig claim', async () => {
    const md = await runMarkdownExport(640)

    // Honest excerpt marker present (mirrors the LaTeX path).
    expect(md).toMatch(/Auszug: erste 500 von 640/)
    // The completeness claim must read "nein", not "ja".
    expect(md).toContain('Vollständige Trefferliste im Bericht: nein')
    expect(md).not.toContain('Vollständige Trefferliste im Bericht: ja')
    // The rendered row count must be the capped count, not the full one.
    expect(md).toContain('Zeilen im Bericht: 500')
    expect(md).not.toContain('Zeilen im Bericht: 640')
    // The integrity anchor stays cited.
    expect(md).toMatch(/row_hash_sha256/)
  })

  it('keeps the vollständig claim true and adds no excerpt marker when all rows fit', async () => {
    const md = await runMarkdownExport(12)

    expect(md).toContain('Vollständige Trefferliste im Bericht: ja')
    expect(md).toContain('Zeilen im Bericht: 12')
    expect(md).not.toMatch(/Auszug: erste/)
  })

  it('reports the exact denominator separately when the server row cap truncates the package', async () => {
    const md = await runMarkdownExport(3, {
      totalMatches: 5,
      exportedRows: 3,
      exportCap: 3,
      truncated: true,
    })

    expect(md).toContain('Vollständige Trefferzahl: 5')
    expect(md).toContain('Serverseitig erfasste KWIC-Zeilen: 3')
    expect(md).toContain('Exportgrenze: 3')
    expect(md).toContain('Vollständige Trefferliste im Bericht: nein')
    expect(md).toContain('Der Server hat 3 von 5 Trefferzeilen ausgegeben')
  })
})

describe('export store — the PDF report keeps queries and parameters readable', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedReplayExportContract()
    vi.clearAllMocks()
    clientMocks.getExportEvidencePackage.mockReset()
  })

  it('sets the query as code and lists the parameters one per line', async () => {
    const pkg = evidencePackage(2)
    pkg.scope = { query: 'cql:[pos="ADJ"] [lemma="freedom"%c] freedom*' }
    ;(pkg as { method_blocks: unknown[] }).method_blocks = [{
      id: 'kwic_query_runtime',
      parameters: { query: 'cql:[pos="ADJ"]', filters: { party: ['Republican'], decade: ['1940s', '1950s'] }, window: 5 },
    }]
    vi.spyOn(URL, 'createObjectURL').mockImplementation(() => 'blob:mock')
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    clientMocks.exportPdf.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
    clientMocks.getExportEvidencePackage.mockResolvedValue(pkg)
    useQueryStore().setTerm('freedom')
    const exportStore = useExportStore()
    await exportStore.exportData({ ...exportStore.defaultOptions, format: 'pdf', includeResults: true, scope: 'loaded' })
    const md = String(clientMocks.exportPdf.mock.calls.at(-1)?.[0] ?? '')

    // The query is a code span: in the PDF it keeps its straight quotes.
    expect(md).toContain('- Query: `cql:[pos="ADJ"] [lemma="freedom"%c] freedom*`')
    // No parameter line is one long inline code span any more: one line per
    // parameter, JSON with spaces at which the line can break.
    expect(md).not.toMatch(/Parameter[^\n]*`\{/)
    expect(md).toContain('  - query: `cql:[pos="ADJ"]`')
    expect(md).toContain('  - filters: `{ "party": [ "Republican" ], "decade": [ "1940s", "1950s" ] }`')
    expect(md).toContain('  - window: `5`')
  })
})
