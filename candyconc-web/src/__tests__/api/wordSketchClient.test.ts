import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import { getWordSketch, getWordSketchDiff } from '@/api/client'

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

describe('getWordSketch', () => {
  beforeEach(() => {
    // REAL r7 backend wire shape: relations nested under `sketches`, a sibling
    // `method` provenance block, plus (for some backends) the relation arrays
    // ALSO mirrored at the top level. The client must read the relations and
    // NEVER call `.slice` on the `sketches`/`method` objects.
    stubFetch({
      sketches: {
        obj: [
          { word: 'beta', score: 3.5, frequency: 4 },
          { word: 'gamma', score: 1.5, f: 2 },
        ],
        amod: [{ word: 'rot', score: 2.1, frequency: 9 }],
      },
      // r9 sibling gloss map: relation code -> { relation, label }.
      relations: {
        obj: {
          relation: 'obj',
          label: 'Objekt von',
          row_limit: 2,
          total_candidates: 12,
          total_rows: 2,
          truncated: true,
          min_freq: 3,
        },
        amod: {
          relation: 'amod',
          label: 'Adjektiv-Modifikatoren',
          row_limit: 2,
          total_candidates: 1,
          total_rows: 1,
          truncated: false,
          min_freq: 3,
        },
      },
      method: { family: 'wordsketch', index_fingerprint: 'fp-123', statistics: [] },
      obj: [
        { word: 'beta', score: 3.5, frequency: 4 },
        { word: 'gamma', score: 1.5, f: 2 },
      ],
      amod: [{ word: 'rot', score: 2.1, frequency: 9 }],
    })
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('forwards relation limit and docset scope to the backend contract', async () => {
    const result = await getWordSketch({
      term: 'alpha',
      limit: 1,
      corpus: 'demo',
      docsetId: 'docset-1',
    })

    const { url, body } = requestFromCall()
    expect(url).toContain('/api/v1/analysis/wordsketch')
    expect(body).toEqual({
      term: 'alpha',
      limit: 1,
      corpus: 'demo',
      docset_id: 'docset-1',
    })
    expect(result.relations[0]?.words).toEqual([
      { word: 'beta', score: 3.5, frequency: 4 },
    ])
  })

  it('parses relations from the nested `sketches` map, skipping reserved keys', async () => {
    const result = await getWordSketch({ term: 'alpha' })
    const relationNames = result.relations.map((r) => r.relation).sort()
    // Relations are obj/amod — NOT the reserved keys 'sketches'/'method'.
    expect(relationNames).toEqual(['amod', 'obj'])
    expect(relationNames).not.toContain('sketches')
    expect(relationNames).not.toContain('method')
    // No throw on object-valued entries; words still parse (f -> frequency).
    const obj = result.relations.find((r) => r.relation === 'obj')
    expect(obj?.words).toEqual([
      { word: 'beta', score: 3.5, frequency: 4 },
      { word: 'gamma', score: 1.5, frequency: 2 },
    ])
    // The sibling method block is surfaced (snake_case fingerprint folded).
    expect(result.method?.family).toBe('wordsketch')
    expect(result.method?.indexFingerprint).toBe('fp-123')
  })

  it('falls back to a top-level relation map when `sketches` is absent (legacy)', async () => {
    stubFetch({
      obj: [{ word: 'beta', score: 3.5, frequency: 4 }],
      method: { family: 'wordsketch' },
    })
    const result = await getWordSketch({ term: 'alpha' })
    expect(result.relations.map((r) => r.relation)).toEqual(['obj'])
    expect(result.method?.family).toBe('wordsketch')
    // No backend gloss map in this legacy payload -> empty record, never a relation.
    expect(result.relationLabels).toEqual({})
  })

  it('surfaces the r9 `relations` gloss map as relationLabels (Finding 11)', async () => {
    const result = await getWordSketch({ term: 'alpha' })
    // The gloss map is flattened to code -> label and NOT mistaken for a relation.
    expect(result.relationLabels).toEqual({
      obj: 'Objekt von',
      amod: 'Adjektiv-Modifikatoren',
    })
    expect(result.relations.map((r) => r.relation)).not.toContain('relations')
  })

  it('surfaces per-relation completeness metadata', async () => {
    const result = await getWordSketch({ term: 'alpha' })
    const obj = result.relations.find((r) => r.relation === 'obj')
    expect(obj).toMatchObject({
      rowLimit: 2,
      totalCandidates: 12,
      totalRows: 2,
      truncated: true,
      minFreq: 3,
    })
  })

  it('mirrors the real backend codes (nk/sb_rev/mnr/cj_rev) into labels', async () => {
    stubFetch({
      sketches: {
        nk: [{ word: 'die', score: 2.7, frequency: 4 }],
        sb_rev: [{ word: 'sagte', score: 9.1, frequency: 2 }],
        mnr: [{ word: 'von', score: 5.0, frequency: 3 }],
        cj_rev: [{ word: 'und', score: 3.0, frequency: 4 }],
      },
      relations: {
        nk: { relation: 'nk', label: 'Kern/Attribut im Nominal (Nomen-Kern)' },
        sb_rev: { relation: 'sb_rev', label: 'Subjekt von' },
        mnr: { relation: 'mnr', label: 'hat als nachgestellten Modifikator' },
        cj_rev: { relation: 'cj_rev', label: 'Konjunkt (verbunden mit)' },
      },
    })
    const result = await getWordSketch({ term: 'Merkel' })
    expect(result.relationLabels.nk).toBe('Kern/Attribut im Nominal (Nomen-Kern)')
    expect(result.relationLabels.sb_rev).toBe('Subjekt von')
    expect(result.relationLabels.mnr).toBe('hat als nachgestellten Modifikator')
    expect(result.relationLabels.cj_rev).toBe('Konjunkt (verbunden mit)')
    // These codes are missing from the hardcoded UI map; the backend map covers them.
    expect(result.relations.map((r) => r.relation).sort()).toEqual([
      'cj_rev',
      'mnr',
      'nk',
      'sb_rev',
    ])
  })

  it('ignores a malformed `relations` block without throwing', async () => {
    stubFetch({
      sketches: { obj: [{ word: 'beta', score: 3.5, frequency: 4 }] },
      // Array shape (not an object map) and non-string labels must be tolerated.
      relations: [{ relation: 'obj' }],
    })
    const result = await getWordSketch({ term: 'alpha' })
    expect(result.relationLabels).toEqual({})
    expect(result.relations.map((r) => r.relation)).toEqual(['obj'])
  })
})

describe('getWordSketchDiff', () => {
  beforeEach(() => {
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('preserves frequency evidence from the dedicated diff endpoint', async () => {
    stubFetch({
      label_a: 'alpha',
      label_b: 'beta',
      relations: {
        obj: {
          only_a: [{ word: 'a-only', score: 3.5, f: 7 }],
          only_b: [{ word: 'b-only', score: 2.5, frequency: 4 }],
          common: [{ word: 'shared', score_a: 4, score_b: 2, delta: 2, f_a: 5, f_b: 9 }],
        },
      },
      relation_labels: { obj: 'Objekt von' },
      method: { family: 'wordsketch' },
    })

    const result = await getWordSketchDiff({
      termA: 'alpha',
      termB: 'beta',
      limit: 5,
      corpus: 'demo',
      docsetId: 'docset-1',
    })

    expect(requestFromCall().body).toEqual({
      term_a: 'alpha',
      term_b: 'beta',
      limit: 5,
      corpus: 'demo',
      docset_id: 'docset-1',
    })
    expect(result.relationLabels).toEqual({ obj: 'Objekt von' })
    expect(result.relations).toEqual([{
      relation: 'obj',
      onlyA: [{ word: 'a-only', score: 3.5, frequency: 7 }],
      onlyB: [{ word: 'b-only', score: 2.5, frequency: 4 }],
      common: [{
        word: 'shared',
        scoreA: 4,
        scoreB: 2,
        frequencyA: 5,
        frequencyB: 9,
        delta: 2,
      }],
    }])
  })
})
