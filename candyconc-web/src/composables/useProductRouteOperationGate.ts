import { computed, type ComputedRef } from 'vue'
import {
  corpusFeatureDecisionReason,
  type ProductBackendRouteFeaturePredicate,
} from '@/lib/productCorpusFeatures'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import {
  useProductCapabilitiesStore,
  type ProductOperationAccessOptions,
  type ProductRouteOperationAvailabilityDecision,
  type ProductRouteOperationSpec,
} from '@/stores/productCapabilities'
import { t } from '@/i18n'

export interface ProductRouteOperationGateOptions {
  capabilityId: string
  label: string
  operation?: ProductRouteOperationSpec | readonly ProductRouteOperationSpec[]
  operationId?: string
  allowMissingContractFallback?: boolean
  corpusFeaturePredicate?: ProductBackendRouteFeaturePredicate
  fallbackReason?: string
}

export interface ProductRouteOperationGate {
  availability: ComputedRef<ProductRouteOperationAvailabilityDecision>
  corpusBlockReason: ComputedRef<string | null>
  blockReason: ComputedRef<string | null>
  canUse: ComputedRef<boolean>
  assertAvailable: (options?: ProductOperationAccessOptions) => Promise<void>
}

export function productCapabilityDenied(
  reason: string | null | undefined,
  fallback: string,
): Error {
  const error = new Error(reason ?? fallback)
  error.name = 'ProductCapabilityDeniedError'
  return error
}

export function useProductRouteOperationGate(
  options: ProductRouteOperationGateOptions,
): ProductRouteOperationGate {
  const productCapabilities = useProductCapabilitiesStore()
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const operations = Array.isArray(options.operation)
    ? options.operation
    : options.operation
      ? [options.operation]
      : []

  const label = computed(() =>
    (options.operationId && productCapabilities.operationFor(options.operationId)?.label) || options.label,
  )

  const availability = computed(() => {
    if (options.operationId) {
      if (!productCapabilities.hasContract) {
        const enabled =
          options.allowMissingContractFallback === true &&
          productCapabilities.allowsMissingContractFallback
        return {
          visible: enabled,
          enabled,
          disabledReason: enabled
            ? null
            : t('capabilities.store.waitingForCatalogue', { label: label.value, suffix: '' }),
          operations,
        }
      }
      return productCapabilities.productOperationAvailability(options.operationId)
    }
    return {
      visible: false,
      enabled: false,
      disabledReason:
        t('capabilities.store.notRunnableServerFunction', { label: label.value }),
      operations,
    }
  })

  const corpusDecision = computed(() =>
    productCapabilities.corpusFeatureDecision(
      options.capabilityId,
      corpusCapabilities.activeSummary,
      options.corpusFeaturePredicate,
    ),
  )

  const corpusBlockReason = computed(() =>
    corpusFeatureDecisionReason(label.value, corpusDecision.value),
  )

  const blockReason = computed(() =>
    availability.value.disabledReason ?? corpusBlockReason.value,
  )

  const canUse = computed(() =>
    availability.value.enabled && !corpusBlockReason.value,
  )

  async function assertAvailable(assertOptions: ProductOperationAccessOptions = {}): Promise<void> {
    await productCapabilities.ensureAccessContext()
    if (!canUse.value) {
      throw productCapabilityDenied(
        blockReason.value,
        options.fallbackReason
          ?? t('capabilities.store.notEnabledContext', { label: label.value }),
      )
    }
    if (options.operationId && productCapabilities.hasContract) {
      await productCapabilities.assertProductOperationAccess(
        options.operationId,
        label.value,
        assertOptions,
      )
    }
  }

  return {
    availability,
    corpusBlockReason,
    blockReason,
    canUse,
    assertAvailable,
  }
}
