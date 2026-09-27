import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import ChatMessage from '@/components/copilot/ChatMessage.vue'
import ToolCallResult from '@/components/copilot/ToolCallResult.vue'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { ProductCapabilityContract } from '@/api/client'

const { dispatch, getMcpTools } = vi.hoisted(() => ({
  dispatch: vi.fn(async () => ({ success: true })),
  getMcpTools: vi.fn(),
}))

vi.mock('@/composables/useActions', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables/useActions')>()
  return { ...actual, useDispatch: () => ({ dispatch }) }
})

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  return { ...actual, getMcpTools: (...args: unknown[]) => getMcpTools(...args) }
})

const CONTROL = {
  name: 'deutung_abgeben',
  role: 'turn_control',
  label: 'Untersuchung abgeschlossen',
  description: 'Der Copilot beendet die Werkzeugphase und übergibt seine Deutung an die Antwort.',
}

function contract(): ProductCapabilityContract {
  return {
    version: 'product-capabilities-v1',
    scope: 'x',
    fingerprint_sha256: 'a'.repeat(64),
    cqlf_capability_contract: { version: 'v', current_level: '2-', fingerprint_sha256: 'b'.repeat(64) },
    capabilities: [
      { id: 'query.kwic', title: 'KWIC', area: 'query', maturity: 'stable', visibility: 'first_class_ui', backend_routes: [], backend_route_descriptors: [], operations: [], frontend_evidence: [], action_types: [], copilot_tools: ['run_cqlf_query'], preconditions: [], requires_corpus_features: [], limits: [] },
      { id: 'analysis.collocations', title: 'Kollokationen', area: 'analysis', maturity: 'stable', visibility: 'first_class_ui', backend_routes: [], backend_route_descriptors: [], operations: [], frontend_evidence: [], action_types: [], copilot_tools: ['collocate_stats'], preconditions: [], requires_corpus_features: [], limits: [] },
    ],
    copilot_control_tools: [CONTROL],
  } as unknown as ProductCapabilityContract
}

function seed() {
  const pinia = createPinia()
  setActivePinia(pinia)
  const caps = useProductCapabilitiesStore()
  caps.contract = contract()
  caps.status = 'ready'
  return pinia
}

const message = {
  id: 'm1',
  role: 'assistant' as const,
  content: 'Frieden steht nah [[beleg:E_collocate_stats_2]], und die Belege [[beleg:E_run_cqlf_query_1]].',
  timestamp: 1,
  evidence: [
    { id: 'E_run_cqlf_query_1', tool: 'run_cqlf_query', query: '{"corpus": "sotu_en", "limit": 3, "query": "freedom"}', status: 'success' },
    { id: 'E_collocate_stats_2', tool: 'collocate_stats', query: '{"term": "freedom", "window": 5}', status: 'success' },
  ],
  toolCalls: [
    { id: 't1', name: 'collocate_stats', arguments: { term: 'peace', window: 5 }, status: 'success' as const, result: { rows: [] } },
    { id: 't2', name: 'collocate_stats', arguments: { term: 'freedom', window: 5 }, status: 'success' as const, result: { rows: [] } },
    { id: 't3', name: 'run_cqlf_query', arguments: { corpus: 'sotu_en', limit: 3, query: 'freedom' }, status: 'success' as const, result: { total: 495, rows: [] } },
  ],
}

describe('Evidence chips lead to their evidence', () => {
  beforeEach(() => {
    dispatch.mockClear()
    getMcpTools.mockReset()
    getMcpTools.mockResolvedValue({ tools: [], tool_statuses: [] })
  })

  it('opens the query of a search tool in the KWIC', async () => {
    const pinia = seed()
    const wrapper = mount(ChatMessage, { props: { message }, global: { plugins: [pinia], stubs: { ToolCallResult: true } } })
    const chips = wrapper.findAll('.ev-chip')
    await chips[1]!.trigger('click')
    await vi.waitFor(() => expect(dispatch).toHaveBeenCalledTimes(1))
    const action = dispatch.mock.calls[0]![0] as { type: string; payload: { term: string; filters?: { corpus?: string } } }
    expect(action.type).toBe('query/execute')
    expect(action.payload.term).toBe('freedom')
    expect(action.payload.filters?.corpus).toBe('sotu_en')
  })

  it('marks the cited tool card of any other tool', async () => {
    const pinia = seed()
    const wrapper = mount(ChatMessage, { props: { message }, global: { plugins: [pinia], stubs: { ToolCallResult: true } } })
    await wrapper.findAll('.ev-chip')[0]!.trigger('click')
    await vi.waitFor(() => expect(wrapper.find('[data-tool-call-id="t2"]').classes()).toContain('tool-call-cited'))
    expect(dispatch).not.toHaveBeenCalled()
    expect(wrapper.find('[data-tool-call-id="t1"]').classes()).not.toContain('tool-call-cited')
  })
})

describe('Turn-control tool card', () => {
  it('shows deutung_abgeben as the end of the investigation, not as blocked', async () => {
    getMcpTools.mockResolvedValue({
      tools: [],
      tool_statuses: [{ name: 'deutung_abgeben', status: 'unclaimed_registered', dispatchable: false, reason: 'x' }],
    })
    const pinia = seed()
    const wrapper = mount(ToolCallResult, {
      props: { toolCall: { id: 'c1', name: 'deutung_abgeben', arguments: { entwurf: 'Text' }, status: 'success', result: { status: 'success' } } },
      global: { plugins: [pinia] },
    })
    await flushPromises()
    const text = wrapper.text()
    expect(text).toContain('Untersuchung abgeschlossen')
    expect(text).toContain('beendet die Werkzeugphase')
    expect(text).not.toContain('gesperrt')
    expect(wrapper.find('.tool-error').exists()).toBe(false)
  })
})
