/**
 * Rezept-Transparenz + beratende Annotationen im SSE-Vertrag:
 *
 * - `copilot.status` traegt zusaetzlich recipe_id (string|null) neben stage.
 * - `copilot.done` traegt zusaetzlich recipe_id in der Aufwandsbilanz.
 * - `copilot.grounding` traegt annotations: [{rule, note}] (beratend, nie
 *   blockierend).
 * - Rueckwaertskompatibilitaet: Frames OHNE diese Felder verhalten sich
 *   byte-identisch zum Alt-Backend (kein recipe_id-Schluessel, einargumentiger
 *   done-Callback ohne Bilanz).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  streamCopilotMessage,
  type CopilotDoneMeta,
  type CopilotGroundingEvent,
  type CopilotStatusEvent,
} from '@/api/sse'

function sseResponse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

describe('copilot.status/done: recipe_id im Stream-Vertrag', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reicht recipe_id aus copilot.status und copilot.done durch', async () => {
    const frames =
      'event: copilot.session\n' +
      'data: {"sessionId":"recipe-session-1","status":"started"}\n\n' +
      'event: copilot.status\n' +
      'data: {"event":"copilot.status","stage":"Werkzeuge","recipe_id":"kontrast"}\n\n' +
      'event: copilot.done\n' +
      'data: {"sessionId":"recipe-session-1","status":"completed","text":"Fertig.","recipe_id":"kontrast","llm_calls_used":2,"elapsed_s":9.1}\n\n'
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(frames)))

    const statusEvents: CopilotStatusEvent[] = []
    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()
    const cancel = streamCopilotMessage('kontrastiere A und B', {
      onStatus: (status) => statusEvents.push(status),
      onDone,
    })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(statusEvents[0]?.stage).toBe('Werkzeuge')
    expect(statusEvents[0]?.recipe_id).toBe('kontrast')
    expect(onDone).toHaveBeenCalledWith('Fertig.', {
      recipe_id: 'kontrast',
      llm_calls_used: 2,
      elapsed_s: 9.1,
    })
    cancel()
  })

  it('recipe_id null (freie Analyse) bleibt von einem fehlenden Feld unterscheidbar', async () => {
    const frames =
      'event: copilot.status\n' +
      'data: {"event":"copilot.status","stage":"Antwort","recipe_id":null}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"Freie Antwort.","recipe_id":null,"llm_calls_used":1}\n\n'
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(frames)))

    const statusEvents: CopilotStatusEvent[] = []
    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()
    const cancel = streamCopilotMessage('freie frage', {
      onStatus: (status) => statusEvents.push(status),
      onDone,
    })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(statusEvents[0]?.recipe_id).toBeNull()
    const meta = onDone.mock.calls[0]?.[1]
    expect(meta).toBeDefined()
    expect(meta).toHaveProperty('recipe_id', null)
    cancel()
  })

  it('Alt-Backend ohne recipe_id: Verhalten unveraendert (Rueckwaertskompatibilitaet)', async () => {
    const frames =
      'event: copilot.status\n' +
      'data: {"event":"copilot.status","stage":"Werkzeuge"}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"Antwort.","llm_calls_used":1,"transport_retries_used":0,"elapsed_s":7.355}\n\n'
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(frames)))

    const statusEvents: CopilotStatusEvent[] = []
    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()
    const cancel = streamCopilotMessage('frage', {
      onStatus: (status) => statusEvents.push(status),
      onDone,
    })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    // Kein Phantom-Schluessel im Status und keiner in der Bilanz.
    expect(statusEvents[0]).not.toHaveProperty('recipe_id')
    expect(onDone).toHaveBeenCalledWith('Antwort.', {
      llm_calls_used: 1,
      transport_retries_used: 0,
      elapsed_s: 7.355,
    })
    cancel()
  })

  it('done ohne jegliche Bilanz-Felder bleibt einargumentig (gepinnte Callform)', async () => {
    const frames =
      'event: copilot.done\n' +
      'data: {"text":"Nur Text."}\n\n'
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(frames)))

    const onDone = vi.fn<(content: string, meta?: CopilotDoneMeta) => void>()
    const cancel = streamCopilotMessage('frage', { onDone })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledTimes(1))
    expect(onDone.mock.calls[0]).toHaveLength(1)
    expect(onDone).toHaveBeenCalledWith('Nur Text.')
    cancel()
  })
})

describe('copilot.grounding: beratende annotations im Stream-Vertrag', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('reicht annotations [{rule, note}] durch', async () => {
    const frames =
      'event: copilot.grounding\n' +
      'data: {"event":"copilot.grounding","grounding":{"verdict":"accepted","annotations":[{"rule":"per_million_normierung","note":"Frequenzen sind pro Million Token normiert."},{"rule":"docset_scope","note":"Werte gelten nur fuer das aktive Subkorpus."}]}}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"done"}\n\n'
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(frames)))

    const groundingEvents: CopilotGroundingEvent[] = []
    const cancel = streamCopilotMessage('frequenzfrage', {
      onGrounding: (event) => groundingEvents.push(event),
      onDone: vi.fn(),
    })

    await vi.waitFor(() => expect(groundingEvents).toHaveLength(1))
    expect(groundingEvents[0]?.verdict).toBe('accepted')
    expect(groundingEvents[0]?.annotations).toEqual([
      { rule: 'per_million_normierung', note: 'Frequenzen sind pro Million Token normiert.' },
      { rule: 'docset_scope', note: 'Werte gelten nur fuer das aktive Subkorpus.' },
    ])
    cancel()
  })

  it('Alt-Backend ohne annotations: Grounding-Event unveraendert', async () => {
    const frames =
      'event: copilot.grounding\n' +
      'data: {"event":"copilot.grounding","grounding":{"analysis_family":"exploratory","verdict":"conservative_only","rejected_claim_count":2}}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"done"}\n\n'
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(frames)))

    const groundingEvents: CopilotGroundingEvent[] = []
    const cancel = streamCopilotMessage('frage', {
      onGrounding: (event) => groundingEvents.push(event),
      onDone: vi.fn(),
    })

    await vi.waitFor(() => expect(groundingEvents).toHaveLength(1))
    expect(groundingEvents[0]).toEqual({
      analysis_family: 'exploratory',
      verdict: 'conservative_only',
      rejected_claim_count: 2,
    })
    expect(groundingEvents[0]).not.toHaveProperty('annotations')
    cancel()
  })
})
