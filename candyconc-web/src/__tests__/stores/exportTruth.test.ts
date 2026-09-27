import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useExportStore, type ExportOptions } from '@/stores/export'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useSettingsStore } from '@/stores/settings'
import { getCollocations, getFrequency } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getFrequency: vi.fn(async () => [
      { item: 'Hase', frequency: 3, relative: 0.3 },
    ]),
    getCollocations: vi.fn(async () => [
      { word: 'schnell', frequency: 2, measure: 'logdice', score: 4.2 },
    ]),
    exportPdf: vi.fn(),
    exportDocx: vi.fn(),
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

function operation(
  capabilityId: string,
  id: string,
  label: string,
  routeDescriptor: ReturnType<typeof route>,
) {
  return {
    id,
    capability_id: capabilityId,
    label,
    description: '',
    route: routeDescriptor,
    effects: ['read'],
    handler_key: id.split('.').at(-1) ?? id,
    surface_slot: id,
    priority: 10,
  }
}

function seedExportContract(): void {
  const concordancePost = route('/api/v1/export/concordance', 'POST')
  const evidence = route('/api/v1/export/evidence-package', 'POST')
  const pdf = route('/api/v1/export/pdf', 'POST')
  const docx = route('/api/v1/export/docx', 'POST')
  const frequency = route('/api/v1/analysis/frequency_list', 'GET')
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'b'.repeat(64),
    capabilities: [
      {
        id: 'research.replay_export',
        title: 'Replay export',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [concordancePost.path, evidence.path, pdf.path, docx.path],
        backend_route_descriptors: [concordancePost, evidence, pdf, docx],
        operations: [
          operation('research.replay_export', 'research.replay_export.concordance', 'Vollständige Konkordanz exportieren', concordancePost),
          operation('research.replay_export', 'research.replay_export.evidence_package', 'EvidencePackage exportieren', evidence),
          operation('research.replay_export', 'research.replay_export.pdf', 'PDF-Report exportieren', pdf),
          operation('research.replay_export', 'research.replay_export.docx', 'DOCX-Report exportieren', docx),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
        notes: '',
      },
      {
        id: 'analysis.frequency',
        title: 'Frequency',
        area: 'analysis',
        maturity: 'stable',
        visibility: 'first_class_ui',
        backend_routes: [frequency.path],
        backend_route_descriptors: [frequency],
        operations: [
          operation('analysis.frequency', 'analysis.frequency.list', 'Frequenzliste', frequency),
        ],
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

describe('export truth labels', () => {
  let downloadedBlob: Blob | null

  beforeEach(() => {
    setActivePinia(createPinia())
    seedExportContract()
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
        return this.parts.map((part) => String(part)).join('')
      }
    }

    vi.stubGlobal('Blob', ReadableBlob)
    vi.spyOn(URL, 'createObjectURL').mockImplementation((blob) => {
      downloadedBlob = blob as Blob
      return 'blob:candyconc-test'
    })
    vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
  })



  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('writes CSV section metadata without pretending loaded rows are all hits', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [
        { position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' },
        { position: 2, left: 'ein', match: 'Hase', right: 'springt', docId: 'd2' },
      ],
      120,
      true,
      true,
    )

    const exportStore = useExportStore()
    await exportStore.exportData({
      ...baseOptions,
      includeResults: false,
      includeFrequency: true,
      includeCollocations: false,
    })

    expect(downloadedBlob).not.toBeNull()
    const csv = await downloadedBlob!.text()
    expect(csv).toContain('# Gesamtzählung der Suche: ≥ 120')
    expect(csv).toContain('# Trefferzeilen im Export: 0')
    expect(csv).toContain('# Trefferzeilen-Scope: alle aktuell geladenen Trefferzeilen')
    expect(csv).not.toContain('# Abschnitt: Geladene KWIC-Trefferzeilen')
    expect(csv).toContain('# Abschnitt: Frequenzliste (Top 50)')
    expect(getFrequency).toHaveBeenCalledTimes(1)
    expect(getCollocations).not.toHaveBeenCalled()
  })

  it.each([false, true])('retains the sampled search population in analysis CSV metadata, partial=%s', async (populationPartial) => {
    const query = useQueryStore()
    query.setTerm('the')
    query.setResults([], 200, true, false)
    query.setSampleProvenance({ requested: 200, drawn: 200, seed: 526085, population: 20907, populationPartial })
    await useExportStore().exportData({ ...baseOptions, includeFrequency: true })
    const csv = await downloadedBlob!.text()
    expect(csv).toContain(`# Gesamtzählung der Suche: ${populationPartial ? '≥ ' : ''}20907`)
    expect(csv).toContain('# Trefferzeilen im Export: 0')
    expect(csv).not.toContain('# Gesamtzählung der Suche: 200')
    expect(csv).not.toContain('Zufallsstichprobe:')
  })

  it('uses the active corpus catalogue count for CSV statistics and frequency requests', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setFilters({ corpus: 'default' })

    const corpusStore = useCorpusCapabilitiesStore()
    corpusStore.corpora = [{
      name: 'default',
      path: '/corpora/default',
      active: true,
      token_count: 56_191,
      doc_count: 2_000,
      import_mode: 'registered',
      paired: false,
      pair_axes: [],
      is_legacy: false,
      capabilities: {},
    }]

    const settingsStore = useSettingsStore()
    settingsStore.systemInfo = {
      backendVersion: '0.1.0',
      uptime: '',
      faissStatus: 'unavailable',
      vectorCount: 0,
      cacheSize: '0 MB',
      corpusName: 'Kein Korpus geladen',
      tokenCount: 0,
      documentCount: 0,
    }

    const exportStore = useExportStore()
    await exportStore.exportData({
      ...baseOptions,
      includeFrequency: true,
      includeStatistics: true,
    })

    expect(downloadedBlob).not.toBeNull()
    const csv = await downloadedBlob!.text()
    expect(csv).toContain('# Token im Korpus: 56191')
    expect(csv).toContain('# Dokumente im Korpus: 2000')
    expect(getFrequency).toHaveBeenCalledWith(expect.objectContaining({
      corpus: 'default',
      tokenCount: 56_191,
    }))
    expect(csv).not.toContain('# Token im Korpus: 0')
    expect(csv).not.toContain('# Dokumente im Korpus: 0')
  })

  it('blocks pure loaded-browser CSV exports without ProductOperation authority', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' }],
      1,
      true,
      false,
    )

    const exportStore = useExportStore()
    const options = {
      ...baseOptions,
      includeResults: true,
      includeFrequency: false,
      includeCollocations: false,
      includeAnnotations: false,
      scope: 'loaded' as const,
    }

    expect(exportStore.exportOptionsAvailability(options)).toMatchObject({
      enabled: false,
      operationIds: [],
    })
    expect(exportStore.exportOptionsAvailability(options).disabledReason).toContain('lokaler Auszug')
    await expect(exportStore.exportData(options)).rejects.toThrow('lokaler Auszug')
    expect(downloadedBlob).toBeNull()
  })

  it('blocks loaded-browser KWIC rows even when a supplemental section has ProductOperation authority', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' }],
      1,
      true,
      false,
    )

    const exportStore = useExportStore()
    const options = {
      ...baseOptions,
      includeResults: true,
      includeFrequency: true,
      includeCollocations: false,
      includeAnnotations: false,
      scope: 'loaded' as const,
    }

    expect(exportStore.exportOptionsAvailability(options)).toMatchObject({
      enabled: false,
      operationIds: ['analysis.frequency.list'],
    })
    expect(exportStore.exportOptionsAvailability(options).disabledReason).toContain('lokaler Auszug')
    await expect(exportStore.exportData(options)).rejects.toThrow('lokaler Auszug')
    expect(getFrequency).not.toHaveBeenCalled()
    expect(downloadedBlob).toBeNull()
  })

  it('blocks collocation export instead of using the synchronous expert API', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const exportStore = useExportStore()
    await expect(exportStore.exportData({
      ...baseOptions,
      includeResults: false,
      includeFrequency: true,
      includeCollocations: true,
    })).rejects.toThrow('scope-stabil über Analysejobs')

    expect(getCollocations).not.toHaveBeenCalled()
  })
})
