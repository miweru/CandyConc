import type { Action, ActionMiddleware, ActionResult } from './types'
import { t } from '@/i18n'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { productActionTypeMap } from '@/lib/copilotTools'
import { parseCoKwicQuery } from '@/utils/coKwic'
import { useDocsetStore } from '@/stores/docset'
import { useQueryStore } from '@/stores/query'

const ALWAYS_ALLOWED_ACTIONS = new Set([
  'ui/toast',
  'ui/setLoading',
  'kwic/scrollToRow',
  'kwic/selectRows',
  'kwic/highlightRow',
  'kwic/expandContext',
])

function blockedResult(reason: string): ActionResult {
  return {
    success: false,
    blocked: true,
    error: reason,
    policyDecision: 'block',
    policyReason: reason,
  }
}

function fallbackCapabilityIds(action: Action): string[] | null {
  if (action.type.startsWith('query/')) return ['query.kwic']
  if (action.type.startsWith('kwic/')) return ['query.kwic']
  if (action.type === 'nav/openDocument') return ['query.document_access']
  if (action.type.startsWith('copilot/')) {
    return ['research.copilot_grounding']
  }
  return null
}

interface ActionRouteRequirement {
  label: string
  operationIds: readonly string[]
}

// Labels are catalog keys, resolved when a block reason is built.
function labeledRequirement(labelKey: string, operationIds: readonly string[]): ActionRouteRequirement {
  return { get label() { return t(labelKey) }, operationIds }
}

function operationRequirement(operationId: string, labelKey: string): ActionRouteRequirement {
  return labeledRequirement(labelKey, [operationId])
}

const ASYNC_JOB_READ_REQUIREMENTS: readonly ActionRouteRequirement[] = [
  operationRequirement('analysis.async_jobs.status', 'capabilities.gate.jobStatus'),
  operationRequirement('analysis.async_jobs.rows', 'capabilities.gate.jobRows'),
]

const FREQUENCY_SYNC_REQUIREMENTS: readonly ActionRouteRequirement[] = [
  operationRequirement('analysis.frequency.list', 'capabilities.gate.frequencyList'),
]

const SEMANTIC_SIMILAR_WORDS_REQUIREMENTS: readonly ActionRouteRequirement[] = [
  operationRequirement('analysis.semantic_similarity.similar_words', 'capabilities.gate.thesaurus'),
]

const SEMANTIC_PASSAGE_SEARCH_REQUIREMENTS: readonly ActionRouteRequirement[] = [
  operationRequirement('analysis.semantic_similarity.passage_search', 'capabilities.gate.passageSearch'),
]

const BOOKMARK_WRITE_REQUIREMENTS: readonly ActionRouteRequirement[] = [
  operationRequirement('research.bookmarks.write', 'capabilities.gate.saveBookmark'),
]

const COPILOT_STREAM_REQUIREMENTS: Record<string, readonly ActionRouteRequirement[]> = {
  'copilot/answerClarification': [
    labeledRequirement('capabilities.gate.clarification', ['research.copilot_grounding.chat_stream']),
  ],
  'copilot/continue': [
    labeledRequirement('capabilities.gate.copilotContinue', ['research.copilot_grounding.continue']),
  ],
  'copilot/sendMessage': [
    labeledRequirement('capabilities.gate.copilotChat', ['research.copilot_grounding.chat_stream']),
  ],
}

