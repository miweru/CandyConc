import { describe, expect, it } from 'vitest'

import type { ProductCapabilityContract } from '@/api/client'
import {
  evidenceOpensKwic,
  evidenceSearch,
  evidenceToolCallId,
  pythonJsonDumps,
} from '@/utils/evidenceTarget'

// methoden C2 / inventar 4.2: a chip click searched the argument JSON.
const contract = {
  version: 'product-capabilities-v1',
  scope: 'x',
  fingerprint_sha256: 'a',
  cqlf_capability_contract: { version: 'v', current_level: '2', fingerprint_sha256: 'b' },
  capabilities: [
    { id: 'query.kwic', copilot_tools: ['run_cqlf_query', 'query_count'], operations: [] },
    { id: 'analysis.collocations', copilot_tools: ['collocate_stats'], operations: [] },
  ],
  copilot_control_tools: [],
} as unknown as ProductCapabilityContract

describe('evidence chip targets', () => {
  it('writes arguments like the backend json.dumps(sort_keys=True)', () => {
    expect(pythonJsonDumps({ query: 'freedom', limit: 3, corpus: 'sotu_en' }))
      .toBe('{"corpus": "sotu_en", "limit": 3, "query": "freedom"}')
  })

  it('opens the KWIC only for tools the contract binds to query.kwic', () => {
    expect(evidenceOpensKwic('run_cqlf_query', contract)).toBe(true)
    expect(evidenceOpensKwic('collocate_stats', contract)).toBe(false)
  })

  it('reads query, corpus and docset from the argument JSON', () => {
    const source = {
      id: 'E_run_cqlf_query_1',
      tool: 'run_cqlf_query',
      query: '{"corpus": "sotu_en", "docset_id": "ds1", "limit": 3, "query": "freedom"}',
      status: 'success',
    }
    expect(evidenceSearch(source)).toEqual({ term: 'freedom', corpus: 'sotu_en', docsetId: 'ds1' })
  })

  // The copilot names the active corpus also "default" or "active". The
  // interface calls it by its catalogue name, and the copilot stores its
  // docsets under that name: an alias in the arguments must not replace it.
  it('leaves the corpus of the interface for the aliases default and active', () => {
    for (const alias of ['default', 'active', 'Default']) {
      const source = {
        id: 'E1', tool: 'run_cqlf_query', status: 'success',
        query: `{"corpus": "${alias}", "docset_id": "ds1", "query": "freedom"}`,
      }
      expect(evidenceSearch(source)).toEqual({ term: 'freedom', docsetId: 'ds1' })
    }
  })

  it('finds the cited tool card by name and arguments, not by position', () => {
    const calls = [
      { id: 't1', name: 'collocate_stats', arguments: { term: 'peace', window: 5 } },
      { id: 't2', name: 'collocate_stats', arguments: { term: 'freedom', window: 5 } },
    ]
    const source = { id: 'E2', tool: 'collocate_stats', query: '{"term": "freedom", "window": 5}', status: 'success' }
    expect(evidenceToolCallId(source, calls)).toBe('t2')
  })

  it('matches a cut argument JSON by its prefix', () => {
    const long = 'x'.repeat(600)
    const calls = [
      { id: 'a', name: 'keyness', arguments: { note: 'y', target: long } },
      { id: 'b', name: 'keyness', arguments: { note: 'z', target: long } },
    ]
    const full = pythonJsonDumps(calls[1]!.arguments)
    const source = { id: 'E3', tool: 'keyness', query: `${full.slice(0, 509).trimEnd()}...`, status: 'success' }
    expect(evidenceToolCallId(source, calls)).toBe('b')
  })
})
