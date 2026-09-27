import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import KwicTable from '@/components/search/KwicTable.vue'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import { useDocsetStore } from '@/stores/docset'
import type { KwicRow } from '@/stores/query'

const { BLOCK } = vi.hoisted(() => ({
  BLOCK: 'Parallelgruppen benötigt Korpus-Evidenz, die der aktive Korpus nicht meldet: Parallelgruppen.',
}))

vi.mock('@/composables/useParallelOperations', async () => {
  const { computed, ref } = await import('vue')
  const unavailable = computed(() => false)
  const reason = ref<string | null>(BLOCK)
  const availability = ref({ visible: true })
  return {
    useParallelOperations: () => ({
      groupsAvailability: availability,
      parallelKwicAvailability: availability,
      canLoadParallelGroups: unavailable,
      canOpenAlignment: unavailable,
      canLoadParallelKwic: unavailable,
      parallelGroupsBlockReason: reason,
      alignmentBlockReason: reason,
      parallelKwicBlockReason: reason,
      loadParallelGroups: vi.fn(),
      loadAlignmentRefDoc: vi.fn(),
      loadParallelKwic: vi.fn(),
    }),
  }
})

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

vi.mock('@tanstack/vue-virtual', () => ({
  useVirtualizer: (optionsRef: { value: { count: number } }) => ({
    value: {
      options: { estimateSize: () => 48 },
      getVirtualItems: () =>
        Array.from({ length: optionsRef.value.count }, (_, index) => ({ index, key: index, start: index * 48, size: 48 })),
      getTotalSize: () => optionsRef.value.count * 48,
      scrollToIndex: vi.fn(),
      measure: vi.fn(),
      measureElement: vi.fn(),
    },
  }),
}))

const mounted: Array<ReturnType<typeof mount>> = []
afterEach(() => {
  while (mounted.length) mounted.pop()?.unmount()
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
  mounted.push(wrapper)
  return wrapper
}

function rows(n: number): KwicRow[] {
  return Array.from({ length: n }, (_, i) => ({
    position: i * 10,
    left: `our cause of`,
    match: 'freedom',
    right: `and peace now`,
    docId: `d${i}`,
    collocateOffsets: [2],
  }))
}

describe('KwicTable scope row and Co-KWIC counts', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
  })

  // erprobung B12: a metadata scope on a corpus without parallel groups showed
  // the parallel-group block reason twice, once in red.
  it('shows no parallel-group row for a metadata scope on a plain corpus', async () => {
    const docset = useDocsetStore()
    docset.activeDocsetId = 'ds-republican'
    const query = useQueryStore()
    query.setTerm('freedom')
    query.setResults(rows(2), 2, true, false)
    const wrapper = mountTable()
    await flushPromises()
    expect(wrapper.find('.refdoc-control').exists()).toBe(false)
    expect(wrapper.text()).not.toContain(BLOCK)
  })

  // erprobung B15: a two-word match showed only its first token as the match.
  it('shows a multi-token match whole in the match column', async () => {
    const query = useQueryStore()
    query.setTerm('cql:[word="edlen"] [word="Freiheit"]')
    query.setResults([
      { position: 105322, left: 'welche Folge der', match: 'edlen', right: 'Freiheit ist ; Alles', docId: 'd1', matchOffsets: [1] },
    ], 1, true, false)
    const wrapper = mountTable()
    await flushPromises()
    const cell = wrapper.find('[data-testid="kwic-row-match"]')
    expect(cell.text()).toBe('edlen Freiheit')
    expect(wrapper.find('[data-testid="kwic-row-right"]').text()).not.toContain('Freiheit')
  })

  // erprobung B3: the rows are node hits, O11 counts collocate tokens.
  it('names O11 next to the Co-KWIC anchors', async () => {
    const query = useQueryStore()
    query.setTerm('co(term="freedom", collocate="peace", window=5, within_sentence=true)')
    query.setResults(rows(2), 2, true, false)
    query.setCoKwicCounts({
      rowUnit: 'node_hit',
      nodeHits: 495,
      collocateTokens: { peace: 52 },
      attribute: 'word',
      window: 5,
      withinSentence: true,
    })
    const wrapper = mountTable()
    await flushPromises()
    const o11 = wrapper.find('[data-testid="co-kwic-o11"]')
    expect(o11.exists()).toBe(true)
    expect(o11.text()).toContain('O11: peace 52')
    expect(o11.attributes('title')).toContain('Vereinigung aller Fenster')
  })
})
