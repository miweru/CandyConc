/**
 * Die Frames, aus denen die Zeitleiste entsteht.
 *
 * Zwei Backend-Ereignisse erreichten den Verteiler und wurden
 * stillschweigend verworfen: `start` und `end` je Werkzeugaufruf. Und die
 * beiden Felder, die Modellzeit von Indexzeit trennen (`llm_seconds`,
 * `llm_seconds_je_stufe`), lagen im `copilot.done`-Frame und starben in der
 * Extraktion.
 *
 * Geprueft wird durch die oeffentliche Naht, nicht an einem Test-Export:
 * ein Feld, das nur ein Test sieht, ist kein Feld.
 */
import { describe, expect, it, vi } from 'vitest'
import { streamCopilotMessage, type CopilotDoneMeta, type CopilotStatusEvent, type CopilotToolPhaseEvent } from '@/api/sse'

function sse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

describe('Werkzeugklammer erreicht das Frontend', () => {
  it('start und end werden zugestellt, mit Zeit und Dauer', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sse(
      'event: start\ndata: {"tool":"query_count","t_rel":1.5}\n\n'
      + 'event: end\ndata: {"tool":"query_count","t_rel":3.25,"duration_ms":1740.2}\n\n'
      + 'event: copilot.done\ndata: {"text":"fertig"}\n\n'
    )))
    const phasen: CopilotToolPhaseEvent[] = []
    streamCopilotMessage('x', {
      onToolPhase: (p) => phasen.push(p),
      onError: vi.fn(),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(phasen).toHaveLength(2))
    expect(phasen[0]).toEqual({
      phase: 'start', tool: 'query_count', t_rel: 1.5, duration_ms: undefined,
    })
    expect(phasen[1]).toEqual({
      phase: 'end', tool: 'query_count', t_rel: 3.25, duration_ms: 1740.2,
    })
  })

  it('ein Frame ohne tool erzeugt nichts', async () => {
    // Positive Klasse: sonst waere ein Handler, der auf jedes start feuert, gruen.
    vi.stubGlobal('fetch', vi.fn(() => sse(
      'event: start\ndata: {}\n\n'
      + 'event: copilot.done\ndata: {"text":"fertig"}\n\n'
    )))
    const onToolPhase = vi.fn()
    const onDone = vi.fn()
    streamCopilotMessage('x', { onToolPhase, onDone, onError: vi.fn(), maxRetries: 0 })
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(onToolPhase).not.toHaveBeenCalled()
  })
})

describe('Stufenmarke und Modellzeit', () => {
  it('copilot.status traegt t_rel', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sse(
      'event: copilot.status\ndata: {"stage":"Verifikation","t_rel":468.166}\n\n'
      + 'event: copilot.done\ndata: {"text":"fertig"}\n\n'
    )))
    const stufen: CopilotStatusEvent[] = []
    streamCopilotMessage('x', {
      onStatus: (s) => stufen.push(s),
      onError: vi.fn(),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(stufen).toHaveLength(1))
    expect(stufen[0]?.stage).toBe('Verifikation')
    expect(stufen[0]?.t_rel).toBe(468.166)
  })

  it('copilot.done liefert Modellzeit und ihre Aufteilung', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sse(
      'event: copilot.done\n'
      + 'data: {"text":"fertig","elapsed_s":2957.853,"llm_calls_used":18,'
      + '"llm_seconds":2935.687,'
      + '"llm_seconds_je_stufe":{"Vorlauf":189.544,"Werkzeuge":216.31,"Verifikation":2529.833}}\n\n'
    )))
    let meta: CopilotDoneMeta | undefined
    streamCopilotMessage('x', {
      onDone: (_t, m) => { meta = m },
      onError: vi.fn(),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(meta).toBeDefined())
    expect(meta?.llm_seconds).toBe(2935.687)
    expect(meta?.llm_seconds_je_stufe).toEqual({
      Vorlauf: 189.544, Werkzeuge: 216.31, Verifikation: 2529.833,
    })
  })

  it('ohne die Felder wird nichts erfunden', async () => {
    // Eine erfundene Null waere schlimmer als eine ehrliche Luecke.
    vi.stubGlobal('fetch', vi.fn(() => sse(
      'event: copilot.done\ndata: {"text":"fertig","elapsed_s":12,"llm_calls_used":2}\n\n'
    )))
    let meta: CopilotDoneMeta | undefined
    streamCopilotMessage('x', {
      onDone: (_t, m) => { meta = m },
      onError: vi.fn(),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(meta).toBeDefined())
    expect(meta?.elapsed_s).toBe(12)
    expect(meta?.llm_seconds).toBeUndefined()
    expect(meta?.llm_seconds_je_stufe).toBeUndefined()
  })
})
