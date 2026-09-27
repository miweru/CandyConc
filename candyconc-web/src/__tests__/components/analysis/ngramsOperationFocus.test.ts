import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import NgramsTab from '@/components/analysis/NgramsTab.vue'
import { useAnalysisJobsStore, useCorpusCapabilitiesStore, useSubcorporaStore, useUiStore } from '@/stores'

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  Button: { props: ['loading'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  CapabilityBoundaryPanel: { template: '<div />' },
  EmptyState: { props: ['title', 'description'], template: '<div class="empty-state">{{ title }}{{ description }}</div>' },
  JobStatusPill: { template: '<div />' },
  SaveAnalysisButton: { template: '<div />' },
  Skeleton: { template: '<div />' },
}

function mountTab(rowsResponse: Record<string, unknown> = {
  rows: [],
  truncated: false,
  row_limit: 500,
  total_candidates: 0,
}) {
  const analysisJobs = useAnalysisJobsStore()
  vi.spyOn(analysisJobs, 'runJobRows').mockResolvedValue(rowsResponse)
  vi.spyOn(analysisJobs, 'clearScope').mockImplementation(() => {})
  vi.spyOn(useSubcorporaStore(), 'init').mockResolvedValue(undefined)

  return mount(NgramsTab, {
    global: { stubs },
  })
}

function seedActiveCorpusCounts() {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  corpusCapabilities.loaded = true
  corpusCapabilities.corpora = [{
    name: 'default',
    path: '/corpora/default',
    active: true,
    token_count: 56_191,
    doc_count: 2_000,
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
  }]
}

function captureCsvBlob() {
  let captured: Blob | null = null
  Object.defineProperty(URL, 'createObjectURL', {
    configurable: true,
    writable: true,
    value: vi.fn((blob: Blob) => {
      captured = blob
      return 'blob:ngrams'
    }),
  })
  Object.defineProperty(URL, 'revokeObjectURL', {
    configurable: true,
    writable: true,
    value: vi.fn(),
  })
  return () => captured
}

async function blobText(blob: Blob): Promise<string> {
  if (typeof blob.text === 'function') return blob.text()
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result ?? ''))
    reader.onerror = () => reject(reader.error)
    reader.readAsText(blob)
  })
}

describe('NgramsTab ProductOperation focus', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('consumes the frequency-job ProductOperation as the frequency mode', async () => {
    const uiStore = useUiStore()
    uiStore.focusProductOperation('analysis.ngrams.frequency_job', {
      capabilityId: 'analysis.ngrams',
      surfaceSlot: 'analysis.ngrams.job',
      preferredMode: 'job',
    })

    const wrapper = mountTab()
    await flushPromises()

    const [frequencyButton, diffButton] = wrapper.findAll('.view-toggle button')
    expect(frequencyButton.classes()).toEqual(expect.arrayContaining(['active', 'operation-focused']))
    expect(diffButton.classes()).not.toContain('active')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('consumes the diff-job ProductOperation as the contrast mode', async () => {
    const uiStore = useUiStore()
    uiStore.focusProductOperation('analysis.ngrams.diff_job', {
      capabilityId: 'analysis.ngrams',
      surfaceSlot: 'analysis.ngrams.diff',
      preferredMode: 'diff',
    })

    const wrapper = mountTab()
    await flushPromises()

    const [, diffButton] = wrapper.findAll('.view-toggle button')
    expect(diffButton.classes()).toEqual(expect.arrayContaining(['active', 'operation-focused']))
    expect(wrapper.text()).toContain('Ziel:')
    expect(wrapper.text()).toContain('Referenz:')
    expect(uiStore.focusedProductOperation).toBeNull()
  })

  it('exports whole-corpus docs and tokens from the corpus catalogue, not empty docset stats', async () => {
    seedActiveCorpusCounts()
    const capturedBlob = captureCsvBlob()

    const wrapper = mountTab({
      rows: [{ ngram: 'Der Hase', freq: 6, n: 2 }],
      truncated: false,
      row_limit: 500,
      total_candidates: 13,
      method: { family: 'ngrams', target_total: 56_191 },
    })
    await flushPromises()

    const csvButton = wrapper.findAll('button').find((button) => button.text().trim() === 'CSV')
    expect(csvButton).toBeTruthy()
    await csvButton!.trigger('click')

    const blob = capturedBlob()
    expect(blob).not.toBeNull()
    const csv = await blobText(blob!)
    expect(csv).toContain('# Docset: all')
    expect(csv).toContain('# Docs: 2000')
    expect(csv).toContain('# Tokens: 56191')
    expect(csv).not.toContain('# Docs: 0')
    expect(csv).not.toContain('# Tokens: 0')
  })

  // Rueckweg: an n-gram row opens its concordance inside one document.
  it('opens the concordance of an n-gram row', async () => {
    seedActiveCorpusCounts()
    const { actionBus } = await import('@/actions/bus')
    const wrapper = mountTab({
      rows: [{ ngram: 'Der Hase', freq: 6, n: 2 }],
      truncated: false,
      row_limit: 500,
      total_candidates: 1,
    })
    await flushPromises()
    const spy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true } as never)
    await wrapper.find('[data-testid="ngram-row-0"]').trigger('click')
    await flushPromises()
    const call = spy.mock.calls.find(([action]) => (action as { type: string }).type === 'query/execute')
    expect((call![0] as { payload: { term: string } }).payload.term)
      .toBe('cql:within(<doc>, [word="Der"] [word="Hase"])')
    spy.mockRestore()
  })

  it('shows filtered-row completeness even when the backend result is not capped', async () => {
    seedActiveCorpusCounts()
    const rows = Array.from({ length: 13 }, (_, index) => ({
      ngram: `ngram ${index}`,
      freq: index < 3 ? 5 : 1,
      n: 2,
    }))

    const wrapper = mountTab({
      rows,
      truncated: false,
      row_limit: 500,
      total_candidates: 13,
      method: { family: 'ngrams', target_total: 56_191 },
    })
    await flushPromises()

    expect(wrapper.text()).toContain('3 angezeigte N-Gramme nach Mindestfrequenz ≥ 5')
    expect(wrapper.text()).toContain('13 vom Backend geladene Kandidaten')
    expect(wrapper.text()).toContain('Backend-Ergebnis nicht gekappt')
  })
})
