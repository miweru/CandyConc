import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useExportStore, type ExportOptions } from '@/stores/export'
import { useQueryStore } from '@/stores/query'
import { useAnnotationsStore } from '@/stores/annotations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'

/**
 * The server concordance exports name the whole hit (`match`, `match_start`,
 * `match_end`, commit 223ddd1a9). The exports built in the browser wrote the
 * node token alone into their `match` column (client.ts maps `kw` to `match`),
 * so for `cql:[pos="ADJ"] [lemma="freedom"]` they said "freedom" where the
 * server export says "political freedom".
 */

const clientMocks = vi.hoisted(() => ({
  exportPdf: vi.fn(),
  exportDocx: vi.fn(),
  getExportEvidencePackage: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getFrequency: vi.fn(async () => []),
    getCollocations: vi.fn(async () => []),
    exportPdf: clientMocks.exportPdf,
    exportDocx: clientMocks.exportDocx,
    getExportEvidencePackage: clientMocks.getExportEvidencePackage,
    getAnnotations: vi.fn(async () => ({
      annotations: { '0:1104': { categoryId: null, note: 'Wertbegriff', annotator: 'alice', updatedAt: 1 } },
      scheme: { categories: [] },
    })),
    putAnnotation: vi.fn(async () => ({ categoryId: null, note: null, annotator: null, updatedAt: 1 })),
    deleteAnnotation: vi.fn(async () => ({ status: 'deleted' })),
    putAnnotationScheme: vi.fn(async (s: unknown) => s),
  }
})

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

