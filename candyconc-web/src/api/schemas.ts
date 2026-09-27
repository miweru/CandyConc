/**
 * Zod Schemas for API Response Validation
 *
 * Runtime type validation for all API responses to catch
 * backend/frontend contract mismatches early.
 */

import { z } from 'zod'

// ============================================
// Query API Schemas
// ============================================

// ============================================
// Statistical Provenance (F1) — `method` block
// ============================================
//
// Analysis responses (keyness/collocates/contrast/ngrams_diff/wordsketch and
// the analysis-job rows envelope) may carry a top-level `method` block that is
// the single source of truth for statistical provenance + reproducibility.
// Every field is optional so an older/partial backend never crashes the client.
export const MethodStatSchema = z.object({
  // Stable statistic identifier (e.g. `ll_signed`, `logdice`). The backend
  // emits an ordered `statistics` array where each entry carries its own key.
  key: z.string().optional(),
  name: z.string().optional(),
  latex_formula: z.string().optional(),
  formula_mathml: z.string().optional(),
  smoothing: z.string().nullable().optional(),
  sort_key: z.string().nullable().optional(),
}).passthrough()

export const MethodBlockSchema = z.object({
  family: z.string().optional(),
  // Ordered per-statistic descriptors; each entry carries its own `key`. This
  // is the authoritative backend shape (analysis_defaults.build_method_block).
  statistics: z.array(MethodStatSchema).optional(),
  default_sort: z.string().nullable().optional(),
  // Back-compat: tolerate a legacy object-keyed `stats` map from an older
  // backend without crashing (callers read `statistics` first).
  stats: z.record(z.string(), MethodStatSchema).optional(),
  target_total: z.number().nullable().optional(),
  reference_total: z.number().nullable().optional(),
  window: z.number().nullable().optional(),
  within_sentence: z.boolean().nullable().optional(),
  indexFingerprint: z.string().nullable().optional(),
  // Tolerate a snake_case alias from the backend without losing the value.
  index_fingerprint: z.string().nullable().optional(),
}).passthrough()

export const QueryHitSchema = z.object({
  position: z.number(),
  left: z.string(),
  match: z.string(),
  right: z.string(),
  doc_id: z.string(),
  doc_title: z.string().optional(),
  metadata: z.record(z.string(), z.string()).optional(),
  collocate_offsets: z.array(z.number()).optional(),
  match_offsets: z.array(z.number()).optional(),
})

export const QueryResultSchema = z.object({
  hits: z.array(QueryHitSchema),
  total: z.number(),
  query_time_ms: z.number(),
})

export const SuggestionsResponseSchema = z.object({
  suggestions: z.array(z.string()).default([]),
})

// Raw backend response for query endpoint
export const RawQueryRowSchema = z.object({
  left: z.string(),
  kw: z.string(),
  right: z.string(),
  pos: z.number().optional(),
  doc_id: z.union([z.number(), z.string()]).optional(),
  doc: z.string().optional(),
  meta: z.record(z.string(), z.unknown()).optional(),
})

// ============================================
// Document API Schemas
// ============================================

export const DocSnippetSchema = z.object({
  doc_id: z.number(),
  doc: z.string(),
  meta: z.record(z.string(), z.string()),
  pos: z.number(),
  ctx: z.number(),
  doc_start: z.number(),
  doc_end: z.number(),
  start_pos: z.number(),
  end_pos: z.number(),
  left: z.string(),
  kw: z.string(),
  right: z.string(),
  text: z.string(),
})

export const DocumentSchema = z.object({
  doc_id: z.number(),
  doc: z.string(),
  meta: z.record(z.string(), z.string()),
  text: z.string(),
  doc_start: z.number().optional(),
  doc_end: z.number().optional(),
})

/** Eine Zeile im Dokumentverzeichnis des Lesers. */
export const DocumentListItemSchema = z.object({
  doc_id: z.number(),
  doc: z.string(),
  meta: z.record(z.string(), z.string()).default({}),
  token_count: z.number(),
  preview: z.string().default(''),
})

/**
 * Fields the server names for the reader, from the metadata schema of the
 * corpus: title_field heads a document, label_fields tell documents apart,
 * the most general first. Older servers do not send them.
 */
export const ReaderFieldsSchema = z.object({
  title_field: z.string().nullable().default(null),
  label_fields: z.array(z.string()).default([]),
  basis: z.string().optional(),
})

export const DocumentListSchema = z.object({
  total: z.number(),
  offset: z.number(),
  limit: z.number(),
  items: z.array(DocumentListItemSchema),
  reader_fields: ReaderFieldsSchema.optional(),
})


// ============================================
// Alignment API Schemas
// ============================================

export const AlignmentSentenceSchema = z.object({
  index: z.number(),
  start_pos: z.number(),
  end_pos: z.number(),
  text: z.string(),
  token_count: z.number(),
})

export const AlignmentReferenceSchema = z.object({
  doc_id: z.number(),
  doc: z.string(),
  meta: z.record(z.string(), z.string()),
  sentence_count: z.number(),
  window_start: z.number(),
  window_end: z.number(),
  focus_sentence_index: z.number().nullable(),
  sentences: z.array(AlignmentSentenceSchema),
})

export const AlignmentPairSchema = z.object({
  ref_index: z.number().nullable(),
  var_index: z.number().nullable(),
  ref_text: z.string(),
  var_text: z.string(),
  ref_start: z.number().nullable(),
  ref_end: z.number().nullable(),
  var_start: z.number().nullable(),
  var_end: z.number().nullable(),
  med: z.number().nullable(),
  similarity: z.number().nullable(),
  norm_med: z.number().nullable(),
})

export const AlignmentSummarySchema = z.object({
  alignment_cost: z.number(),
  aligned_pairs: z.number(),
  avg_med: z.number().nullable(),
  avg_similarity: z.number().nullable(),
})

export const AlignmentVariantSchema = z.object({
  doc_id: z.number(),
  doc: z.string(),
  meta: z.record(z.string(), z.string()),
  model: z.string().default(''),
  axis: z.string().optional(),
  axis_value: z.string().optional(),
  label: z.string().optional(),
  text_type: z.string(),
  sentence_count: z.number(),
  window_start: z.number(),
  window_end: z.number(),
  summary: AlignmentSummarySchema,
  pairs: z.array(AlignmentPairSchema),
})

export const AlignmentRefDocResultSchema = z.object({
  ref_doc: z.number(),
  corpus: z.string(),
  focus_pos: z.number().nullable(),
  focus_doc_id: z.number().nullable(),
  focus_resolution: z.enum(['not_requested', 'reference_sentence', 'variant_sentence_resolved']).optional(),
  alignment_scope: z.literal('complete_document').optional(),
  confidence_threshold: z.number().min(0).max(1).optional(),
  reference: AlignmentReferenceSchema,
  variants: z.array(AlignmentVariantSchema),
  variant_count: z.number(),
})

// ============================================
// KWIC Parallel Projection API Schemas
// ============================================

