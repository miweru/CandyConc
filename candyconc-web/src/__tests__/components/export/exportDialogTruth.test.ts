import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import ExportDialog from '@/components/export/ExportDialog.vue'
import { useExportStore } from '@/stores/export'
import { useAnnotationsStore } from '@/stores/annotations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useSessionStore } from '@/stores/session'
import { useUiStore } from '@/stores/ui'
import type { ProductCapabilityContract } from '@/api/client'

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
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [{
      id: 'research.replay_export',
      title: 'Replay export',
      area: 'research_workflow',
      maturity: 'guarded',
      visibility: 'first_class_ui',
      backend_routes: [concordancePost.path, evidence.path, pdf.path, docx.path],
      backend_route_descriptors: [concordancePost, evidence, pdf, docx],
      operations: [
        {
          id: 'research.replay_export.concordance',
          capability_id: 'research.replay_export',
          label: 'Vollständige Konkordanz exportieren',
          description: '',
          route: concordancePost,
          effects: ['read'],
          handler_key: 'concordance',
          surface_slot: 'research.replay_export.concordance',
          priority: 10,
        },
        {
          id: 'research.replay_export.evidence_package',
          capability_id: 'research.replay_export',
          label: 'EvidencePackage exportieren',
          description: '',
          route: evidence,
          effects: ['read'],
          handler_key: 'evidence_package',
          surface_slot: 'research.replay_export.evidence_package',
          priority: 10,
        },
        {
          id: 'research.replay_export.pdf',
          capability_id: 'research.replay_export',
          label: 'PDF-Report exportieren',
          description: '',
          route: pdf,
          effects: ['read'],
          handler_key: 'pdf',
          surface_slot: 'research.replay_export.pdf',
          priority: 10,
        },
        {
          id: 'research.replay_export.docx',
          capability_id: 'research.replay_export',
          label: 'DOCX-Report exportieren',
          description: '',
          route: docx,
          effects: ['read'],
          handler_key: 'docx',
          surface_slot: 'research.replay_export.docx',
          priority: 10,
        },
      ],
      frontend_evidence: [],
      action_types: [],
      copilot_tools: [],
      preconditions: [],
      requires_corpus_features: [],
      limits: [],
    }],
  } as ProductCapabilityContract

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

function removeReplayExportOperation(operationId: string): void {
  const productCapabilities = useProductCapabilitiesStore()
  const replay = productCapabilities.contract?.capabilities.find((capability) =>
    capability.id === 'research.replay_export'
  )
  if (!replay) throw new Error('Replay-Export-Testcontract fehlt')
  replay.operations = replay.operations.filter((operation) => operation.id !== operationId)
}

