/**
 * Analysis views render English labels, messages and number formats when the
 * interface language is English. Every other test runs in German (setup.ts),
 * so these cases are the guard that the analysis and measures catalogs are
 * wired into the views and not only present as keys.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { QueryClient, VueQueryPlugin } from '@tanstack/vue-query'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import TrendTab from '@/components/analysis/TrendTab.vue'
import WordSketchTab from '@/components/analysis/WordSketchTab.vue'
import MethodPanel from '@/components/analysis/MethodPanel.vue'
import MeasureInfo from '@/components/ui/MeasureInfo.vue'
import { getAnalysisTrend, getWordSketch, type TrendResult } from '@/api/client'
import { applyLocale } from '@/i18n/locale'
import {
  useCorpusCapabilitiesStore,
  useDocsetStore,
  useProductCapabilitiesStore,
  useQueryStore,
  useSessionStore,
} from '@/stores'

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return {
    ...actual,
    getAnalysisTrend: vi.fn(),
    getWordSketch: vi.fn(),
    getWordSketchDiff: vi.fn(),
    getMetaSchema: vi.fn().mockResolvedValue({
      schemaVersion: 1,
      corpus: 'default',
      metadataFields: [],
      warnings: [],
    }),
  }
})

/** German words that must not appear in the English rendering of these views. */
const GERMAN_MARKERS = [
  'Periode', 'Dokumente', 'Treffer', 'pro Million', 'undatiert', 'Datumsfeld', 'Granularität',
  'Frequenzverlauf', 'ohne Datum', 'angezeigt', 'gekappt', 'Analysieren', 'Vergleich',
  'Wort eingeben', 'Subjekt von', 'Objekt von', 'Methode', 'Glättung', 'Formel', 'Fenster',
]

function expectNoGerman(text: string) {
  for (const marker of GERMAN_MARKERS) {
    expect(text, `German label "${marker}" in the English view`).not.toContain(marker)
  }
}

function seedUserSession() {
  const session = useSessionStore()
  session.status = 'ready'
  session.session = {
    schema_version: 'auth-session-v1',
    authenticated: true,
    token_present: true,
    username: 'analyst',
    role: 'user',
    effective_role: 'user',
    rbac_enabled: true,
    security_mode: 'release',
    release_mode: true,
    unsafe_token_transport: false,
    dev_token_available: false,
    can_access_all_roles: false,
  }
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.clearAllMocks()
  applyLocale('en')
})

afterEach(() => {
  applyLocale('de')
})

describe('Trend view in English', () => {
  const FIXTURE: TrendResult = {
    query: 'freedom',
    dateField: 'year',
    granularity: 'year',
    periods: [
      { period: '1945', documents: 1, hits: 4, tokens: 5_120, perMillion: 781.25, ciLow: 304.2, ciHigh: 2005.8 },
      { period: '1946', documents: 2, hits: 12, tokens: 104_000, perMillion: 115.38, ciLow: 66.0, ciHigh: 201.6 },
      { period: 'undatiert', documents: 3, hits: 2, tokens: 9_000, perMillion: 222.22, ciLow: 61.1, ciHigh: 800.5 },
    ],
    warnings: [],
    method: { family: 'trend', ci_method: 'wilson_score', ci_level: 0.95 },
  }

  it('labels toolbar, chart, table and the undated bucket in English with US number format', async () => {
    ;(getAnalysisTrend as Mock).mockResolvedValue(FIXTURE)
    useQueryStore().setTerm('freedom')
    const docsetStore = useDocsetStore()
    docsetStore.metaFields = [{ name: 'year', kind: 'number' }]
    docsetStore.metaSchemaHash = 'hash-1'

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(TrendTab, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient }]],
        stubs: {
          LineChart: { template: '<div class="line-chart-stub" />' },
          CapabilityBoundaryPanel: { template: '<div />' },
          JobStatusPill: { template: '<div />' },
          Skeleton: { template: '<div />' },
        },
      },
    })
    await flushPromises()
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Date field:')
    expect(text).toContain('Granularity:')
    expect(text).toContain('Frequency over time · per million word tokens')
    expect(text).toContain('Band = 95% Wilson confidence interval of the word token rate per period.')
    expect(wrapper.findAll('th').map((th) => th.text())).toEqual([
      'Period', 'Documents', 'Hits', 'Tokens', 'Per million', '95% CI',
    ])
    const rows = wrapper.findAll('tbody tr')
    expect(rows[1]!.text()).toContain('104,000')
    expect(rows[1]!.text()).toContain('115.38')
    expect(rows[2]!.text()).toContain('undated')
    expect(rows[2]!.text()).toContain('no date')
    expect(wrapper.find('.undated-banner').text()).toContain(
      "3 documents without a parsable date in the field 'year' are reported as a separate bucket ‘undated’",
    )
    expect(wrapper.find('[aria-label="Export trend as CSV"]').exists()).toBe(true)
    expectNoGerman(text)
  })

  it('shows the English empty state without an active search', async () => {
    useDocsetStore().metaFields = [{ name: 'year', kind: 'number' }]
    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    const wrapper = mount(TrendTab, {
      global: {
        plugins: [[VueQueryPlugin, { queryClient }]],
        stubs: { CapabilityBoundaryPanel: { template: '<div />' } },
      },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('No active search')
    expect(wrapper.text()).toContain('The frequency over time is computed for the active search.')
    expectNoGerman(wrapper.text())
  })
})

