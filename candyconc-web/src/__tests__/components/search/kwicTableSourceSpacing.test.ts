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


// A corpus imported with whitespace_after.bin: the server sends the text as
// written plus token_starts. Collocate and match offsets still count tokens.
describe('KwicTable with the original spacing', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    useUiStore().setActiveTab('kwic')
  })

  it('highlights the collocate behind attached punctuation', async () => {
    const query = useQueryStore()
    query.setTerm('freedom')
    const row: KwicRow = {
      position: 40,
      left: 'the',
      match: 'rights',
      right: 'of people, and freedom now',
      docId: 'd1',
      // right tokens: "of" "people" "," "and" "freedom" "now". A split at
      // whitespace sees "people," as one token and would mark "now".
      collocateOffsets: [5],
      tokenStarts: { left: [0], kw: [0], right: [0, 3, 9, 11, 15, 23] },
      wsBeforeKw: true,
      wsAfterKw: true,
    }
    query.setResults([row], 1, true, false)
    const wrapper = mountTable()
    await flushPromises()
    const right = wrapper.find('[data-testid="kwic-row-right"]')
    expect(right.text()).toContain('of people, and freedom now')
    expect(right.find('.kwic-collocate').exists()).toBe(true)
    expect(right.find('.kwic-collocate').text()).toBe('freedom')
  })

  it('shows an attached second match token without a space', async () => {
    const query = useQueryStore()
    query.setTerm('cql:[word="TRUMAN"] [word="\'S"]')
    query.setResults([
      {
        position: 3,
        left: 'PRESIDENT HARRY S.',
        match: 'TRUMAN',
        right: "'S ADDRESS BEFORE",
        docId: 'd0',
        matchOffsets: [1],
        tokenStarts: { left: [0, 10, 16], kw: [0], right: [0, 3, 11] },
        wsBeforeKw: true,
        wsAfterKw: false,
      },
    ], 1, true, false)
    const wrapper = mountTable()
    await flushPromises()
    expect(wrapper.find('[data-testid="kwic-row-match"]').text()).toBe("TRUMAN'S")
    expect(wrapper.find('[data-testid="kwic-row-right"]').text()).toBe('ADDRESS BEFORE')
  })
})
