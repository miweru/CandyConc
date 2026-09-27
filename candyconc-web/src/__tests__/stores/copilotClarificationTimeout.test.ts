/**
 * The notice after an unanswered clarification names the time the question
 * actually waited. Before, it always said 60 seconds, also when the
 * clarification carried another timeout.
 */
import { createPinia, setActivePinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { applyLocale } from '@/i18n/locale'
import { useCopilotStore } from '@/stores/copilot'

function clarification(timeout?: number) {
  return {
    id: 'q1',
    explanation: 'Which corpus?',
    options: [{ id: 'a', label: 'A', value: 'a' }],
    answered: false,
    ...(timeout === undefined ? {} : { timeout }),
  }
}

function lastSystemMessage(store: ReturnType<typeof useCopilotStore>): string {
  const system = store.messages.filter((message) => message.role === 'system')
  return system[system.length - 1]?.content ?? ''
}

beforeEach(() => {
  setActivePinia(createPinia())
  vi.useFakeTimers()
})

afterEach(() => {
  vi.useRealTimers()
  applyLocale('de')
})

describe('clarification timeout notice', () => {
  it('names the configured timeout, not a fixed 60 seconds', () => {
    const store = useCopilotStore()
    store.addMessage({ role: 'assistant', content: 'Question', clarification: clarification(90_000) })

    vi.advanceTimersByTime(89_999)
    expect(lastSystemMessage(store)).toBe('')

    vi.advanceTimersByTime(1)
    expect(lastSystemMessage(store)).toContain('90')
    expect(lastSystemMessage(store)).not.toContain('60')
  })

  it('names the default timeout in English', () => {
    applyLocale('en')
    const store = useCopilotStore()
    store.addMessage({ role: 'assistant', content: 'Question', clarification: clarification() })

    vi.advanceTimersByTime(60_000)
    expect(lastSystemMessage(store)).toBe('[No answer within 60 s. Action cancelled.]')
  })

  it('formats a timeout with a fraction of a second in the interface language', () => {
    const store = useCopilotStore()
    store.addMessage({ role: 'assistant', content: 'Question', clarification: clarification(1_500) })

    vi.advanceTimersByTime(1_500)
    expect(lastSystemMessage(store)).toBe('[Keine Antwort innerhalb von 1,5 s. Aktion abgebrochen.]')
  })
})
