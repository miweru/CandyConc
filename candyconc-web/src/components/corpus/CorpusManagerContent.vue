<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { CheckCircle2, Database, FileSearch, FileText, FolderPlus, RefreshCw, Trash2, UploadCloud } from 'lucide-vue-next'
import {
  CORPUS_CATALOGUE_OPERATIONS,
  useCorpusCapabilitiesStore,
} from '@/stores/corpusCapabilities'
import {
  CORPUS_IMPORT_OPERATIONS,
  preflightBlocksImport,
  useCorpusImportsStore,
} from '@/stores/corpusImports'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useSessionStore } from '@/stores/session'
import { useProductOperationFocus } from '@/composables/useProductOperationFocus'
import {
  advancedImportWarnings,
  choiceDescription,
  choiceKey,
  choiceLabel,
  choiceValue,
  defaultUiValue,
  optionDefaultLabel,
  optionLabel,
  optionTypeLabel,
  parseAdvancedImportOptions,
  typedOptionsFromSpecs,
  type CorpusImportParsedOptions,
} from '@/lib/corpusImportContract'
import {
  canActivateCorpusWithPartialImportAcknowledgement,
  canUnregisterCorpusSummary,
  corpusActivationBlockReason,
  corpusRequiresPartialImportAcknowledgement,
  corpusUnregisterBlockReason,
} from '@/lib/corpusCataloguePolicy'
import {
  importReportEntriesFromPayload,
  importReportOutcomeFromPayload,
  type ImportReportEntry,
  type ImportReportPayload,
  type ImportReportOutcome,
} from '@/lib/importReportDiagnostics'
import CorpusFeatureEvidence from '@/components/corpus/CorpusFeatureEvidence.vue'
import CorpusImportPreflightEvidence from '@/components/corpus/CorpusImportPreflightEvidence.vue'
import CorpusReportList from '@/components/corpus/CorpusReportList.vue'
import type { CorpusImportJob, CorpusImportMethod, CorpusImportOptionChoice, CorpusSummary } from '@/api/client'
import { formatNumber, formatDateTime } from '@/i18n/format'
import { corpusLanguageLabel, corpusLanguageName, suggestedPipeline } from '@/lib/corpusLanguage'
import { useI18n } from 'vue-i18n'
import { corpusDisplayName } from '@/lib/corpusDisplayName'

const { t } = useI18n()

const corpusStore = useCorpusCapabilitiesStore()
const importStore = useCorpusImportsStore()
const productCapabilities = useProductCapabilitiesStore()
const sessionStore = useSessionStore()
const { focusedSurfaceSlot, focusMatches, consumeFocusFor } = useProductOperationFocus()

const method = ref('')
const inputPath = ref('')
const targetName = ref('')
const activateOnSuccess = ref(false)
const optionsJson = ref('')
const optionValues = ref<Record<string, unknown>>({})
const registerPath = ref('')
const registerActivate = ref(false)
const catalogueActionError = ref<string | null>(null)
const partialImportAcknowledgements = ref<Record<string, boolean>>({})

const importJobRetentionNote = computed(() => t('corpus.manager.retentionNote'))

const methodOptions = computed(() => importStore.methodOptions)
const selectedMethod = computed(() => methodOptions.value.find((item) => item.method === method.value))
const selectedMethodInput = computed(() => selectedMethod.value?.input)
const selectedInputKind = computed(() => selectedMethodInput.value?.kind ?? 'server_file')
const selectedAcceptsDirectories = computed(() => Boolean(selectedMethodInput.value?.accepts_directories))
const selectedInputExtensions = computed(() => selectedMethodInput.value?.extensions ?? [])
const selectedInputKindLabel = computed(() => inputKindLabel(selectedInputKind.value))
const selectedInputContractLabel = computed(() => {
  if (selectedInputKind.value === 'server_directory') return t('corpus.manager.inputServerDirectory')
  if (selectedInputKind.value === 'server_file' && selectedAcceptsDirectories.value) return t('corpus.manager.inputServerFileOrDirectory')
  if (selectedInputKind.value === 'server_file') return t('corpus.manager.inputServerFile')
  return selectedInputKindLabel.value
})
const inputPathFieldLabel = computed(() => selectedInputContractLabel.value)
const inputPathPlaceholder = computed(() => {
  if (selectedMethodInput.value?.path_hint) return selectedMethodInput.value.path_hint
  if (selectedInputKind.value === 'hf_dataset') return 'organisation/dataset-name'
  return selectedAcceptsDirectories.value || selectedInputKind.value === 'server_directory'
    ? t('corpus.manager.placeholderDirectory')
    : t('corpus.manager.placeholderFile')
})
const inputPathHelp = computed(() => {
  if (selectedInputKind.value === 'hf_dataset') {
    return selectedMethodInput.value?.description
      || t('corpus.manager.helpHfDataset')
  }
  const sentences = [
    selectedAcceptsDirectories.value || selectedInputKind.value === 'server_directory'
      ? t('corpus.manager.helpAcceptsDirectories')
      : t('corpus.manager.helpExpectsFile'),
  ]
  if (selectedInputExtensions.value.length) {
    sentences.push(t('corpus.manager.helpExtensions', { extensions: selectedInputExtensions.value.join(', ') }))
  }
  sentences.push(t('corpus.manager.helpServerReadable'))
  return sentences.join(' ')
})
const selectedMethodAvailability = computed(() => selectedMethod.value?.availability ?? null)
const selectedMethodAvailabilityStatus = computed(() =>
  String(selectedMethodAvailability.value?.status ?? 'unknown').toLowerCase()
)
const selectedMethodIsAvailable = computed(() =>
  !selectedMethodAvailability.value || selectedMethodAvailabilityStatus.value === 'available'
)
const selectedMethodAvailabilityText = computed(() => {
  if (!selectedMethodAvailability.value) return null
  if (selectedMethodAvailabilityStatus.value === 'available') {
    return selectedMethodAvailability.value.script
      ? t('corpus.manager.builderAvailableScript', { script: selectedMethodAvailability.value.script })
      : t('corpus.manager.builderAvailable')
  }
  return selectedMethodAvailability.value.reason
    ? t('corpus.manager.builderUnavailableReason', { reason: selectedMethodAvailability.value.reason })
    : t('corpus.manager.builderUnavailable')
})
const selectedMethodOptionSpecs = computed(() => selectedMethod.value?.option_specs ?? [])
const selectedMethodOptionKeys = computed(() => {
  const keys = selectedMethod.value?.option_keys
  if (Array.isArray(keys) && keys.length) return keys.map((key) => String(key)).filter(Boolean)
  return selectedMethodOptionSpecs.value.map((spec) => spec.key).filter(Boolean)
})
const selectedExpectedColumns = computed(() => selectedMethod.value?.expected_columns ?? [])
const selectedOutput = computed(() => selectedMethod.value?.output ?? null)
const selectedReports = computed(() => selectedMethod.value?.reports ?? [])
const selectedEmittedFeatures = computed(() =>
  selectedMethod.value?.emitted_features?.length
    ? selectedMethod.value.emitted_features
    : selectedOutput.value?.emitted_features ?? []
)
const selectedMethodWorkflowLabel = computed(() =>
  selectedMethod.value ? importMethodWorkflowLabel(selectedMethod.value) : null
)
const selectedMethodWorkflowReason = computed(() =>
  selectedMethod.value ? importMethodWorkflowReason(selectedMethod.value) : null
)
const selectedMethodWorkflowOk = computed(() =>
  selectedMethod.value ? importMethodWorkflowIsFirstClass(selectedMethod.value) : true
)
const isImportWorkflowFocused = computed(() => focusMatches('corpus.import'))
const isImportFormFocused = computed(() =>
  focusMatches('corpus.import.methods', 'corpus.import.preflight', 'corpus.import.start')
)
const isImportJobsFocused = computed(() =>
  focusMatches('corpus.import.jobs', 'corpus.import.job')
)
const isRegisterFocused = computed(() => focusMatches('corpus.catalogue.register'))
const isCatalogueFocused = computed(() =>
  focusMatches('corpus.catalogue', 'corpus.import.build_report')
)
consumeFocusFor([
  'corpus.import',
  'corpus.catalogue',
], () => undefined)
const hasTypedOptionSpecs = computed(() => selectedMethodOptionSpecs.value.length > 0)
const importCapability = computed(() => productCapabilities.capabilityFor('corpus.import'))
const isImportFirstClass = computed(() =>
  Boolean(importCapability.value) &&
  importCapability.value?.visibility === 'first_class_ui' &&
  !['planned', 'unsupported'].includes(importCapability.value?.maturity ?? '')
)
const catalogueListAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_CATALOGUE_OPERATIONS.list)
)
const canUseCatalogue = computed(() => catalogueListAvailability.value.enabled)

const importMethodsAvailability = computed(() => importStore.importMethodsAvailability)
const importPreflightAvailability = computed(() => importStore.importPreflightAvailability)
const importStartAvailability = computed(() => importStore.importStartAvailability)
const importListAvailability = computed(() => importStore.importListAvailability)
const importRefreshAvailability = computed(() => importStore.importRefreshAvailability)
const importCancelAvailability = computed(() => importStore.importCancelAvailability)
const importReportsAvailability = computed(() => importStore.importReportsAvailability)
const registerCorpusAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_CATALOGUE_OPERATIONS.register)
)
const activateCorpusAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_CATALOGUE_OPERATIONS.activate)
)
const corpusCapabilitiesAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_CATALOGUE_OPERATIONS.capabilities)
)
const buildReportsAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.buildReport)
)
const unregisterCorporaAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_CATALOGUE_OPERATIONS.unregister)
)

const canLoadImportMethods = computed(() => importMethodsAvailability.value.enabled)
const canRunImportPreflightRoute = computed(() => importPreflightAvailability.value.enabled)
const canStartImportJob = computed(() => importStartAvailability.value.enabled)
const canListImportJobs = computed(() => importListAvailability.value.enabled)
const canRefreshImportJobs = computed(() => importRefreshAvailability.value.enabled)
const canCancelImportJobs = computed(() => importCancelAvailability.value.enabled)
const canLoadImportJobReports = computed(() => importReportsAvailability.value.enabled)
const canUseImport = computed(() =>
  canLoadImportMethods.value || canRunImportPreflightRoute.value || canStartImportJob.value
)
const canRegisterCorpus = computed(() =>
  canUseCatalogue.value && registerCorpusAvailability.value.enabled
)
const canActivateCorpora = computed(() =>
  canUseCatalogue.value && activateCorpusAvailability.value.enabled
)
const canRefreshCorpusCapabilities = computed(() =>
  canUseCatalogue.value && corpusCapabilitiesAvailability.value.enabled
)
const canLoadBuildReports = computed(() => buildReportsAvailability.value.enabled)
const canUnregisterCorpora = computed(() =>
  canUseCatalogue.value && unregisterCorporaAvailability.value.enabled
)

const importMethodCatalogueRows = computed(() =>
  methodOptions.value.map((item) => ({
    method: item.method,
    label: item.label || item.method,
    description: item.description || '',
    workflowLabel: importMethodWorkflowLabel(item),
    workflowOk: importMethodWorkflowIsFirstClass(item),
    inputLabel: importMethodInputLabel(item),
    outputLabel: importMethodOutputLabel(item),
    availabilityLabel: importMethodAvailabilityLabel(item),
    availabilityOk: importMethodIsAvailable(item),
    optionCount: item.option_specs?.length ?? 0,
    expectedColumnCount: item.expected_columns?.length ?? 0,
    reportCount: item.reports?.length ?? 0,
    emittedFeatures: item.emitted_features?.length
      ? item.emitted_features
      : item.output?.emitted_features ?? [],
    selected: item.method === method.value,
  }))
)

