/**
 * K1-Vertrag: `copilot.status` (sichtbarer Turn-Fortschritt), `copilot.delta`
 * (progressives Rendering), `copilot.done`-Aufwandsbilanz
 * ({llm_calls_used, transport_retries_used, elapsed_s}) und die
 * Stop-Knopf-Wahrheit (lokaler Abbruch loest den Server-Cancel
 * POST /api/v1/copilot/cancel aus, `copilot.cancelled` macht den Stream
 * terminal, ohne die UI auszuknocken).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  continueCopilotExecution,
  getCurrentSessionId,
  streamCopilotMessage,
  type CopilotDoneMeta,
  type CopilotStatusEvent,
} from '@/api/sse'

function sseResponse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

const PROGRESS_FRAMES =
  'event: copilot.session\n' +
  'data: {"sessionId":"status-session-1","status":"started"}\n\n' +
  'event: copilot.status\n' +
  'data: {"event":"copilot.status","stage":"Werkzeuge"}\n\n' +
  'event: copilot.delta\n' +
  'data: {"delta":{"content":"Im Korpus "}}\n\n' +
  'event: copilot.delta\n' +
  'data: {"delta":{"content":"593 Treffer."}}\n\n' +
  'event: copilot.status\n' +
  'data: {"event":"copilot.status","stage":"Antwort","detail":"finale Synthese"}\n\n' +
  'event: copilot.done\n' +
  'data: {"sessionId":"status-session-1","status":"completed","text":"Im Korpus 593 Treffer.","llm_calls_used":1,"transport_retries_used":0,"elapsed_s":7.355}\n\n'

const CANCELLED_FRAMES =
  'event: copilot.session\n' +
  'data: {"sessionId":"cancel-session-1","status":"started"}\n\n' +
  'event: copilot.delta\n' +
  'data: {"delta":{"content":"Teil"}}\n\n' +
  'event: copilot.cancelled\n' +
  'data: {"sessionId":"cancel-session-1","status":"cancelled"}\n\n'

describe('copilot.status / copilot.delta / copilot.done-Bilanz', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('liefert Status-Stufen und Deltas progressiv und die Aufwandsbilanz am Ende', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(PROGRESS_FRAMES)))

    const statusEvents: CopilotStatusEvent[] = []
    const contentChunks: string[] = []
    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()

    const cancel = streamCopilotMessage('wie oft kommt und vor', {
      onStatus: (status) => statusEvents.push(status),
      onContent: (content) => contentChunks.push(content),
      onDone,
    })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))

    // Progressives Rendering: jedes Delta einzeln, in Reihenfolge.
    expect(contentChunks).toEqual(['Im Korpus ', '593 Treffer.'])
    // Stufenanzeige in Emissionsreihenfolge inkl. optionalem detail.
    expect(statusEvents.map((s) => s.stage)).toEqual(['Werkzeuge', 'Antwort'])
    expect(statusEvents[1]?.detail).toBe('finale Synthese')
    // done ersetzt/finalisiert mit Text UND Aufwandsbilanz.
    expect(onDone).toHaveBeenCalledWith('Im Korpus 593 Treffer.', {
      llm_calls_used: 1,
      transport_retries_used: 0,
      elapsed_s: 7.355,
    })
    cancel()
  })

  it('markiert eine Timeout-Salvage-Antwort als partial und behaelt den Text', async () => {
    const frames =
      'event: copilot.session\n' +
      'data: {"sessionId":"salvage-session-1","status":"started"}\n\n' +
      'event: copilot.done\n' +
      'data: {"sessionId":"salvage-session-1","status":"timeout","partial":true,"text":"## Beobachtete Fakten\\n\\nNicht verifiziert.","timeout":"Copilot-Zeitlimit (150s) überschritten","llm_calls_used":2,"elapsed_s":150.2}\n\n'
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(frames)))

    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()
    const cancel = streamCopilotMessage('lange analyse', { onDone })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(onDone).toHaveBeenCalledWith(
      '## Beobachtete Fakten\n\nNicht verifiziert.',
      expect.objectContaining({
        partial: true,
        timeout: 'Copilot-Zeitlimit (150s) überschritten',
        llm_calls_used: 2,
        elapsed_s: 150.2,
      }),
    )
    cancel()
  })

  it('copilot.cancelled feuert onCancelled genau einmal und unterdrueckt done', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(CANCELLED_FRAMES)))

    const onCancelled = vi.fn()
    const onDone = vi.fn()
    const onError = vi.fn()
    const cancel = streamCopilotMessage('frage', { onCancelled, onDone, onError })

    await vi.waitFor(() => expect(onCancelled).toHaveBeenCalledTimes(1))
    // Der Stream endet danach (EOF), es darf KEIN Phantom-done nachkommen.
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(onDone).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
    cancel()
  })

  it('der Continue-Strom verarbeitet status/done-Bilanz identisch (geteilter Dispatcher)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(PROGRESS_FRAMES)))

    const statusEvents: CopilotStatusEvent[] = []
    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()
    const cancel = continueCopilotExecution(
      { onStatus: (status) => statusEvents.push(status), onDone },
      'status-session-1',
    )

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(statusEvents.map((s) => s.stage)).toEqual(['Werkzeuge', 'Antwort'])
    expect(onDone.mock.calls[0]?.[1]).toEqual(expect.objectContaining({
      llm_calls_used: 1,
      elapsed_s: 7.355,
    }))
    cancel()
  })
})

describe('Stop-Knopf-Wahrheit: lokaler Abbruch loest den Server-Cancel aus', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('cancel() sendet POST /api/v1/copilot/cancel mit sessionId und turnId', async () => {
    const encoder = new TextEncoder()
    const fetchMock = vi.fn((url: RequestInfo | URL) => {
      if (String(url) === '/api/v1/chat/stream') {
        // Haengender Stream: Session-Frame kommt, dann bleibt die Verbindung offen.
        const body = new ReadableStream<Uint8Array>({
          start(controller) {
            controller.enqueue(encoder.encode(
              'event: copilot.session\n' +
              'data: {"sessionId":"stop-session-7","status":"started"}\n\n'
            ))
          },
        })
        return Promise.resolve(new Response(body, {
          status: 200,
          headers: { 'Content-Type': 'text/event-stream' },
        }))
      }
      return Promise.resolve(new Response('{"status":"cancellation_requested"}', { status: 200 }))
    })
    vi.stubGlobal('fetch', fetchMock)

    const cancel = streamCopilotMessage('bitte stoppen', {})
    // Erst den Session-Frame verarbeiten lassen, damit die sessionId bekannt ist.
    await vi.waitFor(() => expect(getCurrentSessionId()).toBe('stop-session-7'))

    cancel()

    await vi.waitFor(() => {
      expect(
        fetchMock.mock.calls.some(([url]) => String(url) === '/api/v1/copilot/cancel'),
      ).toBe(true)
    })
    const cancelCall = fetchMock.mock.calls.find(
      ([url]) => String(url) === '/api/v1/copilot/cancel',
    )!
    const init = cancelCall[1] as RequestInit
    expect(init.method).toBe('POST')
    const body = JSON.parse(String(init.body))
    expect(body.sessionId).toBe('stop-session-7')
    expect(typeof body.turnId).toBe('string')
    expect(body.turnId.length).toBeGreaterThan(0)
  })

  it('nach cancel() bleibt der Turn terminal: kein done/error mehr', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(PROGRESS_FRAMES)))

    const onDone = vi.fn()
    const onError = vi.fn()
    const cancel = streamCopilotMessage('frage', { onDone, onError })
    // Sofort stoppen, bevor der (synchron aufgeloeste) Stream verarbeitet ist.
    cancel()

    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(onDone).not.toHaveBeenCalled()
    expect(onError).not.toHaveBeenCalled()
  })
})
