import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
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
import { useAnnotationsStore } from '@/stores/annotations'
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
      backend_routes: [concordancePost.path],
      backend_route_descriptors: [concordancePost],
      operations: [
        operation('research.replay_export.concordance', 'Vollständige Konkordanz exportieren', concordancePost),
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

describe('export store — server CSV carries the annotation section (ANNOTATION-02)', () => {
  let downloadedBlob: Blob | null

  beforeEach(() => {
    setActivePinia(createPinia())
    seedReplayExportContract()
    downloadedBlob = null
    vi.clearAllMocks()
    clientMocks.getExportConcordance.mockReset()

    // jsdom's Blob lacks an async .text(); use a small readable shim so both the
    // server stream blob and the appended output blob can be inspected.
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
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    vi.spyOn(document.body, 'appendChild').mockImplementation((n) => n as never)
    vi.spyOn(document.body, 'removeChild').mockImplementation((n) => n as never)
    vi.spyOn(document, 'createElement').mockImplementation(() => ({ click: vi.fn(), href: '', download: '' }) as never)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  async function seedAnnotations() {
    const annotations = useAnnotationsStore()
    // Let the empty mocked load settle, then seed the local annotation map.
    await Promise.resolve()
    await Promise.resolve()
    annotations.annotations = {
      'default::doc1:5': { categoryId: 'cat1', note: '=HYPERLINK("http://evil")', annotator: '@boss', updatedAt: 1 },
      'default::doc1:6': { categoryId: null, note: 'same corpus, different KWIC row', annotator: 'eve', updatedAt: 2 },
      'other::doc1:5': { categoryId: null, note: 'different corpus', annotator: 'mallory', updatedAt: 3 },
    }
    annotations.categories = [{ id: 'cat1', label: 'Metapher', color: '#fff' }]
  }

  it('appends only loaded-row annotations to the streamed server CSV when the box is checked', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['position,left,match,right,docId\n5,der,Hase,rennt,doc1\n'], { type: 'text/csv' }),
      filename: 'concordance.csv',
      total: 1,
      truncated: false,
    })
    await seedAnnotations()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 5, left: 'der', match: 'Hase', right: 'rennt', docId: 'doc1' }],
      1,
      true,
      false
    )

    const exportStore = useExportStore()
    const job = await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'all-server',
      includeAnnotations: true,
    })

    expect(job.status).toBe('completed')
    expect(downloadedBlob).not.toBeNull()
    const text = await downloadedBlob!.text()
    // The server stream is preserved...
    expect(text).toContain('Hase,rennt,doc1')
    // ...and the annotation section is honestly appended.
    expect(text).toContain('# Abschnitt: Annotationen')
    expect(text).toContain('Metapher')
    expect(text).toContain('default::doc1:5')
    expect(text).not.toContain('default::doc1:6')
    expect(text).not.toContain('other::doc1:5')
    // Injection-laced cells are neutralised by the shared CSV hardening.
    expect(text).toContain(`'@boss`)
    expect(text).not.toMatch(/(^|,)=HYPERLINK/m)
  })

  it('does not alter the server CSV when no annotations exist', async () => {
    clientMocks.getExportConcordance.mockResolvedValue({
      blob: new Blob(['position,left,match,right,docId\n1,der,Hase,rennt,doc1\n'], { type: 'text/csv' }),
      filename: 'concordance.csv',
      total: 1,
      truncated: false,
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    await exportStore.exportData({
      ...exportStore.defaultOptions,
      format: 'csv',
      scope: 'all-server',
      includeAnnotations: true,
    })

    const text = await downloadedBlob!.text()
    expect(text).not.toContain('# Abschnitt: Annotationen')
  })
})
