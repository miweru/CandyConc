import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import {
  getOperationRun,
  type OperationRunSnapshot,
} from '@/api/client'
import { t } from '@/i18n'

export type ProductOperationRunKind = 'analysis' | 'import' | 'system' | 'export' | 'operation'
export type ProductOperationRunStatus = 'queued' | 'running' | 'succeeded' | 'failed' | 'cancelled' | 'stale' | 'unknown'

export interface ProductOperationRunRecord {
  id: string
  operationId: string
  sourceId: string
  backendRunId: string | null
  backendJobId: string | null
  kind: ProductOperationRunKind
  surfaceId: string | null
  cancelOperationId: string | null
  label: string
  detail: string | null
  phase: string | null
  resultRef: string | null
  evidence: Record<string, unknown> | null
  status: ProductOperationRunStatus
  progress: number | null
  message: string | null
  error: string | null
  readiness: string | null
  warnings: string[]
  startedAt: string
  updatedAt: string
  completedAt: string | null
  canRefresh: boolean
  canCancel: boolean
}

export interface StartProductOperationRunRecordInput {
  operationId: string
  sourceId: string
  backendRunId?: string | null
  backendJobId?: string | null
  kind?: ProductOperationRunKind
  surfaceId?: string | null
  cancelOperationId?: string | null
  label?: string
  detail?: string | null
  phase?: string | null
  resultRef?: string | null
  evidence?: Record<string, unknown> | null
  status?: ProductOperationRunStatus
  progress?: number | null
  message?: string | null
  error?: string | null
  readiness?: string | null
  warnings?: string[]
  startedAt?: string
  updatedAt?: string
  canRefresh?: boolean
  canCancel?: boolean
}

type ProductOperationRunPatch = Partial<Omit<ProductOperationRunRecord, 'id' | 'operationId' | 'sourceId' | 'startedAt'>>

function runId(operationId: string, sourceId: string): string {
  return `${operationId}:${sourceId}`
}

function nowIso(): string {
  return new Date().toISOString()
}

function clampProgress(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return Math.max(0, Math.min(100, value))
}

function sortRuns(left: ProductOperationRunRecord, right: ProductOperationRunRecord): number {
  const leftTime = Date.parse(left.updatedAt) || 0
  const rightTime = Date.parse(right.updatedAt) || 0
  if (leftTime !== rightTime) return rightTime - leftTime
  return left.id.localeCompare(right.id)
}

function snapshotStatus(status: OperationRunSnapshot['status']): ProductOperationRunStatus {
  if (status === 'succeeded') return 'succeeded'
  if (status === 'failed') return 'failed'
  if (status === 'cancelled') return 'cancelled'
  if (status === 'stale') return 'stale'
  return status === 'queued' ? 'queued' : 'running'
}

function snapshotKind(kind: string | undefined): ProductOperationRunKind {
  if (kind === 'analysis' || kind === 'import' || kind === 'system' || kind === 'export' || kind === 'operation') {
    return kind
  }
  return 'operation'
}

