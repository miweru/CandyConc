import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import TrendTab from '@/components/analysis/TrendTab.vue'
import { useDocsetStore, useQueryStore } from '@/stores'
import { getAnalysisTrend, type TrendResult } from '@/api/client'
import { downloadCsv } from '@/utils/csv'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAnalysisTrend: vi.fn(),
    getMetaSchema: vi.fn().mockResolvedValue({
      schemaVersion: 1,
      corpus: 'default',
      metadataFields: [],
      warnings: [],
    }),
    getProductCapabilities: vi.fn().mockResolvedValue({
      version: 'product-capabilities-v1',
      scope: 'test',
      capabilities: [],
    }),
  }
})

vi.mock('@/utils/csv', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/utils/csv')>()
  return {
    ...actual,
    downloadCsv: vi.fn(),
  }
})

const FIXTURE: TrendResult = {
  query: 'Klima',
  dateField: 'date',
  granularity: 'year',
  periods: [
    {
      period: '2020',
      documents: 12,
      hits: 30,
      tokens: 100_000,
      perMillion: 300,
      ciLow: 210.12,
      ciHigh: 428.57,
    },
    {
      period: '2021',
      documents: 9,
      hits: 5,
      tokens: 50_000,
      perMillion: 100,
      ciLow: 42.7,
      ciHigh: 233.9,
    },
    {
      period: 'undatiert',
      documents: 3,
      hits: 2,
      tokens: 9_000,
      perMillion: 222.22,
      ciLow: 61.1,
      ciHigh: 800.5,
    },
  ],
  warnings: [
    "3 Dokument(e) ohne parsbaren Datumswert im Feld 'date' wurden dem Bucket 'undatiert' zugeordnet.",
  ],
  method: {
    family: 'trend',
    ci_method: 'wilson_score',
    ci_level: 0.95,
    rate_definition: 'per_million = hits / tokens * 10^6 je Periode',
  },
}

const LineChartStub = {
  props: ['data', 'height'],
  template:
    '<div class="line-chart-stub">' +
    '<span v-for="p in data" :key="p.label" class="chart-point" :data-label="p.label" />' +
    '</div>',
}

const BoundaryStub = {
  props: ['capabilityId', 'method', 'runtimeLimitations', 'runtimeNotes', 'compact'],
  template:
    '<div class="boundary-stub" :data-capability="capabilityId">' +
    '<span class="boundary-family">{{ method?.family }}</span>' +
    '<span class="boundary-ci">{{ method?.ci_method }}</span>' +
    '<span v-for="w in (runtimeLimitations ?? [])" :key="w" class="boundary-warning">{{ w }}</span>' +
    '</div>',
}

const stubs = {
  AnalysisToolbar: { template: '<div class="toolbar"><slot name="left" /><slot name="right" /></div>' },
  JobStatusPill: { template: '<div />' },
  Skeleton: { template: '<div />' },
  LineChart: LineChartStub,
  CapabilityBoundaryPanel: BoundaryStub,
  EmptyState: {
    props: ['title', 'description'],
    template: '<div class="empty-state"><strong>{{ title }}</strong><span>{{ description }}</span><slot /></div>',
  },
}

function mountTrendTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return mount(TrendTab, {
    global: {
      plugins: [[VueQueryPlugin, { queryClient }]],
      stubs,
    },
  })
}

function seedStores(options: {
  term?: string
  metaFields?: Array<{ name: string; kind: 'enum' | 'number' | 'date' | 'text' }>
} = {}) {
  const queryStore = useQueryStore()
  const docsetStore = useDocsetStore()
  if (options.term) queryStore.setTerm(options.term)
  // Pre-seed the meta schema so loadMetaSchema() early-returns without I/O.
  docsetStore.metaFields = options.metaFields ?? []
  docsetStore.metaSchemaHash = options.metaFields?.length ? 'hash-1' : null
  return { queryStore, docsetStore }
}