const ACTION_REQUIREMENT_GROUPS: Record<string, readonly (readonly ActionRouteRequirement[])[]> = {
  'analysis/collocations': [[
    operationRequirement('analysis.collocations.job', 'capabilities.gate.collocationJob'),
    ...ASYNC_JOB_READ_REQUIREMENTS,
  ]],
  'analysis/collocationNetwork': [[
    operationRequirement('analysis.collocation_network.graph', 'capabilities.gate.collocationNetwork'),
  ]],
  'analysis/frequency': [[
    operationRequirement('analysis.frequency.job', 'capabilities.gate.frequencyJob'),
    ...ASYNC_JOB_READ_REQUIREMENTS,
  ], FREQUENCY_SYNC_REQUIREMENTS],
  'analysis/ngramFrequency': [[
    operationRequirement('analysis.ngrams.frequency_job', 'capabilities.gate.ngramJob'),
    ...ASYNC_JOB_READ_REQUIREMENTS,
  ]],
  'analysis/keyness': [[
    operationRequirement('analysis.keyness.job', 'capabilities.gate.keynessJob'),
    ...ASYNC_JOB_READ_REQUIREMENTS,
  ]],
  'analysis/lexicalDiversity': [[
    operationRequirement('analysis.contrast.lexical_diversity', 'capabilities.gate.lexicalDiversity'),
  ]],
  'analysis/freeContrast': [[
    operationRequirement('analysis.contrast.free_job', 'capabilities.gate.freeContrastJob'),
    ...ASYNC_JOB_READ_REQUIREMENTS,
  ]],
  'analysis/collocationContrast': [[
    operationRequirement('analysis.contrast.collocations_diff_job', 'capabilities.gate.collocationContrastJob'),
    ...ASYNC_JOB_READ_REQUIREMENTS,
  ]],
  'analysis/ngramContrast': [[
    operationRequirement('analysis.ngrams.diff_job', 'capabilities.gate.ngramContrastJob'),
    ...ASYNC_JOB_READ_REQUIREMENTS,
  ]],
  'analysis/dispersion': [[
    operationRequirement('analysis.dispersion.stats', 'capabilities.gate.dispersion'),
  ]],
  'analysis/wordSketch': [[
    operationRequirement('analysis.wordsketch.profile', 'capabilities.gate.wordSketch'),
  ]],
  'analysis/wordSketchDiff': [[
    operationRequirement('analysis.wordsketch.diff', 'capabilities.gate.wordSketchDiff'),
  ]],
}

const REPLAY_EXPORT_REQUIREMENTS_BY_FORMAT: Record<string, readonly ActionRouteRequirement[]> = {
  csv: [operationRequirement('research.replay_export.concordance', 'capabilities.gate.concordanceExport')],
  tsv: [operationRequirement('research.replay_export.concordance', 'capabilities.gate.concordanceExport')],
  latex: [operationRequirement('research.replay_export.evidence_package', 'capabilities.gate.evidenceExport')],
  json: [operationRequirement('research.replay_export.concordance', 'capabilities.gate.concordanceExport')],
  jsonl: [operationRequirement('research.replay_export.concordance', 'capabilities.gate.concordanceExport')],
  'evidence-json': [operationRequirement('research.replay_export.evidence_package', 'capabilities.gate.evidenceExport')],
  pdf: [
    operationRequirement('research.replay_export.evidence_package', 'capabilities.gate.evidenceExport'),
    operationRequirement('research.replay_export.pdf', 'capabilities.gate.pdfExport'),
  ],
  docx: [
    operationRequirement('research.replay_export.evidence_package', 'capabilities.gate.evidenceExport'),
    operationRequirement('research.replay_export.docx', 'capabilities.gate.docxExport'),
  ],
}

function activeDocsetIdForActionCorpus(corpus?: string, termChanges = false): string | undefined {
  const docsetStore = useDocsetStore()
  const targetCorpus = corpus ?? docsetStore.activeCorpus
  if (
    docsetStore.hasActiveDocset &&
    !termChanges &&
    !docsetStore.isDirty &&
    docsetStore.activeCorpus === targetCorpus
  ) {
    return docsetStore.activeDocsetId ?? undefined
  }
  return undefined
}

function kwicQueryOperationIdForAction(action: Extract<Action, { type: 'query/execute' }>): string {
  const queryStore = useQueryStore()
  const targetCorpus = action.payload.filters?.corpus ?? queryStore.filters.corpus
  const termChanges = action.payload.term.trim() !== queryStore.term.trim()
  const docsetId = activeDocsetIdForActionCorpus(targetCorpus, termChanges)
  return queryStore.sortBy && !docsetId
    ? 'query.kwic.page'
    : 'query.kwic.stream'
}