function operation(id: string, capabilityId: string, routeDescriptor: ReturnType<typeof route>) {
  return {
    id,
    capability_id: capabilityId,
    label: id,
    description: '',
    route: routeDescriptor,
    effects: ['read'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 10,
  }
}

function capability(id: string, routes: Array<ReturnType<typeof route>>, operations: unknown[]) {
  return {
    id,
    title: id,
    area: 'research_workflow',
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
    notes: '',
  }
}

function seedContract(): void {
  const concordance = route('/api/v1/export/concordance', 'POST')
  const evidence = route('/api/v1/export/evidence-package', 'POST')
  const pdf = route('/api/v1/export/pdf', 'POST')
  const docx = route('/api/v1/export/docx', 'POST')
  const annotations = route('/api/v1/annotations', 'GET')
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'd'.repeat(64),
    capabilities: [
      capability('research.replay_export', [concordance, evidence, pdf, docx], [
        operation('research.replay_export.concordance', 'research.replay_export', concordance),
        operation('research.replay_export.evidence_package', 'research.replay_export', evidence),
        operation('research.replay_export.pdf', 'research.replay_export', pdf),
        operation('research.replay_export.docx', 'research.replay_export', docx),
      ]),
      capability('research.annotations', [annotations], [
        operation('research.annotations.read', 'research.annotations', annotations),
      ]),
    ],
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

const baseOptions: ExportOptions = {
  format: 'csv',
  includeResults: false,
  includeFrequency: false,
  includeCollocations: false,
  includeStatistics: false,
  includeContext: true,
  includeMetadata: true,
  includeReproMeta: false,
  includeAnnotations: true,
  rowRange: 'all',
}

// The first line of cql:[pos="ADJ"] [lemma="freedom"] on the SOTU sample,
// as GET /api/v1/query delivers it and client.ts maps it.
const twoTokenRow = {
  position: 1104,
  left: 'of religious tolerance , political',
  match: 'freedom',
  right: 'and economic opportunity . For',
  docId: '0',
  matchOffsets: [-1],
}

function evidencePackage() {
  return {
    schema_version: 'candyconc-evidence-package-v1',
    package_id: 'evp_span',
    generated_at: '2026-09-27T00:00:00Z',
    query_trace_id: 'qtr_span',
    scope: { query: 'cql:[pos="ADJ"] [lemma="freedom"]' },
    corpus: { name: 'sotu_en' },
    result_summary: {
      observed_hit_count: 1,
      total_matches: 1,
      exported_rows: 1,
      export_cap: 1_000_000,
      rows_included: 1,
      truncated: false,
      complete_within_export_cap: true,
      row_hash_sha256: 'a'.repeat(64),
    },
    method_blocks: [{ id: 'kwic_query_runtime' }],
    // A package row as _export_row_payload writes it.
    rows: [{
      pos: 1104,
      doc_id: 0,
      docId: 0,
      doc: 'sotu-1945-Truman',
      left: 'of religious tolerance , political',
      node: 'freedom',
      right: 'and economic opportunity . For',
      match: 'political freedom',
      match_start: 1103,
      match_end: 1104,
    }],
  }
}

describe('local exports name the whole hit like the server exports', () => {
  let downloadedBlob: Blob | null

  beforeEach(() => {
    setActivePinia(createPinia())
    seedContract()
    downloadedBlob = null
    vi.clearAllMocks()

    class ReadableBlob {
      readonly parts: BlobPart[]
      readonly type: string
      constructor(parts: BlobPart[], options?: BlobPropertyBag) {
        this.parts = parts
        this.type = options?.type ?? ''
      }
      async text(): Promise<string> {
        return this.parts.map((p) => String(p)).join('')
      }
    }
    vi.stubGlobal('Blob', ReadableBlob)
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      downloadedBlob = blob as Blob
      return 'blob:test'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => {})
    vi.spyOn(document.body, 'appendChild').mockImplementation((node) => node as never)
    vi.spyOn(document.body, 'removeChild').mockImplementation((node) => node as never)
    vi.spyOn(document, 'createElement').mockImplementation(() => ({ click: vi.fn(), href: '', download: '' }) as never)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('writes node and whole hit into the annotation section of a CSV export', async () => {
    const query = useQueryStore()
    const annotations = useAnnotationsStore()
    query.setResults([twoTokenRow], 1)
    await vi.waitFor(() => expect(annotations.getAnnotation('default::0:1104')).toBeTruthy())
    annotations.annotations = {
      'default::0:1104': { categoryId: null, note: 'Wertbegriff', annotator: 'alice', updatedAt: 1 },
    }

    await useExportStore().exportData({ ...baseOptions })
    const lines = (await downloadedBlob!.text()).split('\n')
    const header = lines.findIndex((line) => line.startsWith('row_id,'))
    expect(lines[header]).toBe(
      'row_id,position,left,node,right,docId,category,note,annotator,match,match_start,match_end',
    )
    expect(lines[header + 1]).toBe(
      'default::0:1104,1104,"of religious tolerance , political",freedom,and economic opportunity . For,0,,Wertbegriff,alice,political freedom,1103,1104',
    )
  })

  it('shows the whole hit in the Markdown report behind PDF and DOCX', async () => {
    clientMocks.exportPdf.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
    clientMocks.getExportEvidencePackage.mockResolvedValue(evidencePackage())
    useQueryStore().setTerm('cql:[pos="ADJ"] [lemma="freedom"]')

    await useExportStore().exportData({ ...baseOptions, format: 'pdf', includeResults: true, includeAnnotations: false })
    const md = String(clientMocks.exportPdf.mock.calls.at(-1)?.[0] ?? '')
    expect(md).toContain('| # | Links | Treffer | Rechts | Ganzer Treffer | Dokument |')
    expect(md).toContain('|---:|---|---|---|---|---|')
    expect(md).toContain(
      // The document column names the document (doc), not its internal number (docId 0).
      '| 1 | of religious tolerance , political | freedom | and economic opportunity . For | political freedom | sotu-1945-Truman |',
    )
  })

  it('shows the whole hit in the LaTeX report', async () => {
    clientMocks.getExportEvidencePackage.mockResolvedValue(evidencePackage())
    useQueryStore().setTerm('cql:[pos="ADJ"] [lemma="freedom"]')

    await useExportStore().exportData({ ...baseOptions, format: 'latex', includeResults: true, includeAnnotations: false })
    const tex = await downloadedBlob!.text()
    expect(tex).toContain('\\begin{longtable}{rlllll}')
    expect(tex).toContain('Index & Links & Treffer & Rechts & Ganzer Treffer & Dokument \\\\')
    expect(tex).toContain(
      '1 & of religious tolerance , political & freedom & and economic opportunity . For & political freedom & sotu-1945-Truman \\\\',
    )
  })

  it('falls back to the node for packages written before match existed', async () => {
    const pkg = evidencePackage()
    const { match: _match, match_start: _start, match_end: _end, ...legacyRow } = pkg.rows[0]!
    clientMocks.exportPdf.mockResolvedValue(new Blob(['%PDF'], { type: 'application/pdf' }))
    clientMocks.getExportEvidencePackage.mockResolvedValue({ ...pkg, rows: [legacyRow] })
    useQueryStore().setTerm('freedom')

    await useExportStore().exportData({ ...baseOptions, format: 'pdf', includeResults: true, includeAnnotations: false })
    const md = String(clientMocks.exportPdf.mock.calls.at(-1)?.[0] ?? '')
    expect(md).toContain('| freedom | and economic opportunity . For | freedom | sotu-1945-Truman |')
  })
})