// Replace the generic operation label in a role or visibility denial with the
// label of this panel. The fixed text parts come from the active catalog, so
// the rewrite works in every language.
function catalogTail(key: string, params: Record<string, string>, marker: string): string | null {
  const probe = t(key, { label: '\u0000', ...params })
  const start = probe.indexOf('\u0000')
  const end = marker ? probe.indexOf(marker) : probe.length
  return start < 0 || end < 0 ? null : probe.slice(start + 1, end)
}

function scopedAccessMessage(reason: string | null | undefined, label: string): string | null {
  if (!reason) return null
  const roleTail = catalogTail('layout.session.roleRequired', { required: '\u0001', current: '\u0002' }, '\u0001')
  const roleIndex = roleTail ? reason.indexOf(roleTail) : -1
  if (roleTail && roleIndex > 0) return `${label}${reason.slice(roleIndex)}`
  const hiddenTail = catalogTail('capabilities.store.notSurface', {}, '')
  if (hiddenTail && reason.endsWith(hiddenTail) && reason.length > hiddenTail.length) return `${label}${hiddenTail}`
  return reason
}

const importAccessMessage = computed(() =>
  !importCapability.value ||
    importCapability.value.visibility !== 'first_class_ui' ||
    ['planned', 'unsupported'].includes(importCapability.value.maturity)
    ? t('corpus.manager.importNotSurface')
    : scopedAccessMessage(importStartAvailability.value.disabledReason, t('corpus.manager.labelCorpusImport'))
      ?? t('corpus.manager.importNotEnabledCatalogue')
)
const preflightAccessMessage = computed(() => importPreflightAvailability.value.disabledReason)
const importMethodsAccessMessage = computed(() => importMethodsAvailability.value.disabledReason)
const importJobRefreshAccessMessage = computed(() => importRefreshAvailability.value.disabledReason)
const importJobCancelAccessMessage = computed(() => importCancelAvailability.value.disabledReason)
const importJobReportsAccessMessage = computed(() => importReportsAvailability.value.disabledReason)
const importJobListAccessMessage = computed(() =>
  scopedAccessMessage(importListAvailability.value.disabledReason, t('corpus.manager.labelJobMonitor'))
    ?? t('corpus.manager.jobListNotEnabled')
)
const registerAccessMessage = computed(() =>
  scopedAccessMessage(registerCorpusAvailability.value.disabledReason, t('corpus.manager.labelIndexRegistration'))
)
const activateAccessMessage = computed(() => activateCorpusAvailability.value.disabledReason)
const corpusCapabilitiesAccessMessage = computed(() => corpusCapabilitiesAvailability.value.disabledReason)
const buildReportAccessMessage = computed(() => buildReportsAvailability.value.disabledReason)
const unregisterAccessMessage = computed(() => unregisterCorporaAvailability.value.disabledReason)
const resolvedTargetName = computed(() =>
  targetName.value.trim() || inferredTargetNameFromPath(inputPath.value)
)
const inspectOnlyImportMode = computed(() =>
  method.value === 'vrt' &&
    parsedOptions.value.ok &&
    parsedOptions.value.value.inspect === true
)

const currentImportInput = computed(() => ({
  method: method.value,
  inputPath: inputPath.value.trim(),
  targetName: resolvedTargetName.value,
  activateOnSuccess: activateOnSuccess.value,
  options: parsedOptions.value.ok ? parsedOptions.value.value : {},
}))
const currentPreflightKey = computed(() => importStore.payloadKey(currentImportInput.value))
const preflightResult = computed(() => importStore.preflightResult)
const hasFreshPreflight = computed(() =>
  Boolean(preflightResult.value) && importStore.preflightPayloadKey === currentPreflightKey.value
)
const freshPreflightBlocksImport = computed(() =>
  Boolean(preflightResult.value && hasFreshPreflight.value && preflightBlocksImport(preflightResult.value))
)
const preflightChecks = computed(() => preflightResult.value?.checks ?? [])
const preflightColumns = computed(() => preflightResult.value?.evidence?.columns ?? [])
const canRunPreflight = computed(() =>
  canRunImportPreflightRoute.value &&
  Boolean(selectedMethod.value) &&
  Boolean(inputPath.value.trim()) &&
  parsedOptions.value.ok &&
  !importStore.isPreflighting
)
const importIssues = computed(() => {
  const issues: string[] = []
  if (!canStartImportJob.value) {
    issues.push(importAccessMessage.value)
  }
  if (!canLoadImportMethods.value) {
    issues.push(importMethodsAccessMessage.value ?? t('corpus.imports.methodsNotEnabled'))
  }
  if (!canRunImportPreflightRoute.value) {
    issues.push(preflightAccessMessage.value ?? t('corpus.imports.preflightNotEnabled'))
  }
  if (importStore.isLoadingMethods) {
    issues.push(t('corpus.manager.methodsLoading'))
  }
  if (importStore.methodError) {
    issues.push(t('corpus.imports.methodsLoadFailed'))
  }
  if (!methodOptions.value.length && !importStore.isLoadingMethods) {
    issues.push(t('corpus.manager.noMethod'))
  }
  if (!method.value) {
    issues.push(t('corpus.manager.methodMissing'))
  } else if (!selectedMethod.value) {
    issues.push(t('corpus.manager.methodNotListed', { method: method.value }))
  } else if (!selectedMethodIsAvailable.value) {
    issues.push(selectedMethodAvailabilityText.value ?? t('corpus.manager.builderUnavailableForMethod'))
  } else if (!selectedMethodWorkflowOk.value) {
    const reason = selectedMethodWorkflowReason.value
    const message = t('corpus.imports.notFirstClass', {
      label: selectedMethod.value.label || selectedMethod.value.method,
      workflow: selectedMethodWorkflowLabel.value ?? t('corpus.manager.workflowExpert'),
    })
    issues.push(reason ? `${message} ${reason}` : message)
  }
  if (!inputPath.value.trim()) {
    issues.push(t('corpus.manager.fieldMissing', { field: inputPathFieldLabel.value }))
  }
  if (!resolvedTargetName.value) {
    issues.push(t('corpus.manager.targetMissing'))
  } else if (!isSafeTargetName(resolvedTargetName.value)) {
    issues.push(t('corpus.manager.targetUnsafe'))
  }
  if (inspectOnlyImportMode.value) {
    issues.push(t('corpus.manager.vrtInspectNoBuild'))
    if (activateOnSuccess.value) {
      issues.push(t('corpus.manager.vrtInspectNoActivate'))
    }
  }
  if (optionsJson.value.trim() && !parsedOptions.value.ok) {
    issues.push(parsedOptions.value.error)
  } else if (!parsedOptions.value.ok) {
    issues.push(parsedOptions.value.error)
  }
  if (parsedOptions.value.ok && selectedMethod.value && inputPath.value.trim()) {
    if (!preflightResult.value) {
      issues.push(t('corpus.manager.preflightMissing'))
    } else if (!hasFreshPreflight.value) {
      issues.push(t('corpus.manager.preflightStale'))
    } else if (preflightBlocksImport(preflightResult.value)) {
      issues.push(t('corpus.imports.preflightBlocks'))
    }
  }
  return issues
})
const canSubmit = computed(() => importIssues.value.length === 0 && !importStore.isStarting)
const canRegisterExisting = computed(() =>
  canRegisterCorpus.value && Boolean(registerPath.value.trim()) && !corpusStore.isRegisteringExisting
)

type WorkflowStepState = 'ready' | 'active' | 'blocked' | 'waiting'

interface WorkflowStep {
  key: string
  label: string
  state: WorkflowStepState
  note: string
}

function formatCount(value: number): string {
  return formatNumber(value)
}

function statusLabel(status?: string): string {
  if (!status || status === 'ready') return t('corpus.manager.statusReady')
  if (status === 'missing') return t('corpus.manager.statusMissing')
  if (status === 'incomplete') return t('corpus.manager.statusIncomplete')
  if (status === 'corrupt') return t('corpus.manager.statusCorrupt')
  return status
}

function preflightStatusLabel(status?: string): string {
  if (status === 'pass') return t('corpus.manager.preflightPassed')
  if (status === 'warning') return t('corpus.manager.preflightWarnings')
  if (status === 'error') return t('corpus.manager.preflightBlocked')
  return status || t('corpus.manager.preflightUnchecked')
}

function inputKindLabel(kind: string): string {
  if (kind === 'server_file') return t('corpus.manager.inputServerFile')
  if (kind === 'server_directory') return t('corpus.manager.inputServerDirectory')
  if (kind === 'server_path') return t('corpus.manager.inputServerPath')
  if (kind === 'hf_dataset') return t('corpus.manager.inputHfDataset')
  return kind.replace(/_/g, ' ')
}

function importMethodInputLabel(item: CorpusImportMethod): string {
  const input = item.input
  const parts = [inputKindLabel(input?.kind ?? 'server_file')]
  if (input?.accepts_directories) parts.push(t('corpus.manager.directoriesAllowed'))
  if (input?.extensions?.length) parts.push(input.extensions.join(', '))
  return parts.join(' · ')
}

function importMethodOutputLabel(item: CorpusImportMethod): string {
  const output = item.output
  const withKind = (label: string, kind?: string | null) => (kind ? `${label} · ${kind}` : label)
  if (output?.paired) return withKind(t('corpus.shared.paired'), output.pairing_kind)
  if (output?.paired_data_dependent) {
    return withKind(t('corpus.shared.dataDependentPairs'), output.pairing_kind)
  }
  return output?.pairing_kind && output.pairing_kind !== 'none'
    ? withKind(t('corpus.shared.unpaired'), output.pairing_kind)
    : t('corpus.shared.unpaired')
}

function importMethodIsAvailable(item: CorpusImportMethod): boolean {
  return !item.availability || String(item.availability.status ?? 'unknown').toLowerCase() === 'available'
}

function importMethodAvailabilityLabel(item: CorpusImportMethod): string {
  const availability = item.availability
  if (!availability) return t('corpus.manager.availabilityUnknown')
  if (importMethodIsAvailable(item)) {
    return availability.script
      ? t('corpus.manager.builderAvailableScript', { script: availability.script })
      : t('corpus.manager.builderAvailable')
  }
  return availability.reason
    ? t('corpus.manager.builderBlockedReason', { reason: availability.reason })
    : t('corpus.manager.builderUnavailable')
}

function importMethodWorkflowStatus(item: CorpusImportMethod): string {
  return String(item.ui_workflow?.status ?? 'first_class').toLowerCase()
}

function importMethodWorkflowIsFirstClass(item: CorpusImportMethod): boolean {
  return importMethodWorkflowStatus(item) === 'first_class'
}

function importMethodWorkflowLabel(item: CorpusImportMethod): string {
  const explicit = item.ui_workflow?.label?.trim()
  if (explicit) return explicit
  return importMethodWorkflowIsFirstClass(item) ? t('corpus.manager.workflowFirstClass') : t('corpus.manager.workflowExpert')
}

function importMethodWorkflowReason(item: CorpusImportMethod): string | null {
  return item.ui_workflow?.reason?.trim() || null
}