function kwicLoadMoreOperationId(): string {
  const queryStore = useQueryStore()
  const docsetId = activeDocsetIdForActionCorpus(queryStore.filters.corpus)
  return queryStore.sortBy && !docsetId
    ? 'query.kwic.page'
    : 'query.kwic.stream'
}

function operationRequirementAvailable(requirement: ActionRouteRequirement): boolean {
  const productCapabilities = useProductCapabilitiesStore()
  if (requirement.operationIds?.length) {
    return requirement.operationIds.every((operationId) =>
      productCapabilities.productOperationAvailability(
        operationId,
        requirement.label,
      ).enabled,
    )
  }
  return false
}

function requirementGroupAvailable(requirements: readonly ActionRouteRequirement[]): boolean {
  return requirements.every(operationRequirementAvailable)
}

function copilotStreamRequirementGroups(actionType: string): readonly (readonly ActionRouteRequirement[])[] {
  const requirements = COPILOT_STREAM_REQUIREMENTS[actionType]
  return requirements ? [requirements] : []
}

function actionPayloadObject(action: Action): Record<string, unknown> {
  return 'payload' in action && typeof action.payload === 'object' && action.payload !== null
    ? action.payload as Record<string, unknown>
    : {}
}

function exportUsesServerConcordance(format: string, payload: Record<string, unknown>): boolean {
  if (format !== 'csv') return ['tsv', 'json', 'jsonl'].includes(format)
  if (payload.selection === 'selected') return false
  return payload.selection === 'all' || payload.selection === 'filtered' || payload.scope === 'all-server'
}

function nonExecutableExportRequirement(label: string): readonly ActionRouteRequirement[] {
  return [{ label, operationIds: [] }]
}

function exportRequirementsForAction(action: Action): readonly ActionRouteRequirement[] {
  const payload = actionPayloadObject(action)
  const format = typeof payload.format === 'string' ? payload.format : ''
  if (format === 'csv' && !exportUsesServerConcordance(format, payload)) {
    return nonExecutableExportRequirement(t('capabilities.gate.localCsv'))
  }
  if (exportUsesServerConcordance(format, payload)) {
    return REPLAY_EXPORT_REQUIREMENTS_BY_FORMAT[format] ?? nonExecutableExportRequirement(
      format ? t('capabilities.gate.unsupportedFormatNamed', { format }) : t('capabilities.gate.unsupportedFormat'),
    )
  }
  return REPLAY_EXPORT_REQUIREMENTS_BY_FORMAT[format] ?? nonExecutableExportRequirement(
    format ? t('capabilities.gate.unsupportedFormatNamed', { format }) : t('capabilities.gate.unsupportedFormat'),
  )
}

function sharedActionRequirementGroups(action: Action): readonly (readonly ActionRouteRequirement[])[] {
  if (action.type === 'analysis/frequency') {
    const groupBy = actionPayloadObject(action).groupBy
    return typeof groupBy === 'string' && groupBy !== 'word'
      ? [FREQUENCY_SYNC_REQUIREMENTS]
      : ACTION_REQUIREMENT_GROUPS[action.type] ?? [FREQUENCY_SYNC_REQUIREMENTS]
  }
  if (action.type === 'analysis/semantic') {
    return actionPayloadObject(action).mode === 'thesaurus'
      ? [SEMANTIC_SIMILAR_WORDS_REQUIREMENTS]
      : [SEMANTIC_PASSAGE_SEARCH_REQUIREMENTS]
  }
  if (action.type === 'bookmark/add' || action.type === 'bookmark/remove' || action.type === 'bookmark/clear') {
    return [BOOKMARK_WRITE_REQUIREMENTS]
  }
  if (action.type === 'export/data') {
    return [exportRequirementsForAction(action)]
  }
  return ACTION_REQUIREMENT_GROUPS[action.type] ?? []
}