export const ParallelKwicVariantSchema = z.object({
  doc_id: z.number(),
  model: z.string().default(''),
  axis: z.string().optional(),
  axis_value: z.string().optional(),
  label: z.string().optional(),
  prompting_method: z.string().optional(),
  text_type: z.string(),
  left: z.string(),
  kw: z.string(),
  right: z.string(),
  matched: z.boolean(),
  med: z.number().nullable(),
  norm_med: z.number().nullable(),
  similarity: z.number().nullable(),
})

export const ParallelKwicResultSchema = z.object({
  ref_doc: z.number(),
  base_doc_id: z.number(),
  variants: z.array(ParallelKwicVariantSchema),
})

// ============================================
// Analysis API Schemas
// ============================================

export const CollocationSchema = z.object({
  word: z.string(),
  frequency: z.number(),
  score: z.number(),
  measure: z.string(),
})

// Raw backend response for collocations
export const RawCollocationRowSchema = z.object({
  word: z.string(),
  f: z.number().optional(),
  observed: z.number().optional(),
  expected: z.number().nullable().optional(),
  frequency: z.number().optional(),
  mi: z.number().nullable().optional(),
  // MI3 (Oakes 1998): log2(O11^3 / E11). Optional for older engines.
  mi3: z.number().nullable().optional(),
  lmi: z.number().nullable().optional(),
  npmi: z.number().nullable().optional(),
  z: z.number().nullable().optional(),
  chi2_cell: z.number().nullable().optional(),
  t: z.number().nullable().optional(),
  ll: z.number().nullable().optional(),
  dice: z.number().nullable().optional(),
  // Corpus-size-comparable logDice (recommended). Optional for older indexes.
  logdice: z.number().nullable().optional(),
  // Directional delta-P (F3). delta_p_nc = P(collocate|node) advantage,
  // delta_p_cn = P(node|collocate) advantage. Optional for older engines.
  delta_p_nc: z.number().nullable().optional(),
  delta_p_cn: z.number().nullable().optional(),
})

export const CollocationsResponseSchema = z.object({
  rows: z.array(RawCollocationRowSchema).default([]),
  method: MethodBlockSchema.optional(),
  // Bounded-result meta of the paged sync route (BoundedMeta). Optional so
  // older backends without the envelope keep validating.
  row_limit: z.number().nullable().optional(),
  total_candidates: z.number().nullable().optional(),
  truncated: z.boolean().optional(),
  offset: z.number().optional(),
  limit: z.number().optional(),
})

// Collocation network (graph) — defensive: every new field optional so a
// missing/partial payload never crashes the client.
export const CollocationNetworkNodeSchema = z.object({
  id: z.string(),
  freq: z.number().nullable().optional(),
  depth: z.number().nullable().optional(),
})

export const CollocationNetworkEdgeSchema = z.object({
  source: z.string(),
  target: z.string(),
  weight: z.number().nullable().optional(),
  measure: z.string().optional(),
})

export const CollocationNetworkResponseSchema = z.object({
  term: z.string().default(''),
  measure: z.string().default('logdice'),
  nodes: z.array(CollocationNetworkNodeSchema).default([]),
  edges: z.array(CollocationNetworkEdgeSchema).default([]),
  diagnostics: z.record(z.string(), z.unknown()).default({}),
  // Statistical provenance (r7 D-routes). Defensive: older backends omit it.
  method: MethodBlockSchema.optional(),
})

// Trend / Diachronie (POST /analysis/trend) — defensive: numerische Felder
// tolerieren fehlende Werte älterer Backends nicht (die Route liefert sie
// immer), aber warnings/method bleiben optional.
export const TrendPeriodSchema = z.object({
  period: z.string(),
  documents: z.number().default(0),
  hits: z.number().default(0),
  tokens: z.number().default(0),
  per_million: z.number().default(0),
  ci_low: z.number().default(0),
  ci_high: z.number().default(0),
  /** Metadata values of the date field that form the period (period_values). */
  values: z.array(z.union([z.string(), z.number()])).optional(),
})

export const TrendResponseSchema = z.object({
  query: z.string().default(''),
  date_field: z.string().default(''),
  granularity: z.string().default('year'),
  periods: z.array(TrendPeriodSchema).default([]),
  warnings: z.array(z.string()).default([]),
  method: MethodBlockSchema.optional(),
})

export const FrequencyItemSchema = z.object({
  item: z.string(),
  frequency: z.number(),
  relative: z.number(),
})

export const RawFrequencyRowSchema = z.object({
  word: z.string(),
  f: z.number(),
})

export const FrequencyResponseSchema = z.object({
  rows: z.array(RawFrequencyRowSchema).default([]),
  group_by: z.enum(['word', 'lemma', 'pos']).optional(),
  pos: z.string().optional(),
  basis: z.string().optional(),
  case_policy: z.string().optional(),
  filtered_token_policy: z.string().optional(),
  row_limit: z.number().optional(),
  total_candidates: z.number().optional(),
  truncated: z.boolean().optional(),
})

export const AnalysisLimitationSchema = z.object({
  code: z.string().optional(),
  message: z.string().optional(),
  // The backend's honest "not_found" dispersion limitation sends detail:null;
  // it must validate (not throw a generic "Fehler beim Laden").
  detail: z.string().nullable().optional(),
}).passthrough()

export const DispersionResultSchema = z.object({
  term: z.string(),
  partitions: z.array(z.number()),
  // dp is the RAW Gries DP over documents (0 = evenly dispersed, 1 = clustered).
  dp: z.number(),
  // Normalized Gries DP (corrects for the number of parts); optional for older indexes.
  dpnorm: z.number().nullable().optional(),
  // Classification string derived from dp: even / fairly_even / fairly_clustered / clustered.
  classification: z.string().nullable().optional(),
  // Per-document token counts the DP was computed over.
  doc_sizes: z.array(z.number()).nullable().optional(),
  // Unit the dispersion was computed over (e.g. "document").
  unit: z.string().nullable().optional(),
  // Optional legacy DP over equal-width positional windows.
  positional_dp_windowed: z.number().nullable().optional(),
  positional_window_count: z.number().nullable().optional(),
  basis: z.string().optional(),
  token_count: z.number().optional(),
  fallback: z.boolean().optional(),
  partial: z.boolean().optional(),
  // Dispersion family (FT-DISPERSION-FAMILY, r9): all optional so older backends
  // (DP/DPnorm only) still validate. nullable for explicit "not computed".
  juilland_d: z.number().nullable().optional(),
  carroll_d2: z.number().nullable().optional(),
  range_prop: z.number().nullable().optional(),
  vc: z.number().nullable().optional(),
  limitations: z.array(AnalysisLimitationSchema).optional(),
}).passthrough()

