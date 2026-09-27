import type { ProductCapabilityContract } from '@/api/client'
import { t } from '@/i18n'

export interface ClientSideCopilotAlias {
  canonical?: string
  reason: string
}

export type CopilotToolEvidenceKind =
  | 'query'
  | 'frequency'
  | 'collocation'
  | 'network'
  | 'dispersion'
  | 'ngram'
  | 'keyness'
  | 'contrast'
  | 'wordsketch'
  | 'semantic'
  | 'document'
  | 'parallel'
  | 'docset'
  | 'annotation'
  | 'export'
  | 'navigation'
  | 'generic'

export interface CopilotToolMetadata {
  label: string
  summary: string
  evidenceKind: CopilotToolEvidenceKind
  contractLabel?: string
  contractTitle?: string
  methodNote?: string
  interpretative?: boolean
  sideEffect?: boolean
}

/**
 * Backend/product-backed Copilot tools mapped to their frontend action types.
 * Consumed by the capability-contract status logic (copilotToolContractStatus)
 * to resolve which capabilities/operations own a tool name.
 */
export const COPILOT_TOOL_TO_ACTION: Record<string, string> = {
  run_cqlf_query: 'query/execute',
  get_collocations: 'analysis/collocations',
  collocations: 'analysis/collocations',
  collocate_stats: 'analysis/collocations',
  get_frequency: 'analysis/frequency',
  frequency_list: 'analysis/frequency',
  dispersion_offsets: 'analysis/dispersion',
  similar_words: 'analysis/semantic',
  sketch_diff: 'analysis/wordSketchDiff',
  wordsketch_diff: 'analysis/wordSketchDiff',
  frequency_distribution: 'nav/switchTab',
  contrast: 'nav/switchTab',
  keyness: 'analysis/keyness',
  word_sketch: 'analysis/wordSketch',
  collocation_network: 'analysis/collocationNetwork',
  contrast_collocates: 'analysis/collocationContrast',
  ngram_frequency: 'analysis/ngramFrequency',
  ngram_contrast: 'analysis/ngramContrast',
  lexical_diversity: 'analysis/lexicalDiversity',
  semantic_search: 'analysis/semantic',
  semantic_cluster: 'nav/switchTab',
  semantic_cluster_words: 'nav/switchTab',
  semantic_recluster: 'nav/switchTab',
  scroll_to_row: 'kwic/scrollToRow',
  highlight_row: 'kwic/highlightRow',
  select_rows: 'kwic/selectRows',
  switch_tab: 'nav/switchTab',
  open_document: 'nav/openDocument',
  add_bookmark: 'bookmark/add',
  remove_bookmark: 'bookmark/remove',
  export_data: 'export/data',
}

/**
 * Names that are intentionally accepted although they are not canonical backend
 * tool names in the product contract. Keeping this explicit prevents old model
 * habits from becoming invisible product surface area.
 */
export const CLIENT_SIDE_COPILOT_ALIASES: Record<string, ClientSideCopilotAlias> = {
  get_collocations: { canonical: 'collocate_stats', reason: 'Legacy analysis alias.' },
  collocations: { canonical: 'collocate_stats', reason: 'Legacy analysis alias.' },
  get_frequency: { canonical: 'frequency_list', reason: 'Legacy analysis alias.' },
  sketch_diff: { canonical: 'word_sketch', reason: 'Client-side navigation alias for the Word Sketch diff surface.' },
  wordsketch_diff: { canonical: 'word_sketch', reason: 'Legacy spelling alias.' },
  frequency_distribution: { canonical: 'frequency_list', reason: 'Client-side navigation alias for frequency distribution.' },
  contrast: { canonical: 'compare_collocates', reason: 'Client-side navigation alias for the contrast surface.' },
  scroll_to_row: { reason: 'Client-side KWIC navigation action.' },
  highlight_row: { reason: 'Client-side KWIC highlighting action.' }, // i18n-ignore: internal English note, not displayed
  select_rows: { reason: 'Client-side KWIC selection action.' },
  switch_tab: { reason: 'Client-side navigation action.' },
  open_document: { canonical: 'document_text', reason: 'Client-side document drawer action.' },
  add_bookmark: { reason: 'Client-side bookmark action.' },
  remove_bookmark: { reason: 'Client-side bookmark action.' },
  export_data: { reason: 'Client-side export action.' },
  export_concordance: { reason: 'Forward-compatible export tool result with no local navigation.' },
  save_subcorpus: { canonical: 'create_docset', reason: 'Forward-compatible subcorpus persistence tool result.' },
}

