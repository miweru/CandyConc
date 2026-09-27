/**
 * The concordance header names the analysis row it was opened from and says
 * how its lines relate to the number of that row.
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'
import { nextTick } from 'vue'

import BackPathChip from '@/components/search/BackPathChip.vue'
import { useQueryStore } from '@/stores/query'
import { useDocsetStore } from '@/stores/docset'
import { applyLocale } from '@/i18n/locale'

const WS_TERM = '[word=freedom] >amod [word=political]'

function wordSketchOrigin(pairs: number, exact = true) {
  return {
    kind: 'wordSketch' as const,
    term: WS_TERM,
    node: 'freedom',
    relation: 'amod',
    relationLabel: 'adjectival modifier',
    collocate: 'political',
    pairs,
    exact,
  }
}

describe('BackPathChip', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('names the word sketch row and stays quiet when the counts agree', async () => {
    const store = useQueryStore()
    store.setTerm(WS_TERM)
    store.setBackPathOrigin(wordSketchOrigin(5))
    store.setTotalHits(5, true, false)
    const wrapper = mount(BackPathChip)
    await nextTick()
    expect(wrapper.get('[data-testid="kwic-back-path-label"]').text())
      .toBe('Aus dem Word Sketch: freedom · adjectival modifier · political, 5 Paare')
    expect(wrapper.find('[data-testid="kwic-back-path-difference"]').exists()).toBe(false)
    expect(wrapper.attributes('title')).toContain('eine Zeile je Kopf')
  })

  it('names both numbers when a head has several dependents', async () => {
    applyLocale('en')
    const store = useQueryStore()
    store.setTerm(WS_TERM)
    store.setBackPathOrigin(wordSketchOrigin(5, false))
    store.setTotalHits(4, true, false)
    const wrapper = mount(BackPathChip)
    await nextTick()
    expect(wrapper.get('[data-testid="kwic-back-path-label"]').text())
      .toBe('From the word sketch: freedom · adjectival modifier · political, 5 pairs')
    expect(wrapper.get('[data-testid="kwic-back-path-difference"]').text())
      .toBe('4 lines for 5 pairs: a head with several dependents of this form in the relation is one line here.')
    expect(wrapper.attributes('title')).toContain('without regard to case')
  })

  it('waits for the final count before it compares', async () => {
    const store = useQueryStore()
    store.setTerm(WS_TERM)
    store.setBackPathOrigin(wordSketchOrigin(5))
    store.setTotalHits(3, false, true)
    const wrapper = mount(BackPathChip)
    await nextTick()
    expect(wrapper.find('[data-testid="kwic-back-path-difference"]').exists()).toBe(false)
  })

  it('shows trend and contrast origins', async () => {
    const store = useQueryStore()
    store.setTerm('freedom')
    store.setBackPathOrigin({ kind: 'trend', term: 'freedom', query: 'freedom', field: 'year', period: '1945', granularity: 'year', hits: 7 })
    store.setTotalHits(7, true, false)
    const wrapper = mount(BackPathChip)
    await nextTick()
    expect(wrapper.text()).toContain('Aus dem Trend: freedom in 1945 (year), 7 Treffer')
    expect(wrapper.find('[data-testid="kwic-back-path-difference"]').exists()).toBe(false)

    useDocsetStore().resetDocset()
    store.setTotalHits(17, true, false)
    await nextTick()
    expect(wrapper.attributes('title')).toBe('Die Periodenzahl umfasst Dokumente, deren Feld year in die Periode 1945 fällt.')
    expect(wrapper.get('[data-testid="kwic-back-path-difference"]').text()).toContain('17 Treffer')

    const coTerm = 'co(term="freedom", collocate="greater", window=5, within_sentence=true)'
    store.setTerm(coTerm)
    store.setBackPathOrigin({
      kind: 'contrast', term: coTerm, node: 'freedom', collocate: 'greater', side: 'target',
      group: 'party = Republican', cooccurrences: 15, perMillion: 75.2,
    })
    store.setTotalHits(14, true, false)
    await nextTick()
    expect(wrapper.text()).toContain('Aus dem Kontrast, Gruppe A (party = Republican): freedom mit greater, 75,2 pro Million, 15 Kookkurrenzen')
    expect(wrapper.get('[data-testid="kwic-back-path-difference"]').text()).toContain('14 Zeilen für 15 Kookkurrenzen')
    expect(wrapper.attributes('title')).toContain('Die Gruppenzahl stammt aus party = Republican.')
  })

  it('disappears with a new search', async () => {
    const store = useQueryStore()
    store.setTerm(WS_TERM)
    store.setBackPathOrigin(wordSketchOrigin(5))
    const wrapper = mount(BackPathChip)
    await nextTick()
    expect(wrapper.find('[data-testid="kwic-back-path"]').exists()).toBe(true)
    store.setTerm('liberty')
    await nextTick()
    expect(wrapper.find('[data-testid="kwic-back-path"]').exists()).toBe(false)
    expect(store.backPathOrigin).toBeNull()
  })
})
