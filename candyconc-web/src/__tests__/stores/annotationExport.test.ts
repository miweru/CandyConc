import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useExportStore, type ExportOptions } from '@/stores/export'
import { useQueryStore } from '@/stores/query'
import { useAnnotationsStore } from '@/stores/annotations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'

// Keep the analysis fetches inert; only the annotation section matters here.
vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getFrequency: vi.fn(async () => []),
    getCollocations: vi.fn(async () => []),
    exportPdf: vi.fn(),
    exportDocx: vi.fn(),
    // Annotation store APIs are not hit in these tests (we seed state directly),
    // but the corpus/docset watcher fires load() on store init.
    getAnnotations: vi.fn(async () => ({
      annotations: {
        'doc1:5': { categoryId: 'cat1', note: 'normal note', annotator: 'alice', updatedAt: 1 },
        'doc1:6': { categoryId: null, note: '=HYPERLINK("http://evil")', annotator: '@boss', updatedAt: 2 },
      },
      scheme: { categories: [{ id: 'cat1', label: 'Metapher', color: '#fff' }] },
    })),
    putAnnotation: vi.fn(async () => ({ categoryId: null, note: null, annotator: null, updatedAt: 1 })),
    deleteAnnotation: vi.fn(async () => ({ status: 'deleted' })),
    putAnnotationScheme: vi.fn(async (s: unknown) => s),
  }
})

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
    effects: ['read'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 10,
  }
}

function annotationReadOperation(routeDescriptor: ReturnType<typeof route>) {
  return {
    id: 'research.annotations.read',
    capability_id: 'research.annotations',
    label: 'Annotationen laden',
    description: '',
    route: routeDescriptor,
    effects: ['read'],
    handler_key: 'annotations_read',
    surface_slot: 'kwic.annotations.read',
    priority: 10,
  }
}

function seedReplayExportContract(): void {
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
    fingerprint_sha256: 'c'.repeat(64),
    capabilities: [{
      id: 'research.replay_export',
      title: 'Replay export',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [concordance.path, evidence.path, pdf.path, docx.path],
      backend_route_descriptors: [concordance, evidence, pdf, docx],
      operations: [
        operation('research.replay_export.concordance', 'Vollständige Konkordanz exportieren', concordance),
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
    }, {
      id: 'research.annotations',
      title: 'KWIC annotation workflow',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [annotations.path],
      backend_route_descriptors: [annotations],
      operations: [
        annotationReadOperation(annotations),
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

describe('annotation export (F7) — CSV', () => {
  let downloadedBlob: Blob | null

  beforeEach(() => {
    setActivePinia(createPinia())
    seedReplayExportContract()
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

  async function seedRowsAndAnnotations() {
    const query = useQueryStore()
    const annotations = useAnnotationsStore()
    query.setResults(
      [
        { position: 5, left: 'der', match: 'Hase', right: 'rennt', docId: 'doc1' },
        // An adversarial token that a spreadsheet would treat as a formula.
        { position: 6, left: 'die', match: '=cmd|/c calc', right: 'da', docId: 'doc1' },
        { position: 7, left: 'das', match: 'unannotated', right: 'x', docId: 'doc2' },
      ],
      3
    )
    // The annotations store starts an immediate backend load on creation.
    // Let that empty mocked load settle before seeding focused CSV state.
    await Promise.resolve()
    await Promise.resolve()
    // Seed the annotation map directly (bypassing the network). Keys are
    // corpus-namespaced exactly as rowIdFor(row, corpus) builds them; with no
    // active corpus selected the docset store resolves to 'default'.
    annotations.annotations = {
      'default::doc1:5': { categoryId: 'cat1', note: 'normal note', annotator: 'alice', updatedAt: 1 },
      // Injection-laced note + an injection-laced annotator.
      'default::doc1:6': { categoryId: null, note: '=HYPERLINK("http://evil")', annotator: '@boss', updatedAt: 2 },
    }
    annotations.categories = [{ id: 'cat1', label: 'Metapher', color: '#fff' }]
  }

  it('emits one CSV row per annotated KWIC line and neutralises injection', async () => {
    await seedRowsAndAnnotations()
    const store = useExportStore()
    await store.exportData({ ...baseOptions })

    expect(downloadedBlob).not.toBeNull()
    const text = await downloadedBlob!.text()

    expect(text).toContain('# Abschnitt: Annotationen')
    // The node column is named node, the whole hit follows as in the server export.
    expect(text).toContain('row_id,position,left,node,right,docId,category,note,annotator,match,match_start,match_end')
    // Category label resolved from the scheme.
    expect(text).toContain('Metapher')
    // The unannotated row (doc2:7) must NOT appear in the annotation section.
    expect(text).not.toContain('unannotated')

    // Formula-injection guard (utils/csv hardening): leading =/@ cells are
    // prefixed with a single quote. Cells with structural chars (quotes, here
    // from the HYPERLINK payload) are additionally quote-wrapped with `"` doubled.
    expect(text).toContain(`'=cmd|/c calc`)
    expect(text).toContain(`"'=HYPERLINK(""http://evil"")"`)
    expect(text).toContain(`'@boss`)
    // The raw, un-neutralised formula must never appear verbatim at cell start.
    expect(text).not.toMatch(/(^|,)=cmd/m)
  })

  it('honors the "by-category" row range', async () => {
    await seedRowsAndAnnotations()
    const store = useExportStore()
    await store.exportData({ ...baseOptions, rowRange: 'category', rangeCategoryId: 'cat1' })

    const text = await downloadedBlob!.text()
    // cat1 row present, the note-only injection row excluded.
    expect(text).toContain('normal note')
    expect(text).not.toContain('HYPERLINK')
  })

  it('honors the "annotated-only" row range', async () => {
    await seedRowsAndAnnotations()
    const store = useExportStore()
    await store.exportData({ ...baseOptions, rowRange: 'annotated' })

    const text = await downloadedBlob!.text()
    expect(text).toContain('normal note')
    expect(text).toContain('HYPERLINK') // both annotated rows
    expect(text).not.toContain('unannotated')
  })
})