/** Catalog keys of one metadata entry. Texts resolve on access, never at module load. */
interface CopilotToolMetadataKeys {
  labelKey: string
  summaryKey: string
  methodNoteKey?: string
  evidenceKind: CopilotToolEvidenceKind
  interpretative?: boolean
  sideEffect?: boolean
}

function toolMetadata(keys: CopilotToolMetadataKeys): CopilotToolMetadata {
  const entry: CopilotToolMetadata = {
    get label() { return t(keys.labelKey) },
    get summary() { return t(keys.summaryKey) },
    evidenceKind: keys.evidenceKind,
  }
  const methodNoteKey = keys.methodNoteKey
  if (methodNoteKey) {
    Object.defineProperty(entry, 'methodNote', {
      get: () => t(methodNoteKey),
      enumerable: true,
    })
  }
  if (keys.interpretative) entry.interpretative = true
  if (keys.sideEffect) entry.sideEffect = true
  return entry
}

export const COPILOT_TOOL_METADATA: Record<string, CopilotToolMetadata> = {
  run_cqlf_query: toolMetadata({
    labelKey: 'copilot.toolLabels.runCqlfQuery',
    summaryKey: 'copilot.toolSummaries.runCqlfQuery',
    methodNoteKey: 'copilot.toolMethodNotes.runCqlfQuery',
    evidenceKind: 'query',
  }),
  query_count: toolMetadata({
    labelKey: 'copilot.toolLabels.queryCount',
    summaryKey: 'copilot.toolSummaries.queryCount',
    evidenceKind: 'query',
  }),
  parallel_kwic: toolMetadata({
    labelKey: 'copilot.toolLabels.parallelKwic',
    summaryKey: 'copilot.toolSummaries.parallelKwic',
    methodNoteKey: 'copilot.toolMethodNotes.parallelKwic',
    evidenceKind: 'parallel',
  }),
  get_collocations: toolMetadata({
    labelKey: 'copilot.toolLabels.getCollocations',
    summaryKey: 'copilot.toolSummaries.getCollocations',
    evidenceKind: 'collocation',
  }),
  collocations: toolMetadata({
    labelKey: 'copilot.toolLabels.collocations',
    summaryKey: 'copilot.toolSummaries.collocations',
    evidenceKind: 'collocation',
  }),
  collocate_stats: toolMetadata({
    labelKey: 'copilot.toolLabels.collocateStats',
    summaryKey: 'copilot.toolSummaries.collocateStats',
    methodNoteKey: 'copilot.toolMethodNotes.collocateStats',
    evidenceKind: 'collocation',
  }),
  get_frequency: toolMetadata({
    labelKey: 'copilot.toolLabels.getFrequency',
    summaryKey: 'copilot.toolSummaries.getFrequency',
    evidenceKind: 'frequency',
  }),
  frequency_list: toolMetadata({
    labelKey: 'copilot.toolLabels.frequencyList',
    summaryKey: 'copilot.toolSummaries.frequencyList',
    evidenceKind: 'frequency',
  }),
  dispersion_offsets: toolMetadata({
    labelKey: 'copilot.toolLabels.dispersionOffsets',
    summaryKey: 'copilot.toolSummaries.dispersionOffsets',
    evidenceKind: 'dispersion',
  }),
  similar_words: toolMetadata({
    labelKey: 'copilot.toolLabels.similarWords',
    summaryKey: 'copilot.toolSummaries.similarWords',
    methodNoteKey: 'copilot.toolMethodNotes.similarWords',
    evidenceKind: 'semantic',
    interpretative: true,
  }),
  semantic_search: toolMetadata({
    labelKey: 'copilot.toolLabels.semanticSearch',
    summaryKey: 'copilot.toolSummaries.semanticSearch',
    evidenceKind: 'semantic',
    interpretative: true,
  }),
  semantic_cluster: toolMetadata({
    labelKey: 'copilot.toolLabels.semanticCluster',
    summaryKey: 'copilot.toolSummaries.semanticCluster',
    evidenceKind: 'semantic',
    interpretative: true,
    sideEffect: true,
  }),
  semantic_cluster_words: toolMetadata({
    labelKey: 'copilot.toolLabels.semanticClusterWords',
    summaryKey: 'copilot.toolSummaries.semanticClusterWords',
    evidenceKind: 'semantic',
    interpretative: true,
    sideEffect: true,
  }),
  semantic_recluster: toolMetadata({
    labelKey: 'copilot.toolLabels.semanticRecluster',
    summaryKey: 'copilot.toolSummaries.semanticRecluster',
    evidenceKind: 'semantic',
    interpretative: true,
    sideEffect: true,
  }),
  refine_cluster_label: toolMetadata({
    labelKey: 'copilot.toolLabels.refineClusterLabel',
    summaryKey: 'copilot.toolSummaries.refineClusterLabel',
    evidenceKind: 'semantic',
    interpretative: true,
    sideEffect: true,
  }),
  cluster_save: toolMetadata({
    labelKey: 'copilot.toolLabels.clusterSave',
    summaryKey: 'copilot.toolSummaries.clusterSave',
    evidenceKind: 'semantic',
    sideEffect: true,
  }),
  cluster_export_md: toolMetadata({
    labelKey: 'copilot.toolLabels.clusterExportMd',
    summaryKey: 'copilot.toolSummaries.clusterExportMd',
    evidenceKind: 'export',
    sideEffect: true,
  }),
  sketch_diff: toolMetadata({
    labelKey: 'copilot.toolLabels.sketchDiff',
    summaryKey: 'copilot.toolSummaries.sketchDiff',
    evidenceKind: 'wordsketch',
  }),
  wordsketch_diff: toolMetadata({
    labelKey: 'copilot.toolLabels.wordsketchDiff',
    summaryKey: 'copilot.toolSummaries.wordsketchDiff',
    evidenceKind: 'wordsketch',
  }),
  frequency_distribution: toolMetadata({
    labelKey: 'copilot.toolLabels.frequencyDistribution',
    summaryKey: 'copilot.toolSummaries.frequencyDistribution',
    evidenceKind: 'frequency',
  }),
  contrast: toolMetadata({
    labelKey: 'copilot.toolLabels.contrast',
    summaryKey: 'copilot.toolSummaries.contrast',
    evidenceKind: 'contrast',
  }),
  keyness: toolMetadata({
    labelKey: 'copilot.toolLabels.keyness',
    summaryKey: 'copilot.toolSummaries.keyness',
    methodNoteKey: 'copilot.toolMethodNotes.keyness',
    evidenceKind: 'keyness',
  }),
  word_sketch: toolMetadata({
    labelKey: 'copilot.toolLabels.wordSketch',
    summaryKey: 'copilot.toolSummaries.wordSketch',
    methodNoteKey: 'copilot.toolMethodNotes.wordSketch',
    evidenceKind: 'wordsketch',
  }),
  collocation_network: toolMetadata({
    labelKey: 'copilot.toolLabels.collocationNetwork',
    summaryKey: 'copilot.toolSummaries.collocationNetwork',
    methodNoteKey: 'copilot.toolMethodNotes.collocationNetwork',
    evidenceKind: 'network',
  }),
  contrast_collocates: toolMetadata({
    labelKey: 'copilot.toolLabels.contrastCollocates',
    summaryKey: 'copilot.toolSummaries.contrastCollocates',
    evidenceKind: 'contrast',
  }),
  compare_collocates: toolMetadata({
    labelKey: 'copilot.toolLabels.compareCollocates',
    summaryKey: 'copilot.toolSummaries.compareCollocates',
    methodNoteKey: 'copilot.toolMethodNotes.compareCollocates',
    evidenceKind: 'contrast',
  }),
  ngram_frequency: toolMetadata({
    labelKey: 'copilot.toolLabels.ngramFrequency',
    summaryKey: 'copilot.toolSummaries.ngramFrequency',
    evidenceKind: 'ngram',
  }),
  ngram_contrast: toolMetadata({
    labelKey: 'copilot.toolLabels.ngramContrast',
    summaryKey: 'copilot.toolSummaries.ngramContrast',
    evidenceKind: 'ngram',
  }),
  lexical_diversity: toolMetadata({
    labelKey: 'copilot.toolLabels.lexicalDiversity',
    summaryKey: 'copilot.toolSummaries.lexicalDiversity',
    methodNoteKey: 'copilot.toolMethodNotes.lexicalDiversity',
    evidenceKind: 'contrast',
  }),
  document_search: toolMetadata({
    labelKey: 'copilot.toolLabels.documentSearch',
    summaryKey: 'copilot.toolSummaries.documentSearch',
    evidenceKind: 'document',
  }),
  document_text: toolMetadata({
    labelKey: 'copilot.toolLabels.documentText',
    summaryKey: 'copilot.toolSummaries.documentText',
    evidenceKind: 'document',
  }),
  kwic_context: toolMetadata({
    labelKey: 'copilot.toolLabels.kwicContext',
    summaryKey: 'copilot.toolSummaries.kwicContext',
    evidenceKind: 'document',
  }),
  documentation_search: toolMetadata({
    labelKey: 'copilot.toolLabels.documentationSearch',
    summaryKey: 'copilot.toolSummaries.documentationSearch',
    evidenceKind: 'document',
  }),
  metadata_values: toolMetadata({
    labelKey: 'copilot.toolLabels.metadataValues',
    summaryKey: 'copilot.toolSummaries.metadataValues',
    evidenceKind: 'docset',
  }),
  list_docsets: toolMetadata({
    labelKey: 'copilot.toolLabels.listDocsets',
    summaryKey: 'copilot.toolSummaries.listDocsets',
    evidenceKind: 'docset',
  }),
  create_docset: toolMetadata({
    labelKey: 'copilot.toolLabels.createDocset',
    summaryKey: 'copilot.toolSummaries.createDocset',
    evidenceKind: 'docset',
    sideEffect: true,
  }),
  resolve_subcorpus: toolMetadata({
    labelKey: 'copilot.toolLabels.resolveSubcorpus',
    summaryKey: 'copilot.toolSummaries.resolveSubcorpus',
    evidenceKind: 'docset',
  }),
  parallel_groups: toolMetadata({
    labelKey: 'copilot.toolLabels.parallelGroups',
    summaryKey: 'copilot.toolSummaries.parallelGroups',
    evidenceKind: 'parallel',
  }),
  annotations_summary: toolMetadata({
    labelKey: 'copilot.toolLabels.annotationsSummary',
    summaryKey: 'copilot.toolSummaries.annotationsSummary',
    evidenceKind: 'annotation',
  }),
  export_concordance: toolMetadata({
    labelKey: 'copilot.toolLabels.exportConcordance',
    summaryKey: 'copilot.toolSummaries.exportConcordance',
    evidenceKind: 'export',
    sideEffect: true,
  }),
  save_subcorpus: toolMetadata({
    labelKey: 'copilot.toolLabels.saveSubcorpus',
    summaryKey: 'copilot.toolSummaries.saveSubcorpus',
    evidenceKind: 'docset',
    sideEffect: true,
  }),
  scroll_to_row: toolMetadata({
    labelKey: 'copilot.toolLabels.scrollToRow',
    summaryKey: 'copilot.toolSummaries.scrollToRow',
    evidenceKind: 'navigation',
  }),
  highlight_row: toolMetadata({
    labelKey: 'copilot.toolLabels.highlightRow',
    summaryKey: 'copilot.toolSummaries.highlightRow',
    evidenceKind: 'navigation',
  }),
  select_rows: toolMetadata({
    labelKey: 'copilot.toolLabels.selectRows',
    summaryKey: 'copilot.toolSummaries.selectRows',
    evidenceKind: 'navigation',
  }),
  switch_tab: toolMetadata({
    labelKey: 'copilot.toolLabels.switchTab',
    summaryKey: 'copilot.toolSummaries.switchTab',
    evidenceKind: 'navigation',
  }),
  open_document: toolMetadata({
    labelKey: 'copilot.toolLabels.openDocument',
    summaryKey: 'copilot.toolSummaries.openDocument',
    evidenceKind: 'document',
  }),
  add_bookmark: toolMetadata({
    labelKey: 'copilot.toolLabels.addBookmark',
    summaryKey: 'copilot.toolSummaries.addBookmark',
    evidenceKind: 'navigation',
    sideEffect: true,
  }),
  remove_bookmark: toolMetadata({
    labelKey: 'copilot.toolLabels.removeBookmark',
    summaryKey: 'copilot.toolSummaries.removeBookmark',
    evidenceKind: 'navigation',
    sideEffect: true,
  }),
  export_data: toolMetadata({
    labelKey: 'copilot.toolLabels.exportData',
    summaryKey: 'copilot.toolSummaries.exportData',
    evidenceKind: 'export',
    sideEffect: true,
  }),
}

