import { mount, flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import CollocationsTab from '@/components/analysis/CollocationsTab.vue'
import { actionBus } from '@/actions'
import {
  beginCollocationActionHandoff,
  clearCollocationActionHandoff,
  collocationActionHandoff,
  completeCollocationActionHandoff,
} from '@/actions/collocationHandoff'
import { useAnalysisJobsStore, useQueryStore } from '@/stores'

const loadCollocateKwic = vi.fn()
const createCollocationJob = vi.fn()
let cleanupNavHandler: (() => void) | null = null

vi.mock('@/composables/useCollocationOperations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables/useCollocationOperations')>()
  return {
    ...actual,
    useCollocationOperations: () => ({
      createCollocationJob,
      loadCollocateKwic,
      canStartCollocationJob: { value: true },
      canLoadCollocateKwic: { value: true },
      collocationJobBlockReason: { value: null },
      collocationKwicBlockReason: { value: null },
    }),
  }
})

const stubs = {
  AnalysisToolbar: { template: '<div><slot name="left" /><slot name="right" /></div>' },
  Button: { emits: ['click'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
  CapabilityBoundaryPanel: {
    props: ['method'],
    template: '<div data-testid="method-provenance">{{ method?.index_fingerprint || method?.indexFingerprint || "" }}</div>',
  },
  EmptyState: {
    props: ['actionLabel', 'description', 'title'],
    emits: ['action', 'secondaryAction'],
    template: '<button type="button" class="empty-action" @click="$emit(\'action\')">{{ actionLabel || title || description }}</button>',
  },
  ForceGraph: { template: '<div />' },
  JobStatusPill: { template: '<div />' },
  SaveAnalysisButton: { template: '<div />' },
  Skeleton: { template: '<div />' },
}

function mountTab() {
  return mount(CollocationsTab, {
    global: { stubs },
  })
}

describe('CollocationsTab Co-KWIC completeness', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    clearCollocationActionHandoff()
    cleanupNavHandler?.()
    cleanupNavHandler = null
    createCollocationJob.mockResolvedValue({ job_id: 'job-1', status_url: '/jobs/job-1' })
    loadCollocateKwic.mockResolvedValue({
      hits: [{
        position: 7,
        left: 'Der',
        match: 'Hase',
        right: 'läuft',
        doc_id: 'doc-1',
        doc_title: 'Doc 1',
        metadata: {},
        collocate_offsets: [1],
      }],
      total: 2,
      query_time_ms: 2,
      next_offset: 1,
      truncated: false,
    })

    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setFilters({ corpus: 'default' })
    cleanupNavHandler = actionBus.register('nav/switchTab', async () => ({ success: true }))

    const analysisJobs = useAnalysisJobsStore()
    analysisJobs.runJobRows = vi.fn(async () => ({
      rows: [{ word: 'läuft', f: 5, logdice: 8.2, rank: 1 }],
      total_rows: 1,
      total_candidates: 1,
      truncated: false,
    })) as typeof analysisJobs.runJobRows
  })

  afterEach(() => {
    cleanupNavHandler?.()
    cleanupNavHandler = null
  })

  it('keeps the default of five and sends a user-selected minimum of two to the job', async () => {
    const jobs = useAnalysisJobsStore()
    vi.mocked(jobs.runJobRows).mockImplementation(async (options) => {
      await options.start()
      return { rows: [{ word: 'A', f: 2, f2: 3, logdice: 11.6781 }], total_rows: 1, truncated: false }
    })
    const wrapper = mountTab()
    await flushPromises()
    expect(createCollocationJob).toHaveBeenLastCalledWith(expect.objectContaining({ minFreq: 5 }), expect.anything())
    const minimum = wrapper.get('.min-frequency input')
    await minimum.setValue('2')
    await minimum.trigger('blur')
    await flushPromises()
    expect((minimum.element as HTMLInputElement).value).toBe('2')
    expect(createCollocationJob).toHaveBeenLastCalledWith(expect.objectContaining({ minFreq: 2 }), expect.anything())
    expect(wrapper.get('tr.data-row .corpus-freq').text()).toBe('3')
    wrapper.unmount()
  })

  it('marks Co-KWIC launched from a collocation row as partial when the backend page is bounded', async () => {
    const wrapper = mountTab()
    await flushPromises()

    const row = wrapper.find('tr.data-row')
    expect(row.exists()).toBe(true)
    await row.trigger('click')
    await flushPromises()

    const queryStore = useQueryStore()
    expect(loadCollocateKwic).toHaveBeenCalledWith(expect.objectContaining({
      term: 'Hase',
      collocates: ['läuft'],
      corpus: 'default',
      limit: 1000,
    }))
    expect(queryStore.totalPartial).toBe(true)
    // Exact total, partial window (erprobung B11).
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.countIsLowerBound).toBe(false)
    expect(queryStore.hasMore).toBe(true)
    expect(queryStore.nextOffset).toBe(1)
  })

  it('restores method and completeness provenance with a saved collocation result', async () => {
    const wrapper = mountTab()
    await flushPromises()

    const { useAnalysisPresetsStore } = await import('@/stores')
    const presets = useAnalysisPresetsStore()
    presets.isResultValid = vi.fn(async () => true)
    presets.setPending({
      id: 'saved-collocations',
      name: 'Gespeicherte Kollokationen',
      type: 'collocations',
      corpus: 'default',
      docset: null,
      queryTerm: 'Hase',
      params: { windowSize: 5, withinSentence: true, measure: 'logdice', limit: 200 },
      result: { rows: [{ word: 'gespeichert', frequency: 9, score: 8, measure: 'logdice' }] },
      resultMeta: {
        method: { index_fingerprint: 'saved-fingerprint', window: 5, within_sentence: true },
        completeness: {
          rowLimit: 200,
          totalCandidates: 250,
          loadedRows: 200,
          availableRows: 200,
          truncated: true,
        },
      },
      status: 'done',
      kind: 'saved',
      createdAt: 1,
      updatedAt: 1,
      lastAccessedAt: 1,
    })
    await flushPromises()

    expect(wrapper.text()).toContain('saved-fingerprint')
    expect(wrapper.text()).toContain('Top 200 von 250 Kandidaten angezeigt')
  })

  it('renders a completed global action in its original scope without launching a second active-scope job', async () => {
    const handoffId = beginCollocationActionHandoff({
      term: 'Hase',
      windowSize: 7,
      withinSentence: false,
      measure: 'delta_p_nc',
      minFreq: 9,
      limit: 10,
      corpus: 'vergleich',
      docsetId: 'docset-vergleich',
    })
    completeCollocationActionHandoff(handoffId, {
      rows: [{ word: 'Bau', f: 9, mi: 11, delta_p_nc: 0.7 }],
      totalRows: 1,
      rowLimit: 10,
      totalCandidates: 1,
      truncated: false,
      method: { index_fingerprint: 'external-scope-fingerprint' },
    })

    const wrapper = mountTab()
    await flushPromises()

    expect(createCollocationJob).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('Korpus vergleich · Docset docset-vergleich')
    expect(wrapper.text()).toContain('Dieses Ergebnis wurde für Korpus vergleich')
    expect(wrapper.text()).toContain('ΔP (Knoten→Kollokat)')
    expect(wrapper.text()).toContain('0,700')
    expect(wrapper.text()).toContain('external-scope-fingerprint')
    expect(collocationActionHandoff.value).toBeNull()
  })
})