function selectImportMethod(methodId: string): void {
  method.value = methodId
}

function alignmentLabel(corpus: CorpusSummary): string | null {
  const alignment = corpus.features?.alignment
  const paired = alignment?.paired ?? corpus.paired
  if (!paired) return null
  const axes = alignment?.pair_axes ?? corpus.pair_axes
  const modes: string[] = []
  if (alignment?.parallel_groups === true) modes.push(t('corpus.manager.pairGroups'))
  if (alignment?.parallel_kwic === true) modes.push(t('corpus.manager.pairedKwic'))
  const axesText = axes.length ? axes.join(', ') : t('corpus.shared.yes')
  return modes.length
    ? t('corpus.manager.pairMetadataModes', { axes: axesText, modes: modes.join(' + ') })
    : t('corpus.manager.pairMetadata', { axes: axesText })
}

function annotationSourceLabel(value?: string): string | null {
  if (!value) return null
  if (value === 'spacy') return t('corpus.manager.annotationSpacy')
  if (value === 'native') return t('corpus.manager.annotationNative')
  if (value === 'unknown') return t('corpus.manager.annotationUnknown')
  return t('corpus.manager.annotationOther', { value })
}

function isImportJobTerminal(status?: string | null): boolean {
  return ['done', 'error', 'cancelled', 'failed', 'succeeded'].includes(String(status || '').toLowerCase())
}

function canCancelImportJob(job: CorpusImportJob): boolean {
  return canCancelImportJobs.value
    && job.cancellable !== false
    && !importStore.cancellingJobIds.includes(job.job_id)
}

function importJobCancelTitle(job: CorpusImportJob): string {
  if (!canCancelImportJobs.value) {
    return importJobCancelAccessMessage.value ?? t('corpus.manager.cancelNotEnabled')
  }
  if (job.cancellable === false) {
    return t('corpus.manager.cancelFinishing')
  }
  if (importStore.cancellingJobIds.includes(job.job_id)) {
    return t('corpus.manager.cancelling')
  }
  return t('corpus.manager.cancelJob')
}

function isSafeTargetName(value: string): boolean {
  const name = value.trim()
  return Boolean(name) && name !== '.' && name !== '..' && !name.includes('/') && !name.includes('\\')
}

function inferredTargetNameFromPath(value: string): string {
  const input = value.trim().replace(/[\\/]+$/g, '')
  const last = input.split(/[\\/]/).filter(Boolean).pop() ?? ''
  const dot = last.lastIndexOf('.')
  return dot > 0 ? last.slice(0, dot) : last
}

function currentTypedOptions(): CorpusImportParsedOptions {
  const typed = typedOptionsFromSpecs(selectedMethodOptionSpecs.value, optionValues.value)
  // With a language the pipeline field is sent even when it equals the
  // default, so that the server checks both against each other.
  const model = String(optionValues.value.spacy_model ?? '').trim()
  if (typed.ok && typed.value.language && model && !('spacy_model' in typed.value)) {
    return { ok: true, value: { ...typed.value, spacy_model: model } }
  }
  return typed
}

const parsedOptions = computed<CorpusImportParsedOptions>(() => {
  const typed = currentTypedOptions()
  if (!typed.ok) return typed
  const advanced = parseAdvancedImportOptions(optionsJson.value)
  if (!advanced.ok) return advanced
  return { ok: true, value: { ...typed.value, ...advanced.value } }
})

const typedParsedOptions = computed<CorpusImportParsedOptions>(() => currentTypedOptions())
const advancedParsedOptions = computed<CorpusImportParsedOptions>(() => parseAdvancedImportOptions(optionsJson.value))
const advancedOverrideWarnings = computed(() =>
  advancedImportWarnings(selectedMethodOptionSpecs.value, typedParsedOptions.value, advancedParsedOptions.value)
)
const finalImportPayloadPreview = computed(() => {
  if (!parsedOptions.value.ok) return ''
  return JSON.stringify({
    ...parsedOptions.value.value,
    method: method.value,
    input_path: inputPath.value.trim(),
    target_name: resolvedTargetName.value,
    activate_on_success: activateOnSuccess.value,
  }, null, 2)
})

function workflowStepIsFocused(stepKey: string): boolean {
  const slot = focusedSurfaceSlot.value
  if (!slot) return false
  if (stepKey === 'source') return slot === 'corpus.import.methods'
  if (stepKey === 'preflight') return slot === 'corpus.import.preflight'
  if (stepKey === 'start') return slot === 'corpus.import.start'
  if (stepKey === 'review') return slot === 'corpus.import.preflight' || slot === 'corpus.import.start'
  return false
}

const workflowSteps = computed<WorkflowStep[]>(() => [
  {
    key: 'source',
    label: t('corpus.manager.stepSource'),
    state: selectedMethod.value && inputPath.value.trim() ? 'ready' : 'active',
    note: selectedMethod.value
      ? t('corpus.manager.stepSourceNote', {
        method: selectedMethod.value.label || selectedMethod.value.method,
        path: inputPath.value.trim() || t('corpus.manager.fieldMissingShort', { field: inputPathFieldLabel.value }),
      })
      : t('corpus.manager.chooseMethod'),
  },
  {
    key: 'preflight',
    label: t('corpus.manager.stepPreflight'),
    state: freshPreflightBlocksImport.value ? 'blocked' : hasFreshPreflight.value ? 'ready' : 'waiting',
    note: hasFreshPreflight.value
      ? preflightResult.value?.summary || t('corpus.manager.preflightCurrent')
      : preflightResult.value
        ? t('corpus.manager.preflightOutdated')
        : t('corpus.manager.preflightBefore'),
  },
  {
    key: 'review',
    label: t('corpus.manager.stepReview'),
    state: hasFreshPreflight.value ? 'active' : 'waiting',
    note: preflightColumns.value.length
      ? t('corpus.manager.columnsDetected', { count: formatNumber(preflightColumns.value.length) }, preflightColumns.value.length)
      : t('corpus.manager.reviewReported'),
  },
  {
    key: 'start',
    label: inspectOnlyImportMode.value ? t('corpus.manager.stepNoStart') : t('corpus.manager.stepStart'),
    state: canSubmit.value ? 'ready' : importIssues.value.length ? 'blocked' : 'waiting',
    note: canSubmit.value
      ? t('corpus.manager.readyToStart')
      : importIssues.value[0] || t('corpus.manager.waitingForInput'),
  },
])

function seedOptionDefaults() {
  const next: Record<string, unknown> = {}
  for (const spec of selectedMethodOptionSpecs.value) {
    next[spec.key] = defaultUiValue(spec)
  }
  optionValues.value = next
}

watch(
  methodOptions,
  (items) => {
    if (items.length && !items.some((item) => item.method === method.value)) {
      method.value = items[0]!.method
    }
  },
  { immediate: true }
)

watch(
  () => `${selectedMethod.value?.method ?? ''}:${selectedMethodOptionSpecs.value.map((spec) => spec.key).join('|')}`,
  () => seedOptionDefaults(),
  { immediate: true }
)

// The corpus language suggests its standard pipeline: the spaCy model field
// is filled with it and stays editable.
const languageSpec = computed(() => selectedMethodOptionSpecs.value.find((spec) => spec.key === 'language'))
const languageSuggestion = computed(() =>
  suggestedPipeline(languageSpec.value?.choices ?? [], optionValues.value.language)
)
watch(
  () => optionValues.value.language,
  () => {
    const pipeline = languageSuggestion.value
    if (pipeline && selectedMethodOptionSpecs.value.some((spec) => spec.key === 'spacy_model')) {
      optionValues.value = { ...optionValues.value, spacy_model: pipeline }
    }
  }
)

function optionChoiceLabel(key: string, choice: CorpusImportOptionChoice): string {
  if (key !== 'language') return choiceLabel(choice)
  const code = String(choiceValue(choice) ?? '')
  return code ? corpusLanguageName(code) : t('corpus.language.notSet')
}

watch(
  [canListImportJobs, () => productCapabilities.status, () => sessionStore.status],
  ([allowed, productStatus, sessionStatus]) => {
    if (!allowed && productStatus === 'ready' && sessionStatus === 'ready') {
      importStore.clearVisibleJobState()
    }
  },
  { immediate: true }
)

async function refreshAll() {
  await Promise.all([productCapabilities.load(true), sessionStore.load(true)])
  const tasks: Promise<unknown>[] = []
  if (canUseCatalogue.value) {
    tasks.push(corpusStore.fetchCorpora())
  }
  if (canLoadImportMethods.value) {
    tasks.push(importStore.loadMethods())
  }
  if (canListImportJobs.value) {
    tasks.push(importStore.loadJobs())
  }
  await Promise.all(tasks)
}

async function initialiseCorpusManager() {
  await Promise.all([productCapabilities.load(), sessionStore.load()])
  const tasks: Promise<unknown>[] = []
  if (canUseCatalogue.value && !corpusStore.loaded) {
    tasks.push(corpusStore.fetchCorpora())
  }
  if (canLoadImportMethods.value) {
    tasks.push(importStore.loadMethods())
  }
  if (canListImportJobs.value) {
    tasks.push(importStore.loadJobs())
  }
  await Promise.all([
    ...tasks,
  ])
}

async function startImport() {
  if (!canSubmit.value) return
  try {
    await importStore.startImport(currentImportInput.value)
  } catch {
    // Fehler werden im Store gehalten und direkt unter dem Formular angezeigt.
  }
}

async function runImportPreflight() {
  if (!canRunPreflight.value) return
  try {
    await importStore.runPreflight(currentImportInput.value)
  } catch {
    // Fehler werden im Store gehalten und direkt unter dem Formular angezeigt.
  }
}

async function registerExistingCorpus() {
  if (!canRegisterExisting.value) return
  catalogueActionError.value = null
  const result = await corpusStore.registerExisting(registerPath.value, registerActivate.value)
  if (result) {
    registerPath.value = ''
    registerActivate.value = false
  }
}

function corpusByName(name: string): CorpusSummary | null {
  return corpusStore.corpora.find((corpus) => corpus.name === name) ?? null
}

function hasPartialImportAcknowledgement(corpus: CorpusSummary | null | undefined): boolean {
  if (!corpus) return false
  return !corpusRequiresPartialImportAcknowledgement(corpus) ||
    Boolean(partialImportAcknowledgements.value[corpus.name])
}

function canActivateCorpusItem(corpus: CorpusSummary | null | undefined): boolean {
  return canActivateCorpora.value && canActivateCorpusWithPartialImportAcknowledgement(
    corpus,
    hasPartialImportAcknowledgement(corpus),
  )
}

function activationBlockReasonForCorpus(corpus: CorpusSummary | null | undefined): string | null {
  if (!canActivateCorpora.value) {
    return activateAccessMessage.value ?? t('corpus.manager.activationNotEnabled')
  }
  if (canActivateCorpusItem(corpus)) return null
  return corpusActivationBlockReason(corpus)
}

function canUnregisterCorpusItem(corpus: CorpusSummary | null | undefined): boolean {
  return canUnregisterCorpora.value && canUnregisterCorpusSummary(corpus)
}

function unregisterBlockReasonForCorpus(corpus: CorpusSummary | null | undefined): string | null {
  return !canUnregisterCorpora.value
    ? unregisterAccessMessage.value ?? t('corpus.manager.unregisterUnavailable')
    : corpusUnregisterBlockReason(corpus)
}

