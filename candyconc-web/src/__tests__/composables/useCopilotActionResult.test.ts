import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { actionBus } from '@/actions/bus'
import { clearPreviews, pendingPreviews } from '@/actions/policyGate'
import { useCopilotStore } from '@/stores/copilot'
import { useDocsetStore } from '@/stores/docset'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { kwicCapability, withCopilotGroundingCapability } from '@/__tests__/fixtures/copilotGroundingContract'
import { clearAllData, getRunRecord } from '@/services/runRecordService'
import type { ProductCapabilityContract } from '@/api/client'
import type { ActionMeta, ActionRequestV1, ActionResultPayload } from '@/types/copilot-protocol'

interface StreamHandlers {
  onActionRequest?: (request: ActionRequestV1, meta?: ActionMeta | Record<string, unknown>) => void
  onActionResult?: (result: ActionResultPayload) => void
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
    payload: { term: 'Backend-owned result', contextSize: 5 },
    rationale: 'Backend executes and owns the resulting run',
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

function systemMessagesContaining(...tokens: string[]) {
  return useCopilotStore().messages.filter((message) =>
    message.role === 'system' && tokens.every((token) => message.content.includes(token))
  )
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
    capabilities: [kwicCapability()],
  })
}

describe('useCopilot backend-owned action_result events', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractWithoutCqlf()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-live-1'
    docsetStore.stats = { docCount: 10, hitDocCount: 6, refDocCount: 2, tokenCount: 1234 }
    docsetStore.activeFilterSpec = { register: ['Drama'], year: { op: 'between', lo: 1900, hi: 1910 } }
    docsetStore.metaSchemaHash = 'schema-v1'
    vi.restoreAllMocks()
    clearPreviews()
    clearAllData()
    actionBus.releaseLock()
    actionBus.clearHistory()
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

  it('surfaces successful action_result request and run ids without local dispatch or preview', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: true,
      source: 'copilot',
    })
    sseMocks.getCurrentSessionId.mockReturnValue('session-action-result-success')

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.(
        actionRequest('req-backend-owned-success'),
        {
          ...actionMeta(),
          requiresApproval: false,
          status: 'auto_approved',
        }
      )
      handlers.onActionResult?.({
        requestId: 'req-backend-owned-success',
        ok: true,
        runId: 'run-backend-owned-success',
        resultSummary: '12 Treffer aus Backend-Run',
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend liefert ein action_result.')
    await flushAsyncCopilot()

    expect(systemMessagesContaining('req-backend-owned-success', 'run-backend-owned-success')).toHaveLength(1)
    expect(systemMessagesContaining('12 Treffer aus Backend-Run')).toHaveLength(1)
    expect(getRunRecord('run-backend-owned-success')).toMatchObject({
      runId: 'run-backend-owned-success',
      requestId: 'req-backend-owned-success',
      actionType: 'query/execute',
      actionPayload: { term: 'Backend-owned result', contextSize: 5 },
      summary: '12 Treffer aus Backend-Run',
      schemaVersion: '2.0',
      evidence: expect.objectContaining({
        provenance: 'backend_action_result',
        completeness: 'partial',
      }),
    })
    const mirroredRun = getRunRecord('run-backend-owned-success')
    expect(mirroredRun?.evidence.corpusFingerprint.subcorpusHash).toBe('')
    expect(mirroredRun?.evidence.researchScope).toMatchObject({
      corpusId: 'backend-owned',
      scopeHash: '',
      scopeStatus: 'unknown',
    })
    expect(mirroredRun?.evidence.warnings).toContain(
      'Backend execution scope unavailable without backend V2 evidence; mirrored scope is unknown.'
    )
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain(
      'req-backend-owned-success'
    )
    expect(pendingPreviews.value.map((preview) => preview.requestId)).not.toContain(
      'req-backend-owned-success'
    )
    expect(dispatchSpy).not.toHaveBeenCalled()
  })

  it('fails closed for unknown action_result without embedded request payload and does not create a run record', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: true,
      source: 'copilot',
    })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionResult?.({
        requestId: 'req-unknown-action-result',
        ok: true,
        runId: 'run-must-not-be-created',
        resultSummary: 'Backend behauptet Erfolg ohne bekannte Request',
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend liefert ein unbekanntes action_result.')
    await flushAsyncCopilot()

    expect(systemMessagesContaining('req-unknown-action-result', 'blockiert')).toHaveLength(1)
    expect(getRunRecord('run-must-not-be-created')).toBeUndefined()
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain(
      'req-unknown-action-result'
    )
    expect(pendingPreviews.value.map((preview) => preview.requestId)).not.toContain(
      'req-unknown-action-result'
    )
    expect(dispatchSpy).not.toHaveBeenCalled()
  })

  it('does not mirror action_result for a locally blocked action request even with embedded request', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: true,
      source: 'copilot',
    })
    sseMocks.getCurrentSessionId.mockReturnValue('session-blocked-result')
    sseMocks.rejectAction.mockResolvedValue({ status: 'rejected', actionId: 'req-blocked-result' })

    const blockedRequest: ActionRequestV1 = {
      requestId: 'req-blocked-result',
      type: 'unknown/mutate',
      payload: { dangerous: true },
      rationale: 'Should be blocked by local frontend policy',
    }

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionRequest?.(blockedRequest, {
        ...actionMeta(),
        type: 'unknown/mutate',
      })
      handlers.onActionResult?.({
        requestId: 'req-blocked-result',
        ok: true,
        runId: 'run-blocked-result',
        request: blockedRequest,
        resultSummary: 'Backend claimed success after local block',
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend versucht eine lokal geblockte Aktion später als Ergebnis zu melden.')
    await flushAsyncCopilot()

    expect(systemMessagesContaining('req-blocked-result', 'blockiert')).toHaveLength(1)
    expect(getRunRecord('run-blocked-result')).toBeUndefined()
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(copilot.pendingActionRequests.value.map((request) => request.requestId)).not.toContain(
      'req-blocked-result'
    )
    expect(pendingPreviews.value.map((preview) => preview.requestId)).not.toContain(
      'req-blocked-result'
    )
    expect(dispatchSpy).not.toHaveBeenCalled()
  })

  it('does not mirror embedded CQLF action_result when CQLF is hidden', async () => {
    const dispatchSpy = vi.spyOn(actionBus, 'dispatch').mockResolvedValue({
      success: true,
      source: 'copilot',
    })
    const hiddenRequest: ActionRequestV1 = {
      requestId: 'req-hidden-cqlf-result',
      type: 'query/execute',
      payload: { term: '[word=\"Hase\"]', contextSize: 5 },
      rationale: 'Backend should not bypass local product capability gating',
    }

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onActionResult?.({
        requestId: 'req-hidden-cqlf-result',
        ok: true,
        runId: 'run-hidden-cqlf-result',
        request: hiddenRequest,
        resultSummary: 'Backend claimed CQLF success',
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Backend liefert CQLF action_result ohne lokale Freigabe.')
    await new Promise((resolve) => setTimeout(resolve, 0))

    expect(systemMessagesContaining('req-hidden-cqlf-result', 'blockiert', 'CQLF')).toHaveLength(1)
    expect(getRunRecord('run-hidden-cqlf-result')).toBeUndefined()
    expect(copilot.currentActionPreview.value).toBeNull()
    expect(dispatchSpy).not.toHaveBeenCalled()
  })
})
