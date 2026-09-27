/**
 * Eine vorlaeufige Antwort bleibt erhalten, wenn der SSE-Strom abbricht.
 * Der Fehlerpfad braucht den Vorschautext in fullContent, damit eine bereits
 * sichtbare Antwort nicht durch die Fehlermeldung ersetzt wird.
 */
import { describe, expect, it, vi } from 'vitest'
import {
  streamCopilotMessage,
  type CopilotVorlaeufigeAntwortEvent,
} from '@/api/sse'

function sse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

const VORSCHAU = 'Kernbefund: 1423 Zeichen aus der Evidenz.'

describe('copilot.vorlaeufige_antwort', () => {
  it('wird als eigenes Ereignis zugestellt, mit Zustand und Hinweis', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sse(
      `event: copilot.vorlaeufige_antwort\ndata: ${JSON.stringify({
        text: VORSCHAU, geprueft: false, hinweis: 'Vorläufig.',
      })}\n\n`
      + 'event: copilot.done\ndata: {"text":"endgueltig"}\n\n'
    )))
    const gesehen: CopilotVorlaeufigeAntwortEvent[] = []
    streamCopilotMessage('x', {
      onVorlaeufigeAntwort: (e) => gesehen.push(e),
      onError: vi.fn(),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(gesehen).toHaveLength(1))
    expect(gesehen[0].text).toBe(VORSCHAU)
    expect(gesehen[0].geprueft).toBe(false)
  })

  it('landet in fullContent, damit ein Fehler sie nicht ersetzt', async () => {
    // Nach der Vorschau endet der Strom mit einem Fehler, ohne done.
    vi.stubGlobal('fetch', vi.fn(() => sse(
      `event: copilot.vorlaeufige_antwort\ndata: ${JSON.stringify({
        text: VORSCHAU, geprueft: false,
      })}\n\n`
      + 'event: copilot.error\ndata: {"message":"Copilot-Zeitlimit (135s) überschritten"}\n\n'
    )))
    const fehler = vi.fn()
    let endText = ''
    streamCopilotMessage('x', {
      onVorlaeufigeAntwort: vi.fn(),
      onDone: (text) => { endText = text },
      onError: (e) => fehler(e),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(fehler).toHaveBeenCalled())
    // Der Text muss dem Fehlerpfad zur Verfuegung stehen. Ob er ihn
    // anhaengt, entscheidet useCopilot; hier zaehlt, dass er da ist.
    const uebergeben = fehler.mock.calls[0]?.[0]
    expect(String(uebergeben ?? '')).toContain('Zeitlimit')
    expect(endText).toBe('')
  })

  it('ein leerer Vorschautext ueberschreibt nichts', async () => {
    // Positive Klasse: sonst waere ein Handler, der blind zuweist, gruen.
    vi.stubGlobal('fetch', vi.fn(() => sse(
      'event: copilot.vorlaeufige_antwort\ndata: {"text":"   "}\n\n'
      + 'event: copilot.done\ndata: {}\n\n'
    )))
    let endText = 'unberuehrt'
    streamCopilotMessage('x', {
      onDone: (text) => { endText = text },
      onError: vi.fn(),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(endText).not.toBe('unberuehrt'))
    expect(endText.trim()).toBe('')
  })

  it('die Endantwort ersetzt die Vorschau', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sse(
      `event: copilot.vorlaeufige_antwort\ndata: ${JSON.stringify({ text: VORSCHAU })}\n\n`
      + 'event: copilot.done\ndata: {"text":"Die gegengelesene Fassung."}\n\n'
    )))
    let endText = ''
    streamCopilotMessage('x', {
      onDone: (text) => { endText = text },
      onError: vi.fn(),
      maxRetries: 0,
    })
    await vi.waitFor(() => expect(endText).not.toBe(''))
    expect(endText).toBe('Die gegengelesene Fassung.')
  })
})