async function activateCorpus(name: string) {
  if (!canActivateCorpora.value) {
    catalogueActionError.value = activateAccessMessage.value ?? t('corpus.manager.activationNotEnabledSession')
    return
  }
  const corpus = corpusByName(name)
  if (!canActivateCorpusItem(corpus)) {
    catalogueActionError.value = corpusActivationBlockReason(corpus)
    return
  }
  catalogueActionError.value = null
  try {
    await corpusStore.setActive(name, {
      acknowledgePartialInput: hasPartialImportAcknowledgement(corpus),
    })
  } catch (err) {
    catalogueActionError.value = err instanceof Error ? err.message : t('corpus.manager.activationFailed')
  }
}

async function refreshCorpusCapabilities(name: string) {
  if (!canRefreshCorpusCapabilities.value) {
    catalogueActionError.value = corpusCapabilitiesAccessMessage.value ?? t('corpus.manager.capabilitiesNotCheckable')
    return
  }
  catalogueActionError.value = null
  const summary = await corpusStore.fetchCapabilities(name)
  if (!summary && corpusStore.error) {
    catalogueActionError.value = corpusStore.error
  }
}

async function loadBuildReport(name: string) {
  if (!canLoadBuildReports.value) return
  catalogueActionError.value = null
  const report = await corpusStore.loadBuildReport(name)
  if (!report && corpusStore.buildReportError) {
    catalogueActionError.value = corpusStore.buildReportError
  }
}

async function unregisterCorpus(name: string) {
  if (!canUnregisterCorpora.value) return
  const corpus = corpusByName(name)
  if (!canUnregisterCorpusSummary(corpus)) {
    catalogueActionError.value = corpusUnregisterBlockReason(corpus)
    return
  }
  catalogueActionError.value = null
  try {
    await corpusStore.unregister(name)
  } catch (err) {
    catalogueActionError.value = err instanceof Error ? err.message : t('corpus.manager.unregisterFailed')
  }
}

onMounted(() => {
  void initialiseCorpusManager()
})

function reportEntries(jobId: string): ImportReportEntry[] {
  return importReportEntriesFromPayload(importStore.reportsByJobId[jobId])
}

function jobReportOutcome(job: CorpusImportJob): ImportReportOutcome {
  const snapshotReports = (job as { reports?: ImportReportPayload }).reports
  return importReportOutcomeFromPayload(
    importStore.reportsByJobId[job.job_id] ?? snapshotReports,
  )
}

function jobPartialInput(job: CorpusImportJob): boolean {
  return Boolean(
    job.partial_input ||
    job.readiness === 'partial_input' ||
    jobReportOutcome(job).partialInput,
  )
}

function jobWarnings(job: CorpusImportJob): string[] {
  // The server derives the warnings of a job from its reports
  // (import_warnings). Deriving them here as well repeated each fact in other
  // words. Only a snapshot without the field falls back to the reports.
  if (Array.isArray(job.import_warnings)) {
    return [...new Set(job.import_warnings.filter((item) => item.trim()))]
  }
  return jobReportOutcome(job).warnings
}

function corpusPartialImportWarnings(corpus: CorpusSummary | null | undefined): string[] {
  return Array.isArray(corpus?.import_warnings)
    ? corpus.import_warnings.filter((item) => item.trim())
    : []
}

function partialImportAcknowledgementLabel(corpus: CorpusSummary | null | undefined): string {
  const rejected = Number(corpus?.rejected_rows || 0)
  return rejected > 0
    ? t('corpus.manager.ackPartialRejected', { count: formatNumber(rejected) }, rejected)
    : t('corpus.manager.ackPartial')
}

function jobProgress(job: CorpusImportJob): number {
  const value = Number(job.progress ?? 0)
  return Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : 0
}

function jobProgressText(job: CorpusImportJob): string {
  const target = job.target_name || job.job_id
  const stage = String(job.stage || job.status || t('corpus.manager.stageWaiting')).replace(/_/g, ' ')
  const message = String(job.message || '').trim()
  const values = { target, progress: String(jobProgress(job)), stage, message }
  return message
    ? t('corpus.manager.progressTextMessage', values)
    : t('corpus.manager.progressText', values)
}

function jobReadinessLabel(job: CorpusImportJob): string {
  const readiness = String(job.readiness || '').toLowerCase()
  if (jobPartialInput(job) || readiness === 'partial_input') return t('corpus.manager.readinessPartial')
  if (readiness === 'complete') return t('corpus.manager.readinessComplete')
  if (readiness === 'failed') return t('corpus.manager.readinessFailed')
  if (readiness === 'cancelled') return t('corpus.manager.readinessCancelled')
  return t('corpus.manager.readinessOpen')
}

function buildReportEntries(corpusName: string): ImportReportEntry[] {
  return importReportEntriesFromPayload(corpusStore.buildReportsByCorpus[corpusName])
}

function normalizedImportJobStatus(status?: string | null): string {
  const value = String(status || '').toLowerCase()
  if (value === 'succeeded' || value === 'completed') return 'done'
  if (value === 'failed') return 'error'
  return value
}

function isImportJobDone(status?: string | null): boolean {
  return normalizedImportJobStatus(status) === 'done'
}

function jobTargetCorpusName(job: CorpusImportJob): string {
  return String(job.target_name || (job as { corpus?: unknown }).corpus || '').trim()
}

function jobTargetCorpus(job: CorpusImportJob): CorpusSummary | null {
  const target = jobTargetCorpusName(job)
  if (!target) return null
  return corpusStore.corpora.find((corpus) => corpus.name === target) ?? null
}

function hasPostImportHandoff(job: CorpusImportJob): boolean {
  return isImportJobDone(job.status) && Boolean(jobTargetCorpusName(job))
}

function jobBuildReportEntries(job: CorpusImportJob): ImportReportEntry[] {
  const target = jobTargetCorpusName(job)
  return target ? buildReportEntries(target) : []
}

function formatTimestamp(value: unknown): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  const millis = value > 10_000_000_000 ? value : value * 1000
  return formatDateTime(millis, {
    dateStyle: 'short',
    timeStyle: 'medium',
  })
}

function jobTraceEntries(job: CorpusImportJob): Array<{ key: string; label: string; value: string }> {
  const entries: Array<{ key: string; label: string; value: string }> = []
  const pid = job.pid ?? job.process_pid
  const pairs: Array<[string, string, unknown]> = [
    ['stage', t('corpus.manager.traceStage'), job.stage],
    ['pid', 'PID', pid],
    ['returncode', t('corpus.manager.traceReturncode'), job.returncode],
    ['started', t('corpus.manager.traceStarted'), formatTimestamp(job.started_at)],
    ['finished', t('corpus.manager.traceFinished'), formatTimestamp(job.finished_at)],
    ['updated', t('corpus.manager.traceUpdated'), formatTimestamp(job.updated_at)],
  ]
  for (const [key, label, value] of pairs) {
    if (value === undefined || value === null || value === '') continue
    entries.push({ key, label, value: String(value) })
  }
  return entries
}

function boolLabel(value: unknown): string | null {
  if (typeof value !== 'boolean') return null
  return value ? t('corpus.shared.yes') : t('corpus.shared.no')
}

function jobProvenanceEntries(job: CorpusImportJob): Array<{ key: string; label: string; value: string }> {
  const pairs: Array<[string, string, unknown]> = [
    ['input_path', t('corpus.manager.provSource'), job.input_path],
    ['target_name', t('corpus.manager.provTargetCorpus'), job.target_name],
    ['target_path', t('corpus.manager.provTargetPath'), job.target_path],
    ['staging_path', t('corpus.manager.provStagingPath'), job.staging_path],
    ['activate_on_success', t('corpus.manager.provActivateOnSuccess'), boolLabel(job.activate_on_success)],
    ['readiness', t('corpus.manager.provOutcome'), jobReadinessLabel(job)],
    ['rejected_rows', t('corpus.manager.provRejectedRows'), job.rejected_rows],
    ['warning_count', t('corpus.manager.provWarnings'), job.warning_count],
    ['activation_skipped_reason', t('corpus.manager.provActivationSkipped'), job.activation_skipped_reason],
    ['created_at', t('corpus.manager.provCreated'), formatTimestamp(job.created_at)],
  ]
  return pairs.flatMap(([key, label, value]) => {
    if (value === undefined || value === null || value === '') return []
    return [{ key, label, value: String(value) }]
  })
}

function hasJobProvenance(job: CorpusImportJob): boolean {
  return jobProvenanceEntries(job).length > 0
}

function hasJobTrace(job: CorpusImportJob): boolean {
  return Boolean(
    jobTraceEntries(job).length ||
    job.stdout_tail ||
    job.stderr_tail
  )
}
</script>

