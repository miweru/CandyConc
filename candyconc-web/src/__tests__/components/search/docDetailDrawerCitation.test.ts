import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import DocDetailDrawer from '@/components/search/DocDetailDrawer.vue'
import { useQueryStore } from '@/stores/query'

// The citation named the internal index number ("doc 0"), which changes with
// every rebuild of the index, instead of the identifier the corpus gives the
// document (the --id-column value, here sotu-1945-Truman).

const operationMocks = vi.hoisted(() => ({
  loadDocument: vi.fn(),
  loadDocSnippet: vi.fn(),
  copyTextToClipboard: vi.fn(),
}))

vi.mock('@/composables/useDocumentAccessOperations', () => ({
  useDocumentAccessOperations: () => ({
    loadDocument: operationMocks.loadDocument,
    loadDocSnippet: operationMocks.loadDocSnippet,
  }),
}))

vi.mock('@/composables/useParallelOperations', () => ({
  useParallelOperations: () => ({
    canOpenAlignment: { value: false },
    canLoadParallelGroups: { value: false },
    loadAlignmentRefDoc: vi.fn(),
    loadParallelGroups: vi.fn(),
  }),
}))

vi.mock('@/lib/kwicCitation', () => ({
  copyTextToClipboard: operationMocks.copyTextToClipboard,
}))

function mountDrawer(docId: string) {
  return mount(DocDetailDrawer, {
    props: { modelValue: true, docId, highlight: '', highlightPosition: undefined },
    global: {
      stubs: {
        SlideOver: {
          props: ['modelValue', 'title', 'size'],
          template: '<section data-test="slide-over" :data-title="title"><slot /></section>',
        },
        ClipboardList: true,
        Columns2: true,
        AlignmentComparison: true,
      },
    },
  })
}

async function copiedCitation(docId: string): Promise<string> {
  const wrapper = mountDrawer(docId)
  await flushPromises()
  await wrapper.get('.doc-cite-btn').trigger('click')
  await flushPromises()
  expect(operationMocks.copyTextToClipboard).toHaveBeenCalledTimes(1)
  return operationMocks.copyTextToClipboard.mock.calls[0]![0] as string
}

describe('DocDetailDrawer citation names the corpus document identifier', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    useQueryStore().filters.corpus = 'sotu_en'
    operationMocks.loadDocSnippet.mockResolvedValue(null)
    operationMocks.copyTextToClipboard.mockResolvedValue(true)
  })

  it('cites the id column of the import, not the index number', async () => {
    operationMocks.loadDocument.mockResolvedValue({
      doc_id: 0,
      doc: 'sotu-1945-Truman',
      meta: {
        doc_id: 'sotu-1945-Truman',
        path: 'sotu-1945-Truman',
        source: 'state_union',
        title: "PRESIDENT HARRY S. TRUMAN'S ADDRESS BEFORE A JOINT SESSION OF THE CONGRESS",
      },
      text: 'Mr. Speaker ...',
    })
    const citation = await copiedCitation('0')
    expect(citation).toBe(
      "PRESIDENT HARRY S. TRUMAN'S ADDRESS BEFORE A JOINT SESSION OF THE CONGRESS, state_union, doc sotu-1945-Truman",
    )
    expect(citation).not.toContain('doc 0')
  })

  it('cites the document label when the import had no id column', async () => {
    // Without an id column the server repeats the index number in meta doc_id.
    operationMocks.loadDocument.mockResolvedValue({
      doc_id: 12,
      doc: 'speeches/1962-kennedy.txt',
      meta: { doc_id: '12', path: 'speeches/1962-kennedy.txt', source: 'speeches', title: 'State of the Union 1962' },
      text: 'Mr. Vice President ...',
    })
    const citation = await copiedCitation('12')
    expect(citation).toBe('State of the Union 1962, speeches, doc speeches/1962-kennedy.txt')
    expect(citation).not.toContain('doc 12')
  })

  it('does not repeat an identifier that already serves as the title', async () => {
    operationMocks.loadDocument.mockResolvedValue({
      doc_id: 3,
      doc: 'rhode_schall_1800',
      meta: { doc_id: 'rhode_schall_1800', path: 'rhode_schall_1800', source: 'dta_kernkorpus' },
      text: 'Theorie der Verbreitung des Schalles ...',
    })
    const citation = await copiedCitation('3')
    expect(citation).toBe('rhode_schall_1800, dta_kernkorpus')
  })
})
