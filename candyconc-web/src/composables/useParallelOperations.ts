import { computed } from 'vue'
import {
  getAlignmentRefDoc,
  getParallelGroups,
  getParallelKwic,
  type AlignmentRefDocParams,
  type AlignmentRefDocResult,
  type ParallelGroupsParams,
  type ParallelGroupsResult,
  type ParallelKwicParams,
  type ParallelKwicResult,
  type ProductCapabilityBackendRouteDescriptor,
} from '@/api/client'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { useProductOperationRunsStore, type ProductOperationRunRecord } from '@/stores/productOperationRuns'
import { t } from '@/i18n'

export const PARALLEL_CAPABILITY_ID = 'corpus.alignment_parallel'
export const PARALLEL_ROUTES = {
  groups: '/api/v1/analysis/parallel_groups',
  alignmentRefDoc: '/api/v1/analysis/alignment/ref_doc',
  kwicParallel: '/api/v1/analysis/kwic_parallel',
} as const
export const PARALLEL_OPERATIONS = {
  groups: 'corpus.alignment_parallel.parallel_groups',
  alignmentRefDoc: 'corpus.alignment_parallel.alignment_ref_doc',
  kwicParallel: 'corpus.alignment_parallel.parallel_kwic',
} as const

function routeOperationPredicate(path: string, method: string) {
  return (route: ProductCapabilityBackendRouteDescriptor): boolean => {
    if (route.path !== path) return false
    const methods = route.methods ?? []
    if (methods.length === 0) return true
    return methods.map((candidate) => candidate.toUpperCase()).includes(method)
  }
}

export function useParallelOperations() {
  const operationRuns = useProductOperationRunsStore()
  const groupsGate = useProductRouteOperationGate({
    capabilityId: PARALLEL_CAPABILITY_ID,
    label: t('kwic.operations.parallelGroups'),
    operationId: PARALLEL_OPERATIONS.groups,
    operation: { path: PARALLEL_ROUTES.groups, method: 'POST' },
    corpusFeaturePredicate: routeOperationPredicate(PARALLEL_ROUTES.groups, 'POST'),
    fallbackReason: t('kwic.operations.parallelGroupsNotEnabled'),
  })

  function startParallelRun(
    operationId: string,
    sourceId: string,
    label: string,
    detail: string | null,
  ): ProductOperationRunRecord {
    return operationRuns.startRun({
      operationId,
      sourceId,
      kind: 'operation',
      surfaceId: 'corpus.alignment_parallel',
      label,
      detail,
      status: 'running',
      progress: 5,
      message: t('kwic.operations.running', { label }),
    })
  }

  function failParallelRun(run: ProductOperationRunRecord, err: unknown, fallback: string): void {
    operationRuns.failRun(run.id, err instanceof Error ? err.message : fallback)
  }
  const alignmentGate = useProductRouteOperationGate({
    capabilityId: PARALLEL_CAPABILITY_ID,
    label: t('kwic.operations.alignmentRefDoc'),
    operationId: PARALLEL_OPERATIONS.alignmentRefDoc,
    operation: { path: PARALLEL_ROUTES.alignmentRefDoc, method: 'POST' },
    corpusFeaturePredicate: routeOperationPredicate(PARALLEL_ROUTES.alignmentRefDoc, 'POST'),
    fallbackReason: t('kwic.operations.alignmentNotEnabled'),
  })
  const parallelKwicGate = useProductRouteOperationGate({
    capabilityId: PARALLEL_CAPABILITY_ID,
    label: t('kwic.operations.parallelKwic'),
    operationId: PARALLEL_OPERATIONS.kwicParallel,
    operation: { path: PARALLEL_ROUTES.kwicParallel, method: 'POST' },
    corpusFeaturePredicate: routeOperationPredicate(PARALLEL_ROUTES.kwicParallel, 'POST'),
    fallbackReason: t('kwic.operations.parallelKwicNotEnabled'),
  })

  async function loadParallelGroups(
    params: ParallelGroupsParams,
  ): Promise<ParallelGroupsResult> {
    await groupsGate.assertAvailable()
    const run = startParallelRun(
      PARALLEL_OPERATIONS.groups,
      `groups:${params.corpus ?? 'active'}:${Date.now()}`,
      t('kwic.operations.parallelGroups'),
      params.corpus ?? null,
    )
    try {
      const result = await getParallelGroups(params)
      operationRuns.finishRun(run.id, t('kwic.operations.parallelGroupsLoaded'))
      return result
    } catch (err) {
      failParallelRun(run, err, t('kwic.operations.parallelGroupsFailed'))
      throw err
    }
  }

  async function loadAlignmentRefDoc(
    params: AlignmentRefDocParams,
  ): Promise<AlignmentRefDocResult> {
    await alignmentGate.assertAvailable()
    const run = startParallelRun(
      PARALLEL_OPERATIONS.alignmentRefDoc,
      `refdoc:${params.refDoc}`,
      t('kwic.operations.alignmentRefDoc'),
      params.corpus ?? null,
    )
    try {
      const result = await getAlignmentRefDoc(params)
      operationRuns.finishRun(run.id, t('kwic.operations.alignmentRefDocLoaded'))
      return result
    } catch (err) {
      failParallelRun(run, err, t('kwic.operations.alignmentRefDocFailed'))
      throw err
    }
  }

  async function loadParallelKwic(
    params: ParallelKwicParams,
  ): Promise<ParallelKwicResult> {
    await parallelKwicGate.assertAvailable()
    const run = startParallelRun(
      PARALLEL_OPERATIONS.kwicParallel,
      `kwic:${params.pos}`,
      t('kwic.operations.parallelKwic'),
      params.corpus ?? null,
    )
    try {
      const result = await getParallelKwic(params)
      operationRuns.finishRun(run.id, t('kwic.operations.parallelKwicLoaded'))
      return result
    } catch (err) {
      failParallelRun(run, err, t('kwic.operations.parallelKwicFailed'))
      throw err
    }
  }

  return {
    groupsAvailability: groupsGate.availability,
    alignmentRefAvailability: alignmentGate.availability,
    parallelKwicAvailability: parallelKwicGate.availability,
    canLoadParallelGroups: computed(() => groupsGate.canUse.value),
    canOpenAlignment: computed(() => alignmentGate.canUse.value),
    canLoadParallelKwic: computed(() => parallelKwicGate.canUse.value),
    parallelGroupsBlockReason: groupsGate.blockReason,
    alignmentBlockReason: alignmentGate.blockReason,
    parallelKwicBlockReason: parallelKwicGate.blockReason,
    loadParallelGroups,
    loadAlignmentRefDoc,
    loadParallelKwic,
  }
}
