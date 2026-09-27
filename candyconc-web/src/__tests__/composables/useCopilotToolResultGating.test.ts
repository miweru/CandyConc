/**
 * Governance of backend ToolResultV1 frames (`copilot.tool_result`).
 *
 * The legacy `tool_call`/`tool_result`/`clarification` SSE protocol and the
 * client-side executeToolAsAction path are removed — the backend executes all
 * tools itself and streams structured ToolResultV1 frames. These tests pin the
 * remaining frontend responsibilities: capability gating, honest error
 * rendering, and not_applicable handling.
 */
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { actionBus } from '@/actions/bus'
import { useCopilotStore } from '@/stores/copilot'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { withCopilotGroundingCapability } from '@/__tests__/fixtures/copilotGroundingContract'
import type { ProductCapabilityContract } from '@/api/client'
import type { ToolResultV1 } from '@/types/copilot-protocol'

function flushAsyncCopilot(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

interface StreamHandlers {
  onToolResultV1?: (result: ToolResultV1) => void
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

function productContractFixture(): ProductCapabilityContract {
  const copilotTools = [
    'document_search',
    'documentation_search',
    'cluster_save',
    'cluster_export_md',
    'refine_cluster_label',
  ]
  return withCopilotGroundingCapability({
    version: 'product-capabilities-v1',
    scope: 'CandyConc product capability contract',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: {
      version: 'cqlf-capabilities-v1',
      current_level: '2-',
      fingerprint_sha256: 'b'.repeat(64),
    },
    capabilities: [],
  }, { copilot_tools: copilotTools })
}

function productContractWithHiddenSemanticClustering(): ProductCapabilityContract {
  const contract = productContractFixture()
  return {
    ...contract,
    capabilities: [
      ...contract.capabilities,
      {
        id: 'analysis.semantic_clustering',
        title: 'Semantic clustering workflows',
        area: 'analysis',
        maturity: 'experimental',
        visibility: 'hidden_experimental',
        backend_routes: [],
        frontend_evidence: [],
        action_types: [],
        copilot_tools: ['semantic_cluster', 'semantic_cluster_words', 'semantic_recluster'],
        preconditions: [],
        limits: [],
      },
    ],
  }
}

describe('useCopilot ToolResultV1 gating', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractFixture()
    productCapabilities.status = 'ready'
    productCapabilities.error = null
    vi.restoreAllMocks()
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

  it('renders successful backend tool results as tool-call evidence', async () => {
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'copilot' })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onToolResultV1?.({
        toolName: 'cluster_save',
        ok: true,
        ts: 1,
        input: { clusterId: 'cluster-1' },
        output: { saved: true, path: 'cluster.md' },
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Cluster speichern.')
    await flushAsyncCopilot()

    const assistantMessage = useCopilotStore().messages.find((message) => message.role === 'assistant')
    expect(assistantMessage?.toolCalls).toHaveLength(1)
    expect(assistantMessage?.toolCalls?.[0]).toMatchObject({
      name: 'cluster_save',
      status: 'success',
      result: { saved: true, path: 'cluster.md' },
    })
  })

  it('keeps ToolResultV1 ok=false as an error even when output is present', async () => {
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'copilot' })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onToolResultV1?.({
        toolName: 'document_search',
        ok: false,
        ts: 1,
        input: { query: 'Hase' },
        output: {
          error: 'Dokumentsuche fehlgeschlagen.',
          rows: [{ title: 'Darf nicht als Evidenz erscheinen' }],
        },
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Suche Dokumente.')
    await flushAsyncCopilot()

    const assistantMessage = useCopilotStore().messages.find((message) => message.role === 'assistant')
    expect(assistantMessage?.toolCalls).toHaveLength(1)
    expect(assistantMessage?.toolCalls?.[0]).toMatchObject({
      name: 'document_search',
      status: 'error',
      error: 'Dokumentsuche fehlgeschlagen.',
      result: {
        ok: false,
        status: 'error',
        error: 'Dokumentsuche fehlgeschlagen.',
      },
    })
  })

  it('preserves structured parser diagnostics and the backend message', async () => {
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'copilot' })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onToolResultV1?.({
        toolName: 'document_search',
        ok: false,
        ts: 1,
        input: { query: 'cql:[lemma="Demokratie"' },
        output: {
          status: 'error',
          message: 'Expected closing bracket',
          query: 'cql:[lemma="Demokratie"',
          diagnostics: {
            errors: ['Unbalanced brackets'],
            suggestions: ['cql:[lemma="Demokratie"]'],
          },
        },
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Diagnostiziere die ungültige Abfrage.')
    await flushAsyncCopilot()

    const assistantMessage = useCopilotStore().messages.find((message) => message.role === 'assistant')
    expect(assistantMessage?.toolCalls?.[0]).toMatchObject({
      name: 'document_search',
      status: 'error',
      error: 'Expected closing bracket',
      result: {
        status: 'error',
        message: 'Expected closing bracket',
        query: 'cql:[lemma="Demokratie"',
        diagnostics: {
          errors: ['Unbalanced brackets'],
          suggestions: ['cql:[lemma="Demokratie"]'],
        },
      },
    })
  })

  it('blocks hidden experimental backend tool results', async () => {
    const productCapabilities = useProductCapabilitiesStore()
    productCapabilities.contract = productContractWithHiddenSemanticClustering()
    productCapabilities.status = 'ready'
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'copilot' })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onToolResultV1?.({
        toolName: 'semantic_cluster',
        ok: true,
        ts: 1,
        input: { term: 'Migration' },
        output: { clusters: [{ label: 'Migration' }] },
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Cluster explorieren.')
    await flushAsyncCopilot()

    const assistantMessage = useCopilotStore().messages.find((message) => message.role === 'assistant')
    expect(assistantMessage?.toolCalls?.[0]).toMatchObject({
      name: 'semantic_cluster',
      status: 'error',
      error: expect.stringContaining('nicht als CandyConc-Funktion freigegeben'),
      result: expect.objectContaining({ blocked: true }),
    })
  })

  it('renders not_applicable tool results as non-success instead of computed evidence', async () => {
    vi.spyOn(actionBus, 'dispatch').mockResolvedValue({ success: true, source: 'copilot' })

    sseMocks.streamCopilotMessage.mockImplementationOnce((_message: string, handlers: StreamHandlers) => {
      handlers.onToolResultV1?.({
        toolName: 'document_search',
        ok: true,
        ts: 1,
        input: { query: 'Hase' },
        output: {
          status: 'not_applicable',
          reason: 'corpus_not_ready',
          detail: 'Dokumentsuche ist für diesen Korpus nicht anwendbar.',
        },
      })
      handlers.onDone('done')
      return vi.fn()
    })

    const copilot = useCopilot()
    await copilot.sendMessage('Dokumentsuche ausführen.')
    await flushAsyncCopilot()

    const assistantMessage = useCopilotStore().messages.find((message) => message.role === 'assistant')
    expect(assistantMessage?.toolCalls?.[0]).toMatchObject({
      name: 'document_search',
      status: 'error',
      result: expect.objectContaining({ status: 'not_applicable' }),
    })
  })
})
