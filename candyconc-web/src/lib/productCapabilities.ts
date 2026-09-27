import type { ActiveTab, SettingsTab } from '@/stores/ui'
import type {
  ProductCapability,
  ProductCapabilityOperation,
} from '@/api/client'
import { t } from '@/i18n'

export type ProductCapabilitySurfaceKind =
  | 'analysis_tab'
  | 'search_workbench'
  | 'corpus_manager'
  | 'workspace_panel'
  | 'job_lifecycle'
  | 'kwic_layer'
  | 'copilot_panel'
  | 'export_dialog'
  | 'settings_panel'
  | 'session_panel'

export type ProductCapabilityOpenTarget =
  | { kind: 'analysis_tab'; tab: ActiveTab }
  | { kind: 'query_builder' }
  | { kind: 'kwic_tab' }
  | { kind: 'subcorpus_drawer' }
  | { kind: 'corpus_manager' }
  | { kind: 'workspace'; tab: 'subcorpora' | 'analyses' }
  | { kind: 'copilot' }
  | { kind: 'export_dialog' }
  | { kind: 'settings'; tab?: SettingsTab }
  | { kind: 'auth' }
  | { kind: 'bookmarks' }
  | { kind: 'annotation_settings' }

export interface ProductCapabilitySurface {
  capabilityId: string
  kind: ProductCapabilitySurfaceKind
  label: string
  openTarget?: ProductCapabilityOpenTarget
  tab?: ActiveTab
  shortcut?: string
  primary?: boolean
  commandId?: string
  commandLabel?: string
}


export type ProductOperationGenericAction =
  | 'open_surface'
  | 'inspect_only'

export type ProductOperationExecutionPolicy =
  | 'contextual_ui'
  | 'confirmed_contextual_ui'
  | 'none'

const NATIVE_CONFIRMATION_OPERATION_ID = 'corpus.catalogue.unregister'

function normalizeProductOperationExecutionPolicy(
  value: string | null | undefined,
): ProductOperationExecutionPolicy {
  if (value === 'contextual_ui' || value === 'confirmed_contextual_ui' || value === 'none') {
    return value
  }
  return 'contextual_ui'
}

function inferredProductOperationExecutionPolicy(
  operation: ProductCapabilityOperation,
): ProductOperationExecutionPolicy {
  // A click in a concrete product surface is already an explicit decision.
  // Native confirmation belongs only to removing a corpus registration; jobs,
  // analyses and ordinary saved research state report progress or failure in
  // place instead of trapping researchers in repeated dialogs.
  return operation.id === NATIVE_CONFIRMATION_OPERATION_ID
    ? 'confirmed_contextual_ui'
    : 'contextual_ui'
}

function effectiveProductOperationExecutionPolicy(
  operation: ProductCapabilityOperation,
): ProductOperationExecutionPolicy {
  const advertisedPolicy = operation.ui_execution_policy
    ? normalizeProductOperationExecutionPolicy(operation.ui_execution_policy)
    : inferredProductOperationExecutionPolicy(operation)

  // Old servers used confirmation for every long-running request. Keep the
  // current UI usable while such a server is still running: only removing a
  // corpus registration may open a native confirmation dialog.
  if (
    advertisedPolicy === 'confirmed_contextual_ui'
    && operation.id !== NATIVE_CONFIRMATION_OPERATION_ID
  ) {
    return 'contextual_ui'
  }
  return advertisedPolicy
}

export interface ProductOperationAdapterPolicy {
  inspectionAllowed: boolean
  surfaceOpenAllowed: boolean
  genericAction: ProductOperationGenericAction
  executionPolicy: ProductOperationExecutionPolicy
  requiresParameters: boolean
  requiresConfirmation: boolean
  reason: string | null
}

export interface AnalysisTabSurface extends ProductCapabilitySurface {
  kind: 'analysis_tab'
  tab: ActiveTab
  shortcut: string
}

// Labels are catalog keys resolved on every read, so a language switch
// relabels tabs, menus and commands without rebuilding these tables.
function analysisSurface(
  capabilityId: string,
  tab: ActiveTab,
  labelKey: string,
  shortcut: string,
  commandId: string,
  primary = false,
): AnalysisTabSurface {
  return {
    capabilityId,
    kind: 'analysis_tab',
    tab,
    get label() { return t(labelKey) },
    shortcut,
    commandId,
    ...(primary ? { primary } : {}),
  }
}