describe('Word sketch view in English', () => {
  function seedWordSketchCapabilities() {
    const corpusCapabilities = useCorpusCapabilitiesStore()
    corpusCapabilities.corpora = [{
      name: 'default',
      path: '/tmp/default',
      active: true,
      token_count: 1000,
      doc_count: 10,
      import_mode: 'test',
      paired: false,
      pair_axes: [],
      is_legacy: false,
      capabilities: { rel: true },
      features: {
        schema_version: 'corpus-features-v1',
        token_attributes: [{ id: 'rel', cql_attribute: 'rel', label: 'Relation' }],
      },
    }]
    corpusCapabilities.loaded = true
    const route = {
      path: '/api/v1/analysis/wordsketch',
      methods: ['POST'],
      mutates: false,
      requires_corpus_features: ['token_attributes.rel'],
      access: 'user',
      required_role: 'user',
      transport: 'http',
      route_class: 'product_surface',
    } as const
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = {
      version: 'product-capabilities-v1',
      scope: 'test',
      capabilities: [{
        id: 'analysis.wordsketch',
        title: 'Word Sketch',
        area: 'analysis',
        maturity: 'guarded',
        visibility: 'first_class_ui',
        backend_routes: [route.path],
        backend_route_descriptors: [route],
        operations: [{
          id: 'analysis.wordsketch.profile',
          capability_id: 'analysis.wordsketch',
          label: 'Word Sketch',
          description: '',
          route,
          effects: ['read'],
          handler_key: 'word_sketch',
          surface_slot: 'analysis.wordsketch.profile',
          priority: 10,
        }],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: ['word_sketch'],
        preconditions: [],
        requires_corpus_features: [],
        limits: [],
      }],
    }
    productCapabilities.status = 'ready'
    seedUserSession()
  }

  it('labels controls, relation cards and completeness in English', async () => {
    seedWordSketchCapabilities()
    ;(getWordSketch as Mock).mockResolvedValue({
      term: 'freedom',
      relations: [
        {
          relation: 'amod',
          rowLimit: 2,
          totalCandidates: 3,
          totalRows: 2,
          truncated: true,
          minFreq: 3,
          words: [
            { word: 'human', score: 11.25, frequency: 12 },
            { word: 'economic', score: 9.5, frequency: 7 },
          ],
        },
      ],
      relationLabels: {},
      method: { family: 'wordsketch' },
    })
    const wrapper = mount(WordSketchTab, {
      global: {
        stubs: {
          AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
          CapabilityBoundaryPanel: { template: '<div />' },
          SaveAnalysisButton: { template: '<div />' },
          JobStatusPill: { template: '<div />' },
          Skeleton: { template: '<div />' },
        },
      },
    })
    const input = wrapper.find('input.search-input')
    expect(input.attributes('placeholder')).toBe('Word…')
    await input.setValue('freedom')
    await input.trigger('keyup.enter')
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('Analyze')
    expect(text).toContain('Compare')
    expect(text).toContain('Word sketch for: freedom')
    expect(text).toContain('Adjective modifiers')
    expect(text).toContain('2 of 3 shown')
    expect(text).toContain('capped')
    expect(text).toContain('11.250')
    expect(wrapper.find('.item-score').attributes('title')).toContain('Score = logDice')
    expect(wrapper.find('[aria-label="Export word sketch as CSV"]').exists()).toBe(true)
    expectNoGerman(text)
  })
})

describe('method panel and measure tooltip in English', () => {
  it('names the provenance fields in English', () => {
    const wrapper = mount(MethodPanel, {
      props: {
        method: {
          statistics: [{ key: 'logdice', name: 'logDice', latex_formula: '14 + \\log_2 D', smoothing: 'none', sort_key: 'dice' }],
          window: 5,
          within_sentence: true,
          target_total: 403284,
        },
      },
    })
    const text = wrapper.text()
    expect(text).toContain('Method and reproducibility')
    expect(text).toContain('Statistical provenance (from the server)')
    expect(wrapper.findAll('th').map((th) => th.text())).toEqual(['Statistic', 'Formula', 'Smoothing', 'Sort key'])
    expect(text).toContain('Target tokens')
    expect(text).toContain('403,284')
    expect(text).toContain('Window')
    expect(text).toContain('Within sentence')
    expect(text).toContain('yes')
    expectNoGerman(text)
  })

  it('explains a measure from the static catalog in English before any analysis ran', async () => {
    const wrapper = mount(MeasureInfo, { props: { measureKey: 'mi3' } })
    await wrapper.find('button').trigger('focus')
    const button = wrapper.find('button')
    expect(button.attributes('aria-label')).toBe('Formula and explanation: MI3 (cubic MI)')
    const popover = wrapper.find('[role="tooltip"]')
    expect(popover.text()).toContain('Variant of MI with the observed co-occurrence cubed')
    expect(popover.text()).toContain('Reference: Oakes 1998')
    expect(popover.text()).not.toContain('Kubierung')
  })
})
