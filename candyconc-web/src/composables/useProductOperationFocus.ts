import { computed, ref, watch, type WatchStopHandle } from 'vue'
import { operationSlotMatches } from '@/lib/productOperationPlacement'
import { useUiStore, type ProductOperationFocus } from '@/stores/ui'

export function productOperationFocusMatches(
  focus: ProductOperationFocus | null | undefined,
  ...surfaceSlotPrefixes: string[]
): boolean {
  const slot = focus?.surfaceSlot ?? ''
  return Boolean(slot) && surfaceSlotPrefixes.some((prefix) => operationSlotMatches(slot, prefix))
}

export function productOperationFocusIs(
  focus: ProductOperationFocus | null | undefined,
  ...operationIds: string[]
): boolean {
  const operationId = focus?.operationId
  return Boolean(operationId) && operationIds.includes(operationId!)
}

export function useProductOperationFocus() {
  const uiStore = useUiStore()
  const focusedProductOperation = computed(() => uiStore.focusedProductOperation)
  const consumedProductOperation = ref<ProductOperationFocus | null>(null)
  const effectiveProductOperation = computed(
    () => focusedProductOperation.value ?? consumedProductOperation.value,
  )
  const focusedSurfaceSlot = computed(() => effectiveProductOperation.value?.surfaceSlot ?? '')
  const preferredMode = computed(() => effectiveProductOperation.value?.preferredMode ?? null)

  function focusMatches(...surfaceSlotPrefixes: string[]): boolean {
    return productOperationFocusMatches(effectiveProductOperation.value, ...surfaceSlotPrefixes)
  }

  function focusIs(...operationIds: string[]): boolean {
    return productOperationFocusIs(effectiveProductOperation.value, ...operationIds)
  }

  function modeIs(...modes: string[]): boolean {
    const mode = preferredMode.value
    return Boolean(mode) && modes.includes(mode!)
  }

  function clearConsumedFocus(): void {
    consumedProductOperation.value = null
  }

  function consumeFocusFor(
    surfaceSlotPrefixes: string[],
    handler: (focus: ProductOperationFocus) => void,
    options: { immediate?: boolean; clearGlobal?: boolean } = {},
  ): WatchStopHandle {
    const clearGlobal = options.clearGlobal ?? true
    return watch(
      focusedProductOperation,
      (focus) => {
        if (!productOperationFocusMatches(focus, ...surfaceSlotPrefixes)) return
        consumedProductOperation.value = focus!
        handler(focus!)
        if (clearGlobal) {
          uiStore.clearProductOperationFocus()
        }
      },
      { immediate: options.immediate ?? true },
    )
  }

  return {
    focusedProductOperation,
    consumedProductOperation,
    effectiveProductOperation,
    focusedSurfaceSlot,
    preferredMode,
    focusMatches,
    focusIs,
    modeIs,
    clearConsumedFocus,
    consumeFocusFor,
  }
}
