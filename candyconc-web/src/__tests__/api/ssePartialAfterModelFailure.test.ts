/**
 * The partial answer after a model failure reaches the interface.
 *
 * After a model failure the orchestrator sends `copilot.error`
 * (candyconc_copilot/model_failure.py, orchestrator._finalize_grounded_answer)
 * and the route then lands the answer from the collected evidence:
 * `copilot.grounding` with verdict partial_on_engine_error and `copilot.done`
 * with status partial, the text and the error (routes/copilot.py). The
 * dispatcher let only the first terminal event count, so the partial answer
 * never appeared.
 *
 * Contract: `copilot.done` is the terminal frame. A `copilot.error` is
 * terminal when the stream ends without a `copilot.done`.
 */
import { describe, expect, it, vi } from 'vitest'
import { streamCopilotMessage, type CopilotDoneMeta, type CopilotGroundingEvent } from '@/api/sse'

function sse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

const FEHLER = 'LLM request failed: model engine unreachable'
const TEILANTWORT = 'Aus der gesicherten Evidenz: 436 Treffer von economy.'

function frame(event: string, data: Record<string, unknown>): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`
}

describe('copilot.error followed by a partial copilot.done', () => {
  it('delivers the partial answer with the failure, no error bubble', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sse(
      frame('copilot.session', { sessionId: 's1', status: 'started' })
      + frame('copilot.error', { event: 'copilot.error', error: FEHLER })
      + frame('copilot.grounding', {
        sessionId: 's1',
        grounding: { verdict: 'partial_on_engine_error', annotations: [{ rule: 'engine_error', note: FEHLER }] },
      })
      + frame('copilot.done', {
        sessionId: 's1', status: 'partial', partial: true, error: FEHLER, text: TEILANTWORT, llm_calls_used: 4,
      })
      + frame('copilot.session', { sessionId: 's1', status: 'completed' })
    )))
    const onError = vi.fn()
    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()
    const grounding: CopilotGroundingEvent[] = []
    streamCopilotMessage('q', { onError, onDone, onGrounding: (e) => grounding.push(e), maxRetries: 0 })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(onDone.mock.calls[0]![0]).toBe(TEILANTWORT)
    expect(onDone.mock.calls[0]![1]).toMatchObject({ partial: true, error: FEHLER, llm_calls_used: 4 })
    expect(grounding.map((g) => g.verdict)).toEqual(['partial_on_engine_error'])
    expect(onError).not.toHaveBeenCalled()
  })

  it('an error without a done stays the terminal error', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sse(
      frame('copilot.error', { error: FEHLER })
      + frame('copilot.session', { sessionId: 's1', status: 'error' })
    )))
    const onError = vi.fn<(error: Error) => void>()
    const onDone = vi.fn()
    streamCopilotMessage('q', { onError, onDone, maxRetries: 0 })

    await vi.waitFor(() => expect(onError).toHaveBeenCalled())
    expect(onError.mock.calls[0]![0]!.message).toBe(FEHLER)
    expect(onDone).not.toHaveBeenCalled()
  })
})

describe('the interface shows the partial answer with the failure', () => {
  it('assistant message keeps the partial answer, a notice names the failure', async () => {
    const { createPinia, setActivePinia } = await import('pinia')
    setActivePinia(createPinia())
    const { useProductCapabilitiesStore } = await import('@/stores/productCapabilities')
    const { copilotGroundingContract } = await import('@/__tests__/fixtures/copilotGroundingContract')
    const caps = useProductCapabilitiesStore()
    caps.contract = copilotGroundingContract()
    caps.status = 'ready'
    caps.error = null
    const body = frame('copilot.session', { sessionId: 's1', status: 'started' })
      + frame('copilot.error', { event: 'copilot.error', error: FEHLER })
      + frame('copilot.grounding', {
        sessionId: 's1',
        grounding: { verdict: 'partial_on_engine_error', annotations: [{ rule: 'engine_error', note: FEHLER }] },
      })
      + frame('copilot.done', { sessionId: 's1', status: 'partial', partial: true, error: FEHLER, text: TEILANTWORT })
      + frame('copilot.session', { sessionId: 's1', status: 'completed' })
    vi.stubGlobal('fetch', vi.fn((url: string) => (String(url).includes('/chat/stream')
      ? sse(body)
      : Promise.resolve(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } })))))
    const { useCopilot } = await import('@/composables/useCopilot')
    const { useCopilotStore } = await import('@/stores/copilot')
    await useCopilot().sendMessage('How is economy used?')
    const store = useCopilotStore()
    await vi.waitFor(() => expect(store.messages.find((m) => m.role === 'assistant')?.isStreaming).toBe(false))
    const assistant = store.messages.find((m) => m.role === 'assistant')!
    expect(assistant.content).toBe(TEILANTWORT)
    expect(assistant.error).toBeFalsy()
    expect(assistant.usage?.partial).toBe(true)
    expect(assistant.annotations).toEqual([{ rule: 'engine_error', note: FEHLER }])
    const notices = store.messages.filter((m) => m.role === 'system').map((m) => m.content)
    expect(notices.some((n) => n.startsWith('Ausfall des Modells während des Durchgangs') && n.includes('gesicherten Evidenz'))).toBe(true)
  })
})