export const DispersionOffsetsResponseSchema = z.object({
  offsets: z.array(z.number()).default([]),
  basis: z.string().optional(),
  token_count: z.number().nullable().optional(),
  fallback: z.boolean().optional(),
  partial: z.boolean().optional(),
  // The page is a strict subset of the full hit set when a high-frequency term
  // is capped at the sync limit (e.g. 500 of 919). The backend reports the full
  // `total` plus `truncated`/`next_offset` so the UI can say "500 von 919".
  truncated: z.boolean().optional(),
  total: z.number().optional(),
  next_offset: z.number().nullable().optional(),
  limitations: z.array(AnalysisLimitationSchema).optional(),
})

export const NgramSchema = z.object({
  tokens: z.array(z.string()),
  frequency: z.number(),
  relative: z.number(),
  n: z.number(),
})

export const RawNgramRowSchema = z.object({
  ngram: z.string(),
  freq: z.number(),
  n: z.number(),
})

export const NgramsResponseSchema = z.object({
  rows: z.array(RawNgramRowSchema).default([]),
  method: MethodBlockSchema.optional(),
})

export const KeynessItemSchema = z.object({
  word: z.string(),
  chi2_cell: z.number().nullable(),
  ll: z.number().nullable(),
})

export const RawKeynessRowSchema = z.object({
  word: z.string(),
  chi2_cell: z.number().nullable(),
  // Keep unrelated forward-compatible fields, but reject the retired wire name.
  mi2: z.never().optional(),
  // Full 2x2 Pearson chi-square (r7 #2). Defensive: optional/nullable because
  // older backends emit only the per-cell chi2_cell.
  chi2: z.number().nullable().optional(),
  chi2_signed: z.number().nullable().optional(),
  target_freq: z.number().optional(),
  reference_freq: z.number().optional(),
  target_per_million: z.number().optional(),
  reference_per_million: z.number().optional(),
  diff_per_million: z.number().optional(),
  direction: z.string().optional(),
  chi2_cell_signed: z.number().nullable().optional(),
  ll_signed: z.number().nullable().optional(),
  ll: z.number().nullable().optional(),
  // Effect size (log ratio) with its 95% confidence interval.
  log_ratio: z.number().nullable().optional(),
  log_ratio_ci_low: z.number().nullable().optional(),
  log_ratio_ci_high: z.number().nullable().optional(),
  // Significance and multiple-comparison correction.
  p_value: z.number().nullable().optional(),
  q_value: z.number().nullable().optional(),
  bic: z.number().nullable().optional(),
  // Low-reliability flag (FT-KEYNESS-RESEARCH, r9): expected cell < 5, so the
  // chi-square approximation is shaky (optionally Fisher-exact). Defensive.
  low_reliability: z.boolean().nullable().optional(),
  p_method: z.string().nullable().optional(),
}).passthrough()

export const KeynessResponseSchema = z.object({
  rows: z.array(RawKeynessRowSchema).default([]),
  limitations: z.array(AnalysisLimitationSchema).optional(),
  method: MethodBlockSchema.optional(),
})

// ============================================
// Word Sketch API Schemas
// ============================================

export const WordSketchWordSchema = z.object({
  word: z.string(),
  score: z.number().nullable(),
  frequency: z.number().nullable(),
})

export const WordSketchRelationSchema = z.object({
  relation: z.string(),
  words: z.array(WordSketchWordSchema),
  rowLimit: z.number().nullable().optional(),
  totalCandidates: z.number().nullable().optional(),
  totalRows: z.number().nullable().optional(),
  truncated: z.boolean().nullable().optional(),
  minFreq: z.number().nullable().optional(),
})

export const WordSketchResultSchema = z.object({
  term: z.string(),
  relations: z.array(WordSketchRelationSchema),
})

export const RawWordSketchWordSchema = z.object({
  word: z.string(),
  score: z.number().optional(),
  f: z.number().optional(),
})

export const RawWordSketchResponseSchema = z.record(
  z.string(),
  z.array(RawWordSketchWordSchema)
)

// ============================================
// Docset API Schemas
// ============================================

export const DocsetFromSearchResultSchema = z.object({
  docset_id: z.string(),
  doc_count: z.number(),
  hit_doc_count: z.number().optional(),
  ref_doc_count: z.number().optional(),
  token_count: z.number().optional(),
})

export const DocsetIntersectionGroupResultSchema = z.object({
  label: z.string(),
  docset_id: z.string(),
  doc_count: z.number(),
  ref_count: z.number(),
  token_count: z.number().optional(),
})

export const DocsetIntersectionHumanSchema = z.object({
  docset_id: z.string(),
  doc_count: z.number(),
  token_count: z.number().optional(),
})

export const DocsetIntersectionResultSchema = z.object({
  intersection_count: z.number(),
  groups: z.array(DocsetIntersectionGroupResultSchema),
  human: DocsetIntersectionHumanSchema.optional(),
})

// ============================================
// Parallel Groups API Schemas
// ============================================

export const ParallelGroupModelSchema = z.object({
  model: z.string().default(''),
  axis: z.string().optional(),
  axis_value: z.string().optional(),
  label: z.string().optional(),
  count: z.number(),
})

export const ParallelGroupVariantSchema = z.object({
  doc_id: z.number(),
  label: z.string(),
  provenance: z.string().optional(),
})

export const ParallelGroupSchema = z.object({
  ref_doc: z.number(),
  doc_count: z.number(),
  doc_ids: z.array(z.number()),
  human_doc_id: z.number().nullable(),
  variant_doc_ids: z.array(z.number()),
  variants: z.array(ParallelGroupVariantSchema).optional(),
  models: z.array(ParallelGroupModelSchema),
  text_types: z.record(z.string(), z.number()),
  sources: z.array(z.string()),
  label: z.string().optional(),
})

export const ParallelGroupsResultSchema = z.object({
  total: z.number(),
  groups: z.array(ParallelGroupSchema),
})

// ============================================
// Semantic Search API Schemas
// ============================================

export const SemanticResultSchema = z.object({
  doc_id: z.string(),
  chunk_id: z.string(),
  text: z.string(),
  score: z.number(),
  metadata: z.record(z.string(), z.unknown()).optional(),
})

export const RawSemanticRowSchema = z.object({
  kw: z.string(),
  score: z.number().optional(),
  doc_id: z.union([z.number(), z.string()]).optional(),
  chunk_id: z.union([z.number(), z.string()]).optional(),
  meta: z.record(z.string(), z.unknown()).nullable().optional(),
})

export const SemanticSearchMetaSchema = z.object({
  exactness: z.enum(['exact', 'approximate', 'unknown']).optional(),
  candidateGeneration: z.object({
    backend: z.string().optional(),
    level: z.string().optional(),
    method: z.string().optional(),
    indexType: z.string().optional(),
    searchMode: z.enum(['exact', 'approximate', 'unknown']).optional(),
    requestedTopN: z.number().optional(),
    requestedContext: z.number().optional(),
    candidateLimit: z.number().optional(),
    candidateCount: z.number().optional(),
    totalVectors: z.number().optional(),
    lexicalSeedCount: z.number().optional(),
    oversample: z.number().optional(),
  }).passthrough().optional(),
  rerank: z.object({
    enabled: z.boolean().optional(),
    method: z.string().optional(),
    inputCount: z.number().optional(),
    outputCount: z.number().optional(),
  }).passthrough().optional(),
  filtering: z.object({
    docsetApplied: z.boolean().optional(),
    docsetDocCount: z.number().nullable().optional(),
    minScore: z.number().optional(),
    postFilterCandidateCount: z.number().optional(),
  }).passthrough().optional(),
}).passthrough()