const stubs = {
  Modal: {
    template: '<section><slot /><slot name="footer" /></section>',
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

describe('ExportDialog truth labels', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedReplayExportContract()
  })

  it('separates loaded export rows from the complete search count', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    const queryStore = useQueryStore()
    queryStore.setResults(
      [
        { position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' },
        { position: 2, left: 'ein', match: 'Hase', right: 'springt', docId: 'd2' },
      ],
      120,
      true,
      true,
    )

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    expect(wrapper.text()).toContain('2 geladene Zeilen')
    // The count is exact (totalKnown), only the rows are partial: no lower
    // bound marker (erprobung B11).
    expect(wrapper.text()).toContain('Gesamtzählung: 120 Treffer')
    expect(wrapper.text()).not.toContain('≥ 120')
    expect(wrapper.text()).toContain('Die separate Gesamtzählung beschreibt die Suchmenge, nicht den Exportumfang')
  })

  it.each([false, true])('shows the sampled population and seed, with partial=%s', async (populationPartial) => {
    const query = useQueryStore()
    query.setTerm('the')
    query.setResults(Array.from({ length: 200 }, (_, position) => (
      { position, left: '', match: 'the', right: '' }
    )), 200, true, false)
    query.setSampleProvenance({ requested: 200, drawn: 200, seed: 526085, population: 20907, populationPartial })
    const wrapper = mount(ExportDialog, { props: { modelValue: true }, global: { stubs } })

    expect(wrapper.text()).toContain(populationPartial
      ? 'Gesamtzählung: ≥ 20.907 Treffer (partiell)'
      : 'Gesamtzählung: 20.907 Treffer')
    expect(wrapper.text()).toContain('Zufallsstichprobe: 200 von 20.907 Treffern')
    expect(wrapper.text()).toContain('Seed 526085')
    expect(wrapper.text()).not.toContain('Gesamtzählung: 200 Treffer')

    await wrapper.get('input[value="all-server"]').setValue()
    expect(wrapper.text()).toContain('Der Serverexport wiederholt die Suche ohne Stichprobe.')
    await wrapper.get('input[value="loaded"]').setValue()
    expect(wrapper.text()).not.toContain('Der Serverexport wiederholt die Suche ohne Stichprobe.')

    query.setResults([], 20907, true, true)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain('Seed 526085')
    expect(wrapper.text()).toContain('Gesamtzählung: 20.907 Treffer')
  })

  it('offers the server-side full-export scope (F2)', () => {
    const pinia = createPinia()
    setActivePinia(pinia)

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    expect(wrapper.text()).toContain('Trefferumfang')
    expect(wrapper.text()).toContain('Server-Konkordanz (vollständig gezählt)')
    expect(wrapper.text()).toContain('Server-Konkordanz / lokaler Auszug')
    expect(wrapper.text()).toContain('TSV')
    expect(wrapper.text()).toContain('JSONL')
  })

  it('offers XLSX as a server concordance format with server scope semantics', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const xlsxButton = wrapper.findAll('.format-btn').find((button) =>
      button.text().includes('XLSX') && button.text().includes('Server-Konkordanz')
    )
    expect(xlsxButton).toBeDefined()
    expect(xlsxButton?.text()).toContain('Provenienz: Backend-Query + Scope')
    expect(xlsxButton?.text()).toContain('Füllstand: vollständige Zählung, Zeilen ggf. begrenzt')

    await xlsxButton?.trigger('click')
    expect(wrapper.find<HTMLInputElement>('input[value="all-server"]').element.checked).toBe(true)
    expect(wrapper.text()).toContain('XLSX-Datei')
  })

  it('gates annotations off for the XLSX stream like the other non-CSV streams', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    const annotationsStore = useAnnotationsStore()
    annotationsStore.annotations = {
      'default::d1:1': { categoryId: 'cat1', note: 'prüfen', annotator: 'alice', updatedAt: 1 },
    }

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    await wrapper.findAll('.format-btn').find((button) => button.text().includes('XLSX'))?.trigger('click')

    const annotationItem = wrapper
      .findAll('.checkbox-item')
      .find((item) => item.text().includes('Annotationen einschließen'))
    expect(annotationItem?.find('input').attributes('disabled')).toBeDefined()
    expect(annotationItem?.text()).toContain('nur im CSV-Export verfügbar')
  })

  it('offers the Excel-compatible CSV dialect only for the server CSV stream', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const serverCsv = wrapper.findAll('.format-btn').find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: vollständige Zählung, Zeilen ggf. begrenzt')
    )
    await serverCsv?.trigger('click')
    const dialectBox = wrapper.find('[data-testid="excel-csv-dialect"]')
    expect(dialectBox.exists()).toBe(true)
    expect(dialectBox.text()).toContain('Excel-kompatibles CSV (Semikolon, BOM)')
    expect(dialectBox.text()).toContain('Standard-CSV bleibt unverändert')
    // Neutral register: no recommendation labels anywhere in the dialog.
    expect(wrapper.text()).not.toContain('empfohlen')
    expect(wrapper.text()).not.toContain('recommended')

    // Loaded-browser CSV builds its file client-side — no dialect switch.
    const loadedCsv = wrapper.findAll('.format-btn').find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: geladener Auszug')
    )
    await loadedCsv?.trigger('click')
    expect(wrapper.find('[data-testid="excel-csv-dialect"]').exists()).toBe(false)

    // XLSX has no CSV dialect either.
    await wrapper.findAll('.format-btn').find((button) => button.text().includes('XLSX'))?.trigger('click')
    expect(wrapper.find('[data-testid="excel-csv-dialect"]').exists()).toBe(false)
  })

  it('marks annotations as not carryable while the Excel CSV dialect is active', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    const annotationsStore = useAnnotationsStore()
    annotationsStore.annotations = {
      'default::d1:1': { categoryId: 'cat1', note: 'prüfen', annotator: 'alice', updatedAt: 1 },
    }

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const serverCsv = wrapper.findAll('.format-btn').find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: vollständige Zählung, Zeilen ggf. begrenzt')
    )
    await serverCsv?.trigger('click')
    await wrapper.find('[data-testid="excel-csv-dialect"] input').setValue(true)

    const annotationItem = wrapper
      .findAll('.checkbox-item')
      .find((item) => item.text().includes('Annotationen einschließen'))
    expect(annotationItem?.find('input').attributes('disabled')).toBeDefined()
    expect(annotationItem?.text()).toContain('im Excel-kompatiblen CSV-Dialekt nicht enthalten')
  })

  it('offers no staged publication-template selector', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    // The former template selector only ever changed the report H1 string;
    // it must not resurface as a fake publication-format feature.
    expect(wrapper.text()).not.toContain('Export-Style')
    expect(wrapper.text()).not.toContain('ACL (2-column)')
    expect(wrapper.text()).not.toContain('Linguistics (Journal)')
    expect(wrapper.text()).not.toContain('Computational Linguistics')
    expect(wrapper.text()).not.toContain('Templates ·')
  })

  it('groups export formats by source and shows fill-level evidence for each group', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' }],
      12,
      true,
      false,
    )

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    expect(wrapper.text()).toContain('Konkordanzdatei (Server)')
    expect(wrapper.text()).toContain('EvidencePackage / Report')
    expect(wrapper.text()).not.toContain('EvidencePackage / Replay')
    expect(wrapper.text()).toContain('Geladener Auszug')
    expect(wrapper.text()).toContain('Provenienz: Backend-Query + Scope')
    expect(wrapper.text()).toContain('Füllstand: vollständige Zählung, Zeilen ggf. begrenzt')
    expect(wrapper.text()).toContain('Provenienz: EvidencePackage')
    expect(wrapper.text()).toContain('Füllstand: vollständige Zählung, Evidenzzeilen ggf. begrenzt')
    expect(wrapper.text()).toContain('Provenienz: Browser-Zustand')
    expect(wrapper.text()).toContain('Füllstand: geladener Auszug')

    const buttons = wrapper.findAll('.format-btn')
    const serverCsv = buttons.find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: vollständige Zählung, Zeilen ggf. begrenzt')
    )
    const loadedCsv = buttons.find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: geladener Auszug')
    )
    const evidenceJson = buttons.find((button) => button.text().includes('Evidence JSON'))

    await serverCsv?.trigger('click')
    expect(wrapper.find<HTMLInputElement>('input[value="all-server"]').element.checked).toBe(true)

    await loadedCsv?.trigger('click')
    expect(wrapper.find<HTMLInputElement>('input[value="loaded"]').element.checked).toBe(true)

    await evidenceJson?.trigger('click')
    expect(wrapper.text()).toContain('Serverseitiger EvidencePackage-Workflow')
  })

  it('keeps pure loaded-browser CSV visibly separate from full server exports', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 1, left: 'der', match: 'Hase', right: 'läuft', docId: 'd1' }],
      1,
      true,
      false,
    )

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const exportButton = wrapper.findAll('button').find((button) => button.text().includes('Exportieren'))
    expect(wrapper.text()).toContain('Geladener Auszug')
    expect(wrapper.text()).toContain('Provenienz: Browser-Zustand')
    expect(wrapper.text()).toContain('Füllstand: geladener Auszug')
    expect(wrapper.text()).not.toContain('Backend-Workflow')
    expect(wrapper.text()).not.toContain('keine serverseitige ProductOperation')
    expect(exportButton?.attributes('disabled')).toBeDefined()
  })

  it('models full-concordance export as the POST ProductOperation, not the legacy GET route', () => {
    const productCapabilities = useProductCapabilitiesStore()
    const replay = productCapabilities.contract?.capabilities.find((capability) =>
      capability.id === 'research.replay_export'
    )
    const concordance = replay?.operations.find((operation) =>
      operation.id === 'research.replay_export.concordance'
    )

    expect(replay?.backend_route_descriptors).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ path: '/api/v1/export/concordance', methods: ['POST'] }),
      ]),
    )
    expect(concordance?.route.methods).toEqual(['POST'])
  })

  it('consumes replay-export ProductOperation intent as a focused PDF format', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    const uiStore = useUiStore()
    queryStore.setTerm('Hase')
    uiStore.focusProductOperation('research.replay_export.pdf', {
      capabilityId: 'research.replay_export',
      surfaceSlot: 'research.replay_export.pdf',
      preferredMode: 'pdf',
    })

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const pdfButton = wrapper.findAll('.format-btn').find((button) => button.text().includes('PDF'))
    const docxButton = wrapper.findAll('.format-btn').find((button) => button.text().includes('Word'))
    expect(pdfButton?.classes()).toContain('active')
    expect(pdfButton?.classes()).toContain('operation-focused')
    expect(docxButton?.classes()).not.toContain('active')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('opens a preselected header PDF export as PDF on initial mount', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    const exportStore = useExportStore()
    queryStore.setTerm('Hase')
    exportStore.setPreselectedFormat('pdf')

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const pdfButton = wrapper.findAll('.format-btn').find((button) => button.text().includes('PDF'))
    const loadedCsvButton = wrapper.findAll('.format-btn').find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: geladener Auszug')
    )
    expect(pdfButton?.classes()).toContain('active')
    expect(loadedCsvButton?.classes()).not.toContain('active')
    expect(wrapper.text()).toContain('Serverseitiger EvidencePackage-Workflow')
    expect(wrapper.text()).toContain('KWIC-Zeilen aus EvidencePackage')
  })

  it('opens a preselected header CSV export as full server concordance, not a blocked loaded excerpt', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    const exportStore = useExportStore()
    queryStore.setTerm('Hase')
    exportStore.setPreselectedFormat('csv')

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const serverCsvButton = wrapper.findAll('.format-btn').find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: vollständige Zählung, Zeilen ggf. begrenzt')
    )
    const loadedCsvButton = wrapper.findAll('.format-btn').find((button) =>
      button.text().includes('CSV') && button.text().includes('Füllstand: geladener Auszug')
    )
    const serverScope = wrapper.find<HTMLInputElement>('input[value="all-server"]')
    const exportButton = wrapper.findAll('button').find((button) => button.text().includes('Exportieren'))

    expect(serverCsvButton?.classes()).toContain('active')
    expect(loadedCsvButton?.classes()).not.toContain('active')
    expect(serverScope.element.checked).toBe(true)
    expect(exportButton?.attributes('disabled')).toBeUndefined()
  })

  it('maps the full-concordance ProductOperation to server-scope CSV', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    const uiStore = useUiStore()
    queryStore.setTerm('Hase')
    uiStore.focusProductOperation('research.replay_export.concordance', {
      capabilityId: 'research.replay_export',
      surfaceSlot: 'research.replay_export.concordance',
      preferredMode: 'concordance',
    })

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const csvButton = wrapper.findAll('.format-btn').find((button) => button.text().includes('CSV'))
    const serverScope = wrapper.find<HTMLInputElement>('input[value="all-server"]')
    expect(csvButton?.classes()).toContain('active')
    expect(csvButton?.classes()).toContain('operation-focused')
    expect(serverScope.element.checked).toBe(true)
  })

  it('disables EvidencePackage reports without an active query before runtime export starts', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    await wrapper.findAll('.format-btn').find((button) => button.text().includes('PDF'))?.trigger('click')

    const exportButton = wrapper.findAll('button').find((button) => button.text().includes('Exportieren'))
    expect(exportButton?.attributes('disabled')).toBeDefined()
    expect(exportButton?.attributes('title')).toContain('aktive Suche')
  })

  it('keeps report provenance visible without exposing operation ids', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    await wrapper.findAll('.format-btn').find((button) => button.text().includes('PDF'))?.trigger('click')

    const pdfButton = wrapper.findAll('.format-btn').find((button) => button.text().includes('PDF'))
    expect(wrapper.text()).not.toContain('Backend-Workflow')
    expect(wrapper.text()).not.toContain('research.replay_export.evidence_package')
    expect(wrapper.text()).not.toContain('research.replay_export.pdf')
    expect(pdfButton?.text()).toContain('Provenienz: EvidencePackage')
    expect(pdfButton?.text()).toContain('Füllstand: serverseitig rekonstruiert')
    expect(pdfButton?.text()).not.toContain('Backend-Schritte')
  })

  it('shows export runtime as local progress and history without claiming an OperationRun monitor', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    const exportStore = useExportStore()
    queryStore.setTerm('Hase')
    exportStore.isExporting = true
    exportStore.exportProgress = 40
    exportStore.currentJob = {
      id: 'export-live-1',
      format: 'pdf',
      operationIds: [
        'research.replay_export.evidence_package',
        'research.replay_export.pdf',
      ],
      status: 'processing',
      progress: 40,
      filename: 'candyconc_report.pdf',
      total: 1_000_001,
      exportedRows: 1_000_000,
      exportCap: 1_000_000,
      truncated: true,
      warning: 'Der Server hat 1.000.000 von 1.000.001 Trefferzeilen ausgegeben.',
      timestamp: 1,
    }
    exportStore.exportHistory = [{
      id: 'export-done-1',
      format: 'docx',
      operationIds: [
        'research.replay_export.evidence_package',
        'research.replay_export.docx',
      ],
      status: 'completed',
      progress: 100,
      filename: 'candyconc_report.docx',
      total: 12,
      exportedRows: 12,
      exportCap: 1_000_000,
      timestamp: 0,
    }]

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    expect(wrapper.text()).toContain('Export-Laufzeit')
    expect(wrapper.text()).toContain('Exportfortschritt und zuletzt erzeugte Dateien')
    expect(wrapper.text()).toContain('Datei-Exporte zeigen Fortschritt, Status und Historie')
    expect(wrapper.text()).not.toContain('Backend-OperationRun')
    expect(wrapper.text()).not.toContain('OperationRun-Monitor')
    expect(wrapper.text()).toContain('Verarbeitung · 40%')
    expect(wrapper.text()).toContain('candyconc_report.pdf')
    expect(wrapper.text()).toContain('1.000.000 von 1.000.001 Trefferzeilen ausgegeben')
    expect(wrapper.text()).toContain('Trefferliste abgeschnitten')
    expect(wrapper.text()).not.toContain('research.replay_export.evidence_package')
    expect(wrapper.text()).not.toContain('research.replay_export.pdf')
    expect(wrapper.text()).toContain('Zuletzt erzeugt')
    expect(wrapper.text()).toContain('candyconc_report.docx')
    expect(wrapper.text()).toContain('Abgeschlossen')
  })

  it('labels PDF reports as server EvidencePackage workflows, not loaded-browser row exports', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults(
      [{ position: 1, left: 'browser', match: 'Hase', right: 'slice', docId: 'd1' }],
      500,
      true,
      false,
    )

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    await wrapper.findAll('.format-btn').find((button) => button.text().includes('PDF'))?.trigger('click')

    expect(wrapper.text()).toContain('Serverseitiger EvidencePackage-Workflow')
    expect(wrapper.text()).toContain('nicht die geladenen Browser-Zeilen als Beweisquelle')
    expect(wrapper.text()).toContain('KWIC-Zeilen aus EvidencePackage')
    expect(wrapper.text()).toContain('nicht im EvidencePackage-Report gerendert')
    expect(wrapper.text()).not.toContain('in PDF/DOCX als Tabelle')
    expect(wrapper.find<HTMLInputElement>('input[value="loaded"]').exists()).toBe(false)
    expect(wrapper.find<HTMLInputElement>('input[value="all-server"]').exists()).toBe(false)
  })

  it('gates annotations as CSV-only for EvidencePackage report formats', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    const annotationsStore = useAnnotationsStore()
    annotationsStore.annotations = {
      'default::d1:1': { categoryId: 'cat1', note: 'prüfen', annotator: 'alice', updatedAt: 1 },
    }

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    for (const label of ['PDF', 'Word', 'Evidence JSON', 'LaTeX']) {
      const formatButton = wrapper.findAll('.format-btn').find((button) => button.text().includes(label))
      await formatButton?.trigger('click')
      const annotationItem = wrapper
        .findAll('.checkbox-item')
        .find((item) => item.text().includes('Annotationen einschließen'))
      expect(annotationItem?.text()).toContain('nicht im EvidencePackage-Report gerendert')
      expect(annotationItem?.find('input').attributes('disabled')).toBeDefined()
    }
  })

  it('fails closed visibly when a backend export operation is missing', () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    seedReplayExportContract()
    removeReplayExportOperation('research.replay_export.docx')
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')

    const wrapper = mount(ExportDialog, {
      props: { modelValue: true },
      global: {
        plugins: [pinia],
        stubs,
      },
    })

    const pdfButton = wrapper.findAll('.format-btn').find((button) => button.text().includes('PDF'))
    const docxButton = wrapper.findAll('.format-btn').find((button) => button.text().includes('Word'))

    expect(pdfButton?.attributes('disabled')).toBeUndefined()
    expect(docxButton?.attributes('disabled')).toBeDefined()
    expect(docxButton?.text()).not.toContain('research.replay_export.docx')
    expect(docxButton?.text()).toContain('nicht als Serverfunktion verfügbar')
  })
})
