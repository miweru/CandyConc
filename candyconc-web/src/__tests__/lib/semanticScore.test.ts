import { describe, expect, it } from 'vitest'

import {
  deriveSemanticScoreKind,
  formatSemanticScore,
  semanticBarWidth,
  semanticScoreBand,
} from '@/lib/semanticScore'
import { applyLocale } from '@/i18n/locale'

describe('semanticScore — SEM-01 score-kind decision', () => {
  it('derives rerank from a lexical-overlap rerank method', () => {
    expect(
      deriveSemanticScoreKind({ rerank: { method: 'lexical_overlap_then_vector_score' } }),
    ).toBe('rerank')
  })

  it('derives cosine from a pure vector method', () => {
    expect(deriveSemanticScoreKind({ rerank: { method: 'vector_score' } })).toBe('cosine')
  })

  it('honours an explicit score_kind ahead of the method string', () => {
    expect(
      deriveSemanticScoreKind({ score_kind: 'cosine', rerank: { method: 'lexical_overlap' } }),
    ).toBe('cosine')
    expect(deriveSemanticScoreKind({ scoreKind: 'rerank' })).toBe('rerank')
  })

  it('defaults to the honest rerank kind for unknown/empty meta', () => {
    expect(deriveSemanticScoreKind({})).toBe('rerank')
    expect(deriveSemanticScoreKind(null)).toBe('rerank')
    expect(deriveSemanticScoreKind(undefined)).toBe('rerank')
  })
})

describe('semanticScore — kind-aware formatting', () => {
  // Scores follow the interface language (setup.ts runs German). Before the
  // i18n change they were dot-formatted in every language.
  it('formats a cosine as a percentage with one decimal', () => {
    expect(formatSemanticScore(0.953, 'cosine')).toBe('95,3\u00a0%')
    expect(formatSemanticScore(0.7, 'cosine')).toBe('70,0\u00a0%')
  })

  it('formats a rerank score as a raw value, never a percentage', () => {
    expect(formatSemanticScore(1.0, 'rerank')).toBe('1,00')
    expect(formatSemanticScore(2.0, 'rerank')).toBe('2,00')
    expect(formatSemanticScore(1.0, 'rerank')).not.toContain('%')
  })

  it('uses the English number format when the interface is English', () => {
    applyLocale('en')
    try {
      expect(formatSemanticScore(0.953, 'cosine')).toBe('95.3%')
      expect(formatSemanticScore(1.0, 'rerank')).toBe('1.00')
    } finally {
      applyLocale('de')
    }
  })

  it('a 1.0 rerank value never renders as 100% — the core SEM-01 lie', () => {
    const rerank = formatSemanticScore(1.0, 'rerank')
    expect(rerank).not.toBe('100.0%')
    expect(rerank).not.toContain('100')
  })
})

describe('semanticScore — colour band', () => {
  it('only a true cosine earns a high (green) band', () => {
    expect(semanticScoreBand(0.95, 'cosine')).toBe('high')
    expect(semanticScoreBand(0.7, 'cosine')).toBe('medium')
    expect(semanticScoreBand(0.5, 'cosine')).toBe('low')
  })

  it('a rerank score is never high, regardless of magnitude', () => {
    expect(semanticScoreBand(1.0, 'rerank')).toBe('low')
    expect(semanticScoreBand(2.0, 'rerank')).toBe('low')
    expect(semanticScoreBand(0.95, 'rerank')).toBe('low')
  })
})

describe('semanticScore — bar width', () => {
  it('maps a cosine to its percentage', () => {
    expect(semanticBarWidth(0.5, 'cosine')).toBe(50)
  })

  it('normalises a rerank score against the batch maximum', () => {
    expect(semanticBarWidth(1.0, 'rerank', 2.0)).toBe(50)
    expect(semanticBarWidth(2.0, 'rerank', 2.0)).toBe(100)
    expect(semanticBarWidth(1.0, 'rerank', 0)).toBe(0)
  })
})
