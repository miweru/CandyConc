import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DocDetailDrawer from '@/components/search/DocDetailDrawer.vue'
import { useDocsetStore } from '@/stores/docset'
import { useQueryStore } from '@/stores/query'

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

const SOTU_META = {
  doc_id: 'sotu-1945-Truman',
  path: 'sotu-1945-Truman',
  source: 'state_union',
  variant: 'document',
  model: 'none',
  text_type: 'standalone',
  president: 'Harry S. Truman',
  party: 'Democratic',
  year: '1945',
  decade: '1940s',
  date: '1945-04-16',
  title: 'ADDRESS BEFORE A JOINT SESSION OF THE CONGRESS',
}

describe('DocDetailDrawer shows the metadata fields of the corpus (erprobung B10)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    useQueryStore().filters.corpus = 'sotu_en'
    operationMocks.loadDocument.mockResolvedValue({
      doc_id: 0,
      doc: 'sotu-1945-Truman',
      meta: SOTU_META,
      text: 'Mr. Speaker, Mr. President ...',
      doc_start: 0,
      doc_end: 100,
    })
    operationMocks.loadDocSnippet.mockResolvedValue(null)
  })

  it('lists the fields that tell documents apart and puts corpus-wide constants aside', async () => {
    useDocsetStore().metaFieldValueCounts = {
      date: 55, decade: 7, doc_id: 65, model: 1, party: 2, path: 65,
      president: 11, source: 1, text_type: 1, title: 26, variant: 1, year: 61,
    }
    const wrapper = mountDrawer({ docId: '0', highlight: '', highlightPosition: undefined })
    await flushPromises()
    const main = wrapper.get('[data-testid="doc-meta"]').text()
    for (const field of ['president', 'party', 'title', 'year', 'decade', 'date']) {
      expect(main).toContain(field)
    }
    expect(main).toContain('Harry S. Truman')
    for (const field of ['text_type', 'model', 'variant', 'source']) {
      expect(main).not.toContain(field)
    }
    const constant = wrapper.get('[data-testid="doc-meta-constant"]').text()
    for (const field of ['text_type', 'model', 'variant', 'source']) {
      expect(constant).toContain(field)
    }
  })

  it('treats every field as distinguishing while the value counts are unknown', async () => {
    const wrapper = mountDrawer({ docId: '0', highlight: '', highlightPosition: undefined })
    await flushPromises()
    const main = wrapper.get('[data-testid="doc-meta"]').text()
    expect(main).toContain('president')
    expect(main).toContain('text_type')
    expect(wrapper.find('[data-testid="doc-meta-constant"]').exists()).toBe(false)
  })

  it('names the internal document number as such, doc_id stays the identifier of the corpus', async () => {
    const wrapper = mountDrawer({ docId: '0', highlight: '', highlightPosition: undefined })
    await flushPromises()
    // Before, the header read "doc_id: 0" above a metadata row doc_id = sotu-1945-Truman.
    const internal = wrapper.get('.doc-id')
    expect(internal.text()).toBe('Indexnummer 0')
    expect(internal.text()).not.toContain('doc_id')
    expect(internal.attributes('title')).toBe('Position des Dokuments im Index. Die Kennung des Dokuments im Korpus steht in den Metadaten.')
    const rows = wrapper.findAll('[data-testid="doc-meta"] .meta-row').map((row) => row.text())
    expect(rows).toContain('doc_idsotu-1945-Truman')
  })
})