export const useProductOperationRunsStore = defineStore('productOperationRuns', () => {
  const recordsById = ref<Record<string, ProductOperationRunRecord>>({})

  const records = computed(() => Object.values(recordsById.value).sort(sortRuns))
  const activeRecords = computed(() => records.value.filter((record) => record.status === 'queued' || record.status === 'running'))
  const failedRecords = computed(() => records.value.filter((record) => record.status === 'failed' || record.status === 'stale'))

  function startRun(input: StartProductOperationRunRecordInput): ProductOperationRunRecord {
    const timestamp = input.startedAt ?? nowIso()
    const id = runId(input.operationId, input.sourceId)
    const next: ProductOperationRunRecord = {
      id,
      operationId: input.operationId,
      sourceId: input.sourceId,
      backendRunId: input.backendRunId ?? null,
      backendJobId: input.backendJobId ?? null,
      kind: input.kind ?? 'operation',
      surfaceId: input.surfaceId ?? null,
      cancelOperationId: input.cancelOperationId ?? null,
      label: input.label ?? input.operationId,
      detail: input.detail ?? null,
      phase: input.phase ?? null,
      resultRef: input.resultRef ?? null,
      evidence: input.evidence ?? null,
      status: input.status ?? 'queued',
      progress: clampProgress(input.progress),
      message: input.message ?? null,
      error: input.error ?? null,
      readiness: input.readiness ?? null,
      warnings: input.warnings ?? [],
      startedAt: timestamp,
      updatedAt: input.updatedAt ?? timestamp,
      completedAt: null,
      canRefresh: input.canRefresh ?? false,
      canCancel: input.canCancel ?? false,
    }
    recordsById.value = { ...recordsById.value, [id]: next }
    return next
  }

  function updateRun(id: string, patch: ProductOperationRunPatch): ProductOperationRunRecord | null {
    const current = recordsById.value[id]
    if (!current) return null
    const progress = patch.progress === undefined
      ? current.progress
      : clampProgress(patch.progress)
    const next: ProductOperationRunRecord = {
      ...current,
      ...patch,
      progress,
      updatedAt: patch.updatedAt ?? nowIso(),
    }
    recordsById.value = { ...recordsById.value, [id]: next }
    return next
  }

  function finishRun(id: string, message: string = t('capabilities.runs.finished')): ProductOperationRunRecord | null {
    return updateRun(id, {
      status: 'succeeded',
      progress: 100,
      message,
      error: null,
      completedAt: nowIso(),
      canCancel: false,
    })
  }

  function failRun(id: string, error: string): ProductOperationRunRecord | null {
    return updateRun(id, {
      status: 'failed',
      message: error,
      error,
      completedAt: nowIso(),
      canCancel: false,
    })
  }

  function cancelRun(id: string, message: string = t('capabilities.runs.cancelled')): ProductOperationRunRecord | null {
    return updateRun(id, {
      status: 'cancelled',
      message,
      completedAt: nowIso(),
      canCancel: false,
    })
  }

  function removeRun(id: string): void {
    if (!recordsById.value[id]) return
    const next = { ...recordsById.value }
    delete next[id]
    recordsById.value = next
  }

  function clear(): void {
    recordsById.value = {}
  }

  async function refreshBackendRun(backendRunId: string): Promise<ProductOperationRunRecord | null> {
    const snapshot = await getOperationRun(backendRunId)
    const existing = Object.values(recordsById.value).find((record) =>
      record.sourceId === backendRunId ||
      record.backendRunId === backendRunId ||
      record.id === runId(snapshot.operation_id, backendRunId) ||
      record.id === runId(snapshot.operation_id, snapshot.source_id),
    )
    const status = snapshotStatus(snapshot.status)
    const snapshotRunId = snapshot.run_id || backendRunId
    const snapshotSourceId = snapshot.source_id || snapshotRunId
    const snapshotJobId = snapshot.job_id || snapshotRunId
    const snapshotResultRef = snapshot.result_ref ?? null
    const snapshotPhase = snapshot.phase ?? null
    const patch: ProductOperationRunPatch = {
      backendRunId: snapshotRunId,
      backendJobId: snapshotJobId,
      kind: snapshotKind(snapshot.kind),
      label: snapshot.label || existing?.label || t('capabilities.runs.serverRun'),
      detail: snapshotResultRef || snapshotPhase || existing?.detail || null,
      phase: snapshotPhase,
      resultRef: snapshotResultRef,
      evidence: snapshot.evidence ?? null,
      status,
      progress: snapshot.progress ?? null,
      message: snapshot.message ?? null,
      error: snapshot.error ?? null,
      readiness: snapshot.readiness ?? null,
      warnings: snapshot.warnings ?? [],
      updatedAt: snapshot.updated_at ?? nowIso(),
      completedAt: snapshot.finished_at ?? existing?.completedAt ?? null,
      canRefresh: true,
      canCancel: false,
    }
    if (existing) {
      return updateRun(existing.id, patch)
    }
    return startRun({
      operationId: snapshot.operation_id,
      sourceId: snapshotSourceId,
      backendRunId: snapshotRunId,
      backendJobId: snapshotJobId,
      kind: snapshotKind(snapshot.kind),
      label: snapshot.label || t('capabilities.runs.serverRun'),
      detail: snapshotResultRef ?? snapshotPhase,
      phase: snapshotPhase,
      resultRef: snapshotResultRef,
      evidence: snapshot.evidence ?? null,
      status,
      progress: snapshot.progress ?? null,
      message: snapshot.message ?? null,
      error: snapshot.error ?? null,
      readiness: snapshot.readiness ?? null,
      warnings: snapshot.warnings ?? [],
      startedAt: snapshot.created_at ?? nowIso(),
      updatedAt: snapshot.updated_at ?? nowIso(),
      canRefresh: true,
      canCancel: false,
    })
  }

  return {
    recordsById,
    records,
    activeRecords,
    failedRecords,
    startRun,
    updateRun,
    finishRun,
    failRun,
    cancelRun,
    removeRun,
    clear,
    refreshBackendRun,
  }
})
