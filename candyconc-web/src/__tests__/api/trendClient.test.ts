import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { getAnalysisTrend } from '@/api/client'

interface Captured {
  url: string
  body: Record<string, unknown> | null
}

let captured: Captured[]

function installFetch(payload: unknown, status = 200) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string, init?: RequestInit) => {
      if (input instanceof Request) {
        const text = await input.clone().text()
        captured.push({ url: input.url, body: text ? JSON.parse(text) : null })
      } else {
        captured.push({
          url: String(input),
          body: init?.body ? JSON.parse(String(init.body)) : null,
        })
      }
      return new Response(JSON.stringify(payload), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

const SAMPLE = {
  query: 'Klima',
  date_field: 'date',
  granularity: 'year',
  periods: [
    {
      period: '2020',
      documents: 12,
      hits: 30,
      tokens: 100_000,
      per_million: 300.0,
      ci_low: 210.1234,
      ci_high: 428.5678,
    },
    {
      period: '2021',
      documents: 9,
      hits: 0,
      tokens: 50_000,
      per_million: 0.0,
      ci_low: 0.0,
      ci_high: 76.4,
    },
    {
      period: 'undatiert',
      documents: 3,
      hits: 2,
      tokens: 9_000,
      per_million: 222.22,
      ci_low: 61.1,
      ci_high: 800.5,
    },
  ],
  warnings: [
    "3 Dokument(e) ohne parsbaren Datumswert im Feld 'date' wurden dem Bucket 'undatiert' zugeordnet.",
  ],
  method: {
    family: 'trend',
    ci_method: 'wilson_score',
    ci_level: 0.95,
    index_fingerprint: 'abc123',
  },
}

describe('getAnalysisTrend', () => {
  beforeEach(() => {
    captured = []
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('posts query, date_field, granularity and scope to /analysis/trend', async () => {
    installFetch(SAMPLE)

    await getAnalysisTrend({
      query: 'Klima',
      dateField: 'date',
      granularity: 'month',
      corpus: 'demo',
      docsetId: 'ds-1',
    })

    expect(captured[0]!.url).toContain('/api/v1/analysis/trend')
    expect(captured[0]!.body).toEqual({
      query: 'Klima',
      date_field: 'date',
      granularity: 'month',
      corpus: 'demo',
      docset_id: 'ds-1',
    })
  })

  it('defaults granularity to year and omits empty scope fields', async () => {
    installFetch(SAMPLE)

    await getAnalysisTrend({ query: 'Klima', dateField: 'year' })

    expect(captured[0]!.body).toEqual({
      query: 'Klima',
      date_field: 'year',
      granularity: 'year',
    })
  })

  it('supports raw cql payloads instead of a plain query', async () => {
    installFetch(SAMPLE)

    await getAnalysisTrend({ cql: '[pos="NOUN"]', dateField: 'date' })

    expect(captured[0]!.body).toEqual({
      cql: '[pos="NOUN"]',
      date_field: 'date',
      granularity: 'year',
    })
  })

  it('maps snake_case period rows onto the typed TrendResult', async () => {
    installFetch(SAMPLE)

    const result = await getAnalysisTrend({ query: 'Klima', dateField: 'date' })

    expect(result.query).toBe('Klima')
    expect(result.dateField).toBe('date')
    expect(result.granularity).toBe('year')
    expect(result.periods).toHaveLength(3)
    expect(result.periods[0]).toEqual({
      period: '2020',
      documents: 12,
      hits: 30,
      tokens: 100_000,
      perMillion: 300.0,
      ciLow: 210.1234,
      ciHigh: 428.5678,
    })
    // hits=0 must keep the exact zero lower bound reported by the server.
    expect(result.periods[1]!.ciLow).toBe(0)
    expect(result.periods[2]!.period).toBe('undatiert')
    expect(result.warnings).toHaveLength(1)
    expect(result.method?.family).toBe('trend')
    expect(result.method?.ci_method).toBe('wilson_score')
    // coerceMethodBlock folds the snake_case fingerprint into the UI alias.
    expect(result.method?.indexFingerprint).toBe('abc123')
  })

  it('defends against a partial payload without throwing', async () => {
    installFetch({ query: 'leer' })

    const result = await getAnalysisTrend({ query: 'leer', dateField: 'date' })

    expect(result.periods).toEqual([])
    expect(result.warnings).toEqual([])
    expect(result.method).toBeUndefined()
  })
})
