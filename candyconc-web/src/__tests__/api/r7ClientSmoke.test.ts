import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import {
  getExportConcordance,
  getLexicalDiversity,
  executeQuery,
  getQueryCount,
  coerceMethodBlock,
} from '@/api/client'

function jsonResponse(payload: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json', ...headers },
    })
  )
}

function fetchMock() {
  return globalThis.fetch as Mock
}

describe('r7 client smoke — export concordance (F2)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends query/format/case as a POST body and parses the Content-Disposition filename', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response('word,freq\nHase,3\n', {
            status: 200,
            headers: {
              'Content-Type': 'text/csv',
              'Content-Disposition': 'attachment; filename="concordance_demo.csv"',
              'X-CandyConc-Export-Total-Matches': '12',
              'X-CandyConc-Export-Exported-Rows': '3',
              'X-CandyConc-Export-Cap': '3',
              'X-CandyConc-Export-Truncated': '1',
            },
          })
        )
      )
    )

    const { blob, filename, total, totalMatches, exportedRows, exportCap, truncated } = await getExportConcordance({
      query: 'Hase',
      corpus: 'demo',
      docsetId: 'docset-1',
      sort: '1L',
      caseInsensitive: true,
      format: 'csv',
    })

    const [url, request] = fetchMock().mock.calls[0] as [string, RequestInit]
    expect(url).toBe('/api/v1/export/concordance')
    expect(request.method).toBe('POST')
    expect(new Headers(request.headers).get('Content-Type')).toBe('application/json')
    expect(JSON.parse(String(request.body))).toMatchObject({
      query: 'Hase',
      corpus: 'demo',
      docset_id: 'docset-1',
      sort: '1L',
      case_insensitive: true,
      format: 'csv',
    })
    expect(filename).toBe('concordance_demo.csv')
    expect(await blob.text()).toContain('Hase')
    expect(total).toBe(12)
    expect(totalMatches).toBe(12)
    expect(exportedRows).toBe(3)
    expect(exportCap).toBe(3)
    expect(truncated).toBe(true)
  })

  it('falls back to a default filename when no header is present', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } }))
      )
    )
    const { filename } = await getExportConcordance({ query: 'x', format: 'json' })
    expect(filename).toMatch(/^candyconc_concordance_.*\.json$/)
  })
})

describe('r7 client smoke — lexical diversity (F4)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('coerces the real per_side DICT into an ordered array and reads size_warning', async () => {
    // REAL backend wire shape: per_side is a DICT keyed by side (target/reference),
    // sides carry NO label, and the size caveat arrives as a top-level string.
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          sttr_window: 1000,
          per_side: {
            target: { ttr: 0.4, sttr: 0.7, guiraud: 22.1, n_tokens: 10000, n_types: 4000 },
            reference: { ttr: 0.6, sttr: 0.72, n_tokens: 4000, n_types: 2400 },
          },
          size_warning:
            'Die Seiten unterscheiden sich deutlich in der Tokenzahl (10000 vs. 4000).',
        })
      )
    )

    const result = await getLexicalDiversity({
      corpus: 'demo',
      targetDocsetId: 'ai',
      referenceDocsetId: 'human',
      window: 500,
    })

    const request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('/api/v1/analysis/lexical-diversity?')
    expect(request.url).toContain('target_docset_id=ai')
    expect(request.url).toContain('reference_docset_id=human')
    // window must be sent as the canonical `sttr_window` key the backend reads.
    expect(request.url).toContain('sttr_window=500')
    expect(request.url).not.toMatch(/[?&]window=/)
    expect(result.sttr_window).toBe(1000)
    // Dict -> ordered array [target, reference] with the key injected as label.
    expect(result.per_side).toHaveLength(2)
    expect(result.per_side?.[0]).toMatchObject({ label: 'target', sttr: 0.7 })
    expect(result.per_side?.[1]).toMatchObject({ label: 'reference', sttr: 0.72 })
    // Missing mattr on a side is simply absent, never a crash.
    expect(result.per_side?.[1]?.mattr).toBeUndefined()
    // size_warning travels over the wire.
    expect(result.size_warning).toContain('unterscheiden sich')
  })

  it('still accepts a legacy per_side ARRAY for forward-compat', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          sttr_window: 1000,
          per_side: [
            { label: 'AI', ttr: 0.4, sttr: 0.7, guiraud: 22.1, n_tokens: 5000, n_types: 2000 },
            { label: 'Human', ttr: 0.55, sttr: 0.72, n_tokens: 4800, n_types: 2100 },
          ],
        })
      )
    )
    const result = await getLexicalDiversity({ corpus: 'demo' })
    expect(result.per_side).toHaveLength(2)
    expect(result.per_side?.[0]).toMatchObject({ label: 'AI', sttr: 0.7 })
  })

  it('tolerates an empty/partial payload', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({})))
    const result = await getLexicalDiversity({ corpus: 'demo' })
    expect(result.per_side).toBeUndefined()
    expect(result.ttr).toBeUndefined()
    expect(result.size_warning).toBeUndefined()
  })
})

describe('r7 client smoke — caseInsensitive emission (D6)', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('emits case_insensitive on the query endpoint', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse([])))
    await executeQuery({ term: 'Hase', caseInsensitive: false })
    const request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('case_insensitive=false')
  })

  it('emits case_insensitive on the count endpoint', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ status: 'ready', total: 1 })))
    await getQueryCount({ term: 'Hase', caseInsensitive: true })
    const request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('case_insensitive=true')
  })
})

describe('r7 client smoke — method block coercion (F1)', () => {
  it('folds snake_case fingerprint into camelCase and tolerates junk', () => {
    const block = coerceMethodBlock({
      stats: { ll_signed: { name: 'Signed LL', latex_formula: '2 Σ O ln(O/E)' } },
      index_fingerprint: 'abc123',
    })
    expect(block?.indexFingerprint).toBe('abc123')
    expect(block?.stats?.ll_signed?.latex_formula).toContain('Σ')
    expect(coerceMethodBlock(null)).toBeUndefined()
    expect(coerceMethodBlock('not-an-object')).toBeUndefined()
    expect(coerceMethodBlock([])).toBeUndefined()
  })
})
