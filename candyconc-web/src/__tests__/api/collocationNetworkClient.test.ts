import { describe, it, expect, beforeEach, vi, type Mock } from 'vitest'
import { getCollocationNetwork } from '@/api/client'

let captured: Array<{ url: string }> = []

function stubFetch(payload: unknown) {
  captured = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const url = input instanceof Request ? input.url : String(input)
      captured.push({ url })
      return new Response(JSON.stringify(payload), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      })
    })
  )
}

const SAMPLE = {
  term: 'klima',
  measure: 'logdice',
  nodes: [
    { id: 'klima', freq: null, depth: 0 },
    { id: 'wandel', freq: 84, depth: 1 },
    { id: 'schutz', freq: 12, depth: 2 },
  ],
  edges: [
    { source: 'klima', target: 'wandel', weight: 11.2, measure: 'logdice' },
    { source: 'wandel', target: 'schutz', weight: 8.1, measure: 'logdice' },
  ],
  diagnostics: { node_count: 3, edge_count: 2, truncated: false },
}

describe('getCollocationNetwork', () => {
  beforeEach(() => {
    stubFetch(SAMPLE)
    ;(window.localStorage.getItem as Mock).mockReturnValue(null)
  })

  it('forwards term, measure, depth and docset scope to the backend contract', async () => {
    const result = await getCollocationNetwork({
      term: 'klima',
      window: 5,
      measure: 'logdice',
      maxNodes: 30,
      expandDepth: 2,
      corpus: 'demo',
      docsetId: 'docset-1',
    })

    const url = captured[0]?.url ?? ''
    expect(url).toContain('/api/v1/analysis/collocation_network')
    expect(url).toContain('term=klima')
    expect(url).toContain('measure=logdice')
    expect(url).toContain('max_nodes=30')
    expect(url).toContain('expand_depth=2')
    expect(url).toContain('corpus=demo')
    expect(url).toContain('docset_id=docset-1')

    expect(result.term).toBe('klima')
    expect(result.measure).toBe('logdice')
    expect(result.nodes).toHaveLength(3)
    expect(result.edges).toHaveLength(2)
    expect(result.nodes[0]).toEqual({ id: 'klima', freq: null, depth: 0 })
    expect(result.edges[0]).toEqual({
      source: 'klima',
      target: 'wandel',
      weight: 11.2,
      measure: 'logdice',
    })
  })

  it('defends against a partial payload without throwing', async () => {
    stubFetch({ term: 'leer' })
    const result = await getCollocationNetwork({ term: 'leer' })
    expect(result.nodes).toEqual([])
    expect(result.edges).toEqual([])
    expect(result.measure).toBe('logdice')
  })

  it('normalises missing weight/freq to null', async () => {
    stubFetch({
      term: 'x',
      measure: 'dice',
      nodes: [{ id: 'x' }, { id: 'y' }],
      edges: [{ source: 'x', target: 'y' }],
      diagnostics: {},
    })
    const result = await getCollocationNetwork({ term: 'x', measure: 'dice' })
    expect(result.nodes[0]).toEqual({ id: 'x', freq: null, depth: null })
    expect(result.edges[0]).toEqual({
      source: 'x',
      target: 'y',
      weight: null,
      measure: null,
    })
  })
})
