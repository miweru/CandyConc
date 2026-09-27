import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  cancelAnalysisJob,
  getAnalysisJob,
  getAnalysisJobRows,
  type AnalysisJobRows,
  type AnalysisJobSnapshot,
  type AnalysisJobStart,
} from '@/api/client'
import { withAuthHeadersReady } from '@/api/auth'
import { currentLocale } from '@/i18n/locale'
import { useProductCapabilitiesStore } from './productCapabilities'
import type { ProductOperationAccessOptions } from './productCapabilities'
import {
  useProductOperationRunsStore,
  type ProductOperationRunRecord,
  type ProductOperationRunStatus,
} from './productOperationRuns'
import {
  analysisResultLoadedMessage,
  analysisRowsFromTerminalSnapshot,
  hasUnavailableAnalysisRows,
  analysisJobRowsReadiness,
} from '@/lib/productOperationReadiness'
import { t } from '@/i18n'

const DEFAULT_POLL_MS = 700
// A dev proxy or reverse proxy can leave a WebSocket in CONNECTING forever.
// Polling is the equivalent read path, so never let transport negotiation trap
// a finished analysis behind a permanent "Wartet" state.
const WS_FIRST_SNAPSHOT_TIMEOUT_MS = 2_000
const RECENT_JOB_LIMIT = 40
const RECENT_JOBS_STORAGE_KEY = 'candyconc.analysisJobs.recent.v1'
const ASYNC_JOB_ROUTES = {
  status: '/api/v1/analysis/jobs/{job_id}',
  cancel: '/api/v1/analysis/jobs/{job_id}/cancel',
  rows: '/api/v1/analysis/jobs/{job_id}/rows',
} as const
const ASYNC_JOB_OPERATIONS = {
  status: 'analysis.async_jobs.status',
  cancel: 'analysis.async_jobs.cancel',
  rows: 'analysis.async_jobs.rows',
} as const

export interface AnalysisJobRunOptions {
  scope: string
  kind?: string
  corpus?: string
  signal?: AbortSignal
  rowsOffset?: number
  rowsLimit?: number
  pollMs?: number
  queuedMessage?: string
  productOperation?: AnalysisJobProductOperation
  start: () => Promise<AnalysisJobStart>
  onStarted?: (start: AnalysisJobStart) => void | Promise<void>
  onSnapshot?: (snapshot: AnalysisJobSnapshot) => void | Promise<void>
}

export interface AnalysisJobProductOperation {
  operationId: string
  surfaceId?: string | null
  cancelOperationId?: string | null
  label?: string
  detail?: string | null
}

export interface AnalysisJobResumeOptions {
  scope: string
  jobId: string
  kind?: string
  corpus?: string
  signal?: AbortSignal
  rowsOffset?: number
  rowsLimit?: number
  pollMs?: number
  queuedMessage?: string
  productOperation?: AnalysisJobProductOperation
  onSnapshot?: (snapshot: AnalysisJobSnapshot) => void | Promise<void>
}

export interface AnalysisJobMonitorEntry {
  scope: string | null
  jobId: string
  snapshot: AnalysisJobSnapshot
  active: boolean
}

interface PersistedAnalysisJobs {
  jobIds: string[]
  snapshots: Record<string, AnalysisJobSnapshot>
  scopes: Record<string, string>
}

type AnalysisJobMonitorOptions = Pick<
  AnalysisJobRunOptions,
  'scope' | 'signal' | 'rowsOffset' | 'rowsLimit' | 'pollMs' | 'onSnapshot'
>

interface WsTicketResponse {
  ticket?: unknown
  expires_in?: unknown
}

function makeAbortError(): Error {
  const error = new Error('Aborted')
  error.name = 'AbortError'
  return error
}

function isTerminalStatus(status: string): boolean {
  return status === 'done' || status === 'error' || status === 'cancelled'
}

async function mintAnalysisWsTicket(): Promise<string | null> {
  if (typeof fetch === 'undefined') return null
  try {
    const headers = await withAuthHeadersReady({ Accept: 'application/json' })
    const response = await fetch('/api/v1/ws-ticket', { method: 'POST', headers })
    if (!response.ok) return null
    const payload = await response.json().catch(() => null) as WsTicketResponse | null
    const ticket = typeof payload?.ticket === 'string' ? payload.ticket.trim() : ''
    return ticket || null
  } catch {
    return null
  }
}

