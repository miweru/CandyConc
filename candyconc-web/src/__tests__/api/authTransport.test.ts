import { describe, it, expect, beforeEach, afterEach, vi, type Mock } from 'vitest'
import {
  executeQuery,
  executeQueryStreaming,
  executeQueryStreamingToResult,
  getMetaSchema,
  getLexiconSuggestions,
  analyseQuery,
  createCollocatesDiffJob,
  getKeyness,
  semanticSearch,
  semanticSearchWithMeta,
  SemanticSearchError,
} from '@/api/client'
import {
  clearAuthToken,
  ensureDevToken,
  getAuthToken,
  setAuthToken,
  startAuthBootstrap,
  withAuthHeaders,
} from '@/api/auth'
import { streamCopilotMessage } from '@/api/sse'

function mockSseResponse(payload = 'event: done\ndata: {"total":0}\n\n') {
  return Promise.resolve(new Response(payload, {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

function mockJsonResponse(payload: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json', ...headers },
  }))
}

function mockJsonStatusResponse(status: number, payload: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  }))
}

function mockSseChunkedResponse(chunks: string[]) {
  const encoder = new TextEncoder()
  return Promise.resolve(new Response(new ReadableStream({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)))
      controller.close()
    },
  }), {
    status: 200,
    headers: { 'Content-Type': 'text/event-stream' },
  }))
}

function fetchMock() {
  return globalThis.fetch as Mock
}

function headersFromFetchCall(index = 0): Headers {
  const init = fetchMock().mock.calls[index]?.[1] as RequestInit | undefined
  return new Headers(init?.headers)
}

