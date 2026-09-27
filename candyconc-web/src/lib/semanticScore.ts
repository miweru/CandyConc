/**
 * Semantic score KIND — one shared decision both the analysis tab and the
 * copilot renderer reflect identically (sibling-surface parity).
 *
 * The `/analysis/embedding_search` response carries TWO different kinds of
 * number in `row.score`, depending on the active backend/path:
 *   - a true vector COSINE similarity, bounded to [-1, 1]; rendering it as a
 *     percentage with a green colour band is honest.
 *   - a lexical-overlap / document-relevance RERANK score (e.g. 1.0, 2.0) that
 *     merely happens to land inside the cosine window. Painting a rerank value
 *     of 1.0 as a green "100 % perfect match" is a lie about what was measured.
 *
 * Numeric range alone can't tell the two apart (a rerank 1.0 looks like a cosine
 * 1.0). So the KIND must travel WITH the score. The backend already ships it in
 * `meta.rerank.method`; an explicit `score_kind` field (if a backend adds one)
 * is honoured first for forward-compatibility. Unknown → 'rerank', so an
 * unlabelled score is never dressed up as a cosine percentage.
 */

import { t } from '@/i18n'
import { formatDecimal, formatPercent } from '@/i18n/format'

export type SemanticScoreKind = 'cosine' | 'rerank'

interface RerankMetaLike {
  method?: unknown
  enabled?: unknown
  [key: string]: unknown
}

interface SemanticMetaLike {
  score_kind?: unknown
  scoreKind?: unknown
  rerank?: RerankMetaLike | null
  [key: string]: unknown
}

function normaliseKind(value: unknown): SemanticScoreKind | null {
  if (typeof value !== 'string') return null
  const v = value.trim().toLowerCase()
  if (v === 'cosine' || v === 'vector' || v === 'similarity') return 'cosine'
  if (v === 'rerank' || v === 'lexical' || v === 'relevance' || v === 'overlap') return 'rerank'
  return null
}

/**
 * Decide whether the scores in a semantic-search result are true cosines or a
 * lexical/rerank score. Source of truth, in order:
 *   1. an explicit `score_kind` / `scoreKind` on the meta (forward-compat),
 *   2. the `meta.rerank.method` string the backend already emits,
 *   3. default 'rerank' (honest fallback — never fake a cosine %).
 */
export function deriveSemanticScoreKind(meta: SemanticMetaLike | null | undefined): SemanticScoreKind {
  if (!meta || typeof meta !== 'object') return 'rerank'
  const explicit = normaliseKind(meta.score_kind) ?? normaliseKind(meta.scoreKind)
  if (explicit) return explicit
  const method = meta.rerank?.method
  if (typeof method === 'string') {
    const m = method.toLowerCase()
    // A method that reranks by lexical overlap (even if it then orders by a
    // vector score) does NOT make the surfaced `score` a clean cosine: on the
    // spacy/lexical path it is a document-relevance / hit count.
    if (m.includes('lexical') || m.includes('overlap') || m.includes('rerank')) return 'rerank'
    if (m.includes('cosine') || m.includes('vector_score')) return 'cosine'
  }
  return 'rerank'
}

/** Cosine similarity is bounded to [-1, 1] (allow a hair of float slack). */
export function isBoundedCosine(score: number): boolean {
  return Number.isFinite(score) && score >= -1.0001 && score <= 1.0001
}

/**
 * Bar width (0–100) for the score's strength. A cosine maps to its [0, 100]
 * percentage; a rerank score has no upper bound, so the caller passes the batch
 * `max` to normalise against (0 → no bar). Out-of-range cosines get 0 width.
 */
export function semanticBarWidth(score: number, kind: SemanticScoreKind, max = 0): number {
  if (!Number.isFinite(score)) return 0
  if (kind === 'cosine') {
    if (!isBoundedCosine(score)) return 0
    return Math.min(100, Math.max(0, score * 100))
  }
  if (max <= 0 || score <= 0) return 0
  return Math.min(100, Math.max(0, (score / max) * 100))
}

/**
 * Human label for a score. A cosine renders as a percentage in the interface
 * language ("87,3 %" or "87.3%"). A rerank score renders as a raw value with NO
 * percent sign: it is a relevance rank, not a similarity proportion.
 */
export function formatSemanticScore(score: number, kind: SemanticScoreKind): string {
  if (!Number.isFinite(score)) return '–'
  if (kind === 'cosine' && isBoundedCosine(score)) {
    const share = Math.min(1, Math.max(0, score))
    // SEM-03: one precision convention (1 decimal) across both surfaces.
    return formatPercent(share, 1)
  }
  // Rerank (or an out-of-range "cosine"): a raw relevance score, no %.
  return formatDecimal(score, 2)
}

/** Short kind tag shown next to a score so the unit is unambiguous. */
export function semanticScoreUnitLabel(kind: SemanticScoreKind): string {
  return kind === 'cosine' ? t('analysis.charts.cosine') : t('analysis.charts.relevance')
}

/**
 * High/medium/low colour band — ONLY a true cosine earns a green "high" band.
 * A rerank score is always neutral so it is never painted as a "perfect match".
 */
export function semanticScoreBand(score: number, kind: SemanticScoreKind): 'high' | 'medium' | 'low' {
  if (kind !== 'cosine' || !isBoundedCosine(score)) return 'low'
  if (score >= 0.8) return 'high'
  if (score >= 0.6) return 'medium'
  return 'low'
}