function analysisWebSocketUrl(jobId: string, wsPath: string | undefined, ticket: string): string | null {
  if (typeof window === 'undefined' || !window.location?.origin) return null
  const rawPath = wsPath?.trim() || `/api/v1/ws/analysis/${encodeURIComponent(jobId)}`
  try {
    const url = new URL(rawPath, window.location.origin)
    if (url.protocol === 'http:') url.protocol = 'ws:'
    if (url.protocol === 'https:') url.protocol = 'wss:'
    if (url.protocol !== 'ws:' && url.protocol !== 'wss:') return null
    url.searchParams.set('ticket', ticket)
    // A WebSocket upgrade carries the browser's Accept-Language, not the
    // interface language. The server reads this parameter instead.
    url.searchParams.set('lang', currentLocale())
    return url.toString()
  } catch {
    return null
  }
}

function sleepUntilNextPoll(ms: number, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(makeAbortError())
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', abort)
      resolve()
    }, ms)
    const abort = () => {
      clearTimeout(timer)
      reject(makeAbortError())
    }
    signal?.addEventListener('abort', abort, { once: true })
  })
}

function getLocalStorage(): Storage | null {
  if (typeof localStorage !== 'undefined') {
    return localStorage
  }
  if (typeof globalThis !== 'undefined' && 'localStorage' in globalThis && globalThis.localStorage) {
    return globalThis.localStorage
  }
  if (typeof window !== 'undefined' && typeof window.localStorage !== 'undefined') {
    return window.localStorage
  }
  return null
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function normalizePersistedSnapshot(value: unknown): AnalysisJobSnapshot | null {
  if (!isPlainObject(value)) return null
  const jobId = value.job_id
  const status = value.status
  if (typeof jobId !== 'string' || typeof status !== 'string') return null
  return value as unknown as AnalysisJobSnapshot
}

function loadPersistedAnalysisJobs(): PersistedAnalysisJobs {
  const storage = getLocalStorage()
  if (!storage) {
    return { jobIds: [], snapshots: {}, scopes: {} }
  }
  try {
    const raw = storage.getItem(RECENT_JOBS_STORAGE_KEY)
    if (!raw) return { jobIds: [], snapshots: {}, scopes: {} }
    const parsed = JSON.parse(raw)
    if (!isPlainObject(parsed)) return { jobIds: [], snapshots: {}, scopes: {} }
    const jobIds = Array.isArray(parsed.jobIds)
      ? parsed.jobIds.filter((id): id is string => typeof id === 'string' && !!id.trim()).slice(0, RECENT_JOB_LIMIT)
      : []
    const snapshots: Record<string, AnalysisJobSnapshot> = {}
    if (isPlainObject(parsed.snapshots)) {
      for (const [jobId, snapshot] of Object.entries(parsed.snapshots)) {
        if (!jobIds.includes(jobId)) continue
        const normalized = normalizePersistedSnapshot(snapshot)
        if (normalized) snapshots[jobId] = normalized
      }
    }
    const scopes: Record<string, string> = {}
    if (isPlainObject(parsed.scopes)) {
      for (const [jobId, scope] of Object.entries(parsed.scopes)) {
        if (jobIds.includes(jobId) && typeof scope === 'string' && scope.trim()) {
          scopes[jobId] = scope
        }
      }
    }
    return { jobIds, snapshots, scopes }
  } catch {
    return { jobIds: [], snapshots: {}, scopes: {} }
  }
}

function runStatusFromAnalysisSnapshot(snapshot: AnalysisJobSnapshot): ProductOperationRunStatus {
  const status = String(snapshot.status || '').toLowerCase()
  if (status === 'done' || status === 'completed' || status === 'complete') return 'succeeded'
  if (status === 'error' || status === 'failed' || status === 'failure') return 'failed'
  if (status === 'cancelled' || status === 'canceled' || status === 'aborted') return 'cancelled'
  if (status === 'queued' || status === 'pending') return 'queued'
  if (status === 'running' || status === 'processing') return 'running'
  return 'unknown'
}

function snapshotProgress(snapshot: AnalysisJobSnapshot): number | null {
  return typeof snapshot.progress === 'number' && Number.isFinite(snapshot.progress)
    ? Math.max(0, Math.min(100, snapshot.progress))
    : null
}

export const useAnalysisJobsStore = defineStore('analysisJobs', () => {
  const productCapabilities = useProductCapabilitiesStore()
  const operationRuns = useProductOperationRunsStore()
  const persisted = loadPersistedAnalysisJobs()
  const snapshots = ref<Record<string, AnalysisJobSnapshot>>(persisted.snapshots)
  const activeJobIdsByScope = ref<Record<string, string>>({})
  const recentJobIds = ref<string[]>(persisted.jobIds)
  const jobScopes = ref<Record<string, string>>(persisted.scopes)
  function operationAvailability(
    operationId: string,
    _label: string,
    _path: string,
    _method: string,
  ) {
    return productCapabilities.productOperationAvailability(operationId)
  }

  const statusAvailability = computed(() =>
    operationAvailability(
      ASYNC_JOB_OPERATIONS.status,
      t('analysis.jobs.statusLabel'),
      ASYNC_JOB_ROUTES.status,
      'GET',
    )
  )
  const cancelAvailability = computed(() =>
    operationAvailability(
      ASYNC_JOB_OPERATIONS.cancel,
      t('analysis.jobs.cancelLabel'),
      ASYNC_JOB_ROUTES.cancel,
      'POST',
    )
  )
  const rowsAvailability = computed(() =>
    operationAvailability(
      ASYNC_JOB_OPERATIONS.rows,
      t('analysis.jobs.rowsLabel'),
      ASYNC_JOB_ROUTES.rows,
      'GET',
    )
  )
  const canRefreshJobs = computed(() => statusAvailability.value.enabled)
  const canCancelJobs = computed(() => cancelAvailability.value.enabled)
  const canLoadJobRows = computed(() => rowsAvailability.value.enabled)
  const statusDisabledReason = computed(() => statusAvailability.value.disabledReason)
  const cancelDisabledReason = computed(() => cancelAvailability.value.disabledReason)
  const rowsDisabledReason = computed(() => rowsAvailability.value.disabledReason)

  const activeJobs = computed(() =>
    Object.entries(activeJobIdsByScope.value)
      .map(([scope, jobId]) => ({ scope, jobId, snapshot: snapshots.value[jobId] ?? null }))
      .filter((entry) => entry.snapshot),
  )

  const monitorJobs = computed<AnalysisJobMonitorEntry[]>(() => {
    const recentIndex = new Map(recentJobIds.value.map((jobId, index) => [jobId, index]))
    const activeJobIds = new Set(Object.values(activeJobIdsByScope.value))
    const knownIds = [
      ...Object.values(activeJobIdsByScope.value),
      ...recentJobIds.value,
    ]
    const seen = new Set<string>()
    const entries: AnalysisJobMonitorEntry[] = []
    for (const jobId of knownIds) {
      if (seen.has(jobId)) continue
      seen.add(jobId)
      const snapshot = snapshots.value[jobId]
      if (!snapshot) continue
      entries.push({
        scope: scopeForJob(jobId),
        jobId,
        snapshot,
        active: activeJobIds.has(jobId),
      })
    }
    return entries.sort((left, right) => {
      if (left.active !== right.active) return left.active ? -1 : 1
      const leftRunning = isRunningStatus(left.snapshot.status)
      const rightRunning = isRunningStatus(right.snapshot.status)
      if (leftRunning !== rightRunning) return leftRunning ? -1 : 1
      const leftTime = latestSnapshotTime(left.snapshot)
      const rightTime = latestSnapshotTime(right.snapshot)
      if (leftTime !== rightTime) return rightTime - leftTime
      return (recentIndex.get(left.jobId) ?? RECENT_JOB_LIMIT) - (recentIndex.get(right.jobId) ?? RECENT_JOB_LIMIT)
    })
  })

  function persistKnownJobs(): void {
    const storage = getLocalStorage()
    if (!storage) return
    const retainedIds = recentJobIds.value.slice(0, RECENT_JOB_LIMIT)
    const retainedSnapshots: Record<string, AnalysisJobSnapshot> = {}
    const retainedScopes: Record<string, string> = {}
    for (const jobId of retainedIds) {
      if (snapshots.value[jobId]) {
        retainedSnapshots[jobId] = snapshots.value[jobId]
      }
      if (jobScopes.value[jobId]) {
        retainedScopes[jobId] = jobScopes.value[jobId]
      }
    }
    try {
      storage.setItem(
        RECENT_JOBS_STORAGE_KEY,
        JSON.stringify({
          jobIds: retainedIds,
          snapshots: retainedSnapshots,
          scopes: retainedScopes,
        }),
      )
    } catch {
      // Persistence is a convenience layer; the in-memory monitor remains authoritative.
    }
  }

  function rememberJob(jobId: string): void {
    const normalized = jobId.trim()
    if (!normalized) return
    recentJobIds.value = [
      normalized,
      ...recentJobIds.value.filter((id) => id !== normalized),
    ].slice(0, RECENT_JOB_LIMIT)
    persistKnownJobs()
  }

  function isRunningStatus(status: string): boolean {
    return status === 'queued' || status === 'running'
  }

  function latestSnapshotTime(snapshot: AnalysisJobSnapshot): number {
    return snapshot.updated_at ?? snapshot.created_at ?? 0
  }

  function scopeForJob(jobId: string): string | null {
    for (const [scope, activeJobId] of Object.entries(activeJobIdsByScope.value)) {
      if (activeJobId === jobId) return scope
    }
    return jobScopes.value[jobId] ?? null
  }

  function setSnapshot(snapshot: AnalysisJobSnapshot, scope?: string | null): AnalysisJobSnapshot {
    snapshots.value = {
      ...snapshots.value,
      [snapshot.job_id]: snapshot,
    }
    if (scope) {
      jobScopes.value = {
        ...jobScopes.value,
        [snapshot.job_id]: scope,
      }
    }
    rememberJob(snapshot.job_id)
    persistKnownJobs()
    syncProductOperationRunsFromSnapshot(snapshot)
    return snapshot
  }

  function setActive(scope: string, jobId: string): void {
    activeJobIdsByScope.value = {
      ...activeJobIdsByScope.value,
      [scope]: jobId,
    }
    jobScopes.value = {
      ...jobScopes.value,
      [jobId]: scope,
    }
    rememberJob(jobId)
    persistKnownJobs()
  }

  function clearScope(scope: string): void {
    if (!(scope in activeJobIdsByScope.value)) return
    const next = { ...activeJobIdsByScope.value }
    delete next[scope]
    activeJobIdsByScope.value = next
  }

  function activeJobId(scope: string): string | null {
    return activeJobIdsByScope.value[scope] ?? null
  }

  function snapshotFor(jobId: string | null | undefined): AnalysisJobSnapshot | null {
    if (!jobId) return null
    return snapshots.value[jobId] ?? null
  }

  function activeSnapshot(scope: string): AnalysisJobSnapshot | null {
    return snapshotFor(activeJobId(scope))
  }

  async function assertOperation(
    availability: typeof statusAvailability,
    fallback: string,
  ): Promise<void> {
    await productCapabilities.ensureAccessContext()
    if (!availability.value.enabled) {
      throw new Error(availability.value.disabledReason ?? fallback)
    }
  }

  async function assertJobMonitorReady(): Promise<void> {
    await assertOperation(
      statusAvailability,
      t('analysis.jobs.statusNotEnabled'),
    )
    await assertOperation(
      rowsAvailability,
      t('analysis.jobs.rowsNotEnabled'),
    )
  }

  async function refreshJob(jobId: string): Promise<AnalysisJobSnapshot> {
    await assertOperation(
      statusAvailability,
      t('analysis.jobs.statusNotEnabled'),
    )
    return setSnapshot(await getAnalysisJob(jobId), scopeForJob(jobId))
  }

  async function rows<T = unknown>(
    jobId: string,
    offset = 0,
    limit = 200,
  ): Promise<AnalysisJobRows<T>> {
    await assertOperation(
      rowsAvailability,
      t('analysis.jobs.rowsNotEnabled'),
    )
    const response = await getAnalysisJobRows<T>(jobId, offset, limit)
    const existing = snapshotFor(jobId)
    setSnapshot({
      ...(existing ?? { job_id: jobId }),
      status: response.status,
      progress: response.progress ?? existing?.progress,
      message: response.message ?? existing?.message,
      total_rows: response.total_rows ?? response.total ?? existing?.total_rows ?? null,
      error: response.error ?? existing?.error ?? null,
      result_available: response.result_available ?? existing?.result_available,
      result_discarded: response.result_discarded ?? existing?.result_discarded,
      result_discard_reason: response.result_discard_reason ?? existing?.result_discard_reason ?? null,
      result_readiness: response.result_readiness ?? existing?.result_readiness,
      rows_state: response.rows_state ?? existing?.rows_state,
      result_warnings: response.result_warnings ?? existing?.result_warnings,
      result_bytes: response.result_bytes ?? existing?.result_bytes ?? null,
      result_max_bytes: response.result_max_bytes ?? existing?.result_max_bytes ?? null,
    }, scopeForJob(jobId))
    return response
  }

  async function cancelJob(
    jobId: string,
    options: ProductOperationAccessOptions = {},
  ): Promise<AnalysisJobSnapshot> {
    await productCapabilities.assertProductOperationAccess(
      ASYNC_JOB_OPERATIONS.cancel,
      t('analysis.jobs.cancelOperation'),
      {
        target: jobId,
        impact: t('analysis.jobs.cancelImpact'),
        ...options,
      },
    )
    return setSnapshot(await cancelAnalysisJob(jobId))
  }

  async function cancelScope(scope: string): Promise<AnalysisJobSnapshot | null> {
    const jobId = activeJobId(scope)
    if (!jobId) return null
    try {
      return await cancelJob(jobId)
    } finally {
      clearScope(scope)
    }
  }

  function startProductOperationRun(
    options: Pick<AnalysisJobRunOptions, 'productOperation' | 'kind' | 'scope' | 'queuedMessage'>,
    jobId: string,
  ): ProductOperationRunRecord | null {
    const productOperation = options.productOperation
    if (!productOperation?.operationId) return null
    return operationRuns.startRun({
      operationId: productOperation.operationId,
      sourceId: jobId,
      kind: 'analysis',
      surfaceId: productOperation.surfaceId ?? null,
      cancelOperationId: productOperation.cancelOperationId ?? ASYNC_JOB_OPERATIONS.cancel,
      label: productOperation.label ?? options.kind ?? t('analysis.jobs.job'),
      detail: productOperation.detail ?? options.scope,
      status: 'queued',
      progress: 0,
      message: options.queuedMessage ?? t('analysis.jobs.started'),
      canRefresh: true,
      canCancel: true,
    })
  }

  function updateProductOperationRunFromSnapshot(
    run: ProductOperationRunRecord | null,
    snapshot: AnalysisJobSnapshot,
  ): void {
    if (!run) return
    const status = runStatusFromAnalysisSnapshot(snapshot)
    const message = snapshot.message ?? null
    if (status === 'failed') {
      operationRuns.failRun(run.id, snapshot.error || message || t('analysis.jobs.failed'))
      return
    }
    if (status === 'cancelled') {
      operationRuns.cancelRun(run.id, message || t('analysis.jobs.cancelled'))
      return
    }
    if (status === 'succeeded') {
      if (hasUnavailableAnalysisRows(snapshot)) {
        operationRuns.finishRun(
          run.id,
          analysisJobRowsReadiness(snapshot).warnings[0] ?? t('analysis.jobs.doneNoRows'),
        )
        return
      }
      operationRuns.updateRun(run.id, {
        status: 'running',
        progress: 100,
        message: message ?? t('analysis.jobs.doneLoading'),
        error: null,
        canCancel: false,
      })
      return
    }
    operationRuns.updateRun(run.id, {
      status,
      progress: snapshotProgress(snapshot),
      message,
      error: snapshot.error ?? null,
      canCancel: true,
    })
  }

  function syncProductOperationRunsFromSnapshot(snapshot: AnalysisJobSnapshot): void {
    for (const run of operationRuns.records) {
      if (run.kind === 'analysis' && run.sourceId === snapshot.job_id) {
        updateProductOperationRunFromSnapshot(run, snapshot)
      }
    }
  }

  function failProductOperationRun(
    run: ProductOperationRunRecord | null,
    error: unknown,
  ): void {
    if (!run) return
    if (error instanceof Error && error.name === 'AbortError') {
      operationRuns.cancelRun(run.id, t('analysis.jobs.cancelled'))
      return
    }
    operationRuns.failRun(
      run.id,
      error instanceof Error && error.message ? error.message : t('analysis.jobs.failed'),
    )
  }

  async function responseRowsForTerminalSnapshot<T = unknown>(
    jobId: string,
    snapshot: AnalysisJobSnapshot,
    options: AnalysisJobMonitorOptions,
    productOperationRun: ProductOperationRunRecord | null,
  ): Promise<AnalysisJobRows<T>> {
    if (options.signal?.aborted) throw makeAbortError()
    if (snapshot.status === 'done') {
      const offset = options.rowsOffset ?? 0
      const limit = options.rowsLimit ?? 200
      const response = hasUnavailableAnalysisRows(snapshot)
        ? analysisRowsFromTerminalSnapshot<T>(snapshot, offset, limit)
        : await rows<T>(jobId, offset, limit)
      if (productOperationRun) {
        operationRuns.finishRun(productOperationRun.id, analysisResultLoadedMessage(response))
      }
      return response
    }
    if (snapshot.status === 'error') {
      throw new Error(snapshot.error || t('analysis.jobs.failedShort'))
    }
    if (snapshot.status === 'cancelled') {
      throw makeAbortError()
    }
    throw new Error(t('analysis.jobs.unknownStatus', { status: String(snapshot.status) }))
  }

  async function monitorJobViaWebSocket(
    jobId: string,
    options: AnalysisJobMonitorOptions,
    productOperationRun: ProductOperationRunRecord | null,
    wsPath?: string,
  ): Promise<AnalysisJobSnapshot | null> {
    if (typeof WebSocket === 'undefined') return null
    const ticket = await mintAnalysisWsTicket()
    if (!ticket) return null
    const url = analysisWebSocketUrl(jobId, wsPath, ticket)
    if (!url) return null
    if (options.signal?.aborted) throw makeAbortError()

    return await new Promise<AnalysisJobSnapshot | null>((resolve, reject) => {
      let settled = false
      let socket: WebSocket | null = null
      let firstSnapshotTimer: ReturnType<typeof setTimeout> | null = null

      const clearFirstSnapshotTimer = () => {
        if (firstSnapshotTimer === null) return
        clearTimeout(firstSnapshotTimer)
        firstSnapshotTimer = null
      }

      const cleanup = () => {
        clearFirstSnapshotTimer()
        options.signal?.removeEventListener('abort', onAbort)
        if (socket) {
          socket.onopen = null
          socket.onmessage = null
          socket.onerror = null
          socket.onclose = null
        }
      }
      const settleFallback = () => {
        if (settled) return
        settled = true
        cleanup()
        try {
          socket?.close()
        } catch {
          // Polling is already the recovery path; close is best effort.
        }
        resolve(null)
      }
      const settleTerminal = (snapshot: AnalysisJobSnapshot) => {
        if (settled) return
        settled = true
        cleanup()
        resolve(snapshot)
      }
      const settleError = (error: unknown) => {
        if (settled) return
        settled = true
        cleanup()
        reject(error)
      }
      const onAbort = () => {
        try {
          socket?.close()
        } catch {
          // Best effort: aborting the caller is authoritative.
        }
        settleError(makeAbortError())
      }

      options.signal?.addEventListener('abort', onAbort, { once: true })

      try {
        socket = new WebSocket(url)
      } catch {
        cleanup()
        resolve(null)
        return
      }

      // Both a stalled upgrade and an opened socket without the initial job
      // snapshot are transport failures. Fall back to the canonical HTTP status
      // endpoint instead of waiting indefinitely.
      firstSnapshotTimer = setTimeout(() => settleFallback(), WS_FIRST_SNAPSHOT_TIMEOUT_MS)
      socket.onerror = () => {
        settleFallback()
      }
      socket.onclose = () => {
        settleFallback()
      }
      socket.onmessage = (event: MessageEvent) => {
        void (async () => {
          try {
            clearFirstSnapshotTimer()
            const payload = typeof event.data === 'string' ? JSON.parse(event.data) : event.data
            if (
              !isPlainObject(payload) ||
              typeof payload.job_id !== 'string' ||
              typeof payload.status !== 'string'
            ) {
              settleFallback()
              return
            }
            const snapshot = setSnapshot(payload as unknown as AnalysisJobSnapshot, options.scope)
            updateProductOperationRunFromSnapshot(productOperationRun, snapshot)
            await options.onSnapshot?.(snapshot)
            if (isTerminalStatus(snapshot.status)) {
              settleTerminal(snapshot)
              try {
                socket?.close()
              } catch {
                // The terminal message is enough; close failures are irrelevant.
              }
            }
          } catch (error) {
            settleError(error)
          }
        })()
      }
    })
  }

  async function pollJobRows<T = unknown>(
    jobId: string,
    options: AnalysisJobMonitorOptions,
    productOperationRun: ProductOperationRunRecord | null,
  ): Promise<AnalysisJobRows<T>> {
    while (true) {
      if (options.signal?.aborted) throw makeAbortError()
      const snapshot = await refreshJob(jobId)
      updateProductOperationRunFromSnapshot(productOperationRun, snapshot)
      await options.onSnapshot?.(snapshot)
      if (isTerminalStatus(snapshot.status)) {
        return await responseRowsForTerminalSnapshot<T>(
          jobId,
          snapshot,
          options,
          productOperationRun,
        )
      }
      await sleepUntilNextPoll(options.pollMs ?? DEFAULT_POLL_MS, options.signal)
    }
  }

  async function monitorJobRows<T = unknown>(
    jobId: string,
    options: AnalysisJobMonitorOptions,
    productOperationRun: ProductOperationRunRecord | null,
    wsPath?: string,
  ): Promise<AnalysisJobRows<T>> {
    const terminalSnapshot = await monitorJobViaWebSocket(
      jobId,
      options,
      productOperationRun,
      wsPath,
    )
    if (terminalSnapshot) {
      return await responseRowsForTerminalSnapshot<T>(
        jobId,
        terminalSnapshot,
        options,
        productOperationRun,
      )
    }
    return await pollJobRows<T>(jobId, options, productOperationRun)
  }

  async function runJobRows<T = unknown>(
    options: AnalysisJobRunOptions,
  ): Promise<AnalysisJobRows<T>> {
    await assertJobMonitorReady()
    clearScope(options.scope)
    const start = await options.start()
    const jobId = start.job_id
    setActive(options.scope, jobId)
    const productOperationRun = startProductOperationRun(options, jobId)

    const cancelAfterAbort = async () => {
      await cancelJob(jobId).catch((err) => {
        console.warn('Analysis job could not be cancelled after abort', err)
      })
    }
    const cancelOnAbort = () => {
      void cancelAfterAbort()
    }

    try {
      const queuedSnapshot = setSnapshot({
        job_id: jobId,
        kind: options.kind,
        corpus: options.corpus,
        status: 'queued',
        progress: 0,
        message: options.queuedMessage ?? t('analysis.jobs.started'),
      }, options.scope)
      updateProductOperationRunFromSnapshot(productOperationRun, queuedSnapshot)
      await options.onStarted?.(start)
      await options.onSnapshot?.(queuedSnapshot)

      options.signal?.addEventListener('abort', cancelOnAbort, { once: true })
      if (options.signal?.aborted) {
        await cancelAfterAbort()
        throw makeAbortError()
      }
      return await monitorJobRows<T>(jobId, options, productOperationRun, start.ws_url)
    } catch (error) {
      failProductOperationRun(productOperationRun, error)
      throw error
    } finally {
      options.signal?.removeEventListener('abort', cancelOnAbort)
      if (activeJobId(options.scope) === jobId) {
        clearScope(options.scope)
      }
    }
  }

  async function resumeJobRows<T = unknown>(
    options: AnalysisJobResumeOptions,
  ): Promise<AnalysisJobRows<T>> {
    await assertJobMonitorReady()
    setActive(options.scope, options.jobId)
    const productOperationRun = startProductOperationRun(options, options.jobId)
    try {
      return await monitorJobRows<T>(options.jobId, options, productOperationRun)
    } catch (error) {
      failProductOperationRun(productOperationRun, error)
      throw error
    } finally {
      if (activeJobId(options.scope) === options.jobId) {
        clearScope(options.scope)
      }
    }
  }

  return {
    snapshots,
    activeJobIdsByScope,
    recentJobIds,
    jobScopes,
    activeJobs,
    monitorJobs,
    activeJobId,
    activeSnapshot,
    canRefreshJobs,
    canCancelJobs,
    canLoadJobRows,
    statusDisabledReason,
    cancelDisabledReason,
    rowsDisabledReason,
    snapshotFor,
    cancelJob,
    cancelScope,
    clearScope,
    refreshJob,
    resumeJobRows,
    rows,
    runJobRows,
    setSnapshot,
    setActive,
    scopeForJob,
  }
})