export const SemanticSearchResponseSchema = z.object({
  rows: z.array(RawSemanticRowSchema),
  meta: SemanticSearchMetaSchema.optional(),
})

// ============================================
// Distributional Thesaurus (F8) — similar words
// ============================================
//
// GET /api/v1/semantic/similar_words returns a ranked neighbour list for a
// term. Every field beyond `word` is optional so a partial/older backend never
// crashes the client (corpus_frequency may be absent if the join is skipped).
export const SimilarWordSchema = z.object({
  word: z.string(),
  score: z.number().nullable().optional(),
  corpus_frequency: z.number().nullable().optional(),
  shared_query_vector: z.boolean().nullable().optional(),
}).passthrough()

export const SimilarWordsResponseSchema = z.object({
  status: z.string().optional(),
  term: z.string().optional(),
  backend: z.string().nullable().optional(),
  neighbours: z.array(SimilarWordSchema).default([]),
  // Tolerate a US-spelled alias without losing the value.
  neighbors: z.array(SimilarWordSchema).optional(),
}).passthrough()

// ============================================
// KWIC Annotation Layer (F7)
// ============================================
//
// Row-level annotations keyed by a stable `row_id` (`${file}:${pos}`, fallback
// text hash). A row carries at most ONE category plus a free-text note (per
// spec). Every field is optional/defensive so a partial backend never crashes
// the client; span-level annotation is explicitly future work.
export const AnnotationCategorySchema = z.object({
  id: z.string(),
  label: z.string(),
  color: z.string().optional(),
  shortcut: z.string().nullable().optional(),
}).passthrough()

export const AnnotationSchemeSchema = z.object({
  categories: z.array(AnnotationCategorySchema).default([]),
  revision: z.number().int().nonnegative().default(0),
}).passthrough()

export const AnnotationSchemeRemovalImpactSchema = z.object({
  category_id: z.string(),
  label: z.string(),
  annotation_count: z.number().int().nonnegative(),
  corpus_count: z.number().int().nonnegative(),
  annotator_count: z.number().int().nonnegative(),
}).passthrough()

export const AnnotationSchemePreviewSchema = z.object({
  status: z.enum(['ready', 'stale']),
  categories: z.array(AnnotationCategorySchema).default([]),
  revision: z.number().int().nonnegative(),
  removals: z.array(AnnotationSchemeRemovalImpactSchema).default([]),
  confirmation_token: z.string().nullable().optional(),
}).passthrough()

export const AnnotationRecordSchema = z.object({
  category_id: z.string().nullable().optional(),
  note: z.string().nullable().optional(),
  annotator: z.string().nullable().optional(),
  updated_at: z.union([z.number(), z.string()]).nullable().optional(),
}).passthrough()

export const AnnotationsResponseSchema = z.object({
  status: z.string().optional(),
  annotations: z.record(z.string(), AnnotationRecordSchema).default({}),
  scheme: AnnotationSchemeSchema.optional(),
}).passthrough()

// ============================================
// Settings API Schemas
// ============================================

export const UserSettingsSchema = z.object({
  language: z.string(),
  theme: z.enum(['light', 'dark', 'system', 'pink']),
  defaultContext: z.number(),
  defaultCorpus: z.string().optional(),
  fontSize: z.enum(['sm', 'base', 'lg']),
  showLineNumbers: z.boolean(),
  highlightColor: z.string(),
})

export const PrefsStateSchema = z.object({
  prefs: z.record(z.string(), z.string()),
  bookmarks: z.array(z.object({
    left: z.string(),
    kw: z.string(),
    right: z.string(),
  })).optional(),
})

// ============================================
// Analysis Presets Schemas
// ============================================

export const AnalysisPresetSchema = z.object({
  id: z.string(),
  name: z.string(),
  type: z.string(),
  corpus: z.string(),
  docset: z.unknown().nullable().optional(),
  query_term: z.string().optional(),
  params: z.record(z.string(), z.unknown()).optional(),
  result: z.unknown().optional(),
  result_meta: z.record(z.string(), z.unknown()).optional(),
  status: z.string().optional(),
  job_id: z.string().optional(),
  kind: z.string().optional(),
  created_at: z.number().optional(),
  updated_at: z.number().optional(),
  last_accessed_at: z.number().optional(),
})

export const AnalysisPresetsResponseSchema = z.object({
  presets: z.array(AnalysisPresetSchema).default([]),
})

// ============================================
// Embeddings API Schemas
// ============================================

export const EmbeddingModelSchema = z.object({
  id: z.string(),
  name: z.string(),
  installed: z.boolean(),
  dim: z.number().optional(),
  language: z.string().optional(),
  sizeBytes: z.number().optional(),
  url: z.string().optional(),
  sha256: z.string().optional(),
  description: z.string().optional(),
})

export const RawEmbeddingModelSchema = z.object({
  label: z.string().optional(),
  name: z.string().optional(),
  installed: z.boolean().optional(),
  dim: z.number().optional(),
  language: z.string().optional(),
  size_bytes: z.number().optional(),
  url: z.string().optional(),
  sha256: z.string().optional(),
  description: z.string().optional(),
})

export const EmbeddingModelsResponseSchema = z.record(z.string(), RawEmbeddingModelSchema)

const SemanticIndexSizeEstimateSchema = z.object({
  final_bytes: z.number().nonnegative(),
  peak_build_bytes: z.number().nonnegative(),
  warm_search_bytes: z.number().nonnegative(),
})

const SemanticIndexBuildOptionSchema = z.object({
  can_build: z.boolean(),
  required_free_bytes: z.number().nonnegative(),
})

export const LocalSemanticIndexPreflightSchema = z.object({
  schema_version: z.literal('candyconc-semantic-index-preflight-v1'),
  corpus: z.string().min(1),
  corpus_path: z.string().min(1),
  platform: z.object({
    system: z.string(),
    machine: z.string(),
    supported: z.boolean(),
    memory_bytes: z.number().nonnegative(),
  }),
  runtime: z.object({
    installed: z.boolean(),
    python: z.string(),
    model: z.string().min(1),
    model_cached: z.boolean(),
  }),
  counts: z.object({
    documents: z.number().int().nonnegative(),
    sentences: z.number().int().nonnegative(),
    tokens: z.number().int().nonnegative(),
  }),
  disk: z.object({
    free_bytes: z.number().nonnegative(),
    total_bytes: z.number().nonnegative(),
  }),
  estimates: z.object({
    doc: SemanticIndexSizeEstimateSchema,
    sentence: SemanticIndexSizeEstimateSchema,
    both: SemanticIndexSizeEstimateSchema,
    runtime_download_bytes: z.number().nonnegative(),
    model_download_bytes: z.number().nonnegative(),
  }),
  available_levels: z.object({
    doc: z.boolean(),
    sentence: z.boolean(),
  }),
  options: z.object({
    doc: SemanticIndexBuildOptionSchema,
    sentence: SemanticIndexBuildOptionSchema,
    both: SemanticIndexBuildOptionSchema,
  }),
  resumable_run: z.object({
    run_id: z.string().min(1),
    status: z.string(),
    levels: z.array(z.enum(['doc', 'sentence'])),
    progress: z.number().nullable().optional(),
    message: z.string(),
  }).nullable(),
  warnings: z.array(z.string()),
})

