import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from 'vitest'

import {
  getWordSketchDiff,
  getAnnotationAgreement,
  getAnnotations,
  putAnnotation,
  getAnnotationsMulti,
  importAnnotations,
  getAnnotationSettings,
  getCollocateKwic,
  putAnnotationSettings,
} from '@/api/client'

/**
 * T5 frontend-contracts regression tests. These feed the REAL backend wire
 * shapes (read out of routes/analysis.py + routes/annotations.py) so a future
 * drift between client mapping and backend payload fails here.
 */

interface Captured {
  url: string
  method: string
  body: Record<string, unknown> | null
}

let captured: Captured[]

/**
 * Route each request to a per-path handler so we can both (a) return the real
 * backend payload for the dedicated endpoint and (b) PROVE the single-term
 * fallback never fires (its handler asserts it was not reached).
 */
function installRoutingFetch(
  handler: (path: string, captured: Captured) => { payload: unknown; status?: number }
) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string, init?: RequestInit) => {
      let url: string
      let method: string
      let body: Record<string, unknown> | null = null
      if (input instanceof Request) {
        url = input.url
        method = input.method
        const text = await input.clone().text()
        body = text ? JSON.parse(text) : null
      } else {
        url = String(input)
        method = (init?.method ?? 'GET').toUpperCase()
        body = init?.body ? JSON.parse(String(init.body)) : null
      }
      const entry: Captured = { url, method, body }
      captured.push(entry)
      const path = new URL(url, 'http://localhost').pathname
      const { payload, status = 200 } = handler(path, entry)
      return new Response(JSON.stringify(payload), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

function pathsHit(): string[] {
  return captured.map((c) => new URL(c.url, 'http://localhost').pathname)
}

beforeEach(() => {
  captured = []
  ;(window.localStorage.getItem as Mock).mockReturnValue(null)
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('getCollocateKwic — completeness evidence', () => {
  it('preserves the backend truncated flag for Co-KWIC windows', async () => {
    installRoutingFetch(() => ({
      payload: {
        rows: [{ pos: 7, left: 'Der', kw: 'Hase', right: 'läuft', doc_id: 1, coll_offsets: [1] }],
        total: 12,
        next_offset: null,
        truncated: true,
      },
    }))

    const result = await getCollocateKwic({ term: 'Hase', collocate: 'läuft', limit: 5 })

    expect(result.total).toBe(12)
    expect(result.next_offset).toBeNull()
    expect(result.truncated).toBe(true)
    expect(result.hits[0]).toMatchObject({
      position: 7,
      match: 'Hase',
      collocate_offsets: [1],
    })
  })
})

describe('getWordSketchDiff — dict relations contract (C-wordsketch-diff-parity-01)', () => {
  // The EXACT shape routes/analysis.analysis_wordsketch_diff returns: `relations`
  // is a DICT keyed by relation name, each value with common/only_a/only_b; rows
  // keep `word` + `score`; common rows carry score_a/score_b/delta. Plus
  // label_a/label_b.
  const backendDiff = {
    label_a: 'Politik',
    label_b: 'Wirtschaft',
    score_key: 'score',
    relations: {
      obj: {
        only_a: [
          { word: 'Strategie', score: 4.1, f: 8 },
          { word: 'Reform', score: 2.3, frequency: 6 },
        ],
        only_b: [{ word: 'Wachstum', score: 3.7, frequency: 5 }],
        common: [{ word: 'Modell', score_a: 4.1, score_b: 2.0, delta: 2.1, f_a: 4, f_b: 9 }],
      },
      amod: {
        only_a: [],
        only_b: [{ word: 'global', score: 1.5 }],
        common: [],
      },
    },
    relation_labels: {
      obj: 'Objekt von',
      amod: 'Adjektiv-Modifikatoren',
    },
    method: { family: 'wordsketch', index_fingerprint: 'fp-9' },
    limitations: [],
  }

  it('consumes the dedicated endpoint dict shape WITHOUT any single-term fallback', async () => {
    installRoutingFetch((path) => {
      if (path.endsWith('/analysis/wordsketch_diff')) return { payload: backendDiff }
      // If the client falls back to two single-term sketches, this fires — fail.
      if (path.endsWith('/analysis/wordsketch')) {
        throw new Error('single-term fallback was used — wordsketch_diff dict shape not consumed')
      }
      return { payload: {} }
    })

    const result = await getWordSketchDiff({ termA: 'Politik', termB: 'Wirtschaft', corpus: 'demo' })

    // The dedicated endpoint is the ONLY thing hit — zero single-term fetches.
    expect(pathsHit().filter((p) => p.endsWith('/analysis/wordsketch'))).toHaveLength(0)
    expect(pathsHit().filter((p) => p.endsWith('/analysis/wordsketch_diff'))).toHaveLength(1)

    // label_a / label_b → termA / termB.
    expect(result.termA).toBe('Politik')
    expect(result.termB).toBe('Wirtschaft')

    // Dict entries mapped to relation rows.
    const obj = result.relations.find((r) => r.relation === 'obj')
    expect(obj).toBeDefined()
    expect(obj?.onlyA.map((w) => w.word)).toEqual(['Strategie', 'Reform'])
    expect(obj?.onlyB.map((w) => w.word)).toEqual(['Wachstum'])
    expect(obj?.onlyA.map((w) => w.frequency)).toEqual([8, 6])
    expect(obj?.onlyB.map((w) => w.frequency)).toEqual([5])
    expect(obj?.common).toEqual([{
      word: 'Modell',
      scoreA: 4.1,
      scoreB: 2.0,
      frequencyA: 4,
      frequencyB: 9,
      delta: 2.1,
    }])

    const amod = result.relations.find((r) => r.relation === 'amod')
    expect(amod?.onlyB.map((w) => w.word)).toEqual(['global'])
    expect(result.relationLabels).toMatchObject({
      obj: 'Objekt von',
      amod: 'Adjektiv-Modifikatoren',
    })

    expect(result.method?.family).toBe('wordsketch')
  })

  it('still falls back to two single-term sketches when the endpoint is absent (back-compat)', async () => {
    installRoutingFetch((path) => {
      if (path.endsWith('/analysis/wordsketch_diff')) return { payload: { detail: 'missing' }, status: 404 }
      if (path.endsWith('/analysis/wordsketch')) {
        return { payload: { sketches: { obj: [{ word: 'x', score: 1 }] } } }
      }
      return { payload: {} }
    })

    const result = await getWordSketchDiff({ termA: 'A', termB: 'B' })
    // Fallback ran: two single-term sketches were fetched.
    expect(pathsHit().filter((p) => p.endsWith('/analysis/wordsketch'))).toHaveLength(2)
    expect(result.termA).toBe('A')
    expect(result.termB).toBe('B')
  })

  it('does not mask dedicated endpoint server errors with the two-sketch fallback', async () => {
    installRoutingFetch((path) => {
      if (path.endsWith('/analysis/wordsketch_diff')) return { payload: { detail: 'server failed' }, status: 500 }
      if (path.endsWith('/analysis/wordsketch')) {
        throw new Error('single-term fallback must not run after a server error')
      }
      return { payload: {} }
    })

    await expect(getWordSketchDiff({ termA: 'A', termB: 'B' })).rejects.toThrow()
    expect(pathsHit().filter((p) => p.endsWith('/analysis/wordsketch_diff'))).toHaveLength(1)
    expect(pathsHit().filter((p) => p.endsWith('/analysis/wordsketch'))).toHaveLength(0)
  })

  it('does not mask malformed dedicated endpoint payloads with the two-sketch fallback', async () => {
    installRoutingFetch((path) => {
      if (path.endsWith('/analysis/wordsketch_diff')) return { payload: { status: 'ok' } }
      if (path.endsWith('/analysis/wordsketch')) {
        throw new Error('single-term fallback must not run after a schema/shape error')
      }
      return { payload: {} }
    })

    await expect(getWordSketchDiff({ termA: 'A', termB: 'B' }))
      .rejects
      .toThrow(/unsupported response shape/)
    expect(pathsHit().filter((p) => p.endsWith('/analysis/wordsketch_diff'))).toHaveLength(1)
    expect(pathsHit().filter((p) => p.endsWith('/analysis/wordsketch'))).toHaveLength(0)
  })
})

describe('getAnnotationAgreement — real backend field names (C-multicoder-iaa-01)', () => {
  it('maps n_rows_overlap / kappa+kappa_method / per_category_agreement dict', async () => {
    // EXACT AgreementResponse shape from routes/annotations.py.
    const backendAgreement = {
      status: 'ok',
      corpus: 'demo',
      annotators: ['alice', 'bob'],
      n_rows_total: 50,
      n_rows_overlap: 20,
      percent_agreement: 0.85,
      kappa: 0.72,
      kappa_method: 'cohen',
      per_category_agreement: { cat1: 0.9, cat2: 0.6 },
    }
    installRoutingFetch(() => ({ payload: backendAgreement }))

    const result = await getAnnotationAgreement({ corpus: 'demo' })

    expect(result.comparableRows).toBe(20)
    expect(result.percentAgreement).toBe(0.85)
    // Cohen path: cohensKappa carries the value, fleissKappa stays null.
    expect(result.cohensKappa).toBe(0.72)
    expect(result.fleissKappa).toBeNull()
    expect(result.annotators).toEqual(['alice', 'bob'])
    // per-category dict flattened to the UI array shape, survives normalization.
    const byId = Object.fromEntries(result.perCategory.map((e) => [e.categoryId, e.agreement]))
    expect(byId).toEqual({ cat1: 0.9, cat2: 0.6 })
  })

  it('routes a fleiss kappa_method into fleissKappa (≥3 coders)', async () => {
    installRoutingFetch(() => ({
      payload: {
        status: 'ok',
        annotators: ['a', 'b', 'c'],
        n_rows_overlap: 12,
        percent_agreement: 0.7,
        kappa: 0.55,
        kappa_method: 'fleiss',
        per_category_agreement: {},
      },
    }))

    const result = await getAnnotationAgreement({ corpus: 'demo' })
    expect(result.fleissKappa).toBe(0.55)
    expect(result.cohensKappa).toBeNull()
    expect(result.comparableRows).toBe(12)
  })

  it('degrades to an empty result on 404', async () => {
    installRoutingFetch(() => ({ payload: { detail: 'no route' }, status: 404 }))
    const result = await getAnnotationAgreement({ corpus: 'demo' })
    expect(result.comparableRows).toBe(0)
    expect(result.cohensKappa).toBeNull()
    expect(result.perCategory).toEqual([])
  })

  it('does not hide explicit docset-scope rejection as an empty agreement', async () => {
    installRoutingFetch(() => ({
      payload: { detail: 'docset_id wird für Annotation-Agreement noch nicht unterstützt' },
      status: 422,
    }))

    await expect(getAnnotationAgreement({ corpus: 'demo', docsetId: 'review-scope' })).rejects.toThrow()
  })
})

describe('getAnnotations — active coder slot query', () => {
  it('passes the active annotator as query param for multi-coder reads', async () => {
    installRoutingFetch((path, entry) => {
      expect(path.endsWith('/annotations')).toBe(true)
      const params = new URL(entry.url, 'http://localhost').searchParams
      expect(params.get('corpus')).toBe('demo')
      expect(params.get('docset_id')).toBe('review-scope')
      expect(params.get('annotator')).toBe('bob')
      return {
        payload: {
          status: 'ok',
          annotations: {
            'doc1:5': {
              category_id: 'cat1',
              note: 'bob note',
              annotator: 'bob',
              updated_at: '2026-06-21T07:30:00Z',
            },
          },
          scheme: { categories: [] },
        },
      }
    })

    const result = await getAnnotations({
      corpus: 'demo',
      docsetId: 'review-scope',
      annotator: 'bob',
    })

    expect(result.annotations['doc1:5']).toMatchObject({
      categoryId: 'cat1',
      note: 'bob note',
      annotator: 'bob',
    })
  })
})

describe('putAnnotation — real backend upsert envelope', () => {
  it('normalizes the nested annotation record returned by routes/annotations.py', async () => {
    installRoutingFetch((path, entry) => {
      expect(path).toContain('/annotations/')
      expect(entry.method).toBe('PUT')
      expect(entry.body).toMatchObject({
        category_id: 'cat1',
        note: 'client note',
        annotator: 'client-user',
      })
      expect(new URL(entry.url, 'http://localhost').searchParams.get('corpus')).toBe('news')
      return {
        payload: {
          status: 'ok',
          row_id: 'doc1:5',
          annotation: {
            category_id: null,
            note: 'server note',
            annotator: 'server-user',
            updated_at: '2026-06-21T07:30:00Z',
          },
        },
      }
    })

    const result = await putAnnotation(
      'doc1:5',
      { categoryId: 'cat1', note: 'client note', annotator: 'client-user' },
      'news'
    )

    expect(result).toEqual({
      categoryId: null,
      note: 'server note',
      annotator: 'server-user',
      updatedAt: '2026-06-21T07:30:00Z',
    })
  })
})

describe('annotation multi/import/settings wrappers (C-multicoder-iaa-03)', () => {
  it('getAnnotationsMulti parses the nested {row_id:{annotator:record}} view', async () => {
    installRoutingFetch((path) => {
      expect(path.endsWith('/annotations/multi')).toBe(true)
      return {
        payload: {
          status: 'ok',
          annotations: {
            'doc1:5': {
              alice: { category_id: 'cat1', note: null, annotator: 'alice', updated_at: '2026-06-15' },
              bob: { category_id: 'cat2', note: 'hm', annotator: 'bob', updated_at: '2026-06-15' },
            },
          },
          scheme: { categories: [{ id: 'cat1', label: 'A' }] },
          multi_coder: true,
        },
      }
    })

    const result = await getAnnotationsMulti({ corpus: 'demo' })
    expect(result.multiCoder).toBe(true)
    expect(Object.keys(result.annotations['doc1:5'])).toEqual(['alice', 'bob'])
    expect(result.annotations['doc1:5'].alice.categoryId).toBe('cat1')
    expect(result.annotations['doc1:5'].bob.note).toBe('hm')
    expect(result.scheme.categories[0].id).toBe('cat1')
  })

  it('importAnnotations POSTs the exporter record schema and parses the report', async () => {
    installRoutingFetch((path, entry) => {
      expect(path.endsWith('/annotations/import')).toBe(true)
      expect(entry.method).toBe('POST')
      expect(entry.body).toMatchObject({
        records: [{ row_id: 'doc1:5', category_id: 'cat1', annotator: 'alice' }],
        dry_run: true,
      })
      return { payload: { status: 'ok', imported: 0, skipped: 1, dry_run: true, errors: [], previews: [{}] } }
    })

    const result = await importAnnotations(
      [{ rowId: 'doc1:5', categoryId: 'cat1', annotator: 'alice' }],
      { corpus: 'demo', dryRun: true }
    )
    expect(result.dryRun).toBe(true)
    expect(result.skipped).toBe(1)
    expect(result.previews).toHaveLength(1)
  })

  it('get/put AnnotationSettings read and write multi_coder', async () => {
    installRoutingFetch((path, entry) => {
      if (entry.method === 'PUT') {
        expect(path.endsWith('/annotations/settings')).toBe(true)
        expect(entry.body).toEqual({ enabled: true })
        return { payload: { status: 'ok', multi_coder: true } }
      }
      return { payload: { status: 'ok', multi_coder: false } }
    })

    expect((await getAnnotationSettings()).multiCoder).toBe(false)
    expect((await putAnnotationSettings(true)).multiCoder).toBe(true)
  })

  it('getAnnotationSettings degrades to single-coder on 404', async () => {
    installRoutingFetch(() => ({ payload: { detail: 'no route' }, status: 404 }))
    expect((await getAnnotationSettings()).multiCoder).toBe(false)
  })
})
