/**
 * AnalysisPresets Store - Save and restore analysis configurations (server persisted)
 */

import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import type { DocsetSnapshot } from './docset'
import {
  createAnalysisPreset as createAnalysisPresetApi,
  deleteAnalysisPreset,
  getAnalysisPresets,
  getSystemInfo,
  touchAnalysisPreset,
  updateAnalysisPreset,
  type AnalysisJobSnapshot,
  type AnalysisPresetRecord,
  type SystemInfo,
} from '@/api/client'
import { t } from '@/i18n'
import { useAnalysisJobsStore } from './analysisJobs'
import { useCorpusCapabilitiesStore } from './corpusCapabilities'
import {
  useProductCapabilitiesStore,
  type ProductOperationAccessOptions,
} from './productCapabilities'

export type AnalysisType =
  | 'frequency'
  | 'collocations'
  | 'dispersion'
  | 'semantic'
  | 'ngrams'
  | 'keyness'
  | 'contrast'
  | 'wordsketch'
  | 'collocation_network'

export type AnalysisPresetStatus = 'idle' | 'queued' | 'running' | 'done' | 'error' | 'cancelled'

export interface AnalysisPreset {
  id: string
  name: string
  createdAt: number
  updatedAt?: number
  lastAccessedAt?: number
  type: AnalysisType
  corpus: string
  docset: DocsetSnapshot | null
  queryTerm?: string
  params: Record<string, unknown>
  result?: unknown
  resultMeta?: Record<string, unknown>
  status?: AnalysisPresetStatus
  jobId?: string
  kind?: 'saved' | 'session'
  /** Durable subcorpus definition name this preset was run against (reproducibility). */
  subcorpusId?: string
}

const STORAGE_KEY = 'candyconc_analysis_presets'
const DEFAULT_PROJECT = 'default'
const ANALYSIS_CACHE_VERSION = '2026-07-13-chi2-cell'
const CORPUS_SIGNATURE_TTL = 60_000
const RETIRED_CHI2_PARAM_KEYS = ['metric', 'measure', 'collocMeasure', 'sortBy', 'sort_by'] as const

export const ANALYSIS_PRESET_OPERATIONS = {
  list: 'research.analysis_presets.list',
  create: 'research.analysis_presets.create',
  update: 'research.analysis_presets.update',
  delete: 'research.analysis_presets.delete',
  touch: 'research.analysis_presets.touch',
} as const

function migrateRetiredChi2Params(params: Record<string, unknown> | undefined): {
  changed: boolean
  params: Record<string, unknown>
} {
  const next = { ...(params ?? {}) }
  let changed = false
  for (const key of RETIRED_CHI2_PARAM_KEYS) {
    if (next[key] === 'mi2') {
      next[key] = 'chi2_cell'
      changed = true
    }
  }
  return { changed, params: next }
}

function parsePresets(raw: unknown): { changed: boolean; presets: AnalysisPreset[] } {
  if (!raw) return { changed: false, presets: [] }
  try {
    const parsed = typeof raw === 'string' ? JSON.parse(raw) : raw
    if (!Array.isArray(parsed)) return { changed: false, presets: [] }
    let changed = false
    const presets = parsed
      .filter((item) => item && typeof item.id === 'string')
      .map((item) => {
        const preset = item as AnalysisPreset
        const migrated = migrateRetiredChi2Params(preset.params)
        if (!migrated.changed) return preset
        changed = true
        // Cached result payloads stay historical evidence; the cache version
        // below invalidates them rather than rewriting their measurement keys.
        return { ...preset, params: migrated.params }
      })
    return { changed, presets }
  } catch {
    return { changed: false, presets: [] }
  }
}

