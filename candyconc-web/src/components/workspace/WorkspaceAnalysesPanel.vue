<script setup lang="ts">
/**
 * WorkspaceAnalysesPanel - Content for Analysis Library in Workspace
 */
import { computed, onMounted, ref, watch, nextTick } from 'vue'
import { useI18n } from 'vue-i18n'
import { Ban, Loader2, Play, RefreshCw, Table2, Trash2, X } from 'lucide-vue-next'
import {
  useAnalysisJobsStore,
  useAnalysisPresetsStore,
  useDocsetStore,
  useQueryStore,
  useSettingsStore,
  useUiStore,
} from '@/stores'
import type { AnalysisPreset, AnalysisPresetStatus, AnalysisType } from '@/stores/analysisPresets'
import type { ProductOperationFocus } from '@/stores/ui'
import type { AnalysisJobRows, AnalysisJobSnapshot } from '@/api/client'
import type { AnalysisJobMonitorEntry } from '@/stores/analysisJobs'
import { actionBus } from '@/actions'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import {
  analysisJobRowsReadiness,
  analysisResultAvailabilityLabel,
} from '@/lib/productOperationReadiness'
import MethodPanel from '@/components/analysis/MethodPanel.vue'
import { useProductOperationFocus } from '@/composables/useProductOperationFocus'
import { buildCoKwicQuery } from '@/utils/coKwic'
import { deriveFilterSpecFromLegacy, filterSpecSummaryParts } from '@/lib/filterSpec'
import { formatNumber, formatDateTime, formatPercent } from '@/i18n/format'

const { t } = useI18n()
const uiStore = useUiStore()
const analysisJobs = useAnalysisJobsStore()
const presetsStore = useAnalysisPresetsStore()
const docsetStore = useDocsetStore()
const queryStore = useQueryStore()
const settingsStore = useSettingsStore()
const { consumeFocusFor } = useProductOperationFocus()

const presets = computed(() => presetsStore.sortedPresets)
const isLoading = computed(() => presetsStore.isLoading)
const loadError = computed(() => presetsStore.error)
const searchQuery = ref('')
const searchInput = ref<HTMLInputElement | null>(null)
const typeFilter = ref<'all' | AnalysisType>('all')
const statusFilter = ref<'all' | AnalysisPresetStatus>('all')
const cancelling = ref<Record<string, boolean>>({})
const refreshingJobs = ref<Record<string, boolean>>({})
const loadingJobRows = ref<Record<string, boolean>>({})
const jobRows = ref<Record<string, AnalysisJobRows<Record<string, unknown>>>>({})
const lookupJobId = ref('')
const focusedJobOperation = ref<ProductOperationFocus | null>(null)
const canCancelAnalysisJobs = computed(() => analysisJobs.canCancelJobs)
const canRefreshAnalysisJobs = computed(() => analysisJobs.canRefreshJobs)
const canLoadAnalysisJobRows = computed(() => analysisJobs.canLoadJobRows)
const cancelAnalysisJobBlockReason = computed(() => analysisJobs.cancelDisabledReason)
const refreshAnalysisJobBlockReason = computed(() => analysisJobs.statusDisabledReason)
const rowsAnalysisJobBlockReason = computed(() => analysisJobs.rowsDisabledReason)
const canDeletePresets = computed(() => presetsStore.canDeletePresets)
const deletePresetBlockReason = computed(() => presetsStore.deleteAvailability.disabledReason)
const hasActiveFilters = computed(() =>
  !!searchQuery.value.trim() || typeFilter.value !== 'all' || statusFilter.value !== 'all'
)

const typeOrder: AnalysisType[] = [
  'frequency',
  'collocations',
  'collocation_network',
  'dispersion',
  'semantic',
  'ngrams',
  'keyness',
  'wordsketch',
]

// Labels resolve at call time so they follow the interface language.
const typeLabels: Record<AnalysisType, () => string> = {
  frequency: () => t('workspace.analysesPanel.types.frequency'),
  collocations: () => t('workspace.analysesPanel.types.collocations'),
  collocation_network: () => t('workspace.analysesPanel.types.collocationNetwork'),
  dispersion: () => t('workspace.analysesPanel.types.dispersion'),
  semantic: () => t('workspace.analysesPanel.types.semantic'),
  ngrams: () => t('workspace.analysesPanel.types.ngrams'),
  keyness: () => t('workspace.analysesPanel.types.keyness'),
  contrast: () => t('workspace.analysesPanel.types.contrast'),
  wordsketch: () => t('workspace.analysesPanel.types.wordsketch'),
}

const ANALYSIS_JOB_STATUS_OPERATION_ID = 'analysis.async_jobs.status'
const ANALYSIS_JOB_CANCEL_OPERATION_ID = 'analysis.async_jobs.cancel'
const ANALYSIS_JOB_ROWS_OPERATION_ID = 'analysis.async_jobs.rows'
const ANALYSIS_JOB_OPERATION_IDS = [
  ANALYSIS_JOB_STATUS_OPERATION_ID,
  ANALYSIS_JOB_CANCEL_OPERATION_ID,
  ANALYSIS_JOB_ROWS_OPERATION_ID,
]

const statusLabels: Record<AnalysisPresetStatus, () => string> = {
  idle: () => t('workspace.analysesPanel.status.idle'),
  queued: () => t('workspace.analysesPanel.status.queued'),
  running: () => t('workspace.analysesPanel.status.running'),
  done: () => t('workspace.analysesPanel.status.done'),
  error: () => t('workspace.analysesPanel.status.error'),
  cancelled: () => t('workspace.analysesPanel.status.cancelled'),
}

const typeOptions = computed(() =>
  typeOrder.filter((type) => presets.value.some((preset) => preset.type === type))
)
const typeCounts = computed<Record<AnalysisType, number>>(() => {
  const counts = {} as Record<AnalysisType, number>
  for (const preset of presets.value) {
    counts[preset.type] = (counts[preset.type] ?? 0) + 1
  }
  return counts
})

const statusOrder: AnalysisPresetStatus[] = ['running', 'queued', 'done', 'error', 'cancelled', 'idle']
const statusOptions = computed(() =>
  statusOrder.filter((status) => presets.value.some((preset) => (preset.status ?? 'idle') === status))
)
const statusCounts = computed<Record<AnalysisPresetStatus, number>>(() => {
  const counts = {} as Record<AnalysisPresetStatus, number>
  for (const preset of presets.value) {
    const status = preset.status ?? 'idle'
    counts[status] = (counts[status] ?? 0) + 1
  }
  return counts
})

function labelForType(type: AnalysisType): string {
  return typeLabels[type]?.() ?? type
}

function labelForStatus(status?: AnalysisPresetStatus): string | undefined {
  if (!status) return undefined
  return statusLabels[status]?.() ?? status
}

function statusClass(status?: AnalysisPresetStatus): string {
  if (status === 'running' || status === 'queued') return 'chip-status-running'
  if (status === 'done') return 'chip-status-done'
  if (status === 'error' || status === 'cancelled') return 'chip-status-error'
  return 'chip-status-idle'
}

function canCancelPreset(preset: AnalysisPreset): boolean {
  return canCancelAnalysisJobs.value && !!preset.jobId && (preset.status === 'running' || preset.status === 'queued')
}

function isCancelling(preset: AnalysisPreset): boolean {
  return !!cancelling.value[preset.id]
}

