import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { actionBus } from '@/actions/bus'
import { addActionPreview, clearPreviews, pendingPreviews } from '@/actions/policyGate'
import { useCopilotStore } from '@/stores/copilot'
import { useQueryStore } from '@/stores/query'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { copilotGroundingWithKwicContract } from '@/__tests__/fixtures/copilotGroundingContract'
import type { ActionCommitPayload, ActionMeta, ActionRequestV1 } from '@/types/copilot-protocol'

interface StreamHandlers {
  onActionRequest?: (request: ActionRequestV1, meta?: ActionMeta | Record<string, unknown>) => void
  onActionCommit?: (commit: ActionCommitPayload) => void
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

vi.mock('@/composables/useContextSnapshot', () => ({
  useContextSnapshot: () => ({
    buildSnapshotSync: () => ({
      version: '1.0',
      ts: 1,
    }),
  }),
}))

import { useCopilot } from '@/composables/useCopilot'

function flushAsyncCopilot(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function actionRequest(requestId: string): ActionRequestV1 {
  return {
    requestId,
    type: 'query/execute',
    payload: { term: 'Commit darf nicht lokal mutieren', contextSize: 5 },
    rationale: 'Backend approval request',
  }
}

function actionMeta(): ActionMeta {
  return {
    type: 'query/execute',
    label: 'Execute query',
    reversible: true,
    userVisible: true,
    cost: 'medium',
    scientificRisk: ['none'],
    requiresConfirmationAtOrBelowAutonomy: 5,
  }
}

function visibleCommitMessages(requestId: string) {
  return useCopilotStore().messages.filter((message) =>
    message.role === 'system' && message.content.includes(requestId)
  )
}

async function createApprovedBackendAction(copilot: ReturnType<typeof useCopilot>, requestId: string) {
  sseMocks.getCurrentSessionId.mockReturnValue('session-commit-dedupe')
  sseMocks.approveAction.mockResolvedValue({ status: 'approved', actionId: requestId })
  sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
    handlers.onActionRequest?.(actionRequest(requestId), actionMeta())
    handlers.onDone('approval requested')
    return vi.fn()
  })

  await copilot.sendMessage('Bitte Backend-Aktion vorbereiten.')
  await flushAsyncCopilot()
  expect(copilot.currentActionPreview.value?.requestId).toBe(requestId)

  await copilot.approveAction(requestId)
  expect(copilot.currentActionPreview.value).toBeNull()
  expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain(requestId)
}

describe('useCopilot action commit events', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = copilotGroundingWithKwicContract()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    vi.restoreAllMocks()
    clearPreviews()
    actionBus.releaseLock()
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

  it('shows action_commit events without creating a preview or local mutation', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: true,
      source: 'copilot',
    })
    const queryStore = useQueryStore()
    queryStore.setTerm('stabiler lokaler Zustand')

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionCommit?.({ requestId: 'req-visible-commit' })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend meldet einen Commit.')
    await flushAsyncCopilot()

    expect(visibleCommitMessages('req-visible-commit')).toHaveLength(1)
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain('req-visible-commit')
    expect(pendingPreviews.value.map((preview) => preview.requestId)).not.toContain('req-visible-commit')
    expect(dispatchSpy).not.toHaveBeenCalled()
    expect(queryStore.term).toBe('stabiler lokaler Zustand')
  })

  it('deduplicates commits for already-approved backend action requests by requestId', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: true,
      source: 'copilot',
    })
    const copilot = useCopilot()
    await createApprovedBackendAction(copilot, 'req-approved-commit')

    const previewsBeforeCommit = pendingPreviews.value.map((preview) => ({
      requestId: preview.requestId,
      resolved: preview.resolved,
      resolution: preview.resolution,
    }))

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionCommit?.({ requestId: 'req-approved-commit' })
      handlers.onDone('commit received')
      return vi.fn()
    })

    await copilot.sendMessage('Backend bestätigt den Commit.')
    await flushAsyncCopilot()

    expect(visibleCommitMessages('req-approved-commit')).toHaveLength(1)
    expect(pendingPreviews.value.map((preview) => ({
      requestId: preview.requestId,
      resolved: preview.resolved,
      resolution: preview.resolution,
    }))).toEqual(previewsBeforeCommit)
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain('req-approved-commit')
    expect(dispatchSpy).not.toHaveBeenCalled()
  })

  it('deduplicates commits for approved local-only previews by requestId', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: true,
      source: 'copilot',
    })
    const copilot = useCopilot()

    addActionPreview(
      { type: 'query/execute', payload: { term: 'lokal genehmigt' } } as never,
      actionMeta(),
      'preview',
      'local preview',
      'req-local-approved-commit'
    )
    await copilot.approveAction('req-local-approved-commit')

    const previewsBeforeCommit = pendingPreviews.value.map((preview) => preview.requestId)

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionCommit?.({ requestId: 'req-local-approved-commit' })
      handlers.onDone('commit received')
      return vi.fn()
    })

    await copilot.sendMessage('Backend bestätigt lokalen Commit.')
    await flushAsyncCopilot()

    expect(visibleCommitMessages('req-local-approved-commit')).toHaveLength(1)
    expect(pendingPreviews.value.map((preview) => preview.requestId)).toEqual(previewsBeforeCommit)
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(dispatchSpy).not.toHaveBeenCalled()
  })

  it('ignores action requests that arrive after the same request id was committed', async () => {
    const copilot = useCopilot()

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionCommit?.({
        requestId: 'req-commit-before-request',
        request: actionRequest('req-commit-before-request'),
      })
      handlers.onActionRequest?.(actionRequest('req-commit-before-request'), actionMeta())
      handlers.onDone('done')
      return vi.fn()
    })

    await copilot.sendMessage('Commit kommt vor ActionRequest.')
    await flushAsyncCopilot()

    expect(visibleCommitMessages('req-commit-before-request')).toHaveLength(2)
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain(
      'req-commit-before-request'
    )
    expect(pendingPreviews.value.map((preview) => preview.requestId)).not.toContain(
      'req-commit-before-request'
    )
  })

  it('closes pending approval UI on commit and does not send a later approval again', async () => {
    sseMocks.getCurrentSessionId.mockReturnValue('session-commit-before-approval')
    const copilot = useCopilot()

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.(actionRequest('req-pending-then-commit'), actionMeta())
      handlers.onActionCommit?.({ requestId: 'req-pending-then-commit' })
      handlers.onDone('done')
      return vi.fn()
    })

    await copilot.sendMessage('ActionRequest wird direkt committed.')
    await flushAsyncCopilot()

    expect(copilot.currentActionPreview.value).toBeNull()
    expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain(
      'req-pending-then-commit'
    )
    expect(pendingPreviews.value.find((preview) => preview.requestId === 'req-pending-then-commit'))
      .toMatchObject({ resolved: true, resolution: 'approved' })

    await copilot.approveAction('req-pending-then-commit')

    expect(sseMocks.approveAction).not.toHaveBeenCalled()
  })
})