<template>
  <div class="corpus-manager-content" data-testid="corpus-manager">
    <section class="manager-hero">
      <div class="hero-icon">
        <Database class="w-5 h-5" />
      </div>
      <div>
        <h3 class="section-title">{{ t('corpus.manager.title') }}</h3>
        <p class="section-description">
          {{ t('corpus.manager.description') }}
        </p>
      </div>
      <button type="button" class="btn-secondary" :disabled="corpusStore.isLoading" @click="refreshAll">
        <RefreshCw class="w-4 h-4" />
        {{ t('corpus.manager.refresh') }}
      </button>
    </section>

    <section
      class="workflow-card"
      :class="{ 'surface-focus': isImportWorkflowFocused }"
      :aria-label="t('corpus.manager.workflowTitle')"
    >
      <div class="card-heading">
        <UploadCloud class="w-4 h-4" />
        <h4>{{ t('corpus.manager.workflowTitle') }}</h4>
        <span class="scope-badge">{{ t('corpus.manager.workflowBadge') }}</span>
      </div>
      <p class="card-note">
        {{ t('corpus.manager.workflowNote') }}
      </p>
      <div class="workflow-steps">
        <article
          v-for="step in workflowSteps"
          :key="step.key"
          class="workflow-step"
          :class="[`workflow-step--${step.state}`, { 'workflow-step--focused': workflowStepIsFocused(step.key) }]"
        >
          <strong>{{ step.label }}</strong>
          <span>{{ step.note }}</span>
        </article>
      </div>
    </section>

    <section class="import-card" data-testid="corpus-import-card" :class="{ 'surface-focus': isImportFormFocused }">
      <div class="card-heading">
        <UploadCloud class="w-4 h-4" />
        <h4>{{ t('corpus.manager.importTitle') }}</h4>
        <span class="scope-badge">{{ importCapability?.maturity ?? t('corpus.manager.maturityFallback') }}</span>
      </div>
      <p class="card-note">
        {{ t('corpus.manager.importNote') }}
      </p>
      <p class="limitation-note">
        {{ t('corpus.manager.importLimitation') }}
      </p>
      <p v-if="!canUseImport" class="error-text">
        {{ importAccessMessage }}
      </p>
      <ul v-if="importCapability?.preconditions?.length || importCapability?.limits?.length" class="validation-list">
        <li v-for="note in importCapability.preconditions" :key="`import-pre-${note}`">{{ t('corpus.manager.precondition', { note }) }}</li>
        <li v-for="note in importCapability.limits" :key="`import-limit-${note}`">{{ t('corpus.manager.limit', { note }) }}</li>
      </ul>

      <div v-if="canUseImport" class="form-grid">
        <label class="field">
          <span>{{ t('corpus.manager.format') }}</span>
          <select v-model="method" data-testid="corpus-import-method" :disabled="importStore.isLoadingMethods">
            <option v-for="item in methodOptions" :key="item.method" :value="item.method">
              {{ item.label || item.method }}
            </option>
          </select>
          <small v-if="selectedMethod?.description" class="field-note">{{ selectedMethod.description }}</small>
          <small v-if="importStore.methodError" class="warning-text">{{ importStore.methodError }}</small>
        </label>
        <details v-if="importMethodCatalogueRows.length" class="method-catalogue field-wide" open>
          <summary>
            {{ t('corpus.manager.methodsTitle') }}
            <span>{{ t('corpus.manager.methodCount', { count: importMethodCatalogueRows.length }, importMethodCatalogueRows.length) }}</span>
          </summary>
          <p class="field-note">
            {{ t('corpus.manager.methodsNote') }}
          </p>
          <div class="method-catalogue-grid">
            <button
              v-for="item in importMethodCatalogueRows"
              :key="item.method"
              type="button"
              class="method-catalogue-card"
              :class="{
                'method-catalogue-card--selected': item.selected,
                'method-catalogue-card--blocked': !item.availabilityOk,
              }"
              @click="selectImportMethod(item.method)"
            >
              <span class="workflow-phase">{{ item.method }}</span>
              <strong>{{ item.label }}</strong>
              <small v-if="item.description">{{ item.description }}</small>
              <span>{{ item.inputLabel }}</span>
              <span>{{ item.outputLabel }}</span>
              <em :class="item.workflowOk ? 'route-flag route-flag--ok' : 'route-flag route-flag--mutates'">
                {{ item.workflowLabel }}
              </em>
              <span>{{ t('corpus.manager.cardOptions', { count: item.optionCount }, item.optionCount) }} · {{ t('corpus.manager.cardFields', { count: item.expectedColumnCount }, item.expectedColumnCount) }} · {{ t('corpus.manager.cardReports', { count: item.reportCount }, item.reportCount) }}</span>
              <span v-if="item.emittedFeatures.length">{{ t('corpus.manager.features', { list: item.emittedFeatures.join(', ') }) }}</span>
              <em :class="item.availabilityOk ? 'route-flag route-flag--ok' : 'route-flag route-flag--mutates'">
                {{ item.availabilityLabel }}
              </em>
            </button>
          </div>
        </details>
        <div v-if="selectedMethod" class="method-contract field-wide">
          <div class="contract-grid">
            <span v-if="selectedMethodAvailabilityText" :class="selectedMethodIsAvailable ? 'route-flag route-flag--ok' : 'route-flag route-flag--mutates'">
              {{ selectedMethodAvailabilityText }}
            </span>
            <span v-if="selectedMethodWorkflowLabel" :class="selectedMethodWorkflowOk ? 'route-flag route-flag--ok' : 'route-flag route-flag--mutates'">
              {{ t('corpus.manager.workflowRoute', { label: selectedMethodWorkflowLabel }) }}
            </span>
            <span>{{ t('corpus.manager.input', { label: selectedInputContractLabel }) }}</span>
            <span>{{ selectedAcceptsDirectories || selectedInputKind === 'server_directory' ? t('corpus.manager.directoriesAccepted') : t('corpus.manager.directoriesNotAccepted') }}</span>
            <span v-if="selectedMethodInput?.extensions?.length">{{ t('corpus.manager.extensions', { list: selectedMethodInput.extensions.join(', ') }) }}</span>
            <span v-if="selectedOutput">{{ selectedOutput.paired ? t('corpus.manager.outputPaired') : selectedOutput.paired_data_dependent ? t('corpus.manager.outputDataDependent') : t('corpus.manager.outputUnpaired') }}</span>
          </div>
          <p v-if="selectedMethodAvailabilityText && !selectedMethodIsAvailable" class="error-text">
            {{ t('corpus.manager.methodNotStartable') }}
          </p>
          <p v-if="selectedMethodWorkflowReason" class="field-note">{{ selectedMethodWorkflowReason }}</p>
          <p v-if="selectedMethodInput?.description" class="field-note">{{ selectedMethodInput.description }}</p>
          <div v-if="selectedExpectedColumns.length" class="contract-section">
            <strong>{{ t('corpus.manager.expectedColumns') }}</strong>
            <ul class="contract-list">
              <li v-for="column in selectedExpectedColumns" :key="`col-${method}-${column.key}`">
                <code>{{ column.key }}</code>
                <span v-if="column.required" class="route-flag route-flag--mutates">{{ t('corpus.shared.required') }}</span>
                <span v-if="column.configured_by">{{ t('corpus.manager.configuredBy', { field: column.configured_by }) }}</span>
                <span v-if="column.description">{{ column.description }}</span>
              </li>
            </ul>
          </div>
          <div v-if="selectedEmittedFeatures.length || selectedOutput?.guarantees?.length || selectedOutput?.limitations?.length" class="contract-section">
            <strong>{{ t('corpus.manager.plannedArtifacts') }}</strong>
            <p v-if="selectedEmittedFeatures.length" class="field-note">
              {{ t('corpus.manager.plannedArtifactsNote') }}
            </p>
            <ul class="contract-list">
              <li v-for="feature in selectedEmittedFeatures" :key="`feat-${method}-${feature}`">{{ feature }}</li>
              <li v-for="guarantee in selectedOutput?.guarantees ?? []" :key="`guarantee-${method}-${guarantee}`" class="method-guarantee">{{ guarantee }}</li>
              <li v-for="limit in selectedOutput?.limitations ?? []" :key="`limit-${method}-${limit}`" class="method-limit">{{ limit }}</li>
            </ul>
          </div>
          <div v-if="selectedReports.length" class="contract-section">
            <strong>{{ t('corpus.shared.expectedReports') }}</strong>
            <ul class="contract-list">
              <li v-for="report in selectedReports" :key="`report-${method}-${report.key}`">
                <code>{{ report.key }}</code>
                <span>{{ report.label || report.key }}</span>
                <span v-if="report.description">{{ report.description }}</span>
              </li>
            </ul>
          </div>
        </div>
        <label class="field">
          <span>{{ t('corpus.manager.targetName') }}</span>
          <input v-model="targetName" data-testid="corpus-import-target-name" type="text" :placeholder="t('corpus.manager.targetPlaceholder')" />
          <small class="field-note">
            {{ t('corpus.manager.targetNote') }}
            <template v-if="!targetName.trim() && resolvedTargetName">
              {{ t('corpus.manager.targetDerived', { name: resolvedTargetName }) }}
            </template>
          </small>
        </label>
        <label class="field field-wide">
          <span>{{ inputPathFieldLabel }}</span>
          <input v-model="inputPath" data-testid="corpus-import-input-path" type="text" :placeholder="inputPathPlaceholder" />
          <small class="field-note">{{ inputPathHelp }}</small>
        </label>
        <label class="checkbox-field field-wide">
          <input v-model="activateOnSuccess" type="checkbox" />
          <span>{{ t('corpus.manager.activateAfterImport') }}</span>
        </label>
        <p v-if="inspectOnlyImportMode" class="limitation-note field-wide">
          {{ t('corpus.manager.vrtInspectActive') }}
        </p>
        <div v-if="hasTypedOptionSpecs" class="option-spec-panel field-wide">
          <div class="option-spec-heading">
            <strong>{{ t('corpus.manager.importOptions') }}</strong>
            <span>{{ t('corpus.manager.importOptionsSource') }}</span>
          </div>
          <div class="option-spec-grid">
            <label v-for="spec in selectedMethodOptionSpecs" :key="`option-${method}-${spec.key}`" class="field option-field">
              <span>
                {{ optionLabel(spec) }}
                <em v-if="spec.required" class="option-required">{{ t('corpus.shared.required') }}</em>
                <em class="option-type">{{ optionTypeLabel(spec) }}</em>
              </span>
              <template v-if="spec.type === 'choice'">
                <select v-model="optionValues[spec.key]">
                  <option v-for="choice in spec.choices" :key="`${spec.key}-${choiceKey(choice)}`" :value="choiceValue(choice)">
                    {{ optionChoiceLabel(spec.key, choice) }}
                  </option>
                </select>
                <small v-if="spec.key === 'language' && languageSuggestion" class="field-note" data-testid="language-pipeline-suggestion">
                  {{ t('corpus.language.suggestedPipeline', { pipeline: languageSuggestion }) }}
                </small>
                <div
                  v-if="spec.choices.some((choice) => choiceDescription(choice))"
                  class="choice-description-list"
                >
                  <small
                    v-for="choice in spec.choices"
                    :key="`${spec.key}-desc-${choiceKey(choice)}`"
                  >
                    <template v-if="choiceDescription(choice)">
                      <strong>{{ choiceLabel(choice) }}:</strong> {{ choiceDescription(choice) }}
                    </template>
                  </small>
                </div>
              </template>
              <div v-else-if="spec.type === 'boolean'" class="checkbox-field option-checkbox">
                <input v-model="optionValues[spec.key]" type="checkbox" />
                <span>{{ optionValues[spec.key] ? t('corpus.manager.switchOn') : t('corpus.manager.switchOff') }}</span>
              </div>
              <input
                v-else-if="spec.type === 'integer' || spec.type === 'number'"
                v-model="optionValues[spec.key]"
                type="number"
                :step="spec.type === 'integer' ? 1 : 'any'"
                :placeholder="spec.placeholder || optionDefaultLabel(spec) || ''"
              />
              <input
                v-else
                v-model="optionValues[spec.key]"
                type="text"
                :placeholder="spec.placeholder || optionDefaultLabel(spec) || ''"
              />
              <small class="field-note">
                <span v-if="spec.description">{{ spec.description }}</span>
                <span v-if="optionDefaultLabel(spec)"> · {{ t('corpus.manager.optionDefault', { value: optionDefaultLabel(spec) ?? '' }) }}</span>
                <span v-if="spec.aliases.length"> · {{ t('corpus.manager.optionAliases', { list: spec.aliases.join(', ') }) }}</span>
              </small>
            </label>
          </div>
        </div>
        <label class="field field-wide">
          <span>{{ t('corpus.manager.advancedJson') }}</span>
          <textarea v-model="optionsJson" rows="4" placeholder='{"reject_policy":"fail_fast"}' />
          <small v-if="selectedMethodOptionKeys.length" class="field-note">
            {{ t('corpus.manager.allowedOptions', { method: selectedMethod?.label || method, options: selectedMethodOptionKeys.join(', ') }) }}
          </small>
          <small v-else class="field-note">
            {{ t('corpus.manager.advancedJsonNote') }}
          </small>
        </label>
        <div v-if="advancedOverrideWarnings.length || finalImportPayloadPreview" class="payload-review field-wide">
          <div class="option-spec-heading">
            <strong>{{ t('corpus.manager.plannedRequest') }}</strong>
            <span>{{ t('corpus.manager.checkBeforeStart') }}</span>
          </div>
          <ul v-if="advancedOverrideWarnings.length" class="preflight-issues">
            <li v-for="warning in advancedOverrideWarnings" :key="warning" class="warning-text">{{ warning }}</li>
          </ul>
          <pre v-if="finalImportPayloadPreview">{{ finalImportPayloadPreview }}</pre>
        </div>
        <div v-if="preflightResult || importStore.preflightError" class="preflight-card field-wide" :class="`preflight-${preflightResult?.status ?? 'error'}`">
          <div class="preflight-heading">
            <strong>{{ t('corpus.manager.preflightHeading', { status: preflightStatusLabel(preflightResult?.status) }) }}</strong>
            <span v-if="hasFreshPreflight">{{ t('corpus.manager.current') }}</span>
            <span v-else-if="preflightResult">{{ t('corpus.manager.outdated') }}</span>
          </div>
          <p v-if="preflightResult?.summary" class="field-note">{{ preflightResult.summary }}</p>
          <p v-if="importStore.preflightError" class="error-text">{{ importStore.preflightError }}</p>
          <ul v-if="preflightResult?.errors.length || preflightResult?.warnings.length" class="preflight-issues">
            <li v-for="error in preflightResult.errors" :key="`preflight-error-${error}`" class="error-text">{{ error }}</li>
            <li v-for="warning in preflightResult.warnings" :key="`preflight-warning-${warning}`" class="warning-text">{{ warning }}</li>
          </ul>
          <CorpusImportPreflightEvidence v-if="preflightResult" :result="preflightResult" />
          <ul v-if="preflightChecks.length" class="preflight-checks" :aria-label="t('corpus.manager.preflightChecks')">
            <li v-for="check in preflightChecks" :key="`preflight-check-${check.key}`" :class="`check-${check.status}`">
              <strong>{{ check.label || check.key }}</strong>
              <span>{{ check.message }}</span>
            </li>
          </ul>
        </div>
      </div>

      <ul v-if="canUseImport && importIssues.length" class="validation-list">
        <li v-for="issue in importIssues" :key="issue">{{ issue }}</li>
      </ul>
      <div v-if="canUseImport" class="form-actions">
        <button type="button" class="btn-secondary" data-testid="corpus-import-preflight-button" :disabled="!canRunPreflight" @click="runImportPreflight">
          {{ importStore.isPreflighting ? t('corpus.manager.preflightRunning') : t('corpus.manager.runPreflight') }}
        </button>
        <button type="button" class="btn-primary" data-testid="corpus-import-start-button" :disabled="!canSubmit" @click="startImport">
          {{ inspectOnlyImportMode ? t('corpus.manager.diagnosticNoStart') : t('corpus.manager.startImport') }}
        </button>
        <p v-if="importStore.error" class="error-text">{{ importStore.error }}</p>
      </div>
    </section>

    <section class="register-card" :class="{ 'surface-focus': isRegisterFocused }">
      <div class="card-heading">
        <FolderPlus class="w-4 h-4" />
        <h4>{{ t('corpus.manager.registerTitle') }}</h4>
        <span class="scope-badge">{{ t('corpus.manager.registerBadge') }}</span>
      </div>
      <p class="card-note">
        {{ t('corpus.manager.registerNote') }}
      </p>
      <p v-if="!canUseCatalogue" class="error-text">
        {{ catalogueListAvailability.disabledReason ?? t('corpus.manager.catalogueNotEnabled') }}
      </p>
      <p v-else-if="registerAccessMessage" class="warning-text">
        {{ registerAccessMessage }}
      </p>
      <div v-if="canUseCatalogue" class="form-grid">
        <label class="field field-wide">
          <span>{{ t('corpus.manager.registerPath') }}</span>
          <input v-model="registerPath" type="text" :placeholder="t('corpus.manager.registerPlaceholder')" :disabled="!canRegisterCorpus" />
        </label>
        <label class="checkbox-field field-wide">
          <input v-model="registerActivate" type="checkbox" :disabled="!canRegisterCorpus" />
          <span>{{ t('corpus.manager.activateAfterRegister') }}</span>
        </label>
      </div>
      <div v-if="canUseCatalogue" class="form-actions">
        <button type="button" class="btn-secondary" :disabled="!canRegisterExisting" @click="registerExistingCorpus">
          {{ t('corpus.manager.register') }}
        </button>
        <p v-if="corpusStore.registerError" class="error-text">{{ corpusStore.registerError }}</p>
      </div>
    </section>

    <section
      v-if="isImportFirstClass"
      class="job-list"
      :class="{ 'surface-focus surface-focus--soft': isImportJobsFocused }"
    >
      <div class="job-list-heading">
        <h4 class="group-title">{{ t('corpus.manager.jobsTitle') }}</h4>
        <span v-if="importStore.isPolling" class="route-flag route-flag--ok">{{ t('corpus.manager.autoRefresh') }}</span>
      </div>
      <div v-if="!canListImportJobs" class="empty-state" role="status">
        {{ importJobListAccessMessage }}
      </div>
      <div v-else-if="importStore.isLoadingJobs && !importStore.recentJobs.length" class="empty-state">
        {{ t('corpus.manager.jobsLoading') }}
      </div>
      <div v-else-if="!importStore.recentJobs.length" class="empty-state" role="status">
        {{ t('corpus.manager.jobsEmpty') }}
        {{ importJobRetentionNote }}
      </div>
      <template v-else>
        <article
          v-for="job in importStore.recentJobs"
          :key="job.job_id"
          class="job-card"
          data-testid="corpus-import-job-card"
          :data-job-id="job.job_id"
        >
          <div class="job-main">
            <strong>{{ job.target_name || job.job_id }}</strong>
            <span>{{ job.method }} · {{ job.status }} · {{ jobReadinessLabel(job) }}</span>
            <span
              v-if="jobPartialInput(job)"
              class="route-flag route-flag--mutates"
            >
              {{ t('corpus.manager.partialImport') }}
            </span>
          </div>
          <div
            class="progress-track"
            role="progressbar"
            :aria-label="t('corpus.manager.progressAria', { name: job.target_name || job.job_id })"
            aria-valuemin="0"
            aria-valuemax="100"
            :aria-valuenow="jobProgress(job)"
            :aria-valuetext="jobProgressText(job)"
          >
            <span aria-hidden="true" :style="{ width: `${jobProgress(job)}%` }" />
          </div>
          <p class="sr-only" aria-live="polite">{{ jobProgressText(job) }}</p>
          <p v-if="job.message" class="job-message">{{ job.message }}</p>
          <p v-if="job.error" class="error-text">{{ job.error }}</p>
          <ul v-if="jobWarnings(job).length" class="job-warning-list" :aria-label="t('corpus.manager.warningsAria')">
            <li v-for="warning in jobWarnings(job)" :key="`${job.job_id}-${warning}`">
              {{ warning }}
            </li>
          </ul>
          <details v-if="hasJobProvenance(job)" class="job-provenance" open>
          <summary>{{ t('corpus.manager.jobProvenance') }}</summary>
          <div class="trace-grid">
            <span v-for="entry in jobProvenanceEntries(job)" :key="`${job.job_id}-provenance-${entry.key}`">
              <strong>{{ entry.label }}</strong>
              {{ entry.value }}
            </span>
          </div>
          <p class="job-retention-note">{{ importJobRetentionNote }}</p>
        </details>
        <details v-if="hasJobTrace(job)" class="job-trace">
          <summary>{{ t('corpus.manager.runLog') }}</summary>
          <div v-if="jobTraceEntries(job).length" class="trace-grid">
            <span v-for="entry in jobTraceEntries(job)" :key="`${job.job_id}-${entry.key}`">
              <strong>{{ entry.label }}</strong>
              {{ entry.value }}
            </span>
          </div>
          <div v-if="job.stdout_tail || job.stderr_tail" class="trace-output">
            <div v-if="job.stdout_tail">
              <strong>{{ job.stdout_truncated ? t('corpus.manager.stdoutTruncated') : 'stdout' }}</strong>
              <pre>{{ job.stdout_tail }}</pre>
            </div>
            <div v-if="job.stderr_tail">
              <strong>{{ job.stderr_truncated ? t('corpus.manager.stderrTruncated') : 'stderr' }}</strong>
              <pre>{{ job.stderr_tail }}</pre>
            </div>
          </div>
        </details>
        <p v-if="importStore.reportLoadingJobIds.includes(job.job_id)" class="field-note">
          {{ t('corpus.manager.reportsLoading') }}
        </p>
        <p v-if="importStore.reportErrorByJobId[job.job_id]" class="warning-text">
          {{ importStore.reportErrorByJobId[job.job_id] }}
        </p>
        <CorpusReportList
          :title="t('corpus.manager.loadedReports')"
          :ariaLabel="t('corpus.manager.importReportsAria')"
          :entries="reportEntries(job.job_id)"
        />
        <div
          v-if="hasPostImportHandoff(job)"
          class="post-import-handoff"
          data-testid="post-import-handoff"
          :aria-label="t('corpus.manager.handoffAria')"
        >
          <div class="handoff-heading">
            <strong>{{ t('corpus.manager.handoffTitle') }}</strong>
            <span
              class="route-flag"
              :class="jobPartialInput(job) ? 'route-flag--mutates' : 'route-flag--ok'"
            >
              {{ jobPartialInput(job) ? t('corpus.manager.importWithWarnings') : t('corpus.manager.importComplete') }}
            </span>
          </div>
          <p v-if="jobPartialInput(job)" class="warning-text">
            {{ t('corpus.manager.partialJobNote') }}
          </p>
          <div class="handoff-status">
            <span>{{ t('corpus.manager.targetCorpusLabel') }} <code>{{ jobTargetCorpusName(job) }}</code></span>
            <span v-if="jobTargetCorpus(job)" class="route-flag route-flag--ok">{{ t('corpus.manager.inCatalogue') }}</span>
            <span v-else class="route-flag route-flag--mutates">{{ t('corpus.manager.notInCatalogue') }}</span>
            <span v-if="jobTargetCorpus(job)?.active" class="route-flag route-flag--ok">{{ t('corpus.shared.active') }}</span>
          </div>
          <div
            v-if="jobPartialInput(job) && jobTargetCorpus(job) && !jobTargetCorpus(job)?.active"
            class="partial-activation-review"
            role="group"
            :aria-label="t('corpus.manager.partialActivationAria', { name: jobTargetCorpusName(job) })"
          >
            <strong>{{ t('corpus.manager.deliberateActivation') }}</strong>
            <p>
              {{ t('corpus.manager.deliberateActivationNote') }}
            </p>
            <ul v-if="corpusPartialImportWarnings(jobTargetCorpus(job)).length" class="partial-warning-list">
              <li v-for="warning in corpusPartialImportWarnings(jobTargetCorpus(job))" :key="`${job.job_id}-${warning}`">
                {{ warning }}
              </li>
            </ul>
            <label class="checkbox-field">
              <input
                v-model="partialImportAcknowledgements[jobTargetCorpusName(job)]"
                :data-testid="`partial-import-ack-${jobTargetCorpusName(job)}`"
                type="checkbox"
              />
              <span>{{ partialImportAcknowledgementLabel(jobTargetCorpus(job)) }}</span>
            </label>
          </div>
          <div class="handoff-actions">
            <button
              type="button"
              class="btn-secondary"
              :disabled="!canLoadBuildReports || corpusStore.loadingBuildReportFor === jobTargetCorpusName(job)"
              :title="!canLoadBuildReports ? buildReportAccessMessage ?? t('corpus.manager.buildReportUnavailable') : t('corpus.manager.loadTargetBuildReport')"
              @click="loadBuildReport(jobTargetCorpusName(job))"
            >
              <FileSearch class="w-4 h-4" />
              {{ t('corpus.manager.reviewBuildReport') }}
            </button>
            <button
              type="button"
              class="btn-secondary"
              :disabled="!canRefreshCorpusCapabilities"
              :title="!canRefreshCorpusCapabilities ? corpusCapabilitiesAccessMessage ?? t('corpus.manager.capabilitiesNotEnabled') : t('corpus.manager.checkTargetCapabilitiesTitle')"
              @click="refreshCorpusCapabilities(jobTargetCorpusName(job))"
            >
              <RefreshCw class="w-4 h-4" />
              {{ t('corpus.manager.checkTargetCapabilities') }}
            </button>
            <button
              v-if="!jobTargetCorpus(job)?.active"
              type="button"
              class="btn-secondary"
              :disabled="!canActivateCorpusItem(jobTargetCorpus(job)) || corpusStore.isActivating"
              :title="activationBlockReasonForCorpus(jobTargetCorpus(job)) ?? t('corpus.manager.activateTarget')"
              @click="activateCorpus(jobTargetCorpusName(job))"
            >
              <CheckCircle2 class="w-4 h-4" />
              {{ t('corpus.manager.activateTarget') }}
            </button>
          </div>
          <CorpusReportList
            :title="t('corpus.manager.targetBuildReport')"
            :ariaLabel="t('corpus.manager.handoffBuildReportAria')"
            :entries="jobBuildReportEntries(job)"
          />
        </div>
        <div class="job-actions">
          <button
            v-if="!isImportJobTerminal(job.status)"
            type="button"
            class="btn-secondary"
            :disabled="!canCancelImportJob(job)"
            :title="importJobCancelTitle(job)"
            @click="importStore.cancelJob(job.job_id)"
          >
            {{ t('corpus.manager.cancel') }}
          </button>
          <button
            type="button"
            class="btn-secondary"
            :disabled="!canRefreshImportJobs"
            :title="!canRefreshImportJobs ? importJobRefreshAccessMessage ?? t('corpus.manager.jobStatusNotEnabled') : t('corpus.manager.checkStatus')"
            @click="importStore.refreshJob(job.job_id)"
          >
            {{ t('corpus.manager.checkStatus') }}
          </button>
          <button
            type="button"
            class="btn-secondary"
            :disabled="!canLoadImportJobReports || importStore.reportLoadingJobIds.includes(job.job_id)"
            :title="!canLoadImportJobReports ? importJobReportsAccessMessage ?? t('corpus.manager.jobReportsNotEnabled') : t('corpus.manager.loadReports')"
            @click="importStore.loadReports(job.job_id, true)"
          >
            {{ importStore.reportLoadingJobIds.includes(job.job_id) ? t('corpus.manager.loadReportsRunning') : t('corpus.manager.loadReports') }}
          </button>
        </div>
        </article>
      </template>
    </section>

    <section class="catalogue" :class="{ 'surface-focus surface-focus--soft': isCatalogueFocused }">
      <h4 class="group-title">{{ t('corpus.manager.catalogueTitle') }}</h4>
      <div v-if="!canUseCatalogue" class="empty-state">
        {{ catalogueListAvailability.disabledReason ?? t('corpus.manager.catalogueNotSurface') }}
      </div>
      <p v-if="catalogueActionError || corpusStore.activationError || corpusStore.buildReportError" class="error-text">
        {{ catalogueActionError || corpusStore.activationError || corpusStore.buildReportError }}
      </p>
      <div v-if="canUseCatalogue && corpusStore.isLoading && !corpusStore.corpora.length" class="empty-state">{{ t('corpus.manager.corporaLoading') }}</div>
      <div v-else-if="canUseCatalogue && !corpusStore.corpora.length" class="empty-state">{{ t('corpus.manager.noCorpora') }}</div>
      <article v-for="corpus in canUseCatalogue ? corpusStore.corpora : []" :key="`${corpus.name}-${corpus.path}`" class="corpus-card">
        <div class="corpus-info">
          <div class="corpus-name">
            <FileText class="w-4 h-4" />
            <strong :title="corpus.display_name && corpus.display_name !== corpus.name ? corpus.name : undefined">{{ corpusDisplayName(corpus) }}</strong>
            <span v-if="corpus.active" class="active-badge">{{ t('corpus.shared.active') }}</span>
          </div>
          <div class="corpus-meta">
            <span>{{ statusLabel(corpus.status) }}</span>
            <span>{{ t('corpus.manager.tokens', { count: formatCount(corpus.token_count) }, corpus.token_count) }}</span>
            <span>{{ t('corpus.manager.documents', { count: formatCount(corpus.doc_count) }, corpus.doc_count) }}</span>
            <span v-if="corpus.import_mode">{{ corpus.import_mode }}</span>
            <span v-if="annotationSourceLabel(corpus.annotation_source)">{{ annotationSourceLabel(corpus.annotation_source) }}</span>
            <span v-if="corpus.status === 'ready' || corpus.language" data-testid="corpus-language">{{ corpusLanguageLabel(corpus) }}</span>
            <span v-if="corpus.annotation_pipeline">{{ t('corpus.language.pipeline', { pipeline: corpus.annotation_pipeline }) }}</span>
            <span v-if="alignmentLabel(corpus)">{{ alignmentLabel(corpus) }}</span>
          </div>
          <p v-if="corpus.status_reason" class="warning-text">{{ corpus.status_reason }}</p>
          <div
            v-if="corpusRequiresPartialImportAcknowledgement(corpus) && !corpus.active"
            class="partial-activation-review"
            role="group"
            :aria-label="t('corpus.manager.partialActivationAria', { name: corpus.name })"
          >
            <strong>{{ t('corpus.manager.partialReviewTitle') }}</strong>
            <p>
              {{ t('corpus.manager.partialReviewNote') }}
            </p>
            <ul v-if="corpusPartialImportWarnings(corpus).length" class="partial-warning-list">
              <li v-for="warning in corpusPartialImportWarnings(corpus)" :key="`${corpus.name}-${warning}`">
                {{ warning }}
              </li>
            </ul>
            <label class="checkbox-field">
              <input
                v-model="partialImportAcknowledgements[corpus.name]"
                :data-testid="`partial-import-ack-${corpus.name}`"
                type="checkbox"
              />
              <span>{{ partialImportAcknowledgementLabel(corpus) }}</span>
            </label>
          </div>
          <CorpusFeatureEvidence :summary="corpus" />
        </div>
        <div class="corpus-actions">
          <button
            v-if="!corpus.active"
            type="button"
            class="btn-secondary"
            :disabled="!canActivateCorpusItem(corpus) || corpusStore.isActivating"
            :title="activationBlockReasonForCorpus(corpus) ?? t('corpus.manager.activateCorpusTitle')"
            @click="activateCorpus(corpus.name)"
          >
            <CheckCircle2 class="w-4 h-4" />
            {{ t('corpus.manager.activate') }}
          </button>
          <button
            type="button"
            class="btn-secondary"
            :disabled="!canRefreshCorpusCapabilities"
            :title="!canRefreshCorpusCapabilities ? corpusCapabilitiesAccessMessage ?? t('corpus.manager.capabilitiesNotEnabled') : t('corpus.manager.checkCapabilities')"
            @click="refreshCorpusCapabilities(corpus.name)"
          >
            <RefreshCw class="w-4 h-4" />
            {{ t('corpus.manager.checkCapabilities') }}
          </button>
          <button
            type="button"
            class="btn-secondary"
            :disabled="!canLoadBuildReports || corpusStore.loadingBuildReportFor === corpus.name"
            :title="!canLoadBuildReports ? buildReportAccessMessage ?? t('corpus.manager.buildReportUnavailable') : t('corpus.manager.loadBuildReport')"
            @click="loadBuildReport(corpus.name)"
          >
            <FileSearch class="w-4 h-4" />
            {{ t('corpus.manager.buildReport') }}
          </button>
          <button
            type="button"
            class="btn-secondary danger-action"
            :disabled="!canUnregisterCorpusItem(corpus)"
            :title="unregisterBlockReasonForCorpus(corpus) ?? t('corpus.manager.removeFromRegistry')"
            @click="unregisterCorpus(corpus.name)"
          >
            <Trash2 class="w-4 h-4" />
            {{ t('corpus.manager.removeFromRegistry') }}
          </button>
        </div>
        <CorpusReportList
          :title="t('corpus.manager.buildReportAndManifest')"
          :ariaLabel="t('corpus.manager.buildReport')"
          :entries="buildReportEntries(corpus.name)"
        />
      </article>
    </section>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.corpus-manager-content { @apply space-y-6; }
