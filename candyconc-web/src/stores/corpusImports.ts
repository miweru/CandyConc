/**
 * Corpus Imports Store
 *
 * UI-facing state for backend-owned, observable corpus import jobs. This store
 * deliberately models the real backend contract (`method`, `input_path`,
 * `target_name`) instead of pretending that browser file inputs are local server
 * files.
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  cancelCorpusImportJob,
  createCorpusImportJob,
  getCorpusImportJob,
  getCorpusImportMethods,
  getCorpusImportReports,
  listCorpusImportJobs,
  preflightCorpusImport,
  type CorpusImportJob as ApiCorpusImportJob,
  type CorpusImportMethod,
  type CorpusImportPreflightResponse,
  type CorpusImportReportsResponse,
  type CreateCorpusImportJobPayload,
} from '@/api/client'
import { useCorpusCapabilitiesStore } from './corpusCapabilities'
import { useProductCapabilitiesStore } from './productCapabilities'
import type { ProductOperationAccessOptions } from './productCapabilities'
import { t } from '@/i18n'

export type CorpusImportJobStatus = 'queued' | 'running' | 'done' | 'error' | 'cancelled' | string

export interface CorpusImportDraft {
  method: string
  inputPath: string
  targetName: string
  activateOnSuccess: boolean
  options: Record<string, unknown>
}

export interface StartCorpusImportInput {
  method?: string
  inputPath?: string
  input?: string
  path?: string
  serverPath?: string
  targetName?: string
  target?: string
  corpusName?: string
  activateOnSuccess?: boolean
  activate?: boolean
  options?: Record<string, unknown>
  [key: string]: unknown
}

export type StartServerPathImportInput = StartCorpusImportInput
export type CorpusImportJob = ApiCorpusImportJob
export type CorpusImportReport = CorpusImportReportsResponse
export type CorpusImportPreflight = CorpusImportPreflightResponse

const DEFAULT_DRAFT: CorpusImportDraft = {
  method: '',
  inputPath: '',
  targetName: '',
  activateOnSuccess: false,
  options: {},
}

export const CORPUS_IMPORT_OPERATIONS = {
  methods: 'corpus.import.methods',
  preflight: 'corpus.import.preflight',
  jobsList: 'corpus.import.jobs_list',
  start: 'corpus.import.start',
  jobStatus: 'corpus.import.job_status',
  jobCancel: 'corpus.import.job_cancel',
  jobReports: 'corpus.import.job_reports',
  buildReport: 'corpus.import.build_report',
} as const

const TERMINAL_STATUSES = new Set(['done', 'error', 'cancelled', 'failed', 'succeeded'])
const DEFAULT_POLL_INTERVAL_MS = 3000
const RETAINED_JOB_LIMIT = 128

function normalizeStatus(status: unknown): string {
  const value = String(status || 'queued').toLowerCase()
  if (value === 'succeeded' || value === 'completed') return 'done'
  if (value === 'failed') return 'error'
  return value
}

function isDoneStatus(status: unknown): boolean {
  return normalizeStatus(status) === 'done'
}

function isTerminal(status: unknown): boolean {
  return TERMINAL_STATUSES.has(normalizeStatus(status))
}

function normalizeProgress(value: unknown, status: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.max(0, Math.min(100, value))
  }
  return isDoneStatus(status) ? 100 : 0
}

function mergeJob(existing: ApiCorpusImportJob | undefined, incoming: ApiCorpusImportJob): ApiCorpusImportJob {
  const status = normalizeStatus(incoming.status)
  return {
    ...existing,
    ...incoming,
    status,
    progress: Math.max(existing?.progress ?? 0, normalizeProgress(incoming.progress, status)),
  }
}

function reportsFromSnapshot(job: ApiCorpusImportJob): CorpusImportReportsResponse['reports'] | null {
  const reports = (job as { reports?: unknown }).reports
  return reports && typeof reports === 'object' && !Array.isArray(reports)
    ? reports as CorpusImportReportsResponse['reports']
    : null
}

function payloadFromInput(input: StartCorpusImportInput): CreateCorpusImportJobPayload {
  const method = String(input.method || input.importMode || DEFAULT_DRAFT.method)
  const inputPath = String(input.inputPath || input.serverPath || input.sourcePath || input.input_path || input.input || input.path || '')
  const targetName = String(input.targetName || input.corpusName || input.corpus || input.target_name || input.target || '')
  const activateOnSuccess = Boolean(input.activateOnSuccess ?? input.activate ?? input.activate_on_success ?? false)
  const reservedKeys = new Set([
    'method',
    'importMode',
    'inputPath',
    'serverPath',
    'sourcePath',
    'input_path',
    'input',
    'path',
    'targetName',
    'corpusName',
    'corpus',
    'target_name',
    'target',
    'target_path',
    'targetPath',
    'staging_path',
    'stagingPath',
    'activateOnSuccess',
    'activate',
    'activate_on_success',
    'options',
  ])
  const topLevelOptions = Object.fromEntries(
    Object.entries(input).filter(([key, value]) => !reservedKeys.has(key) && value !== undefined)
  )
  const nestedOptions = input.options && typeof input.options === 'object'
    ? input.options as Record<string, unknown>
    : {}
  const options = { ...topLevelOptions, ...nestedOptions }
  return {
    ...options,
    method,
    input_path: inputPath,
    target_name: targetName,
    activate_on_success: activateOnSuccess,
  }
}

function stableStringify(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`
  if (value && typeof value === 'object') {
    return `{${Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => `${JSON.stringify(key)}:${stableStringify(item)}`)
      .join(',')}}`
  }
  return JSON.stringify(value) ?? 'null'
}

function payloadKey(input: StartCorpusImportInput): string {
  return stableStringify(payloadFromInput(input))
}

export function preflightBlocksImport(result: CorpusImportPreflightResponse): boolean {
  return result.blocking || result.ok === false || result.status === 'error'
}

function errorMessage(err: unknown, fallback: string): string {
  return err instanceof Error && err.message ? err.message : fallback
}

export const useCorpusImportsStore = defineStore('corpusImports', () => {
  const corpusCapabilities = useCorpusCapabilitiesStore()
  const productCapabilities = useProductCapabilitiesStore()
  let pollTimer: ReturnType<typeof setInterval> | null = null
  let pollInFlight: Promise<void> | null = null

  const draft = ref<CorpusImportDraft>({ ...DEFAULT_DRAFT })
  const jobs = ref<Record<string, ApiCorpusImportJob>>({})
  const activeJobId = ref<string | null>(null)
  const recentJobIds = ref<string[]>([])
  const reportsByJobId = ref<Record<string, CorpusImportReportsResponse['reports']>>({})
  const canonicalReportJobIds = ref<string[]>([])
  const reportErrorByJobId = ref<Record<string, string>>({})
  const reportLoadingJobIds = ref<string[]>([])
  const terminalCatalogRefreshJobIds = ref<string[]>([])
  const preflightResult = ref<CorpusImportPreflightResponse | null>(null)
  const preflightPayloadKey = ref<string | null>(null)
  const methods = ref<CorpusImportMethod[]>([])
  const cancellingJobIds = ref<string[]>([])
  const error = ref<string | null>(null)
  const methodError = ref<string | null>(null)
  const preflightError = ref<string | null>(null)
  const isStarting = ref(false)
  const isPreflighting = ref(false)
  const isLoadingMethods = ref(false)
  const isLoadingJobs = ref(false)
  const isPolling = ref(false)

  const activeJob = computed(() => activeJobId.value ? jobs.value[activeJobId.value] ?? null : null)
  const recentJobs = computed<ApiCorpusImportJob[]>(() =>
    recentJobIds.value
      .map((id) => jobs.value[id])
      .filter((job): job is ApiCorpusImportJob => Boolean(job))
  )
  const methodOptions = computed<CorpusImportMethod[]>(() =>
    methods.value
  )
  const hasRunningJobs = computed(() => Object.values(jobs.value).some((job) => !isTerminal(job.status)))
  const importMethodsAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.methods)
  )
  const importPreflightAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.preflight)
  )
  const importStartAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.start)
  )
  const importListAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.jobsList)
  )
  const importRefreshAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.jobStatus)
  )
  const importCancelAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.jobCancel)
  )
  const importReportsAvailability = computed(() =>
    productCapabilities.productOperationAvailability(CORPUS_IMPORT_OPERATIONS.jobReports)
  )
  const catalogueRefreshAvailability = computed(() =>
    productCapabilities.productOperationAvailability('corpus.catalogue.list')
  )
  const canLoadMethods = computed(() => importMethodsAvailability.value.enabled)
  const canRunPreflight = computed(() => importPreflightAvailability.value.enabled)
  const canStartImports = computed(() => importStartAvailability.value.enabled)
  const canListJobs = computed(() => importListAvailability.value.enabled)
  const canRefreshJobs = computed(() => importRefreshAvailability.value.enabled)
  const canCancelJobs = computed(() => importCancelAvailability.value.enabled)
  const canLoadReports = computed(() => importReportsAvailability.value.enabled)
  const canRefreshCatalogue = computed(() => catalogueRefreshAvailability.value.enabled)

  function deniedError(reason: string | null, fallback: string): Error {
    return new Error(reason ?? fallback)
  }

  function importMethodById(methodId: string): CorpusImportMethod | null {
    return methods.value.find((item) => item.method === methodId) ?? null
  }

  function importMethodWorkflowStatus(item: CorpusImportMethod): string {
    return String(item.ui_workflow?.status ?? 'first_class').toLowerCase()
  }

  function importMethodIsFirstClass(item: CorpusImportMethod): boolean {
    return importMethodWorkflowStatus(item) === 'first_class'
  }

  function importMethodWorkflowLabel(item: CorpusImportMethod): string {
    const explicit = item.ui_workflow?.label?.trim()
    if (explicit) return explicit
    return importMethodIsFirstClass(item) ? t('corpus.manager.workflowFirstClass') : t('corpus.manager.workflowExpert')
  }

  function nonFirstClassImportError(item: CorpusImportMethod): Error {
    const label = item.label || item.method
    const workflow = importMethodWorkflowLabel(item)
    const reason = item.ui_workflow?.reason?.trim()
    const message = t('corpus.imports.notFirstClass', { label, workflow })
    return new Error(reason ? `${message} ${reason}` : message)
  }

  async function assertImportOperation(
    operationId: string,
    fallbackLabel: string,
    options: ProductOperationAccessOptions = {},
  ): Promise<void> {
    await productCapabilities.assertProductOperationAccess(operationId, fallbackLabel, options)
  }

  function remember(jobId: string) {
    recentJobIds.value = [jobId, ...recentJobIds.value.filter((id) => id !== jobId)].slice(0, RETAINED_JOB_LIMIT)
  }

  function clearVisibleJobState(): void {
    stopPolling()
    jobs.value = {}
    activeJobId.value = null
    recentJobIds.value = []
    reportsByJobId.value = {}
    canonicalReportJobIds.value = []
    reportErrorByJobId.value = {}
    reportLoadingJobIds.value = []
    cancellingJobIds.value = []
  }

  function applyProgress(snapshot: ApiCorpusImportJob): ApiCorpusImportJob {
    const existing = jobs.value[snapshot.job_id]
    const merged = mergeJob(existing, snapshot)
    jobs.value = { ...jobs.value, [merged.job_id]: merged }
    const snapshotReports = reportsFromSnapshot(snapshot)
    if (snapshotReports) {
      if (!canonicalReportJobIds.value.includes(merged.job_id)) {
        reportsByJobId.value = { ...reportsByJobId.value, [merged.job_id]: snapshotReports }
        reportErrorByJobId.value = { ...reportErrorByJobId.value, [merged.job_id]: '' }
      }
    }
    remember(merged.job_id)
    if (!activeJobId.value || !isTerminal(merged.status)) {
      activeJobId.value = merged.job_id
    }
    return merged
  }

  async function loadTerminalReports(job: ApiCorpusImportJob): Promise<void> {
    if (!isTerminal(job.status) || canonicalReportJobIds.value.includes(job.job_id)) return
    try {
      await loadReports(job.job_id)
    } catch {
      // loadReports records the per-job error. Polling must keep other jobs alive.
    }
  }

  async function refreshCatalogueForDoneJob(job: ApiCorpusImportJob): Promise<void> {
    if (!isDoneStatus(job.status) || terminalCatalogRefreshJobIds.value.includes(job.job_id)) return
    if (!canRefreshCatalogue.value) return
    terminalCatalogRefreshJobIds.value = [...terminalCatalogRefreshJobIds.value, job.job_id]
    await corpusCapabilities.fetchCorpora()
    const targetName = String(job.target_name || (job as { corpus?: unknown }).corpus || '').trim()
    if (targetName && corpusCapabilities.corpora.find((corpus) => corpus.name === targetName)?.active) {
      await corpusCapabilities.syncBackendActiveCorpus(targetName)
    }
  }

  async function reconcileActivatedImport(job: ApiCorpusImportJob, targetName: string): Promise<void> {
    if (!targetName) {
      await corpusCapabilities.syncBackendActiveCorpus()
      return
    }
    const synced = await corpusCapabilities.syncBackendActiveCorpus(targetName)
    if (synced || job.activation_skipped_reason) return
    await corpusCapabilities.setActive(targetName)
  }

  async function loadTerminalArtifacts(job: ApiCorpusImportJob): Promise<void> {
    if (!isTerminal(job.status)) return
    const targetName = String(job.target_name || (job as { corpus?: unknown }).corpus || '').trim()
    const catalogueTask = isDoneStatus(job.status) && job.activate_on_success
      ? reconcileActivatedImport(job, targetName)
      : refreshCatalogueForDoneJob(job)
    await Promise.allSettled([
      catalogueTask,
      loadTerminalReports(job),
    ])
  }

  async function startImport(input: StartCorpusImportInput): Promise<ApiCorpusImportJob> {
    const payload = payloadFromInput(input)
    const key = stableStringify(payload)
    draft.value = {
      method: payload.method,
      inputPath: payload.input_path,
      targetName: payload.target_name ?? '',
      activateOnSuccess: Boolean(payload.activate_on_success),
      options: input.options && typeof input.options === 'object' ? input.options as Record<string, unknown> : {},
    }
    const methodContract = importMethodById(payload.method)
    if (methodContract && !importMethodIsFirstClass(methodContract)) {
      const err = nonFirstClassImportError(methodContract)
      error.value = err.message
      isStarting.value = false
      throw err
    }
    if (!preflightResult.value) {
      const err = new Error(t('corpus.imports.preflightMissingRun'))
      error.value = err.message
      isStarting.value = false
      throw err
    }
    if (preflightPayloadKey.value !== key) {
      const err = new Error(t('corpus.imports.preflightStaleRecheck'))
      error.value = err.message
      isStarting.value = false
      throw err
    }
    if (preflightBlocksImport(preflightResult.value)) {
      const err = new Error(t('corpus.imports.preflightBlocks'))
      error.value = err.message
      isStarting.value = false
      throw err
    }
    try {
      await assertImportOperation(CORPUS_IMPORT_OPERATIONS.start, t('corpus.imports.labelImport'))
    } catch (accessError) {
      const err = deniedError(accessError instanceof Error ? accessError.message : importStartAvailability.value.disabledReason, t('corpus.imports.importNotEnabled'))
      error.value = err.message
      throw err
    }
    isStarting.value = true
    error.value = null
    try {
      const job = applyProgress(await createCorpusImportJob(payload))
      activeJobId.value = job.job_id
      if (!isTerminal(job.status)) startPolling()
      else await loadTerminalArtifacts(job)
      return job
    } catch (err) {
      error.value = errorMessage(err, t('corpus.imports.startFailed'))
      throw err
    } finally {
      isStarting.value = false
    }
  }

  async function startServerPathImport(input: StartServerPathImportInput): Promise<ApiCorpusImportJob> {
    return startImport(input)
  }

  async function loadMethods(): Promise<CorpusImportMethod[]> {
    try {
      await assertImportOperation(CORPUS_IMPORT_OPERATIONS.methods, t('corpus.imports.labelMethods'))
    } catch (accessError) {
      methodError.value = accessError instanceof Error ? accessError.message : importMethodsAvailability.value.disabledReason ?? t('corpus.imports.methodsNotEnabled')
      methods.value = []
      return []
    }
    isLoadingMethods.value = true
    methodError.value = null
    try {
      const next = await getCorpusImportMethods()
      methods.value = next
      return next
    } catch (err) {
      methodError.value = errorMessage(
        err,
        t('corpus.imports.methodsLoadFailed')
      )
      methods.value = []
      return []
    } finally {
      isLoadingMethods.value = false
    }
  }

  async function loadJobs(): Promise<ApiCorpusImportJob[]> {
    try {
      await assertImportOperation(CORPUS_IMPORT_OPERATIONS.jobsList, t('corpus.imports.labelJobs'))
    } catch (err) {
      error.value = err instanceof Error ? err.message : importListAvailability.value.disabledReason ?? t('corpus.imports.jobsNotEnabled')
      clearVisibleJobState()
      return []
    }
    isLoadingJobs.value = true
    error.value = null
    try {
      const snapshots = await listCorpusImportJobs()
      const terminalArtifactTasks: Promise<void>[] = []
      for (const snapshot of snapshots) {
        const job = applyProgress(snapshot)
        if (isTerminal(job.status)) {
          terminalArtifactTasks.push(loadTerminalArtifacts(job))
        }
      }
      await Promise.allSettled(terminalArtifactTasks)
      if (hasRunningJobs.value) startPolling()
      return snapshots
    } catch (err) {
      error.value = errorMessage(err, t('corpus.imports.jobsLoadFailed'))
      return []
    } finally {
      isLoadingJobs.value = false
    }
  }

  async function runPreflight(input: StartCorpusImportInput): Promise<CorpusImportPreflightResponse> {
    try {
      await assertImportOperation(CORPUS_IMPORT_OPERATIONS.preflight, t('corpus.imports.labelPreflight'))
    } catch (accessError) {
      const err = deniedError(accessError instanceof Error ? accessError.message : importPreflightAvailability.value.disabledReason, t('corpus.imports.preflightNotEnabled'))
      preflightError.value = err.message
      throw err
    }
    isPreflighting.value = true
    preflightError.value = null
    const payload = payloadFromInput(input)
    const key = stableStringify(payload)
    draft.value = {
      method: payload.method,
      inputPath: payload.input_path,
      targetName: payload.target_name ?? '',
      activateOnSuccess: Boolean(payload.activate_on_success),
      options: input.options && typeof input.options === 'object' ? input.options as Record<string, unknown> : {},
    }
    try {
      const result = await preflightCorpusImport(payload)
      preflightResult.value = result
      preflightPayloadKey.value = key
      return result
    } catch (err) {
      preflightError.value = errorMessage(err, t('corpus.imports.preflightFailed'))
      preflightResult.value = null
      preflightPayloadKey.value = null
      throw err
    } finally {
      isPreflighting.value = false
    }
  }

  async function refreshJob(jobId: string): Promise<ApiCorpusImportJob> {
    try {
      await assertImportOperation(CORPUS_IMPORT_OPERATIONS.jobStatus, t('corpus.imports.labelJobStatus'))
    } catch (accessError) {
      const err = deniedError(accessError instanceof Error ? accessError.message : importRefreshAvailability.value.disabledReason, t('corpus.imports.jobStatusNotEnabled'))
      error.value = err.message
      throw err
    }
    const job = applyProgress(await getCorpusImportJob(jobId))
    await loadTerminalArtifacts(job)
    return job
  }

  async function pollRunningJobs(): Promise<void> {
    if (pollInFlight) return pollInFlight
    pollInFlight = (async () => {
      const runningJobIds = recentJobs.value
        .filter((job) => !isTerminal(job.status))
        .map((job) => job.job_id)
      if (!runningJobIds.length) {
        stopPolling()
        return
      }
      if (!canRefreshJobs.value) {
        error.value = importRefreshAvailability.value.disabledReason ?? t('corpus.imports.jobStatusNotEnabled')
        stopPolling()
        return
      }
      await Promise.allSettled(runningJobIds.map((jobId) => refreshJob(jobId)))
      if (!hasRunningJobs.value) stopPolling()
    })()
    try {
      await pollInFlight
    } finally {
      pollInFlight = null
    }
  }

  function startPolling(intervalMs = DEFAULT_POLL_INTERVAL_MS) {
    if (pollTimer) return
    if (!canRefreshJobs.value) {
      error.value = importRefreshAvailability.value.disabledReason ?? t('corpus.imports.jobStatusNotEnabled')
      isPolling.value = false
      return
    }
    isPolling.value = true
    pollTimer = setInterval(() => {
      void pollRunningJobs()
    }, intervalMs)
    ;(pollTimer as { unref?: () => void }).unref?.()
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
    isPolling.value = false
  }

  async function cancelJob(
    jobId: string,
    options: ProductOperationAccessOptions = {},
  ): Promise<ApiCorpusImportJob> {
    try {
      await assertImportOperation(CORPUS_IMPORT_OPERATIONS.jobCancel, t('corpus.imports.labelCancel'), {
        target: jobId,
        impact: t('corpus.imports.cancelImpact'),
        ...options,
      })
    } catch (accessError) {
      const err = deniedError(accessError instanceof Error ? accessError.message : importCancelAvailability.value.disabledReason, t('corpus.imports.cancelNotEnabled'))
      error.value = err.message
      throw err
    }
    if (!cancellingJobIds.value.includes(jobId)) {
      cancellingJobIds.value = [...cancellingJobIds.value, jobId]
    }
    try {
      const job = applyProgress(await cancelCorpusImportJob(jobId))
      await loadTerminalArtifacts(job)
      return job
    } catch (err) {
      error.value = errorMessage(err, t('corpus.imports.cancelFailed'))
      throw err
    } finally {
      cancellingJobIds.value = cancellingJobIds.value.filter((id) => id !== jobId)
    }
  }

  async function loadReports(jobId: string, force = false): Promise<CorpusImportReportsResponse['reports']> {
    if (!force && canonicalReportJobIds.value.includes(jobId) && reportsByJobId.value[jobId]) {
      return reportsByJobId.value[jobId]
    }
    try {
      await assertImportOperation(CORPUS_IMPORT_OPERATIONS.jobReports, t('corpus.imports.labelReports'))
    } catch (accessError) {
      const err = deniedError(accessError instanceof Error ? accessError.message : importReportsAvailability.value.disabledReason, t('corpus.imports.reportsNotEnabled'))
      reportErrorByJobId.value = { ...reportErrorByJobId.value, [jobId]: err.message }
      throw err
    }
    if (!reportLoadingJobIds.value.includes(jobId)) {
      reportLoadingJobIds.value = [...reportLoadingJobIds.value, jobId]
    }
    reportErrorByJobId.value = { ...reportErrorByJobId.value, [jobId]: '' }
    try {
      const reports = await getCorpusImportReports(jobId)
      reportsByJobId.value = { ...reportsByJobId.value, [jobId]: reports.reports }
      if (!canonicalReportJobIds.value.includes(jobId)) {
        canonicalReportJobIds.value = [...canonicalReportJobIds.value, jobId]
      }
      return reports.reports
    } catch (err) {
      reportErrorByJobId.value = {
        ...reportErrorByJobId.value,
        [jobId]: errorMessage(err, t('corpus.imports.reportsLoadFailed')),
      }
      throw err
    } finally {
      reportLoadingJobIds.value = reportLoadingJobIds.value.filter((id) => id !== jobId)
    }
  }

  function setDraft(patch: Partial<CorpusImportDraft>) {
    draft.value = { ...draft.value, ...patch, options: patch.options ?? draft.value.options }
  }

  function resetDraft() {
    draft.value = { ...DEFAULT_DRAFT, options: {} }
    clearPreflight()
  }

  function clearError() {
    error.value = null
  }

  function clearPreflight() {
    preflightResult.value = null
    preflightPayloadKey.value = null
    preflightError.value = null
  }

  return {
    draft,
    jobs,
    activeJobId,
    activeJob,
    recentJobIds,
    recentJobs,
    reportsByJobId,
    reportErrorByJobId,
    reportLoadingJobIds,
    preflightResult,
    preflightPayloadKey,
    methods,
    methodOptions,
    cancellingJobIds,
    error,
    methodError,
    preflightError,
    isStarting,
    isPreflighting,
    isLoadingMethods,
    isLoadingJobs,
    isPolling,
    hasRunningJobs,
    importMethodsAvailability,
    importPreflightAvailability,
    importStartAvailability,
    importListAvailability,
    importRefreshAvailability,
    importCancelAvailability,
    importReportsAvailability,
    canLoadMethods,
    canRunPreflight,
    canStartImports,
    canListJobs,
    canRefreshJobs,
    canCancelJobs,
    canLoadReports,
    applyProgress,
    startImport,
    startServerPathImport,
    runPreflight,
    payloadKey,
    loadMethods,
    loadJobs,
    refreshJob,
    pollRunningJobs,
    startPolling,
    stopPolling,
    cancelJob,
    loadReports,
    clearVisibleJobState,
    setDraft,
    resetDraft,
    clearError,
    clearPreflight,
  }
})

export const useCorpusImportStore = useCorpusImportsStore
