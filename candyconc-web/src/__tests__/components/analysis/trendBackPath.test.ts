/**
 * A trend period (row or chart point) opens the hits of the period in the
 * concordance: the scope is narrowed by a metadata filter on the values of
 * the period, and the same search runs there. Before, the table and the chart
 * had no back path, and the guide described setting the filter by hand.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import TrendTab from '@/components/analysis/TrendTab.vue'
import { actionBus } from '@/actions/bus'
import { useDocsetStore, useQueryStore } from '@/stores'
import { getAnalysisTrend, type TrendResult } from '@/api/client'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAnalysisTrend: vi.fn(),
    getMetaSchema: vi.fn().mockResolvedValue({ schemaVersion: 1, corpus: 'default', metadataFields: [], warnings: [] }),
    getProductCapabilities: vi.fn().mockResolvedValue({ version: 'product-capabilities-v1', scope: 'test', capabilities: [] }),
  }
})

const FIXTURE: TrendResult = {
  query: 'freedom',
  dateField: 'date',
  granularity: 'year',
  periods: [
    { period: '1945', documents: 1, hits: 7, tokens: 2193, perMillion: 3191.97, ciLow: 1500, ciHigh: 6000, values: ['1945-01-06'] },
    { period: '1946', documents: 2, hits: 3, tokens: 30000, perMillion: 100, ciLow: 30, ciHigh: 300, values: ['1946-01-14', '1946-01-21'] },
    { period: 'undatiert', documents: 10, hits: 79, tokens: 90000, perMillion: 877.8, ciLow: 700, ciHigh: 1000 },
  ],
  warnings: [],
  method: { family: 'trend' },
}

const LineChartStub = {
  props: ['data', 'height', 'clickable'],
  emits: ['pointClick'],
  template:
    '<div class="line-chart-stub">' +
    '<button v-for="p in data" :key="p.label" class="chart-point" :data-label="p.label" @click="$emit(\'pointClick\', p)" />' +
    '</div>',
}

const stubs = {
  AnalysisToolbar: { template: '<div class="toolbar"><slot name="left" /><slot name="right" /></div>' },
  JobStatusPill: { template: '<div />' },
  Skeleton: { template: '<div />' },
  LineChart: LineChartStub,
  CapabilityBoundaryPanel: { template: '<div />' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state">{{ title }}</div>' },
}

function mountTrendTab() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return mount(TrendTab, { global: { plugins: [[VueQueryPlugin, { queryClient }]], stubs } })
}

describe('TrendTab back path to the concordance', () => {
  let dispatch: ReturnType<typeof vi.spyOn>
  let narrow: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(getAnalysisTrend as Mock).mockResolvedValue(FIXTURE)
    const queryStore = useQueryStore()
    const docsetStore = useDocsetStore()
    queryStore.setTerm('freedom')
    docsetStore.metaFields = [{ name: 'date', kind: 'date' }]
    docsetStore.metaSchemaHash = 'hash-1'
    dispatch = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
    narrow = vi.spyOn(docsetStore, 'narrowScope').mockImplementation(async () => {
      docsetStore.activeDocsetId = 'docset-period'
      return true
    })
  })

  afterEach(() => {
    dispatch.mockRestore()
    narrow.mockRestore()
  })

  it('asks the server for the values behind each period', async () => {
    mountTrendTab()
    await flushPromises()
    expect((getAnalysisTrend as Mock).mock.calls.at(-1)![0]).toMatchObject({ periodValues: true })
  })

  it('narrows the scope to the values of the period and runs the same search', async () => {
    const wrapper = mountTrendTab()
    await flushPromises()
    const row = wrapper.findAll('[data-testid="trend-row"]')[1]!
    expect(row.classes()).toContain('row-link')

    await row.trigger('click')
    await flushPromises()

    expect(narrow).toHaveBeenCalledWith('date', ['1946-01-14', '1946-01-21'])
    expect(dispatch).toHaveBeenCalledWith({
      type: 'query/execute',
      payload: { term: 'freedom', contextSize: useQueryStore().contextSize, docsetId: 'docset-period' },
    })
    expect(dispatch).toHaveBeenLastCalledWith({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
    expect(useQueryStore().backPathOrigin).toEqual({
      kind: 'trend',
      term: 'freedom',
      query: 'freedom',
      field: 'date',
      period: '1946',
      granularity: 'year',
      hits: 3,
    })
  })

  it('opens a period from its chart point', async () => {
    const wrapper = mountTrendTab()
    await flushPromises()
    await wrapper.get('.chart-point[data-label="1945"]').trigger('click')
    await flushPromises()
    expect(narrow).toHaveBeenCalledWith('date', ['1945-01-06'])
    expect(useQueryStore().backPathOrigin).toMatchObject({ period: '1945', hits: 7 })
  })

  it('gives the undated bucket no back path', async () => {
    const wrapper = mountTrendTab()
    await flushPromises()
    const undated = wrapper.findAll('[data-testid="trend-row"]')[2]!
    expect(undated.classes()).not.toContain('row-link')
    expect(undated.attributes('title')).toContain('ohne lesbares Datum')
    await undated.trigger('click')
    await flushPromises()
    expect(narrow).not.toHaveBeenCalled()
    expect(dispatch).not.toHaveBeenCalled()
  })

  it('stops when the scope cannot be narrowed', async () => {
    narrow.mockResolvedValue(false)
    const wrapper = mountTrendTab()
    await flushPromises()
    await wrapper.findAll('[data-testid="trend-row"]')[0]!.trigger('click')
    await flushPromises()
    expect(dispatch).not.toHaveBeenCalled()
    expect(useQueryStore().backPathOrigin).toBeNull()
  })
})