function matchesPreset(preset: AnalysisPreset): boolean {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return true
  const haystack = [
    preset.name,
    preset.type,
    labelForType(preset.type),
    preset.corpus,
    preset.queryTerm ?? '',
  ]
    .join(' ')
    .toLowerCase()
  return haystack.includes(query)
}

const filteredPresets = computed(() =>
  presets.value.filter((preset) => {
    if (!matchesPreset(preset)) return false
    if (typeFilter.value !== 'all' && preset.type !== typeFilter.value) return false
    if (statusFilter.value !== 'all' && (preset.status ?? 'idle') !== statusFilter.value) return false
    return true
  })
)

const hasFilteredPresets = computed(() => filteredPresets.value.length > 0)

const filteredCountLabel = computed(() => {
  const count = filteredPresets.value.length
  const total = presets.value.length
  if (count === total) return t('workspace.analysesPanel.count', { count: formatNumber(count) }, count)
  return t('workspace.analysesPanel.countOf', { count: formatNumber(count), total: formatNumber(total) }, count)
})

const activeFilterLabel = computed(() => {
  const parts: string[] = []
  const query = searchQuery.value.trim()
  if (query) {
    parts.push(t('workspace.analysesPanel.filterSearch', { query }))
  }
  if (typeFilter.value !== 'all') {
    parts.push(t('workspace.analysesPanel.filterType', { type: labelForType(typeFilter.value) }))
  }
  if (statusFilter.value !== 'all') {
    parts.push(t('workspace.analysesPanel.filterStatus', { status: labelForStatus(statusFilter.value) ?? statusFilter.value }))
  }
  if (!parts.length) return null
  return t('workspace.analysesPanel.filterSummary', { parts: parts.join(' · ') })
})

const showRecent = computed(() =>
  !searchQuery.value.trim() && typeFilter.value === 'all' && statusFilter.value === 'all'
)

const recentPresets = computed(() => (showRecent.value ? presets.value.slice(0, 3) : []))

const remainingPresets = computed(() => {
  if (!showRecent.value) return filteredPresets.value
  const recentIds = new Set(recentPresets.value.map((preset) => preset.id))
  return filteredPresets.value.filter((preset) => !recentIds.has(preset.id))
})

const monitorJobs = computed<AnalysisJobMonitorEntry[]>(() =>
  canRefreshAnalysisJobs.value ? analysisJobs.monitorJobs : [],
)

function isRunningJob(status: string): boolean {
  return status === 'running' || status === 'queued'
}

const activeMonitorJobCount = computed(() =>
  monitorJobs.value.filter((job) => isRunningJob(job.snapshot.status)).length
)

function canCancelMonitorJob(job: AnalysisJobMonitorEntry): boolean {
  return canCancelAnalysisJobs.value && isRunningJob(job.snapshot.status)
}

function isCancellingJob(jobId: string): boolean {
  return !!cancelling.value[`job:${jobId}`]
}

function isRefreshingJob(jobId: string): boolean {
  return !!refreshingJobs.value[jobId]
}

function isLoadingJobRows(jobId: string): boolean {
  return !!loadingJobRows.value[jobId]
}

function canRefreshMonitorJob(): boolean {
  return canRefreshAnalysisJobs.value
}

function rowLoadBlockReason(job: AnalysisJobMonitorEntry): string | null {
  return analysisJobRowsReadiness(job.snapshot, {
    rowsEnabled: canLoadAnalysisJobRows.value,
    disabledReason: rowsAnalysisJobBlockReason.value,
  }).blockReason
}

function canLoadRowsForJob(job: AnalysisJobMonitorEntry): boolean {
  return rowLoadBlockReason(job) === null
}

function focusedJobOperationLabel(): string | null {
  const focus = focusedJobOperation.value
  if (!focus) return null
  if (focus.operationId === ANALYSIS_JOB_STATUS_OPERATION_ID) return t('workspace.analysesPanel.opStatus')
  if (focus.operationId === ANALYSIS_JOB_ROWS_OPERATION_ID) return t('workspace.analysesPanel.opRows')
  if (focus.operationId === ANALYSIS_JOB_CANCEL_OPERATION_ID) return t('workspace.analysesPanel.opCancel')
  return null
}

function focusedJobOperationHint(): string | null {
  const focus = focusedJobOperation.value
  if (!focus) return null
  if (focus.operationId === ANALYSIS_JOB_STATUS_OPERATION_ID) {
    return t('workspace.analysesPanel.opStatusHint')
  }
  if (focus.operationId === ANALYSIS_JOB_ROWS_OPERATION_ID) {
    return t('workspace.analysesPanel.opRowsHint')
  }
  if (focus.operationId === ANALYSIS_JOB_CANCEL_OPERATION_ID) {
    return t('workspace.analysesPanel.opCancelHint')
  }
  return null
}

function jobMatchesFocusedOperation(job: AnalysisJobMonitorEntry): boolean {
  const focus = focusedJobOperation.value
  if (!focus) return false
  if (focus.operationId === ANALYSIS_JOB_STATUS_OPERATION_ID) return true
  if (focus.operationId === ANALYSIS_JOB_ROWS_OPERATION_ID) return canLoadRowsForJob(job)
  if (focus.operationId === ANALYSIS_JOB_CANCEL_OPERATION_ID) return canCancelMonitorJob(job)
  return false
}

function focusedJobOperationLabelFor(job: AnalysisJobMonitorEntry): string | null {
  return jobMatchesFocusedOperation(job) ? focusedJobOperationLabel() : null
}

function handleAnalysisJobFocus(focus: ProductOperationFocus): void {
  if (!ANALYSIS_JOB_OPERATION_IDS.includes(focus.operationId)) return
  focusedJobOperation.value = focus
}

function labelForJobKind(kind?: string): string {
  if (!kind) return t('workspace.analysesPanel.jobKindFallback')
  // A diff job compares two groups. The collocation contrast of the Contrast
  // tab runs as collocates_diff and was listed as "Collocations".
  if (kind.endsWith('_diff')) {
    return kind.includes('collocate')
      ? t('workspace.analysesPanel.types.collocationContrast')
      : typeLabels.contrast()
  }
  const normalized = kind
    .replace(/_job$/, '')
    .replace(/_list$/, '')
    .replace(/_diff$/, '')
  const direct = typeLabels[normalized as AnalysisType]
  if (direct) return direct()
  if (kind.includes('collocate')) return typeLabels.collocations()
  if (kind.includes('frequency')) return typeLabels.frequency()
  if (kind.includes('ngram')) return typeLabels.ngrams()
  if (kind.includes('keyness')) return typeLabels.keyness()
  if (kind.includes('contrast')) return typeLabels.contrast()
  return kind
}

function jobProgressLabel(snapshot: AnalysisJobSnapshot): string {
  if (typeof snapshot.progress === 'number') {
    return formatPercent(snapshot.progress / 100, 0)
  }
  return t('workspace.analysesPanel.progressUnknown')
}

function formatBytes(value?: number | null): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  if (value < 1024) return `${formatNumber(value)} B`
  if (value < 1024 * 1024) return `${formatNumber(value / 1024, { maximumFractionDigits: 1 })} KB`
  return `${formatNumber(value / (1024 * 1024), { maximumFractionDigits: 1 })} MB`
}

function resultAvailabilityLabel(snapshot: AnalysisJobSnapshot): string | null {
  return analysisResultAvailabilityLabel(snapshot)
}

function scopeLabelForJob(job: AnalysisJobMonitorEntry): string {
  return job.scope ?? t('workspace.analysesPanel.unknownScope')
}

