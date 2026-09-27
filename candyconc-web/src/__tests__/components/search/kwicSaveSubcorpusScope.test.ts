import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import * as api from '@/api/client'
import KwicTable from '@/components/search/KwicTable.vue'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import { useDocsetStore } from '@/stores/docset'
import { useSubcorporaStore, type SubcorpusSnapshot } from '@/stores/subcorpora'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
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
    left: 'defend our',
    match: 'freedom',
    right: 'and peace',
    docId: `d${i}`,
  }))
}

describe('KwicTable: save subcorpus from hits keeps the active scope (erprobung B2)', () => {
  let saved: SubcorpusSnapshot[]

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    useUiStore().setActiveTab('kwic')
    saved = []
    vi.spyOn(useProductCapabilitiesStore(), 'assertProductOperationAccess').mockResolvedValue({
      visible: true,
      enabled: true,
      disabledReason: null,
      operations: [],
    })
    vi.spyOn(api, 'createDocsetFromSearch').mockResolvedValue({
      docset_id: 'ds-hits',
      doc_count: 33,
      hit_doc_count: 33,
      ref_doc_count: 0,
      token_count: 190000,
    } as Awaited<ReturnType<typeof api.createDocsetFromSearch>>)
    const subcorpora = useSubcorporaStore()
    vi.spyOn(subcorpora, 'add').mockImplementation((snapshot: SubcorpusSnapshot) => {
      saved.push(snapshot)
      return true
    })
  })

  async function saveFromHits() {
    const query = useQueryStore()
    query.setTerm('freedom')
    query.setResults(rows(3), 330, true, false)
    const wrapper = mountTable()
    await flushPromises()
    const open = wrapper.findAll('button').find((b) => b.text().includes('Subkorpus speichern'))
    expect(open).toBeTruthy()
    await open!.trigger('click')
    await flushPromises()
    await wrapper.get('.name-input').setValue('republican_addresses')
    const confirm = wrapper.findAll('.name-actions button').at(1)!
    await confirm.trigger('click')
    await flushPromises()
    return wrapper
  }

  it('stores the metadata filter of the scope with the query', async () => {
    const docset = useDocsetStore()
    docset.activeDocsetId = 'ds-republican'
    docset.activeFilterSpec = { party: ['Republican'] }
    docset.activeDocsetOrigin = { kind: 'meta' }
    docset.stats = { docCount: 36, hitDocCount: 0, refDocCount: 0, tokenCount: 199379 }

    await saveFromHits()

    expect(api.createDocsetFromSearch).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'freedom', metaFilters: { party: ['Republican'] } }),
    )
    expect(saved).toHaveLength(1)
    const snapshot = saved[0]!
    expect(snapshot.name).toBe('republican_addresses')
    expect(snapshot.filterSpec).toEqual({ party: ['Republican'] })
    expect(snapshot.origin).toEqual({ type: 'query', query: 'freedom' })
    // The counts are those of the hit documents inside the scope, not of the scope.
    expect(snapshot.stats.docCount).toBe(33)
    expect(snapshot.docsetId).toBe('ds-hits')
    // The active scope is unchanged.
    expect(docset.activeDocsetId).toBe('ds-republican')
    expect(docset.activeFilterSpec).toEqual({ party: ['Republican'] })
  })

  it('saves a plain query without a scope as query-only subcorpus', async () => {
    await saveFromHits()
    expect(api.createDocsetFromSearch).toHaveBeenCalledWith(
      expect.objectContaining({ query: 'freedom', metaFilters: undefined }),
    )
    expect(saved[0]!.filterSpec).toEqual({})
    expect(useDocsetStore().activeDocsetId).toBeNull()
  })

  it('names the field of the dialog "Name subcorpus" through its label', async () => {
    const query = useQueryStore()
    query.setTerm('freedom')
    query.setResults(rows(3), 330, true, false)
    const wrapper = mountTable()
    await flushPromises()
    const open = wrapper.findAll('button').find((b) => b.text().includes('Subkorpus speichern'))
    await open!.trigger('click')
    await flushPromises()
    const input = wrapper.get('.name-input').element as HTMLInputElement
    const label = wrapper.get('.name-label').element as HTMLLabelElement
    expect(input.id).not.toBe('')
    expect(label.htmlFor).toBe(input.id)
  })

  it('keeps the metadata fields of a query scope when a new term rebuilds it', async () => {
    const docset = useDocsetStore()
    docset.activeDocsetId = 'ds-saved'
    docset.activeFilterSpec = { party: ['Republican'] }
    docset.activeDocsetOrigin = { kind: 'search', query: 'freedom' }
    vi.spyOn(useProductCapabilitiesStore(), 'isVisible').mockReturnValue(true)
    const built = await docset.buildDocset(true, 'liberty')
    expect(built).toBe(true)
    expect(api.createDocsetFromSearch).toHaveBeenLastCalledWith(
      expect.objectContaining({ query: 'liberty', metaFilters: { party: ['Republican'] } }),
    )
    expect(docset.activeFilterSpec).toEqual({ party: ['Republican'] })
  })
})