describe('TrendTab', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    ;(getAnalysisTrend as Mock).mockResolvedValue(FIXTURE)
  })

  it('renders periods with CI in the table and marks the undatiert bucket', async () => {
    seedStores({
      term: 'Klima',
      metaFields: [
        { name: 'date', kind: 'date' },
        { name: 'register', kind: 'enum' },
      ],
    })
    const wrapper = mountTrendTab()
    await flushPromises()

    const rows = wrapper.findAll('tbody tr')
    expect(rows).toHaveLength(3)
    expect(rows[0]!.text()).toContain('2020')
    expect(rows[0]!.text()).toContain('30')
    expect(rows[0]!.text()).toContain('100.000')
    expect(rows[0]!.text()).toContain('300,00')
    expect(rows[0]!.text()).toContain('210,12 bis 428,57')

    // undatiert row is visually flagged and announced in the banner.
    expect(rows[2]!.classes()).toContain('undated-row')
    expect(rows[2]!.text()).toContain('undatiert')
    expect(wrapper.find('.undated-banner').exists()).toBe(true)
    expect(wrapper.find('.undated-banner').text()).toContain('undatiert')
  })

  it('passes only dated periods to the line chart', async () => {
    seedStores({ term: 'Klima', metaFields: [{ name: 'date', kind: 'date' }] })
    const wrapper = mountTrendTab()
    await flushPromises()

    const points = wrapper.findAll('.chart-point')
    expect(points.map((p) => p.attributes('data-label'))).toEqual(['2020', '2021'])
  })

  it('requests the trend with selected date field, granularity and scope', async () => {
    seedStores({
      term: 'Klima',
      metaFields: [
        { name: 'register', kind: 'enum' },
        { name: 'pub_year', kind: 'number' },
      ],
    })
    const wrapper = mountTrendTab()
    await flushPromises()

    // pub_year matches the date-name heuristic and is auto-selected.
    expect(getAnalysisTrend).toHaveBeenCalled()
    const [params] = (getAnalysisTrend as Mock).mock.calls.at(-1)!
    expect(params).toMatchObject({
      query: 'Klima',
      dateField: 'pub_year',
      granularity: 'year',
      corpus: 'default',
    })

    // Switching granularity triggers a new request with month buckets.
    const selects = wrapper.findAll('select')
    await selects[1]!.setValue('month')
    await flushPromises()
    const [monthParams] = (getAnalysisTrend as Mock).mock.calls.at(-1)!
    expect(monthParams).toMatchObject({ dateField: 'pub_year', granularity: 'month' })
  })

  it('renders the server method block through the boundary panel', async () => {
    seedStores({ term: 'Klima', metaFields: [{ name: 'date', kind: 'date' }] })
    const wrapper = mountTrendTab()
    await flushPromises()

    const boundary = wrapper.find('.boundary-stub')
    expect(boundary.exists()).toBe(true)
    expect(boundary.attributes('data-capability')).toBe('analysis.trend')
    expect(boundary.find('.boundary-family').text()).toBe('trend')
    expect(boundary.find('.boundary-ci').text()).toBe('wilson_score')
    expect(boundary.findAll('.boundary-warning')).toHaveLength(1)
  })

  it('shows an honest empty state when the corpus has no metadata fields', async () => {
    seedStores({ term: 'Klima', metaFields: [] })
    const wrapper = mountTrendTab()
    await flushPromises()

    expect(wrapper.find('.empty-state').text()).toContain('Keine Metadatenfelder verfügbar')
    expect(getAnalysisTrend).not.toHaveBeenCalled()
  })

  it('offers free field choice when no field looks like a date', async () => {
    seedStores({ term: 'Klima', metaFields: [{ name: 'register', kind: 'enum' }] })
    const wrapper = mountTrendTab()
    await flushPromises()

    // No auto-selection, honest hint, but the field select stays usable.
    expect(getAnalysisTrend).not.toHaveBeenCalled()
    expect(wrapper.find('.empty-state').text()).toContain('Kein Datumsfeld gewählt')
    const fieldSelect = wrapper.findAll('select')[0]!
    expect(fieldSelect.findAll('option').map((o) => o.text())).toContain('register')

    await fieldSelect.setValue('register')
    await flushPromises()
    const [params] = (getAnalysisTrend as Mock).mock.calls.at(-1)!
    expect(params).toMatchObject({ dateField: 'register' })
  })

  it('exports the full period table incl. undatiert and provenance meta as CSV', async () => {
    seedStores({ term: 'Klima', metaFields: [{ name: 'date', kind: 'date' }] })
    const wrapper = mountTrendTab()
    await flushPromises()

    await wrapper.find('button[aria-label="Trend als CSV exportieren"]').trigger('click')

    expect(downloadCsv).toHaveBeenCalledTimes(1)
    const [csv, filename] = (downloadCsv as Mock).mock.calls[0]!
    expect(String(filename)).toContain('trend_')
    const content = String(csv)
    expect(content).toContain('period,documents,hits,tokens,per_million,ci_low,ci_high')
    expect(content).toContain('2020,12,30,100000,300,210.12,428.57')
    expect(content).toContain('undatiert,3,2,9000,222.22,61.1,800.5')
    expect(content).toContain('# ci_method: wilson_score')
    expect(content).toContain('# DateField: date')
  })
})
