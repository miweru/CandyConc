/**
 * FIX 1 (round 5) — co-occurrence KWIC completeness honesty.
 *
 * The co-occurrence GET path in `query/execute` must derive completeness the
 * SAME way the sorted GET path does: a bounded window (backend `truncated` OR a
 * `next_offset` signalling more hits) is PARTIAL, not the complete population.
 * Before the fix the path hard-coded `setResults(..., known=true, partial=false)`
 * and `setTotalHits(total, true, false)`, so StatusBar rendered "N Treffer" over a
 * bounded page (a count that contradicts the rows beneath it) and offered no
 * load-more affordance.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

const loadCollocateKwic = vi.fn()

vi.mock('@/composables/useCollocationOperations', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/composables/useCollocationOperations')>()
  return {
    ...actual,
    useCollocationOperations: () => ({ loadCollocateKwic }),
  }
})

vi.mock('@/api/client', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/api/client')>()
  const route = (path: string, method: string) => ({
    path,
    methods: [method],
    mutates: false,
    requires_corpus_features: [],
    access: 'public',
    required_role: null,
    transport: 'http',
  })
  const operation = (id: string, path: string, method: string, label: string) => ({
    id,
    capability_id: 'query.kwic',
    label,
    description: '',
    route: route(path, method),
    effects: ['read'],
    handler_key: id.replaceAll('.', '_'),
    surface_slot: id,
    priority: 10,
  })
  const kwicRoutes = [
    route('/api/v1/query', 'GET'),
    route('/api/v1/query/stream', 'GET'),
    route('/api/v1/query/count', 'GET'),
  ]
  const coKwicRoute = route('/api/v1/analysis/collocates/kwic', 'POST')
  const coOperation = {
    id: 'analysis.collocations.kwic',
    capability_id: 'analysis.collocations',
    label: 'Co-KWIC',
    description: '',
    route: coKwicRoute,
    effects: ['read'],
    handler_key: 'analysis_collocations_kwic',
    surface_slot: 'analysis.collocations.kwic',
    priority: 10,
  }
  return {
    ...actual,
    getProductCapabilities: vi.fn(async () => ({
      version: 'product-capabilities-v1',
      scope: 'CandyConc product capability contract',
      fingerprint_sha256: 'a'.repeat(64),
      cqlf_capability_contract: {
        version: 'cqlf-capabilities-v1',
        current_level: '2-',
        fingerprint_sha256: 'b'.repeat(64),
      },
      capabilities: [
        {
          id: 'query.kwic',
          title: 'KWIC',
          area: 'query',
          maturity: 'stable',
          visibility: 'first_class_ui',
          backend_routes: kwicRoutes.map((item) => item.path),
          backend_route_descriptors: kwicRoutes,
          operations: [
            operation('query.kwic.page', '/api/v1/query', 'GET', 'KWIC-Trefferseite'),
            operation('query.kwic.stream', '/api/v1/query/stream', 'GET', 'KWIC-Stream'),
            operation('query.kwic.count', '/api/v1/query/count', 'GET', 'KWIC-Zählung'),
          ],
          frontend_evidence: [],
          action_types: ['query/execute', 'query/loadMore'],
          copilot_tools: [],
          preconditions: [],
          limits: [],
          requires_corpus_features: [],
        },
        {
          id: 'analysis.collocations',
          title: 'Kollokationen',
          area: 'analysis',
          maturity: 'stable',
          visibility: 'first_class_ui',
          backend_routes: [coKwicRoute.path],
          backend_route_descriptors: [coKwicRoute],
          operations: [coOperation],
          frontend_evidence: [],
          action_types: ['query/execute', 'query/loadMore'],
          copilot_tools: [],
          preconditions: [],
          limits: [],
          requires_corpus_features: [],
        },
      ],
    })),
    getMetaSchema: vi.fn(async () => ({ fields: [] })),
  }
})

import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useQueryStore } from '@/stores/query'

const CO_TERM = 'co(term="Haus", collocate="steht", window=5, within_sentence=true)'

const hit = {
  position: 7,
  left: 'das',
  match: 'Haus',
  right: 'steht',
  doc_id: '1',
  doc_title: 'Doc 1',
  metadata: {},
  collocate_offsets: [],
}

describe('query/execute co-occurrence completeness honesty', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('marks a bounded co-occurrence window (next_offset) as PARTIAL with load-more', async () => {
    loadCollocateKwic.mockResolvedValueOnce({
      hits: [hit],
      total: 1,
      query_time_ms: 2,
      next_offset: 1, // more hits beyond the returned window
      truncated: false,
    })

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: CO_TERM },
    })

    expect(result.success).toBe(true)
    const queryStore = useQueryStore()
    // The leak: total presented as complete/known. After the fix it is honest.
    expect(queryStore.totalPartial).toBe(true)
    // The route counts every node hit before paging: the total is exact, only
    // the window is partial (erprobung B11).
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.countIsLowerBound).toBe(false)
    // Load-more affordance is armed from the backend next_offset.
    expect(queryStore.hasMore).toBe(true)
    expect(queryStore.nextOffset).toBe(1)
  })

  it('marks a bounded co-occurrence window (truncated flag) as PARTIAL', async () => {
    loadCollocateKwic.mockResolvedValueOnce({
      hits: [hit],
      total: 1,
      query_time_ms: 2,
      next_offset: null,
      truncated: true,
    })

    await actionBus.dispatch({ type: 'query/execute', payload: { term: CO_TERM } })

    const queryStore = useQueryStore()
    expect(queryStore.totalPartial).toBe(true)
    // The route counts every node hit before paging: the total is exact, only
    // the window is partial (erprobung B11).
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.countIsLowerBound).toBe(false)
  })

  it('keeps a complete co-occurrence result honest (no next_offset, not truncated)', async () => {
    loadCollocateKwic.mockResolvedValueOnce({
      hits: [hit],
      total: 1,
      query_time_ms: 2,
      next_offset: null,
      truncated: false,
    })

    await actionBus.dispatch({ type: 'query/execute', payload: { term: CO_TERM } })

    const queryStore = useQueryStore()
    expect(queryStore.totalPartial).toBe(false)
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.hasMore).toBe(false)
    expect(queryStore.nextOffset).toBe(0)
  })

  it('keeps Co-KWIC load-more partial while the backend still exposes another page', async () => {
    loadCollocateKwic.mockResolvedValueOnce({
      hits: [hit],
      total: 3,
      query_time_ms: 2,
      next_offset: 1,
      truncated: false,
    })

    await actionBus.dispatch({ type: 'query/execute', payload: { term: CO_TERM } })
    loadCollocateKwic.mockResolvedValueOnce({
      hits: [{ ...hit, position: 8 }],
      total: 3,
      query_time_ms: 2,
      next_offset: 2,
      truncated: false,
    })

    const result = await actionBus.dispatch({ type: 'query/loadMore', payload: {} })

    expect(result.success).toBe(true)
    const queryStore = useQueryStore()
    expect(queryStore.results).toHaveLength(2)
    expect(queryStore.totalPartial).toBe(true)
    // The route counts every node hit before paging: the total is exact, only
    // the window is partial (erprobung B11).
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.countIsLowerBound).toBe(false)
    expect(queryStore.hasMore).toBe(true)
    expect(queryStore.nextOffset).toBe(2)
  })

  it('clears Co-KWIC partiality only after the loaded window is complete', async () => {
    loadCollocateKwic.mockResolvedValueOnce({
      hits: [hit],
      total: 2,
      query_time_ms: 2,
      next_offset: 1,
      truncated: false,
    })

    await actionBus.dispatch({ type: 'query/execute', payload: { term: CO_TERM } })
    loadCollocateKwic.mockResolvedValueOnce({
      hits: [{ ...hit, position: 8 }],
      total: 2,
      query_time_ms: 2,
      next_offset: null,
      truncated: false,
    })

    await actionBus.dispatch({ type: 'query/loadMore', payload: {} })

    const queryStore = useQueryStore()
    expect(queryStore.results).toHaveLength(2)
    expect(queryStore.totalPartial).toBe(false)
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.hasMore).toBe(false)
    expect(queryStore.nextOffset).toBe(0)
  })
})
