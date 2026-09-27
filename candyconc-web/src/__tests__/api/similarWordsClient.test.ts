import { afterEach, describe, expect, it, vi, type Mock } from 'vitest'

import { getSimilarWords, SimilarWordsUnavailableError } from '@/api/client'

function jsonResponse(payload: unknown, status = 200) {
  return Promise.resolve(
    new Response(JSON.stringify(payload), {
      status,
      headers: { 'Content-Type': 'application/json' },
    })
  )
}

function fetchMock() {
  return globalThis.fetch as Mock
}

/** ky may invoke fetch with a string URL or a Request object — normalise. */
function calledUrl(): string {
  const arg = fetchMock().mock.calls[0]?.[0]
  return arg instanceof Request ? arg.url : String(arg)
}

describe('getSimilarWords (F8) — ranked neighbours', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('sends term/k/min_score/corpus/docset_id and maps the ranked neighbours', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() =>
        jsonResponse({
          status: 'ok',
          term: 'Klimawandel',
          backend: 'faiss',
          neighbours: [
            { word: 'Erderwärmung', score: 0.91, corpus_frequency: 120 },
            { word: 'Klimakrise', score: 0.84, corpus_frequency: 77 },
          ],
        })
      )
    )

    const result = await getSimilarWords({
      term: 'Klimawandel',
      k: 20,
      minScore: 0.5,
      corpus: 'demo',
      docsetId: 'ds-1',
    })

    const url = calledUrl()
    expect(url).toContain('/api/v1/semantic/similar_words?')
    expect(url).toContain('term=Klimawandel')
    expect(url).toContain('k=20')
    expect(url).toContain('min_score=0.5')
    expect(url).toContain('corpus=demo')
    expect(url).toContain('docset_id=ds-1')

    expect(result.backend).toBe('faiss')
    expect(result.unavailable).toBe(false)
    expect(result.neighbours).toHaveLength(2)
    expect(result.neighbours[0]).toMatchObject({ word: 'Erderwärmung', score: 0.91, corpusFrequency: 120 })
  })

  it('preserves vector equality evidence independently of cosine scores', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({
      term: 'freedom',
      neighbours: [
        { word: 'liberty', score: 1, shared_query_vector: true },
        { word: 'peace', score: 1, shared_query_vector: false },
        { word: 'world', score: 1 },
      ],
    })))
    const result = await getSimilarWords({ term: 'freedom' })
    expect(result.neighbours.map((row) => row.sharedQueryVector)).toEqual([true, false, null])
  })

  it('tolerates missing score/corpus_frequency (defensive nulls)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse({ term: 'x', neighbours: [{ word: 'y' }] }))
    )
    const result = await getSimilarWords({ term: 'x' })
    expect(result.neighbours[0]).toMatchObject({ word: 'y', score: null, corpusFrequency: null })
    expect(result.backend).toBeNull()
  })

  it('accepts a US-spelled `neighbors` alias', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(() => jsonResponse({ term: 'x', neighbours: [], neighbors: [{ word: 'z', score: 0.7 }] }))
    )
    const result = await getSimilarWords({ term: 'x' })
    expect(result.neighbours).toHaveLength(1)
    expect(result.neighbours[0]?.word).toBe('z')
  })

  it('short-circuits an empty term without a network call', async () => {
    vi.stubGlobal('fetch', vi.fn())
    const result = await getSimilarWords({ term: '   ' })
    expect(result.neighbours).toHaveLength(0)
    expect(fetchMock()).not.toHaveBeenCalled()
  })
})

describe('getSimilarWords (F8) — soft degradation', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('throws SimilarWordsUnavailableError on 404', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ detail: 'no embeddings' }, 404)))
    await expect(getSimilarWords({ term: 'x' })).rejects.toBeInstanceOf(SimilarWordsUnavailableError)
  })

  it('throws SimilarWordsUnavailableError on 501', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ detail: 'not implemented' }, 501)))
    await expect(getSimilarWords({ term: 'x' })).rejects.toBeInstanceOf(SimilarWordsUnavailableError)
  })

  it('throws SimilarWordsUnavailableError on 503 (embeddings/index not loaded)', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ detail: 'embeddings unavailable' }, 503)))
    const err = await getSimilarWords({ term: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(SimilarWordsUnavailableError)
    expect((err as SimilarWordsUnavailableError).status).toBe(503)
    expect((err as SimilarWordsUnavailableError).message).toBe('Embeddings nicht verfügbar')
  })

  // The server answers a corpus without word vectors with 422
  // word_vectors.unavailable and a corpus whose pipeline it lacks with 503
  // word_vectors.service_error, both with the reason in detail.
  it('treats 422 word_vectors.unavailable as unavailable and keeps the reason', async () => {
    const detail = 'No word vectors for this corpus (word_similarity): … The corpus was imported with blank:en, which only tokenizes and has no word vectors.'
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ status: 422, code: 'word_vectors.unavailable', detail }, 422)))
    const err = await getSimilarWords({ term: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(SimilarWordsUnavailableError)
    expect((err as SimilarWordsUnavailableError).status).toBe(422)
    expect((err as SimilarWordsUnavailableError).reason).toBe(detail)
  })

  it('keeps the reason of a 503 word_vectors.service_error', async () => {
    const detail = 'The word vectors of this corpus cannot be loaded on this server. The spaCy pipeline \'en_core_web_md\' is not installed.'
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ status: 503, code: 'word_vectors.service_error', detail }, 503)))
    const err = await getSimilarWords({ term: 'x' }).catch((e) => e)
    expect(err).toBeInstanceOf(SimilarWordsUnavailableError)
    expect((err as SimilarWordsUnavailableError).reason).toBe(detail)
  })

  it('keeps other 422 answers as errors', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ status: 422, code: 'request.invalid', detail: 'k must be >= 1' }, 422)))
    const err = await getSimilarWords({ term: 'x' }).catch((e) => e)
    expect(err).not.toBeInstanceOf(SimilarWordsUnavailableError)
  })

  it('treats a 200 unavailable envelope as a soft signal', async () => {
    vi.stubGlobal('fetch', vi.fn(() => jsonResponse({ status: 'unavailable', neighbours: [] })))
    await expect(getSimilarWords({ term: 'x' })).rejects.toBeInstanceOf(SimilarWordsUnavailableError)
  })
})
