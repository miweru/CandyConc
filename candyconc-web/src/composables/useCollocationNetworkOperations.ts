import { computed } from 'vue'
import {
  getCollocationNetwork,
  type CollocationNetwork,
  type CollocationNetworkParams,
} from '@/api/client'
import { useProductOperation } from '@/composables/useProductOperation'
import { t } from '@/i18n'

export const COLLOCATION_NETWORK_OPERATIONS = {
  graph: 'analysis.collocation_network.graph',
} as const
export const COLLOCATION_NETWORK_ROUTES = {
  graph: '/api/v1/analysis/collocation_network',
} as const

export function useCollocationNetworkOperations() {
  const graphOperation = useProductOperation<
    [CollocationNetworkParams],
    CollocationNetwork
  >(
    COLLOCATION_NETWORK_OPERATIONS.graph,
    getCollocationNetwork,
    {
      fallbackCapabilityId: 'analysis.collocation_network',
      fallbackLabel: t('analysis.operations.collocationNetwork'),
      fallbackOperation: { path: COLLOCATION_NETWORK_ROUTES.graph, method: 'GET' },
      fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.collocationNetwork') }),
    },
  )

  return {
    graphAvailability: graphOperation.availability,
    canLoadCollocationNetwork: computed(() => graphOperation.canUse.value),
    collocationNetworkBlockReason: graphOperation.blockReason,
    assertCanLoadCollocationNetwork: graphOperation.assertAvailable,
    loadCollocationNetwork: graphOperation.run,
  }
}