function mapApiPreset(preset: AnalysisPresetRecord): AnalysisPreset {
  const createdAt = preset.created_at ?? Date.now()
  const params = migrateRetiredChi2Params(preset.params).params
  const subcorpusId =
    typeof params.subcorpusId === 'string' ? (params.subcorpusId as string) : undefined
  return {
    id: preset.id,
    name: preset.name,
    type: preset.type as AnalysisType,
    corpus: preset.corpus ?? 'default',
    docset: (preset.docset as DocsetSnapshot) ?? null,
    queryTerm: preset.query_term,
    params,
    result: preset.result,
    resultMeta: preset.result_meta,
    status: (preset.status as AnalysisPresetStatus | undefined) ?? 'idle',
    jobId: preset.job_id,
    kind: (preset.kind as 'saved' | 'session' | undefined) ?? 'saved',
    subcorpusId,
    createdAt,
    updatedAt: preset.updated_at ?? undefined,
    lastAccessedAt: preset.last_accessed_at ?? undefined,
  }
}

function paramsWithSubcorpus(preset: AnalysisPreset): Record<string, unknown> {
  const params = { ...(preset.params ?? {}) }
  if (preset.subcorpusId) {
    params.subcorpusId = preset.subcorpusId
  } else {
    delete params.subcorpusId
  }
  return params
}

function toApiPreset(preset: AnalysisPreset): AnalysisPresetRecord {
  return {
    id: preset.id,
    name: preset.name,
    type: preset.type,
    corpus: preset.corpus,
    docset: preset.docset ?? null,
    query_term: preset.queryTerm,
    params: paramsWithSubcorpus(preset),
    result: preset.result,
    result_meta: preset.resultMeta,
    status: preset.status,
    job_id: preset.jobId,
    kind: preset.kind,
    created_at: preset.createdAt,
    updated_at: preset.updatedAt,
    last_accessed_at: preset.lastAccessedAt,
  }
}

function toApiPatch(patch: Partial<AnalysisPreset>): Partial<AnalysisPresetRecord> {
  const mapped: Partial<AnalysisPresetRecord> = {}
  if (patch.name !== undefined) mapped.name = patch.name
  if (patch.type !== undefined) mapped.type = patch.type
  if (patch.corpus !== undefined) mapped.corpus = patch.corpus
  if (patch.docset !== undefined) mapped.docset = patch.docset
  if (patch.queryTerm !== undefined) mapped.query_term = patch.queryTerm
  if (patch.params !== undefined || patch.subcorpusId !== undefined) {
    const params = { ...(patch.params ?? {}) }
    if (patch.subcorpusId !== undefined) {
      if (patch.subcorpusId) params.subcorpusId = patch.subcorpusId
      else delete params.subcorpusId
    }
    mapped.params = params
  }
  if (patch.result !== undefined) mapped.result = patch.result
  if (patch.resultMeta !== undefined) mapped.result_meta = patch.resultMeta
  if (patch.status !== undefined) mapped.status = patch.status
  if (patch.jobId !== undefined) mapped.job_id = patch.jobId
  if (patch.kind !== undefined) mapped.kind = patch.kind
  if (patch.createdAt !== undefined) mapped.created_at = patch.createdAt
  if (patch.updatedAt !== undefined) mapped.updated_at = patch.updatedAt
  if (patch.lastAccessedAt !== undefined) mapped.last_accessed_at = patch.lastAccessedAt
  return mapped
}

function upsertLocal(list: AnalysisPreset[], preset: AnalysisPreset): AnalysisPreset[] {
  const idx = list.findIndex((p) => p.id === preset.id)
  if (idx === -1) {
    return [preset, ...list]
  }
  const next = [...list]
  next[idx] = preset
  return next
}

function latestTimestamp(preset: AnalysisPreset): number {
  return Math.max(preset.updatedAt ?? 0, preset.lastAccessedAt ?? 0, preset.createdAt ?? 0)
}

function stableStringify(value: unknown): string {
  if (value === null || typeof value !== 'object') {
    return JSON.stringify(value)
  }
  if (Array.isArray(value)) {
    return `[${value.map((item) => stableStringify(item)).join(',')}]`
  }
  const entries = Object.entries(value as Record<string, unknown>).sort(([a], [b]) =>
    a.localeCompare(b)
  )
  return `{${entries.map(([k, v]) => `${JSON.stringify(k)}:${stableStringify(v)}`).join(',')}}`
}

