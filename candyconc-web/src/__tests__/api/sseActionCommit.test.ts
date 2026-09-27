import { describe, expect, it, vi, type Mock } from 'vitest'
import { continueCopilotExecution, streamCopilotMessage } from '@/api/sse'
import type { ActionCommitPayload, ActionRequestV1, ActionResultPayload } from '@/types/copilot-protocol'

function mockSseResponse(payload: string) {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

function mockSseChunkedResponse(chunks: string[]) {
  const encoder = new TextEncoder()
  return Promise.resolve(new Response(new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  }), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

function fetchMock() {
  return globalThis.fetch as Mock
}

describe('Copilot SSE action commit events', () => {
  it('parses copilot.action_commit events and calls the commit handler', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.action_commit\n' +
      'data: {"requestId":"req-commit-1"}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"done"}\n\n'
    )))

    const onActionCommit = vi.fn<(commit: ActionCommitPayload) => void>()
    const cancel = streamCopilotMessage('commit please', {
      onActionCommit,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onActionCommit).toHaveBeenCalledWith({
      requestId: 'req-commit-1',
    }))
    cancel()
  })

  it('parses enveloped copilot.action_commit payloads', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.action_commit\n' +
      'data: {"event":"copilot.action_commit","id":"evt-1","ts":1,"payload":{"requestId":"req-envelope","runId":"run-envelope"}}\n\n' +
      'event: copilot.done\n' +
      'data: {"payload":{"text":"done"}}\n\n'
    )))

    const onActionCommit = vi.fn<(commit: ActionCommitPayload) => void>()
    const cancel = streamCopilotMessage('commit envelope', {
      onActionCommit,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onActionCommit).toHaveBeenCalledWith({
      requestId: 'req-envelope',
      runId: 'run-envelope',
    }))
    cancel()
  })

  it('does not unwrap direct ActionRequestV1 payload fields as event envelopes', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.action_request\n' +
      'data: {"requestId":"req-direct","type":"query/execute","payload":{"term":"Zeit"}}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"done"}\n\n'
    )))

    const onActionRequest = vi.fn<(request: ActionRequestV1) => void>()
    const cancel = streamCopilotMessage('direct request', {
      onActionRequest,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onActionRequest).toHaveBeenCalledWith(
      {
        requestId: 'req-direct',
        type: 'query/execute',
        payload: { term: 'Zeit' },
      },
      undefined
    ))
    cancel()
  })

  it('does not unwrap direct action_result result data as an event envelope', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.action_result\n' +
      'data: {"requestId":"req-result-direct","ok":true,"runId":"run-result-direct","result":{"rows":[1,2]},"resultSummary":"direct result"}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"done"}\n\n'
    )))

    const onActionResult = vi.fn<(result: ActionResultPayload) => void>()
    const cancel = streamCopilotMessage('direct action result', {
      onActionResult,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onActionResult).toHaveBeenCalledWith({
      requestId: 'req-result-direct',
      ok: true,
      runId: 'run-result-direct',
      result: { rows: [1, 2] },
      resultSummary: 'direct result',
    }))
    cancel()
  })

  it('unwraps enveloped action_result payloads', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.action_result\n' +
      'data: {"event":"copilot.action_result","id":"evt-result","ts":1,"payload":{"result":{"requestId":"req-result-envelope","ok":true,"runId":"run-result-envelope"}}}\n\n' +
      'event: copilot.done\n' +
      'data: {"payload":{"text":"done"}}\n\n'
    )))

    const onActionResult = vi.fn<(result: ActionResultPayload) => void>()
    const cancel = streamCopilotMessage('enveloped action result', {
      onActionResult,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onActionResult).toHaveBeenCalledWith({
      requestId: 'req-result-envelope',
      ok: true,
      runId: 'run-result-envelope',
    }))
    cancel()
  })

  it('keeps copilot.action_commit event type across chunk boundaries', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseChunkedResponse([
      'event: copilot.action_commit\n',
      'data: {"requestId":"req-chunked-commit"}\n\n',
      'event: copilot.done\n',
      'data: {"text":"done"}\n\n',
    ])))

    const onActionCommit = vi.fn<(commit: ActionCommitPayload) => void>()
    const cancel = streamCopilotMessage('commit in chunks', {
      onActionCommit,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onActionCommit).toHaveBeenCalledWith({
      requestId: 'req-chunked-commit',
    }))
    expect(fetchMock()).toHaveBeenCalledTimes(1)
    cancel()
  })

  it('continueCopilotExecution fires onDone exactly once for terminal done events', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.delta\n' +
      'data: {"content":"partial "}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"final text"}\n\n'
    )))

    const onDone = vi.fn<(message: string) => void>()
    const cancel = continueCopilotExecution({
      onDone,
      onError: vi.fn(),
    }, 'session-once-guard')

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith('final text'))
    // Stream end after the terminal event must not fire onDone a second time.
    expect(onDone).toHaveBeenCalledTimes(1)
    cancel()
  })

  it('continueCopilotExecution fires onDone once at natural stream end without a done event', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.delta\n' +
      'data: {"content":"only content"}\n\n'
    )))

    const onDone = vi.fn<(message: string) => void>()
    const cancel = continueCopilotExecution({
      onDone,
      onError: vi.fn(),
    }, 'session-natural-end')

    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith('only content'))
    expect(onDone).toHaveBeenCalledTimes(1)
    cancel()
  })

  it('streamCopilotMessage reads nested delta content and done text', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.delta\n' +
      'data: {"delta":{"content":"streamed "}}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"final answer"}\n\n'
    )))

    const onContent = vi.fn<(content: string) => void>()
    const onDone = vi.fn<(message: string) => void>()
    const cancel = streamCopilotMessage('nested delta', {
      onContent,
      onDone,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onContent).toHaveBeenCalledWith('streamed '))
    await vi.waitFor(() => expect(onDone).toHaveBeenCalledWith('final answer'))
    expect(onDone).toHaveBeenCalledTimes(1)
    cancel()
  })

  it('parses copilot grounding, evidence-gap and recovery events', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse(
      'event: copilot.grounding\n' +
      'data: {"event":"copilot.grounding","grounding":{"analysis_family":"exploratory","verdict":"conservative_only","rejected_claim_count":2,"route":"responses","model":"qwen"}}\n\n' +
      'event: copilot.evidence_gap\n' +
      'data: {"event":"copilot.evidence_gap","analysis_family":"exploratory","gaps":["keine belastbare Belegzeile"],"model":"qwen"}\n\n' +
      'event: copilot.recovery\n' +
      'data: {"event":"copilot.recovery","recovery":{"kind":"llm_timeout","message":"Fallback auf konservative Antwort","retryable":true}}\n\n' +
      'event: copilot.done\n' +
      'data: {"text":"done"}\n\n'
    )))

    const onGrounding = vi.fn()
    const onEvidenceGap = vi.fn()
    const onRecovery = vi.fn()
    const cancel = streamCopilotMessage('grounding events', {
      onGrounding,
      onEvidenceGap,
      onRecovery,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onGrounding).toHaveBeenCalledWith({
      analysis_family: 'exploratory',
      verdict: 'conservative_only',
      rejected_claim_count: 2,
      route: 'responses',
      model: 'qwen',
    }))
    await vi.waitFor(() => expect(onEvidenceGap).toHaveBeenCalledWith({
      event: 'copilot.evidence_gap',
      analysis_family: 'exploratory',
      gaps: ['keine belastbare Belegzeile'],
      model: 'qwen',
    }))
    await vi.waitFor(() => expect(onRecovery).toHaveBeenCalledWith({
      kind: 'llm_timeout',
      message: 'Fallback auf konservative Antwort',
      retryable: true,
    }))
    cancel()
  })
})
