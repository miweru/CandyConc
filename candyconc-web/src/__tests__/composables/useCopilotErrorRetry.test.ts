import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { copilotGroundingContract } from '@/__tests__/fixtures/copilotGroundingContract'

interface StreamHandlers {
  onContent?: (content: string) => void
  onError?: (error: Error) => void
  onDone?: (content: string) => void
  onClarifyV1?: (question: {
    questionId: string
    prompt: string
    blocking: boolean
    options: Array<{ id: string; label: string; value: unknown }>
  }) => void
  onGrounding?: (grounding: Record<string, unknown>) => void
  onEvidenceGap?: (gap: Record<string, unknown>) => void
  onRecovery?: (recovery: Record<string, unknown>) => void
}

const sseMocks = vi.hoisted(() => ({
  streamCopilotMessage: vi.fn(),
  approveAction: vi.fn(),
  rejectAction: vi.fn(),
  answerClarification: vi.fn(),
  updateCopilotContext: vi.fn(),
  getCurrentSessionId: vi.fn(() => null),
  continueCopilotExecution: vi.fn(),
}))

vi.mock('@/api/sse', () => sseMocks)

vi.mock('@/composables/useContextSnapshot', () => ({
  useContextSnapshot: () => ({
    buildSnapshotSync: () => ({ version: '1.0', ts: 1 }),
  }),
}))

import { useCopilot, localizeCopilotError } from '@/composables/useCopilot'

function lastAssistant() {
  const messages = useCopilotStore().messages
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]!.role === 'assistant') return messages[i]!
  }
  return undefined
}