function jobLookupLabel(job: AnalysisJobMonitorEntry): string {
  const params = { scope: scopeLabelForJob(job), jobId: job.jobId }
  return job.active
    ? t('workspace.analysesPanel.jobLookupActive', params)
    : t('workspace.analysesPanel.jobLookupKnown', params)
}

function previewRows(jobId: string): Record<string, unknown>[] {
  return (jobRows.value[jobId]?.rows ?? []).slice(0, 5)
}

function jobRowsFor(jobId: string): AnalysisJobRows<Record<string, unknown>> | null {
  return jobRows.value[jobId] ?? null
}

function previewTotalRows(jobId: string): number {
  const result = jobRowsFor(jobId)
  return result?.total_rows ?? result?.total ?? previewRows(jobId).length
}

function jobResultEvidenceLabels(jobId: string): string[] {
  const result = jobRowsFor(jobId)
  if (!result) return []
  const labels: string[] = []
  const rows = result.rows?.length ?? 0
  labels.push(t('workspace.analysesPanel.previewRowsLoaded', { count: formatNumber(rows) }))
  if (typeof result.total_rows === 'number') {
    labels.push(t('workspace.analysesPanel.totalRows', { count: formatNumber(result.total_rows) }))
  } else if (typeof result.total === 'number') {
    labels.push(t('workspace.analysesPanel.total', { count: formatNumber(result.total) }))
  }
  if (typeof result.total_candidates === 'number') {
    labels.push(t('workspace.analysesPanel.candidates', { count: formatNumber(result.total_candidates) }))
  }
  if (typeof result.row_limit === 'number') {
    labels.push(t('workspace.analysesPanel.rowLimit', { count: formatNumber(result.row_limit) }))
  }
  if (typeof result.offset === 'number' || typeof result.limit === 'number') {
    labels.push(t('workspace.analysesPanel.fetchWindow', {
      offset: formatNumber(result.offset ?? 0),
      limit: formatNumber(result.limit ?? rows),
    }))
  }
  const resultSize = formatBytes(result.result_bytes)
  if (resultSize) {
    labels.push(t('workspace.analysesPanel.resultSize', { size: resultSize }))
  }
  return labels
}

function jobResultWarning(jobId: string): string | null {
  const result = jobRowsFor(jobId)
  if (!result) return null
  if (result.truncated) {
    return t('workspace.analysesPanel.resultTruncated')
  }
  if (result.result_discarded) {
    return t('workspace.analysesPanel.resultDiscarded', {
      reason: result.result_discard_reason ?? t('workspace.analysesPanel.discardReasonDefault'),
    })
  }
  return null
}

function previewFields(row: Record<string, unknown>): Array<[string, unknown]> {
  return Object.entries(row).slice(0, 6)
}

function formatPreviewValue(value: unknown): string {
  if (value === null || value === undefined) return '—'
  if (typeof value === 'number') return formatNumber(value)
  if (typeof value === 'string') return value
  return JSON.stringify(value)
}

const validityMap = ref<Record<string, boolean | null>>({})
let validityToken = 0

async function refreshValidity() {
  const token = ++validityToken
  const visible = [...recentPresets.value, ...remainingPresets.value].slice(0, 12)
  const next: Record<string, boolean | null> = { ...validityMap.value }
  for (const preset of visible) {
    if (!preset.resultMeta || !preset.result) {
      next[preset.id] = null
      continue
    }
    try {
      const isValid = await presetsStore.isResultValid(preset)
      if (token !== validityToken) return
      next[preset.id] = isValid
    } catch {
      if (token !== validityToken) return
      next[preset.id] = null
    }
  }
  if (token === validityToken) {
    validityMap.value = next
  }
}

function cacheLabel(preset: AnalysisPreset): string | null {
  const state = validityMap.value[preset.id]
  if (state === true) return t('workspace.analysesPanel.cacheCurrent')
  if (state === false) return t('workspace.analysesPanel.cacheStale')
  return null
}

function cacheClass(preset: AnalysisPreset): string {
  const state = validityMap.value[preset.id]
  if (state === true) return 'chip-cache-ok'
  if (state === false) return 'chip-cache-warn'
  return 'chip-cache-unknown'
}

function cacheTitle(preset: AnalysisPreset): string {
  const state = validityMap.value[preset.id]
  if (state === true) return t('workspace.analysesPanel.cacheCurrentTitle')
  if (state === false) return t('workspace.analysesPanel.cacheStaleTitle')
  return t('workspace.analysesPanel.cacheUnknownTitle')
}

function formatDate(ts: number): string {
  return formatDateTime(ts)
}

function queryTermForPreset(preset: AnalysisPreset): string | null {
  const term = preset.queryTerm?.trim()
  if (!term || preset.type !== 'collocations') return term ?? null
  const params = preset.params as {
    anchorCollocate?: unknown
    windowSize?: unknown
    withinSentence?: unknown
    attribute?: unknown
  }
  const anchor = typeof params.anchorCollocate === 'string'
    ? params.anchorCollocate.split('|').map((value) => value.trim()).filter(Boolean)
    : []
  if (!anchor.length) return term
  const rawWindow = typeof params.windowSize === 'number' ? params.windowSize : 5
  const window = Number.isFinite(rawWindow) ? Math.max(1, Math.round(rawWindow)) : 5
  return buildCoKwicQuery({
    term,
    collocates: anchor,
    window,
    withinSentence: typeof params.withinSentence === 'boolean' ? params.withinSentence : true,
    attribute: params.attribute === 'lemma' ? 'lemma' : 'word',
  })
}

function scopeSummary(preset: AnalysisPreset): string | null {
  if (!preset.docset) return t('workspace.shared.wholeCorpus')
  const parts = filterSpecSummaryParts(
    deriveFilterSpecFromLegacy(preset.docset.filters, preset.docset.filterSpec)
  )
  if (preset.docset.includeAi && !preset.docset.includeHuman) parts.push(t('workspace.shared.ai'))
  if (preset.docset.includeHuman && !preset.docset.includeAi) parts.push(t('workspace.shared.human'))
  if (!parts.length) return t('workspace.analysesPanel.scopeNoFilters')
  let label = parts.join(' · ')
  if (label.length > 140) label = `${label.slice(0, 137)}…`
  return label
}

async function applyPreset(preset: AnalysisPreset) {
  const corpusProblem = await presetsStore.activatePresetCorpus(preset)
  if (corpusProblem) {
    uiStore.showToast(corpusProblem, 'error')
    return
  }
  if (preset.docset) {
    await docsetStore.applySnapshot(preset.docset as any)
  } else {
    docsetStore.resetDocset()
  }
  const restoredQuery = queryTermForPreset(preset)
  if (restoredQuery) {
    queryStore.setTerm(restoredQuery)
  }
  await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: preset.type as any } }, { source: 'restore' })
  presetsStore.setPending(preset)
  void presetsStore.touch(preset.id).catch((err) => {
    const message = err instanceof Error ? err.message : t('workspace.analysesPanel.touchFailed')
    uiStore.showToast(message, 'warning')
  })
  uiStore.closeWorkspace()
}

async function removePreset(preset: AnalysisPreset) {
  if (!canDeletePresets.value) {
    uiStore.showToast(deletePresetBlockReason.value ?? t('workspace.analysesPanel.deleteNotEnabledSession'), 'warning')
    return
  }
  if (!settingsStore.confirmDeletion(preset.name)) return
  try {
    await presetsStore.remove(preset.id)
  } catch (err) {
    const message = err instanceof Error ? err.message : t('workspace.analysesPanel.deleteFailed')
    uiStore.showToast(message, 'error')
  }
}

