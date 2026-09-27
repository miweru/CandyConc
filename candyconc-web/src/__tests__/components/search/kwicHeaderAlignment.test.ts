import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KwicTable from '@/components/search/KwicTable.vue'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import type { KwicRow } from '@/stores/query'

/**
 * DESIGN-UX-GLOBAL-01: the sticky KWIC header used independent CSS grids from the
 * body, so a content-sized `auto` Match track resolved to a different width in
 * the header vs. the rows and the labels collided ("MATCHRECHTER KONTEXT"). The
 * header must share the SAME, deterministic column template as the body rows.
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

function makeRows(n: number): KwicRow[] {
  return Array.from({ length: n }, (_, i) => ({
    position: i,
    left: `left ${i}`,
    // A long node token would, under an `auto` track, blow the body's Match
    // column wider than the header's "Match" label.
    match: `SEHR_LANGES_TREFFER_TOKEN_${i}`,
    right: `right ${i}`,
    docId: `doc${i}`,
  }))
}

const mountedWrappers: Array<ReturnType<typeof mount>> = []
afterEach(() => {
  while (mountedWrappers.length) mountedWrappers.pop()?.unmount()
})

function mountTable() {
  const wrapper = mount(KwicTable, {
    global: {
      stubs: {
        Modal: { template: '<div><slot /></div>' },
        DocDetailDrawer: { template: '<div />' },
        AnnotationSchemeEditor: { template: '<div />' },
      },
    },
  })
  mountedWrappers.push(wrapper)
  return wrapper
}

describe('KwicTable sticky-header column alignment (DESIGN-UX-GLOBAL-01)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
  })

  it('header grid and body rows share the same deterministic column template', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('TREFFER')
    queryStore.setResults(makeRows(3), 3, true, false)

    const wrapper = mountTable()
    await flushPromises()

    const header = wrapper.find('.column-header-grid')
    const row = wrapper.find('.row-desktop')
    expect(header.exists()).toBe(true)
    expect(row.exists()).toBe(true)

    const headerCols = (header.element as HTMLElement).style.gridTemplateColumns
    const rowCols = (row.element as HTMLElement).style.gridTemplateColumns

    // Both must use the SAME template — that is what keeps the header over its
    // columns regardless of node-token width.
    expect(headerCols).not.toBe('')
    expect(headerCols).toBe(rowCols)
    // And the Match track must be deterministic (fr-based), not content-sized `auto`.
    expect(headerCols).not.toContain('auto')
    expect(headerCols).toContain('0.55fr')
  })

  it('header still exposes Match and Rechter Kontext as separate cells', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('TREFFER')
    queryStore.setResults(makeRows(2), 2, true, false)

    const wrapper = mountTable()
    await flushPromises()

    const heads = wrapper.findAll('.column-header-grid .col-head').map((h) => h.text())
    expect(heads).toContain('Match')
    expect(heads.some((t) => t.includes('Rechter Kontext'))).toBe(true)
    // They are distinct cells, not a single collided "MATCHRECHTER KONTEXT".
    expect(heads.some((t) => t.includes('MATCHRECHTER'))).toBe(false)
  })
})
