/**
 * K1-Frontend: Fortschritt sichtbar machen + Kontrollierbarkeit.
 *
 * - `copilot.delta` rendert progressiv in die laufende Assistant-Message,
 *   `copilot.done` ersetzt/finalisiert.
 * - `copilot.status` erscheint als dezente Stufenanzeige an der laufenden
 *   Message und verschwindet bei done/error/stop.
 * - Die done-Bilanz {llm_calls_used, transport_retries_used, elapsed_s}
 *   landet als usage-Fusszeile auf der Nachricht.
 * - Server-Cancel (`copilot.cancelled`) macht die UI SOFORT wieder
 *   eingabebereit (kein Ausknocken), spaete Frames bleiben inert.
 * - Timeout-Salvage-Antworten (formatiertes Markdown, partial:true) rendern
 *   wie normale Antworten inkl. Ehrlichkeits-Satz.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { copilotGroundingContract } from '@/__tests__/fixtures/copilotGroundingContract'
import type { CopilotDoneMeta, CopilotStatusEvent } from '@/api/sse'

interface StreamHandlers {
  onContent?: (content: string) => void
  onStatus?: (status: CopilotStatusEvent) => void
  onCancelled?: () => void
  onDone?: (content: string, meta?: CopilotDoneMeta) => void
  onError?: (error: Error) => void
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

import { useCopilot } from '@/composables/useCopilot'

function lastAssistant() {
  const messages = useCopilotStore().messages
  for (let i = messages.length - 1; i >= 0; i--) {
    if (messages[i]!.role === 'assistant') return messages[i]!
  }
  return undefined
}

describe('useCopilot Stream-Fortschritt (copilot.delta/status/done-Bilanz)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = copilotGroundingContract()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
  })

  it('rendert Deltas progressiv, zeigt Status-Stufen und finalisiert mit Bilanz', async () => {
    let handlers: StreamHandlers | undefined
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return vi.fn()
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('wie oft kommt und vor')

    // Stufe 1: Werkzeuge laufen.
    handlers!.onStatus?.({ stage: 'Werkzeuge' })
    let assistant = lastAssistant()!
    expect(assistant.status).toEqual({ stage: 'Werkzeuge' })
    expect(assistant.isStreaming).toBe(true)

    // Delta 1 erscheint sofort (progressives Rendering), Status bleibt.
    handlers!.onContent?.('Im Korpus ')
    assistant = lastAssistant()!
    expect(assistant.content).toBe('Im Korpus ')
    expect(assistant.status).toEqual({ stage: 'Werkzeuge' })

    // Delta 2 haengt an (append, kein Ersetzen).
    handlers!.onContent?.('593 Treffer.')
    assistant = lastAssistant()!
    expect(assistant.content).toBe('Im Korpus 593 Treffer.')

    // Stufenwechsel inkl. detail.
    handlers!.onStatus?.({ stage: 'Antwort', detail: 'finale Synthese' })
    assistant = lastAssistant()!
    expect(assistant.status).toEqual({ stage: 'Antwort', detail: 'finale Synthese' })

    // done ersetzt/finalisiert: Status weg, Bilanz als usage-Fusszeile da.
    handlers!.onDone?.('Im Korpus 593 Treffer.', {
      llm_calls_used: 1,
      transport_retries_used: 0,
      elapsed_s: 7.355,
    })
    assistant = lastAssistant()!
    expect(assistant.content).toBe('Im Korpus 593 Treffer.')
    expect(assistant.isStreaming).toBe(false)
    expect(assistant.status).toBeUndefined()
    expect(assistant.usage).toEqual({
      llmCalls: 1,
      transportRetries: 0,
      elapsedS: 7.355,
    })
    expect(useCopilotStore().isThinking).toBe(false)
  })

  it('done ohne Bilanz-Felder erzeugt keine usage-Fusszeile', async () => {
    let handlers: StreamHandlers | undefined
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return vi.fn()
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('frage')
    handlers!.onDone?.('Antworttext')

    const assistant = lastAssistant()!
    expect(assistant.content).toBe('Antworttext')
    expect(assistant.usage).toBeUndefined()
  })

  it('rendert eine Timeout-Salvage-Antwort wie eine normale Antwort inkl. Ehrlichkeits-Satz', async () => {
    let handlers: StreamHandlers | undefined
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return vi.fn()
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('lange analyse')

    const salvageMarkdown =
      '## Beobachtete Fakten\n\n- 593 Treffer für "und"\n\n' +
      'Diese Angaben sind nicht verifiziert. Der Turn wurde durch das Zeitlimit beendet.'
    handlers!.onDone?.(salvageMarkdown, {
      partial: true,
      timeout: 'Copilot-Zeitlimit (150s) überschritten',
      llm_calls_used: 2,
      elapsed_s: 150.2,
    })

    const assistant = lastAssistant()!
    // Kein Fehlerzustand, kein Roh-JSON: die formatierte Antwort steht als Text.
    expect(assistant.error).toBeFalsy()
    expect(assistant.isStreaming).toBe(false)
    expect(assistant.content).toBe(salvageMarkdown)
    expect(assistant.content).toContain('nicht verifiziert')
    expect(assistant.usage).toEqual({
      llmCalls: 2,
      elapsedS: 150.2,
      partial: true,
      timeout: 'Copilot-Zeitlimit (150s) überschritten',
    })
    // Eingabe sofort wieder frei.
    expect(useCopilotStore().isThinking).toBe(false)
  })

  it('Fehler entfernt die Stufenanzeige von der Nachricht', async () => {
    let handlers: StreamHandlers | undefined
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return vi.fn()
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('frage')
    handlers!.onStatus?.({ stage: 'Verifikation' })
    expect(lastAssistant()!.status).toEqual({ stage: 'Verifikation' })

    handlers!.onError?.(new Error('TimeoutError'))
    const assistant = lastAssistant()!
    expect(assistant.status).toBeUndefined()
    expect(assistant.error).toBe(true)
    expect(useCopilotStore().isThinking).toBe(false)
  })
})

describe('useCopilot Kontrollierbarkeit (Stop + Server-Cancel)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = copilotGroundingContract()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
  })

  it('Stop ruft den Stream-Cancel (traegt den Server-Cancel) und macht die UI sofort eingabebereit', async () => {
    let handlers: StreamHandlers | undefined
    const abort = vi.fn()
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return abort
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('bitte stoppen')
    handlers!.onStatus?.({ stage: 'Werkzeuge' })
    handlers!.onContent?.('Teilsatz.')

    copilot.cancel()

    // Der von streamCopilotMessage zurueckgegebene Cancel (er sendet den
    // Server-Cancel POST /api/v1/copilot/cancel) wurde genau einmal gerufen.
    expect(abort).toHaveBeenCalledTimes(1)
    // UI sofort wieder eingabebereit, Status-Anzeige weg.
    expect(useCopilotStore().isThinking).toBe(false)
    const stopped = lastAssistant()!
    expect(stopped.isStreaming).toBe(false)
    expect(stopped.status).toBeUndefined()
    expect(stopped.content).toContain('Antwort angehalten')
  })

  it('Server-Cancel (copilot.cancelled) knockt die UI nicht aus: sofort eingabebereit, spaete Frames inert', async () => {
    let handlers: StreamHandlers | undefined
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return vi.fn()
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('wird serverseitig abgebrochen')
    handlers!.onContent?.('Angefangener Satz.')

    // Der SERVER beendet den Turn (Owner-Supersede/Backstop), ohne done-Frame.
    handlers!.onCancelled?.()

    const cancelled = lastAssistant()!
    expect(cancelled.isStreaming).toBe(false)
    expect(cancelled.content).toContain('Angefangener Satz.')
    expect(cancelled.content).toContain('serverseitig abgebrochen')
    expect(useCopilotStore().isThinking).toBe(false)

    // Ein direkt neuer Turn ist moeglich (System knockt sich nicht aus).
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        incoming.onDone?.('neue Antwort')
        return vi.fn()
      },
    )
    await copilot.sendMessage('neue Anfrage sofort danach')
    expect(lastAssistant()!.content).toBe('neue Antwort')

    // Spaete Frames des abgebrochenen Turns bleiben inert.
    handlers!.onContent?.(' Dieser Text darf nicht mehr erscheinen.')
    handlers!.onDone?.('Phantom-Abschluss')
    expect(lastAssistant()!.content).toBe('neue Antwort')
  })

  it('Server-Cancel ohne empfangenen Inhalt finalisiert mit neutralem Hinweis', async () => {
    let handlers: StreamHandlers | undefined
    sseMocks.streamCopilotMessage.mockImplementationOnce(
      (_message: string, incoming: StreamHandlers) => {
        handlers = incoming
        return vi.fn()
      },
    )

    const copilot = useCopilot()
    await copilot.sendMessage('frage')
    handlers!.onCancelled?.()

    const cancelled = lastAssistant()!
    expect(cancelled.content).toBe('Antwort serverseitig abgebrochen.')
    expect(cancelled.isStreaming).toBe(false)
    expect(cancelled.error).toBeFalsy()
    expect(useCopilotStore().isThinking).toBe(false)
  })
})