function reloadPresets() {
  if (isLoading.value) return
  void presetsStore.init(undefined, true)
  void nextTick(() => {
    searchInput.value?.focus()
  })
}

function resetFilters() {
  searchQuery.value = ''
  typeFilter.value = 'all'
  statusFilter.value = 'all'
  void nextTick(() => {
    searchInput.value?.focus()
  })
}

function clearSearch() {
  searchQuery.value = ''
  void nextTick(() => {
    searchInput.value?.focus()
  })
}

async function cancelPreset(preset: AnalysisPreset) {
  if (!canCancelAnalysisJobs.value) {
    uiStore.showToast(cancelAnalysisJobBlockReason.value ?? t('workspace.analysesPanel.cancelNotEnabledSession'), 'warning')
    return
  }
  if (!preset.jobId || isCancelling(preset) || !canCancelPreset(preset)) return
  cancelling.value = { ...cancelling.value, [preset.id]: true }
  try {
    const snap = await analysisJobs.cancelJob(preset.jobId)
    await presetsStore.updateJobStatus(preset.id, snap)
    uiStore.showToast(t('workspace.analysesPanel.cancelling'), 'info')
  } catch (err) {
    const message = err instanceof Error ? err.message : t('workspace.analysesPanel.cancelFailed')
    uiStore.showToast(message, 'error')
  } finally {
    const next = { ...cancelling.value }
    delete next[preset.id]
    cancelling.value = next
  }
}

async function refreshMonitorJob(job: AnalysisJobMonitorEntry) {
  if (!canRefreshMonitorJob()) {
    uiStore.showToast(refreshAnalysisJobBlockReason.value ?? t('workspace.analysesPanel.statusNotEnabledSession'), 'warning')
    return
  }
  if (isRefreshingJob(job.jobId)) return
  refreshingJobs.value = { ...refreshingJobs.value, [job.jobId]: true }
  try {
    await analysisJobs.refreshJob(job.jobId)
  } catch (err) {
    const message = err instanceof Error ? err.message : t('workspace.analysesPanel.refreshFailed')
    uiStore.showToast(message, 'error')
  } finally {
    const next = { ...refreshingJobs.value }
    delete next[job.jobId]
    refreshingJobs.value = next
  }
}

async function lookupMonitorJob() {
  const jobId = lookupJobId.value.trim()
  if (!jobId) {
    uiStore.showToast(t('workspace.analysesPanel.enterJobId'), 'warning')
    return
  }
  if (!canRefreshMonitorJob()) {
    uiStore.showToast(refreshAnalysisJobBlockReason.value ?? t('workspace.analysesPanel.statusNotEnabledSession'), 'warning')
    return
  }
  refreshingJobs.value = { ...refreshingJobs.value, [jobId]: true }
  try {
    await analysisJobs.refreshJob(jobId)
    lookupJobId.value = ''
    uiStore.showToast(t('workspace.analysesPanel.jobAdded'), 'success')
  } catch (err) {
    const message = err instanceof Error ? err.message : t('workspace.analysesPanel.jobNotFound')
    uiStore.showToast(message, 'error')
  } finally {
    const next = { ...refreshingJobs.value }
    delete next[jobId]
    refreshingJobs.value = next
  }
}

async function loadMonitorJobRows(job: AnalysisJobMonitorEntry) {
  const blockedReason = rowLoadBlockReason(job)
  if (blockedReason) {
    uiStore.showToast(blockedReason, 'warning')
    return
  }
  if (isLoadingJobRows(job.jobId)) return
  loadingJobRows.value = { ...loadingJobRows.value, [job.jobId]: true }
  try {
    const rows = await analysisJobs.rows<Record<string, unknown>>(job.jobId, 0, 5)
    jobRows.value = { ...jobRows.value, [job.jobId]: rows }
  } catch (err) {
    const message = err instanceof Error ? err.message : t('workspace.analysesPanel.rowsFailed')
    uiStore.showToast(message, 'error')
  } finally {
    const next = { ...loadingJobRows.value }
    delete next[job.jobId]
    loadingJobRows.value = next
  }
}

async function cancelActiveJob(job: AnalysisJobMonitorEntry) {
  if (!canCancelAnalysisJobs.value) {
    uiStore.showToast(cancelAnalysisJobBlockReason.value ?? t('workspace.analysesPanel.cancelNotEnabledSession'), 'warning')
    return
  }
  if (!canCancelMonitorJob(job) || isCancellingJob(job.jobId)) return
  const key = `job:${job.jobId}`
  cancelling.value = { ...cancelling.value, [key]: true }
  try {
    await analysisJobs.cancelJob(job.jobId)
    if (job.scope) {
      analysisJobs.clearScope(job.scope)
    }
    uiStore.showToast(t('workspace.analysesPanel.cancelling'), 'info')
  } catch (err) {
    const message = err instanceof Error ? err.message : t('workspace.analysesPanel.cancelFailed')
    uiStore.showToast(message, 'error')
  } finally {
    const next = { ...cancelling.value }
    delete next[key]
    cancelling.value = next
  }
}

onMounted(() => {
  void presetsStore.init()
  void refreshValidity()
})

consumeFocusFor(['analysis.async_jobs'], handleAnalysisJobFocus)

watch(
  () => [uiStore.workspaceOpen, uiStore.workspaceTab],
  ([open, tab]) => {
    if (!open || tab !== 'analyses') return
    void nextTick(() => {
      searchInput.value?.focus()
    })
  }
)

watch(
  () => uiStore.workspaceOpen,
  (open) => {
    if (open) return
    searchQuery.value = ''
    typeFilter.value = 'all'
    statusFilter.value = 'all'
  }
)

watch([recentPresets, remainingPresets], () => {
  void refreshValidity()
})

watch(statusCounts, () => {
  if (statusFilter.value === 'all') return
  const count = statusCounts.value[statusFilter.value] ?? 0
  if (count === 0) {
    statusFilter.value = 'all'
  }
})

watch(typeCounts, () => {
  if (typeFilter.value === 'all') return
  const count = typeCounts.value[typeFilter.value] ?? 0
  if (count === 0) {
    typeFilter.value = 'all'
  }
})
</script>