.manager-hero { @apply flex items-start gap-3 pb-4 border-b border-neutral-200 dark:border-neutral-700; }
.hero-icon { @apply p-2 rounded-xl bg-primary-100 text-primary-700 dark:bg-primary-900/30 dark:text-primary-300; }
.section-title { @apply text-base font-semibold text-neutral-900 dark:text-neutral-100; }
.section-description { @apply text-sm text-neutral-500 dark:text-neutral-400 max-w-2xl; }
.import-card, .register-card, .job-card, .corpus-card, .workflow-card { @apply p-4 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/50; }
.surface-focus { @apply ring-2 ring-primary-400 ring-offset-2 ring-offset-white dark:ring-primary-500 dark:ring-offset-neutral-900; }
.surface-focus--soft { @apply rounded-xl p-3; }
.card-heading { @apply flex items-center gap-2 font-semibold text-neutral-900 dark:text-neutral-100; }
.technical-summary { @apply flex cursor-pointer list-none items-center gap-2 font-semibold text-neutral-900 dark:text-neutral-100; }
.technical-summary::-webkit-details-marker { @apply hidden; }
.card-note { @apply mt-1 text-sm text-neutral-500 dark:text-neutral-400; }
.limitation-note { @apply mt-2 rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800 dark:border-warning-900/50 dark:bg-warning-900/20 dark:text-warning-200; }
.workflow-steps { @apply mt-4 grid grid-cols-1 md:grid-cols-4 gap-2; }
.workflow-step { @apply rounded-lg border px-3 py-2 text-xs; }
.workflow-step strong { @apply block text-neutral-900 dark:text-neutral-100; }
.workflow-step span { @apply mt-1 block text-neutral-500 dark:text-neutral-400; }
.workflow-step--ready { @apply border-success-200 bg-success-50 dark:border-success-900/40 dark:bg-success-900/20; }
.workflow-step--active { @apply border-primary-200 bg-primary-50 dark:border-primary-900/40 dark:bg-primary-900/20; }
.workflow-step--waiting { @apply border-neutral-200 bg-white dark:border-neutral-700 dark:bg-neutral-900/70; }
.workflow-step--blocked { @apply border-warning-200 bg-warning-50 dark:border-warning-900/40 dark:bg-warning-900/20; }
.workflow-step--focused { @apply ring-2 ring-primary-400 ring-offset-1 ring-offset-white dark:ring-primary-500 dark:ring-offset-neutral-900; }
.operation-context { @apply mt-4; }
.validation-list { @apply mt-3 space-y-1 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-xs text-neutral-600 dark:border-neutral-700 dark:bg-neutral-900/70 dark:text-neutral-300; }
.form-grid { @apply grid grid-cols-1 md:grid-cols-2 gap-3 mt-4; }
.field { @apply flex flex-col gap-1.5 text-sm font-medium text-neutral-700 dark:text-neutral-200; }
.field-wide { @apply md:col-span-2; }
.field input, .field select, .field textarea { @apply px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100; }
.field-note { @apply text-xs font-normal text-neutral-500 dark:text-neutral-400; }
.checkbox-field { @apply flex flex-row items-center gap-2 text-sm text-neutral-700 dark:text-neutral-200; }
.method-contract, .method-catalogue, .option-spec-panel, .preflight-card, .payload-review { @apply rounded-lg border border-neutral-200 bg-white p-3 text-xs dark:border-neutral-700 dark:bg-neutral-900/70; }
.payload-review pre { @apply mt-3 max-h-56 overflow-auto rounded bg-neutral-950 p-2 text-[0.7rem] leading-relaxed text-neutral-100; }
.contract-grid { @apply flex flex-wrap gap-2 text-[0.68rem] text-neutral-500 dark:text-neutral-400; }
.contract-grid span { @apply rounded-full bg-neutral-100 px-2 py-0.5 dark:bg-neutral-800; }
.contract-section { @apply mt-3 space-y-1; }
.contract-section strong, .option-spec-heading strong { @apply text-xs font-semibold text-neutral-800 dark:text-neutral-100; }
.contract-list { @apply space-y-1 text-[0.68rem] leading-relaxed text-neutral-600 dark:text-neutral-300; }
.contract-list li { @apply flex flex-wrap items-center gap-1.5 rounded-md bg-neutral-50 px-2 py-1 dark:bg-neutral-950/50; }
.contract-list code { @apply rounded bg-white px-1 py-0.5 font-mono text-[0.64rem] text-neutral-700 dark:bg-neutral-900 dark:text-neutral-200; }
.method-guarantee { @apply text-success-700 dark:text-success-300; }
.method-limit { @apply text-warning-700 dark:text-warning-300; }
.option-spec-heading { @apply flex flex-wrap items-center justify-between gap-2; }
.option-spec-heading span { @apply text-[0.68rem] text-neutral-500 dark:text-neutral-400; }
.method-catalogue-grid { @apply mt-3 grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4; }
.method-catalogue-card { @apply flex flex-col gap-1 rounded-lg border border-neutral-100 bg-neutral-50 p-2 text-left text-[0.68rem] text-neutral-600 dark:border-neutral-800 dark:bg-neutral-950/40 dark:text-neutral-300; }
.method-catalogue-card strong { @apply text-xs text-neutral-900 dark:text-neutral-100; }
.method-catalogue-card--blocked { @apply border-warning-200 bg-warning-50/70 dark:border-warning-900/50 dark:bg-warning-900/20; }
.workflow-phase { @apply text-[0.6rem] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400; }
.method-catalogue summary { @apply flex cursor-pointer list-none items-center justify-between gap-2 text-sm font-semibold text-neutral-900 dark:text-neutral-100; }
.method-catalogue summary::-webkit-details-marker { @apply hidden; }
.method-catalogue summary span { @apply rounded-full bg-neutral-100 px-2 py-0.5 text-[0.65rem] text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400; }
.method-catalogue-card { @apply cursor-pointer hover:border-primary-200 hover:bg-primary-50 dark:hover:border-primary-900/60 dark:hover:bg-primary-950/20; }
.method-catalogue-card--selected { @apply border-primary-300 bg-primary-50 ring-1 ring-primary-300 dark:border-primary-800 dark:bg-primary-950/30 dark:ring-primary-800; }
.option-spec-grid { @apply mt-3 grid grid-cols-1 md:grid-cols-2 gap-3; }
.option-field { @apply rounded-lg border border-neutral-100 bg-neutral-50 p-3 dark:border-neutral-800 dark:bg-neutral-950/40; }
.option-field span:first-child { @apply flex flex-wrap items-center gap-1.5; }
.choice-description-list { @apply mt-2 space-y-1 rounded-md bg-white/70 p-2 dark:bg-neutral-900/70; }
.choice-description-list small { @apply block text-[0.68rem] leading-relaxed text-neutral-500 dark:text-neutral-400; }
.choice-description-list strong { @apply text-neutral-700 dark:text-neutral-200; }
.option-required, .option-type { @apply rounded-full px-1.5 py-0.5 text-[0.6rem] not-italic; }
.option-required { @apply bg-warning-100 text-warning-800 dark:bg-warning-900/40 dark:text-warning-200; }
.option-type { @apply bg-neutral-100 text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400; }
.option-checkbox { @apply rounded-lg border border-neutral-200 bg-white px-3 py-2 dark:border-neutral-700 dark:bg-neutral-900; }
.preflight-pass { @apply border-success-200 dark:border-success-900/50; }
.preflight-warning { @apply border-warning-200 dark:border-warning-900/50; }
.preflight-error { @apply border-error-200 dark:border-error-900/50; }
.preflight-heading { @apply flex flex-wrap items-center justify-between gap-2 text-sm text-neutral-900 dark:text-neutral-100; }
.preflight-heading span { @apply rounded-full bg-neutral-100 px-2 py-0.5 text-[0.65rem] text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400; }
.preflight-issues { @apply mt-2 space-y-1; }
.preflight-checks { @apply mt-3 space-y-1 text-[0.68rem] leading-relaxed; }
.preflight-checks li { @apply rounded-md border px-2 py-1; }
.preflight-checks strong { @apply mr-1 text-neutral-800 dark:text-neutral-100; }
.check-pass { @apply border-success-100 bg-success-50 text-success-800 dark:border-success-900/40 dark:bg-success-900/20 dark:text-success-200; }
.check-warn { @apply border-warning-100 bg-warning-50 text-warning-800 dark:border-warning-900/40 dark:bg-warning-900/20 dark:text-warning-200; }
.check-fail { @apply border-error-100 bg-error-50 text-error-800 dark:border-error-900/40 dark:bg-error-900/20 dark:text-error-200; }
.form-actions, .job-actions { @apply flex flex-wrap items-center gap-2 mt-4; }
.btn-primary { @apply px-4 py-2 rounded-lg bg-primary-600 text-white text-sm font-medium hover:bg-primary-700 disabled:opacity-50 disabled:cursor-not-allowed; }
.btn-secondary { @apply inline-flex items-center gap-2 px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-700 text-sm text-neutral-700 dark:text-neutral-200 hover:bg-white dark:hover:bg-neutral-800 disabled:opacity-50; }
.group-title { @apply text-xs font-semibold uppercase tracking-wider text-neutral-500 dark:text-neutral-400 mb-3; }
.job-list, .catalogue { @apply space-y-3; }
.job-list-heading { @apply flex flex-wrap items-center justify-between gap-2; }
.job-main { @apply flex items-center justify-between gap-3 text-sm; }
.job-main span, .job-message, .corpus-meta { @apply text-xs text-neutral-500 dark:text-neutral-400; }
.job-warning-list { @apply mt-2 list-disc rounded-lg border border-warning-200 bg-warning-50 px-4 py-2 text-xs text-warning-800 dark:border-warning-900/50 dark:bg-warning-900/20 dark:text-warning-200; }
.progress-track { @apply mt-3 h-2 rounded-full bg-neutral-200 dark:bg-neutral-700 overflow-hidden; }
.progress-track span { @apply block h-full rounded-full bg-primary-600; }
.job-provenance,
.job-trace { @apply mt-3 rounded-lg border border-neutral-200 bg-white p-3 text-xs dark:border-neutral-700 dark:bg-neutral-900/70; }
.job-provenance { @apply border-emerald-200 bg-emerald-50/50 dark:border-emerald-900 dark:bg-emerald-950/20; }
.job-provenance summary,
.job-trace summary { @apply cursor-pointer font-semibold text-neutral-800 dark:text-neutral-100; }
.job-retention-note { @apply mt-3 text-xs leading-relaxed text-neutral-500 dark:text-neutral-400; }
.trace-grid { @apply mt-3 grid gap-2; grid-template-columns: repeat(auto-fill, minmax(9rem, 1fr)); }
/* Long paths break at any character inside their cell. */
.trace-grid span { @apply min-w-0 rounded-md bg-neutral-50 px-2 py-1 text-neutral-600 dark:bg-neutral-950/50 dark:text-neutral-300; overflow-wrap: anywhere; }
.trace-grid strong { @apply mr-1 text-neutral-900 dark:text-neutral-100; }
.trace-urls { @apply mt-3 flex flex-col gap-1; }
.trace-urls code { @apply rounded bg-neutral-100 px-2 py-1 font-mono text-[0.68rem] text-neutral-700 dark:bg-neutral-950 dark:text-neutral-200; }
.trace-output { @apply mt-3 grid grid-cols-1 md:grid-cols-2 gap-3; }
.trace-output strong { @apply text-neutral-800 dark:text-neutral-100; }
.trace-output pre { @apply mt-1 max-h-44 overflow-auto rounded bg-neutral-950 p-2 text-[0.7rem] leading-relaxed text-neutral-100; }
.scope-badge { @apply rounded-full bg-warning-100 px-2 py-0.5 text-xs font-medium text-warning-800 dark:bg-warning-900/40 dark:text-warning-200; }
.post-import-handoff { @apply mt-4 rounded-lg border border-success-200 bg-success-50 p-3 text-xs dark:border-success-900/50 dark:bg-success-900/20; }
.handoff-heading { @apply flex flex-wrap items-center justify-between gap-2 text-sm text-success-900 dark:text-success-100; }
.handoff-status { @apply mt-3 flex flex-wrap items-center gap-2 text-[0.68rem] text-neutral-600 dark:text-neutral-300; }
.handoff-status code { @apply rounded bg-white px-1 py-0.5 font-mono text-[0.64rem] text-neutral-700 dark:bg-neutral-900 dark:text-neutral-200; }
.handoff-actions { @apply mt-3 flex flex-wrap items-center gap-2; }
.partial-activation-review { @apply mt-3 space-y-2 rounded-lg border border-warning-300 bg-warning-50 p-3 text-xs text-warning-900 dark:border-warning-800 dark:bg-warning-900/30 dark:text-warning-100; }
.partial-activation-review p { @apply text-warning-800 dark:text-warning-200; }
.partial-warning-list { @apply list-disc space-y-1 pl-4 text-warning-800 dark:text-warning-200; }
.corpus-info { @apply min-w-0; }
.corpus-name { @apply flex items-center gap-2 text-sm text-neutral-900 dark:text-neutral-100; }
.corpus-meta { @apply flex flex-wrap gap-2 mt-1; }
.corpus-actions { @apply mt-4 flex flex-wrap items-center gap-2; }
.danger-action { @apply border-error-200 text-error-700 hover:bg-error-50 dark:border-error-900/60 dark:text-error-300 dark:hover:bg-error-900/20; }
.active-badge { @apply px-2 py-0.5 rounded-full bg-success-100 text-success-700 dark:bg-success-900/30 dark:text-success-300 text-xs; }
.empty-state { @apply p-4 rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 text-sm text-neutral-500 dark:text-neutral-400; }
.error-text { @apply text-sm text-error-600 dark:text-error-400; }
.warning-text { @apply mt-2 text-xs text-warning-700 dark:text-warning-300; }
.route-flag { @apply rounded-full bg-neutral-100 px-1.5 py-0.5 text-[0.6rem] text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400; }
.route-flag--mutates { @apply bg-warning-100 text-warning-800 dark:bg-warning-900/40 dark:text-warning-200; }
.route-flag--ok { @apply bg-success-100 text-success-800 dark:bg-success-900/40 dark:text-success-200; }
</style>