export function copilotToolMetadata(toolName: string): CopilotToolMetadata {
  return COPILOT_TOOL_METADATA[toolName] ?? {
    label: toolName,
    summary: t('copilot.toolSummaries.unclassified'),
    evidenceKind: 'generic',
  }
}

export type CopilotToolContractStatus =
  | { status: 'product'; capabilityIds: string[]; operationIds: string[] }
  | { status: 'client_alias'; alias: ClientSideCopilotAlias; canonicalCapabilityIds: string[]; operationIds: string[] }
  | { status: 'unknown' }

export function productCopilotToolMap(contract: ProductCapabilityContract | null | undefined): Map<string, string[]> {
  const map = new Map<string, string[]>()
  const addTool = (tool: string, capabilityId: string) => {
    const ids = map.get(tool) ?? []
    ids.push(capabilityId)
    map.set(tool, [...new Set(ids)])
  }
  for (const capability of contract?.capabilities ?? []) {
    for (const tool of capability.copilot_tools ?? []) {
      addTool(tool, capability.id)
    }
    for (const operation of capability.operations ?? []) {
      for (const tool of operation.copilot_tools ?? []) {
        addTool(tool, operation.capability_id || capability.id)
      }
    }
  }
  return map
}

export function productOperationToolMap(contract: ProductCapabilityContract | null | undefined): Map<string, Array<{ capabilityId: string; operationId: string }>> {
  const map = new Map<string, Array<{ capabilityId: string; operationId: string }>>()
  for (const capability of contract?.capabilities ?? []) {
    for (const operation of capability.operations ?? []) {
      for (const key of (operation.copilot_tools ?? []).map((tool) => tool.trim()).filter(Boolean)) {
        const entries = map.get(key) ?? []
        entries.push({
          capabilityId: operation.capability_id || capability.id,
          operationId: operation.id,
        })
        map.set(key, entries)
      }
    }
  }
  return map
}