function surface(
  capabilityId: string,
  kind: ProductCapabilitySurfaceKind,
  labelKey: string,
  openTarget?: ProductCapabilityOpenTarget,
  options: Pick<ProductCapabilitySurface, 'shortcut' | 'commandId'> & { commandLabelKey?: string } = {},
): ProductCapabilitySurface {
  const { commandLabelKey, ...rest } = options
  const record: ProductCapabilitySurface = {
    capabilityId,
    kind,
    get label() { return t(labelKey) },
    ...(openTarget ? { openTarget } : {}),
    ...rest,
  }
  if (commandLabelKey) {
    Object.defineProperty(record, 'commandLabel', {
      get: () => t(commandLabelKey),
      enumerable: true,
    })
  }
  return record
}

export const analysisTabSurfaces: readonly AnalysisTabSurface[] = [
  analysisSurface('query.kwic', 'kwic', 'capabilities.tabs.kwic', 'Alt+1', 'nav-kwic', true),
  // Der Leser steht VOR den Auswertungen, weil man ein Korpus liest,
  // bevor man es misst. Er haengt an query.document_access, also an
  // derselben Faehigkeit wie Volltext und Snippet, und nicht an einer
  // erfundenen eigenen.
  analysisSurface('query.corpus_reader', 'reader', 'capabilities.tabs.reader', 'Alt+L', 'nav-reader', true),
  analysisSurface('analysis.frequency', 'frequency', 'capabilities.tabs.frequency', 'Alt+2', 'nav-frequency', true),
  analysisSurface('analysis.collocations', 'collocations', 'capabilities.tabs.collocations', 'Alt+3', 'nav-collocations', true),
  analysisSurface('analysis.collocation_network', 'collocation_network', 'capabilities.tabs.collocationNetwork', 'Alt+0', 'analysis-collocation-network'),
  analysisSurface('analysis.dispersion', 'dispersion', 'capabilities.tabs.dispersion', 'Alt+4', 'nav-dispersion', true),
  analysisSurface('analysis.semantic_similarity', 'semantic', 'capabilities.tabs.semantic', 'Alt+5', 'nav-semantic', true),
  analysisSurface('analysis.ngrams', 'ngrams', 'capabilities.tabs.ngrams', 'Alt+6', 'analysis-ngrams'),
  analysisSurface('analysis.contrast', 'contrast', 'capabilities.tabs.contrast', 'Alt+7', 'analysis-contrast', true),
  analysisSurface('analysis.keyness', 'keyness', 'capabilities.tabs.keyness', 'Alt+8', 'analysis-keyness'),
  analysisSurface('analysis.wordsketch', 'wordsketch', 'capabilities.tabs.wordsketch', 'Alt+9', 'analysis-wordsketch'),
  analysisSurface('analysis.trend', 'trend', 'capabilities.tabs.trend', 'Alt+T', 'analysis-trend'),
]

export const productCapabilitySurfaces: readonly ProductCapabilitySurface[] = [
  ...analysisTabSurfaces,
  surface('platform.session', 'session_panel', 'capabilities.surfaces.session', { kind: 'auth' }, { commandId: 'session-open', commandLabelKey: 'capabilities.surfaces.sessionCommand' }),
  surface('query.cqlf', 'search_workbench', 'capabilities.surfaces.queryBuilder', { kind: 'query_builder' }, { shortcut: 'Cmd+B', commandId: 'query-builder', commandLabelKey: 'capabilities.surfaces.queryBuilderCommand' }),
  surface('query.document_access', 'kwic_layer', 'capabilities.surfaces.documentAccess', { kind: 'kwic_tab' }),
  surface('corpus.catalogue', 'corpus_manager', 'capabilities.surfaces.corpusCatalogue', { kind: 'corpus_manager' }, { commandId: 'corpus-catalogue-open', commandLabelKey: 'capabilities.surfaces.corpusCatalogueCommand' }),
  surface('corpus.import', 'corpus_manager', 'capabilities.surfaces.corpusImport', { kind: 'corpus_manager' }, { commandId: 'corpus-manager-open', commandLabelKey: 'capabilities.surfaces.corpusImportCommand' }),
  surface('analysis.async_jobs', 'job_lifecycle', 'capabilities.surfaces.analysisJobs', { kind: 'workspace', tab: 'analyses' }),
  surface('research.subcorpora_docsets', 'workspace_panel', 'capabilities.surfaces.subcorpora', { kind: 'subcorpus_drawer' }),
  surface('research.annotations', 'kwic_layer', 'capabilities.surfaces.annotations', { kind: 'kwic_tab' }),
  surface('research.bookmarks', 'kwic_layer', 'capabilities.surfaces.bookmarks', { kind: 'bookmarks' }, { commandId: 'settings-bookmarks', commandLabelKey: 'capabilities.surfaces.bookmarksCommand' }),
  surface('research.analysis_presets', 'workspace_panel', 'capabilities.surfaces.analysisPresets', { kind: 'workspace', tab: 'analyses' }),
  surface('research.copilot_grounding', 'copilot_panel', 'capabilities.surfaces.copilot', { kind: 'copilot' }, { shortcut: 'Cmd+Shift+K', commandId: 'copilot-open', commandLabelKey: 'capabilities.surfaces.copilotCommand' }),
  surface('research.replay_export', 'export_dialog', 'capabilities.surfaces.export', { kind: 'export_dialog' }, { shortcut: 'Cmd+E', commandId: 'export-open', commandLabelKey: 'capabilities.surfaces.exportCommand' }),
  surface('admin.system_operations', 'settings_panel', 'capabilities.surfaces.system', { kind: 'settings', tab: 'system' }),
  surface('settings.preferences', 'settings_panel', 'capabilities.surfaces.preferences', { kind: 'settings', tab: 'general' }, { shortcut: 'Cmd+,', commandId: 'settings-open', commandLabelKey: 'capabilities.surfaces.preferencesCommand' }),
  surface('settings.embedding_management', 'settings_panel', 'capabilities.surfaces.embeddings', { kind: 'settings', tab: 'embeddings' }),
  surface('settings.model_route', 'settings_panel', 'capabilities.surfaces.modelRoute', { kind: 'settings', tab: 'modelroute' }),
  surface('corpus.alignment_parallel', 'kwic_layer', 'capabilities.surfaces.parallelKwic', { kind: 'kwic_tab' }),
]