<template>
  <div class="library-body">
    <section class="job-monitor" aria-labelledby="active-analysis-jobs-heading">
      <div class="job-monitor-head">
        <div>
          <div id="active-analysis-jobs-heading" class="section-title">
            {{ t('workspace.analysesPanel.jobsTitle') }}
          </div>
          <p class="job-monitor-copy">
            {{ t('workspace.analysesPanel.jobsIntro') }}
          </p>
        </div>
        <div class="job-monitor-counts" aria-live="polite">
          <span class="chip chip-primary">
            {{ t('workspace.analysesPanel.monitorActive', { count: formatNumber(activeMonitorJobCount) }) }}
          </span>
          <span class="chip">
            {{ t('workspace.analysesPanel.monitorKnown', { count: formatNumber(monitorJobs.length) }) }}
          </span>
        </div>
      </div>
      <form class="job-lookup" @submit.prevent="lookupMonitorJob">
        <input
          v-model="lookupJobId"
          class="job-lookup-input"
          type="search"
          :placeholder="t('workspace.analysesPanel.lookupPlaceholder')"
          :aria-label="t('workspace.analysesPanel.lookupLabel')"
          autocomplete="off"
          spellcheck="false"
          :disabled="!canRefreshAnalysisJobs"
        />
        <button
          class="job-action-btn"
          type="submit"
          :disabled="!canRefreshAnalysisJobs || !lookupJobId.trim() || isRefreshingJob(lookupJobId.trim())"
          :title="!canRefreshAnalysisJobs ? refreshAnalysisJobBlockReason ?? t('workspace.analysesPanel.statusNotEnabled') : t('workspace.analysesPanel.checkJobId')"
        >
          <Loader2 v-if="isRefreshingJob(lookupJobId.trim())" class="w-3.5 h-3.5 animate-spin" />
          <RefreshCw v-else class="w-3.5 h-3.5" />
          {{ t('workspace.analysesPanel.check') }}
        </button>
      </form>
      <div v-if="!monitorJobs.length" class="job-monitor-empty" role="status" aria-live="polite">
        <strong>
          {{ canRefreshAnalysisJobs ? t('workspace.analysesPanel.noJobs') : t('workspace.analysesPanel.monitorUnavailable') }}
        </strong>
        <span>
          {{
            canRefreshAnalysisJobs
              ? t('workspace.analysesPanel.noJobsHint')
              : refreshAnalysisJobBlockReason ?? t('workspace.analysesPanel.statusNotInCatalog')
          }}
        </span>
      </div>
      <div
        v-if="focusedJobOperationLabel()"
        class="job-operation-focus"
        role="status"
        aria-live="polite"
      >
        <strong>{{ t('workspace.analysesPanel.focus', { label: focusedJobOperationLabel() }) }}</strong>
        <span>{{ focusedJobOperationHint() }}</span>
      </div>
      <div class="job-monitor-list">
        <article
          v-for="job in monitorJobs"
          :key="`${job.scope ?? 'recent'}:${job.jobId}`"
          class="job-monitor-card"
          :class="{
            'job-monitor-card-terminal': !job.active && !isRunningJob(job.snapshot.status),
            'job-monitor-card-focused': jobMatchesFocusedOperation(job),
          }"
          :data-testid="`job-monitor-card-${job.jobId}`"
        >
          <div class="job-monitor-card-head">
            <div>
              <div class="job-monitor-title">
                {{ labelForJobKind(job.snapshot.kind) }}
              </div>
              <div class="job-monitor-subtitle">
                {{ jobLookupLabel(job) }}
              </div>
            </div>
            <JobStatusPill
              :data-testid="`active-job-${job.jobId}`"
              :status="job.snapshot.status"
              :progress="job.snapshot.progress ?? 0"
              :message="job.snapshot.message || jobProgressLabel(job.snapshot)"
              :can-cancel="canCancelMonitorJob(job) && !isCancellingJob(job.jobId)"
              @cancel="cancelActiveJob(job)"
            />
          </div>
          <div
            v-if="isRunningJob(job.snapshot.status) && !canCancelAnalysisJobs"
            class="job-result-warning"
          >
            {{ t('workspace.analysesPanel.cancelUnavailable', { reason: cancelAnalysisJobBlockReason ?? t('workspace.analysesPanel.cancelNotEnabledSession') }) }}
          </div>
          <div class="job-monitor-meta">
            <span v-if="job.snapshot.corpus" class="chip" :title="t('workspace.shared.corpus', { corpus: job.snapshot.corpus })">
              {{ t('workspace.shared.corpus', { corpus: job.snapshot.corpus }) }}
            </span>
            <span class="chip" :class="statusClass(job.snapshot.status as AnalysisPresetStatus)">
              {{ labelForStatus(job.snapshot.status as AnalysisPresetStatus) ?? job.snapshot.status }}
            </span>
            <span v-if="job.snapshot.total_rows !== undefined && job.snapshot.total_rows !== null" class="chip">
              {{ t('workspace.analysesPanel.rows', { count: formatNumber(job.snapshot.total_rows) }) }}
            </span>
            <span
              v-if="resultAvailabilityLabel(job.snapshot)"
              class="chip"
              :class="job.snapshot.result_discarded || job.snapshot.result_available === false ? 'chip-status-error' : 'chip-status-done'"
            >
              {{ resultAvailabilityLabel(job.snapshot) }}
            </span>
            <span v-if="formatBytes(job.snapshot.result_bytes)" class="chip">
              {{ t('workspace.analysesPanel.resultSize', { size: formatBytes(job.snapshot.result_bytes) }) }}
            </span>
            <span v-if="job.snapshot.error" class="chip chip-status-error" :title="job.snapshot.error">
              {{ t('workspace.analysesPanel.errorDetails') }}
            </span>
            <span
              v-if="focusedJobOperationLabelFor(job)"
              class="chip chip-operation-focus"
            >
              {{ t('workspace.analysesPanel.focus', { label: focusedJobOperationLabelFor(job) }) }}
            </span>
          </div>
          <div class="job-monitor-actions">
            <button
              class="job-action-btn subtle"
              type="button"
              :disabled="!canRefreshAnalysisJobs || isRefreshingJob(job.jobId)"
              :title="!canRefreshAnalysisJobs ? refreshAnalysisJobBlockReason ?? t('workspace.analysesPanel.statusNotEnabled') : t('workspace.analysesPanel.refreshStatus')"
              @click="refreshMonitorJob(job)"
            >
              <Loader2 v-if="isRefreshingJob(job.jobId)" class="w-3.5 h-3.5 animate-spin" />
              <RefreshCw v-else class="w-3.5 h-3.5" />
              {{ t('workspace.analysesPanel.statusButton') }}
            </button>
            <button
              v-if="job.snapshot.status === 'done'"
              class="job-action-btn subtle"
              type="button"
              :disabled="!canLoadRowsForJob(job) || isLoadingJobRows(job.jobId)"
              :title="rowLoadBlockReason(job) ?? t('workspace.analysesPanel.loadRows')"
              @click="loadMonitorJobRows(job)"
            >
              <Loader2 v-if="isLoadingJobRows(job.jobId)" class="w-3.5 h-3.5 animate-spin" />
              <Table2 v-else class="w-3.5 h-3.5" />
              {{ t('workspace.analysesPanel.rowsButton') }}
            </button>
          </div>
          <div
            v-if="job.snapshot.status === 'done' && !canLoadRowsForJob(job)"
            class="job-result-warning"
          >
            {{ rowLoadBlockReason(job) }}
          </div>
          <div v-if="previewRows(job.jobId).length" class="job-row-preview">
            <div class="job-row-preview-title">
              {{ t('workspace.analysesPanel.preview', { shown: formatNumber(previewRows(job.jobId).length), total: formatNumber(previewTotalRows(job.jobId)) }) }}
            </div>
            <div class="job-row-evidence" :aria-label="t('workspace.analysesPanel.resultLimits')">
              <span
                v-for="label in jobResultEvidenceLabels(job.jobId)"
                :key="`${job.jobId}:evidence:${label}`"
                class="chip"
              >
                {{ label }}
              </span>
            </div>
            <div
              v-if="jobResultWarning(job.jobId)"
              class="job-result-warning"
            >
              {{ jobResultWarning(job.jobId) }}
            </div>
            <MethodPanel
              v-if="jobRows[job.jobId]?.method"
              :method="jobRows[job.jobId]?.method"
            />
            <div class="job-row-preview-list">
              <div
                v-for="(row, rowIndex) in previewRows(job.jobId)"
                :key="`${job.jobId}:row:${rowIndex}`"
                class="job-row-preview-item"
              >
                <span
                  v-for="[field, value] in previewFields(row)"
                  :key="field"
                  class="chip"
                  :title="`${field}: ${formatPreviewValue(value)}`"
                >
                  {{ field }}: {{ formatPreviewValue(value) }}
                </span>
              </div>
            </div>
          </div>
        </article>
      </div>
    </section>

    <div v-if="presets.length" class="toolbar">
      <div class="toolbar-search">
        <div class="search-field" role="search">
          <input
            v-model="searchQuery"
            ref="searchInput"
            type="search"
            class="search-input"
            :placeholder="t('workspace.analysesPanel.searchPlaceholder')"
            :aria-label="t('workspace.analysesPanel.searchLabel')"
            autocomplete="off"
            spellcheck="false"
            inputmode="search"
            enterkeyhint="search"
            autocapitalize="none"
            @keydown.esc.prevent="clearSearch"
          />
          <button
            v-if="searchQuery"
            class="search-clear"
            type="button"
            :title="t('workspace.shared.clearSearch')"
            :aria-label="t('workspace.shared.clearSearch')"
            @click="clearSearch"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
      <div v-if="typeOptions.length" class="toolbar-filters">
        <button
          class="filter-btn"
          :class="{ active: typeFilter === 'all' }"
          type="button"
          @click="typeFilter = 'all'"
        >
          {{ t('workspace.shared.filterAll', { count: formatNumber(presets.length) }) }}
        </button>
        <button
          v-for="type in typeOptions"
          :key="type"
          class="filter-btn"
          :class="{ active: typeFilter === type }"
          type="button"
          :disabled="(typeCounts[type] ?? 0) === 0"
          :title="(typeCounts[type] ?? 0) === 0 ? t('workspace.analysesPanel.noneOfType') : labelForType(type)"
          @click="typeFilter = type"
        >
          {{ labelForType(type) }} ({{ formatNumber(typeCounts[type] ?? 0) }})
        </button>
      </div>
      <div v-if="statusOptions.length" class="toolbar-filters">
        <span class="filter-label">{{ t('workspace.analysesPanel.statusFilterLabel') }}</span>
        <button
          class="filter-btn"
          :class="{ active: statusFilter === 'all' }"
          type="button"
          @click="statusFilter = 'all'"
        >
          {{ t('workspace.shared.filterAll', { count: formatNumber(presets.length) }) }}
        </button>
        <button
          v-for="status in statusOptions"
          :key="status"
          class="filter-btn"
          :class="{ active: statusFilter === status }"
          type="button"
          :disabled="(statusCounts[status] ?? 0) === 0"
          :title="(statusCounts[status] ?? 0) === 0 ? t('workspace.analysesPanel.noneWithStatus') : labelForStatus(status)"
          @click="statusFilter = status"
        >
          {{ labelForStatus(status) }} ({{ formatNumber(statusCounts[status] ?? 0) }})
        </button>
      </div>
      <div class="toolbar-meta">
        <span aria-live="polite">{{ filteredCountLabel }}</span>
        <span v-if="activeFilterLabel" class="toolbar-meta-secondary" :title="activeFilterLabel">
          {{ activeFilterLabel }}
        </span>
        <span v-else class="toolbar-meta-secondary" :title="t('workspace.shared.noFilters')">
          {{ t('workspace.shared.noFilters') }}
        </span>
        <button
          v-if="hasActiveFilters"
          class="filter-reset"
          type="button"
          :title="t('workspace.shared.resetFilters')"
          :aria-label="t('workspace.shared.resetFilters')"
          @click="resetFilters"
        >
          {{ t('workspace.shared.resetFilters') }}
        </button>
      </div>
    </div>

    <div v-if="isLoading" class="empty" role="status" aria-live="polite">
      {{ t('workspace.analysesPanel.loading') }}
    </div>
    <div v-else-if="loadError" class="empty" role="alert">
      <div>{{ loadError }}</div>
      <button class="cta-btn" type="button" @click="reloadPresets">
        {{ t('workspace.analysesPanel.reload') }}
      </button>
    </div>
    <div v-else-if="!presets.length && !monitorJobs.length" class="empty" role="status" aria-live="polite">
      {{ t('workspace.analysesPanel.empty') }}
    </div>
    <div v-else-if="!presets.length && monitorJobs.length" class="empty" role="status" aria-live="polite">
      {{ t('workspace.analysesPanel.emptyWithJobs') }}
    </div>
    <div v-else-if="!hasFilteredPresets" class="empty" role="status" aria-live="polite">
      <span v-if="searchQuery">{{ t('workspace.shared.noMatchesFor', { query: searchQuery }) }}</span>
      <span v-else>{{ t('workspace.shared.noMatchesFilter') }}</span>
      <span v-if="activeFilterLabel" class="empty-hint" :title="activeFilterLabel">
        {{ activeFilterLabel }}
      </span>
      <button
        class="cta-btn"
        type="button"
        :title="t('workspace.shared.resetFilters')"
        :aria-label="t('workspace.shared.resetFilters')"
        @click="resetFilters"
      >
        {{ t('workspace.shared.resetFilters') }}
      </button>
    </div>
    <div v-else>
      <div v-if="showRecent && recentPresets.length" class="section">
        <div class="section-title">{{ t('workspace.analysesPanel.recent') }}</div>
        <div class="list">
          <div v-for="preset in recentPresets" :key="preset.id" class="card">
            <div class="card-head">
              <div class="title" :title="preset.name">{{ preset.name }}</div>
              <div class="actions">
                <button
                  v-if="canCancelPreset(preset)"
                  class="icon-btn warning"
                  :disabled="isCancelling(preset)"
                  :title="isCancelling(preset) ? t('workspace.analysesPanel.cancelRunning') : cancelAnalysisJobBlockReason ?? t('workspace.analysesPanel.cancelAnalysis')"
                  :aria-label="isCancelling(preset) ? t('workspace.analysesPanel.cancelRunning') : cancelAnalysisJobBlockReason ?? t('workspace.analysesPanel.cancelAnalysis')"
                  @click="cancelPreset(preset)"
                >
                  <Loader2 v-if="isCancelling(preset)" class="w-4 h-4 animate-spin" />
                  <Ban v-else class="w-4 h-4" />
                </button>
                <button
                  class="icon-btn"
                  :title="t('workspace.analysesPanel.open')"
                  :aria-label="t('workspace.analysesPanel.open')"
                  :disabled="isCancelling(preset)"
                  @click="applyPreset(preset)"
                >
                  <Play class="w-4 h-4" />
                </button>
                <button
                  class="icon-btn danger"
                  :title="!canDeletePresets ? deletePresetBlockReason ?? t('workspace.analysesPanel.deleteNotEnabled') : t('workspace.analysesPanel.delete')"
                  :aria-label="!canDeletePresets ? deletePresetBlockReason ?? t('workspace.analysesPanel.deleteNotEnabled') : t('workspace.analysesPanel.delete')"
                  :disabled="isCancelling(preset) || !canDeletePresets"
                  @click="removePreset(preset)"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>
            </div>
            <div class="meta">
              <span class="chip chip-primary" :title="labelForType(preset.type)">
                {{ labelForType(preset.type) }}
              </span>
              <span class="chip" :title="preset.docset ? t('workspace.shared.subcorpus') : t('workspace.shared.wholeCorpus')">
                {{ preset.docset ? t('workspace.shared.subcorpus') : t('workspace.shared.wholeCorpus') }}
              </span>
              <span class="chip" :title="t('workspace.shared.corpus', { corpus: preset.corpus })">{{ t('workspace.shared.corpus', { corpus: preset.corpus }) }}</span>
              <span v-if="preset.queryTerm" class="chip" :title="t('workspace.shared.query', { query: preset.queryTerm })">
                {{ t('workspace.shared.query', { query: preset.queryTerm }) }}
              </span>
              <span
                v-if="labelForStatus(preset.status)"
                class="chip"
                :class="statusClass(preset.status)"
              >
                {{ labelForStatus(preset.status) }}
              </span>
              <span
                v-if="cacheLabel(preset)"
                class="chip"
                :class="cacheClass(preset)"
                :title="cacheTitle(preset)"
              >
                {{ cacheLabel(preset) }}
              </span>
            </div>
            <div class="scope-summary">
              {{ scopeSummary(preset) }}
            </div>
            <div class="card-foot">
              <div class="foot">
                <div class="foot-row">
                  <span class="foot-label">{{ t('workspace.analysesPanel.created') }}</span>
                  <span>{{ formatDate(preset.createdAt) }}</span>
                </div>
                <div v-if="preset.updatedAt" class="foot-row">
                  <span class="foot-label">{{ t('workspace.analysesPanel.modified') }}</span>
                  <span>{{ formatDate(preset.updatedAt) }}</span>
                </div>
                <div v-if="preset.lastAccessedAt" class="foot-row">
                  <span class="foot-label">{{ t('workspace.analysesPanel.lastOpened') }}</span>
                  <span>{{ formatDate(preset.lastAccessedAt) }}</span>
                </div>
              </div>
              <button class="cta-btn" type="button" @click="applyPreset(preset)">
                {{ t('workspace.analysesPanel.restore') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="remainingPresets.length" class="section">
        <div v-if="showRecent" class="section-title">{{ t('workspace.analysesPanel.all') }}</div>
        <div class="list">
          <div v-for="preset in remainingPresets" :key="preset.id" class="card">
            <div class="card-head">
              <div class="title" :title="preset.name">{{ preset.name }}</div>
              <div class="actions">
                <button
                  v-if="canCancelPreset(preset)"
                  class="icon-btn warning"
                  :disabled="isCancelling(preset)"
                  :title="isCancelling(preset) ? t('workspace.analysesPanel.cancelRunning') : t('workspace.analysesPanel.cancelAnalysis')"
                  :aria-label="isCancelling(preset) ? t('workspace.analysesPanel.cancelRunning') : t('workspace.analysesPanel.cancelAnalysis')"
                  @click="cancelPreset(preset)"
                >
                  <Loader2 v-if="isCancelling(preset)" class="w-4 h-4 animate-spin" />
                  <Ban v-else class="w-4 h-4" />
                </button>
                <button
                  class="icon-btn"
                  :title="t('workspace.analysesPanel.open')"
                  :aria-label="t('workspace.analysesPanel.open')"
                  :disabled="isCancelling(preset)"
                  @click="applyPreset(preset)"
                >
                  <Play class="w-4 h-4" />
                </button>
                <button
                  class="icon-btn danger"
                  :title="!canDeletePresets ? deletePresetBlockReason ?? t('workspace.analysesPanel.deleteNotEnabled') : t('workspace.analysesPanel.delete')"
                  :aria-label="!canDeletePresets ? deletePresetBlockReason ?? t('workspace.analysesPanel.deleteNotEnabled') : t('workspace.analysesPanel.delete')"
                  :disabled="isCancelling(preset) || !canDeletePresets"
                  @click="removePreset(preset)"
                >
                  <Trash2 class="w-4 h-4" />
                </button>
              </div>
            </div>
            <div class="meta">
              <span class="chip chip-primary" :title="labelForType(preset.type)">
                {{ labelForType(preset.type) }}
              </span>
              <span class="chip" :title="preset.docset ? t('workspace.shared.subcorpus') : t('workspace.shared.wholeCorpus')">
                {{ preset.docset ? t('workspace.shared.subcorpus') : t('workspace.shared.wholeCorpus') }}
              </span>
              <span class="chip" :title="t('workspace.shared.corpus', { corpus: preset.corpus })">{{ t('workspace.shared.corpus', { corpus: preset.corpus }) }}</span>
              <span v-if="preset.queryTerm" class="chip" :title="t('workspace.shared.query', { query: preset.queryTerm })">
                {{ t('workspace.shared.query', { query: preset.queryTerm }) }}
              </span>
              <span
                v-if="labelForStatus(preset.status)"
                class="chip"
                :class="statusClass(preset.status)"
              >
                {{ labelForStatus(preset.status) }}
              </span>
              <span
                v-if="cacheLabel(preset)"
                class="chip"
                :class="cacheClass(preset)"
                :title="cacheTitle(preset)"
              >
                {{ cacheLabel(preset) }}
              </span>
            </div>
            <div class="scope-summary">
              {{ scopeSummary(preset) }}
            </div>
            <div class="card-foot">
              <div class="foot">
                <div class="foot-row">
                  <span class="foot-label">{{ t('workspace.analysesPanel.created') }}</span>
                  <span>{{ formatDate(preset.createdAt) }}</span>
                </div>
                <div v-if="preset.updatedAt" class="foot-row">
                  <span class="foot-label">{{ t('workspace.analysesPanel.modified') }}</span>
                  <span>{{ formatDate(preset.updatedAt) }}</span>
                </div>
                <div v-if="preset.lastAccessedAt" class="foot-row">
                  <span class="foot-label">{{ t('workspace.analysesPanel.lastOpened') }}</span>
                  <span>{{ formatDate(preset.lastAccessedAt) }}</span>
                </div>
              </div>
              <button class="cta-btn" type="button" @click="applyPreset(preset)">
                {{ t('workspace.analysesPanel.restore') }}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div v-if="!recentPresets.length && !remainingPresets.length" class="empty">
        <span>{{ t('workspace.shared.noMatchesFilter') }}</span>
        <button v-if="hasActiveFilters" class="cta-btn" type="button" @click="resetFilters">
          {{ t('workspace.shared.resetFilters') }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.library-body {
  @apply flex flex-col gap-3;
}

.section {
  @apply flex flex-col gap-2;
}

.section-title {
  @apply text-xs font-semibold uppercase tracking-wide;
  @apply text-neutral-500 dark:text-neutral-400;
}

.job-monitor {
  @apply rounded-2xl border border-primary-200/70 dark:border-primary-800/70;
  @apply bg-primary-50/70 dark:bg-primary-900/20;
  @apply p-3 space-y-3;
}

.job-monitor-head {
  @apply flex items-start justify-between gap-3;
}

.job-monitor-counts {
  @apply flex flex-wrap justify-end gap-1;
}

.job-monitor-copy {
  @apply mt-1 text-xs text-neutral-600 dark:text-neutral-300;
  @apply max-w-2xl;
}

.job-lookup {
  @apply flex flex-col gap-2;
  @apply sm:flex-row sm:items-center;
}

.job-lookup-input {
  @apply flex-1 px-3 py-2 rounded-lg text-xs;
  @apply bg-white/80 dark:bg-neutral-950/70;
  @apply border border-primary-200/70 dark:border-primary-800/70;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.job-lookup-input:disabled {
  @apply opacity-60 cursor-not-allowed;
}

.job-monitor-list {
  @apply grid gap-2;
}

.job-monitor-empty {
  @apply rounded-xl border border-dashed border-primary-200/80 dark:border-primary-800/70;
  @apply bg-white/70 dark:bg-neutral-950/50;
  @apply p-3 text-xs text-neutral-600 dark:text-neutral-300;
}

.job-monitor-empty strong {
  @apply block text-sm text-neutral-800 dark:text-neutral-100;
}

.job-monitor-empty span {
  @apply mt-1 block;
}

.job-operation-focus {
  @apply rounded-xl border border-amber-300 bg-amber-50 px-3 py-2;
  @apply text-xs text-amber-900;
  @apply dark:border-amber-700/70 dark:bg-amber-950/30 dark:text-amber-100;
}

.job-operation-focus strong {
  @apply block text-sm;
}

.job-operation-focus span {
  @apply mt-1 block;
}

.job-operation-focus code {
  @apply mt-1 inline-block rounded bg-white/70 px-1.5 py-0.5 text-[11px];
  @apply text-amber-800 dark:bg-neutral-950/60 dark:text-amber-200;
}

.job-monitor-card {
  @apply rounded-xl border border-white/70 dark:border-neutral-800;
  @apply bg-white/80 dark:bg-neutral-950/70;
  @apply p-3 space-y-2;
}

.job-monitor-card-focused {
  @apply border-amber-300 ring-2 ring-amber-300/60;
  @apply dark:border-amber-700 dark:ring-amber-500/30;
}

.job-monitor-card-terminal {
  @apply border-neutral-200/80 dark:border-neutral-800;
  @apply bg-white/70 dark:bg-neutral-950/50;
}

.job-monitor-card-head {
  @apply flex flex-col gap-3;
  @apply sm:flex-row sm:items-center sm:justify-between;
}

.job-monitor-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.job-monitor-subtitle {
  @apply mt-1 text-[11px] text-neutral-500 dark:text-neutral-400;
  @apply break-all;
}

.job-monitor-meta {
  @apply flex flex-wrap gap-1;
}

.chip-operation-focus {
  @apply bg-amber-100 text-amber-800 border-amber-200;
  @apply dark:bg-amber-900/30 dark:text-amber-200 dark:border-amber-800/70;
}

.job-monitor-actions {
  @apply flex flex-wrap gap-2;
}

.job-action-btn {
  @apply inline-flex items-center justify-center gap-1.5;
  @apply px-2.5 py-1.5 rounded-full text-xs font-medium;
  @apply bg-primary-600 text-white;
  @apply hover:bg-primary-700;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
  @apply transition-colors;
}

.job-action-btn.subtle {
  @apply bg-white text-neutral-700 border border-neutral-200;
  @apply hover:bg-neutral-100;
  @apply dark:bg-neutral-900 dark:text-neutral-200 dark:border-neutral-700 dark:hover:bg-neutral-800;
}

.job-action-btn:disabled {
  @apply opacity-50 cursor-not-allowed;
}

.job-result-warning {
  @apply rounded-lg border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800;
  @apply dark:border-warning-900/50 dark:bg-warning-900/20 dark:text-warning-200;
}

.job-row-preview {
  @apply rounded-lg border border-neutral-200/80 dark:border-neutral-800;
  @apply bg-neutral-50/80 dark:bg-neutral-950/70;
  @apply p-2 space-y-2;
}

.job-row-preview-title {
  @apply text-[11px] font-semibold text-neutral-500 dark:text-neutral-400;
}

.job-row-evidence {
  @apply flex flex-wrap gap-1;
}

.job-row-preview-list {
  @apply flex flex-col gap-1.5;
}

.job-row-preview-item {
  @apply flex flex-wrap gap-1;
}

.toolbar {
  @apply flex flex-col gap-3;
  @apply sm:flex-row sm:flex-wrap sm:items-center sm:justify-between;
}

/* Keep the search field readable when filter chips and counters share the row. */
.toolbar-search {
  @apply flex-1 sm:min-w-[16rem];
}

.search-field {
  @apply relative;
}

.search-input {
  @apply w-full px-3 py-2 rounded-lg text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
  @apply pr-9;
}

.search-clear {
  @apply absolute right-2 top-1/2 -translate-y-1/2;
  @apply p-1 rounded-md;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
}

.toolbar-filters {
  @apply flex flex-wrap items-center gap-2;
}

.filter-label {
  @apply text-[10px] uppercase tracking-wide font-semibold;
  @apply text-neutral-400 dark:text-neutral-500;
}

.toolbar-meta {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  @apply sm:self-end;
  @apply flex flex-col gap-1;
  @apply text-right;
}

.toolbar-meta-secondary {
  @apply text-[11px] text-neutral-400 dark:text-neutral-500;
}

.filter-reset {
  @apply text-[11px] text-primary-600 dark:text-primary-300;
  @apply hover:underline self-end;
}

.filter-btn {
  @apply px-2.5 py-1 rounded-full text-xs font-medium;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
  @apply transition-colors;
}

.filter-btn:disabled {
  @apply opacity-60 cursor-not-allowed;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.filter-btn.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.list {
  @apply flex flex-col gap-3;
}

.card {
  @apply rounded-xl border border-neutral-200/80 dark:border-neutral-700/80;
  @apply bg-white dark:bg-neutral-900;
  @apply p-3 space-y-2;
  @apply transition-shadow;
  @apply hover:shadow-sm;
}

.card-head {
  @apply flex items-center justify-between gap-2;
}

.title {
  @apply text-[15px] font-semibold text-neutral-800 dark:text-neutral-100;
  @apply leading-snug;
}

.actions {
  @apply flex items-center gap-1;
}

.icon-btn {
  @apply p-1.5 rounded-md;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500/40;
}

.icon-btn:disabled {
  @apply opacity-50 cursor-not-allowed;
}

.icon-btn.warning {
  @apply text-amber-600 dark:text-amber-400;
}

.icon-btn.danger {
  @apply text-error-600 dark:text-error-400;
}

.meta {
  @apply flex flex-wrap gap-1;
}

.scope-summary {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
  @apply line-clamp-2;
}

.card-foot {
  @apply flex items-end justify-between gap-3;
}

.cta-btn {
  @apply px-3 py-1.5 rounded-full text-xs font-medium;
  @apply bg-primary-600 text-white;
  @apply hover:bg-primary-700;
  @apply transition-colors;
}

.chip {
  @apply px-2 py-0.5 rounded-full text-[10px] font-medium;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply border border-transparent;
  @apply max-w-[240px] truncate;
}

.chip-primary {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.chip-status-running {
  @apply bg-amber-100 text-amber-800;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.chip-status-done {
  @apply bg-emerald-100 text-emerald-800;
  @apply dark:bg-emerald-900/40 dark:text-emerald-200;
}

.chip-status-error {
  @apply bg-rose-100 text-rose-800;
  @apply dark:bg-rose-900/40 dark:text-rose-200;
}

.chip-status-idle {
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.chip-cache-ok {
  @apply bg-emerald-100 text-emerald-800;
  @apply dark:bg-emerald-900/40 dark:text-emerald-200;
}

.chip-cache-warn {
  @apply bg-amber-100 text-amber-800;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.chip-cache-unknown {
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.foot {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  @apply flex flex-col gap-1;
}

.foot-row {
  @apply flex items-center gap-2;
}

.foot-label {
  @apply text-[10px] uppercase tracking-wide text-neutral-400 dark:text-neutral-500;
}

.empty {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
  @apply flex flex-col gap-2;
}

.empty-hint {
  @apply text-[11px] text-neutral-400 dark:text-neutral-500;
}
</style>
