/**
 * SEM/DE-DE locale parity (P3): the n-gram single-list "pro Mio. Tokens" column
 * must read in the German convention (comma decimal: "2188,96"), like every
 * other statistic value (FrequencyTab / n-grams-diff / Keyness), NOT an English
 * dot-decimal ("2188.96"). Red before the formatGermanDecimal routing, green after.
 */
import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import NgramsTab from '@/components/analysis/NgramsTab.vue'
import { useAnalysisJobsStore, useCorpusCapabilitiesStore, useSubcorporaStore } from '@/stores'

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  Button: { props: ['loading'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  CapabilityBoundaryPanel: { template: '<div />' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state">{{ title }}{{ description }}</div>' },
  JobStatusPill: { template: '<div />' },
  SaveAnalysisButton: { template: '<div />' },
  Skeleton: { template: '<div />' },
}

function seedActiveCorpus(tokenCount: number) {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/tmp/default',
    active: true,
    token_count: tokenCount,
    doc_count: 1,
    import_mode: 'test',
    paired: false,
    pair_axes: [],
    is_legacy: false,
    capabilities: {},
    features: {
      schema_version: 'corpus-features-v1',
      token_attributes: [{ id: 'word', cql_attribute: 'word', label: 'Wortform' }],
      frequency_groups: [{ id: 'word', label: 'Wortform' }],
      semantic: { passage_search: false, word_similarity: false, sentence_alignment: false },
      alignment: { paired: false, pair_axes: [], parallel_groups: false, parallel_kwic: false },
    },
  }] as never
}

function mountTab() {
  const analysisJobs = useAnalysisJobsStore()
  // 12345 occurrences / 5_641_000 tokens → 2188.99 per million (English dot
  // before the fix; comma after). Mocking runJobRows means the real job/start
  // path is never touched.
  vi.spyOn(analysisJobs, 'runJobRows').mockResolvedValue({
    rows: [{ ngram: 'in der', freq: 12345, n: 2 }],
    truncated: false,
    row_limit: 500,
    total_candidates: 1,
  } as never)
  vi.spyOn(analysisJobs, 'clearScope').mockImplementation(() => {})
  vi.spyOn(useSubcorporaStore(), 'init').mockResolvedValue(undefined)

  return mount(NgramsTab, { global: { stubs } })
}

describe('NgramsTab single-list per-million — German decimal locale', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    seedActiveCorpus(5_641_000)
  })

  it('renders the per-million value with a German comma decimal, not an English dot', async () => {
    const wrapper = mountTab()
    await flushPromises()

    // Trigger the frequency-mode refresh (first ghost Button = "Aktualisieren").
    await wrapper.find('button').trigger('click')
    await flushPromises()

    const cell = wrapper.find('td.col-relative')
    expect(cell.exists()).toBe(true)
    const text = cell.text()
    // 12345 / 5_641_000 * 1e6 = 2188,44 → German format: dot thousands, comma
    // decimal. The English-dot bug would render "2188.44" (dot before exactly
    // two trailing decimals, no thousands separator).
    expect(text).toContain(',')
    expect(text).not.toMatch(/\.\d{2}$/) // not the English dot-decimal "2188.44"
    expect(text).toMatch(/^2\.188,\d{2}$/) // de-DE thousands-dot + comma decimal
  })
})
