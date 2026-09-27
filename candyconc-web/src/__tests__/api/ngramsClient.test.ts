/**
 * N-gram API client tests — verify the request payloads match the backend
 * contract in routes/analysis.py (POST /analysis/ngrams/job and
 * /analysis/ngrams_diff/job) and that schema validation rejects bad shapes.
 */
import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import { createNgramsJob, createNgramsDiffJob, getAnalysisJobRows } from '@/api/client'

/** Requests captured at fetch time (the body is unreadable after ky sends it). */
let captured: Array<{ url: string; body: any }> = []

function stubFetch(payload: unknown) {
  captured = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
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
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

function requestFromCall(index = 0): { url: string; body: any } {
  const call = captured[index]
  expect(call).toBeDefined()
  return call!
}

const jobStart = {
  job_id: 'job123',
  status_url: '/api/v1/analysis/jobs/job123',
  rows_url: '/api/v1/analysis/jobs/job123/rows?offset=0&limit=200',
  ws_url: '/api/v1/ws/analysis/job123',
}

describe('createNgramsJob', () => {
  beforeEach(() => {
    stubFetch(jobStart)
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('posts min_n/max_n/min_freq/docset_id per the backend contract', async () => {
    const result = await createNgramsJob({
      n: 3,
      minFreq: 5,
      limit: 500,
      corpus: 'default',
      docsetId: 'a1b2c3',
    })
    expect(result.job_id).toBe('job123')
    const { url, body } = requestFromCall()
    expect(url).toContain('/api/v1/analysis/ngrams/job')
    expect(body).toEqual({
      min_n: 3,
      max_n: 3,
      min_freq: 5,
      limit: 500,
      corpus: 'default',
      docset_id: 'a1b2c3',
    })
  })

  it('omits optional fields when unset', async () => {
    await createNgramsJob({ n: 2 })
    const { body } = requestFromCall()
    expect(body).toEqual({ min_n: 2, max_n: 2 })
  })

  it('preserves explicit min/max n-gram ranges', async () => {
    await createNgramsJob({ minN: 1, maxN: 3, limit: 25 })
    const { body } = requestFromCall()
    expect(body).toEqual({ min_n: 1, max_n: 3, limit: 25 })
  })

  it('throws when the response does not match the AnalysisJobStart schema', async () => {
    stubFetch({ nope: true })
    await expect(createNgramsJob({ n: 2 })).rejects.toThrow()
  })
})

describe('createNgramsDiffJob', () => {
  beforeEach(() => {
    stubFetch(jobStart)
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('posts target/reference docset ids and min_freq per the backend contract', async () => {
    const result = await createNgramsDiffJob({
      targetDocsetId: 'a1b2c3',
      referenceDocsetId: 'd4e5f6',
      n: 2,
      minFreq: 7,
      limit: 100,
      corpus: 'default',
    })
    expect(result.job_id).toBe('job123')
    const { url, body } = requestFromCall()
    expect(url).toContain('/api/v1/analysis/ngrams_diff/job')
    expect(body).toEqual({
      target_docset_id: 'a1b2c3',
      reference_docset_id: 'd4e5f6',
      min_n: 2,
      max_n: 2,
      min_freq: 7,
      limit: 100,
      corpus: 'default',
    })
  })

  it('preserves explicit min/max ranges for n-gram diff jobs', async () => {
    await createNgramsDiffJob({
      targetDocsetId: 'a1b2c3',
      referenceDocsetId: 'd4e5f6',
      minN: 1,
      maxN: 3,
    })
    const { body } = requestFromCall()
    expect(body).toEqual({
      target_docset_id: 'a1b2c3',
      reference_docset_id: 'd4e5f6',
      min_n: 1,
      max_n: 3,
    })
  })
})

describe('getAnalysisJobRows', () => {
  beforeEach(() => {
    stubFetch({
      job_id: 'job123',
      status: 'done',
      total_rows: 500,
      row_limit: 500,
      total_candidates: 1200,
      truncated: true,
      offset: 0,
      limit: 500,
      rows: [{ ngram: 'im Jahr', freq: 340, n: 2 }],
    })
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('preserves backend limit metadata instead of treating capped rows as complete', async () => {
    const result = await getAnalysisJobRows('job123', 0, 500)
    const { url } = requestFromCall()

    expect(url).toContain('/api/v1/analysis/jobs/job123/rows')
    expect(result.rows).toHaveLength(1)
    expect(result.total_rows).toBe(500)
    expect(result.row_limit).toBe(500)
    expect(result.total_candidates).toBe(1200)
    expect(result.truncated).toBe(true)
  })
})
