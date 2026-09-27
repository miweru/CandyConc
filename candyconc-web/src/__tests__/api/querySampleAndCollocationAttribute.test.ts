import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import {
  coerceSampleProvenance,
  executeQuery,
  executeSampledQuery,
  executeQueryStreaming,
  getCollocations,
  getCollocationsPage,
  getCollocationNetwork,
  parseSampleProvenanceHeader,
  type QueryParams,
  type QueryResult,
} from '@/api/client'

/**
 * Parameter-Durchreichung der Messlatte-S3-Frontend-Anbindung:
 *  - GET /query: sample+seed landen als Query-Parameter, X-CandyConc-Sample
 *    wird als Provenienz geparst (niemals fabriziert).
 *  - GET /query/stream: sample+seed werden gespiegelt.
 *  - executeSampledQuery: sammelt die KOMPLETTE Stichprobe über Offset-Paging.
 *  - /analysis/collocates + /analysis/collocation_network: attribute-Parameter
 *    ('word'|'lemma') und mi3-Sortierung erreichen den Server unverändert.
 */

function jsonResponse(payload: unknown, headers: Record<string, string> = {}) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'Content-Type': 'application/json', ...headers },
    })
  )
}

function fetchMock(): Mock {
  return globalThis.fetch as Mock
}

function requestedUrl(callIndex = 0): string {
  const arg = fetchMock().mock.calls[callIndex]?.[0] as Request | string
  return typeof arg === 'string' ? arg : arg.url
}

const SAMPLE_HEADER = JSON.stringify({
  requested: 200,
  drawn: 200,
  seed: 42,
  population: 9740,
  population_partial: false,
})

describe('GET /query sample+seed passthrough', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse(
          [{ left: 'l', kw: 'Treffer', right: 'r', pos: 7, doc_id: 3, doc: 'D' }],
          { 'X-CandyConc-Sample': SAMPLE_HEADER }
        )
      )
    )
  })

  afterEach(() => vi.unstubAllGlobals())

  it('sends sample and seed and parses the provenance header verbatim', async () => {
    const result = await executeQuery({ term: 'Haus', sample: 200, seed: 42 })
    const url = requestedUrl()
    expect(url).toContain('/api/v1/query?')
    expect(url).toContain('sample=200')
    expect(url).toContain('seed=42')
    expect(result.sample).toEqual({
      requested: 200,
      drawn: 200,
      seed: 42,
      population: 9740,
      populationPartial: false,
    })
  })

  it('omits sample/seed entirely when not configured (unveränderter Altpfad)', async () => {
    await executeQuery({ term: 'Haus' })
    const url = requestedUrl()
    expect(url).not.toContain('sample=')
    expect(url).not.toContain('seed=')
  })

  it('streams mirror sample/seed as query parameters', async () => {
    // Der Stream-Client liest response.body; ein leerer SSE-Body genügt, um
    // die Request-URL zu verifizieren.
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        Promise.resolve(
          new Response('', {
            status: 200,
            headers: { 'Content-Type': 'text/event-stream' },
          })
        )
      )
    )
    const events = []
    for await (const event of executeQueryStreaming({ term: 'Haus', docsetId: 'ds1', sample: 50, seed: 7 })) {
      events.push(event)
    }
    const url = requestedUrl()
    expect(url).toContain('/api/v1/query/stream?')
    expect(url).toContain('docset_id=ds1')
    expect(url).toContain('sample=50')
    expect(url).toContain('seed=7')
  })
})

describe('sample provenance parsing stays honest', () => {
  it('rejects malformed provenance instead of fabricating fields', () => {
    expect(parseSampleProvenanceHeader(null)).toBeNull()
    expect(parseSampleProvenanceHeader('not json')).toBeNull()
    expect(parseSampleProvenanceHeader('{"requested": 10}')).toBeNull()
    expect(coerceSampleProvenance({ requested: 1, drawn: 1, seed: 'x', population: 5 })).toBeNull()
    expect(
      coerceSampleProvenance({ requested: 10, drawn: 5, seed: 0, population: 5, population_partial: true })
    ).toEqual({ requested: 10, drawn: 5, seed: 0, population: 5, populationPartial: true })
  })
})