describe('useCopilot stream error + retry', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = copilotGroundingContract()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
  })

  it('surfaces the error notice even when only whitespace was streamed (id 3)', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        // A single whitespace delta arrives before the failure — this used to
        // make fullContent truthy and suppress the fallback.
        handlers.onContent?.(' ')
        handlers.onError?.(new Error('TimeoutError'))
        return vi.fn()
      }
    )

    const copilot = useCopilot()
    await copilot.sendMessage('Vergleiche demo und default')

    const assistant = lastAssistant()
    expect(assistant?.content).toContain('Fehler: TimeoutError')
    expect(assistant?.error).toBe(true)
    expect(assistant?.retryPrompt).toBe('Vergleiche demo und default')
  })

  it('preserves already-received prose and appends the error (id 0)', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        handlers.onContent?.('Teilantwort')
        handlers.onError?.(new Error('TimeoutError'))
        return vi.fn()
      }
    )

    const copilot = useCopilot()
    await copilot.sendMessage('frage')

    const assistant = lastAssistant()
    expect(assistant?.content).toContain('Teilantwort')
    expect(assistant?.content).toContain('Fehler: TimeoutError')
  })

  it('retryMessage clears the failed marker and re-sends the original prompt (id 0)', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        handlers.onError?.(new Error('TimeoutError'))
        return vi.fn()
      }
    )

    const copilot = useCopilot()
    await copilot.sendMessage('original prompt')

    const failed = lastAssistant()!
    expect(failed.error).toBe(true)

    // Second send succeeds.
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        handlers.onDone?.('jetzt erfolgreich')
        return vi.fn()
      }
    )

    await copilot.retryMessage(failed.id)

    // The originally-failed bubble no longer advertises a retry.
    const cleared = useCopilotStore().messages.find(m => m.id === failed.id)
    expect(cleared?.error).toBe(false)
    expect(cleared?.retryPrompt).toBeUndefined()

    // The retry re-sent the original prompt.
    expect(sseMocks.streamCopilotMessage).toHaveBeenCalledTimes(2)
    expect(sseMocks.streamCopilotMessage.mock.calls[1]![0]).toBe('original prompt')
  })

  it('makes a blocked chatStream recoverable: the system bubble carries a retry that re-fires (COPILOT-1)', async () => {
    // Remove the chatStream operation so the access gate denies it. The block
    // must not be a dead end — the bubble carries error+retryPrompt so the
    // in-app "Erneut versuchen" affordance can re-send the original prompt.
    const productCapabilities = useProductCapabilitiesStore()
    const grounding = productCapabilities.contract!.capabilities.find(
      (c) => c.id === 'research.copilot_grounding',
    )!
    grounding.operations = grounding.operations.filter(
      (op) => op.id !== 'research.copilot_grounding.chat_stream',
    )

    const copilot = useCopilot()
    await copilot.sendMessage('blockierter prompt')

    const store = useCopilotStore()
    const blocked = store.messages.find((m) => m.role === 'system' && m.retryPrompt)
    expect(blocked).toBeDefined()
    expect(blocked?.error).toBe(true)
    expect(blocked?.retryPrompt).toBe('blockierter prompt')
    // The native stream was never called for the blocked turn.
    expect(sseMocks.streamCopilotMessage).not.toHaveBeenCalled()

    // Re-grant the operation and retry: the request re-fires.
    productCapabilities.contract = copilotGroundingContract()
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        handlers.onDone?.('jetzt erlaubt')
        return vi.fn()
      },
    )
    await copilot.retryMessage(blocked!.id)
    expect(sseMocks.streamCopilotMessage).toHaveBeenCalledTimes(1)
    expect(sseMocks.streamCopilotMessage.mock.calls[0]![0]).toBe('blockierter prompt')
  })

  it('localises a network fetch TypeError to a German "Backend nicht erreichbar" notice (COPILOT-4)', async () => {
    const networkError = new TypeError('Failed to fetch')
    expect(localizeCopilotError(networkError)).toContain('Backend nicht erreichbar')
    // A non-network error message is passed through verbatim.
    expect(localizeCopilotError(new Error('HTTP 503'))).toBe('HTTP 503')

    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        handlers.onError?.(networkError)
        return vi.fn()
      },
    )
    const copilot = useCopilot()
    await copilot.sendMessage('netzwerk weg')
    const assistant = lastAssistant()
    expect(assistant?.content).toContain('Backend nicht erreichbar')
    expect(assistant?.content).not.toContain('Failed to fetch')
  })

  it('sends the live autonomy level at ui_context.autonomy_level (id 1)', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        handlers.onDone?.('ok')
        return vi.fn()
      }
    )

    const store = useCopilotStore()
    store.setAutonomyLevel(0)

    const copilot = useCopilot()
    await copilot.sendMessage('mutating request')

    const options = sseMocks.streamCopilotMessage.mock.calls[0]![1] as {
      snapshot?: Record<string, unknown>
    }
    expect(options.snapshot?.autonomy_level).toBe(0)
  })

  it('surfaces backend grounding, evidence-gap and recovery events as visible system notices', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, handlers: StreamHandlers) => {
        handlers.onGrounding?.({
          analysis_family: 'exploratory',
          verdict: 'conservative_only',
          rejected_claim_count: 2,
          route: 'responses',
          model: 'qwen',
        })
        handlers.onEvidenceGap?.({
          analysis_family: 'exploratory',
          gaps: ['keine belastbare Belegzeile'],
          model: 'qwen',
        })
        handlers.onRecovery?.({
          kind: 'llm_timeout',
          message: 'Fallback auf konservative Antwort',
          retryable: true,
        })
        handlers.onDone?.('fertig')
        return vi.fn()
      }
    )

    const copilot = useCopilot()
    await copilot.sendMessage('erzähle interessante Sachen')

    const systemMessages = useCopilotStore().messages
      .filter((message) => message.role === 'system')
      .map((message) => message.content)
    expect(systemMessages).toContain(
      'Grounding geprüft: konservativ begrenzt · Analyse: exploratory · Route: responses · Modell: qwen · 2 Claims verworfen'
    )
    expect(systemMessages).toContain(
      'Evidenzlücke: keine belastbare Belegzeile · Analyse: exploratory · Modell: qwen'
    )
    // Recovery kinds without a label and the retry flag no longer appear as
    // codes (before: 'Copilot-Recovery: llm_timeout · … · retryable'), see
    // useCopilotGroundingNotices.
    expect(systemMessages).toContain(
      'Copilot-Recovery · Fallback auf konservative Antwort · erneuter Versuch möglich'
    )
  })

  it('keeps a stopped turn stopped when late SSE frames arrive', async () => {
    let handlers: StreamHandlers | undefined
    const abort = vi.fn()
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return abort
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('Bitte anhalten')
    handlers!.onContent?.('Bereits empfangener Satz.')

    copilot.cancel()
    const stopped = lastAssistant()
    expect(stopped?.content).toContain('Antwort angehalten')
    expect(stopped?.isStreaming).toBe(false)
    expect(useCopilotStore().isThinking).toBe(false)
    expect(abort).toHaveBeenCalledTimes(1)

    handlers!.onContent?.(' Dieser Text darf nicht mehr erscheinen.')
    handlers!.onDone?.('Diese Abschlussantwort darf nicht mehr erscheinen.')

    const afterLateFrames = lastAssistant()
    expect(afterLateFrames?.content).toBe(stopped?.content)
    expect(afterLateFrames?.isStreaming).toBe(false)
  })

  it('does not invent a clarification answer when the question expires', async () => {
    let handlers: StreamHandlers | undefined
    const abort = vi.fn()
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return abort
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('Bitte klären')
    handlers!.onClarifyV1?.({
      questionId: 'clarify-1',
      prompt: 'Welches Register?',
      blocking: true,
      options: [{ id: 'all', label: 'Alle', value: 'all' }],
    })
    expect(copilot.currentClarification.value?.questionId).toBe('clarify-1')

    copilot.expireClarification('clarify-1')

    expect(sseMocks.answerClarification).not.toHaveBeenCalled()
    expect(copilot.currentClarification.value).toBeNull()
    expect(useCopilotStore().messages.at(-1)?.content).toContain('nicht mit einer erfundenen Antwort')
    expect(abort).toHaveBeenCalledTimes(1)
  })
})
