import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { addActionPreview, clearPreviews, pendingPreviews } from '@/actions/policyGate'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { withCopilotGroundingCapability } from '@/__tests__/fixtures/copilotGroundingContract'
import { COPILOT_GROUNDING_OPERATIONS } from '@/lib/copilotGroundingOperations'
import type { ProductCapabilityContract } from '@/api/client'
import type { ActionMeta, ActionRequestV1, ToolResultV1 } from '@/types/copilot-protocol'

function flushAsyncCopilot(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

interface StreamHandlers {
  onToolResultV1?: (result: ToolResultV1) => void
  onActionRequest?: (request: ActionRequestV1, meta?: ActionMeta | Record<string, unknown>) => void
  onDone: (content: string) => void
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

import { useCopilot } from '@/composables/useCopilot'

function deferred<T = void>() {
  let resolve!: (value: T | PromiseLike<T>) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

function actionRequest(requestId: string): ActionRequestV1 {
  return {
    requestId,
    type: 'query/execute',
    payload: { term: 'Klimawandel', contextSize: 5 },
    rationale: 'Run the query after user approval',
  }
}

function actionMeta(type: string): ActionMeta {
  return {
    type,
    label: 'Execute query',
    reversible: true,
    userVisible: true,
    cost: 'medium',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 5,
  }
}

function route(path: string, methods = ['GET']) {
  return {
    path,
    methods,
    mutates: methods.some((method) => method !== 'GET'),
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
    route_class: 'product_surface',
  }
}

function productContractWithoutCqlf(): ProductCapabilityContract {
  return withCopilotGroundingCapability({
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [{
      id: 'query.kwic',
      title: 'KWIC',
      area: 'query',
      maturity: 'stable',
      visibility: 'first_class_ui',
      backend_routes: ['/api/v1/query/stream', '/api/v1/query'],
      backend_route_descriptors: [
        route('/api/v1/query/stream'),
        route('/api/v1/query'),
      ],
      operations: [
        {
          id: 'query.kwic.stream',
          capability_id: 'query.kwic',
          label: 'KWIC streamen',
          description: '',
          route: route('/api/v1/query/stream'),
          effects: ['read', 'long_running'],
          handler_key: 'stream_kwic',
          surface_slot: 'kwic.stream',
          priority: 10,
        },
        {
          id: 'query.kwic.page',
          capability_id: 'query.kwic',
          label: 'KWIC laden',
          description: '',
          route: route('/api/v1/query'),
          effects: ['read'],
          handler_key: 'kwic_page',
          surface_slot: 'kwic.page',
          priority: 20,
        },
      ],
      frontend_evidence: [],
      action_types: ['query/execute'],
      copilot_tools: ['run_cqlf_query'],
      preconditions: [],
      limits: [],
    }],
  })
}

function productContractWithoutCopilotOperation(operationId: string): ProductCapabilityContract {
  const contract = productContractWithoutCqlf()
  return {
    ...contract,
    capabilities: contract.capabilities.map((capability) => capability.id === 'research.copilot_grounding'
      ? {
          ...capability,
          operations: (capability.operations ?? []).filter((operation) => operation.id !== operationId),
        }
      : capability),
  }
}

function systemMessagesContaining(...tokens: string[]) {
  return useCopilotStore().messages.filter((message) =>
    message.role === 'system' && tokens.every((token) => message.content.includes(token))
  )
}

async function addPendingAction(
  copilot: ReturnType<typeof useCopilot>,
  requestId: string
) {
  const request = actionRequest(requestId)
  sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
    handlers.onActionRequest?.(request, actionMeta(request.type))
    handlers.onDone('done')
    return vi.fn()
  })

  await copilot.sendMessage(`Bitte Aktion ${requestId} vorbereiten.`)
  await flushAsyncCopilot()

  expect(copilot.currentActionPreview.value?.requestId).toBe(requestId)
  expect(copilot.pendingActionRequests.value.map(r => r.requestId)).toContain(requestId)
}

function previewFor(requestId: string) {
  return pendingPreviews.value.find(preview => preview.requestId === requestId)
}

function addLocalPreview(requestId: string) {
  addActionPreview(
    { type: 'query/execute', payload: { term: 'Klimawandel' } } as never,
    actionMeta('query/execute'),
    'preview',
    undefined,
    requestId
  )
}

describe('useCopilot action governance', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractWithoutCqlf()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    vi.restoreAllMocks()
    clearPreviews()
    sseMocks.streamCopilotMessage.mockReset()
    sseMocks.approveAction.mockReset()
    sseMocks.rejectAction.mockReset()
    sseMocks.answerClarification.mockReset()
    sseMocks.updateCopilotContext.mockReset()
    sseMocks.getCurrentSessionId.mockReset()
    sseMocks.continueCopilotExecution.mockReset()
    sseMocks.getCurrentSessionId.mockReturnValue(null)
    sseMocks.continueCopilotExecution.mockReturnValue(vi.fn())
  })

  it('blocks chat streaming before network when chat_stream is not offered', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractWithoutCopilotOperation(
      COPILOT_GROUNDING_OPERATIONS.chatStream,
    )
    productCapabilities.status = 'ready'

    const copilot = useCopilot()
    await copilot.sendMessage('Bitte starten.')

    expect(sseMocks.streamCopilotMessage).not.toHaveBeenCalled()
    expect(systemMessagesContaining('Copilot-Chat streamen', 'nicht als Serverfunktion verfügbar')).toHaveLength(1)
  })

  it('blocks backend approval before network when action_approve is not offered', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-approve-operation-blocked')
    const copilot = useCopilot()
    await addPendingAction(copilot, 'req-approve-operation-blocked')

    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractWithoutCopilotOperation(
      COPILOT_GROUNDING_OPERATIONS.actionApprove,
    )

    await copilot.approveAction('req-approve-operation-blocked')

    expect(sseMocks.approveAction).not.toHaveBeenCalled()
    expect(sseMocks.continueCopilotExecution).not.toHaveBeenCalled()
    expect(systemMessagesContaining('Copilot-Aktion genehmigen', 'nicht als Serverfunktion verfügbar')).toHaveLength(1)
  })

  it('blocks orchestration continue before network when continue is not offered', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-continue-operation-blocked')
    sseMocks.approveAction.mockResolvedValue({ status: 'approved', actionId: 'req-continue-operation-blocked' })
    const copilot = useCopilot()
    await addPendingAction(copilot, 'req-continue-operation-blocked')

    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractWithoutCopilotOperation(
      COPILOT_GROUNDING_OPERATIONS.continue,
    )

    await copilot.approveAction('req-continue-operation-blocked')

    expect(sseMocks.approveAction).toHaveBeenCalledWith(
      'req-continue-operation-blocked',
      'session-continue-operation-blocked',
    )
    expect(sseMocks.continueCopilotExecution).not.toHaveBeenCalled()
    expect(systemMessagesContaining('Copilot-Ausführung fortsetzen', 'nicht als Serverfunktion verfügbar')).toHaveLength(1)
  })

  it('keeps approval preview pending until backend approval succeeds', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-approve')
    const backendApproval = deferred()
    sseMocks.approveAction.mockReturnValue(backendApproval.promise)

    const copilot = useCopilot()
    await addPendingAction(copilot, 'req-approve-success')

    const approvePromise = copilot.approveAction('req-approve-success')
    await flushAsyncCopilot()

    expect(sseMocks.approveAction).toHaveBeenCalledWith('req-approve-success', 'session-approve')
    expect(copilot.currentActionPreview.value?.requestId).toBe('req-approve-success')
    expect(previewFor('req-approve-success')?.resolved).toBe(false)
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).toContain('req-approve-success')

    backendApproval.resolve()
    await approvePromise

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-approve-success')?.resolution).toBe('approved')
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-approve-success')
    expect(sseMocks.continueCopilotExecution).toHaveBeenCalledWith(expect.any(Object), 'session-approve')
  })

  it('blocks unknown action requests before they become approvable previews', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-block')
    sseMocks.rejectAction.mockResolvedValue({ status: 'rejected', actionId: 'req-unknown' })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.({
        requestId: 'req-unknown',
        type: 'unknown/mutate',
        payload: { value: true },
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Bitte riskante unbekannte Aktion ausführen.')
    await flushAsyncCopilot()

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-unknown')).toBeUndefined()
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-unknown')
    expect(sseMocks.rejectAction).toHaveBeenCalledWith(
      'req-unknown',
      expect.stringContaining('Lokale Frontend-Policy blockiert'),
      'session-block'
    )
  })

  it('rejects backend CQLF action requests before approval when CQLF is hidden', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractWithoutCqlf()
    productCapabilities.status = 'ready'
    sseMocks.getCurrentSessionId.mockReturnValue('session-hidden-cqlf')
    sseMocks.rejectAction.mockResolvedValue({ status: 'rejected', actionId: 'req-hidden-cqlf' })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.({
        requestId: 'req-hidden-cqlf',
        type: 'query/execute',
        payload: { term: '[word=\"Hase\"]', contextSize: 5 },
      }, actionMeta('query/execute'))
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Bitte CQLF ausführen.')
    await flushAsyncCopilot()

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-hidden-cqlf')).toBeUndefined()
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-hidden-cqlf')
    expect(sseMocks.rejectAction).toHaveBeenCalledWith(
      'req-hidden-cqlf',
      expect.stringContaining('CQLF ist laut Fähigkeitskatalog nicht freigeschaltet'),
      'session-hidden-cqlf'
    )
  })

  it('does not create pending approval UI for auto-approved backend action requests', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-auto-approved')
    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.(
        actionRequest('req-auto-approved'),
        {
          ...actionMeta('query/execute'),
          requiresApproval: false,
          status: 'auto_approved',
        }
      )
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend sagt auto-approved.')
    await flushAsyncCopilot()

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-auto-approved')).toBeUndefined()
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-auto-approved')
    expect(sseMocks.approveAction).not.toHaveBeenCalled()
    expect(sseMocks.rejectAction).not.toHaveBeenCalled()
  })

  it('deduplicates repeated backend action requests by request id', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-duplicate-request')
    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.(actionRequest('req-duplicate'), actionMeta('query/execute'))
      handlers.onActionRequest?.(actionRequest('req-duplicate'), actionMeta('query/execute'))
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend schickt dieselbe Aktion doppelt.')
    await flushAsyncCopilot()

    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).toEqual(['req-duplicate'])
    expect(pendingPreviews.value.filter(preview => preview.requestId === 'req-duplicate')).toHaveLength(1)
    expect(copilot.currentActionPreview.value?.requestId).toBe('req-duplicate')
  })

  it('fails closed for backend action requests without an active session', async () => {
    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.(actionRequest('req-no-session'), actionMeta('query/execute'))
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend-Aktion ohne Session.')
    await flushAsyncCopilot()

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-no-session')).toBeUndefined()
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-no-session')
    expect(sseMocks.approveAction).not.toHaveBeenCalled()
    expect(sseMocks.rejectAction).not.toHaveBeenCalled()
  })

  it('deduplicates concurrent approvals for the same request id', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-double-approve')
    const backendApproval = deferred()
    sseMocks.approveAction.mockReturnValue(backendApproval.promise)

    const copilot = useCopilot()
    await addPendingAction(copilot, 'req-double-approve')

    const firstApprove = copilot.approveAction('req-double-approve')
    const secondApprove = copilot.approveAction('req-double-approve')
    await flushAsyncCopilot()

    expect(sseMocks.approveAction).toHaveBeenCalledTimes(1)
    backendApproval.resolve()
    await Promise.all([firstApprove, secondApprove])

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-double-approve')?.resolution).toBe('approved')
    expect(sseMocks.continueCopilotExecution).toHaveBeenCalledTimes(1)
  })

  it('keeps approval preview and pending request when backend approval fails', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-approve-error')
    sseMocks.approveAction.mockRejectedValue(new Error('approval backend unavailable'))
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    const copilot = useCopilot()
    await addPendingAction(copilot, 'req-approve-error')

    await copilot.approveAction('req-approve-error').catch(() => undefined)

    expect(sseMocks.approveAction).toHaveBeenCalledWith('req-approve-error', 'session-approve-error')
    expect(copilot.currentActionPreview.value?.requestId).toBe('req-approve-error')
    expect(previewFor('req-approve-error')?.resolved).toBe(false)
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).toContain('req-approve-error')
    expect(sseMocks.continueCopilotExecution).not.toHaveBeenCalled()
  })

  it('keeps rejection preview pending until backend rejection succeeds', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-reject')
    const backendRejection = deferred()
    sseMocks.rejectAction.mockReturnValue(backendRejection.promise)

    const copilot = useCopilot()
    await addPendingAction(copilot, 'req-reject-success')

    const rejectPromise = copilot.rejectAction('req-reject-success', 'Nicht ausführen')
    await flushAsyncCopilot()

    expect(sseMocks.rejectAction).toHaveBeenCalledWith('req-reject-success', 'Nicht ausführen', 'session-reject')
    expect(copilot.currentActionPreview.value?.requestId).toBe('req-reject-success')
    expect(previewFor('req-reject-success')?.resolved).toBe(false)
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).toContain('req-reject-success')

    backendRejection.resolve()
    await rejectPromise

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-reject-success')?.resolution).toBe('rejected')
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-reject-success')
    expect(sseMocks.continueCopilotExecution).toHaveBeenCalledTimes(1)
    expect(sseMocks.continueCopilotExecution).toHaveBeenCalledWith(expect.any(Object), 'session-reject')
  })

  it('keeps rejection preview and pending request when backend rejection fails', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-reject-error')
    sseMocks.rejectAction.mockRejectedValue(new Error('rejection backend unavailable'))
    vi.spyOn(console, 'warn').mockImplementation(() => undefined)

    const copilot = useCopilot()
    await addPendingAction(copilot, 'req-reject-error')

    await copilot.rejectAction('req-reject-error', 'Nicht ausführen').catch(() => undefined)

    expect(sseMocks.rejectAction).toHaveBeenCalledWith(
      'req-reject-error',
      'Nicht ausführen',
      'session-reject-error'
    )
    expect(copilot.currentActionPreview.value?.requestId).toBe('req-reject-error')
    expect(previewFor('req-reject-error')?.resolved).toBe(false)
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).toContain('req-reject-error')
    expect(sseMocks.continueCopilotExecution).not.toHaveBeenCalled()
  })

  it('resolves local-only previews without backend approval endpoints', async () => {
    const copilot = useCopilot()

    addLocalPreview('req-offline-approve')
    await copilot.approveAction('req-offline-approve')

    expect(sseMocks.approveAction).not.toHaveBeenCalled()
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-offline-approve')?.resolution).toBe('approved')
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-offline-approve')

    addLocalPreview('req-offline-reject')
    await copilot.rejectAction('req-offline-reject', 'Offline ablehnen')

    expect(sseMocks.rejectAction).not.toHaveBeenCalled()
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(previewFor('req-offline-reject')?.resolution).toBe('rejected')
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).not.toContain('req-offline-reject')
  })

  it('does not send local-only previews to backend even when a session exists', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-local-preview')
    const copilot = useCopilot()

    addLocalPreview('req-local-only')
    await copilot.approveAction('req-local-only')

    expect(sseMocks.approveAction).not.toHaveBeenCalled()
    expect(sseMocks.continueCopilotExecution).not.toHaveBeenCalled()
    expect(previewFor('req-local-only')?.resolution).toBe('approved')
  })

  it('turns suggested actions from structured tool results into governed previews', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-tool-result')
    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onToolResultV1?.({
        toolName: 'document_search',
        ok: true,
        ts: 1,
        output: { rows: [] },
        suggestedActions: [actionRequest('req-suggested-action')],
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Bitte suche Dokumente und schlage nächste Aktion vor.')
    await flushAsyncCopilot()

    expect(copilot.currentActionPreview.value?.requestId).toBe('req-suggested-action')
    expect(copilot.pendingActionRequests.value.map(r => r.requestId)).toContain('req-suggested-action')
    expect(previewFor('req-suggested-action')).toBeDefined()
  })
})
