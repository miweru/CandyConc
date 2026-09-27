import { computed } from 'vue'
import {
  getSimilarWords,
  semanticSearchWithMeta,
  type SemanticSearchParams,
  type SemanticSearchResultSet,
  type SimilarWordsParams,
  type SimilarWordsResult,
} from '@/api/client'
import { useProductOperation } from '@/composables/useProductOperation'
import { t } from '@/i18n'

export const SEMANTIC_OPERATIONS = {
  similarWords: 'analysis.semantic_similarity.similar_words',
  passageSearch: 'analysis.semantic_similarity.passage_search',
} as const

export const SEMANTIC_ROUTES = {
  similarWords: '/api/v1/semantic/similar_words',
  passageSearch: '/api/v1/analysis/embedding_search',
} as const

export function useSemanticOperations() {
  const similarWordsOperation = useProductOperation<
    [SimilarWordsParams, { signal?: AbortSignal }?],
    SimilarWordsResult
  >(
    SEMANTIC_OPERATIONS.similarWords,
    getSimilarWords,
    {
      fallbackCapabilityId: 'analysis.semantic_similarity',
      fallbackLabel: t('analysis.operations.similarWords'),
      fallbackOperation: { path: SEMANTIC_ROUTES.similarWords, method: 'GET' },
      fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.similarWords') }),
      corpusFeaturePredicate: (route) => route.path === SEMANTIC_ROUTES.similarWords,
    },
  )

  const passageSearchOperation = useProductOperation<
    [SemanticSearchParams, { signal?: AbortSignal }?],
    SemanticSearchResultSet
  >(
    SEMANTIC_OPERATIONS.passageSearch,
    semanticSearchWithMeta,
    {
      fallbackCapabilityId: 'analysis.semantic_similarity',
      fallbackLabel: t('analysis.operations.semanticSearch'),
      fallbackOperation: { path: SEMANTIC_ROUTES.passageSearch, method: 'POST' },
      fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.semanticSearch') }),
      corpusFeaturePredicate: (route) => route.path === SEMANTIC_ROUTES.passageSearch,
    },
  )

  return {
    similarWordsAvailability: similarWordsOperation.availability,
    passageSearchAvailability: passageSearchOperation.availability,
    canLoadSimilarWords: computed(() => similarWordsOperation.canUse.value),
    canSearchPassages: computed(() => passageSearchOperation.canUse.value),
    similarWordsBlockReason: similarWordsOperation.blockReason,
    semanticPassageBlockReason: passageSearchOperation.blockReason,
    loadSimilarWords: similarWordsOperation.run,
    searchPassages: passageSearchOperation.run,
  }
}
