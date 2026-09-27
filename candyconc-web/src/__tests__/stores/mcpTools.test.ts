import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useMcpToolsStore } from '@/stores/mcpTools'

const getMcpTools = vi.fn()

vi.mock('@/api/client', () => ({
  getMcpTools: (...args: unknown[]) => getMcpTools(...args),
}))

describe('mcpTools store', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('maps listed MCP tools back to ProductOperations', async () => {
    getMcpTools.mockResolvedValueOnce({
      tools: [{
        type: 'function',
        function: { name: 'frequency_list', description: 'Frequency list' },
        read_only: true,
        concurrency_safe: true,
        runtime_metadata_status: 'verified',
        product_operation_ids: ['analysis.frequency.list'],
        product_capability_ids: ['analysis.frequency'],
        product_effects: ['read'],
        requires_corpus_features: [],
      }],
      tool_statuses: [{
        name: 'frequency_list',
        status: 'operation_bound',
        dispatchable: true,
        reason: 'Tool ist dispatchbar.',
        registered: true,
        visible_product_claimed: true,
        read_only: true,
        concurrency_safe: true,
        runtime_metadata_status: 'verified',
        product_operation_ids: ['analysis.frequency.list'],
        product_capability_ids: ['analysis.frequency'],
        product_effects: ['read'],
        requires_corpus_features: [],
      }],
    })

    const store = useMcpToolsStore()
    await store.load()

    expect(store.status).toBe('ready')
    expect(store.toolsForOperation('analysis.frequency.list').map((tool) => tool.function.name)).toEqual([
      'frequency_list',
    ])
    expect(store.runtimeDecisionForOperation({
      operationId: 'analysis.frequency.list',
      copilotTools: ['frequency_list'],
    })).toMatchObject({
      status: 'available',
      listedToolNames: ['frequency_list'],
      missingToolNames: [],
      readOnly: true,
      concurrencySafe: true,
      runtimeMetadataStatus: 'verified',
    })
  })

  it('flags contract-bound tools that are not listed by the MCP runtime', async () => {
    getMcpTools.mockResolvedValueOnce({
      tools: [],
      tool_statuses: [{
        name: 'frequency_list',
        status: 'policy_blocked',
        dispatchable: false,
        reason: 'Release-Default-Deny blockiert nicht-read-only Tools ohne explizite Tool-ACL.',
        registered: true,
        visible_product_claimed: true,
        read_only: false,
        concurrency_safe: false,
        runtime_metadata_status: 'verified',
        product_operation_ids: ['analysis.frequency.list'],
        product_capability_ids: ['analysis.frequency'],
        product_effects: ['write'],
        requires_corpus_features: [],
      }],
    })

    const store = useMcpToolsStore()
    await store.load()

    expect(store.runtimeDecisionForOperation({
      operationId: 'analysis.frequency.list',
      copilotTools: ['frequency_list'],
    })).toMatchObject({
      status: 'not_listed',
      missingToolNames: ['frequency_list'],
      reason: 'Mindestens ein benötigtes Copilot-Werkzeug ist aktuell nicht verfügbar.',
    })
  })

  it('rejects listed tools whose runtime metadata does not bind the ProductOperation', async () => {
    getMcpTools.mockResolvedValueOnce({
      tools: [{
        type: 'function',
        function: { name: 'frequency_list', description: 'Frequency list' },
        read_only: true,
        concurrency_safe: true,
        runtime_metadata_status: 'verified',
        product_operation_ids: ['analysis.other_operation'],
        product_capability_ids: ['analysis.frequency'],
        product_effects: ['read'],
        requires_corpus_features: [],
      }],
      tool_statuses: [],
    })

    const store = useMcpToolsStore()
    await store.load()

    expect(store.runtimeDecisionForOperation({
      operationId: 'analysis.frequency.list',
      copilotTools: ['frequency_list'],
    })).toMatchObject({
      status: 'operation_mismatch',
      listedToolNames: ['frequency_list'],
      missingToolNames: [],
      misboundToolNames: ['frequency_list'],
      reason: 'Mindestens ein Copilot-Werkzeug passt nicht zur freigegebenen CandyConc-Funktion.',
    })
  })
})