export const OperationRunStatusSchema = z.enum([
  'queued',
  'running',
  'succeeded',
  'failed',
  'cancelled',
  'stale',
])

export const OperationRunSnapshotSchema = z.object({
  run_id: z.string().min(1),
  job_id: z.string().min(1),
  operation_id: z.string().min(1),
  source_id: z.string().min(1),
  kind: z.string().min(1),
  label: z.string(),
  status: OperationRunStatusSchema,
  phase: z.string(),
  progress: z.number().min(0).max(100).nullable(),
  message: z.string(),
  error: z.string().nullable(),
  result_ref: z.string().nullable(),
  readiness: z.string(),
  warnings: z.array(z.string()),
  evidence: z.record(z.string(), z.unknown()),
  created_at: z.string().min(1),
  updated_at: z.string().min(1),
  finished_at: z.string().nullable(),
}).passthrough()

export const OperationRunLaunchResponseSchema = z.object({
  status: z.literal('queued'),
  run_id: z.string().min(1),
  job_id: z.string().min(1),
  status_url: z.string().min(1),
  operation_id: z.string().min(1),
}).passthrough()

// ============================================
// System API Schemas
// ============================================

export const DiskUsageSchema = z.object({
  used: z.number(),
  total: z.number(),
})

export const SystemInfoSchema = z.object({
  version: z.string(),
  backendVersion: z.string().optional(),
  uptime: z.string().optional(),
  corpusName: z.string(),
  tokenCount: z.number(),
  documentCount: z.number(),
  indexStatus: z.enum(['ready', 'building', 'error']).optional(),
  lastUpdated: z.string().optional(),
  diskUsage: DiskUsageSchema.optional(),
  faissStatus: z.enum(['ready', 'building', 'error', 'unavailable']).optional(),
  faissDetail: z.string().optional(),
  vectorCount: z.number().optional(),
  cacheSize: z.string().optional(),
  source: z.enum(['backend', 'legacy_health_fallback', 'backend_degraded_fallback']).optional(),
})

export const HealthCheckSchema = z.object({
  status: z.enum(['ok', 'degraded', 'error']),
  services: z.record(z.string(), z.boolean()),
})

export const RebuildIndexResponseSchema = z.object({
  jobId: z.string(),
  wsUrl: z.string().optional(),
})

export const RawRebuildIndexResponseSchema = z.object({
  job_id: z.string(),
  ws_url: z.string().optional(),
})

export type RebuildIndexResponse = z.infer<typeof RebuildIndexResponseSchema>

// ============================================
// Meta Values API Schema
// ============================================

export const MetaValuesResponseSchema = z.object({
  values: z.record(z.string(), z.array(z.string())).optional(),
  truncated_fields: z.array(z.string()).default([]),
  limit: z.number().int().positive().optional(),
})

export const MetaCountsResponseSchema = z.object({
  counts: z.record(z.string(), z.record(z.string(), z.number())).optional(),
})

export const MetaSchemaFieldSchema = z.object({
  name: z.string(),
  kind: z.string().optional(),
  hasString: z.boolean().optional(),
  hasNumber: z.boolean().optional(),
  stringValueCount: z.number().nullable().optional(),
  numericValueCount: z.number().nullable().optional(),
  // True for model/text_type/variant when they hold only the value the
  // builder writes into every document of an unpaired corpus.
  placeholder: z.boolean().optional(),
}).passthrough()

export const MetaSchemaResponseSchema = z.object({
  schemaVersion: z.number(),
  corpus: z.string(),
  documentCount: z.number().optional(),
  indexFingerprint: z.string().optional(),
  metadataSchemaHash: z.string().optional(),
  fingerprint: z.string().optional(),
  fingerprintStrength: z.string().optional(),
  metadataFields: z.array(MetaSchemaFieldSchema).default([]),
  metaIndex: z.record(z.string(), z.unknown()).optional(),
  docMetadataStore: z.record(z.string(), z.unknown()).optional(),
  warnings: z.array(z.string()).default([]),
}).passthrough()

export type MetaSchemaResponse = z.infer<typeof MetaSchemaResponseSchema>

// ============================================
// Product Capability Contract Schemas
// ============================================

export const ProductCapabilityBackendRouteDescriptorSchema = z.object({
  path: z.string(),
  methods: z.array(z.string()).default([]),
  mutates: z.boolean().default(false),
  requires_corpus_features: z.array(z.string()).default([]),
  access: z.enum(['public', 'user', 'manager', 'admin', 'owner_or_admin']).nullable().optional(),
  required_role: z.string().nullable().optional(),
  transport: z.enum(['http', 'websocket']).default('http'),
  route_class: z.enum(['product_surface', 'admin_surface', 'infrastructure', 'deprecated', 'unclassified']).nullable().optional(),
}).passthrough()

export const ProductCapabilityBackendRouteClaimSchema = z.union([
  z.string(),
  ProductCapabilityBackendRouteDescriptorSchema,
])

export const ProductOperationLifecycleSchema = z.object({
  kind: z.enum(['analysis_job', 'corpus_import_job', 'system_status_job', 'websocket_job', 'operation_run']),
  job_id_field: z.string(),
  status_operation_id: z.string().default(''),
  cancel_operation_id: z.string().default(''),
  rows_operation_id: z.string().default(''),
  reports_operation_id: z.string().default(''),
  status_url_field: z.string().default(''),
  rows_url_field: z.string().default(''),
  websocket_url_field: z.string().default(''),
  polling: z.enum(['http_poll', 'websocket', 'none']),
  status_field: z.string().default('status'),
  progress_field: z.string().default('progress'),
  message_field: z.string().default('message'),
  error_field: z.string().default('error'),
  rows_state_field: z.string().default(''),
  readiness_field: z.string().default(''),
  warnings_field: z.string().default(''),
  result_available_field: z.string().default(''),
  result_discarded_field: z.string().default(''),
  result_discard_reason_field: z.string().default(''),
  terminal_statuses: z.array(z.string()).default([]),
}).passthrough()

