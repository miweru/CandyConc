import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { ActionBus } from '@/actions/bus'
import type { Action, ActionDispatchContext } from '@/actions/types'
import {
  clearPreviews,
  createPolicyGateMiddleware,
  currentPreview,
  enterCopilotContext,
  exitCopilotContext,
  executeCopilotActionRequest,
  getUnresolvedPreviews,
  resolvePreview,
} from '@/actions/policyGate'
import { useCopilotStore } from '@/stores/copilot'

describe('ActionBus dispatch context and policy gate', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    exitCopilotContext()
    clearPreviews()
  })

  it('passes ActionDispatchContext to middleware and handlers', async () => {
    const bus = new ActionBus()
    const seen: ActionDispatchContext[] = []

    bus.use(async (_action, next, context) => {
      seen.push(context)
      return next()
    })
    bus.register('ui/toast', async (_action, context) => {
      seen.push(context)
      return { success: true }
    })

    const result = await bus.dispatch(
      { type: 'ui/toast', payload: { message: 'ok', type: 'info' } },
      { source: 'system', requestId: 'req-1', timestamp: 123 }
    )

    expect(result).toMatchObject({ success: true, source: 'system' })
    expect(seen).toHaveLength(2)
    expect(seen[0]).toEqual({ source: 'system', requestId: 'req-1', timestamp: 123 })
    expect(seen[1]).toBe(seen[0])
    expect(bus.getHistory()[0]?.context).toBe(seen[0])
  })

  it('treats explicit user dispatch as user even inside legacy copilot context', async () => {
    const store = useCopilotStore()
    store.setAutonomyLevel(0)

    const bus = new ActionBus()
    let handled = false
    bus.use(createPolicyGateMiddleware())
    bus.register('query/execute', async () => {
      handled = true
      return { success: true }
    })

    enterCopilotContext()
    const result = await bus.dispatch({ type: 'query/execute', payload: { term: 'Haus' } }, 'user')
    exitCopilotContext()

    expect(result).toMatchObject({ success: true, source: 'user' })
    expect(handled).toBe(true)
    expect(getUnresolvedPreviews()).toHaveLength(0)
  })

  it('uses copilot dispatch context for policy previews', async () => {
    const store = useCopilotStore()
    store.setAutonomyLevel(0)

    const bus = new ActionBus()
    let handled = false
    bus.use(createPolicyGateMiddleware())
    bus.register('query/execute', async () => {
      handled = true
      return { success: true }
    })

    const resultPromise = bus.dispatch(
      { type: 'query/execute', payload: { term: 'Haus' } },
      { source: 'copilot', requestId: 'policy-req-1' }
    )
    const preview = currentPreview.value

    expect(preview?.action.type).toBe('query/execute')
    expect(preview?.requestId).toBe('policy-req-1')
    expect(getUnresolvedPreviews()).toHaveLength(1)

    resolvePreview(preview!.requestId, false, 'rejected')
    const result = await resultPromise

    expect(result).toMatchObject({
      success: false,
      blocked: true,
      source: 'copilot',
      requestId: 'policy-req-1',
      policyDecision: 'preview',
    })
    expect(handled).toBe(false)
  })

  it('dispatches ActionRequestV1 with copilot source', async () => {
    const contexts: Array<ActionDispatchContext | string> = []
    const dispatch = async (_action: Action, context: ActionDispatchContext | string) => {
      contexts.push(context)
      return { success: true }
    }

    const result = await executeCopilotActionRequest(
      { requestId: 'tool-1', type: 'ui/toast', payload: { message: 'ok', type: 'info' } },
      dispatch
    )

    expect(result.success).toBe(true)
    expect(contexts[0]).toEqual({ source: 'copilot', requestId: 'tool-1' })
  })
})
