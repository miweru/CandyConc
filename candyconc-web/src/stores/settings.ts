/**
 * Settings Store - User preferences and system configuration
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import type { AppLocale } from '@/i18n'
import { applyLocale, detectBrowserLocale, isAppLocale } from '@/i18n/locale'
import { t } from '@/i18n'
import { useUiStore } from '@/stores/ui'
import {
  getPrefs,
  updatePrefs,
  getEmbeddingModels,
  downloadEmbeddingModel,
  getOperationRun,
  getLocalSemanticIndexPreflight,
  startLocalSemanticIndexBuild,
  getLocalSemanticIndexBuild,
  cancelLocalSemanticIndexBuild,
  deleteEmbeddingModel,
  getEmbeddingBackend,
  setEmbeddingBackend as setEmbeddingBackendRequest,
  getSystemInfo as fetchSystemInfo,
  clearCache as apiClearCache,
} from '@/api/client'
import type { EmbeddingBackendState, LocalSemanticIndexPreflight, OperationRunSnapshot } from '@/api/client'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import type { ProductOperationAccessOptions } from '@/stores/productCapabilities'
import { useProductOperationRunsStore, type ProductOperationRunRecord } from './productOperationRuns'

// ============================================
// Types
// ============================================

export interface UserPreferences {
  // General
  /** Interface language. Without a stored value it follows the browser. */
  language: AppLocale
  /** Corpus activated at startup when the address names none. 'default' follows the catalogue. */
  defaultCorpus: string
  resultsPerPage: number

  // Appearance (applied to the document root, see applyDisplayPreferences)
  highlightColor: 'yellow' | 'blue' | 'green' | 'purple'
  fontFamily: 'system' | 'mono'
  fontSize: 'small' | 'medium' | 'large'

  // Behavior
  /** Ask before a bookmark, annotation, saved subcorpus or saved analysis is deleted. */
  confirmDelete: boolean
  /** Global keyboard shortcuts (uiStore.shortcutsEnabled). */
  enableShortcuts: boolean
  /** Copilot-Hintergrund-Recherche (ui_context.disable_background_research bei aus). */
  backgroundResearch: boolean
}

export interface EmbeddingModel {
  id: string
  name: string
  language?: string
  size: string
  sizeBytes?: number
  dim?: number
  downloaded: boolean
  downloadProgress?: number
  url?: string
  sha256?: string
  description?: string
}

export interface SystemInfo {
  backendVersion: string
  uptime: string
  faissStatus: 'ready' | 'building' | 'error' | 'unavailable'
  faissDetail?: string
  vectorCount: number
  cacheSize: string
  corpusName: string
  tokenCount: number
  documentCount: number
  lastUpdated?: string
  source?: 'backend' | 'legacy_health_fallback' | 'backend_degraded_fallback'
}

export type BackendDataFreshness = 'fresh' | 'stale_cache' | 'degraded' | 'unavailable'
export type EmbeddingDownloadResult = 'installed' | 'queued' | false

export interface BackendDataProvenance {
  freshness: BackendDataFreshness
  source: 'backend' | 'local_cache' | 'legacy_fallback' | 'backend_degraded_fallback' | 'none'
  message: string
  observedAt?: string
}

export const SETTINGS_PREFERENCE_OPERATIONS = {
  read: 'settings.preferences.read',
  update: 'settings.preferences.update',
} as const

export const EMBEDDING_MANAGEMENT_OPERATIONS = {
  list: 'settings.embedding_management.list',
  localIndexPreflight: 'settings.embedding_management.local_index_preflight',
  localIndexBuild: 'settings.embedding_management.local_index_build',
  localIndexStatus: 'settings.embedding_management.local_index_status',
  localIndexCancel: 'settings.embedding_management.local_index_cancel',
  download: 'settings.embedding_management.download',
  downloadStatus: 'settings.embedding_management.download_status',
  remove: 'settings.embedding_management.remove',
  setActive: 'settings.embedding_management.set_active',
  backend: 'settings.embedding_management.backend',
} as const

export const MODEL_ROUTE_OPERATIONS = {
  read: 'settings.model_route.read',
  update: 'settings.model_route.update',
} as const

export const SYSTEM_OPERATION_OPERATIONS = {
  info: 'admin.system_operations.info',
  clearCache: 'admin.system_operations.clear_cache',
} as const

/** Value of defaultCorpus that means: use the active corpus of the catalogue. */
export const DEFAULT_CORPUS_PREFERENCE = 'default'

const HIGHLIGHT_COLORS = ['yellow', 'blue', 'green', 'purple'] as const
const FONT_FAMILIES = ['system', 'mono'] as const
const FONT_SIZES = ['small', 'medium', 'large'] as const

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
  return typeof value === 'string' && (allowed as readonly string[]).includes(value) ? (value as T) : fallback
}

/** Drop stored values the dialog no longer offers (for example the former 'inter' typeface). */
function sanitizePreferences(prefs: UserPreferences): UserPreferences {
  return {
    ...prefs,
    highlightColor: oneOf(prefs.highlightColor, HIGHLIGHT_COLORS, 'yellow'),
    fontFamily: oneOf(prefs.fontFamily, FONT_FAMILIES, 'system'),
    fontSize: oneOf(prefs.fontSize, FONT_SIZES, 'medium'),
  }
}

