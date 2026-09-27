/**
 * KWIC-Sort routing (release re-audit finding 2):
 *
 * The backend stream endpoint /query/stream rejects sort_by with 400, so the
 * `query/execute` handler must route sorted searches to the sorting GET
 * /query endpoint (api.executeQuery) and keep the SSE stream for unsorted
 * searches — without ever passing sort params to the stream.
 */
import { describe, it, expect, beforeAll, beforeEach, vi, type Mock } from 'vitest'
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
    executeQuery: vi.fn(async () => ({
      hits: [
        {
          position: 7,
          left: 'das',
          match: 'Haus',
          right: 'steht',
          doc_id: '1',
          doc_title: 'Doc 1',
        },
      ],
      total: 1,
      query_time_ms: 3,
      next_offset: null,
      truncated: false,
      sortApproximate: false,
    })),
    executeQueryStreaming: vi.fn(async function* () {
      yield { type: 'count', total: 1, partial: false, elapsed_ms: 1 }
      yield {
        type: 'batch',
        hits: [
          {
            position: 7,
            left: 'das',
            match: 'Haus',
            right: 'steht',
            doc_id: '1',
            doc_title: 'Doc 1',
          },
        ],
      }
      yield { type: 'done', total: 1, partial: false, next_offset: null, query_time_ms: 2 }
    }),
    getQueryCount: vi.fn(async () => ({ status: 'ready', total: 1, partial: false })),
    getMetaSchema: vi.fn(async () => ({ fields: [] })),
  }
})

import * as api from '@/api/client'
import { actionBus } from '@/actions/bus'
import { registerActionHandlers } from '@/actions/handlers'
import { useQueryStore } from '@/stores/query'
import { useDocsetStore } from '@/stores/docset'
import { useUiStore } from '@/stores/ui'

