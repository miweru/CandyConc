import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DocDetailDrawer from '@/components/search/DocDetailDrawer.vue'

const operationMocks = vi.hoisted(() => ({
  loadDocument: vi.fn(),
  loadDocSnippet: vi.fn(),
}))

const parallelMocks = vi.hoisted(() => ({
  canOpenAlignment: { value: false },
  canLoadParallelGroups: { value: false },
  loadAlignmentRefDoc: vi.fn(),
  loadParallelGroups: vi.fn(),
}))

vi.mock('@/composables/useDocumentAccessOperations', () => ({
  useDocumentAccessOperations: () => ({
    loadDocument: operationMocks.loadDocument,
    loadDocSnippet: operationMocks.loadDocSnippet,
  }),
}))

vi.mock('@/composables/useParallelOperations', () => ({
  useParallelOperations: () => ({
    canOpenAlignment: parallelMocks.canOpenAlignment,
    canLoadParallelGroups: parallelMocks.canLoadParallelGroups,
    loadAlignmentRefDoc: parallelMocks.loadAlignmentRefDoc,
    loadParallelGroups: parallelMocks.loadParallelGroups,
  }),
}))

function mountDrawer(props: Record<string, unknown>) {
  return mount(DocDetailDrawer, {
    props: {
      modelValue: true,
      docId: '7',
      highlight: 'Hase',
      highlightPosition: 42,
      highlightLeft: 'ein',
      highlightRight: 'läuft',
      ...props,
    },
    global: {
      stubs: {
        SlideOver: {
          props: ['modelValue', 'title', 'size'],
          template: '<section data-test="slide-over" :data-size="size" :data-title="title"><slot /></section>',
        },
        ClipboardList: true,
        Columns2: true,
        AlignmentComparison: {
          props: ['result'],
          template: '<div data-test="alignment-comparison">Vergleich geladen</div>',
        },
      },
    },
  })
}

