import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import { getDispersion, getDispersionOffsets, docsetFromMeta } from '@/api/client'

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function fetchMock() {
  return globalThis.fetch as Mock
}

describe('dispersion client truth metadata', () => {
  let consoleError: ReturnType<typeof vi.spyOn>

  beforeEach(() => {
    consoleError = vi.spyOn(console, 'error').mockImplementation(() => undefined)
  })

  afterEach(() => {
    consoleError.mockRestore()
    vi.unstubAllGlobals()
  })

  it('preserves exact backend basis instead of marking it partial', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({
      term: 'politik',
      partitions: [1, 0, 2],
      dp: 0.25,
      basis: 'global',
      token_count: 100,
      fallback: false,
      partial: false,
      limitations: [],
    })))

    const result = await getDispersion({ term: 'politik', partitions: 3, corpus: 'demo' })

    const request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('/api/v1/analysis/dispersion?')
    expect(result.basis).toBe('global')
    expect(result.token_count).toBe(100)
    expect(result.fallback).toBe(false)
    expect(result.partial).toBe(false)
    expect(result.limitations).toEqual([])
  })

  it('passes through the dispersion-family fields when supplied (FT-DISPERSION-FAMILY)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({
      term: 'politik',
      partitions: [3, 1, 2],
      dp: 0.2,
      dpnorm: 0.18,
      positional_dp_windowed: 0.31,
      positional_window_count: 10,
      juilland_d: 0.91,
      carroll_d2: 0.87,
      range_prop: 0.66,
      vc: 0.42,
      basis: 'global',
      token_count: 100,
    })))

    const result = await getDispersion({ term: 'politik', partitions: 3, corpus: 'demo' })

    expect(result.juilland_d).toBe(0.91)
    expect(result.carroll_d2).toBe(0.87)
    expect(result.range_prop).toBe(0.66)
    expect(result.vc).toBe(0.42)
    expect(result.positional_dp_windowed).toBe(0.31)
    expect(result.positional_window_count).toBe(10)
  })

  it('degrades gracefully when the dispersion-family fields are absent', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({
      term: 'politik',
      partitions: [3, 1, 2],
      dp: 0.2,
      basis: 'global',
      token_count: 100,
    })))

    const result = await getDispersion({ term: 'politik', partitions: 3, corpus: 'demo' })

    expect(result.juilland_d).toBeUndefined()
    expect(result.dp).toBe(0.2)
  })

  it('surfaces a missing primary endpoint instead of silently using offsets', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ detail: 'missing' }, 404)))

    await expect(getDispersion({ term: 'politik', partitions: 5, corpus: 'demo', tokenCount: 999 }))
      .rejects
      .toThrow()

    const calls = fetchMock().mock.calls.map((call) => (call[0] as Request).url)
    expect(calls[0]).toContain('/api/v1/analysis/dispersion?')
    expect(calls).toHaveLength(1)
    expect(calls.some((url) => url.includes('/api/v1/analysis/dispersion_offsets?'))).toBe(false)
  })

  it('does not mask primary endpoint server errors with the offsets fallback', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ detail: 'server failed' }, 500)))

    await expect(getDispersion({ term: 'politik', partitions: 5, corpus: 'demo' }))
      .rejects
      .toThrow()

    const calls = fetchMock().mock.calls.map((call) => (call[0] as Request).url)
    expect(calls.length).toBeGreaterThanOrEqual(1)
    expect(calls.every((url) => url.includes('/api/v1/analysis/dispersion?'))).toBe(true)
    expect(calls.some((url) => url.includes('/api/v1/analysis/dispersion_offsets?'))).toBe(false)
  })

  it('does not mask primary endpoint schema errors with the offsets fallback', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ status: 'not the dispersion schema' })))

    await expect(getDispersion({ term: 'politik', partitions: 5, corpus: 'demo' }))
      .rejects
      .toThrow(/analysis\/dispersion/)

    const calls = fetchMock().mock.calls.map((call) => (call[0] as Request).url)
    expect(calls).toHaveLength(1)
    expect(calls[0]).toContain('/api/v1/analysis/dispersion?')
  })

  it('DISP-NOTFOUND-SCHEMA: accepts the honest "not_found" limitation with detail:null', async () => {
    // The backend flags a zero-frequency term distinctly and sends detail:null;
    // the schema must validate it, not throw a generic "Fehler beim Laden".
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({
      term: 'nichtvorhanden',
      partitions: [0, 0, 0],
      dp: 0,
      classification: 'not_found',
      basis: 'global',
      token_count: 100,
      limitations: [
        { code: 'dispersion_term_not_found', message: 'Term kommt nicht vor', detail: null },
      ],
    })))

    const result = await getDispersion({ term: 'nichtvorhanden', partitions: 3, corpus: 'demo' })

    expect(result.classification).toBe('not_found')
    expect(result.limitations?.[0]?.detail).toBeNull()
  })

  it('accepts exact offset evidence without fabricating a token denominator', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({
      offsets: [3, 9],
      basis: 'global_offsets_only',
      token_count: null,
      fallback: false,
      partial: true,
      limitations: [{ code: 'dispersion_offsets_token_basis_unavailable' }],
    })))

    const result = await getDispersionOffsets({ term: 'politik', corpus: 'demo' })

    expect(result.token_count).toBeNull()
    expect(result.partial).toBe(true)
    expect(result.basis).toBe('global_offsets_only')
  })
})

describe('docsetFromMeta token-count opt-in (NGRAMS-METASUBCORPUS-PERMILLION / SUBC-02)', () => {
  // The body is unreadable after ky sends it, so capture it at fetch time.
  let captured: Array<Record<string, unknown>>

  function stubCapturingFetch(response: unknown) {
    captured = []
    vi.stubGlobal('fetch', vi.fn(async (input: Request) => {
      const text = await input.clone().text()
      captured.push(text ? JSON.parse(text) : {})
      return jsonResponse(response)
    }))
  }

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('asks the backend to compute the real scope token count by default', async () => {
    stubCapturingFetch({ docset_id: 'meta-1', doc_count: 12, token_count: 5000 })

    const result = await docsetFromMeta({ register: ['news'] }, 'demo')

    // The truthy token_count flag opts into the backend's real-count computation.
    expect(captured[0]?.token_count).toBe(1)
    expect(captured[0]?.filters).toEqual({ register: ['news'] })
    expect(result.token_count).toBe(5000)
  })

  it('omits the flag when explicitly opted out', async () => {
    stubCapturingFetch({ docset_id: 'meta-2', doc_count: 3 })

    await docsetFromMeta({ register: ['news'] }, 'demo', false)

    expect(captured[0]?.token_count).toBeUndefined()
  })
})