/**
 * Apply highlight colour, typeface and text size to the document root. The
 * rules that read these attributes are in style.css.
 */
export function applyDisplayPreferences(
  prefs: Pick<UserPreferences, 'highlightColor' | 'fontFamily' | 'fontSize'>,
): void {
  if (typeof document === 'undefined') return
  const root = document.documentElement
  root.dataset.kwicHighlight = oneOf(prefs.highlightColor, HIGHLIGHT_COLORS, 'yellow')
  root.dataset.fontFamily = oneOf(prefs.fontFamily, FONT_FAMILIES, 'system')
  root.dataset.fontSize = oneOf(prefs.fontSize, FONT_SIZES, 'medium')
}

// ============================================
// Store
// ============================================

export const useSettingsStore = defineStore('settings', () => {
  const operationRuns = useProductOperationRunsStore()
  const embeddingDownloadPollTimers = new Map<string, ReturnType<typeof setInterval>>()
  let localSemanticIndexPollTimer: ReturnType<typeof setInterval> | null = null

  // ============================================
  // State
  // ============================================

  const preferences = ref<UserPreferences>({
    // General
    language: detectBrowserLocale(),
    defaultCorpus: DEFAULT_CORPUS_PREFERENCE,
    resultsPerPage: 100,

    // Appearance
    highlightColor: 'yellow',
    fontFamily: 'system',
    fontSize: 'medium',

    // Behavior
    confirmDelete: true,
    enableShortcuts: true,
    backgroundResearch: true,
  })

  // The interface language follows this preference and nothing else.
  watch(
    () => preferences.value.language,
    (language) => applyLocale(isAppLocale(language) ? language : detectBrowserLocale()),
    { immediate: true, flush: 'sync' },
  )

  // Highlight colour, typeface and text size take effect through attributes on
  // the document root (rules in style.css).
  watch(
    () => [preferences.value.highlightColor, preferences.value.fontFamily, preferences.value.fontSize] as const,
    () => applyDisplayPreferences(preferences.value),
    { immediate: true, flush: 'sync' },
  )

  // Keyboard shortcuts are switched in the UI store, which useKeyboard reads.
  watch(
    () => preferences.value.enableShortcuts,
    (enabled) => useUiStore().setShortcutsEnabled(enabled !== false),
    { immediate: true, flush: 'sync' },
  )

  const embeddings = ref<EmbeddingModel[]>([])
  const localSemanticIndexPreflight = ref<LocalSemanticIndexPreflight | null>(null)
  const localSemanticIndexRun = ref<OperationRunSnapshot | null>(null)
  const localSemanticIndexError = ref<string | null>(null)
  const isLoadingLocalSemanticIndex = ref(false)

  const embeddingBackend = ref<EmbeddingBackendState | null>(null)
  const embeddingBackendError = ref<string | null>(null)
  const embeddingCatalogueProvenance = ref<BackendDataProvenance>({
    freshness: 'unavailable',
    source: 'none',
    message: t('settings.store.catalogueNotLoaded'),
  })

  const systemInfo = ref<SystemInfo>({
    backendVersion: '0.1.0',
    uptime: '0d 0h',
    faissStatus: 'unavailable',
    faissDetail: undefined,
    vectorCount: 0,
    cacheSize: '0 MB',
    corpusName: t('settings.store.noCorpus'),
    tokenCount: 0,
    documentCount: 0,
    lastUpdated: undefined,
  })
  const systemInfoProvenance = ref<BackendDataProvenance>({
    freshness: 'unavailable',
    source: 'none',
    message: t('settings.store.systemNotLoaded'),
  })

  const isLoading = ref(false)
  const downloadProgress = ref<Record<string, number>>({})
  const embeddingDownloadRunIds = ref<Record<string, string>>({})
  const embeddingDownloadBackendRunIds = ref<Record<string, string>>({})

  function stopEmbeddingDownloadPolling(modelId?: string): void {
    if (modelId) {
      const timer = embeddingDownloadPollTimers.get(modelId)
      if (timer) clearInterval(timer)
      embeddingDownloadPollTimers.delete(modelId)
      return
    }
    for (const timer of embeddingDownloadPollTimers.values()) clearInterval(timer)
    embeddingDownloadPollTimers.clear()
  }

  function rememberEmbeddingDownloadRun(modelId: string, runId: string, backendRunId?: string): void {
    embeddingDownloadRunIds.value = {
      ...embeddingDownloadRunIds.value,
      [modelId]: runId,
    }
    if (backendRunId) {
      embeddingDownloadBackendRunIds.value = {
        ...embeddingDownloadBackendRunIds.value,
        [modelId]: backendRunId,
      }
    }
  }

  function modelIdForEmbeddingBackendRun(backendRunId: string): string | null {
    const match = Object.entries(embeddingDownloadBackendRunIds.value)
      .find(([, candidate]) => candidate === backendRunId)
    return match?.[0] ?? null
  }

  function embeddingModelIsInstalled(modelId: string): boolean {
    return embeddings.value.some((model) => model.id === modelId && model.downloaded)
  }

  function markEmbeddingDownloadQueued(
    modelId: string,
    runId: string,
    message = t('settings.store.downloadQueued'),
  ): void {
    downloadProgress.value[modelId] = Math.max(downloadProgress.value[modelId] ?? 0, 25)
    operationRuns.updateRun(runId, {
      status: 'queued',
      progress: downloadProgress.value[modelId],
      message,
      error: null,
      canRefresh: true,
      canCancel: false,
    })
  }

  function finishEmbeddingDownloadIfInstalled(modelId: string, runId: string): boolean {
    if (!embeddingCatalogueIsFresh.value) return false
    if (!embeddingModelIsInstalled(modelId)) return false
    downloadProgress.value[modelId] = 100
    operationRuns.finishRun(runId, t('settings.store.modelInstalled'))
    delete downloadProgress.value[modelId]
    stopEmbeddingDownloadPolling(modelId)
    return true
  }

  function embeddingRunPatchFromSnapshot(
    snapshot: OperationRunSnapshot,
    fallbackMessage: string,
  ): Partial<ProductOperationRunRecord> {
    return {
      backendRunId: snapshot.run_id ?? null,
      backendJobId: snapshot.job_id ?? snapshot.run_id ?? null,
      phase: snapshot.phase ?? null,
      resultRef: snapshot.result_ref ?? null,
      evidence: snapshot.evidence ?? null,
      readiness: snapshot.readiness ?? null,
      warnings: snapshot.warnings ?? [],
      progress: typeof snapshot.progress === 'number' ? Math.max(0, Math.min(100, snapshot.progress)) : null,
      message: snapshot.message || fallbackMessage,
      error: snapshot.error ?? null,
      canRefresh: true,
      canCancel: false,
    }
  }

  function updateEmbeddingDownloadFromRun(modelId: string, runId: string, snapshot: OperationRunSnapshot): boolean {
    const previousProgress = downloadProgress.value[modelId] ?? 0
    const reportedProgress = typeof snapshot.progress === 'number'
      ? Math.max(0, Math.min(100, snapshot.progress))
      : null
    const progress = reportedProgress === null
      ? Math.max(previousProgress, snapshot.status === 'succeeded' ? 100 : 25)
      : Math.max(previousProgress, reportedProgress)
    downloadProgress.value[modelId] = progress

    if (snapshot.status === 'failed' || snapshot.status === 'cancelled' || snapshot.status === 'stale') {
      const error = snapshot.error || snapshot.message || t('settings.store.downloadNotFinished')
      operationRuns.updateRun(runId, {
        ...embeddingRunPatchFromSnapshot(snapshot, error),
        status: snapshot.status,
        message: error,
        error,
        completedAt: new Date().toISOString(),
        canRefresh: true,
        canCancel: false,
      })
      delete downloadProgress.value[modelId]
      stopEmbeddingDownloadPolling(modelId)
      return true
    }

    operationRuns.updateRun(runId, {
      ...embeddingRunPatchFromSnapshot(snapshot, t('settings.store.downloadRunning')),
      status: snapshot.status === 'queued' ? 'queued' : 'running',
      progress,
      message: snapshot.message || t('settings.store.downloadRunning'),
      error: null,
      canRefresh: true,
      canCancel: false,
    })
    return false
  }

  async function refreshEmbeddingDownloadStatus(
    modelId: string,
    runId: string,
    backendRunId?: string,
  ): Promise<void> {
    rememberEmbeddingDownloadRun(modelId, runId, backendRunId)
    let backendReportedSuccess = false
    if (backendRunId) {
      await assertProductOperation(
        EMBEDDING_MANAGEMENT_OPERATIONS.downloadStatus,
        t('settings.store.checkDownload'),
      )
      const snapshot = await getOperationRun(backendRunId)
      const terminal = updateEmbeddingDownloadFromRun(modelId, runId, snapshot)
      if (terminal) return
      backendReportedSuccess = snapshot.status === 'succeeded'
      if (!backendReportedSuccess) return
    }

    await loadEmbeddings()
    if (finishEmbeddingDownloadIfInstalled(modelId, runId)) return
    if (backendReportedSuccess) {
      operationRuns.updateRun(runId, {
        status: 'stale',
        message: t('settings.store.downloadContradiction'),
        error: t('settings.store.statusContradiction'),
        canRefresh: true,
        canCancel: false,
      })
      return
    }
    {
      markEmbeddingDownloadQueued(
        modelId,
        runId,
        t('settings.store.downloadContinues'),
      )
    }
  }

  async function refreshEmbeddingDownloadRun(backendRunId: string): Promise<void> {
    const modelId = modelIdForEmbeddingBackendRun(backendRunId)
    const runId = modelId ? embeddingDownloadRunIds.value[modelId] : null
    if (modelId && runId) {
      await refreshEmbeddingDownloadStatus(modelId, runId, backendRunId)
      return
    }

    await assertProductOperation(
      EMBEDDING_MANAGEMENT_OPERATIONS.downloadStatus,
      t('settings.store.checkDownload'),
    )
    const snapshot = await getOperationRun(backendRunId)
    operationRuns.startRun({
      operationId: snapshot.operation_id,
      sourceId: snapshot.source_id || backendRunId,
      backendRunId: snapshot.run_id || backendRunId,
      backendJobId: snapshot.job_id || snapshot.run_id || backendRunId,
      kind: 'operation',
      surfaceId: 'settings.embedding_management',
      label: snapshot.label || t('settings.store.download'),
      detail: snapshot.result_ref ?? null,
      phase: snapshot.phase ?? null,
      resultRef: snapshot.result_ref ?? null,
      evidence: snapshot.evidence ?? null,
      status: snapshot.status,
      progress: snapshot.progress ?? null,
      message: snapshot.message ?? null,
      error: snapshot.error ?? null,
      readiness: snapshot.readiness ?? null,
      warnings: snapshot.warnings ?? [],
      startedAt: snapshot.created_at,
      updatedAt: snapshot.updated_at,
      canRefresh: true,
      canCancel: false,
    })
  }

  function startEmbeddingDownloadPolling(
    modelId: string,
    runId: string,
    backendRunId?: string,
    intervalMs = 5000,
  ): void {
    if (embeddingDownloadPollTimers.has(modelId)) return
    const timer = setInterval(() => {
      refreshEmbeddingDownloadStatus(modelId, runId, backendRunId)
        .catch((error) => {
          operationRuns.updateRun(runId, {
            status: 'stale',
            message: t('settings.store.downloadUnchecked'),
            error: errorMessage(error),
            canRefresh: true,
            canCancel: false,
          })
        })
    }, intervalMs)
    ;(timer as { unref?: () => void }).unref?.()
    embeddingDownloadPollTimers.set(modelId, timer)
  }

  function responseStatus(error: unknown): number | null {
    const response = (error as { response?: unknown } | null)?.response
    if (response instanceof Response) return response.status
    if (
      response &&
      typeof response === 'object' &&
      'status' in response &&
      typeof response.status === 'number'
    ) {
      return response.status
    }
    return null
  }

  function isAccessError(error: unknown): boolean {
    const status = responseStatus(error)
    return status === 401 || status === 403
  }

  function isCapabilityDeniedError(error: unknown): boolean {
    return error instanceof Error && error.name === 'ProductCapabilityDeniedError'
  }

  function isExpectedAccessRestriction(error: unknown): boolean {
    return isAccessError(error) || isCapabilityDeniedError(error)
  }

  async function assertProductOperation(
    operationId: string,
    fallbackLabel: string,
    options: ProductOperationAccessOptions = {},
  ): Promise<void> {
    await useProductCapabilitiesStore().assertProductOperationAccess(operationId, fallbackLabel, options)
  }

  async function canUseProductOperation(operationId: string): Promise<boolean> {
    const productCapabilities = useProductCapabilitiesStore()
    await productCapabilities.ensureAccessContext()
    return productCapabilities.productOperationAvailability(operationId).enabled
  }

  // ============================================
  // Computed
  // ============================================

  const downloadedEmbeddings = computed(() =>
    embeddings.value.filter(e => e.downloaded)
  )

  const availableEmbeddings = computed(() =>
    embeddings.value.filter(e => !e.downloaded)
  )
  const embeddingDownloadRunsByModelId = computed<Record<string, ProductOperationRunRecord>>(() => {
    const result: Record<string, ProductOperationRunRecord> = {}
    for (const [modelId, runId] of Object.entries(embeddingDownloadRunIds.value)) {
      const run = operationRuns.recordsById[runId]
      if (run) result[modelId] = run
    }
    return result
  })
  const systemInfoIsFresh = computed(() => systemInfoProvenance.value.freshness === 'fresh')
  const embeddingCatalogueIsFresh = computed(() => embeddingCatalogueProvenance.value.freshness === 'fresh')
  const systemInfoIsStale = computed(() => systemInfoProvenance.value.freshness === 'stale_cache')
  const embeddingCatalogueIsStale = computed(() => embeddingCatalogueProvenance.value.freshness === 'stale_cache')

  // ============================================
  // Helpers
  // ============================================

  function parseBoolean(value: string | undefined, fallback: boolean): boolean {
    if (value === undefined) return fallback
    return value === 'true' || value === '1'
  }

  function parseNumber(value: string | undefined, fallback: number): number {
    if (value === undefined) return fallback
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : fallback
  }

  function formatBytes(bytes: number | undefined): string {
    if (!bytes || bytes <= 0) return t('settings.store.unknownSize')
    const units = ['B', 'KB', 'MB', 'GB', 'TB']
    let value = bytes
    let unitIndex = 0
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024
      unitIndex += 1
    }
    const rounded = value >= 100 ? Math.round(value) : Math.round(value * 10) / 10
    return `${rounded} ${units[unitIndex]}`
  }

  function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : t('settings.store.unknownError')
  }

  function freshProvenance(message: string): BackendDataProvenance {
    return {
      freshness: 'fresh',
      source: 'backend',
      message,
      observedAt: new Date().toISOString(),
    }
  }

  function staleCacheProvenance(message: string): BackendDataProvenance {
    return {
      freshness: 'stale_cache',
      source: 'local_cache',
      message,
      observedAt: new Date().toISOString(),
    }
  }

  function degradedProvenance(
    message: string,
    source: BackendDataProvenance['source'] = 'backend_degraded_fallback',
  ): BackendDataProvenance {
    return {
      freshness: 'degraded',
      source,
      message,
      observedAt: new Date().toISOString(),
    }
  }

  function unavailableProvenance(message: string): BackendDataProvenance {
    return {
      freshness: 'unavailable',
      source: 'none',
      message,
      observedAt: new Date().toISOString(),
    }
  }

  function coercePreferences(prefs: Record<string, string>): Partial<UserPreferences> {
    return {
      language: isAppLocale(prefs.language) ? prefs.language : preferences.value.language,
      defaultCorpus: prefs.defaultCorpus ?? preferences.value.defaultCorpus,
      resultsPerPage: parseNumber(prefs.resultsPerPage, preferences.value.resultsPerPage),
      highlightColor: oneOf(prefs.highlightColor, HIGHLIGHT_COLORS, preferences.value.highlightColor),
      fontFamily: oneOf(prefs.fontFamily, FONT_FAMILIES, preferences.value.fontFamily),
      fontSize: oneOf(prefs.fontSize, FONT_SIZES, preferences.value.fontSize),
      confirmDelete: parseBoolean(prefs.confirmDelete, preferences.value.confirmDelete),
      enableShortcuts: parseBoolean(prefs.enableShortcuts, preferences.value.enableShortcuts),
      backgroundResearch: parseBoolean(prefs.backgroundResearch, preferences.value.backgroundResearch),
    }
  }

  function mapEmbeddingModel(model: Awaited<ReturnType<typeof getEmbeddingModels>>[number]): EmbeddingModel {
    return {
      id: model.id,
      name: model.name,
      language: model.language ?? 'multi',
      size: formatBytes(model.sizeBytes),
      sizeBytes: model.sizeBytes,
      dim: model.dim,
      downloaded: model.installed,
      url: model.url,
      sha256: model.sha256,
      description: model.description,
    }
  }

  // ============================================
  // Actions
  // ============================================

  function loadLocalPreferences(): void {
    try {
      const stored = localStorage.getItem('candyconc_preferences')
      if (stored) {
        const parsed = JSON.parse(stored)
        preferences.value = sanitizePreferences({ ...preferences.value, ...parsed })
        if (!isAppLocale(preferences.value.language)) {
          preferences.value.language = detectBrowserLocale()
        }
      }
    } catch (localError) {
      console.error('Failed to load preferences from localStorage:', localError)
    }
  }

  async function loadPreferences() {
    isLoading.value = true
    try {
      await assertProductOperation(SETTINGS_PREFERENCE_OPERATIONS.read, t('settings.store.loadPreferences'))
      const state = await getPrefs()
      const prefs = state.prefs ?? {}
      preferences.value = { ...preferences.value, ...coercePreferences(prefs) }

      // Keep a local fallback cache.
      localStorage.setItem('candyconc_preferences', JSON.stringify(preferences.value))
    } catch (error) {
      console.error('Failed to load preferences from backend, falling back to localStorage:', error)
      loadLocalPreferences()
    } finally {
      isLoading.value = false
    }
  }

  async function savePreference<K extends keyof UserPreferences>(
    key: K,
    value: UserPreferences[K]
  ) {
    const nextPreferences = { ...preferences.value, [key]: value }

    try {
      await assertProductOperation(SETTINGS_PREFERENCE_OPERATIONS.update, t('settings.store.savePreference'))
      await updatePrefs({ [key]: value })
      preferences.value = nextPreferences
      localStorage.setItem('candyconc_preferences', JSON.stringify(preferences.value))
    } catch (error) {
      console.error('Failed to save preference to backend:', error)
    }
  }

  /**
   * Switch the interface language. The choice is applied and cached in this
   * browser first, so it takes effect even when the session may not write
   * server preferences. The server copy is updated where that is allowed.
   */
  async function setLanguage(language: AppLocale): Promise<void> {
    if (!isAppLocale(language)) return
    preferences.value = { ...preferences.value, language }
    try {
      localStorage.setItem('candyconc_preferences', JSON.stringify(preferences.value))
    } catch (localError) {
      console.error('Failed to cache language preference in localStorage:', localError)
    }
    try {
      if (!(await canUseProductOperation(SETTINGS_PREFERENCE_OPERATIONS.update))) return
      await updatePrefs({ language })
    } catch (error) {
      console.error('Failed to save language preference to backend:', error)
    }
  }

  /**
   * Ask before a user deletes something, when the preference says so. Returns
   * true when the deletion may proceed.
   */
  function confirmDeletion(name?: string | null): boolean {
    if (!preferences.value.confirmDelete) return true
    if (typeof window === 'undefined' || typeof window.confirm !== 'function') return true
    const label = name?.trim()
    return window.confirm(
      label ? t('settings.store.confirmDeleteNamed', { name: label }) : t('settings.store.confirmDelete'),
    )
  }

  async function resetPreferences() {
    const defaults: UserPreferences = {
      language: detectBrowserLocale(),
      defaultCorpus: DEFAULT_CORPUS_PREFERENCE,
      resultsPerPage: 100,
      highlightColor: 'yellow',
      fontFamily: 'system',
      fontSize: 'medium',
      confirmDelete: true,
      enableShortcuts: true,
      backgroundResearch: true,
    }
    try {
      await assertProductOperation(SETTINGS_PREFERENCE_OPERATIONS.update, t('settings.store.resetPreferences'))
      await updatePrefs(defaults as unknown as Record<string, unknown>)
      preferences.value = defaults
      localStorage.removeItem('candyconc_preferences')
    } catch (error) {
      console.error('Failed to reset preferences in backend:', error)
    }
  }

  // Local semantic index (Apple Silicon)
  function stopLocalSemanticIndexPolling(): void {
    if (localSemanticIndexPollTimer) {
      clearInterval(localSemanticIndexPollTimer)
      localSemanticIndexPollTimer = null
    }
  }

  function startLocalSemanticIndexPolling(runId: string, corpus: string, intervalMs = 3000): void {
    stopLocalSemanticIndexPolling()
    localSemanticIndexPollTimer = setInterval(() => {
      refreshLocalSemanticIndexBuild(runId, corpus).catch(() => undefined)
    }, intervalMs)
    ;(localSemanticIndexPollTimer as { unref?: () => void }).unref?.()
  }

  async function loadLocalSemanticIndexPreflight(corpus: string): Promise<boolean> {
    isLoadingLocalSemanticIndex.value = true
    localSemanticIndexError.value = null
    try {
      await assertProductOperation(
        EMBEDDING_MANAGEMENT_OPERATIONS.localIndexPreflight,
        t('settings.store.checkLocalBuild'),
      )
      const result = await getLocalSemanticIndexPreflight(corpus)
      localSemanticIndexPreflight.value = result
      const resumable = result.resumable_run
      if (resumable?.run_id) {
        await refreshLocalSemanticIndexBuild(resumable.run_id, corpus)
        if (localSemanticIndexRun.value?.status === 'running' || localSemanticIndexRun.value?.status === 'queued') {
          startLocalSemanticIndexPolling(resumable.run_id, corpus)
        }
      }
      return true
    } catch (error) {
      localSemanticIndexPreflight.value = null
      localSemanticIndexError.value = errorMessage(error)
      return false
    } finally {
      isLoadingLocalSemanticIndex.value = false
    }
  }

  async function refreshLocalSemanticIndexBuild(runId: string, corpus: string): Promise<void> {
    const snapshot = await getLocalSemanticIndexBuild(runId)
    localSemanticIndexRun.value = snapshot
    if (!['succeeded', 'failed', 'cancelled', 'stale'].includes(snapshot.status)) return
    stopLocalSemanticIndexPolling()
    if (snapshot.status === 'succeeded') {
      await Promise.all([
        loadLocalSemanticIndexPreflight(corpus),
        loadSystemInfo(),
      ])
    }
  }

  async function startLocalSemanticIndex(
    corpus: string,
    levels: Array<'doc' | 'sentence'>,
  ): Promise<boolean> {
    localSemanticIndexError.value = null
    try {
      await assertProductOperation(
        EMBEDDING_MANAGEMENT_OPERATIONS.localIndexBuild,
        t('settings.store.createLocalIndex'),
        {
          target: corpus,
          impact: t('settings.store.createLocalIndexImpact'),
        },
      )
      const launch = await startLocalSemanticIndexBuild(corpus, levels)
      const runId = launch.run_id || launch.job_id
      await refreshLocalSemanticIndexBuild(runId, corpus)
      if (!localSemanticIndexRun.value || !['succeeded', 'failed', 'cancelled', 'stale'].includes(localSemanticIndexRun.value.status)) {
        startLocalSemanticIndexPolling(runId, corpus)
      }
      return true
    } catch (error) {
      localSemanticIndexError.value = errorMessage(error)
      return false
    }
  }

  async function cancelLocalSemanticIndex(runId: string): Promise<boolean> {
    try {
      await assertProductOperation(
        EMBEDDING_MANAGEMENT_OPERATIONS.localIndexCancel,
        t('settings.store.cancelLocalBuild'),
      )
      localSemanticIndexRun.value = await cancelLocalSemanticIndexBuild(runId)
      stopLocalSemanticIndexPolling()
      return true
    } catch (error) {
      localSemanticIndexError.value = errorMessage(error)
      return false
    }
  }

  // Legacy word-vector package management
  async function loadEmbeddings() {
    isLoading.value = true
    try {
      await assertProductOperation(EMBEDDING_MANAGEMENT_OPERATIONS.list, t('settings.store.loadEmbeddings'))
      const models = await getEmbeddingModels()
      embeddings.value = models.map(mapEmbeddingModel)
      embeddingCatalogueProvenance.value = freshProvenance(
        t('settings.store.catalogueLoaded'),
      )

      localStorage.setItem('candyconc_embeddings', JSON.stringify({
        models: embeddings.value,
      }))
    } catch (error) {
      if (!isExpectedAccessRestriction(error)) {
        console.error('Failed to load embeddings from backend:', error)
      }
      if (isExpectedAccessRestriction(error)) {
        embeddings.value = []
        embeddingCatalogueProvenance.value = unavailableProvenance(
          t('settings.store.catalogueNotEnabled'),
        )
        return
      }
      try {
        const stored = localStorage.getItem('candyconc_embeddings')
        if (stored) {
          const { models } = JSON.parse(stored)
          embeddings.value = models
          embeddingCatalogueProvenance.value = staleCacheProvenance(
            t('settings.store.catalogueCached', { error: errorMessage(error) }),
          )
        } else {
          embeddingCatalogueProvenance.value = unavailableProvenance(
            t('settings.store.catalogueFailed', { error: errorMessage(error) }),
          )
        }
      } catch (localError) {
        console.error('Failed to load embeddings from localStorage:', localError)
        embeddingCatalogueProvenance.value = unavailableProvenance(
          t('settings.store.catalogueAndCacheFailed', { error: errorMessage(error) }),
        )
      }
    } finally {
      isLoading.value = false
    }
  }

  async function downloadEmbedding(modelId: string): Promise<EmbeddingDownloadResult> {
    if (!embeddingCatalogueIsFresh.value) {
      console.warn('Embedding mutation blocked because catalogue is not fresh.')
      return false
    }
    const model = embeddings.value.find(e => e.id === modelId)
    if (!model || model.downloaded || !model.url) return false
    let localRunId: string | null = null

    try {
      await assertProductOperation(
        EMBEDDING_MANAGEMENT_OPERATIONS.download,
        t('settings.store.downloadModel'),
        {
          target: model.name ?? model.id,
          impact: t('settings.store.downloadModelImpact'),
        },
      )
      downloadProgress.value[modelId] = 10
      const response = await downloadEmbeddingModel(modelId, model.url, model.sha256)
      const backendRunId = response.run_id ?? response.job_id
      const run = operationRuns.startRun({
        operationId: EMBEDDING_MANAGEMENT_OPERATIONS.download,
        sourceId: modelId,
        backendRunId: backendRunId ?? null,
        backendJobId: response.job_id ?? backendRunId ?? null,
        kind: 'operation',
        surfaceId: 'settings.embedding_management',
        label: `Embedding-Download: ${model.name ?? model.id}`,
        detail: response.status_url ?? model.size ?? null,
        phase: backendRunId ? 'queued' : null,
        status: backendRunId ? 'running' : 'queued',
        progress: 10,
        message: t('settings.store.downloading'),
      })
      localRunId = run.id
      rememberEmbeddingDownloadRun(modelId, run.id, backendRunId)
      await refreshEmbeddingDownloadStatus(modelId, run.id, backendRunId)
      if (finishEmbeddingDownloadIfInstalled(modelId, run.id)) return 'installed'

      if (!backendRunId) {
        markEmbeddingDownloadQueued(
          modelId,
          run.id,
          response.status === 'queued'
            ? t('settings.store.downloadQueued')
            : t('settings.store.downloadConfirmed', { status: response.status }),
        )
      }
      startEmbeddingDownloadPolling(modelId, run.id, backendRunId)

      return 'queued'
    } catch (error) {
      console.error('Failed to download embedding:', error)
      operationRuns.failRun(
        localRunId ?? `${EMBEDDING_MANAGEMENT_OPERATIONS.download}:${modelId}`,
        error instanceof Error ? error.message : t('settings.store.downloadFailed'),
      )
      stopEmbeddingDownloadPolling(modelId)
      delete downloadProgress.value[modelId]
      return false
    }
  }

  async function removeEmbedding(modelId: string): Promise<boolean> {
    if (!embeddingCatalogueIsFresh.value) {
      console.warn('Embedding mutation blocked because catalogue is not fresh.')
      return false
    }
    const model = embeddings.value.find(e => e.id === modelId)
    if (!model || !model.downloaded) return false

    try {
      await assertProductOperation(
        EMBEDDING_MANAGEMENT_OPERATIONS.remove,
        t('settings.store.removeModel'),
        {
          target: model.name ?? model.id,
          impact: t('settings.store.removeModelImpact'),
        },
      )
      await deleteEmbeddingModel(modelId)
      await loadEmbeddings()
      return true
    } catch (error) {
      console.error('Failed to remove embedding:', error)
      return false
    }
  }

  /**
   * The server's embedding backend (spacy or none). Servers without the read
   * route (before release/rest_backend) leave it null and the settings show
   * no switch.
   */
  async function loadEmbeddingBackend(): Promise<void> {
    embeddingBackendError.value = null
    if (!(await canUseProductOperation(EMBEDDING_MANAGEMENT_OPERATIONS.backend))) {
      embeddingBackend.value = null
      return
    }
    try {
      embeddingBackend.value = await getEmbeddingBackend()
    } catch (error) {
      embeddingBackend.value = null
      embeddingBackendError.value = errorMessage(error)
    }
  }

  /** Switches the embedding backend. The server accepts spacy and none only. */
  async function setEmbeddingBackend(backend: string): Promise<boolean> {
    embeddingBackendError.value = null
    try {
      await assertProductOperation(EMBEDDING_MANAGEMENT_OPERATIONS.setActive, t('settings.store.setBackend'))
      embeddingBackend.value = await setEmbeddingBackendRequest(backend)
      return true
    } catch (error) {
      embeddingBackendError.value = errorMessage(error)
      return false
    }
  }

  // System Info
  async function loadSystemInfo() {
    isLoading.value = true
    try {
      await assertProductOperation(SYSTEM_OPERATION_OPERATIONS.info, t('settings.store.loadSystemInfo'))
      const info = await fetchSystemInfo()
      const faissStatus = info.faissStatus
        ?? (info.indexStatus === 'building'
          ? 'building'
          : info.indexStatus === 'error'
            ? 'error'
            : 'ready')

      systemInfo.value = {
        backendVersion: info.backendVersion ?? info.version,
        uptime: info.uptime ?? systemInfo.value.uptime,
        faissStatus,
        faissDetail: info.faissDetail ?? undefined,
        vectorCount: info.vectorCount ?? systemInfo.value.vectorCount,
        cacheSize: info.cacheSize ?? systemInfo.value.cacheSize,
        corpusName: info.corpusName,
        tokenCount: info.tokenCount,
        documentCount: info.documentCount,
        lastUpdated: info.lastUpdated,
        source: info.source,
      }
      if (info.source === 'legacy_health_fallback') {
        systemInfoProvenance.value = degradedProvenance(
          t('settings.store.systemLegacy'),
          'legacy_fallback',
        )
      } else if (info.source === 'backend_degraded_fallback') {
        systemInfoProvenance.value = degradedProvenance(
          t('settings.store.systemDegraded'),
          'backend_degraded_fallback',
        )
      } else {
        systemInfoProvenance.value = freshProvenance(
          t('settings.store.systemLoaded'),
        )
      }
      localStorage.setItem('candyconc_system_info', JSON.stringify(systemInfo.value))
    } catch (error) {
      if (!isExpectedAccessRestriction(error)) {
        console.error('Failed to load system info from backend:', error)
      }
      if (isExpectedAccessRestriction(error)) {
        systemInfo.value = {
          ...systemInfo.value,
          faissStatus: 'unavailable',
          faissDetail: t('settings.store.systemNotEnabled'),
          vectorCount: 0,
          cacheSize: '0 MB',
          corpusName: t('settings.store.noCorpus'),
          tokenCount: 0,
          documentCount: 0,
          lastUpdated: undefined,
        }
        systemInfoProvenance.value = unavailableProvenance(
          t('settings.store.systemNotEnabled'),
        )
        return
      }
      try {
        const stored = localStorage.getItem('candyconc_system_info')
        if (stored) {
          systemInfo.value = { ...systemInfo.value, ...JSON.parse(stored) }
          systemInfoProvenance.value = staleCacheProvenance(
            t('settings.store.systemCached', { error: errorMessage(error) }),
          )
        } else {
          systemInfoProvenance.value = unavailableProvenance(
            t('settings.store.systemFailed', { error: errorMessage(error) }),
          )
        }
      } catch (localError) {
        console.error('Failed to load system info from localStorage:', localError)
        systemInfoProvenance.value = unavailableProvenance(
          t('settings.store.systemAndCacheFailed', { error: errorMessage(error) }),
        )
      }
    } finally {
      isLoading.value = false
    }
  }

  async function clearCache(): Promise<boolean> {
    try {
      if (!systemInfoIsFresh.value) {
        console.warn('System mutation blocked because system info is not fresh.')
        return false
      }
      await assertProductOperation(
        SYSTEM_OPERATION_OPERATIONS.clearCache,
        t('settings.store.clearCache'),
        {
          target: 'Server-Cache',
          impact: t('settings.store.clearCacheImpact'),
        },
      )
      await apiClearCache()
      await loadSystemInfo()
      return true
    } catch (error) {
      console.error('Failed to clear cache:', error)
      return false
    }
  }

  // Initialize
  function init(options: { loadPreferences?: boolean; loadEmbeddings?: boolean; loadSystemInfo?: boolean } = {}) {
    if (options.loadPreferences === false) {
      loadLocalPreferences()
    } else {
      loadPreferences()
    }
    if (options.loadEmbeddings !== false) {
      loadEmbeddings()
    }
    if (options.loadSystemInfo !== false) {
      loadSystemInfo()
    }
  }

  return {
    // State
    preferences,
    embeddings,
    localSemanticIndexPreflight,
    localSemanticIndexRun,
    localSemanticIndexError,
    isLoadingLocalSemanticIndex,
    embeddingBackend,
    embeddingBackendError,
    systemInfo,
    embeddingCatalogueProvenance,
    systemInfoProvenance,
    isLoading,
    downloadProgress,

    // Computed
    downloadedEmbeddings,
    availableEmbeddings,
    embeddingDownloadRunsByModelId,
    embeddingCatalogueIsFresh,
    systemInfoIsFresh,
    embeddingCatalogueIsStale,
    systemInfoIsStale,

    // Actions
    loadPreferences,
    loadLocalPreferences,
    savePreference,
    setLanguage,
    resetPreferences,
    confirmDeletion,
    loadEmbeddings,
    loadLocalSemanticIndexPreflight,
    refreshLocalSemanticIndexBuild,
    startLocalSemanticIndex,
    cancelLocalSemanticIndex,
    stopLocalSemanticIndexPolling,
    downloadEmbedding,
    refreshEmbeddingDownloadRun,
    removeEmbedding,
    loadEmbeddingBackend,
    setEmbeddingBackend,
    loadSystemInfo,
    stopEmbeddingDownloadPolling,
    clearCache,
    init,
  }
})