describe('DocDetailDrawer evidential anchor', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    parallelMocks.canOpenAlignment.value = false
    parallelMocks.canLoadParallelGroups.value = false
    operationMocks.loadDocument.mockResolvedValue({
      doc_id: 7,
      doc: 'Dokument 7',
      meta: { source: 'test' },
      text: 'Hase am Anfang. Später läuft der Hase weiter.',
      doc_start: 0,
      doc_end: 200,
    })
    operationMocks.loadDocSnippet.mockResolvedValue({
      doc_id: 7,
      doc: 'Dokument 7',
      meta: { source: 'test' },
      pos: 42,
      ctx: 40,
      doc_start: 0,
      doc_end: 200,
      start_pos: 39,
      end_pos: 45,
      left: 'ein schneller',
      kw: 'Hase',
      right: 'läuft weiter',
      text: 'ein schneller Hase läuft weiter',
    })
  })

  it('loads the KWIC snippet and renders it as the evidential anchor', async () => {
    const wrapper = mountDrawer({})

    await flushPromises()

    expect(operationMocks.loadDocument).toHaveBeenCalledWith('7', 'default')
    expect(operationMocks.loadDocSnippet).toHaveBeenCalledWith({
      pos: 42,
      ctx: 40,
      corpus: 'default',
    })
    expect(wrapper.text()).not.toContain('Dokumentzugriff-Contract')
    expect(wrapper.text()).not.toContain('ProductOperation-gegatet')
    expect(wrapper.text()).not.toContain('query.document_access.full_text')
    expect(wrapper.text()).not.toContain('query.document_access.snippet')
    expect(wrapper.text()).toContain('KWIC-Beleg')
    expect(wrapper.text()).toContain('Tokenposition 42')
    expect(wrapper.text()).toContain('ein schneller')
    expect(wrapper.text()).toContain('Hase')
    expect(wrapper.text()).toContain('läuft weiter')
    expect(wrapper.text()).toContain('Token 39-45, Dokumentbereich 0-200')
    expect(wrapper.text()).toContain('textbasierte Orientierung')
    expect(wrapper.text()).not.toContain('Zum Treffer im Volltext')
    expect(wrapper.text()).toContain('Mehrere Volltextmarkierungen sind nicht eindeutig zuordenbar')
  })

  it('uses the corpus pinned on the document request', async () => {
    mountDrawer({ corpus: 'corpus-a' })

    await flushPromises()

    expect(operationMocks.loadDocument).toHaveBeenCalledWith('7', 'corpus-a')
    expect(operationMocks.loadDocSnippet).toHaveBeenCalledWith({
      pos: 42,
      ctx: 40,
      corpus: 'corpus-a',
    })
  })

  it('keeps the full document usable when snippet loading fails', async () => {
    operationMocks.loadDocSnippet.mockRejectedValueOnce(new Error('Snippet route disabled'))

    const wrapper = mountDrawer({})

    await flushPromises()

    expect(wrapper.text()).not.toContain('query.document_access.snippet')
    expect(wrapper.text()).not.toContain('Dokument-Snippet ist im aktuellen Funktionskontext nicht freigegeben.')
    expect(wrapper.text()).toContain('Snippet route disabled')
    expect(wrapper.text()).toContain('Der KWIC-Zeilenkontext bleibt als Fallback sichtbar')
    expect(wrapper.text()).toContain('ein')
    expect(wrapper.text()).toContain('läuft')
    expect(wrapper.text()).toContain('Hase am Anfang')
  })

  it('keeps the KWIC anchor visible when full text loading fails', async () => {
    operationMocks.loadDocument.mockRejectedValueOnce(new Error('Full text unavailable'))

    const wrapper = mountDrawer({})

    await flushPromises()

    expect(wrapper.text()).toContain('KWIC-Beleg')
    expect(wrapper.text()).toContain('ein schneller')
    expect(wrapper.text()).toContain('läuft weiter')
    expect(wrapper.text()).toContain('Full text unavailable')
  })

  it('warns when an external position anchor does not belong to the opened document', async () => {
    operationMocks.loadDocument.mockResolvedValueOnce({
      doc_id: 8,
      doc: 'Dokument 8',
      meta: {},
      text: 'Anderer Volltext mit Hase.',
    })

    const wrapper = mountDrawer({})

    await flushPromises()

    expect(wrapper.text()).toContain('Positionsbeleg verweist auf doc_id 7, geöffnet ist doc_id 8')
  })

  it('renders a complete reference and the opened variant before optional sentence evidence', async () => {
    parallelMocks.canOpenAlignment.value = true
    parallelMocks.canLoadParallelGroups.value = true
    operationMocks.loadDocument.mockResolvedValueOnce({
      doc_id: 7,
      doc: 'Variante 7',
      meta: { ref_doc: '4', model: 'Testmodell' },
      text: 'Varianten-Volltext mit dem Hase und einem zusätzlichen Schluss.',
    }).mockResolvedValueOnce({
      doc_id: 4,
      doc: 'Referenz 4',
      meta: { source: 'Referenzkorpus', origin_id: 'Referenzkorpus:4' },
      text: 'Referenzvolltext mit dem Hase und einem anderen Schluss.',
    })
    parallelMocks.loadParallelGroups.mockResolvedValueOnce({
      total: 1,
      groups: [{
        ref_doc: 4,
        doc_count: 2,
        doc_ids: [4, 7],
        human_doc_id: 4,
        variant_doc_ids: [7],
        variants: [{ doc_id: 7, label: 'Testmodell', provenance: 'Testkorpus · 7' }],
        models: [],
        text_types: { human: 1, generated: 1 },
        sources: ['Testkorpus'],
      }],
    })
    parallelMocks.loadAlignmentRefDoc.mockResolvedValueOnce({
      ref_doc: 4,
      corpus: 'default',
      focus_pos: 42,
      focus_doc_id: 7,
      alignment_scope: 'complete_document',
      reference: { doc_id: 4, doc: 'Referenz', meta: {}, sentence_count: 1, window_start: 0, window_end: 1, focus_sentence_index: 0, sentences: [] },
      variants: [],
      variant_count: 1,
    })

    const wrapper = mountDrawer({})
    await flushPromises()

    expect(wrapper.text()).toContain('Dokumentvarianten')
    await wrapper.get('.variant-comparison-btn').trigger('click')
    await flushPromises()

    expect(parallelMocks.loadParallelGroups).toHaveBeenCalledWith({
      corpus: 'default',
      refDoc: 4,
      includeAllVariants: true,
      limit: 1,
    })
    expect(parallelMocks.loadAlignmentRefDoc).toHaveBeenCalledWith({
      refDoc: 4,
      corpus: 'default',
      focusPos: 42,
      includeDocIds: [7],
      windowSentences: 24,
      maxVariants: 1,
    })
    expect(operationMocks.loadDocument).toHaveBeenCalledWith('4', 'default')
    expect(wrapper.text()).toContain('Volltextvergleich')
    expect(wrapper.text()).toContain('Referenzvolltext mit dem Hase und einem anderen Schluss.')
    expect(wrapper.text()).toContain('Varianten-Volltext mit dem Hase und einem zusätzlichen Schluss.')
    expect(wrapper.text()).toContain('Zuordnung am vollständigen Dokument geprüft')
    expect(wrapper.get('.alignment-evidence').attributes('open')).toBeUndefined()
    expect(wrapper.text()).toContain('Satzweise Evidenzprüfung öffnen')
    expect(wrapper.get('[data-test="alignment-comparison"]').text()).toContain('Vergleich geladen')
    expect(wrapper.get('[data-test="slide-over"]').attributes('data-size')).toBe('wide')
  })

  it('lets researchers select several complete variants for a side-by-side reading session', async () => {
    parallelMocks.canOpenAlignment.value = true
    parallelMocks.canLoadParallelGroups.value = true
    operationMocks.loadDocument.mockResolvedValueOnce({
      doc_id: 7,
      doc: 'Variante 7',
      meta: { ref_doc: '4', model: 'Testmodell A' },
      text: 'Volltext Variante A.',
    }).mockResolvedValueOnce({
      doc_id: 4,
      doc: 'Referenz 4',
      meta: { source: 'Referenzkorpus' },
      text: 'Volltext Referenz.',
    }).mockResolvedValueOnce({
      doc_id: 8,
      doc: 'Variante 8',
      meta: { model: 'Testmodell B' },
      text: 'Volltext Variante B.',
    }).mockResolvedValueOnce({
      doc_id: 9,
      doc: 'Variante 9',
      meta: { model: 'Testmodell C' },
      text: 'Volltext Variante C.',
    })
    parallelMocks.loadParallelGroups.mockResolvedValueOnce({
      total: 1,
      groups: [{
        ref_doc: 4,
        doc_count: 4,
        doc_ids: [4, 7, 8, 9],
        human_doc_id: 4,
        variant_doc_ids: [7, 8, 9],
        variants: [
          { doc_id: 7, label: 'Testmodell A', provenance: '' },
          { doc_id: 8, label: 'Testmodell B', provenance: '' },
          { doc_id: 9, label: 'Testmodell C', provenance: '' },
        ],
        models: [],
        text_types: { human: 1, generated: 3 },
        sources: ['Testkorpus'],
      }],
    })
    parallelMocks.loadAlignmentRefDoc.mockResolvedValueOnce({
      ref_doc: 4,
      corpus: 'default',
      focus_pos: 42,
      focus_doc_id: 7,
      alignment_scope: 'complete_document',
      reference: { doc_id: 4, doc: 'Referenz', meta: {}, sentence_count: 1, window_start: 0, window_end: 1, focus_sentence_index: 0, sentences: [] },
      variants: [],
      variant_count: 1,
    })

    const wrapper = mountDrawer({})
    await flushPromises()
    await wrapper.get('.variant-comparison-btn').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Varianten auswählen')
    expect(wrapper.text()).toContain('Alle 3 Varianten anzeigen')
    expect(wrapper.findAll('.full-text-pane')).toHaveLength(2)

    await wrapper.findAll('button').find((button) => button.text().includes('Alle 3 Varianten anzeigen'))!.trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Volltext Referenz.')
    expect(wrapper.text()).toContain('Volltext Variante A.')
    expect(wrapper.text()).toContain('Volltext Variante B.')
    expect(wrapper.text()).toContain('Volltext Variante C.')
    expect(wrapper.findAll('.full-text-pane')).toHaveLength(4)
    expect(wrapper.get('.full-text-comparison-grid').classes()).toContain('full-text-comparison-grid--multi')
    expect(operationMocks.loadDocument).toHaveBeenCalledWith('8', 'default')
    expect(operationMocks.loadDocument).toHaveBeenCalledWith('9', 'default')
  })

  it('keeps the full-text reader usable when the focused KWIC sentence has no counterpart', async () => {
    parallelMocks.canOpenAlignment.value = true
    parallelMocks.canLoadParallelGroups.value = true
    operationMocks.loadDocument.mockResolvedValueOnce({
      doc_id: 7,
      doc: 'Variante 7',
      meta: { ref_doc: '4', model: 'Testmodell' },
      text: 'Varianten-Volltext.',
    }).mockResolvedValueOnce({
      doc_id: 4,
      doc: 'Referenz 4',
      meta: { source: 'Referenzkorpus' },
      text: 'Referenzvolltext.',
    })
    parallelMocks.loadParallelGroups.mockResolvedValueOnce({
      total: 1,
      groups: [{
        ref_doc: 4,
        doc_count: 2,
        doc_ids: [4, 7],
        human_doc_id: 4,
        variant_doc_ids: [7],
        variants: [{ doc_id: 7, label: 'Testmodell', provenance: '' }],
        models: [],
        text_types: { human: 1, generated: 1 },
        sources: ['Testkorpus'],
      }],
    })
    parallelMocks.loadAlignmentRefDoc.mockRejectedValueOnce(
      new Error('Für den geöffneten Varianten-Satz wurde keine ausreichend belegte Referenzentsprechung gefunden.')
    )

    const wrapper = mountDrawer({})
    await flushPromises()
    await wrapper.get('.variant-comparison-btn').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('Volltextvergleich')
    expect(wrapper.text()).toContain('Referenzvolltext.')
    expect(wrapper.text()).toContain('Varianten-Volltext.')
    expect(wrapper.text()).toContain('Satzweise Evidenzprüfung nicht verfügbar')
    expect(wrapper.text()).toContain('Der Volltextvergleich bleibt deshalb bewusst unverändert')
    expect(wrapper.find('[data-test="alignment-comparison"]').exists()).toBe(false)
    expect(wrapper.get('[data-test="slide-over"]').attributes('data-size')).toBe('wide')
  })

  it('uses a readable corpus identifier as the drawer title and keeps technical metadata available', async () => {
    operationMocks.loadDocument.mockResolvedValueOnce({
      doc_id: 7,
      doc: 'opaque:internal:document:key',
      meta: {
        origin_id: 'korpus:42',
        genre: 'Sachtext',
        internal_hash: 'abc123',
      },
      text: 'Hase am Anfang.',
    })

    const wrapper = mountDrawer({})
    await flushPromises()

    expect(wrapper.get('[data-test="slide-over"]').attributes('data-title')).toBe('korpus:42')
    expect(wrapper.text()).toContain('genre')
    // Without value counts of the corpus every field is listed with the
    // metadata. The former split by a fixed list of project fields is gone.
    expect(wrapper.get('[data-testid="doc-meta"]').text()).toContain('internal_hash')
  })

  it('shortens a source-prefixed origin id in the heading without losing the full provenance metadata', async () => {
    operationMocks.loadDocument.mockResolvedValueOnce({
      doc_id: 7,
      doc: 'opaque:internal:document:key',
      meta: {
        source: 'klexikon_full',
        origin_id: 'klexikon_full:1125',
      },
      text: 'Hase am Anfang.',
    })

    const wrapper = mountDrawer({})
    await flushPromises()

    expect(wrapper.get('[data-test="slide-over"]').attributes('data-title')).toBe('klexikon_full · 1125')
    const metadata = wrapper.get('[data-testid="doc-meta"]').text()
    expect(metadata).toContain('origin_id')
    expect(metadata).toContain('klexikon_full:1125')
  })
})