function contractDeclaredActionOperationIds(
  actionType: string | undefined,
  contract: ProductCapabilityContract | null | undefined,
): string[] {
  if (!actionType) return []
  return [
    ...new Set(
      (contract?.capabilities ?? [])
        .filter((capability) => (capability.action_types ?? []).includes(actionType))
        .flatMap((capability) =>
          (capability.operations ?? []).map((operation) => operation.id),
        ),
    ),
  ]
}

export function visibleProductCopilotToolMap(contract: ProductCapabilityContract | null | undefined): Map<string, string[]> {
  const map = new Map<string, string[]>()
  const addTool = (tool: string, capabilityId: string) => {
    const ids = map.get(tool) ?? []
    ids.push(capabilityId)
    map.set(tool, [...new Set(ids)])
  }
  for (const capability of contract?.capabilities ?? []) {
    if (capability.visibility !== 'first_class_ui') continue
    if (capability.maturity === 'planned' || capability.maturity === 'unsupported') continue
    for (const tool of capability.copilot_tools ?? []) {
      addTool(tool, capability.id)
    }
    for (const operation of capability.operations ?? []) {
      for (const tool of operation.copilot_tools ?? []) {
        addTool(tool, operation.capability_id || capability.id)
      }
    }
  }
  return map
}

export function productActionTypeMap(contract: ProductCapabilityContract | null | undefined): Map<string, string[]> {
  const map = new Map<string, string[]>()
  for (const capability of contract?.capabilities ?? []) {
    for (const actionType of capability.action_types ?? []) {
      const ids = map.get(actionType) ?? []
      ids.push(capability.id)
      map.set(actionType, ids)
    }
  }
  return map
}

