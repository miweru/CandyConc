/**
 * REGRESSED GUARD (KWIC-PLAIN-LOADMORE-PARTIAL-01) — window-partial honesty must
 * survive the `query/loadMore` exact-count reconciliation, the same way it does
 * on the initial `query/execute` render.
 *
 * The initial path (handlers.ts ~:1050) captures `windowTruncated =
 * queryStore.hasMore` before its count fallback and passes it to setTotalHits, so
 * an exact total over a truncated window still renders "≥ N (partiell)". The
 * load-more path (~:1528) used to hardcode setTotalHits(total, true, false),
 * wiping the partial marker after the first load-more even though hasMore=true
 * and only a fraction of rows are visible. This test pins the symmetric
 * behaviour: after a load-more that overflows the window, an exact count keeps
 * the partial marker; a genuinely-complete result stays exact.
 */
import { describe, it, expect, beforeAll, beforeEach, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

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
      ],
    })),
    executeQueryStreaming: vi.fn(),
    getQueryCount: vi.fn(async () => ({ status: 'ready', total: 55550, partial: false })),
    getMetaSchema: vi.fn(async () => ({ fields: [] })),
  }
})

import * as api from '@/api/client'
import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useQueryStore } from '@/stores/query'

function makeHit(i: number) {
  return {
    position: i,
    left: 'das',
    match: 'Haus',
    right: 'steht',
    doc_id: String(i),
    doc_title: `Doc ${i}`,
  }
}

// Arrange a store as though one page is already loaded and more is pending:
// hasMore=true, a non-zero offset. `totalPartial` seeds the streaming loop's
// countPartial; pass it so callers control whether the count fallback fires.
function primeLoadMoreState(totalPartial: boolean) {
  const queryStore = useQueryStore()
  queryStore.resetSort()
  queryStore.setTerm('Haus')
  queryStore.appendResults(Array.from({ length: 200 }, (_, i) => makeHit(i)))
  queryStore.setTotalHits(200, false, totalPartial)
  queryStore.setHasMore(true)
  queryStore.setNextOffset(200)
  return queryStore
}

describe('query/loadMore window-partial honesty', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('keeps the partial marker after load-more when the window is still truncated', async () => {
    // The next page also overflows the UI window (stopEarly), and no 'count'/'done'
    // event resolves the total, so the handler falls back to loadQueryCount which
    // returns an EXACT 55550. The window is still truncated -> partial must hold.
    ;(api.executeQueryStreaming as ReturnType<typeof vi.fn>).mockImplementation(
      async function* () {
        const hits = Array.from({ length: 300 }, (_, i) => makeHit(200 + i))
        yield { type: 'batch', hits }
      },
    )

    const queryStore = primeLoadMoreState(true)

    const result = await actionBus.dispatch({
      type: 'query/loadMore',
      payload: { direction: 'next' },
    })

    expect(result.success).toBe(true)
    expect(api.getQueryCount).toHaveBeenCalled()
    // Exact total resolved...
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.totalHits).toBe(55550)
    // ...but the still-truncated window keeps "≥ N (partiell)" + load-more. The
    // pre-fix hardcoded setTotalHits(total, true, false) wiped this to a bare
    // exact "N Treffer" over a partial window.
    expect(queryStore.totalPartial).toBe(true)
    expect(queryStore.hasMore).toBe(true)
  })

  it('keeps the partial marker when a mid-stream count event resolves over a still-truncated window', async () => {
    // The leak the round-8 parity probe caught: a mid-stream `count` event
    // (exact, partial=false) set totalPartial=false with no hasMore guard, and the
    // `done` event's reconciliation only ran when !totalKnown -> the marker stayed
    // wiped even though `done` keeps hasMore=true (next_offset set).
    // Small batch (does NOT fill the UI window -> no stopEarly break), so the
    // mid-stream `count` + `done` events are actually consumed; `done` keeps the
    // window truncated via next_offset.
    ;(api.executeQueryStreaming as ReturnType<typeof vi.fn>).mockImplementation(
      async function* () {
        yield { type: 'batch', hits: [makeHit(200), makeHit(201)] }
        yield { type: 'count', total: 55550, partial: false }
        yield { type: 'done', total: 55550, partial: true, next_offset: 502, query_time_ms: 3 }
      },
    )

    const queryStore = primeLoadMoreState(false)

    const result = await actionBus.dispatch({
      type: 'query/loadMore',
      payload: { direction: 'next' },
    })

    expect(result.success).toBe(true)
    // The exact total came from the mid-stream count event (no fallback needed)...
    expect(api.getQueryCount).not.toHaveBeenCalled()
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.totalHits).toBe(55550)
    // ...and the still-truncated window keeps the partial marker.
    expect(queryStore.hasMore).toBe(true)
    expect(queryStore.totalPartial).toBe(true)
  })

  it('drops the partial marker when a mid-stream count event is followed by a complete done', async () => {
    // The other direction: an exact mid-stream count, then `done` completes the
    // window (next_offset=null) -> hasMore=false -> the marker must clear so a
    // complete result is not mislabelled "(partiell)".
    ;(api.executeQueryStreaming as ReturnType<typeof vi.fn>).mockImplementation(
      async function* () {
        yield { type: 'batch', hits: [makeHit(200), makeHit(201)] }
        yield { type: 'count', total: 202, partial: false }
        yield { type: 'done', total: 202, partial: false, next_offset: null, query_time_ms: 2 }
      },
    )

    const queryStore = primeLoadMoreState(false)

    const result = await actionBus.dispatch({
      type: 'query/loadMore',
      payload: { direction: 'next' },
    })

    expect(result.success).toBe(true)
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.totalHits).toBe(202)
    expect(queryStore.hasMore).toBe(false)
    expect(queryStore.totalPartial).toBe(false)
  })

  it('renders an exact total when the stream completes (done, no count fallback)', async () => {
    // The natural complete path: the stream's `done` carries next_offset=null, so
    // hasMore flips to false and the total resolves exactly WITHOUT hitting the
    // count fallback — the displayed window is the whole result, no partial marker.
    ;(api.executeQueryStreaming as ReturnType<typeof vi.fn>).mockImplementation(
      async function* () {
        yield { type: 'batch', hits: [makeHit(200), makeHit(201)] }
        yield { type: 'done', total: 202, partial: false, next_offset: null, query_time_ms: 2 }
      },
    )

    // Seed totalPartial=false so the streaming loop's countPartial starts clean
    // and the `done` event can mark the result complete (totalKnown=true).
    const queryStore = primeLoadMoreState(false)

    const result = await actionBus.dispatch({
      type: 'query/loadMore',
      payload: { direction: 'next' },
    })

    expect(result.success).toBe(true)
    // The exact total comes from the stream's done event, not the count fallback.
    expect(api.getQueryCount).not.toHaveBeenCalled()
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.totalHits).toBe(202)
    expect(queryStore.totalPartial).toBe(false)
    expect(queryStore.hasMore).toBe(false)
  })
})