export const ProductCapabilityOperationSchema = z.object({
  id: z.string(),
  capability_id: z.string(),
  label: z.string(),
  description: z.string().default(''),
  route: ProductCapabilityBackendRouteDescriptorSchema,
  effects: z.array(z.enum(['read', 'write', 'destructive', 'long_running'])).default([]),
  copilot_tools: z.array(z.string()).optional(),
  surface_slot: z.string().default(''),
  priority: z.number().default(100),
  input_schema_ref: z.string(),
  required_context: z.array(z.string()).default([]),
  response_shape: z.enum(['data', 'job', 'stream', 'file', 'image', 'void', 'mixed', 'unknown']),
  run_semantics: z.enum([
    'instant',
    'bounded_sync',
    'job_lifecycle',
    'stream',
    'file_export',
    'fire_and_forget',
  ]),
  ui_execution_policy: z.enum(['contextual_ui', 'confirmed_contextual_ui', 'none']),
  requires_parameters: z.boolean().default(true),
  lifecycle: ProductOperationLifecycleSchema.nullable().default(null),
}).passthrough()

export const ProductCapabilitySchema = z.object({
  id: z.string(),
  title: z.string(),
  area: z.string(),
  maturity: z.enum(['stable', 'guarded', 'experimental', 'planned', 'unsupported']),
  visibility: z.enum(['first_class_ui', 'expert_api', 'hidden_experimental']),
  backend_routes: z.array(ProductCapabilityBackendRouteClaimSchema).default([]),
  backend_route_descriptors: z.array(ProductCapabilityBackendRouteDescriptorSchema).default([]),
  operations: z.array(ProductCapabilityOperationSchema).default([]),
  action_types: z.array(z.string()).default([]),
  copilot_tools: z.array(z.string()).default([]),
  preconditions: z.array(z.string()).default([]),
  requires_corpus_features: z.array(z.string()).default([]),
  limits: z.array(z.string()).default([]),
  notes: z.string().optional(),
}).passthrough()

export const CqlfCapabilitySchema = z.object({
  id: z.string(),
  title: z.string(),
  level: z.number(),
  syntax: z.enum(['supported', 'partial', 'planned', 'unsupported', 'not_applicable']),
  execution: z.enum(['supported', 'partial', 'planned', 'unsupported', 'not_applicable']),
  diagnostics: z.enum(['supported', 'partial', 'planned', 'unsupported', 'not_applicable']),
  explain: z.enum(['supported', 'partial', 'planned', 'unsupported', 'not_applicable']),
  tests: z.enum(['supported', 'partial', 'planned', 'unsupported', 'not_applicable']),
  ast_nodes: z.array(z.string()).default([]),
  token_operators: z.array(z.string()).default([]),
  meta_operators: z.array(z.string()).default([]),
  token_attributes: z.array(z.string()).default([]),
  language_service_attributes: z.array(z.string()).default([]),
  language_service_parameters: z.array(z.string()).default([]),
  snippets: z.array(z.object({
    insert_text: z.string(),
    detail: z.string(),
  }).passthrough()).default([]),
  requires: z.array(z.string()).default([]),
  limits: z.array(z.string()).default([]),
  notes: z.string().default(''),
}).passthrough()

export const ProductCapabilityContractSchema = z.object({
  version: z.string(),
  scope: z.string(),
  fingerprint_sha256: z.string(),
  cqlf_capability_contract: z.object({
    version: z.string(),
    current_level: z.string(),
    fingerprint_sha256: z.string(),
    capabilities: z.array(CqlfCapabilitySchema).optional(),
  }).passthrough(),
  capabilities: z.array(ProductCapabilitySchema).default([]),
  /** Copilot tools that steer the turn (no corpus evidence), from the backend contract. */
  copilot_control_tools: z.array(z.object({
    name: z.string(),
    role: z.string(),
    label: z.string().optional(),
    description: z.string().optional(),
  }).passthrough()).default([]),
}).passthrough()

export type ProductCapabilityBackendRouteDescriptor = z.infer<typeof ProductCapabilityBackendRouteDescriptorSchema>
export type ProductOperationLifecycle = z.infer<typeof ProductOperationLifecycleSchema>
export type ProductCapabilityOperation = z.infer<typeof ProductCapabilityOperationSchema>
export type ProductCapability = z.infer<typeof ProductCapabilitySchema>
export type CqlfCapability = z.infer<typeof CqlfCapabilitySchema>
export type ProductCapabilityContract = z.infer<typeof ProductCapabilityContractSchema>

export const McpToolFunctionSchema = z.object({
  name: z.string(),
  description: z.string().optional(),
  parameters: z.unknown().optional(),
}).passthrough()

export const McpToolRuntimeSchema = z.object({
  type: z.string().optional(),
  function: McpToolFunctionSchema,
  read_only: z.boolean().default(false),
  concurrency_safe: z.boolean().default(false),
  runtime_metadata_status: z.enum(['verified', 'missing']).default('missing'),
  product_operation_ids: z.array(z.string()).default([]),
  product_capability_ids: z.array(z.string()).default([]),
  product_effects: z.array(z.string()).default([]),
  requires_corpus_features: z.array(z.string()).default([]),
}).passthrough()

export const McpToolStatusSchema = z.object({
  name: z.string(),
  status: z.enum([
    'operation_bound',
    'policy_blocked',
    'metadata_missing',
    'capability_only',
    'unclaimed_registered',
    'registry_missing',
  ]),
  dispatchable: z.boolean().default(false),
  reason: z.string().default(''),
  registered: z.boolean().default(false),
  visible_product_claimed: z.boolean().default(false),
  read_only: z.boolean().default(false),
  concurrency_safe: z.boolean().default(false),
  runtime_metadata_status: z.enum(['verified', 'missing']).default('missing'),
  product_operation_ids: z.array(z.string()).default([]),
  product_capability_ids: z.array(z.string()).default([]),
  product_effects: z.array(z.string()).default([]),
  requires_corpus_features: z.array(z.string()).default([]),
}).passthrough()

export const McpToolsResponseSchema = z.object({
  tools: z.array(McpToolRuntimeSchema).default([]),
  tool_statuses: z.array(McpToolStatusSchema).default([]),
}).passthrough()

export type McpToolRuntime = z.infer<typeof McpToolRuntimeSchema>
export type McpToolStatus = z.infer<typeof McpToolStatusSchema>
export type McpToolsResponse = z.infer<typeof McpToolsResponseSchema>

// ============================================
// Auth Session Schemas
// ============================================

export const AuthSessionSchema = z.object({
  schema_version: z.literal('auth-session-v1'),
  authenticated: z.boolean(),
  token_present: z.boolean(),
  username: z.string().nullable().optional(),
  role: z.string().nullable().optional(),
  effective_role: z.string().nullable().optional(),
  rbac_enabled: z.boolean(),
  security_mode: z.string(),
  release_mode: z.boolean(),
  unsafe_token_transport: z.boolean(),
  dev_token_available: z.boolean(),
  can_access_all_roles: z.boolean(),
}).passthrough()

export type AuthSession = z.infer<typeof AuthSessionSchema>

export const AuthLoginResponseSchema = z.object({
  token: z.string().min(1),
}).passthrough()

export const AuthLogoutResponseSchema = z.object({
  status: z.string(),
}).passthrough()

