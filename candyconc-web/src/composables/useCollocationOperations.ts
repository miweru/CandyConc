import { computed } from 'vue'
import {
  createCollocatesJob,
  getCollocateKwic,
  getCollocations,
  type AnalysisJobStart,
  type CollocateKwicParams,
  type CollocatesJobParams,
  type Collocation,
  type CollocationsParams,
  type QueryResult,
} from '@/api/client'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { t } from '@/i18n'
import type { ProductOperationAccessOptions } from '@/stores/productCapabilities'

export const COLLOCATION_CAPABILITY_ID = 'analysis.collocations'
export const COLLOCATION_SYNC_API_CAPABILITY_ID = 'analysis.sync_collocations_api'
export const COLLOCATION_ROUTES = {
  stats: '/api/v1/analysis/collocates',
  job: '/api/v1/analysis/collocates/job',
  kwic: '/api/v1/analysis/collocates/kwic',
} as const
export const COLLOCATION_OPERATIONS = {
  stats: 'analysis.sync_collocations_api.stats',
  job: 'analysis.collocations.job',
  kwic: 'analysis.collocations.kwic',
} as const

export function useCollocationOperations() {
  const statsGate = useProductRouteOperationGate({
    capabilityId: COLLOCATION_SYNC_API_CAPABILITY_ID,
    label: t('analysis.operations.collocationStats'),
    operationId: COLLOCATION_OPERATIONS.stats,
    operation: { path: COLLOCATION_ROUTES.stats, method: 'GET' },
    fallbackReason: t('analysis.operations.expertOnlyReason', { label: t('analysis.operations.collocationStats') }),
  })
  const jobGate = useProductRouteOperationGate({
    capabilityId: COLLOCATION_CAPABILITY_ID,
    label: t('analysis.operations.collocationJob'),
    operationId: COLLOCATION_OPERATIONS.job,
    operation: { path: COLLOCATION_ROUTES.job, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.collocationJob') }),
  })
  const kwicGate = useProductRouteOperationGate({
    capabilityId: COLLOCATION_CAPABILITY_ID,
    label: t('analysis.operations.coKwic'),
    operationId: COLLOCATION_OPERATIONS.kwic,
    operation: { path: COLLOCATION_ROUTES.kwic, method: 'GET' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.coKwic') }),
  })

  async function loadCollocations(params: CollocationsParams): Promise<Collocation[]> {
    await statsGate.assertAvailable()
    return getCollocations(params)
  }

  async function createCollocationJob(
    params: CollocatesJobParams,
    options: ProductOperationAccessOptions = {},
  ): Promise<AnalysisJobStart> {
    await jobGate.assertAvailable(options)
    return createCollocatesJob(params)
  }

  async function loadCollocateKwic(params: CollocateKwicParams): Promise<QueryResult> {
    await kwicGate.assertAvailable()
    return getCollocateKwic(params)
  }

  return {
    statsAvailability: statsGate.availability,
    jobAvailability: jobGate.availability,
    kwicAvailability: kwicGate.availability,
    canLoadCollocations: computed(() => statsGate.canUse.value),
    canStartCollocationJob: computed(() => jobGate.canUse.value),
    canLoadCollocateKwic: computed(() => kwicGate.canUse.value),
    collocationStatsBlockReason: statsGate.blockReason,
    collocationJobBlockReason: jobGate.blockReason,
    collocationKwicBlockReason: kwicGate.blockReason,
    loadCollocations,
    createCollocationJob,
    loadCollocateKwic,
  }
}
