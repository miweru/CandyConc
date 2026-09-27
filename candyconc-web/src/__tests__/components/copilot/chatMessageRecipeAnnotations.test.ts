/**
 * Rezept-Transparenz + beratende Annotationen im Rendering:
 *
 * - Laufende Message: 'Rezept: Kontrast · Werkzeuge…' (recipe_id aus
 *   copilot.status, humanisierte Namen, null = 'Freie Analyse').
 * - done-Fusszeile: Rezeptname vor der Call-Bilanz.
 * - annotations: einklappbarer 'Hinweise'-Block, neutral (Info-Optik, keine
 *   Warnfarben), kein Modal.
 * - Ohne die neuen Felder: unveraendertes Alt-Verhalten (gepinnt).
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import ChatMessage from '@/components/copilot/ChatMessage.vue'
import type { ChatMessage as ChatMessageType } from '@/stores'
import { COPILOT_RECIPE_LABELS, copilotRecipeLabel } from '@/stores/copilot'

function makeMessage(overrides: Partial<ChatMessageType> = {}): ChatMessageType {
  return {
    id: 'm-1',
    role: 'assistant',
    content: 'Teilantwort',
    timestamp: 1754900000000,
    ...overrides,
  }
}

describe('ChatMessage Rezept-Anzeige (copilot.status.recipe_id)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('zeigt den humanisierten Rezeptnamen vor der Stufe', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          isStreaming: true,
          status: { stage: 'Werkzeuge', recipeId: 'kontrast' },
        }),
      },
    })
    expect(wrapper.find('.stream-status').text()).toBe('Rezept: Kontrast · Werkzeuge…')
  })

  it('recipeId null wird als Freie Analyse angezeigt', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          isStreaming: true,
          status: { stage: 'Antwort', recipeId: null },
        }),
      },
    })
    expect(wrapper.find('.stream-status').text()).toBe('Rezept: Freie Analyse · Antwort…')
  })

  it('ohne recipeId bleibt die reine Stufenanzeige (Alt-Backend gepinnt)', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          isStreaming: true,
          status: { stage: 'Werkzeuge' },
        }),
      },
    })
    expect(wrapper.find('.stream-status').text()).toBe('Werkzeuge…')
  })

  it('unbekannte Rezept-IDs erscheinen roh statt zu verschwinden', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          isStreaming: true,
          status: { stage: 'Werkzeuge', recipeId: 'zukunft_rezept' },
        }),
      },
    })
    expect(wrapper.find('.stream-status').text()).toBe('Rezept: zukunft_rezept · Werkzeuge…')
  })

  it('alle acht Rezepte haben einen humanisierten Namen', () => {
    const ids = [
      'frequenz',
      'gebrauch_kwic',
      'assoziation',
      'kontrast',
      'verlauf',
      'profil',
      'metadaten_struktur',
      'exploration_meta',
    ]
    for (const id of ids) {
      expect(COPILOT_RECIPE_LABELS[id], `Label fuer ${id}`).toBeTruthy()
      expect(copilotRecipeLabel(id)).not.toBe(id)
    }
    expect(copilotRecipeLabel(null)).toBe('Freie Analyse')
  })
})

describe('ChatMessage done-Fusszeile mit Rezeptname', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('stellt den Rezeptnamen vor die Call-Bilanz', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          usage: { recipeId: 'kontrast', llmCalls: 3, elapsedS: 24 },
        }),
      },
    })
    const footer = wrapper.find('.usage-footer')
    expect(footer.exists()).toBe(true)
    const text = footer.text()
    expect(text).toContain('Kontrast')
    expect(text).toContain('3 LLM-Aufrufe')
    expect(text.indexOf('Kontrast')).toBeLessThan(text.indexOf('3 LLM-Aufrufe'))
  })

  it('recipeId null erscheint als Freie Analyse in der Fusszeile', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          usage: { recipeId: null, llmCalls: 1 },
        }),
      },
    })
    expect(wrapper.find('.usage-footer').text()).toContain('Freie Analyse')
  })

  it('ohne recipeId bleibt die Fusszeile unveraendert (Alt-Backend gepinnt)', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ usage: { llmCalls: 3, elapsedS: 24 } }),
      },
    })
    const text = wrapper.find('.usage-footer').text()
    expect(text).toContain('3 LLM-Aufrufe')
    expect(text).not.toContain('Rezept')
    expect(text).not.toContain('Freie Analyse')
  })
})

describe('ChatMessage beratende Hinweise (annotations)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  const twoAnnotations = [
    { rule: 'per_million_normierung', note: 'Frequenzen sind pro Million Token normiert.' },
    { rule: 'docset_scope', note: 'Werte gelten nur fuer das aktive Subkorpus.' },
  ]

  it('rendert einen einklappbaren Hinweise-Block unter der Antwort', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ annotations: twoAnnotations }),
      },
    })
    const block = wrapper.find('details.grounding-annotations')
    expect(block.exists()).toBe(true)
    expect(block.find('summary').text()).toContain('Hinweise (2)')
    const items = block.findAll('li')
    expect(items).toHaveLength(2)
    expect(items[0]!.text()).toContain('Frequenzen sind pro Million Token normiert.')
    expect(items[0]!.text()).toContain('per_million_normierung')
    expect(items[1]!.text()).toContain('Werte gelten nur fuer das aktive Subkorpus.')
  })

  it('ist beratend und neutral: kein Modal, keine Warn-Optik, Info-Icon', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ annotations: twoAnnotations }),
      },
    })
    const block = wrapper.find('.grounding-annotations')
    // Einklappbar per <details>, kein role=dialog/alert.
    expect(block.element.tagName.toLowerCase()).toBe('details')
    expect(block.attributes('role')).toBeUndefined()
    expect(wrapper.find('[role="dialog"]').exists()).toBe(false)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    // Info-Icon statt Warn-Icon im Summary.
    expect(block.find('summary .annotation-icon').exists()).toBe(true)
  })

  it('ohne annotations erscheint kein Block (Alt-Backend gepinnt)', () => {
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage() },
    })
    expect(wrapper.find('.grounding-annotations').exists()).toBe(false)

    const empty = mount(ChatMessage, {
      props: { message: makeMessage({ annotations: [] }) },
    })
    expect(empty.find('.grounding-annotations').exists()).toBe(false)
  })

  it('Eintraege ohne note zeigen die Regel als Text', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ annotations: [{ rule: 'nur_regel' }] }),
      },
    })
    const item = wrapper.find('.grounding-annotations li')
    expect(item.text()).toBe('nur_regel')
  })
})
