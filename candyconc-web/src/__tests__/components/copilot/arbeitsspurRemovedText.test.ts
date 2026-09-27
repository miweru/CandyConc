/**
 * The research trace says what the checks remove, and what they do not.
 *
 * The block "Removed from the answer" said "Anything that fails these checks
 * is removed" (German: "Was das nicht erfüllt, wird gestrichen"). An answer
 * from the synthesis of the collected evidence keeps its quotes: a quote
 * without a match gets a note below the answer
 * (interpretation_synthesis._unverifizierte_zitate), an unknown evidence mark
 * loses its mark and the sentence stays, numbers are not struck in the
 * default setting (CANDYCONC_ZAHLEN_STREICHEN off). Quotes are removed on the
 * other paths only (recipe_runtime, eigene_zitate_bleiben).
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, describe, expect, it } from 'vitest'

import ArbeitsspurGross from '@/components/copilot/ArbeitsspurGross.vue'
import { useCopilotStore } from '@/stores/copilot'
import { applyLocale } from '@/i18n/locale'

afterEach(() => applyLocale('de'))

function trace(): string {
  setActivePinia(createPinia())
  const store = useCopilotStore()
  store.addMessage({ role: 'user', content: 'Frage' })
  store.addMessage({
    role: 'assistant',
    content: 'Antwort',
    annotations: [{ rule: 'zitat_ohne_deckung_entfernt', note: '1 Zitat(e) ohne Deckung entfernt' }],
  })
  return mount(ArbeitsspurGross, { global: { stubs: { Minimize2: true, X: true } } }).text()
}

describe('research trace: removed from the answer', () => {
  it('German: names what stays and what is removed', () => {
    const text = trace()
    expect(text).toContain('Aus der Antwort entfernt')
    expect(text).not.toContain('Was das nicht erfüllt, wird gestrichen')
    expect(text).toContain('bekommt einen Hinweis unter der Antwort')
    expect(text).toContain('im freien Modus ohne Rezept')
  })

  it('English: names what stays and what is removed', () => {
    applyLocale('en')
    const text = trace()
    expect(text).toContain('Removed from the answer')
    expect(text).not.toContain('Anything that fails these checks is removed')
    expect(text).toContain('gets a note below the answer')
    expect(text).toContain('in free mode without a recipe')
  })
})
