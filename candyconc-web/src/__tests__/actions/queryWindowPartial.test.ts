/**
 * BLOCKER c (KWIC-PLAIN-01) — window-partial honesty on the default unsorted
 * streaming path.
 *
 * The SSE wire is honest: the `count` event carries the full canonical total
 * (e.g. 55550 for `[word=".*"]`), and the stream truncates the displayed window
 * after `streamWindow` rows (hasMore=true, more pages available). Before the fix
 * the `query/execute` handler treated "exact total known" as "result complete"
 * and rendered a plain "N Treffer" over a truncated window — the count
 * contradicting the page beneath it and no `(partiell)` marker / load-more cue.
 *
 * After the fix a truncated default search stays PARTIAL (StatusBar / KwicTable
 * show "≥ N (partiell)") while the exact total is preserved (totalKnown stays
 * true) and load-more is armed. A result that fully fits one window stays exact.
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

describe('query/execute default-unsorted window-partial honesty', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('keeps a truncated default search PARTIAL even when the count is exact', async () => {
    // The count event delivers the FULL canonical total up front; the stream then
    // overflows the UI window (streamWindow min = 200) so stopEarly fires.
    ;(api.executeQueryStreaming as ReturnType<typeof vi.fn>).mockImplementation(
      async function* () {
        yield { type: 'count', total: 55550, partial: false, elapsed_ms: 1 }
        // 300 hits > streamWindow(200) -> handler stops early mid-stream.
        const hits = Array.from({ length: 300 }, (_, i) => makeHit(i))
        yield { type: 'batch', hits }
        // A 'done' may or may not arrive after the client cancels; emit none.
      },
    )

    const queryStore = useQueryStore()
    queryStore.resetSort()

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'Haus' },
    })

    expect(result.success).toBe(true)
    // The exact canonical total is preserved...
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.totalHits).toBe(55550)
    // ...but the displayed WINDOW is partial: "≥ 55.550 (partiell)" + load-more.
    expect(queryStore.totalPartial).toBe(true)
    expect(queryStore.hasMore).toBe(true)
    expect(queryStore.nextOffset).toBeGreaterThan(0)
  })

  it('keeps a complete default search EXACT (fits one window, no partial marker)', async () => {
    ;(api.executeQueryStreaming as ReturnType<typeof vi.fn>).mockImplementation(
      async function* () {
        yield { type: 'count', total: 2, partial: false, elapsed_ms: 1 }
        yield { type: 'batch', hits: [makeHit(0), makeHit(1)] }
        yield { type: 'done', total: 2, partial: false, next_offset: null, query_time_ms: 2 }
      },
    )

    const queryStore = useQueryStore()
    queryStore.resetSort()

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'Haus' },
    })

    expect(result.success).toBe(true)
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.totalHits).toBe(2)
    expect(queryStore.totalPartial).toBe(false)
    expect(queryStore.hasMore).toBe(false)
  })

  it('preserves window-partial through the exact-count reconciliation (no count event)', async () => {
    // No 'count' event arrives during the stream, so totalKnown stays false and
    // the handler falls back to loadQueryCount (getQueryCount -> exact 55550).
    // The window was still truncated (stopEarly), so the exact count must NOT
    // wipe the partial marker.
    ;(api.executeQueryStreaming as ReturnType<typeof vi.fn>).mockImplementation(
      async function* () {
        const hits = Array.from({ length: 300 }, (_, i) => makeHit(i))
        yield { type: 'batch', hits }
      },
    )

    const queryStore = useQueryStore()
    queryStore.resetSort()

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'Haus' },
    })

    expect(result.success).toBe(true)
    expect(api.getQueryCount).toHaveBeenCalled()
    // Exact total resolved via the count fallback...
    expect(queryStore.totalKnown).toBe(true)
    expect(queryStore.totalHits).toBe(55550)
    // ...but the truncated window keeps the partial marker (not wiped).
    expect(queryStore.totalPartial).toBe(true)
    expect(queryStore.hasMore).toBe(true)
  })
})