describe('executeSampledQuery collects the complete drawn sample', () => {
  it('pages through runPage until next_offset is exhausted', async () => {
    const provenance = {
      requested: 5,
      drawn: 5,
      seed: 42,
      population: 100,
      populationPartial: false,
    }
    const pages: QueryResult[] = [
      {
        hits: [1, 2, 3].map((n) => ({
          position: n,
          left: '',
          match: `t${n}`,
          right: '',
          doc_id: 'd',
        })),
        total: 5,
        query_time_ms: 1,
        next_offset: 3,
        sample: provenance,
      },
      {
        hits: [4, 5].map((n) => ({
          position: n,
          left: '',
          match: `t${n}`,
          right: '',
          doc_id: 'd',
        })),
        total: 5,
        query_time_ms: 1,
        next_offset: null,
        sample: provenance,
      },
    ]
    const runPage = vi.fn(async (params: QueryParams) => pages[params.offset === 0 ? 0 : 1])

    const result = await executeSampledQuery({ term: 'x', sample: 5, seed: 42 }, runPage)

    expect(runPage).toHaveBeenCalledTimes(2)
    expect(runPage.mock.calls[0][0]).toMatchObject({ sample: 5, seed: 42, offset: 0 })
    expect(runPage.mock.calls[1][0]).toMatchObject({ sample: 5, seed: 42, offset: 3 })
    expect(result.hits.map((hit) => hit.match)).toEqual(['t1', 't2', 't3', 't4', 't5'])
    expect(result.total).toBe(5)
    expect(result.sample).toEqual(provenance)
    // Die geladene STICHPROBE ist vollständig — kein truncated-Flag.
    expect(result.truncated).toBe(false)
    expect(result.next_offset).toBeNull()
  })

  it('enforces the seed requirement client-side (Reproduzierbarkeitskontrakt)', async () => {
    await expect(executeSampledQuery({ term: 'x', sample: 5 })).rejects.toThrow(/Seed/)
    await expect(executeSampledQuery({ term: 'x', sample: 0, seed: 1 })).rejects.toThrow(/sample/)
  })
})

describe('collocation attribute + mi3 passthrough', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          rows: [
            {
              word: 'bellt',
              f: 6,
              frequency: 6,
              logdice: 9.1,
              mi: 2.2,
              mi3: 8.9891,
            },
          ],
          method: { family: 'collocation', statistics: [] },
          row_limit: 200,
          total_candidates: 1,
          truncated: false,
          offset: 0,
          limit: 200,
        })
      )
    )
  })

  afterEach(() => vi.unstubAllGlobals())

  it('getCollocations sends attribute=lemma and sort_by=mi3', async () => {
    await getCollocations({ term: 'Hund', measure: 'mi3', sortBy: 'mi3', attribute: 'lemma' })
    const url = requestedUrl()
    expect(url).toContain('/api/v1/analysis/collocates?')
    expect(url).toContain('attribute=lemma')
    expect(url).toContain('sort_by=mi3')
  })

  it('getCollocations omits attribute by default (byte-identischer Altpfad)', async () => {
    await getCollocations({ term: 'Hund' })
    expect(requestedUrl()).not.toContain('attribute=')
  })

  it('getCollocationsPage surfaces rows, method and bounded-result meta', async () => {
    const page = await getCollocationsPage({
      term: 'Hund',
      attribute: 'lemma',
      sortBy: 'mi3',
      offset: 0,
      limit: 200,
    })
    expect(requestedUrl()).toContain('attribute=lemma')
    expect(page.rows[0]).toMatchObject({ word: 'bellt', mi3: 8.9891 })
    expect(page.total_candidates).toBe(1)
    expect(page.truncated).toBe(false)
    expect(page.limit).toBe(200)
  })

  it('getCollocationNetwork mirrors attribute and accepts measure=mi3', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          term: 'Hund',
          measure: 'mi3',
          nodes: [],
          edges: [],
        })
      )
    )
    await getCollocationNetwork({ term: 'Hund', measure: 'mi3', attribute: 'lemma' })
    const url = requestedUrl()
    expect(url).toContain('/api/v1/analysis/collocation_network?')
    expect(url).toContain('measure=mi3')
    expect(url).toContain('attribute=lemma')
  })
})
