/**
 * K1-Frontend: dezente Stufenanzeige (`copilot.status`) an der laufenden
 * Message und unaufdringliche Aufwands-Fusszeile (`copilot.done`-Bilanz).
 */
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it } from 'vitest'

import ChatMessage from '@/components/copilot/ChatMessage.vue'
import type { ChatMessage as ChatMessageType } from '@/stores'

function makeMessage(overrides: Partial<ChatMessageType> = {}): ChatMessageType {
  return {
    id: 'm-1',
    role: 'assistant',
    content: 'Teilantwort',
    timestamp: 1754900000000,
    ...overrides,
  }
}

describe('ChatMessage Fortschritt + Aufwands-Fusszeile', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('zeigt die Stufenanzeige nur an einer laufenden Message', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          isStreaming: true,
          status: { stage: 'Werkzeuge' },
        }),
      },
    })
    const status = wrapper.find('.stream-status')
    expect(status.exists()).toBe(true)
    expect(status.text()).toBe('Werkzeuge…')
    // Kein Modal: die Anzeige ist ein kleines role=status-Element.
    expect(status.attributes('role')).toBe('status')
  })

  it('traegt das optionale detail als Tooltip', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          isStreaming: true,
          status: { stage: 'Verifikation', detail: 'Grounding-Verifikation' },
        }),
      },
    })
    expect(wrapper.find('.stream-status').attributes('title')).toBe('Grounding-Verifikation')
  })

  it('blendet die Stufenanzeige aus, sobald die Message nicht mehr streamt', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          isStreaming: false,
          status: { stage: 'Antwort' },
        }),
      },
    })
    expect(wrapper.find('.stream-status').exists()).toBe(false)
  })

  it('rendert die Aufwands-Fusszeile kompakt mit Details im Tooltip', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          usage: {
            llmCalls: 3,
            transportRetries: 1,
            elapsedS: 24,
            budgetClass: 'standard',
          },
        }),
      },
    })
    const footer = wrapper.find('.usage-footer')
    expect(footer.exists()).toBe(true)
    expect(footer.text()).toContain('3 LLM-Aufrufe')
    expect(footer.text()).toContain('24 s')
    expect(footer.attributes('title')).toContain('Transport-Wiederholungen: 1')
    expect(footer.attributes('title')).toContain('Budget-Klasse: standard')
  })

  it('formatiert einen einzelnen LLM-Aufruf im Singular', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({ usage: { llmCalls: 1, elapsedS: 7.355 } }),
      },
    })
    const footer = wrapper.find('.usage-footer')
    expect(footer.text()).toContain('1 LLM-Aufruf')
    expect(footer.text()).toMatch(/7[.,]4\s*s/)
  })

  it('kennzeichnet eine Timeout-Teilantwort in der Fusszeile', () => {
    const wrapper = mount(ChatMessage, {
      props: {
        message: makeMessage({
          usage: {
            llmCalls: 2,
            elapsedS: 150.2,
            partial: true,
            timeout: 'Copilot-Zeitlimit (150s) überschritten',
          },
        }),
      },
    })
    const footer = wrapper.find('.usage-footer')
    expect(footer.text()).toContain('Teilantwort')
    expect(footer.attributes('title')).toContain('Zeitlimit')
  })

  it('zeigt ohne usage keine Fusszeile', () => {
    const wrapper = mount(ChatMessage, {
      props: { message: makeMessage() },
    })
    expect(wrapper.find('.usage-footer').exists()).toBe(false)
  })
})