export type AuthLoginResponse = z.infer<typeof AuthLoginResponseSchema>
export type AuthLogoutResponse = z.infer<typeof AuthLogoutResponseSchema>

// ============================================
// Corpus Import API Schemas
// ============================================

export const CorpusImportReportSchema = z.record(z.string(), z.unknown())

export const CorpusImportReportsSchema = z.record(z.string(), z.unknown())

export const CorpusImportOptionChoiceSchema = z.union([
  z.string(),
  z.number(),
  z.boolean(),
  z.object({
    value: z.union([z.string(), z.number(), z.boolean()]),
    label: z.string().optional(),
    description: z.string().optional(),
    /** Language choices of the import form: the pipeline the language suggests. */
    pipeline: z.string().optional(),
  }).passthrough(),
])

export const CorpusImportOptionSpecSchema = z.object({
  key: z.string(),
  label: z.string().optional(),
  type: z.string().default('string'),
  required: z.boolean().default(false),
  description: z.string().optional(),
  default: z.unknown().optional(),
  choices: z.array(CorpusImportOptionChoiceSchema).default([]),
  aliases: z.array(z.string()).default([]),
  placeholder: z.string().optional(),
}).passthrough()

export const CorpusImportInputSpecSchema = z.object({
  kind: z.string().default('server_file'),
  extensions: z.array(z.string()).default([]),
  accepts_directories: z.boolean().default(false),
  path_hint: z.string().optional(),
  description: z.string().optional(),
}).passthrough()

export const CorpusImportColumnSpecSchema = z.object({
  key: z.string(),
  label: z.string().optional(),
  required: z.boolean().default(false),
  description: z.string().optional(),
  configured_by: z.string().optional(),
}).passthrough()

export const CorpusImportOutputSpecSchema = z.object({
  paired: z.boolean().default(false),
  paired_data_dependent: z.boolean().default(false),
  pairing_kind: z.string().optional(),
  emitted_features: z.array(z.string()).default([]),
  guarantees: z.array(z.string()).default([]),
  limitations: z.array(z.string()).default([]),
}).passthrough()

export const CorpusImportReportSpecSchema = z.object({
  key: z.string(),
  label: z.string().optional(),
  description: z.string().optional(),
}).passthrough()

export const CorpusImportMethodAvailabilitySchema = z.object({
  status: z.string().default('unknown'),
  reason: z.string().optional(),
  script: z.string().optional(),
  script_path: z.string().optional(),
  subcommand: z.array(z.string()).default([]),
}).passthrough()

export const CorpusImportMethodUiWorkflowSchema = z.object({
  status: z.string().default('first_class'),
  label: z.string().optional(),
  reason: z.string().optional(),
}).passthrough()

export const CorpusImportMethodSchema = z.object({
  schema_version: z.string(),
  method: z.string(),
  label: z.string().optional(),
  description: z.string().optional(),
  input: CorpusImportInputSpecSchema,
  availability: CorpusImportMethodAvailabilitySchema.optional(),
  ui_workflow: CorpusImportMethodUiWorkflowSchema.optional(),
  option_keys: z.array(z.string()),
  option_specs: z.array(CorpusImportOptionSpecSchema),
  expected_columns: z.array(CorpusImportColumnSpecSchema).default([]),
  output: CorpusImportOutputSpecSchema,
  emitted_features: z.array(z.string()).default([]),
  reports: z.array(CorpusImportReportSpecSchema),
}).passthrough()

export const CorpusImportMethodsResponseSchema = z.object({
  methods: z.array(CorpusImportMethodSchema).default([]),
}).passthrough()

export const CorpusImportPreflightCheckSchema = z.object({
  key: z.string(),
  label: z.string().optional(),
  status: z.enum(['pass', 'warn', 'fail']),
  severity: z.enum(['info', 'warning', 'error']).default('info'),
  blocking: z.boolean().default(false),
  message: z.string(),
  evidence: z.record(z.string(), z.unknown()).default({}),
}).passthrough()

export const CorpusImportPreflightEvidenceSchema = z.object({
  path: z.string().optional(),
  exists: z.boolean().optional(),
  is_file: z.boolean().optional(),
  is_dir: z.boolean().optional(),
  size_bytes: z.number().nullable().optional(),
  suffix: z.string().optional(),
  columns: z.array(z.string()).default([]),
  method_contract: CorpusImportMethodSchema.optional(),
}).passthrough()

export const CorpusImportPreflightResponseSchema = z.object({
  schema_version: z.string(),
  method: z.string(),
  input_path: z.string(),
  status: z.enum(['pass', 'warning', 'error']),
  ok: z.boolean(),
  blocking: z.boolean(),
  max_severity: z.enum(['info', 'warning', 'error']).default('info'),
  summary: z.string().optional(),
  errors: z.array(z.string()).default([]),
  warnings: z.array(z.string()).default([]),
  checks: z.array(CorpusImportPreflightCheckSchema).default([]),
  evidence: CorpusImportPreflightEvidenceSchema,
  normalized_payload: z.record(z.string(), z.unknown()).optional(),
}).passthrough()

export const CorpusImportJobSchema = z.object({
  job_id: z.string(),
  status: z.string(),
  progress: z.number().optional(),
  stage: z.string().nullable().optional(),
  message: z.string().nullable().optional(),
  method: z.string().nullable().optional(),
  input_path: z.string().nullable().optional(),
  target_name: z.string().nullable().optional(),
  target_path: z.string().nullable().optional(),
  staging_path: z.string().nullable().optional(),
  activate_on_success: z.boolean().optional(),
  pid: z.number().nullable().optional(),
  process_pid: z.number().nullable().optional(),
  returncode: z.number().nullable().optional(),
  created_at: z.number().nullable().optional(),
  updated_at: z.number().nullable().optional(),
  started_at: z.number().nullable().optional(),
  finished_at: z.number().nullable().optional(),
  error: z.string().nullable().optional(),
  finalization_started: z.boolean().optional(),
  cancellable: z.boolean().optional(),
  stdout_tail: z.string().nullable().optional(),
  stdout_truncated: z.boolean().optional(),
  stderr_tail: z.string().nullable().optional(),
  stderr_truncated: z.boolean().optional(),
  readiness: z.string().optional(),
  partial_input: z.boolean().optional(),
  rejected_rows: z.number().optional(),
  warning_count: z.number().optional(),
  import_warnings: z.array(z.string()).default([]),
  activation_skipped_reason: z.string().nullable().optional(),
  urls: z.record(z.string(), z.string()).optional(),
  reports: CorpusImportReportsSchema.optional(),
}).passthrough()

export const CorpusImportReportsResponseSchema = z.object({
  schema_version: z.enum(['corpus-import-reports-v1', 'legacy-flattened-import-reports']),
  job_id: z.string(),
  reports: CorpusImportReportsSchema,
}).passthrough()

export const CorpusImportJobsResponseSchema = z.object({
  jobs: z.array(CorpusImportJobSchema).default([]),
  count: z.number().optional(),
}).passthrough()

