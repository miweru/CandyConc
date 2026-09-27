import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KwicTable from '@/components/search/KwicTable.vue'
import { actionBus } from '@/actions'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import { useDocsetStore } from '@/stores/docset'
import type { KwicRow } from '@/stores/query'

const parallelOperationMocks = vi.hoisted(() => ({
  loadParallelKwic: vi.fn(),
}))

vi.mock('@/composables/useParallelOperations', async () => {
  const { computed, ref } = await import('vue')
  const ready = computed(() => true)
  const unavailable = computed(() => false)
  const noReason = ref<string | null>(null)
  const availability = ref({ visible: true })
  return {
    useParallelOperations: () => ({
      groupsAvailability: availability,
      parallelKwicAvailability: availability,
      canLoadParallelGroups: unavailable,
      canOpenAlignment: unavailable,
      canLoadParallelKwic: ready,
      parallelGroupsBlockReason: noReason,
      alignmentBlockReason: noReason,
      parallelKwicBlockReason: noReason,
      loadParallelGroups: vi.fn(),
      loadAlignmentRefDoc: vi.fn(),
      loadParallelKwic: parallelOperationMocks.loadParallelKwic,
    }),
  }
})

// KwicTable constructs a ResizeObserver inside a deferred nextTick in onMounted.
// Provide a real (constructable) class so that deferred construction never trips
// the global vi.fn mock after teardown.
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

// jsdom elements lack scrollIntoView; the component guards it, but the mocked
// virtualizer rows are plain divs — provide a no-op so any stray call is safe.
if (!('scrollIntoView' in HTMLElement.prototype)) {
  // @ts-expect-error augmenting the prototype for the test environment
  HTMLElement.prototype.scrollIntoView = function scrollIntoView() {}
}

// Track mounted wrappers and unmount them after each test so the component's
// onUnmounted cleanup clears its debounced timers (otherwise deferred callbacks
// fire after pinia/mocks are torn down, producing unhandled rejections).
const mountedWrappers: Array<ReturnType<typeof mount>> = []
afterEach(() => {
  while (mountedWrappers.length) mountedWrappers.pop()?.unmount()
})

// TanStack Virtual is mocked to a minimal virtualizer that exposes one virtual
// item per loaded result (so the grid renders rows) and stubs the scroll/measure
// methods the component calls. This keeps the keyboard-navigation logic real
// while avoiding jsdom layout dependencies.
vi.mock('@tanstack/vue-virtual', () => {
  return {
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
  }
})

function makeRows(n: number): KwicRow[] {
  return Array.from({ length: n }, (_, i) => ({
    position: i,
    left: `left ${i}`,
    match: `match ${i}`,
    right: `right ${i}`,
    docId: `doc${i}`,
  }))
}

