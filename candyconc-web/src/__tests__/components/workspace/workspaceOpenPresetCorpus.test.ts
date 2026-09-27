/**
 * Opening a saved analysis activates the corpus it was saved on, or says that
 * the corpus is missing. Before, the analysis opened on whatever corpus was
 * active, and the guide asked the reader to switch by hand first.
 */
import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import WorkspaceAnalysesPanel from '@/components/workspace/WorkspaceAnalysesPanel.vue'
import { actionBus } from '@/actions/bus'
import {
  useAnalysisPresetsStore,
  useCorpusCapabilitiesStore,
  useQueryStore,
  useUiStore,
} from '@/stores'
import type { AnalysisPreset } from '@/stores/analysisPresets'
import type { CorpusSummary } from '@/api/client'

function preset(corpus: string): AnalysisPreset {
  return {
    id: `preset-${corpus}`,
    name: `Freiheit in ${corpus}`,
    createdAt: 1,
    type: 'wordsketch',
    corpus,
    docset: null,
    queryTerm: 'Freiheit',
    params: { term: 'Freiheit' },
    kind: 'saved',
  }
}

function summary(name: string): CorpusSummary {
  return { name, token_count: 10, doc_count: 1 } as unknown as CorpusSummary
}

describe('WorkspaceAnalysesPanel opens a saved analysis on its corpus', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    vi.spyOn(useAnalysisPresetsStore(), 'init').mockResolvedValue()
    vi.spyOn(useAnalysisPresetsStore(), 'touch').mockResolvedValue()
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true })
    useQueryStore().setFilters({ corpus: 'sotu_en' })
    useCorpusCapabilitiesStore().corpora = [summary('sotu_en'), summary('dta_de')]
  })

  it('shows the saved metadata filters on the analysis card', async () => {
    const saved = preset('sotu_en')
    saved.docset = {
      corpus: 'sotu_en',
      docsetId: 'coast-2020',
      stats: { docCount: 1, hitDocCount: 0, refDocCount: 0, tokenCount: 10 },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      filterSpec: { text_group: ['Coast'], year: 2020 },
      includeAi: true,
      includeHuman: true,
    }
    useAnalysisPresetsStore().presets = [saved]

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()

    expect(wrapper.get('.scope-summary').text()).toBe('text_group: Coast · year: 2020')
    wrapper.unmount()
  })

  it('activates the stored corpus before the analysis opens', async () => {
    const corpusStore = useCorpusCapabilitiesStore()
    const queryStore = useQueryStore()
    const setActive = vi.spyOn(corpusStore, 'setActive').mockImplementation(async (name: string) => {
      queryStore.setFilters({ corpus: name })
    })
    useAnalysisPresetsStore().presets = [preset('dta_de')]

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()
    await wrapper.get('button[aria-label="Analyse öffnen"]').trigger('click')
    await flushPromises()

    expect(setActive).toHaveBeenCalledWith('dta_de')
    expect(corpusStore.activeCorpus).toBe('dta_de')
    expect(useAnalysisPresetsStore().pendingPreset?.id).toBe('preset-dta_de')
    expect(actionBus.dispatch).toHaveBeenCalledWith(
      { type: 'nav/switchTab', payload: { tab: 'wordsketch' } },
      { source: 'restore' },
    )
  })

  it('names a corpus that is missing and leaves the analysis closed', async () => {
    const corpusStore = useCorpusCapabilitiesStore()
    const setActive = vi.spyOn(corpusStore, 'setActive')
    const toast = vi.spyOn(useUiStore(), 'showToast')
    useAnalysisPresetsStore().presets = [preset('gone_corpus')]

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()
    await wrapper.get('button[aria-label="Analyse öffnen"]').trigger('click')
    await flushPromises()

    expect(setActive).not.toHaveBeenCalled()
    expect(corpusStore.activeCorpus).toBe('sotu_en')
    expect(toast).toHaveBeenCalledWith(expect.stringContaining('gone_corpus'), 'error')
    expect(useAnalysisPresetsStore().pendingPreset).toBeNull()
    expect(actionBus.dispatch).not.toHaveBeenCalled()
  })

  it('reports a refused activation and stays on the active corpus', async () => {
    const corpusStore = useCorpusCapabilitiesStore()
    vi.spyOn(corpusStore, 'setActive').mockImplementation(async () => {
      corpusStore.activationError = 'Aktivierung abgelehnt'
    })
    const toast = vi.spyOn(useUiStore(), 'showToast')
    useAnalysisPresetsStore().presets = [preset('dta_de')]

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()
    await wrapper.get('button[aria-label="Analyse öffnen"]').trigger('click')
    await flushPromises()

    expect(corpusStore.activeCorpus).toBe('sotu_en')
    expect(toast).toHaveBeenCalledWith('Aktivierung abgelehnt', 'error')
    expect(actionBus.dispatch).not.toHaveBeenCalled()
  })

  it('opens directly when the corpus is already active', async () => {
    const setActive = vi.spyOn(useCorpusCapabilitiesStore(), 'setActive')
    useAnalysisPresetsStore().presets = [preset('sotu_en')]

    const wrapper = mount(WorkspaceAnalysesPanel)
    await nextTick()
    await wrapper.get('button[aria-label="Analyse öffnen"]').trigger('click')
    await flushPromises()

    expect(setActive).not.toHaveBeenCalled()
    expect(useAnalysisPresetsStore().pendingPreset?.id).toBe('preset-sotu_en')
  })
})