export interface CopilotControlTool {
  name: string
  role: string
  label: string
  description: string
}

/**
 * The contract entry of a copilot tool that steers the turn instead of reading
 * the corpus (e.g. `deutung_abgeben`). The backend contract is the only source,
 * the UI keeps no list of its own.
 */
export function copilotControlTool(
  toolName: string,
  contract: ProductCapabilityContract | null | undefined,
): CopilotControlTool | null {
  const entry = (contract?.copilot_control_tools ?? []).find((tool) => tool.name === toolName)
  if (!entry) return null
  return {
    name: entry.name,
    role: entry.role,
    label: entry.label ?? entry.name,
    description: entry.description ?? '',
  }
}

export function copilotToolContractStatus(
  toolName: string,
  contract: ProductCapabilityContract | null | undefined
): CopilotToolContractStatus {
  const productTools = productCopilotToolMap(contract)
  const operationTools = productOperationToolMap(contract)
  const capabilityIds = productTools.get(toolName)
  if (capabilityIds) {
    const actionType = COPILOT_TOOL_TO_ACTION[toolName]
    const actionOperationIds = contractDeclaredActionOperationIds(actionType, contract)
    const handlerOperationIds = (operationTools.get(toolName) ?? [])
      .filter((entry) => capabilityIds.includes(entry.capabilityId))
      .map((entry) => entry.operationId)
    return {
      status: 'product',
      capabilityIds,
      operationIds: [...new Set([...handlerOperationIds, ...actionOperationIds])],
    }
  }

  const alias = CLIENT_SIDE_COPILOT_ALIASES[toolName]
    if (alias) {
    const directOperationEntries = operationTools.get(toolName) ?? []
    if (alias.canonical && contract) {
      const canonicalCapabilityIds = productTools.get(alias.canonical)
      if (!canonicalCapabilityIds) {
        return { status: 'unknown' }
      }
      const operationEntries = directOperationEntries.length
        ? directOperationEntries
        : operationTools.get(alias.canonical) ?? []
      const actionType = COPILOT_TOOL_TO_ACTION[toolName]
      const actionOperationIds = contractDeclaredActionOperationIds(actionType, contract)
      return {
        status: 'client_alias',
        alias,
        canonicalCapabilityIds,
        operationIds: [
          ...new Set([
            ...operationEntries
              .filter((entry) => canonicalCapabilityIds.includes(entry.capabilityId))
              .map((entry) => entry.operationId),
            ...actionOperationIds,
          ]),
        ],
      }
    }
    if (contract) {
      const actionType = COPILOT_TOOL_TO_ACTION[toolName]
      const actionCapabilityIds = actionType ? productActionTypeMap(contract).get(actionType) : undefined
      if (actionType && actionCapabilityIds) {
        const actionOperationIds = contractDeclaredActionOperationIds(actionType, contract)
        return {
          status: 'client_alias',
          alias,
          canonicalCapabilityIds: actionCapabilityIds,
          operationIds: actionOperationIds,
        }
      }
      if (directOperationEntries.length) {
        return {
          status: 'client_alias',
          alias,
          canonicalCapabilityIds: [...new Set(directOperationEntries.map((entry) => entry.capabilityId))],
          operationIds: directOperationEntries.map((entry) => entry.operationId),
        }
      }
      return { status: 'unknown' }
    }
    return { status: 'client_alias', alias, canonicalCapabilityIds: [], operationIds: [] }
  }

  return { status: 'unknown' }
}
