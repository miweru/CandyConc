import { computed } from 'vue'
import {
  createKeynessJob,
  getKeyness,
  type AnalysisJobStart,
  type KeynessItem,
  type KeynessJobParams,
  type KeynessParams,
} from '@/api/client'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { t } from '@/i18n'
import type { ProductOperationAccessOptions } from '@/stores/productCapabilities'

export const KEYNESS_CAPABILITY_ID = 'analysis.keyness'
export const KEYNESS_SYNC_API_CAPABILITY_ID = 'analysis.sync_keyness_api'
export const KEYNESS_ROUTES = {
  stats: '/api/v1/analysis/keyness',
  job: '/api/v1/analysis/keyness/job',
} as const
export const KEYNESS_OPERATIONS = {
  stats: 'analysis.sync_keyness_api.stats',
  job: 'analysis.keyness.job',
} as const

export function useKeynessOperations() {
  const statsGate = useProductRouteOperationGate({
    capabilityId: KEYNESS_SYNC_API_CAPABILITY_ID,
    label: t('analysis.operations.keynessStats'),
    operationId: KEYNESS_OPERATIONS.stats,
    operation: { path: KEYNESS_ROUTES.stats, method: 'POST' },
    fallbackReason: t('analysis.operations.expertOnlyReason', { label: t('analysis.operations.keynessStats') }),
  })
  const jobGate = useProductRouteOperationGate({
    capabilityId: KEYNESS_CAPABILITY_ID,
    label: t('analysis.operations.keynessJob'),
    operationId: KEYNESS_OPERATIONS.job,
    operation: { path: KEYNESS_ROUTES.job, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.keynessJob') }),
  })

  async function loadKeynessStats(params: KeynessParams): Promise<KeynessItem[]> {
    await statsGate.assertAvailable()
    return getKeyness(params)
  }

  async function createKeynessAnalysisJob(
    params: KeynessJobParams,
    options: ProductOperationAccessOptions = {},
  ): Promise<AnalysisJobStart> {
    await jobGate.assertAvailable(options)
    return createKeynessJob(params)
  }

  return {
    statsAvailability: statsGate.availability,
    jobAvailability: jobGate.availability,
    canLoadKeynessStats: computed(() => statsGate.canUse.value),
    canStartKeynessJob: computed(() => jobGate.canUse.value),
    keynessStatsBlockReason: statsGate.blockReason,
    keynessJobBlockReason: jobGate.blockReason,
    loadKeynessStats,
    createKeynessAnalysisJob,
  }
}
