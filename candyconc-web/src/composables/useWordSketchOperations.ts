import { computed } from 'vue'
import {
  getWordSketch,
  getWordSketchDiff,
  type WordSketchDiffParams,
  type WordSketchDiffResult,
  type WordSketchParams,
  type WordSketchResult,
} from '@/api/client'
import { useProductOperation } from '@/composables/useProductOperation'
import { t } from '@/i18n'

export const WORD_SKETCH_OPERATIONS = {
  profile: 'analysis.wordsketch.profile',
  diff: 'analysis.wordsketch.diff',
} as const

export const WORD_SKETCH_ROUTES = {
  profile: '/api/v1/analysis/wordsketch',
  diff: '/api/v1/analysis/wordsketch_diff',
} as const

export function useWordSketchOperations() {
  const profileOperation = useProductOperation<
    [WordSketchParams, { signal?: AbortSignal }?],
    WordSketchResult
  >(
    WORD_SKETCH_OPERATIONS.profile,
    getWordSketch,
    {
      fallbackCapabilityId: 'analysis.wordsketch',
      fallbackLabel: t('analysis.operations.wordSketch'),
      fallbackOperation: { path: WORD_SKETCH_ROUTES.profile, method: 'POST' },
      fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.wordSketch') }),
      corpusFeaturePredicate: (route) => route.path === WORD_SKETCH_ROUTES.profile,
    },
  )

  const diffOperation = useProductOperation<
    [WordSketchDiffParams, { signal?: AbortSignal }?],
    WordSketchDiffResult
  >(
    WORD_SKETCH_OPERATIONS.diff,
    getWordSketchDiff,
    {
      fallbackCapabilityId: 'analysis.wordsketch',
      fallbackLabel: t('analysis.operations.wordSketchDiff'),
      fallbackOperation: { path: WORD_SKETCH_ROUTES.diff, method: 'POST' },
      fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.wordSketchDiff') }),
      corpusFeaturePredicate: (route) => route.path === WORD_SKETCH_ROUTES.diff,
    },
  )

  return {
    profileAvailability: profileOperation.availability,
    diffAvailability: diffOperation.availability,
    canLoadWordSketch: computed(() => profileOperation.canUse.value),
    canLoadWordSketchDiff: computed(() => diffOperation.canUse.value),
    wordSketchBlockReason: profileOperation.blockReason,
    wordSketchDiffBlockReason: diffOperation.blockReason,
    loadWordSketch: profileOperation.run,
    loadWordSketchDiff: diffOperation.run,
  }
}
