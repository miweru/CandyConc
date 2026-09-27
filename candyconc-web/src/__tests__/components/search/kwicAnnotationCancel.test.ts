import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KwicTable from '@/components/search/KwicTable.vue'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import { useAnnotationsStore, rowIdFor } from '@/stores/annotations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { deleteAnnotation, putAnnotation } from '@/api/client'
import type { KwicRow } from '@/stores/query'

/**
 * ANNOTATION-01: toggling an annotation off is an explicit coding action. It
 * must save immediately instead of opening a native confirmation dialog.
 */

class TestResizeObserver {
  private callback: ResizeObserverCallback
  constructor(callback: ResizeObserverCallback) {
    this.callback = callback
  }
  observe() {
    this.callback([], this)
  }
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: typeof TestResizeObserver }).ResizeObserver = TestResizeObserver

if (!('scrollIntoView' in HTMLElement.prototype)) {
  // @ts-expect-error augmenting prototype for jsdom
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

vi.mock('@tanstack/vue-virtual', () => ({
  useVirtualizer: (optionsRef: { value: { count: number } }) => ({
    value: {
      options: { estimateSize: () => 48 },
      getVirtualItems: () =>
        Array.from({ length: optionsRef.value.count }, (_, index) => ({
          index,
          key: index,
          start: index * 48,
          size: 48,
        })),
      getTotalSize: () => optionsRef.value.count * 48,
      scrollToIndex: vi.fn(),
      measure: vi.fn(),
      measureElement: vi.fn(),
    },
  }),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAnnotations: vi.fn(async () => ({ annotations: {}, scheme: { categories: [] } })),
    getAnnotationScheme: vi.fn(async () => ({ categories: [] })),
    getAnnotationSettings: vi.fn(async () => ({ multiCoder: false })),
    getAnnotationAgreement: vi.fn(async () => ({
      overall: { percentAgreement: 1, cohenKappa: null, n: 0 },
      perCategory: [],
      annotators: [],
      itemCount: 0,
    })),
    putAnnotation: vi.fn(async (_rowId: string, input: { categoryId?: string | null; note?: string | null; annotator?: string | null }) => ({
      categoryId: input.categoryId ?? null,
      note: input.note ?? null,
      annotator: input.annotator ?? 'local-annotator',
      updatedAt: 1,
    })),
    deleteAnnotation: vi.fn(async () => ({ status: 'deleted' })),
  }
})

function route(path: string, method = 'GET') {
  return {
    path,
    methods: [method],
    mutates: method !== 'GET',
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function operation(id: string, path: string, method: string, label: string) {
  return {
    id,
    capability_id: 'research.annotations',
    label,
    description: '',
    route: route(path, method),
    effects: [method === 'GET' ? 'read' : 'write'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: id,
    priority: 10,
  }
}

function seedAnnotationContract(): void {
  const productCapabilities = useProductCapabilitiesStore()
  productCapabilities.status = 'ready'
  productCapabilities.contract = {
    version: 'product-capabilities-v1',
    scope: 'test',
    fingerprint_sha256: 'a'.repeat(64),
    capabilities: [
      {
        id: 'research.annotations',
        title: 'KWIC annotation workflow',
        area: 'research_workflow',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: ['/api/v1/annotations/{row_id}'],
        backend_route_descriptors: [
          route('/api/v1/annotations/{row_id}', 'PUT'),
          route('/api/v1/annotations/{row_id}', 'DELETE'),
        ],
        operations: [
          operation('research.annotations.write', '/api/v1/annotations/{row_id}', 'PUT', 'Annotation speichern'),
          operation('research.annotations.delete', '/api/v1/annotations/{row_id}', 'DELETE', 'Annotation löschen'),
        ],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: [],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      },
    ],
  } as never
}

function makeRow(): KwicRow {
  return { position: 0, left: 'links', match: 'TREFFER', right: 'rechts', docId: 'doc0' }
}

const mountedWrappers: Array<ReturnType<typeof mount>> = []
afterEach(() => {
  while (mountedWrappers.length) mountedWrappers.pop()?.unmount()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

function mountTable() {
  const wrapper = mount(KwicTable, {
    global: {
      stubs: {
        Modal: { template: '<div><slot /><slot name="footer" /></div>' },
        DocDetailDrawer: { template: '<div />' },
        AnnotationSchemeEditor: { template: '<div />' },
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('KwicTable annotation toggle-off (ANNOTATION-01)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedAnnotationContract()
    useUiStore().setActiveTab('kwic')
  })

  it('removes the code without a native confirmation dialog or a spurious error toast', async () => {
    const row = makeRow()
    // KwicTable namespaces ids by docsetStore.activeCorpus, which defaults to
    // 'default'; match that so rowCategory() finds the seeded annotation.
    const rowId = rowIdFor(row, 'default')

    const annotations = useAnnotationsStore()
    annotations.categories = [{ id: 'cat1', label: 'Ironie', color: '#f00', shortcut: 'i' }]
    annotations.annotations = {
      [rowId]: { categoryId: 'cat1', note: null, annotator: 'tester', updatedAt: 1 },
    }
    expect(annotations.canWriteAnnotations).toBe(true)

    const queryStore = useQueryStore()
    queryStore.setTerm('TREFFER')
    queryStore.setResults([row], 1, true, false)

    const ui = useUiStore()
    const toastSpy = vi.spyOn(ui, 'showToast')

    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

    const wrapper = mountTable()
    await flushPromises()

    // Select the single row, then press the category shortcut to toggle it off.
    queryStore.selectRow(0)
    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'i' })
    await flushPromises()

    expect(confirmSpy).not.toHaveBeenCalled()
    expect(deleteAnnotation).toHaveBeenCalled()

    // Cancel must be a clean no-op: no error toast at all.
    const errorToasts = toastSpy.mock.calls.filter((c) => c[1] === 'error')
    expect(errorToasts).toEqual([])
    expect(toastSpy).not.toHaveBeenCalledWith(
      'Kategorie konnte nicht gespeichert werden',
      expect.anything(),
    )

    expect(annotations.getAnnotation(rowId)).toBeUndefined()
  })

  it('stages code and note until the researcher explicitly saves both together', async () => {
    const row = makeRow()
    const rowId = rowIdFor(row, 'default')

    const annotations = useAnnotationsStore()
    annotations.categories = [{ id: 'cat1', label: 'Ironie', color: '#f00', shortcut: 'i' }]
    expect(annotations.canWriteAnnotations).toBe(true)

    const queryStore = useQueryStore()
    queryStore.setTerm('TREFFER')
    queryStore.setResults([row], 1, true, false)

    const wrapper = mountTable()
    await flushPromises()

    await wrapper.find('.ann-btn').trigger('click')
    await wrapper.find('#ann-note').setValue('Notiz direkt vor Kategorie')
    const categoryButton = wrapper.findAll('.ann-category-btn').find((button) => button.text().includes('Ironie'))
    expect(categoryButton).toBeDefined()
    await categoryButton!.trigger('click')
    await flushPromises()

    expect(putAnnotation).not.toHaveBeenCalled()

    await wrapper.find('.ann-footer-save').trigger('click')
    await flushPromises()

    expect(putAnnotation).toHaveBeenCalledWith(
      'doc0:0',
      expect.objectContaining({
        categoryId: 'cat1',
        note: 'Notiz direkt vor Kategorie',
      }),
      'default',
    )
    expect(annotations.getAnnotation(rowId)).toMatchObject({
      categoryId: 'cat1',
      note: 'Notiz direkt vor Kategorie',
    })
  })

  it('explains the first coding action and gives the row action an accessible name', async () => {
    const annotations = useAnnotationsStore()
    annotations.categories = [{ id: 'cat1', label: 'Ironie', color: '#f00', shortcut: 'i' }]

    const queryStore = useQueryStore()
    queryStore.setTerm('TREFFER')
    queryStore.setResults([makeRow()], 1, true, false)

    const wrapper = mountTable()
    await flushPromises()

    const annotationControl = wrapper
      .findAll('.header-btn')
      .find((button) => button.text().includes('Codes & Annotationen'))
    expect(annotationControl).toBeDefined()
    // BEANSTANDET 2026-08-31: hier stand "So annotieren Sie Belege: Codes &
    // Annotationen oeffnen, bei Bedarf einen Code anlegen, dann in der
    // KWIC-Zeile das Etikett-Symbol waehlen." Ein Tutorial, das zwei
    // beschriftete Knoepfe erklaert, die daneben stehen, und das siezt.
    // Der Test pinnte den Satz und haette seine Entfernung verhindert.
    // Jetzt prueft er das Gegenteil: kein Erklaertext, sondern die
    // benannten Bedienelemente.
    expect(wrapper.find('.annotation-intro').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('So annotieren')
    expect(wrapper.get('.ann-btn').attributes('aria-label')).toBe('Zeile codieren: Code und Notiz')
  })

  it('keeps the annotation modal open when saving the note fails', async () => {
    vi.mocked(putAnnotation).mockRejectedValueOnce(new Error('backend down'))
    const row = makeRow()

    const annotations = useAnnotationsStore()
    annotations.categories = [{ id: 'cat1', label: 'Ironie', color: '#f00', shortcut: 'i' }]

    const queryStore = useQueryStore()
    queryStore.setTerm('TREFFER')
    queryStore.setResults([row], 1, true, false)

    const wrapper = mountTable()
    await flushPromises()

    await wrapper.find('.ann-btn').trigger('click')
    await wrapper.find('#ann-note').setValue('nicht verlieren')
    await wrapper.find('.ann-footer-save').trigger('click')
    await flushPromises()

    expect(wrapper.find('#ann-note').exists()).toBe(true)
    expect((wrapper.find('#ann-note').element as HTMLTextAreaElement).value).toBe('nicht verlieren')
    expect(useUiStore().toasts.at(-1)).toMatchObject({
      message: 'Annotation konnte nicht gespeichert werden',
      type: 'error',
    })
  })
})

describe('KwicTable annotation dialog context', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    seedAnnotationContract()
    useUiStore().setActiveTab('kwic')
  })

  it('shows twelve words on each side of the node, so code and note stay in view', async () => {
    const words = (prefix: string) => Array.from({ length: 200 }, (_, i) => `${prefix}${i}`).join(' ')
    const queryStore = useQueryStore()
    queryStore.setTerm('TREFFER')
    queryStore.setResults([{ position: 0, left: words('l'), match: 'TREFFER', right: words('r'), docId: 'doc0' }], 1, true, false)
    const wrapper = mountTable()
    await flushPromises()
    await wrapper.find('.ann-btn').trigger('click')
    await flushPromises()
    const left = wrapper.get('.ann-preview-left').text()
    const right = wrapper.get('.ann-preview-right').text()
    expect(left).toBe(`…${Array.from({ length: 12 }, (_, i) => `l${188 + i}`).join(' ')}`)
    expect(right).toBe(`${Array.from({ length: 12 }, (_, i) => `r${i}`).join(' ')}…`)
  })
})
