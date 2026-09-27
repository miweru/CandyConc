import { describe, expect, it, vi } from 'vitest'
import { streamCopilotMessage } from '@/api/sse'

function sseResponse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

function jsonErrorResponse(status: number, body: Record<string, unknown>) {
  return Promise.resolve(new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

describe('Copilot SSE error surfacing', () => {
  it('reads the copilot.error payload `error` key (id 2), not `message`', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(
      'event: copilot.error\n' +
      'data: {"sessionId":"s1","error":"TimeoutError"}\n\n'
    )))

    const onError = vi.fn<(error: Error) => void>()
    const onDone = vi.fn<(content: string) => void>()
    const cancel = streamCopilotMessage('q', { onError, onDone, maxRetries: 0 })

    await vi.waitFor(() => expect(onError).toHaveBeenCalled())
    expect(onError.mock.calls[0]![0]!.message).toBe('TimeoutError')
    expect(onDone).not.toHaveBeenCalled()
    cancel()
  })

  it('does not re-post an ambiguous failed request unless a caller explicitly opts in', async () => {
    const fetchMock = vi.fn(() => jsonErrorResponse(503, { detail: 'temporarily unavailable' }))
    vi.stubGlobal('fetch', fetchMock)

    const onError = vi.fn<(error: Error) => void>()
    const cancel = streamCopilotMessage('q', { onError })

    await vi.waitFor(() => expect(onError).toHaveBeenCalled())
    expect(fetchMock).toHaveBeenCalledTimes(1)
    cancel()
  })

  it('falls back to `message` when no `error` key is present', async () => {
    vi.stubGlobal('fetch', vi.fn(() => sseResponse(
      'event: copilot.error\n' +
      'data: {"message":"Policy block"}\n\n'
    )))

    const onError = vi.fn<(error: Error) => void>()
    const cancel = streamCopilotMessage('q', { onError, maxRetries: 0 })

    await vi.waitFor(() => expect(onError).toHaveBeenCalled())
    expect(onError.mock.calls[0]![0]!.message).toBe('Policy block')
    cancel()
  })

  it('surfaces the backend detail on a 422 instead of a bare HTTP status (id 20)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonErrorResponse(422, {
      detail: "Unsupported payload: erwartet wird 'application/json'",
    })))

    const onError = vi.fn<(error: Error) => void>()
    const cancel = streamCopilotMessage('q', { onError, maxRetries: 0 })

    await vi.waitFor(() => expect(onError).toHaveBeenCalled())
    const msg = onError.mock.calls[0]![0]!.message
    expect(msg).toContain("Unsupported payload: erwartet wird 'application/json'")
    expect(msg).toContain('422')
    cancel()
  })

  it('surfaces a friendly German rate-limit message on 429 (id 21)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonErrorResponse(429, {
      detail: 'Rate limit exceeded',
    })))

    const onError = vi.fn<(error: Error) => void>()
    // maxRetries:0 so we observe the surfaced error directly rather than retries.
    const cancel = streamCopilotMessage('q', { onError, maxRetries: 0 })

    await vi.waitFor(() => expect(onError).toHaveBeenCalled())
    const msg = onError.mock.calls[0]![0]!.message
    expect(msg).toContain('Zu viele Anfragen')
    // Still carries the status so it is classified as retryable downstream.
    expect(msg).toContain('429')
    cancel()
  })

  it('surfaces model-not-loaded details from the backend gate', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonErrorResponse(424, {
      detail: {
        code: 'model_not_loaded',
        message: 'LM Studio meldet kein geladenes Modell. No model load was attempted.',
        model: 'qwen-test',
      },
    })))

    const onError = vi.fn<(error: Error) => void>()
    const cancel = streamCopilotMessage('q', { onError, maxRetries: 0 })

    await vi.waitFor(() => expect(onError).toHaveBeenCalled())
    const msg = onError.mock.calls[0]![0]!.message
    expect(msg).toContain('Copilot-Modell nicht geladen')
    expect(msg).toContain('No model load was attempted')
    expect(msg).toContain('424')
    cancel()
  })
})