function isReadOnlyProductOperation(operation: ProductCapabilityOperation): boolean {
  const effects = operation.effects ?? []
  return (
    effects.length > 0 &&
    effects.every((effect) => effect === 'read') &&
    !operation.route.mutates
  )
}

export function productOperationAdapterPolicyFor(
  operation: ProductCapabilityOperation,
  adapterStatus: string,
  adapterReason: string | null = null,
): ProductOperationAdapterPolicy {
  const contractExecutionPolicy = effectiveProductOperationExecutionPolicy(operation)
  const requiresParameters = operation.requires_parameters ?? true
  if (adapterStatus !== 'ready') {
    return {
      inspectionAllowed: true,
      surfaceOpenAllowed: false,
      genericAction: 'inspect_only',
      executionPolicy: 'none',
      requiresParameters,
      requiresConfirmation: false,
      reason: adapterReason ?? t('capabilities.adapter.noFirstClassUi'),
    }
  }
  if (!isReadOnlyProductOperation(operation)) {
    return {
      inspectionAllowed: true,
      surfaceOpenAllowed: false,
      genericAction: 'inspect_only',
      executionPolicy: contractExecutionPolicy,
      requiresParameters,
      requiresConfirmation: contractExecutionPolicy === 'confirmed_contextual_ui',
      reason: contractExecutionPolicy === 'confirmed_contextual_ui'
        ? t('capabilities.adapter.inspectOnlyConfirm')
        : t('capabilities.adapter.inspectOnly'),
    }
  }
  if (contractExecutionPolicy === 'none') {
    return {
      inspectionAllowed: true,
      surfaceOpenAllowed: false,
      genericAction: 'inspect_only',
      executionPolicy: 'none',
      requiresParameters,
      requiresConfirmation: false,
      reason: t('capabilities.adapter.notGeneric'),
    }
  }
  return {
    inspectionAllowed: true,
    surfaceOpenAllowed: true,
    genericAction: 'open_surface',
    executionPolicy: contractExecutionPolicy,
    requiresParameters,
    requiresConfirmation: contractExecutionPolicy === 'confirmed_contextual_ui',
    reason: null,
  }
}

export function surfaceForCapability(
  id: string,
): ProductCapabilitySurface | undefined {
  return productCapabilitySurfaces.find(
    (surface) => surface.capabilityId === id,
  )
}

export function analysisSurfaceForTab(
  tab: string,
): AnalysisTabSurface | undefined {
  return analysisTabSurfaces.find((surface) => surface.tab === tab)
}

export function isCapabilityFirstClass(
  capability: ProductCapability | undefined,
): boolean {
  return Boolean(
    capability &&
    capability.visibility === 'first_class_ui' &&
    capability.maturity !== 'unsupported',
  )
}

export function isCapabilityNavigable(
  capability: ProductCapability | undefined,
): boolean {
  if (!capability) return false
  return (
    capability.visibility === 'first_class_ui' &&
    !['planned', 'unsupported'].includes(capability.maturity)
  )
}
