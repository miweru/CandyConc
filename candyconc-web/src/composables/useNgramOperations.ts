import { computed } from 'vue'
import {
  createNgramsDiffJob,
  createNgramsJob,
  getNgrams,
  type AnalysisJobStart,
  type Ngram,
  type NgramsParams,
  type NgramsDiffJobParams,
  type NgramsJobParams,
} from '@/api/client'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { t } from '@/i18n'
import type { ProductOperationAccessOptions } from '@/stores/productCapabilities'

export const NGRAM_CAPABILITY_ID = 'analysis.ngrams'
export const NGRAM_SYNC_API_CAPABILITY_ID = 'analysis.sync_ngrams_api'
export const NGRAM_ROUTES = {
  frequency: '/api/v1/analysis/ngrams',
  frequencyJob: '/api/v1/analysis/ngrams/job',
  diffJob: '/api/v1/analysis/ngrams_diff/job',
} as const
export const NGRAM_OPERATIONS = {
  frequency: 'analysis.sync_ngrams_api.frequency',
  frequencyJob: 'analysis.ngrams.frequency_job',
  diffJob: 'analysis.ngrams.diff_job',
} as const

export function useNgramOperations() {
  const frequencyGate = useProductRouteOperationGate({
    capabilityId: NGRAM_SYNC_API_CAPABILITY_ID,
    label: t('analysis.operations.ngramFrequency'),
    operationId: NGRAM_OPERATIONS.frequency,
    operation: { path: NGRAM_ROUTES.frequency, method: 'POST' },
    fallbackReason: t('analysis.operations.expertOnlyReason', { label: t('analysis.operations.ngramFrequency') }),
  })
  const frequencyJobGate = useProductRouteOperationGate({
    capabilityId: NGRAM_CAPABILITY_ID,
    label: t('analysis.operations.ngramFrequencyJob'),
    operationId: NGRAM_OPERATIONS.frequencyJob,
    operation: { path: NGRAM_ROUTES.frequencyJob, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.ngramFrequencyJob') }),
  })
  const diffJobGate = useProductRouteOperationGate({
    capabilityId: NGRAM_CAPABILITY_ID,
    label: t('analysis.operations.ngramContrastJob'),
    operationId: NGRAM_OPERATIONS.diffJob,
    operation: { path: NGRAM_ROUTES.diffJob, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.ngramContrastJob') }),
  })

  async function createNgramFrequencyJob(
    params: NgramsJobParams,
    options: ProductOperationAccessOptions = {},
  ): Promise<AnalysisJobStart> {
    await frequencyJobGate.assertAvailable(options)
    return createNgramsJob(params)
  }

  async function loadNgramFrequency(params: NgramsParams): Promise<Ngram[]> {
    await frequencyGate.assertAvailable()
    return getNgrams(params)
  }

  async function createNgramDiffJob(
    params: NgramsDiffJobParams,
    options: ProductOperationAccessOptions = {},
  ): Promise<AnalysisJobStart> {
    await diffJobGate.assertAvailable(options)
    return createNgramsDiffJob(params)
  }

  return {
    frequencyAvailability: frequencyGate.availability,
    frequencyJobAvailability: frequencyJobGate.availability,
    diffJobAvailability: diffJobGate.availability,
    canLoadNgramFrequency: computed(() => frequencyGate.canUse.value),
    canStartNgramFrequencyJob: computed(() => frequencyJobGate.canUse.value),
    canStartNgramDiffJob: computed(() => diffJobGate.canUse.value),
    ngramFrequencyBlockReason: frequencyGate.blockReason,
    ngramFrequencyJobBlockReason: frequencyJobGate.blockReason,
    ngramDiffJobBlockReason: diffJobGate.blockReason,
    loadNgramFrequency,
    createNgramFrequencyJob,
    createNgramDiffJob,
  }
}