function actionRouteRequirementGroups(action: Action): readonly (readonly ActionRouteRequirement[])[] {
  const sharedGroups = sharedActionRequirementGroups(action)
  if (sharedGroups.length) return sharedGroups

  if (action.type === 'query/execute') {
    const term = action.payload.term ?? ''
    if (parseCoKwicQuery(term)) {
      return [[labeledRequirement('capabilities.gate.coKwic', ['analysis.collocations.kwic'])]]
    }
    return [[labeledRequirement('capabilities.gate.kwicSearch', [kwicQueryOperationIdForAction(action)])]]
  }
  if (action.type === 'query/loadMore') {
    const queryStore = useQueryStore()
    if (parseCoKwicQuery(queryStore.term)) {
      return [[labeledRequirement('capabilities.gate.coKwicPaging', ['analysis.collocations.kwic'])]]
    }
    return [[labeledRequirement('capabilities.gate.kwicPaging', [kwicLoadMoreOperationId()])]]
  }
  if (action.type === 'nav/openDocument') {
    return [[labeledRequirement('capabilities.gate.openDocument', ['query.document_access.full_text'])]]
  }
  return copilotStreamRequirementGroups(action.type)
}

function routeOperationBlockReasonForRequirements(
  requirements: readonly ActionRouteRequirement[],
): string | null {
  const productCapabilities = useProductCapabilitiesStore()
  for (const requirement of requirements) {
    if (requirement.operationIds?.length) {
      for (const operationId of requirement.operationIds) {
        const availability = productCapabilities.productOperationAvailability(
          operationId,
          requirement.label,
        )
        if (!availability.enabled) {
          const reason = availability.disabledReason
          return reason
            ?? t('capabilities.gate.notEnabled', { label: requirement.label })
        }
      }
      continue
    }
    return t('capabilities.gate.notDirect', { label: requirement.label })
  }
  return null
}

export function routeOperationBlockReasonForAction(action: Action): string | null {
  const groups = actionRouteRequirementGroups(action)
  if (!groups.length) return null

  let firstReason: string | null = null
  for (const requirements of groups) {
    if (requirementGroupAvailable(requirements)) return null
    const reason = routeOperationBlockReasonForRequirements(requirements)
    if (!firstReason && reason) firstReason = reason
  }
  return firstReason
}

export function capabilityBlockReasonForAction(action: Action): string | null {
  if (ALWAYS_ALLOWED_ACTIONS.has(action.type)) return null

  const productCapabilities = useProductCapabilitiesStore()
  if (!productCapabilities.hasContract) {
    return productCapabilities.allowsMissingContractFallback
      ? null
      : t('capabilities.gate.catalogueMissing')
  }

  if (action.type === 'nav/switchTab') {
    return productCapabilities.isAnalysisTabVisible(action.payload.tab)
      ? null
      : t('capabilities.gate.tabNotEnabled', { tab: action.payload.tab })
  }

  const contractIds = action.type.startsWith('query/')
    ? undefined
    : productActionTypeMap(productCapabilities.contract).get(action.type)
  const capabilityIds = contractIds?.length ? contractIds : fallbackCapabilityIds(action)
  if (!capabilityIds?.length) {
    return t('capabilities.gate.actionUnknown', { action: action.type })
  }

  const blockedIds = capabilityIds.filter((id) => !productCapabilities.isVisible(id))
  if (blockedIds.length) {
    const reasons = blockedIds
      .map((id) => productCapabilities.accessBlockReason(id))
      .filter((reason): reason is string => Boolean(reason))
    return reasons.length
      ? reasons.join(' ')
      : t('capabilities.gate.actionHidden', { action: action.type, ids: blockedIds.join(', ') })
  }

  const routeReason = routeOperationBlockReasonForAction(action)
  if (routeReason) return routeReason

  return null
}

export function createProductCapabilityGateMiddleware(): ActionMiddleware {
  return async (action, next, context) => {
    const productCapabilities = useProductCapabilitiesStore()

    if (!ALWAYS_ALLOWED_ACTIONS.has(action.type)) {
      await productCapabilities.ensureAccessContext().catch(() => null)
    }

    const reason = capabilityBlockReasonForAction(action)
    if (reason) {
      return {
        ...blockedResult(reason),
        source: context.source,
        requestId: context.requestId,
        runId: context.runId,
      }
    }

    return next()
  }
}
