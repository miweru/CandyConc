/**
 * N-gram tab helper + routing tests.
 */
import { describe, it, expect, beforeEach, afterEach } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useUiStore } from '@/stores/ui'
import { applyLocale } from '@/i18n/locale'
import {
  NGRAM_SIZES,
  buildNgramCsv,
  buildNgramFormulaLines,
  buildNgramResultStateHeader,
  buildNgramResultStateNotice,
  buildNgramResultStateSummary,
  mapNgramDiffRows,
  mapNgramFrequencyRows,
  perMillion,
  formatPerMillion,
  sortNgramRows,
} from '@/components/analysis/ngrams'

describe('ngrams tab routing', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('routes to the ngrams analysis tab', () => {
    const store = useUiStore()
    store.setActiveTab('ngrams')
    expect(store.activeTab).toBe('ngrams')
  })

  it('exposes n-gram sizes 2 through 5, matching the release backend cap', () => {
    expect([...NGRAM_SIZES]).toEqual([2, 3, 4, 5])
  })
})

describe('mapNgramFrequencyRows', () => {
  it('maps backend rows (ngram/freq) and computes relative against tokenCount', () => {
    const rows = [
      { ngram: 'im Jahr', freq: 340, n: 2 },
      { ngram: 'der Welt', freq: 60, n: 2 },
    ]
    const mapped = mapNgramFrequencyRows(rows, { minFreq: 1, tokenCount: 1_000_000 })
    expect(mapped).toHaveLength(2)
    expect(mapped[0]).toEqual({ ngram: 'im Jahr', frequency: 340, relative: 340 / 1_000_000 })
    expect(perMillion(mapped[0]!.relative)).toBeCloseTo(340)
  })

  it('prefers the server target_total for pro-Million values', () => {
    const mapped = mapNgramFrequencyRows(
      [{ ngram: 'im Jahr', freq: 8, n: 2 }],
      { minFreq: 1, tokenCount: 1_000_000, targetTotal: 56_191 },
    )

    expect(mapped[0]!.relative).toBeCloseTo(8 / 56_191)
    expect(perMillion(mapped[0]!.relative)).toBeCloseTo((8 / 56_191) * 1_000_000)
  })

  it('applies the min-frequency filter and drops empty ngrams', () => {
    const rows = [
      { ngram: 'im Jahr', freq: 340 },
      { ngram: 'selten hier', freq: 2 },
      { ngram: '  ', freq: 500 },
    ]
    const mapped = mapNgramFrequencyRows(rows, { minFreq: 5, tokenCount: 1000 })
    expect(mapped.map((r) => r.ngram)).toEqual(['im Jahr'])
  })

  it('REFUSES the freq-sum denominator when no scope total is available', () => {
    // NGRAMS-METASUBCORPUS-PERMILLION: dividing by the sum of displayed freqs is
    // not the scope size and inflates per-million wildly. With no real
    // denominator we emit NaN so the UI renders '—' (formatPerMillion).
    const rows = [
      { ngram: 'a b', freq: 75 },
      { ngram: 'c d', freq: 25 },
    ]
    const mapped = mapNgramFrequencyRows(rows, { minFreq: 1, tokenCount: 0 })
    expect(Number.isNaN(mapped[0]!.relative)).toBe(true)
    expect(Number.isNaN(mapped[1]!.relative)).toBe(true)
    expect(formatPerMillion(mapped[0]!.relative)).toBe('—')
  })

  it('ignores malformed freq values instead of producing NaN', () => {
    const rows = [{ ngram: 'a b', freq: 'oops' }, { ngram: 'c d', freq: 10 }]
    const mapped = mapNgramFrequencyRows(rows, { minFreq: 1, tokenCount: 100 })
    expect(mapped.map((r) => r.ngram)).toEqual(['c d'])
  })
})

describe('mapNgramDiffRows', () => {
  const backendRows = [
    {
      ngram: 'im Jahr',
      n: 2,
      target_freq: 12,
      reference_freq: 2,
      target_per_million: 120,
      reference_per_million: 20,
      diff_per_million: 100,
      diff_abs: 100,
    },
    {
      ngram: 'der Welt',
      n: 2,
      target_freq: 1,
      reference_freq: 30,
      target_per_million: 10,
      reference_per_million: 300,
      diff_per_million: -290,
      diff_abs: 290,
    },
  ]

  it('maps the ngrams_diff row contract and sorts by absolute difference', () => {
    const mapped = mapNgramDiffRows(backendRows, { minFreq: 1, limit: 500 })
    expect(mapped.map((r) => r.ngram)).toEqual(['der Welt', 'im Jahr'])
    expect(mapped[0]).toMatchObject({
      targetFreq: 1,
      referenceFreq: 30,
      targetPerMillion: 10,
      referencePerMillion: 300,
      diffPerMillion: -290,
      diffAbs: 290,
    })
  })

  it('keeps rows where either side reaches minFreq', () => {
    const mapped = mapNgramDiffRows(backendRows, { minFreq: 5, limit: 500 })
    // 'der Welt' target_freq=1 but reference_freq=30 → kept.
    expect(mapped.map((r) => r.ngram)).toEqual(['der Welt', 'im Jahr'])
    const strict = mapNgramDiffRows(backendRows, { minFreq: 20, limit: 500 })
    expect(strict.map((r) => r.ngram)).toEqual(['der Welt'])
  })

  it('derives diffAbs from diff_per_million when the field is missing', () => {
    const mapped = mapNgramDiffRows(
      [{ ngram: 'x y', target_freq: 5, reference_freq: 0, diff_per_million: -42 }],
      { minFreq: 1, limit: 10 }
    )
    expect(mapped[0]!.diffAbs).toBe(42)
  })

  it('applies the row limit', () => {
    const mapped = mapNgramDiffRows(backendRows, { minFreq: 1, limit: 1 })
    expect(mapped).toHaveLength(1)
    expect(mapped[0]!.ngram).toBe('der Welt')
  })
})

