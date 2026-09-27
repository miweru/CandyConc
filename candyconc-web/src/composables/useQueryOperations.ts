import { computed } from 'vue'
import {
  executeQuery,
  executeQueryStreaming,
  getQueryCount,
  type QueryCountParams,
  type QueryCountResult,
  type QueryParams,
  type QueryResult,
  type QueryStreamEvent,
  type StreamingQueryParams,
} from '@/api/client'
import { useProductOperation } from '@/composables/useProductOperation'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import type { ProductOperationAccessOptions } from '@/stores/productCapabilities'
import { t } from '@/i18n'

export const QUERY_CAPABILITY_ID = 'query.kwic'
export const QUERY_ROUTES = {
  page: '/api/v1/query',
  stream: '/api/v1/query/stream',
  count: '/api/v1/query/count',
} as const
export const QUERY_OPERATIONS = {
  page: 'query.kwic.page',
  stream: 'query.kwic.stream',
  count: 'query.kwic.count',
} as const

export interface QueryStreamOptions {
  signal?: AbortSignal
  access?: ProductOperationAccessOptions
}

function isAbortSignal(value: AbortSignal | QueryStreamOptions | undefined): value is AbortSignal {
  return Boolean(
    value &&
    typeof value === 'object' &&
    'aborted' in value &&
    typeof value.aborted === 'boolean' &&
    'addEventListener' in value,
  )
}

function normalizeQueryStreamOptions(
  options?: AbortSignal | QueryStreamOptions,
): QueryStreamOptions {
  if (!options) return {}
  if (isAbortSignal(options)) return { signal: options }
  return options
}

export function useQueryOperations() {
  const pageOperation = useProductOperation<
    [QueryParams],
    QueryResult
  >(
    QUERY_OPERATIONS.page,
    executeQuery,
    {
      fallbackCapabilityId: QUERY_CAPABILITY_ID,
      fallbackLabel: t('search.queryOps.page'),
      fallbackOperation: { path: QUERY_ROUTES.page, method: 'GET' },
      fallbackReason: t('search.queryOps.pageNotEnabled'),
    },
  )

  const streamGate = useProductRouteOperationGate({
    capabilityId: QUERY_CAPABILITY_ID,
    label: t('search.queryOps.stream'),
    operationId: QUERY_OPERATIONS.stream,
    operation: { path: QUERY_ROUTES.stream, method: 'GET' },
    fallbackReason: t('search.queryOps.streamNotEnabled'),
  })

  const countOperation = useProductOperation<
    [QueryCountParams],
    QueryCountResult
  >(
    QUERY_OPERATIONS.count,
    getQueryCount,
    {
      fallbackCapabilityId: QUERY_CAPABILITY_ID,
      fallbackLabel: t('search.queryOps.count'),
      fallbackOperation: { path: QUERY_ROUTES.count, method: 'GET' },
      fallbackReason: t('search.queryOps.countNotEnabled'),
    },
  )

  async function* streamKwic(
    params: StreamingQueryParams,
    options?: AbortSignal | QueryStreamOptions,
  ): AsyncGenerator<QueryStreamEvent, void, unknown> {
    const streamOptions = normalizeQueryStreamOptions(options)
    await streamGate.assertAvailable({
      ...streamOptions.access,
      target: streamOptions.access?.target ?? (params.corpus ? t('search.queryOps.targetCorpus', { name: params.corpus }) : t('search.queryOps.targetActive')),
      impact: streamOptions.access?.impact ?? t('search.queryOps.streamImpact'),
    })
    yield* executeQueryStreaming(params, streamOptions.signal)
  }

  return {
    pageAvailability: pageOperation.availability,
    streamAvailability: streamGate.availability,
    countAvailability: countOperation.availability,
    canExecuteKwicPage: computed(() => pageOperation.canUse.value),
    canStreamKwic: computed(() => streamGate.canUse.value),
    canLoadQueryCount: computed(() => countOperation.canUse.value),
    kwicPageBlockReason: pageOperation.blockReason,
    kwicStreamBlockReason: streamGate.blockReason,
    queryCountBlockReason: countOperation.blockReason,
    executeKwicPage: pageOperation.run,
    streamKwic,
    loadQueryCount: countOperation.run,
  }
}
