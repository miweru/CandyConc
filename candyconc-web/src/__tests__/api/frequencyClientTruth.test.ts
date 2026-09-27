import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import {
  canCreateFrequencyListJob,
  createFrequencyDiffJob,
  createFrequencyListJob,
  frequencyJobRowsToResult,
  getFrequencyResult,
} from '@/api/client'

function mockJsonResponse(payload: unknown) {
  return Promise.resolve(new Response(JSON.stringify(payload), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  }))
}

function fetchMock() {
  return globalThis.fetch as Mock
}

describe('frequency client truth metadata', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(() => mockJsonResponse({
      rows: [{ word: 'gehen', f: 7 }],
      group_by: 'lemma',
      basis: 'analyst_token_frequency',
      case_policy: 'case_insensitive (lowercase)',
      filtered_token_policy: 'Leere Werte ausgeschlossen',
      row_limit: 50,
      total_candidates: 125,
      truncated: true,
    })))
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('sends group_by and returns bounded-result provenance', async () => {
    const result = await getFrequencyResult({
      groupBy: 'lemma',
      sortBy: 'freq',
      limit: 50,
      corpus: 'demo',
      docsetId: 'docset-1',
      tokenCount: 100,
    })

    const request = fetchMock().mock.calls[0]?.[0] as Request
    const url = request.url
    expect(url).toContain('/api/v1/analysis/frequency_list?')
    expect(url).toContain('group_by=lemma')
    expect(url).toContain('corpus=demo')
    expect(url).toContain('docset_id=docset-1')
    expect(result.rows).toEqual([{ item: 'gehen', frequency: 7, relative: 0.07 }])
    expect(result.groupBy).toBe('lemma')
    expect(result.basis).toBe('analyst_token_frequency')
    expect(result.casePolicy).toBe('case_insensitive (lowercase)')
    expect(result.filteredTokenPolicy).toBe('Leere Werte ausgeschlossen')
    expect(result.rowLimit).toBe(50)
    expect(result.totalCandidates).toBe(125)
    expect(result.truncated).toBe(true)
  })

  it('sends POS-prefix filters through the synchronous and job frequency contracts', async () => {
    const result = await getFrequencyResult({
      groupBy: 'word',
      posPrefix: 'NN',
      limit: 50,
      tokenCount: 100,
    })

    let request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('/api/v1/analysis/frequency_list?')
    expect(request.url).toContain('group_by=word')
    expect(request.url).toContain('pos=NN')
    expect(result.posPrefix).toBe('NN')

    let capturedJobPayload: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      capturedJobPayload = input instanceof Request ? await input.json() : null
      return mockJsonResponse({
      job_id: 'job-frequency-1',
      status_url: '/api/v1/analysis/jobs/job-frequency-1',
      rows_url: '/api/v1/analysis/jobs/job-frequency-1/rows?offset=0&limit=200',
      })
    }))

    await createFrequencyListJob({
      groupBy: 'word',
      posPrefix: 'NN',
      limit: 250,
    })

    request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('/api/v1/analysis/frequency_list/job')
    expect(request.method).toBe('POST')
    expect(capturedJobPayload).toMatchObject({
      pos_prefix: 'NN',
      limit: 250,
    })
  })

  it('starts background frequency jobs only for word-frequency semantics', async () => {
    vi.stubGlobal('fetch', vi.fn(() => mockJsonResponse({
      job_id: 'job-frequency-1',
      status_url: '/api/v1/analysis/jobs/job-frequency-1',
      rows_url: '/api/v1/analysis/jobs/job-frequency-1/rows?offset=0&limit=200',
    })))

    expect(canCreateFrequencyListJob({ groupBy: 'word' })).toBe(true)
    expect(canCreateFrequencyListJob({ groupBy: 'lemma' })).toBe(false)

    const start = await createFrequencyListJob({
      groupBy: 'word',
      limit: 250,
      corpus: 'demo',
      docsetId: 'docset-1',
    })

    const request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('/api/v1/analysis/frequency_list/job')
    expect(request.method).toBe('POST')
    expect(start.job_id).toBe('job-frequency-1')
  })

  it('starts an exact frequency-difference job instead of joining bounded frequency pages', async () => {
    let payload: unknown = null
    vi.stubGlobal('fetch', vi.fn(async (input: RequestInfo | URL) => {
      payload = input instanceof Request ? await input.clone().json() : null
      return mockJsonResponse({
        job_id: 'job-frequency-diff-1',
        status_url: '/api/v1/analysis/jobs/job-frequency-diff-1',
        rows_url: '/api/v1/analysis/jobs/job-frequency-diff-1/rows?offset=0&limit=200',
      })
    }))

    const start = await createFrequencyDiffJob({
      targetDocsetId: 'target',
      referenceDocsetId: 'reference',
      minFreq: 1,
      limit: 30,
      corpus: 'demo',
    })

    const request = fetchMock().mock.calls[0]?.[0] as Request
    expect(request.url).toContain('/api/v1/analysis/frequency_diff/job')
    expect(request.method).toBe('POST')
    expect(payload).toEqual({
      target_docset_id: 'target',
      reference_docset_id: 'reference',
      min_freq: 1,
      limit: 30,
      corpus: 'demo',
    })
    expect(start.job_id).toBe('job-frequency-diff-1')
  })

  it('maps frequency job rows without pretending lemma/POS support', () => {
    const result = frequencyJobRowsToResult({
      job_id: 'job-frequency-1',
      status: 'done',
      row_limit: 50,
      total_candidates: 125,
      truncated: true,
      rows: [{ word: 'Hase', f: 10 }],
    }, {
      groupBy: 'word',
      tokenCount: 100,
      limit: 50,
    })

    expect(result).toMatchObject({
      groupBy: 'word',
      basis: 'analyst_token_frequency',
      casePolicy: 'case_insensitive (lowercase)',
      filteredTokenPolicy: 'Leere Werte, reine Nicht-Alnum-Werte und |Marker|-Werte sind ausgeschlossen',
      rowLimit: 50,
      totalCandidates: 125,
      truncated: true,
      rows: [{ item: 'Hase', frequency: 10, relative: 0.1 }],
    })
  })

  it('rejects background jobs for lemma/POS grouping instead of silently changing method', async () => {
    await expect(createFrequencyListJob({ groupBy: 'lemma' })).rejects.toThrow(
      'Frequency-Job unterstützt aktuell nur groupBy=word',
    )
    expect(fetchMock()).not.toHaveBeenCalled()
  })
})