export const CorpusBuildReportSchema = z.object({
  schema_version: z.enum(['corpus-build-report-v1', 'legacy-flattened-corpus-build-report']),
  corpus: z.string(),
  path: z.string().optional(),
  reports: CorpusImportReportsSchema,
}).passthrough()

export type CorpusImportReport = z.infer<typeof CorpusImportReportSchema>
export type CorpusImportReports = z.infer<typeof CorpusImportReportsSchema>
export type CorpusImportOptionChoice = z.infer<typeof CorpusImportOptionChoiceSchema>
export type CorpusImportOptionSpec = z.infer<typeof CorpusImportOptionSpecSchema>
export type CorpusImportInputSpec = z.infer<typeof CorpusImportInputSpecSchema>
export type CorpusImportColumnSpec = z.infer<typeof CorpusImportColumnSpecSchema>
export type CorpusImportOutputSpec = z.infer<typeof CorpusImportOutputSpecSchema>
export type CorpusImportReportSpec = z.infer<typeof CorpusImportReportSpecSchema>
export type CorpusImportMethodAvailability = z.infer<typeof CorpusImportMethodAvailabilitySchema>
export type CorpusImportMethod = z.infer<typeof CorpusImportMethodSchema>
export type CorpusImportMethodsResponse = z.infer<typeof CorpusImportMethodsResponseSchema>
export type CorpusImportPreflightCheck = z.infer<typeof CorpusImportPreflightCheckSchema>
export type CorpusImportPreflightEvidence = z.infer<typeof CorpusImportPreflightEvidenceSchema>
export type CorpusImportPreflightResponse = z.infer<typeof CorpusImportPreflightResponseSchema>
export type CorpusImportJob = z.infer<typeof CorpusImportJobSchema>
export type CorpusImportJobsResponse = z.infer<typeof CorpusImportJobsResponseSchema>
export type CorpusImportReportsResponse = z.infer<typeof CorpusImportReportsResponseSchema>
export type CorpusBuildReport = z.infer<typeof CorpusBuildReportSchema>

// ============================================
// Analysis Jobs Schemas
// ============================================

export const AnalysisJobSnapshotSchema = z.object({
  job_id: z.string(),
  kind: z.string().optional(),
  corpus: z.string().optional(),
  params: z.record(z.string(), z.any()).optional(),
  status: z.string(),
  progress: z.number().optional(),
  message: z.string().optional(),
  total_rows: z.number().nullable().optional(),
  error: z.string().nullable().optional(),
  result_available: z.boolean().optional(),
  result_discarded: z.boolean().optional(),
  result_discard_reason: z.string().nullable().optional(),
  result_readiness: z.string().optional(),
  rows_state: z.string().optional(),
  result_warnings: z.array(z.string()).optional(),
  result_bytes: z.number().nullable().optional(),
  result_max_bytes: z.number().nullable().optional(),
  created_at: z.number().optional(),
  updated_at: z.number().optional(),
})

export const AnalysisJobStartSchema = z.object({
  job_id: z.string(),
  status_url: z.string().optional(),
  rows_url: z.string().optional(),
  ws_url: z.string().optional(),
})

export const AnalysisJobRowsSchema = z.object({
  job_id: z.string(),
  status: z.string(),
  progress: z.number().optional(),
  message: z.string().optional(),
  total_rows: z.number().nullable().optional(),
  // Some analysis tool responses (e.g. contrast) report the full result count as `total`.
  total: z.number().nullable().optional(),
  row_limit: z.number().nullable().optional(),
  total_candidates: z.number().nullable().optional(),
  truncated: z.boolean().optional(),
  error: z.string().nullable().optional(),
  result_available: z.boolean().optional(),
  result_discarded: z.boolean().optional(),
  result_discard_reason: z.string().nullable().optional(),
  result_readiness: z.string().optional(),
  rows_state: z.string().optional(),
  result_warnings: z.array(z.string()).optional(),
  result_bytes: z.number().nullable().optional(),
  result_max_bytes: z.number().nullable().optional(),
  offset: z.number().optional(),
  limit: z.number().optional(),
  rows: z.array(z.any()).optional(),
  // Statistical provenance (F1); present on keyness/contrast/collocates jobs.
  method: MethodBlockSchema.optional(),
}).passthrough()

// Note: Type exports are provided by client.ts to avoid duplication.
// Use the schemas for runtime validation only.

// ============================================
// Validation Helpers
// ============================================

/**
 * Safely parse data with a Zod schema, returning null on failure
 */
export function safeParse<T>(schema: z.ZodSchema<T>, data: unknown): T | null {
  const result = schema.safeParse(data)
  return result.success ? result.data : null
}

/**
 * Parse data with a Zod schema, throwing on failure with detailed error
 */
export function parse<T>(schema: z.ZodSchema<T>, data: unknown): T {
  return schema.parse(data)
}

/**
 * Thrown when an API response does not match its expected schema. Carries the
 * endpoint and the raw Zod issues so callers can surface a meaningful error
 * instead of receiving malformed data blindly cast to the success type.
 */
export class SchemaValidationError extends Error {
  readonly endpoint: string
  readonly issues: z.ZodIssue[]

  constructor(endpoint: string, issues: z.ZodIssue[]) {
    super(`API response from "${endpoint}" did not match the expected schema`)
    this.name = 'SchemaValidationError'
    this.endpoint = endpoint
    this.issues = issues
  }
}

/**
 * Validate an API response against its schema. On mismatch, throw a typed
 * {@link SchemaValidationError} rather than silently casting malformed data
 * (e.g. an error body or a `{status: "not_applicable"}` envelope) to the
 * success type. Callers already wrap API calls in try/catch and surface the
 * failure to the UI.
 */
/**
 * Modellweg: lokal oder ueber einen Anbieter.
 *
 * Der Schluessel selbst ist NICHT Teil dieser Antwort. Das Backend gibt ihn
 * nie zurueck, nur ob einer gesetzt ist und seine letzten vier Zeichen.
 */
export const ModelRouteProfileSchema = z.object({
  id: z.string(),
  name: z.string(),
  endpoint: z.string(),
  schluessel_noetig: z.boolean(),
  hinweis: z.string(),
})

export const ModelRouteSchema = z.object({
  aktiv: z.string(),
  endpoint: z.string().nullable(),
  modell: z.string().nullable(),
  schluessel_gesetzt: z.boolean(),
  schluessel_endet_auf: z.string().nullable(),
  schluessel_fluechtig: z.boolean(),
  profile: z.array(ModelRouteProfileSchema),
})

export type ModelRoute = z.infer<typeof ModelRouteSchema>
export type ModelRouteProfile = z.infer<typeof ModelRouteProfileSchema>

export function validateResponse<T>(
  schema: z.ZodSchema<T>,
  data: unknown,
  endpoint: string
): T {
  const result = schema.safeParse(data)
  if (!result.success) {
    console.warn(`[API Schema Mismatch] ${endpoint}:`, result.error.issues)
    throw new SchemaValidationError(endpoint, result.error.issues)
  }
  return result.data
}
