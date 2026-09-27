import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import { applyLocale } from '@/i18n/locale'

import KwicPlaceholder from '@/components/search/KwicPlaceholder.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'

describe('KWIC placeholder truth states', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('shows a real zero-results state after an executed search', () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Hase')
    queryStore.setResults([], 0, true, false)
    queryStore.setLastExecutedAt(Date.now())

    const wrapper = mount(KwicPlaceholder, {
      global: {
        stubs: {
          Search: true,
          Sparkles: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Keine Treffer gefunden')
    expect(wrapper.text()).toContain('0 Treffer für')
    expect(wrapper.text()).not.toContain('Suche starten')
  })

  it('keeps the start prompt before any search has executed', () => {
    const wrapper = mount(KwicPlaceholder, {
      global: {
        stubs: {
          Search: true,
          Sparkles: true,
        },
      },
    })

    expect(wrapper.text()).toContain('Suche starten')
    expect(wrapper.text()).not.toContain('Keine Treffer gefunden')
  })

  it('offers the import when the catalogue holds no corpus (first start)', async () => {
    const corpus = useCorpusCapabilitiesStore()
    corpus.$patch({ loaded: true, corpora: [], error: null })
    const ui = useUiStore()

    const wrapper = mount(KwicPlaceholder, {
      global: { stubs: { Search: true, Sparkles: true, FolderInput: true } },
    })

    expect(wrapper.find('[data-testid="kwic-no-corpus"]').exists()).toBe(true)
    // The first-start state was an English literal in the German interface.
    // It now comes from the catalog in both languages.
    expect(wrapper.text()).toContain('Noch kein Korpus')
    expect(wrapper.text()).not.toContain('Suche starten')
    applyLocale('en')
    await nextTick()
    expect(wrapper.text()).toContain('No corpus yet')
    expect(wrapper.text()).toContain('Import a corpus')
    await wrapper.find('button').trigger('click')
    expect(ui.corpusManagerOpen).toBe(true)
  })

  it('keeps the search prompt once a corpus exists', () => {
    const corpus = useCorpusCapabilitiesStore()
    corpus.$patch({ loaded: true, corpora: [{ name: 'A', path: '/a', token_count: 1, doc_count: 1 } as never], error: null })

    const wrapper = mount(KwicPlaceholder, {
      global: { stubs: { Search: true, Sparkles: true, FolderInput: true } },
    })

    expect(wrapper.find('[data-testid="kwic-no-corpus"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('Suche starten')
  })
})