describe('sortNgramRows', () => {
  it('sorts by frequency or relative without mutating the input', () => {
    const rows = [
      { ngram: 'a b', frequency: 10, relative: 0.9 },
      { ngram: 'c d', frequency: 20, relative: 0.1 },
    ]
    expect(sortNgramRows(rows, 'frequency')[0]!.ngram).toBe('c d')
    expect(sortNgramRows(rows, 'relative')[0]!.ngram).toBe('a b')
    expect(rows[0]!.ngram).toBe('a b')
  })
})

describe('buildNgramResultStateNotice', () => {
  it('surfaces truncated backend result metadata', () => {
    const notice = buildNgramResultStateNotice({
      truncated: true,
      rowLimit: 500,
      totalCandidates: 1200,
    })
    expect(notice).toBe('Begrenzte Ergebnisliste: 500 von 1.200 Kandidaten angezeigt.')
  })

  it('stays quiet for complete result metadata', () => {
    expect(buildNgramResultStateNotice({ truncated: false, rowLimit: 500 })).toBeNull()
  })

  it('serializes result-state metadata for exports', () => {
    expect(buildNgramResultStateHeader({
      truncated: true,
      rowLimit: 500,
      totalCandidates: 1200,
      loadedRows: 500,
    })).toEqual([
      '# Result.truncated: true',
      '# Result.row_limit: 500',
      '# Result.total_candidates: 1200',
      '# Result.loaded_rows: 500',
    ])
  })
})

describe('buildNgramResultStateSummary', () => {
  it('surfaces displayed rows, the min-frequency filter and backend completeness', () => {
    expect(buildNgramResultStateSummary({
      truncated: false,
      rowLimit: 500,
      totalCandidates: 13,
      loadedRows: 13,
    }, {
      displayedRows: 3,
      minFreq: 5,
      mode: 'frequency',
    })).toBe(
      '3 angezeigte N-Gramme nach Mindestfrequenz ≥ 5 · 13 vom Backend geladene Kandidaten · 13 Kandidaten insgesamt · Zeilenlimit 500 · Backend-Ergebnis nicht gekappt.'
    )
  })

  it('marks capped backend result summaries explicitly', () => {
    expect(buildNgramResultStateSummary({
      truncated: true,
      rowLimit: 500,
      totalCandidates: 1200,
      loadedRows: 500,
    }, {
      displayedRows: 500,
      minFreq: 1,
      mode: 'diff',
    })).toContain('Backend-Ergebnis gekappt')
  })
})

describe('buildNgramCsv', () => {
  it('joins header lines, columns and rows', () => {
    const csv = buildNgramCsv(['# Header'], ['ngram', 'frequency'], [['im Jahr', 340]])
    expect(csv).toBe('# Header\nngram,frequency\nim Jahr,340')
  })

  it('escapes cells containing commas or quotes', () => {
    const csv = buildNgramCsv([], ['ngram'], [['sagt, "ja"']])
    expect(csv.split('\n')[1]).toBe('"sagt, ""ja"""')
  })
})

describe('buildNgramFormulaLines', () => {
  afterEach(() => {
    applyLocale('de')
  })

  // The contrast divides by the n-gram positions of each side, the sum of
  // (L_d - n + 1) over its documents, not by the token count of the subcorpus.
  it('describes the contrast rate by n-gram positions without a method block', () => {
    const lines = buildNgramFormulaLines(null, 'diff')
    const rateLine = lines.find((line) => line.startsWith('# per_million'))
    expect(rateLine).toContain('n-gram positions')
    expect(rateLine).toContain('(tokens - n + 1)')
    expect(lines.join('\n')).not.toContain('tokenCount')
  })

  it('keeps the token count as the basis of the frequency list without a method block', () => {
    expect(buildNgramFormulaLines(null, 'frequency')).toContain('# per_million = frequency * 1e6 / tokenCount')
  })

  it('names the rate basis and the positions of the server method block', () => {
    const lines = buildNgramFormulaLines({
      family: 'ngrams_diff',
      statistics: [{ key: 'frequency', name: 'Frequency', latex_formula: 'f' }],
      target_total: 92,
      reference_total: 70,
      rate_basis: 'ngram_positions_per_order',
      ngram_positions_target: { '2': 88 },
      ngram_positions_reference: { '2': 66 },
      indexFingerprint: 'abc123abc123',
    }, 'diff')
    expect(lines).toContain('# Frequency = f')
    expect(lines).toContain('# rate_basis: ngram_positions_per_order')
    expect(lines).toContain('# ngram_positions_target: 2=88')
    expect(lines).toContain('# ngram_positions_reference: 2=66')
    expect(lines).toContain('# indexFingerprint: abc123abc123')
  })

  it('writes the method header in the interface language', () => {
    applyLocale('en')
    const [header] = buildNgramFormulaLines({ family: 'ngrams' }, 'frequency')
    expect(header).toBe('# Method (source: server provenance)')
  })
})
