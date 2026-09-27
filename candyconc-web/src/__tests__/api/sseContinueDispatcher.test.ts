/**
 * Der Continue-Strom teilt sich den Event-Dispatcher mit dem initialen
 * Chat-Strom. Vor dem Dedup verlor er `copilot.message` und `copilot.session`
 * (Handler-Drift zwischen zwei Kopien desselben Switch).
 */
import { afterEach, describe, expect, it, vi } from 'vitest'
import { continueCopilotExecution, getCurrentSessionId, streamCopilotMessage } from '@/api/sse'

function sseResponse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

const FIXTURE_FRAMES =
  'event: copilot.session\n' +
  'data: {"sessionId":"dispatcher-session-1","status":"started"}\n\n' +
  'event: copilot.delta\n' +
  'data: {"delta":{"content":"partial "}}\n\n' +
  'event: copilot.message\n' +
  'data: {"text":"final message text","messageId":"m1"}\n\n' +
  'event: copilot.research\n' +
  'data: {"event":"copilot.research","researchId":"r1","phase":"started","query":"Hase","ts":1}\n\n' +
  'event: copilot.action_blocked\n' +
  'data: {"event":"copilot.action_blocked","id":"b1","request":{"requestId":"b1","type":"export/data","payload":{}},"meta":{"summary":"Export","status":"blocked","reason":"not visible","ts":1}}\n\n' +
  'event: copilot.done\n' +
  'data: {"status":"completed"}\n\n'

describe('continueCopilotExecution shared dispatcher', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('processes copilot.message and copilot.session identically to the initial stream', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(FIXTURE_FRAMES)))

    const onDone = vi.fn<(content: string) => void>()
    const onResearch = vi.fn()
    const onActionBlocked = vi.fn()
    const cancel = continueCopilotExecution(
      { onDone, onResearch, onActionBlocked },
      'session-before',
    )

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    // copilot.message ersetzt den akkumulierten Delta-Inhalt (copilot.done
    // liefert hier kein text-Feld — der Wert MUSS aus copilot.message kommen).
    expect(onDone).toHaveBeenCalledWith('final message text')
    // copilot.session aktualisiert die Session-Verfolgung auch im Continue-Strom.
    expect(getCurrentSessionId()).toBe('dispatcher-session-1')
    // Research-/Blocked-Events laufen durch denselben Dispatcher.
    expect(onResearch).toHaveBeenCalledWith(expect.objectContaining({
      researchId: 'r1',
      phase: 'started',
      query: 'Hase',
    }))
    expect(onActionBlocked).toHaveBeenCalledWith(expect.objectContaining({
      meta: expect.objectContaining({ reason: 'not visible' }),
    }))
    cancel()
  })

  it('the initial stream dispatches the identical fixture the same way', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(FIXTURE_FRAMES)))

    const onDone = vi.fn<(content: string) => void>()
    const onResearch = vi.fn()
    const onActionBlocked = vi.fn()
    const cancel = streamCopilotMessage('q', {
      onDone,
      onResearch,
      onActionBlocked,
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    expect(onDone).toHaveBeenCalledWith('final message text')
    expect(getCurrentSessionId()).toBe('dispatcher-session-1')
    expect(onResearch).toHaveBeenCalledTimes(1)
    expect(onActionBlocked).toHaveBeenCalledTimes(1)
    cancel()
  })
})
