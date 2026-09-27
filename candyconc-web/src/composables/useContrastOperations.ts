import { computed } from 'vue'
import {
  createCollocatesDiffJob,
  createContrastJob,
  getLexicalDiversity,
  type AnalysisJobStart,
  type CollocatesDiffJobParams,
  type ContrastJobParams,
  type LexicalDiversityParams,
  type LexicalDiversityResult,
} from '@/api/client'
import { useProductRouteOperationGate } from '@/composables/useProductRouteOperationGate'
import { t } from '@/i18n'

export const CONTRAST_CAPABILITY_ID = 'analysis.contrast'
export const CONTRAST_ROUTES = {
  freeJob: '/api/v1/analysis/contrast',
  collocationsDiffJob: '/api/v1/analysis/collocates_diff/job',
  lexicalDiversity: '/api/v1/analysis/lexical-diversity',
} as const
export const CONTRAST_OPERATIONS = {
  freeJob: 'analysis.contrast.free_job',
  collocationsDiffJob: 'analysis.contrast.collocations_diff_job',
  lexicalDiversity: 'analysis.contrast.lexical_diversity',
} as const

export function useContrastOperations() {
  const freeJobGate = useProductRouteOperationGate({
    capabilityId: CONTRAST_CAPABILITY_ID,
    label: t('analysis.operations.freeContrastJob'),
    operationId: CONTRAST_OPERATIONS.freeJob,
    operation: { path: CONTRAST_ROUTES.freeJob, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.freeContrastJob') }),
  })
  const collocationsDiffJobGate = useProductRouteOperationGate({
    capabilityId: CONTRAST_CAPABILITY_ID,
    label: t('analysis.operations.collocationContrastJob'),
    operationId: CONTRAST_OPERATIONS.collocationsDiffJob,
    operation: { path: CONTRAST_ROUTES.collocationsDiffJob, method: 'POST' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.collocationContrastJob') }),
  })
  const lexicalDiversityGate = useProductRouteOperationGate({
    capabilityId: CONTRAST_CAPABILITY_ID,
    label: t('analysis.operations.lexicalDiversity'),
    operationId: CONTRAST_OPERATIONS.lexicalDiversity,
    operation: { path: CONTRAST_ROUTES.lexicalDiversity, method: 'GET' },
    fallbackReason: t('capabilities.store.notEnabledContext', { label: t('analysis.operations.lexicalDiversity') }),
  })

  async function createFreeContrastJob(params: ContrastJobParams): Promise<AnalysisJobStart> {
    await freeJobGate.assertAvailable()
    return createContrastJob(params)
  }

  async function createCollocationContrastJob(
    params: CollocatesDiffJobParams,
  ): Promise<AnalysisJobStart> {
    await collocationsDiffJobGate.assertAvailable()
    return createCollocatesDiffJob(params)
  }

  async function loadLexicalDiversity(
    params: LexicalDiversityParams = {},
    options: { signal?: AbortSignal } = {},
  ): Promise<LexicalDiversityResult> {
    await lexicalDiversityGate.assertAvailable()
    return getLexicalDiversity(params, options)
  }

  return {
    freeJobAvailability: freeJobGate.availability,
    collocationsDiffJobAvailability: collocationsDiffJobGate.availability,
    lexicalDiversityAvailability: lexicalDiversityGate.availability,
    canStartFreeContrastJob: computed(() => freeJobGate.canUse.value),
    canStartCollocationContrastJob: computed(() => collocationsDiffJobGate.canUse.value),
    canLoadLexicalDiversity: computed(() => lexicalDiversityGate.canUse.value),
    freeContrastJobBlockReason: freeJobGate.blockReason,
    collocationContrastJobBlockReason: collocationsDiffJobGate.blockReason,
    lexicalDiversityBlockReason: lexicalDiversityGate.blockReason,
    createFreeContrastJob,
    createCollocationContrastJob,
    loadLexicalDiversity,
  }
}