function mountTable() {
  const wrapper = mount(KwicTable, {
    global: {
      stubs: {
        Modal: { template: '<div><slot /></div>' },
        DocDetailDrawer: { template: '<div />' },
        AnnotationSchemeEditor: { template: '<div />' },
        // lucide icons
        ArrowDown: true,
        ArrowUp: true,
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('KwicTable keyboard navigation (DT-FE-KWIC-A11Y)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const ui = useUiStore()
    ui.setActiveTab('kwic')
    parallelOperationMocks.loadParallelKwic.mockReset()
  })

  it('renders the WAI-ARIA grid pattern on the viewport', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('match')
    queryStore.setResults(makeRows(5), 5, true, false)

    const wrapper = mountTable()
    await flushPromises()

    const grid = wrapper.find('[role="grid"]')
    expect(grid.exists()).toBe(true)
    expect(grid.attributes('aria-rowcount')).toBe('5')
    expect(grid.attributes('aria-multiselectable')).toBe('true')

    const rows = wrapper.findAll('[role="row"][aria-rowindex]')
    expect(rows.length).toBeGreaterThan(0)
    // Every data row exposes aria-selected.
    expect(wrapper.find('.table-row[role="row"]').attributes('aria-selected')).toBe('false')
  })

  it('ArrowDown from an empty selection selects row 0', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('match')
    queryStore.setResults(makeRows(5), 5, true, false)
    expect(queryStore.selectedRows.size).toBe(0)

    const wrapper = mountTable()
    await flushPromises()

    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowDown' })

    expect(queryStore.selectedRows.has(0)).toBe(true)
    expect(queryStore.highlightedRow).toBe(0)
    // aria-activedescendant points at the active row's DOM id.
    expect(wrapper.find('[role="grid"]').attributes('aria-activedescendant')).toBe('kwic-grid-row-0')
  })

  it('ArrowUp from an empty selection selects the last row', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('match')
    queryStore.setResults(makeRows(5), 5, true, false)

    const wrapper = mountTable()
    await flushPromises()

    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'ArrowUp' })

    expect(queryStore.selectedRows.has(4)).toBe(true)
    expect(queryStore.highlightedRow).toBe(4)
  })

  it('Home/End jump to the first/last row', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('match')
    queryStore.setResults(makeRows(8), 8, true, false)

    const wrapper = mountTable()
    await flushPromises()

    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'End' })
    expect(queryStore.highlightedRow).toBe(7)

    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'Home' })
    expect(queryStore.highlightedRow).toBe(0)
  })

  it('opens the active document with Enter instead of hiding the primary action behind a mouse click', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('match')
    queryStore.setResults(makeRows(2), 2, true, false)
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true } as never)

    const wrapper = mountTable()
    await flushPromises()
    queryStore.selectRow(1)
    queryStore.setHighlightedRow(1)

    await wrapper.find('[role="grid"]').trigger('keydown', { key: 'Enter' })

    expect(dispatchSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        type: 'nav/openDocument',
        payload: expect.objectContaining({ docId: 'doc1', highlight: 'match 1' }),
      }),
      { source: 'user' },
    )
    dispatchSpy.mockRestore()
  })
})

describe('KwicTable Parallel-KWIC scheduling (DT-FE-PARALLEL-01)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
    parallelOperationMocks.loadParallelKwic.mockReset()
    vi.mocked(window.confirm).mockReset()
    vi.mocked(window.confirm).mockReturnValue(true)
  })

  it('requires a fixed model selection before scheduling rows and never opens confirmation loops', async () => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    queryStore.setTerm('match')
    queryStore.setResults(makeRows(5), 5, true, false)
    docsetStore.metaOptions.model = ['Modell A']
    vi.spyOn(docsetStore, 'loadModelOptionsForPrompt').mockResolvedValue()

    const pending: Array<{ resolve: (value: { ref_doc: number; base_doc_id: number; variants: [] }) => void }> = []
    parallelOperationMocks.loadParallelKwic.mockImplementation(() => new Promise((resolve) => {
      pending.push({ resolve })
    }))

    const wrapper = mountTable()
    await flushPromises()

    await wrapper.get('.parallel-toggle input').setValue(true)
    await new Promise((resolve) => window.setTimeout(resolve, 70))
    await flushPromises()
    expect(parallelOperationMocks.loadParallelKwic).not.toHaveBeenCalled()
    expect(window.confirm).not.toHaveBeenCalled()
    // Neutralisiert am 2026-08-31: der Duz-Imperativ "Waehle mindestens
    // ein Modell" wurde zu "Mindestens ein Modell auswaehlen", der
    // Fassung, die im selben Bauteil bei KwicTable.vue:3269 schon stand.
    expect(wrapper.text()).toContain('Mindestens ein Modell auswählen')

    await wrapper.get('select.parallel-select--models').setValue(['Modell A'])
    await new Promise((resolve) => window.setTimeout(resolve, 70))
    await flushPromises()
    // Five visible rows are eventually loaded, but never more than two at once.
    expect(parallelOperationMocks.loadParallelKwic).toHaveBeenCalledTimes(2)

    for (let index = 0; index < 5; index += 1) {
      const next = pending.shift()
      expect(next).toBeDefined()
      next!.resolve({ ref_doc: index, base_doc_id: index, variants: [] })
      await flushPromises()
    }

    expect(
      parallelOperationMocks.loadParallelKwic.mock.calls.map(
        ([params]) => (params as { pos: number }).pos,
      ),
    ).toEqual([0, 1, 2, 3, 4])
    expect(window.confirm).not.toHaveBeenCalled()
  })

  it('loads model choices without requiring the complete legacy metadata filter set', async () => {
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    queryStore.setTerm('match')
    queryStore.setResults(makeRows(1), 1, true, false)
    const loadModels = vi
      .spyOn(docsetStore, 'loadModelOptionsForPrompt')
      .mockImplementation(async () => {
        docsetStore.metaOptions.model = ['target']
      })
    parallelOperationMocks.loadParallelKwic.mockResolvedValue({
      ref_doc: 0,
      base_doc_id: 0,
      variants: [],
    })

    const wrapper = mountTable()
    await flushPromises()
    await wrapper.get('.parallel-toggle input').setValue(true)
    await flushPromises()

    expect(loadModels).toHaveBeenCalledOnce()
    expect(wrapper.find('select.parallel-select--models option').text()).toBe('target')

    await wrapper.get('select.parallel-select--models').setValue(['target'])
    await new Promise((resolve) => window.setTimeout(resolve, 70))
    await flushPromises()
    expect(parallelOperationMocks.loadParallelKwic).toHaveBeenCalledWith(
      expect.objectContaining({ includeModels: ['target'] }),
    )
  })
})

