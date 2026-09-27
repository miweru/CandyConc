import { computed } from 'vue'
import {
  getDispersion,
  getDispersionOffsets,
  type DispersionOffsetsResult,
  type DispersionParams,
  type DispersionResult,
} from '@/api/client'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { t } from '@/i18n'

export const DISPERSION_CAPABILITY_ID = 'analysis.dispersion'
export const DISPERSION_ROUTES = {
  stats: '/api/v1/analysis/dispersion',
  offsets: '/api/v1/analysis/dispersion_offsets',
} as const
export const DISPERSION_OPERATIONS = {
  stats: 'analysis.dispersion.stats',
  offsets: 'analysis.dispersion.offsets',
} as const

export function useDispersionOperations() {
  const statsGate = useProductRouteOperationGate({
    capabilityId: DISPERSION_CAPABILITY_ID,
    label: t('analysis.operations.dispersion'),
    operationId: DISPERSION_OPERATIONS.stats,
    operation: { path: DISPERSION_ROUTES.stats, method: 'GET' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.dispersion') }),
  })
  const offsetsGate = useProductRouteOperationGate({
    capabilityId: DISPERSION_CAPABILITY_ID,
    label: t('analysis.operations.dispersionOffsets'),
    operationId: DISPERSION_OPERATIONS.offsets,
    operation: { path: DISPERSION_ROUTES.offsets, method: 'GET' },
    fallbackReason: t('analysis.operations.dispersionOffsetsNotEnabled'),
  })

  async function loadDispersion(
    params: DispersionParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<DispersionResult> {
    await statsGate.assertAvailable()
    // A page of offsets cannot reproduce document-based Gries DP: it may be
    // capped and has neither the full document partition nor its denominators.
    // Surface an unavailable stats endpoint instead of manufacturing a metric.
    return getDispersion(params, options)
  }

  async function loadDispersionOffsets(
    params: DispersionParams,
    options: { signal?: AbortSignal } = {},
  ): Promise<DispersionOffsetsResult> {
    await offsetsGate.assertAvailable()
    return getDispersionOffsets(params, options)
  }

  return {
    statsAvailability: statsGate.availability,
    offsetsAvailability: offsetsGate.availability,
    canLoadDispersion: computed(() => statsGate.canUse.value),
    canLoadDispersionOffsets: computed(() => offsetsGate.canUse.value),
    dispersionBlockReason: statsGate.blockReason,
    dispersionOffsetsBlockReason: offsetsGate.blockReason,
    loadDispersion,
    loadDispersionOffsets,
  }
}