describe('API auth transport', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('fetch', vi.fn(() => mockSseResponse()))
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
    clearAuthToken()
  })

  afterEach(() => {
    clearAuthToken()
  })

  it('prefers the in-memory token over web storage and mirrors it to sessionStorage', () => {
    ;(window.localStorage.getItem as Mock).mockReturnValue('legacy-storage-token')

    setAuthToken(' runtime-token ')

    expect(getAuthToken()).toBe('runtime-token')
    expect(window.sessionStorage.getItem('auth_token')).toBe('runtime-token')
    expect(withAuthHeaders().get('Authorization')).toBe('Bearer runtime-token')
  })

  it('falls back to sessionStorage before legacy localStorage', () => {
    ;(window.localStorage.getItem as Mock).mockReturnValue('legacy-storage-token')
    window.sessionStorage.setItem('auth_token', 'session-token')

    expect(getAuthToken()).toBe('session-token')
    window.sessionStorage.removeItem('auth_token')
    expect(getAuthToken()).toBe('session-token')
  })

  it('clearAuthToken drops memory, sessionStorage and legacy localStorage copies', () => {
    setAuthToken('runtime-token')
    clearAuthToken()

    expect(window.sessionStorage.getItem('auth_token')).toBeNull()
    expect(window.localStorage.removeItem).toHaveBeenCalledWith('auth_token')
    expect(getAuthToken()).toBeNull()
  })

  it('adds a Bearer header from the existing auth token storage', () => {
    ;(window.localStorage.getItem as Mock).mockReturnValue(' release-token ')

    const headers = withAuthHeaders({ 'Content-Type': 'application/json' })

    expect(window.localStorage.getItem).toHaveBeenCalledWith('auth_token')
    expect(headers.get('Authorization')).toBe('Bearer release-token')
    expect(headers.get('Content-Type')).toBe('application/json')
    expect(window.sessionStorage.getItem('auth_token')).toBe('release-token')
    expect(window.localStorage.removeItem).toHaveBeenCalledWith('auth_token')
  })

  it('does not add Authorization when no auth token exists', () => {
    const headers = withAuthHeaders({ Accept: 'text/event-stream' })

    expect(headers.has('Authorization')).toBe(false)
    expect(headers.get('Accept')).toBe('text/event-stream')
  })

  it('does not persist a dev token when the backend rejects the hidden dev-token endpoint', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonStatusResponse(404, { detail: 'Not available' }))

    await ensureDevToken()

    expect(fetchMock()).toHaveBeenCalledWith('/api/v1/auth/dev-token', expect.objectContaining({
      headers: { Accept: 'application/json' },
    }))
    expect(getAuthToken()).toBeNull()
    expect(window.sessionStorage.getItem('auth_token')).toBeNull()
  })

  it('replaces a stale local dev token before ky and raw fetch requests', async () => {
    let resolveDevToken!: () => void
    fetchMock().mockImplementation((input: RequestInfo | URL) => {
      const url = String(input instanceof Request ? input.url : input)
      if (url.includes('/api/v1/auth/session')) {
        return mockJsonResponse({
          authenticated: false,
          token_present: true,
          rbac_enabled: false,
          dev_token_available: true,
          release_mode: false,
        })
      }
      if (url.endsWith('/api/v1/auth/dev-token')) {
        return new Promise<Response>((resolve) => {
          resolveDevToken = () => {
            resolve(new Response(JSON.stringify({ token: 'dev-token' }), {
              status: 200,
              headers: { 'Content-Type': 'application/json' },
            }))
          }
        })
      }
      if (url.includes('/api/v1/analysis/meta_schema')) {
        return mockJsonResponse({
          schemaVersion: 1,
          corpus: 'demo',
          indexFingerprint: 'sha256:index',
          metadataSchemaHash: 'sha256:meta',
          metadataFields: [],
          warnings: [],
        })
      }
      if (url.includes('/api/v1/query/stream')) {
        return mockSseResponse()
      }
      return mockJsonStatusResponse(404, { detail: 'unexpected request' })
    })

    setAuthToken('stale-local-dev-token')
    const bootstrap = startAuthBootstrap()
    const schemaPromise = getMetaSchema({ corpus: 'demo' })
    const events: unknown[] = []
    const streamPromise = (async () => {
      for await (const event of executeQueryStreaming({ term: 'lemma', corpus: 'demo' })) {
        events.push(event)
      }
    })()

    await vi.waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(2))
    const sessionInput = fetchMock().mock.calls[0]?.[0]
    const sessionInit = fetchMock().mock.calls[0]?.[1] as RequestInit | undefined
    expect(String(sessionInput)).toContain('/api/v1/auth/session')
    expect(new Headers(sessionInit?.headers).get('Authorization')).toBe('Bearer stale-local-dev-token')
    expect(String(fetchMock().mock.calls[1]?.[0])).toBe('/api/v1/auth/dev-token')

    resolveDevToken()
    await bootstrap
    await schemaPromise
    await streamPromise

    expect(fetchMock()).toHaveBeenCalledTimes(4)
    const kyCall = fetchMock().mock.calls.find(([input]) =>
      input instanceof Request && input.url.includes('/api/v1/analysis/meta_schema')
    )
    const streamCallIndex = fetchMock().mock.calls.findIndex(([input]) =>
      String(input).includes('/api/v1/query/stream')
    )
    const kyRequest = kyCall?.[0] as Request
    expect(kyRequest.url).toContain('/api/v1/analysis/meta_schema?corpus=demo')
    expect(kyRequest.headers.get('Authorization')).toBe('Bearer dev-token')
    expect(streamCallIndex).toBeGreaterThan(0)
    expect(headersFromFetchCall(streamCallIndex).get('Authorization')).toBe('Bearer dev-token')
    expect(events).toEqual([{ type: 'done', total: 0, partial: false, truncated: false, next_offset: null, query_time_ms: undefined }])
  })

  it('streams queries without token query parameters and sends Bearer auth', async () => {
    ;(window.localStorage.getItem as Mock).mockReturnValue('query-token')
    fetchMock().mockResolvedValueOnce(await mockSseResponse())

    const events = []
    for await (const event of executeQueryStreaming({ term: 'lemma', corpus: 'demo' })) {
      events.push(event)
    }

    const url = String(fetchMock().mock.calls[0]?.[0])
    expect(url).toContain('/api/v1/query/stream?')
    expect(url).toContain('term=lemma')
    expect(url).toContain('corpus=demo')
    expect(url).not.toContain('token=')
    expect(headersFromFetchCall().get('Authorization')).toBe('Bearer query-token')
    expect(headersFromFetchCall().get('Accept')).toBe('text/event-stream')
    expect(events).toEqual([{ type: 'done', total: 0, partial: false, truncated: false, next_offset: null, query_time_ms: undefined }])
  })

  it('surfaces backend 4xx details from query streams instead of generic HTTP status text', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonStatusResponse(422, {
      detail: 'CQL-Fehler: schließende Klammer fehlt',
    }))

    const events = []
    for await (const event of executeQueryStreaming({ term: 'cql:[word="Haus"' })) {
      events.push(event)
    }

    expect(events).toEqual([{
      type: 'error',
      error: 'CQL-Fehler: schließende Klammer fehlt',
    }])
  })

  it('parses backend query trace ids from streaming done events', async () => {
    fetchMock().mockResolvedValueOnce(await mockSseResponse(
      'event: done\ndata: {"total":1,"queryTraceId":"qtr-backend"}\n\n'
    ))

    const events = []
    for await (const event of executeQueryStreaming({ term: 'lemma' })) {
      events.push(event)
    }

    expect(events).toEqual([{
      type: 'done',
      total: 1,
      partial: false,
      truncated: false,
      next_offset: null,
      query_time_ms: undefined,
      backendQueryTraceId: 'qtr-backend',
    }])
  })

  it('parses snake_case backend query trace ids and propagates them to collected results', async () => {
    fetchMock().mockResolvedValueOnce(await mockSseResponse(
      'event: batch\ndata: [{"left":"","kw":"lemma","right":"","pos":1}]\n\n' +
      'event: done\ndata: {"total":1,"query_trace_id":"qtr-snake"}\n\n'
    ))

    const result = await executeQueryStreamingToResult({ term: 'lemma' })

    expect(result.hits).toHaveLength(1)
    expect(result.backendQueryTraceId).toBe('qtr-snake')
  })

  it('reads backend query trace ids from non-streaming query headers', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonResponse(
      [{ left: '', kw: 'lemma', right: '', pos: 1 }],
      { 'X-CandyConc-Query-Trace-Id': 'qtr-header' }
    ))

    const result = await executeQuery({ term: 'lemma' })
    const request = fetchMock().mock.calls[0]?.[0] as Request

    expect(request.url).toContain('/api/v1/query?term=lemma')
    expect(result.backendQueryTraceId).toBe('qtr-header')
  })

  it('sends non-streaming query offset/limit and reads backend next offset', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonResponse(
      [
        { left: '', kw: 'b', right: '', pos: 2 },
        { left: '', kw: 'c', right: '', pos: 3 },
      ],
      {
        'X-CandyConc-Query-Trace-Id': 'qtr-offset',
        'X-CandyConc-Truncated': 'true',
        'X-CandyConc-Next-Offset': '4',
        'X-CandyConc-Total': '12',
      }
    ))

    const result = await executeQuery({ term: 'lemma', offset: 2, limit: 2, sortBy: '1L', sortDir: 'desc' })
    const request = fetchMock().mock.calls[0]?.[0] as Request
    const url = new URL(request.url)

    expect(url.searchParams.get('term')).toBe('lemma')
    expect(url.searchParams.get('offset')).toBe('2')
    expect(url.searchParams.get('limit')).toBe('2')
    expect(url.searchParams.get('sort_by')).toBe('1L')
    expect(url.searchParams.get('sort_dir')).toBe('desc')
    expect(result.hits.map((hit) => hit.match)).toEqual(['b', 'c'])
    expect(result.total).toBe(12)
    expect(result.next_offset).toBe(4)
    expect(result.truncated).toBe(true)
    expect(result.backendQueryTraceId).toBe('qtr-offset')
  })

  it('fetches meta schema evidence with Bearer auth and corpus query only', async () => {
    ;(window.localStorage.getItem as Mock).mockReturnValue('meta-token')
    fetchMock().mockResolvedValueOnce(await mockJsonResponse({
      schemaVersion: 1,
      corpus: 'demo',
      indexFingerprint: 'sha256:index',
      metadataSchemaHash: 'sha256:meta',
      metadataFields: [],
      warnings: [],
    }))

    const schema = await getMetaSchema({ corpus: 'demo' })
    const request = fetchMock().mock.calls[0]?.[0] as Request

    expect(request.url).toContain('/api/v1/analysis/meta_schema?corpus=demo')
    expect(request.url).not.toContain('token=')
    expect(request.headers.get('Authorization')).toBe('Bearer meta-token')
    expect(schema.metadataSchemaHash).toBe('sha256:meta')
  })

  it('preserves CQL analysis warnings and diagnostics', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonResponse({
      errors: [],
      warnings: ['[cqlf.level2.quantifiers] guarded'],
      diagnostics: [
        { severity: 'warning', message: '[cqlf.level2.quantifiers] guarded', start: 4, end: 10, fixes: [] },
      ],
      suggestions: ['cql:[word="Hase"]'],
      hints: ['Token word'],
      kinds: ['complete'],
      spans: [],
      builder: { type: 'token' },
    }))

    const result = await analyseQuery('cql:[word="Has"]')

    expect(result.warnings).toEqual(['[cqlf.level2.quantifiers] guarded'])
    expect(result.diagnostics[0]).toMatchObject({ severity: 'warning', start: 4, end: 10 })
    expect(result.suggestions[0]).toMatchObject({ text: 'cql:[word="Hase"]', kind: 'complete' })
  })

  it('scopes CQL analysis to the selected corpus when provided', async () => {
    let body: unknown
    fetchMock().mockImplementationOnce(async (input: RequestInfo | URL) => {
      body = await (input as Request).clone().json()
      return mockJsonResponse({
        errors: [],
        warnings: [],
        diagnostics: [],
        suggestions: [],
        hints: [],
        kinds: [],
        spans: [],
        builder: null,
      })
    })

    await analyseQuery('cql:[word="Has"]', undefined, 'demo-corpus')

    expect(body).toMatchObject({ query: 'cql:[word="Has"]', corpus: 'demo-corpus' })
  })

  it('scopes lexicon suggestions to the selected corpus when provided', async () => {
    let body: unknown
    fetchMock().mockImplementationOnce(async (input: RequestInfo | URL) => {
      body = await (input as Request).clone().json()
      return mockJsonResponse({ values: ['Hase'] })
    })

    const result = await getLexiconSuggestions('word', 'Ha', 5, undefined, 'demo-corpus')

    expect(result).toEqual(['Hase'])
    expect(body).toMatchObject({ attr: 'word', prefix: 'Ha', limit: 5, corpus: 'demo-corpus' })
  })

  it('sends real logdice as collocates diff sort key', async () => {
    let body: unknown
    fetchMock().mockImplementationOnce(async (input: RequestInfo | URL) => {
      body = await (input as Request).clone().json()
      return mockJsonResponse({
        job_id: 'job-logdice',
        status_url: '/api/v1/analysis/jobs/job-logdice',
        rows_url: '/api/v1/analysis/jobs/job-logdice/rows',
      })
    })

    await createCollocatesDiffJob({
      term: 'Hase',
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      sortBy: 'logdice',
    })
    const request = fetchMock().mock.calls[0]?.[0] as Request

    expect(request.url).toContain('/api/v1/analysis/collocates_diff/job')
    expect(body).toMatchObject({ sort_by: 'logdice' })
  })

  it('sends corpus keyness parameters with limit and preserves directed scores', async () => {
    let body: unknown
    fetchMock().mockImplementationOnce(async (input: RequestInfo | URL) => {
      body = await (input as Request).clone().json()
      return mockJsonResponse({
        rows: [
          {
            word: 'alpha',
            chi2_cell: 2,
            ll: 3,
            direction: 'target',
            chi2_cell_signed: 2,
          },
        ],
      })
    })

    const rows = await getKeyness({
      targetCorpus: 'target-corpus',
      referenceCorpus: 'reference-corpus',
      pos: 'N',
      limit: 25,
    })

    expect(body).toMatchObject({
      target_corpus: 'target-corpus',
      reference_corpus: 'reference-corpus',
      pos: 'N',
      limit: 25,
    })
    expect(rows[0]).toMatchObject({
      word: 'alpha',
      direction: 'target',
      chi2_cell: 2,
      chi2_cell_signed: 2,
    })
  })

  it('surfaces keyness limitations instead of silently returning an empty complete-looking result', async () => {
    fetchMock().mockImplementationOnce(async () => mockJsonResponse({
      rows: [],
      limitations: [{ message: 'POS-gefilterte Keyness ist für diesen Pfad eingeschränkt.' }],
    }))

    await expect(getKeyness({
      targetCorpus: 'target-corpus',
      referenceCorpus: 'reference-corpus',
      pos: 'N',
    })).rejects.toThrow('eingeschränkt')
  })

  it('keeps semantic empty result distinct from semantic infrastructure errors', async () => {
    let body: unknown
    fetchMock().mockImplementationOnce(async (input: RequestInfo | URL) => {
      body = await (input as Request).clone().json()
      return mockJsonResponse({
        rows: [],
        meta: {
          exactness: 'approximate',
          candidateGeneration: { method: 'faiss_passage', searchMode: 'approximate', candidateCount: 0 },
          rerank: { enabled: true, method: 'lexical_overlap_then_vector_score' },
          filtering: { docsetApplied: false },
        },
      })
    })

    const result = await semanticSearch({ query: 'Klima', top_k: 5, corpus: 'paired-sample', docsetId: 'docset-1' })
    const request = fetchMock().mock.calls[0]?.[0] as Request

    expect(request.url).toContain('/api/v1/analysis/embedding_search')
    expect(body).toMatchObject({ term: 'Klima', top_n: 5, corpus: 'paired-sample', docset_id: 'docset-1' })
    expect(result).toEqual([])
  })

  it('returns semantic response metadata and non-string row metadata through the detailed client helper', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonResponse({
      rows: [{
        kw: 'Klima und Energie',
        score: 0.87,
        doc_id: 7,
        chunk_id: '7:0',
        meta: { source: 'news', year: 2026, flags: ['ai'] },
      }],
      meta: {
        exactness: 'exact',
        candidateGeneration: {
          method: 'faiss_passage',
          searchMode: 'exact',
          candidateCount: 24,
          lexicalSeedCount: 2,
        },
        rerank: { enabled: true, inputCount: 26, outputCount: 1 },
        filtering: { docsetApplied: true, docsetDocCount: 12 },
      },
    }))

    const result = await semanticSearchWithMeta({ query: 'Klima' })

    expect(result.rows[0]).toMatchObject({ doc_id: '7', chunk_id: '7:0', text: 'Klima und Energie' })
    expect(result.rows[0]?.metadata).toEqual({ source: 'news', year: 2026, flags: ['ai'] })
    expect(result.meta).toMatchObject({
      exactness: 'exact',
      candidateGeneration: { method: 'faiss_passage', searchMode: 'exact', candidateCount: 24 },
      rerank: { enabled: true, inputCount: 26, outputCount: 1 },
      filtering: { docsetApplied: true, docsetDocCount: 12 },
    })
  })

  it('accepts semantic rows with null metadata from the backend', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonResponse({
      rows: [{ kw: 'Erneuerbare Energien', score: 0.81, doc_id: 9, meta: null }],
    }))

    const result = await semanticSearchWithMeta({ query: 'Energiewende' })

    expect(result.rows[0]).toMatchObject({ doc_id: '9', text: 'Erneuerbare Energien' })
    expect(result.rows[0]?.metadata).toBeUndefined()
  })

  it('throws semantic search errors with backend detail instead of returning empty rows', async () => {
    fetchMock().mockResolvedValueOnce(await mockJsonStatusResponse(503, {
      detail: {
        code: 'semantic_index_missing',
        message: 'Semantischer Vektorindex fehlt oder ist unvollständig.',
        backend: 'spacy',
        level: 'doc',
        faissStatus: 'unavailable',
        missingAssets: ['/private/index/faiss_passage.index'],
      },
    }))

    const thrown = await semanticSearch({ query: 'Klima' }).catch((error) => error)

    expect(thrown).toBeInstanceOf(SemanticSearchError)
    expect(thrown).toMatchObject({
      name: 'SemanticSearchError',
      code: 'semantic_index_missing',
      backend: 'spacy',
      level: 'doc',
      faissStatus: 'unavailable',
      missingAssets: ['/private/index/faiss_passage.index'],
    })
  })

  it('sends Bearer auth on Copilot SSE chat streams', async () => {
    ;(window.localStorage.getItem as Mock).mockReturnValue('copilot-token')
    fetchMock().mockResolvedValueOnce(await mockSseResponse('event: copilot.done\ndata: {"text":"ok"}\n\n'))

    const cancel = streamCopilotMessage('hello', { onError: vi.fn(), maxRetries: 0 })
    await vi.waitFor(() => expect(fetchMock()).toHaveBeenCalledTimes(1))
    cancel()

    expect(String(fetchMock().mock.calls[0]?.[0])).toBe('/api/v1/chat/stream')
    expect(headersFromFetchCall().get('Authorization')).toBe('Bearer copilot-token')
    expect(headersFromFetchCall().get('Accept')).toBe('text/event-stream')
  })

  it('keeps Copilot SSE event type across chunk boundaries', async () => {
    fetchMock().mockResolvedValueOnce(await mockSseChunkedResponse([
      'event: copilot.tool_result\n',
      'data: {"toolName":"document_search","ok":true,"ts":1,"output":{"rows":[{"id":1}]}}\n\n',
      'event: copilot.done\n',
      'data: {"text":"ok"}\n\n',
    ]))

    const onToolResultV1 = vi.fn()
    const onDone = vi.fn()
    const cancel = streamCopilotMessage('hello', {
      onToolResultV1,
      onDone,
      onError: vi.fn(),
      maxRetries: 0,
    })

    await vi.waitFor(() => expect(onToolResultV1).toHaveBeenCalledWith({
      toolName: 'document_search',
      ok: true,
      ts: 1,
      output: { rows: [{ id: 1 }] },
    }))
    await vi.waitFor(() => expect(onDone).toHaveBeenCalled())
    cancel()
  })

})
