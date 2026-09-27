import { computed } from 'vue'
import {
  createFrequencyDiffJob as requestFrequencyDiffJob,
  canCreateFrequencyListJob,
  createFrequencyListJob,
  frequencyJobRowsToResult,
  getFrequencyResult,
  type AnalysisJobRows,
  type AnalysisJobStart,
  type FrequencyDiffJobParams,
  type FrequencyParams,
  type FrequencyResult,
} from '@/api/client'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { t } from '@/i18n'
import type { ProductOperationAccessOptions } from '@/stores/productCapabilities'

export const FREQUENCY_CAPABILITY_ID = 'analysis.frequency'
export const FREQUENCY_ROUTES = {
  list: '/api/v1/analysis/frequency_list',
  job: '/api/v1/analysis/frequency_list/job',
  diffJob: '/api/v1/analysis/frequency_diff/job',
} as const
export const FREQUENCY_OPERATIONS = {
  list: 'analysis.frequency.list',
  job: 'analysis.frequency.job',
  diffJob: 'analysis.frequency.diff_job',
} as const

export function useFrequencyOperations() {
  const listGate = useProductRouteOperationGate({
    capabilityId: FREQUENCY_CAPABILITY_ID,
    label: t('analysis.operations.frequencyList'),
    operationId: FREQUENCY_OPERATIONS.list,
    operation: { path: FREQUENCY_ROUTES.list, method: 'GET' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.frequencyList') }),
  })
  const jobGate = useProductRouteOperationGate({
    capabilityId: FREQUENCY_CAPABILITY_ID,
    label: t('analysis.operations.frequencyJob'),
    operationId: FREQUENCY_OPERATIONS.job,
    operation: { path: FREQUENCY_ROUTES.job, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.frequencyJob') }),
  })
  const diffJobGate = useProductRouteOperationGate({
    capabilityId: FREQUENCY_CAPABILITY_ID,
    label: t('analysis.operations.frequencyContrastJob'),
    operationId: FREQUENCY_OPERATIONS.diffJob,
    operation: { path: FREQUENCY_ROUTES.diffJob, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.frequencyContrastJob') }),
  })

  function canCreateFrequencyJob(params: FrequencyParams): boolean {
    return canCreateFrequencyListJob(params)
  }

  async function loadFrequencyResult(
    params: FrequencyParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<FrequencyResult> {
    await listGate.assertAvailable()
    return getFrequencyResult(params, options)
  }

  async function createFrequencyJob(
    params: FrequencyParams,
    options: ProductOperationAccessOptions = {},
  ): Promise<AnalysisJobStart> {
    await jobGate.assertAvailable(options)
    return createFrequencyListJob(params)
  }

  async function createFrequencyDiffJob(
    params: FrequencyDiffJobParams,
    options: ProductOperationAccessOptions = {},
  ): Promise<AnalysisJobStart> {
    await diffJobGate.assertAvailable(options)
    return requestFrequencyDiffJob(params)
  }

  function rowsToFrequencyResult(
    response: AnalysisJobRows<{ word: string; f: number }>,
    params: FrequencyParams,
  ): FrequencyResult {
    return frequencyJobRowsToResult(response, params)
  }

  return {
    listAvailability: listGate.availability,
    jobAvailability: jobGate.availability,
    diffJobAvailability: diffJobGate.availability,
    canLoadFrequencyList: computed(() => listGate.canUse.value),
    canStartFrequencyJob: computed(() => jobGate.canUse.value),
    canStartFrequencyDiffJob: computed(() => diffJobGate.canUse.value),
    frequencyListBlockReason: listGate.blockReason,
    frequencyJobBlockReason: jobGate.blockReason,
    frequencyDiffJobBlockReason: diffJobGate.blockReason,
    canCreateFrequencyJob,
    loadFrequencyResult,
    createFrequencyJob,
    createFrequencyDiffJob,
    rowsToFrequencyResult,
  }
}