function hashString(value: string): string {
  let hash = 5381
  for (let i = 0; i < value.length; i += 1) {
    hash = ((hash << 5) + hash) ^ value.charCodeAt(i)
  }
  return (hash >>> 0).toString(16)
}

function corpusSignatureUnavailable(corpus: string, error: unknown): Record<string, unknown> {
  return {
    corpus,
    fallback: true,
    signatureUnavailable: true,
    reason: error instanceof Error ? error.message : 'system_info_unavailable',
    backendVersion: 'unknown',
    lastUpdated: null,
    tokenCount: null,
    documentCount: null,
    vectorCount: null,
  }
}

export const useAnalysisPresetsStore = defineStore('analysisPresets', () => {
  const productCapabilities = useProductCapabilitiesStore()
  const presets = ref<AnalysisPreset[]>([])
  const sessionPresets = ref<AnalysisPreset[]>([])
  const pendingPreset = ref<AnalysisPreset | null>(null)
  const isLoading = ref(false)
  const isLoaded = ref(false)
  const error = ref<string | null>(null)
  const corpusSignatureCache = ref<Record<string, { ts: number; signature: Record<string, unknown> }>>({})

  const sortedPresets = computed(() =>
    [...presets.value].sort((a, b) => latestTimestamp(b) - latestTimestamp(a))
  )
  const sortedSessionPresets = computed(() =>
    [...sessionPresets.value].sort((a, b) => latestTimestamp(b) - latestTimestamp(a))
  )
  const listAvailability = computed(() =>
    productCapabilities.productOperationAvailability(ANALYSIS_PRESET_OPERATIONS.list)
  )
  const createAvailability = computed(() =>
    productCapabilities.productOperationAvailability(ANALYSIS_PRESET_OPERATIONS.create)
  )
  const updateAvailability = computed(() =>
    productCapabilities.productOperationAvailability(ANALYSIS_PRESET_OPERATIONS.update)
  )
  const deleteAvailability = computed(() =>
    productCapabilities.productOperationAvailability(ANALYSIS_PRESET_OPERATIONS.delete)
  )
  const touchAvailability = computed(() =>
    productCapabilities.productOperationAvailability(ANALYSIS_PRESET_OPERATIONS.touch)
  )
  const canLoadPresets = computed(() => listAvailability.value.enabled)
  const canCreatePresets = computed(() => createAvailability.value.enabled)
  const canUpdatePresets = computed(() => updateAvailability.value.enabled)
  const canDeletePresets = computed(() => deleteAvailability.value.enabled)
  const canTouchPresets = computed(() => touchAvailability.value.enabled)

  function denied(reason: string | null, fallback: string): Error {
    return new Error(reason ?? fallback)
  }

  async function assertPresetOperation(
    operationId: string,
    label: string,
    availability: { disabledReason: string | null; enabled: boolean },
    options: ProductOperationAccessOptions = {},
  ): Promise<void> {
    if (!productCapabilities.hasContract) {
      if (!availability.enabled) {
        throw denied(availability.disabledReason, t('workspace.presetsStore.notEnabledSession', { label }))
      }
      return
    }
    await productCapabilities.assertProductOperationAccess(operationId, label, options)
  }

  async function migrateLocalPresets(localPresets: AnalysisPreset[], project = DEFAULT_PROJECT) {
    if (!localPresets.length) return
    if (!canCreatePresets.value) return
    for (const preset of localPresets) {
      try {
        const created = await createAnalysisPresetApi(toApiPreset(preset), project)
        presets.value = upsertLocal(presets.value, mapApiPreset(created))
      } catch {
        // Ignore migration errors
      }
    }
    localStorage.removeItem(STORAGE_KEY)
  }

  async function init(project = DEFAULT_PROJECT, force = false) {
    if (isLoading.value) return
    if (isLoaded.value && !force) return
    isLoading.value = true
    error.value = null
    const parsedLocalPresets = parsePresets(localStorage.getItem(STORAGE_KEY))
    const localPresets = parsedLocalPresets.presets
    if (parsedLocalPresets.changed) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(localPresets))
    }
    if (!canLoadPresets.value) {
      error.value = listAvailability.value.disabledReason ?? t('workspace.presetsStore.listNotEnabled')
      presets.value = localPresets
      isLoading.value = false
      return
    }
    try {
      const serverPresets = await getAnalysisPresets(project)
      presets.value = serverPresets.map(mapApiPreset)
      isLoaded.value = true
      if (!serverPresets.length && localPresets.length) {
        await migrateLocalPresets(localPresets, project)
      }
      await refreshRunningJobs(project)
    } catch (err) {
      error.value = err instanceof Error ? err.message : t('workspace.presetsStore.loadFailed')
      presets.value = localPresets
    } finally {
      isLoading.value = false
    }
  }

  async function add(preset: AnalysisPreset, project = DEFAULT_PROJECT) {
    await assertPresetOperation(
      ANALYSIS_PRESET_OPERATIONS.create,
      t('workspace.presetsStore.save'),
      createAvailability.value,
      { target: preset.name || preset.id },
    )
    const created = await createAnalysisPresetApi(toApiPreset(preset), project)
    const mapped = mapApiPreset(created)
    presets.value = upsertLocal(presets.value, mapped)
    return mapped
  }

  async function update(id: string, patch: Partial<AnalysisPreset>, project = DEFAULT_PROJECT) {
    await assertPresetOperation(
      ANALYSIS_PRESET_OPERATIONS.update,
      t('workspace.presetsStore.update'),
      updateAvailability.value,
      { target: patch.name || id },
    )
    const updated = await updateAnalysisPreset(id, toApiPatch(patch), project)
    const mapped = mapApiPreset(updated)
    presets.value = upsertLocal(presets.value, mapped)
    return mapped
  }

  async function remove(id: string, project = DEFAULT_PROJECT) {
    const preset = presets.value.find((item) => item.id === id)
    await assertPresetOperation(
      ANALYSIS_PRESET_OPERATIONS.delete,
      t('workspace.presetsStore.delete'),
      deleteAvailability.value,
      {
        target: preset?.name ?? id,
        impact: t('workspace.presetsStore.deleteImpact'),
      },
    )
    await deleteAnalysisPreset(id, project)
    presets.value = presets.value.filter((p) => p.id !== id)
  }

  async function touch(id: string, project = DEFAULT_PROJECT) {
    await assertPresetOperation(
      ANALYSIS_PRESET_OPERATIONS.touch,
      t('workspace.presetsStore.touch'),
      touchAvailability.value,
      { target: id },
    )
    const updated = await touchAnalysisPreset(id, project)
    const mapped = mapApiPreset(updated)
    presets.value = upsertLocal(presets.value, mapped)
    return mapped
  }

  function setPending(preset: AnalysisPreset | null) {
    pendingPreset.value = preset
  }

  /**
   * Make the corpus of a saved analysis the active corpus. Returns null when
   * it is active, else the message why it is not: the corpus is not in the
   * catalog, or the server refused the activation.
   */
  async function activatePresetCorpus(preset: AnalysisPreset): Promise<string | null> {
    const corpusStore = useCorpusCapabilitiesStore()
    const target = (preset.docset?.corpus || preset.corpus || '').trim()
    if (!target || target === corpusStore.activeCorpus) return null
    if (!corpusStore.corpora.length) await corpusStore.fetchCorpora()
    if (!corpusStore.corpora.some((corpus) => corpus.name === target)) {
      return t('workspace.presetsStore.corpusMissing', { name: preset.name, corpus: target })
    }
    await corpusStore.setActive(target)
    if (corpusStore.activeCorpus === target) return null
    return corpusStore.activationError ?? t('workspace.presetsStore.corpusNotActivated', { corpus: target })
  }

  function createPreset(
    input: Omit<AnalysisPreset, 'id' | 'createdAt' | 'updatedAt' | 'lastAccessedAt'>
  ): AnalysisPreset {
    const now = Date.now()
    return {
      ...input,
      id: crypto.randomUUID(),
      createdAt: now,
      updatedAt: now,
      lastAccessedAt: now,
      status: input.status ?? 'idle',
      kind: input.kind ?? 'saved',
    }
  }

  async function upsertJobSession(
    input: Omit<AnalysisPreset, 'id' | 'createdAt' | 'updatedAt' | 'lastAccessedAt'> & {
      id?: string
      status?: AnalysisPresetStatus
    },
    project = DEFAULT_PROJECT
  ) {
    void project
    const existing = input.id ? sessionPresets.value.find((p) => p.id === input.id) : null
    if (existing) {
      const next = {
        ...existing,
        name: input.name,
        type: input.type,
        corpus: input.corpus,
        docset: input.docset,
        queryTerm: input.queryTerm,
        params: input.params,
        status: input.status,
        jobId: input.jobId,
        kind: 'session' as const,
        updatedAt: Date.now(),
      }
      sessionPresets.value = upsertLocal(sessionPresets.value, next)
      return next
    }

    const preset = createPreset({
      name: input.name,
      type: input.type,
      corpus: input.corpus,
      docset: input.docset,
      queryTerm: input.queryTerm,
      params: input.params,
      status: input.status ?? 'running',
      jobId: input.jobId,
      kind: 'session',
    })
    sessionPresets.value = upsertLocal(sessionPresets.value, preset)
    return preset
  }

  async function updateJobStatus(
    presetId: string,
    snapshot: AnalysisJobSnapshot,
    project = DEFAULT_PROJECT
  ) {
    const session = sessionPresets.value.find((p) => p.id === presetId)
    if (session) {
      const nextStatus = snapshot.status as AnalysisPresetStatus
      if (session.status === nextStatus && session.jobId === snapshot.job_id) return
      sessionPresets.value = upsertLocal(sessionPresets.value, {
        ...session,
        status: nextStatus,
        jobId: snapshot.job_id,
        updatedAt: Date.now(),
      })
      return
    }
    const preset = presets.value.find((p) => p.id === presetId)
    if (!preset) return
    const nextStatus = snapshot.status as AnalysisPresetStatus
    if (preset.status === nextStatus && preset.jobId === snapshot.job_id) return
    await update(
      presetId,
      {
        status: nextStatus,
        jobId: snapshot.job_id,
      },
      project
    )
  }

  async function updateResult(
    presetId: string,
    result: unknown,
    resultMeta: Record<string, unknown>,
    project = DEFAULT_PROJECT
  ) {
    const session = sessionPresets.value.find((p) => p.id === presetId)
    if (session) {
      sessionPresets.value = upsertLocal(sessionPresets.value, {
        ...session,
        result,
        resultMeta,
        status: 'done',
        updatedAt: Date.now(),
      })
      return
    }
    await update(
      presetId,
      {
        result,
        resultMeta,
        status: 'done',
      },
      project
    )
  }

  async function refreshRunningJobs(project = DEFAULT_PROJECT) {
    if (!canUpdatePresets.value) return
    const analysisJobs = useAnalysisJobsStore()
    const running = presets.value.filter(
      (preset) =>
        preset.jobId &&
        (preset.status === 'running' || preset.status === 'queued')
    )
    if (!running.length) return

    await Promise.allSettled(
      running.map(async (preset) => {
        try {
          const snap = await analysisJobs.refreshJob(preset.jobId as string)
          await updateJobStatus(preset.id, snap, project)
        } catch {
          await update(preset.id, { status: 'error' }, project)
        }
      })
    )
  }

  async function getCorpusSignature(corpus: string): Promise<Record<string, unknown>> {
    const cached = corpusSignatureCache.value[corpus]
    const now = Date.now()
    if (cached && now - cached.ts < CORPUS_SIGNATURE_TTL) {
      return cached.signature
    }
    let info: SystemInfo
    let fallback = false
    try {
      info = await getSystemInfo(corpus)
    } catch (scopedError) {
      // The corpus-scoped lookup failed, so the stats below describe the
      // DEFAULT corpus, not `corpus`. The corpus-specific counts must not be
      // attributed to (or cached for) `corpus`, otherwise a switch would serve
      // the previous/default corpus's stats.
      try {
        info = await getSystemInfo()
      } catch {
        return corpusSignatureUnavailable(corpus, scopedError)
      }
      fallback = true
    }
    const signature = {
      corpus,
      // Mark fallback-derived signatures so they always differ from a later
      // successful corpus-scoped fetch and never collide with another corpus.
      fallback,
      backendVersion: info.backendVersion ?? info.version ?? 'unknown',
      lastUpdated: fallback ? null : (info.lastUpdated ?? null),
      tokenCount: fallback ? 0 : (info.tokenCount ?? 0),
      documentCount: fallback ? 0 : (info.documentCount ?? 0),
      vectorCount: fallback ? null : (info.vectorCount ?? null),
    }
    // Don't cache fallback-derived signatures: a subsequent attempt should be
    // able to obtain the real corpus-scoped stats instead of being pinned to
    // the placeholder for the full TTL.
    if (!fallback) {
      corpusSignatureCache.value[corpus] = { ts: now, signature }
    }
    return signature
  }

  async function buildCacheKey(input: {
    type: AnalysisType
    corpus: string
    docset: DocsetSnapshot | null
    queryTerm?: string
    params: Record<string, unknown>
    subcorpusId?: string
  }): Promise<string> {
    const corpusSignature = await getCorpusSignature(input.corpus ?? 'default')
    // Identify the scope by the DURABLE subcorpus name (when available) plus a
    // stable filter hash — never by the transient docsetId, which changes on
    // every restart and would otherwise invalidate every cached result.
    const docsetSignature = input.docset
      ? {
          subcorpusId: input.subcorpusId ?? input.docset.name ?? null,
          filterSpec: input.docset.filterSpec ?? null,
          filters: input.docset.filters,
          includeAi: input.docset.includeAi,
          includeHuman: input.docset.includeHuman,
          corpus: input.docset.corpus,
          query: input.docset.query ?? null,
        }
      : null
    const payload = {
      cacheVersion: ANALYSIS_CACHE_VERSION,
      type: input.type,
      corpusSignature,
      docsetSignature,
      queryTerm: input.queryTerm ?? null,
      params: input.params ?? {},
    }
    return hashString(stableStringify(payload))
  }

  async function isResultValid(preset: AnalysisPreset): Promise<boolean> {
    if (!preset.result || !preset.resultMeta) return false
    const meta = preset.resultMeta as Record<string, unknown>
    if (meta.cacheVersion !== ANALYSIS_CACHE_VERSION) return false
    const cachedKey = meta.cacheKey
    if (!cachedKey || typeof cachedKey !== 'string') return false
    const currentKey = await buildCacheKey({
      type: preset.type,
      corpus: preset.corpus,
      docset: preset.docset,
      queryTerm: preset.queryTerm,
      params: preset.params ?? {},
      subcorpusId: preset.subcorpusId,
    })
    return cachedKey === currentKey
  }

  return {
    presets,
    sessionPresets,
    sortedPresets,
    sortedSessionPresets,
    pendingPreset,
    isLoading,
    error,
    listAvailability,
    createAvailability,
    updateAvailability,
    deleteAvailability,
    touchAvailability,
    canLoadPresets,
    canCreatePresets,
    canUpdatePresets,
    canDeletePresets,
    canTouchPresets,
    init,
    add,
    update,
    remove,
    touch,
    setPending,
    activatePresetCorpus,
    createPreset,
    upsertJobSession,
    updateJobStatus,
    updateResult,
    refreshRunningJobs,
    buildCacheKey,
    isResultValid,
    cacheVersion: ANALYSIS_CACHE_VERSION,
  }
})
