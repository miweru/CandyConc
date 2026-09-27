import { describe, expect, it } from 'vitest'
import {
  deriveFilterSpecFromLegacy,
  filterSpecChips,
  filterSpecSummaryParts,
  legacyFiltersFromSpec,
  searchableFilterSpecText,
} from '@/lib/filterSpec'
import type { FilterSpec } from '@/api/client'

describe('filterSpec utilities', () => {
  it('renders equality, membership and range filters as human-readable chips', () => {
    const spec: FilterSpec = {
      genre: ['Zeitung', 'Blog'],
      year: { op: 'between', lo: 1900, hi: 1930 },
      source: 'Archiv',
      token_count: { op: '>=', value: 500 },
    }

    expect(filterSpecChips(spec)).toEqual([
      {
        field: 'genre',
        label: 'genre',
        valueLabel: 'Zeitung, Blog',
        title: 'genre: Zeitung, Blog',
        kind: 'in',
      },
      {
        field: 'year',
        label: 'year',
        valueLabel: '1900 bis 1930',
        title: 'year: 1900 bis 1930',
        kind: 'range',
      },
      {
        field: 'source',
        label: 'Quelle',
        valueLabel: 'Archiv',
        title: 'Quelle: Archiv',
        kind: 'equals',
      },
      {
        field: 'token_count',
        label: 'token_count',
        valueLabel: '>= 500',
        title: 'token_count: >= 500',
        kind: 'comparison',
      },
    ])
    expect(filterSpecSummaryParts(spec)).toContain('year: 1900 bis 1930')
    expect(searchableFilterSpecText(spec)).toContain('Zeitung, Blog')
  })

  it('preserves explicit generic specs instead of collapsing them into legacy filters', () => {
    const explicit: FilterSpec = { year: { op: 'between', lo: 1800, hi: 1850 } }

    expect(deriveFilterSpecFromLegacy({
      prompting_method: [],
      model: ['qwen'],
      register: [],
      source: [],
    }, explicit)).toEqual(explicit)
  })

  it('recovers only legacy buckets from a generic filter spec for compatibility UIs', () => {
    expect(legacyFiltersFromSpec({
      prompting_method: ['rewrite'],
      model: 'qwen',
      year: { op: '>=', value: 1900 },
    })).toEqual({
      prompting_method: ['rewrite'],
      model: ['qwen'],
      register: [],
      source: [],
    })
  })
})
