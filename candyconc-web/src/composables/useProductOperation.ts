import { computed, type ComputedRef } from 'vue'
import type { ProductBackendRouteFeaturePredicate } from '@/lib/productCorpusFeatures'
import {
  useProductCapabilitiesStore,
  type ProductRouteOperationAvailabilityDecision,
  type ProductRouteOperationSpec,
} from '@/stores/productCapabilities'
import type { ProductCapabilityOperation } from '@/api/client'
import {
  productCapabilityDenied,
  useProductRouteOperationGate,
} from '@/composables/useProductRouteOperationGate'
import { t } from '@/i18n'

export interface ProductOperationOptions {
  fallbackCapabilityId?: string
  fallbackLabel?: string
  fallbackOperation?: ProductRouteOperationSpec | readonly ProductRouteOperationSpec[]
  fallbackReason?: string
  corpusFeaturePredicate?: ProductBackendRouteFeaturePredicate
}

export interface ProductOperationFacade<Args extends unknown[], Result> {
  operation: ComputedRef<ProductCapabilityOperation | undefined>
  availability: ComputedRef<ProductRouteOperationAvailabilityDecision>
  corpusBlockReason: ComputedRef<string | null>
  blockReason: ComputedRef<string | null>
  canUse: ComputedRef<boolean>
  assertAvailable: () => Promise<void>
  run: (...args: Args) => Promise<Result>
}

export function useProductOperation<Args extends unknown[], Result>(
  operationId: string,
  executor: (...args: Args) => Promise<Result>,
  options: ProductOperationOptions = {},
): ProductOperationFacade<Args, Result> {
  const productCapabilities = useProductCapabilitiesStore()
  const operation = computed(() => productCapabilities.operationFor(operationId))
  const hasFallbackOperation = Boolean(options.fallbackOperation)
  const missingFallbackReason = computed(() =>
    !productCapabilities.hasContract && !operation.value && !hasFallbackOperation
      ? t('capabilities.store.noCatalogueForOperation')
      : null,
  )

  const gate = useProductRouteOperationGate({
    capabilityId: options.fallbackCapabilityId ?? operationId,
    label: options.fallbackLabel ?? operationId,
    operationId,
    operation: options.fallbackOperation,
    allowMissingContractFallback: hasFallbackOperation,
    corpusFeaturePredicate: options.corpusFeaturePredicate,
    fallbackReason: options.fallbackReason,
  })

  async function assertAvailable(): Promise<void> {
    if (missingFallbackReason.value) {
      throw productCapabilityDenied(
        missingFallbackReason.value,
        options.fallbackReason
          ?? t('capabilities.store.notEnabledContext', { label: operationId }),
      )
    }
    await gate.assertAvailable()
  }

  async function run(...args: Args): Promise<Result> {
    await assertAvailable()
    return executor(...args)
  }

  return {
    operation,
    availability: gate.availability,
    corpusBlockReason: gate.corpusBlockReason,
    blockReason: computed(() => gate.blockReason.value ?? missingFallbackReason.value),
    canUse: computed(() => gate.canUse.value && !missingFallbackReason.value),
    assertAvailable,
    run,
  }
}
