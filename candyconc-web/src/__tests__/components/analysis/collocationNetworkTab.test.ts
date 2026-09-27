import { mount, flushPromises } from '@vue/test-utils'
import { setActivePinia, createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import CollocationNetworkTab from '@/components/analysis/CollocationNetworkTab.vue'
import { getCollocationNetwork } from '@/api/client'
import { useDocsetStore, useQueryStore } from '@/stores'

const apiMocks = vi.hoisted(() => ({
  getCollocationNetwork: vi.fn(),
}))

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getCollocationNetwork: apiMocks.getCollocationNetwork,
  }
})

vi.mock('@/composables/useCollocationNetworkOperations', () => ({
  useCollocationNetworkOperations: () => ({
    assertCanLoadCollocationNetwork: vi.fn().mockResolvedValue(undefined),
    loadCollocationNetwork: apiMocks.getCollocationNetwork,
    canLoadCollocationNetwork: { __v_isRef: true, value: true },
    collocationNetworkBlockReason: { __v_isRef: true, value: null },
  }),
}))

// Stub the D3 child so the test does not depend on SVG layout / animation.
const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state">{{ title }} {{ description }}</div>' },
  Skeleton: { template: '<div class="skeleton" />' },
  CollocationNetworkGraph: {
    props: ['nodes', 'edges', 'measureLabel', 'showEdgeLabels', 'height'],
    template: '<div class="cn-graph-stub" :data-nodes="nodes.length" :data-edges="edges.length" />',
  },
}

const SAMPLE = {
  term: 'alpha',
  measure: 'logdice',
  nodes: [
    { id: 'alpha', freq: null, depth: 0 },
    { id: 'beta', freq: 12, depth: 1 },
  ],
  edges: [{ source: 'alpha', target: 'beta', weight: 9.2, measure: 'logdice' }],
  diagnostics: { node_count: 2, edge_count: 1, second_order_count: 0, truncated: false },
}

function mountTab() {
  return mount(CollocationNetworkTab, { global: { stubs } })
}

describe('CollocationNetworkTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    ;(getCollocationNetwork as Mock).mockReset()
    ;(getCollocationNetwork as Mock).mockResolvedValue(SAMPLE)
  })

  it('shows the empty no-query state without calling the endpoint', async () => {
    const wrapper = mountTab()
    await flushPromises()
    expect(getCollocationNetwork).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Keine Suche aktiv')
  })

  it('loads and renders the network for the active term', async () => {
    useQueryStore().setTerm('alpha')
    const wrapper = mountTab()
    await flushPromises()

    expect(getCollocationNetwork).toHaveBeenCalledWith(
      expect.objectContaining({ term: 'alpha', corpus: 'default', expandDepth: 1 })
    )
    const graph = wrapper.find('.cn-graph-stub')
    expect(graph.exists()).toBe(true)
    expect(graph.attributes('data-nodes')).toBe('2')
    expect(graph.attributes('data-edges')).toBe('1')
  })

  it('forwards the active docset id when scoped', async () => {
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-1'
    docsetStore.stats = { docCount: 2, hitDocCount: 2, refDocCount: 0, tokenCount: 100 }
    docsetStore.isDirty = false
    useQueryStore().setTerm('alpha')

    mountTab()
    await flushPromises()

    expect(getCollocationNetwork).toHaveBeenCalledWith(
      expect.objectContaining({ term: 'alpha', docsetId: 'docset-1' })
    )
  })

  it('renders the error state when the endpoint fails', async () => {
    ;(getCollocationNetwork as Mock).mockRejectedValueOnce(new Error('boom'))
    useQueryStore().setTerm('alpha')
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.text()).toContain('Fehler bei der Analyse')
    expect(wrapper.text()).toContain('boom')
  })

  it('shows the empty-result state when no edges come back', async () => {
    ;(getCollocationNetwork as Mock).mockResolvedValueOnce({
      term: 'alpha',
      measure: 'logdice',
      nodes: [{ id: 'alpha', freq: null, depth: 0 }],
      edges: [],
      diagnostics: {},
    })
    useQueryStore().setTerm('alpha')
    const wrapper = mountTab()
    await flushPromises()

    expect(wrapper.text()).toContain('Kein Netzwerk gefunden')
  })
})