describe('query/execute KWIC sort routing', () => {
  beforeAll(() => {
    setActivePinia(createPinia())
    registerActionHandlers()
  })

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('routes sorted searches to GET /query (executeQuery), not the stream', async () => {
    const queryStore = useQueryStore()
    queryStore.setSort('1L', 'desc')

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'Haus' },
    })

    expect(result.success).toBe(true)
    expect(api.executeQuery).toHaveBeenCalledTimes(1)
    expect(api.executeQueryStreaming).not.toHaveBeenCalled()

    const params = (api.executeQuery as Mock).mock.calls[0][0]
    expect(params).toMatchObject({ term: 'Haus', sortBy: '1L', sortDir: 'desc' })
    expect(queryStore.results).toHaveLength(1)
    expect(queryStore.results[0]).toMatchObject({ match: 'Haus', docId: '1' })
  })

  it('keeps unsorted searches on the stream and never sends sort params', async () => {
    const queryStore = useQueryStore()
    queryStore.resetSort()

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'Haus' },
    })

    expect(result.success).toBe(true)
    expect(api.executeQueryStreaming).toHaveBeenCalledTimes(1)
    expect(api.executeQuery).not.toHaveBeenCalled()

    const streamParams = (api.executeQueryStreaming as Mock).mock.calls[0][0]
    expect(streamParams).not.toHaveProperty('sortBy')
    expect(streamParams).not.toHaveProperty('sortDir')
    expect(streamParams).not.toHaveProperty('sort_by')
  })

  it('keeps a metadata-built scope when the researcher changes the query', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('alter Suchterm')
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-meta'
    docsetStore.activeDocsetOrigin = { kind: 'meta' }
    docsetStore.activeFilterSpec = { register: ['Presse'] }
    docsetStore.isDirty = false

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'neuer Suchterm' },
    })

    expect(result.success).toBe(true)
    expect(api.executeQueryStreaming).toHaveBeenCalledTimes(1)
    const streamParams = (api.executeQueryStreaming as Mock).mock.calls[0][0]
    expect(streamParams).toMatchObject({ term: 'neuer Suchterm', docsetId: 'docset-meta' })
    expect(docsetStore.isDirty).toBe(false)
  })

  it('rebuilds a query-built scope before running a different query', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('alter Suchterm')
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-alt'
    docsetStore.activeDocsetOrigin = { kind: 'search', query: 'alter Suchterm' }
    docsetStore.isDirty = false
    const rebuild = vi.spyOn(docsetStore, 'buildDocset').mockImplementation(async (_force, term) => {
      docsetStore.activeDocsetId = 'docset-neu'
      docsetStore.activeDocsetOrigin = { kind: 'search', query: term ?? '' }
      docsetStore.isDirty = false
      return true
    })

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'neuer Suchterm' },
    })

    expect(result.success).toBe(true)
    expect(rebuild).toHaveBeenCalledWith(true, 'neuer Suchterm')
    const streamParams = (api.executeQueryStreaming as Mock).mock.calls[0][0]
    expect(streamParams).toMatchObject({ term: 'neuer Suchterm', docsetId: 'docset-neu' })
  })

  it('fails closed when rebuilding a changed query scope fails', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('alter Suchterm')
    const docsetStore = useDocsetStore()
    docsetStore.activeDocsetId = 'docset-alt'
    docsetStore.activeDocsetOrigin = { kind: 'search', query: 'alter Suchterm' }
    docsetStore.error = 'Docset-Bau fehlgeschlagen'
    const rebuild = vi.spyOn(docsetStore, 'buildDocset').mockResolvedValue(false)

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'neuer Suchterm' },
    })

    expect(result.success).toBe(false)
    expect(result.error).toBe('scope_rebuild_failed')
    expect(rebuild).toHaveBeenCalledWith(true, 'neuer Suchterm')
    expect(api.executeQueryStreaming).not.toHaveBeenCalled()
  })

  it('keeps the active subcorpus scope by resetting unsupported KWIC sorting instead of dropping the docset', async () => {
    const queryStore = useQueryStore()
    queryStore.setTerm('Haus')
    queryStore.setSort('1L', 'asc')
    const docsetStore = useDocsetStore()
    await docsetStore.applySnapshot({
      corpus: 'default',
      docsetId: 'docset-scope',
      stats: { docCount: 2, hitDocCount: 1, refDocCount: 0, tokenCount: 20 },
      filters: { prompting_method: [], model: [], register: [], source: [] },
      includeAi: true,
      includeHuman: true,
    })
    const uiStore = useUiStore()
    const toastSpy = vi.spyOn(uiStore, 'showToast')

    const result = await actionBus.dispatch({
      type: 'query/execute',
      payload: { term: 'Haus' },
    })

    expect(result.success).toBe(true)
    expect(api.executeQuery).not.toHaveBeenCalled()
    expect(api.executeQueryStreaming).toHaveBeenCalledTimes(1)
    expect(queryStore.sortBy).toBeNull()
    expect(toastSpy).toHaveBeenCalledWith(
      'Sortierung ist mit aktivem Subkorpus nicht verfügbar. Treffer in Korpusreihenfolge',
      'warning',
    )
    const streamParams = (api.executeQueryStreaming as Mock).mock.calls[0][0]
    expect(streamParams).toMatchObject({ term: 'Haus', docsetId: 'docset-scope' })
    expect(streamParams).not.toHaveProperty('sortBy')
    expect(streamParams).not.toHaveProperty('sortDir')
  })

  it('routes sorted pagination (query/loadMore) through GET /query as well', async () => {
    const queryStore = useQueryStore()
    queryStore.setSort('node', 'asc')
    queryStore.setTerm('Haus')
    queryStore.setResults(
      [
        {
          position: 7,
          left: 'das',
          match: 'Haus',
          right: 'steht',
          docId: '1',
        },
      ],
      10,
      true,
      false
    )
    queryStore.setHasMore(true)
    queryStore.setNextOffset(1)

    const result = await actionBus.dispatch({
      type: 'query/loadMore',
      payload: {},
    })

    expect(result.success).toBe(true)
    expect(api.executeQuery).toHaveBeenCalledTimes(1)
    expect(api.executeQueryStreaming).not.toHaveBeenCalled()
    const params = (api.executeQuery as Mock).mock.calls[0][0]
    expect(params).toMatchObject({ term: 'Haus', sortBy: 'node', sortDir: 'asc', offset: 1 })
  })
  it('emits caseInsensitive = !caseSensitive on the streaming path (D6)', async () => {
    const queryStore = useQueryStore()
    queryStore.resetSort()
    queryStore.setCaseSensitive(false) // UI default → insensitive matching

    await actionBus.dispatch({ type: 'query/execute', payload: { term: 'Haus' } })

    const streamParams = (api.executeQueryStreaming as Mock).mock.calls[0][0]
    expect(streamParams.caseInsensitive).toBe(true)
  })

  it('emits caseInsensitive = false when caseSensitive is enabled (sorted GET path)', async () => {
    const queryStore = useQueryStore()
    queryStore.setSort('1L', 'asc')
    queryStore.setCaseSensitive(true)

    await actionBus.dispatch({ type: 'query/execute', payload: { term: 'Haus' } })

    const params = (api.executeQuery as Mock).mock.calls[0][0]
    expect(params.caseInsensitive).toBe(false)
  })

  it('uses backend next_offset for sorted pagination state', async () => {
    ;(api.executeQuery as Mock).mockResolvedValueOnce({
      hits: [
        {
          position: 8,
          left: 'ein',
          match: 'Haus',
          right: 'steht',
          doc_id: '2',
        },
      ],
      total: 1,
      query_time_ms: 3,
      next_offset: 4,
      truncated: true,
      sortApproximate: false,
    })
    const queryStore = useQueryStore()
    queryStore.setSort('node', 'asc')
    queryStore.setTerm('Haus')
    queryStore.setResults(
      [
        { position: 7, left: 'das', match: 'Haus', right: 'steht', docId: '1' },
      ],
      10,
      false,
      true
    )
    queryStore.setHasMore(true)
    queryStore.setNextOffset(2)

    const result = await actionBus.dispatch({ type: 'query/loadMore', payload: {} })

    expect(result.success).toBe(true)
    expect(queryStore.hasMore).toBe(true)
    expect(queryStore.nextOffset).toBe(4)
  })

})