describe('KwicTable filter-in-results (DT-FE-UX-CORE)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
  })

  function visibleRowCount(wrapper: ReturnType<typeof mountTable>): number {
    return wrapper.findAll('.table-row[role="row"]').filter((r) => !r.classes('is-filtered-out')).length
  }

  it('substring filter hides non-matching loaded rows (no re-query)', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('match')
    const rows = makeRows(5)
    rows[2]!.right = 'Klimawandel hier'
    queryStore.setResults(rows, 5, true, false)

    const wrapper = mountTable()
    await flushPromises()
    expect(visibleRowCount(wrapper)).toBe(5)

    await wrapper.find('.row-filter-input').setValue('Klimawandel')
    await flushPromises()

    // Only the one row whose text contains the needle stays visible.
    expect(visibleRowCount(wrapper)).toBe(1)
    // The loaded results themselves are untouched (filter is view-only).
    expect(queryStore.results.length).toBe(5)
  })

  it('a /regex/ filter matches by pattern and degrades to substring on invalid regex', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('match')
    const rows = makeRows(4)
    rows[0]!.left = 'foo123 bar'
    rows[1]!.left = 'no digits here'
    queryStore.setResults(rows, 4, true, false)

    const wrapper = mountTable()
    await flushPromises()

    await wrapper.find('.row-filter-input').setValue('/\\d{3}/')
    await flushPromises()
    expect(visibleRowCount(wrapper)).toBe(1)

    // Invalid regex → substring fallback (no crash), error hint shown.
    await wrapper.find('.row-filter-input').setValue('/(/')
    await flushPromises()
    expect(wrapper.find('.row-filter-error').exists()).toBe(true)
  })
})

describe('KwicTable auto context (P1-01)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
  })

  it('does not dispatch a second query for auto-context recomputation', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch')
    try {
      const queryStore = useQueryStore()
      queryStore.setTerm('match')
      queryStore.setResults(makeRows(3), 3, true, false)

      mountTable()
      await flushPromises()
      dispatchSpy.mockClear()

      await new Promise((resolve) => window.setTimeout(resolve, 120))
      await flushPromises()

      expect(dispatchSpy).not.toHaveBeenCalledWith(
        expect.objectContaining({ type: 'query/execute' }),
        expect.objectContaining({ requestId: 'kwic:auto-context' })
      )
    } finally {
      dispatchSpy.mockRestore()
    }
  })
})
