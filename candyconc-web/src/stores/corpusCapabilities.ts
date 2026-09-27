/**
 * Corpus Capabilities Store
 *
 * Single source of truth for the list of available corpora, the active corpus,
 * and the per-corpus capability map exposed by the backend.
 *
 * ── Single source of truth for "active corpus" ──────────────────────────────
 * The active corpus name lives in exactly one place: `queryStore.filters.corpus`
 * (exposed read-only here as `activeCorpus`). Every search consumer (docset
 * store, KWIC loader, action handlers) already reads from that filter, so there
 * is one truth for "which corpus am I searching".
 *
 * `setActive()` is the ONLY mutator of that truth. It performs the backend
 * activation first, then reconciles the previously-divergent surfaces:
 *   1. backend default    → POST /corpora/{name}/activate  (server-side active)
 *   2. client filter      → queryStore.filters.corpus      (drives all queries)
 *   3. status bar / footer→ settingsStore.systemInfo       (re-fetched after #1)
 * plus the local `corpora[].active` badges, so the manager catalogue agrees too.
 *
 * Backend routes consumed:
 *   GET    /api/v1/corpora
 *   GET    /api/v1/corpora/{corpus}/capabilities
 *   GET    /api/v1/corpora/{corpus}/build-report
 *   POST   /api/v1/corpora/register
 *   POST   /api/v1/corpora/{corpus}/activate      (single source of truth sync)
 *   DELETE /api/v1/corpora/{corpus}/registration  (unregister)
 */

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'
import {
  getCorpora,
  getCorpusCapabilities,
  getCorpusBuildReport,
  activateCorpus as activateCorpusApi,
  registerCorpus as registerCorpusApi,
  unregisterCorpus as unregisterCorpusApi,
  type CorpusBuildReport,
  type CorpusSummary,
} from '@/api/client'
import {
  alignmentPairAxes,
  frequencyGroupOptions,
  hasPassageSearch,
  hasParallelGroups,
  hasParallelKwic,
  hasSemanticSearch,
  hasWordSimilarity,
  isCorpusPaired,
  queryAttributeOptions,
  simpleIntentOptions,
  supportsFrequencyGroup,
  supportsSimpleIntent,
  supportsTokenAttribute,
  type CorpusFrequencyGroup,
  type CorpusTokenAttribute,
} from '@/lib/corpusFeatureOptions'
import { useQueryStore } from './query'
import { DEFAULT_CORPUS_PREFERENCE, useSettingsStore } from './settings'
import {
  useProductCapabilitiesStore,
  type ProductOperationAccessOptions,
} from './productCapabilities'
import { t } from '@/i18n'
import { currentLocale } from '@/i18n/locale'
import { corpusDisplayName } from '@/lib/corpusDisplayName'

export type { CorpusSummary } from '@/api/client'

const DEFAULT_CORPUS = 'default'

export const CORPUS_CATALOGUE_OPERATIONS = {
  list: 'corpus.catalogue.list',
  register: 'corpus.catalogue.register',
  activate: 'corpus.catalogue.activate',
  capabilities: 'corpus.catalogue.capabilities',
  unregister: 'corpus.catalogue.unregister',
} as const

const CORPUS_IMPORT_BUILD_REPORT_OPERATION = 'corpus.import.build_report'

export const useCorpusCapabilitiesStore = defineStore('corpusCapabilities', () => {
  const queryStore = useQueryStore()

  // ============================================
  // State
  // ============================================

  const corpora = ref<CorpusSummary[]>([])
  const loaded = ref(false)
  const isLoading = ref(false)
  const error = ref<string | null>(null)
  const registerError = ref<string | null>(null)
  const buildReportError = ref<string | null>(null)
  const buildReportsByCorpus = ref<Record<string, CorpusBuildReport>>({})
  const isRegisteringExisting = ref(false)
  const loadingBuildReportFor = ref<string | null>(null)
  // Set while a backend activation round-trip is in flight, and to the error
  // message if `/activate` failed. Client query state is not switched until the
  // backend confirms activation, so UI and backend cannot drift silently.
  const isActivating = ref(false)
  const activationError = ref<string | null>(null)
  /** A successful activation that does not reach the copilot (server started with a pinned index). */
  const activationNotice = ref<string | null>(null)
  // Counts corpora confirmed as active, so fetchCorpora can recognise a
  // catalogue response requested before the latest confirmation.
  let confirmedActivations = 0
  let lastConfirmedCorpus: string | null = null

  // The active corpus is bound to the query store filter so it stays the single
  // source of truth shared with every search consumer.
  const activeCorpus = computed<string>(() => queryStore.filters.corpus ?? DEFAULT_CORPUS)

  // ============================================
  // Computed / Getters
  // ============================================

  const activeSummary = computed<CorpusSummary | null>(() => {
    const name = activeCorpus.value
    return corpora.value.find((corpus) => corpus.name === name) ?? null
  })
  /** The catalog answered and holds no corpus (first start with an empty data folder). */
  const catalogEmpty = computed<boolean>(() => loaded.value && !error.value && corpora.value.length === 0)
  /** Name to show for the active corpus (display_name, else the identifier). */
  const activeDisplayName = computed<string>(() => corpusDisplayName(activeSummary.value, activeCorpus.value))
  const activeCorpusTokenCount = computed<number>(() => activeSummary.value?.token_count ?? 0)
  const activeCorpusDocCount = computed<number>(() => activeSummary.value?.doc_count ?? 0)

  // Pairing axes available for the active corpus (empty when unpaired).
  const pairAxes = computed<string[]>(() => alignmentPairAxes(activeSummary.value))

  // Descriptor-backed alignment truth. Axes describe grouping dimensions; the
  // endpoint gates are the explicit `parallel_*` flags.
  const isPaired = computed<boolean>(() => isCorpusPaired(activeSummary.value))
  const canUseParallelGroups = computed<boolean>(() => hasParallelGroups(activeSummary.value))
  const canUseParallelKwic = computed<boolean>(() => hasParallelKwic(activeSummary.value))

  // Generic collocation-contrast works on any corpus (default true).
  const hasFreeContrast = computed<boolean>(
    () => activeSummary.value?.capabilities.free_contrast ?? true
  )

  const queryAttributes = computed(() => queryAttributeOptions(activeSummary.value))
  const cqlTokenAttributes = computed(() => queryAttributes.value.map((option) => option.cqlAttribute))
  const frequencyGroups = computed(() => frequencyGroupOptions(activeSummary.value))
  const simpleSearchIntents = computed(() => simpleIntentOptions(activeSummary.value))
  const hasSemantic = computed<boolean>(() => hasSemanticSearch(activeSummary.value))
  const hasSemanticPassageSearch = computed<boolean>(() => hasPassageSearch(activeSummary.value))
  const hasSemanticWordSimilarity = computed<boolean>(() => hasWordSimilarity(activeSummary.value))
  const activeFeatureSummary = computed(() => {
    const attrs = queryAttributes.value.map((option) => option.label).join(', ')
    const freq = frequencyGroups.value.map((option) => option.label).join(', ')
    return {
      queryAttributes: attrs || t('corpus.capabilitiesStore.defaultAttribute'),
      frequencyGroups: freq || t('corpus.capabilitiesStore.defaultFrequencyGroup'),
      semantic: hasSemantic.value,
      alignment: canUseParallelGroups.value || canUseParallelKwic.value,
    }
  })

  function can(capabilityKey: string): boolean {
    return activeSummary.value?.capabilities[capabilityKey] ?? false
  }

  function canUseTokenAttribute(attr: CorpusTokenAttribute): boolean {
    return supportsTokenAttribute(activeSummary.value, attr)
  }

  function canUseFrequencyGroup(group: CorpusFrequencyGroup): boolean {
    return supportsFrequencyGroup(activeSummary.value, group)
  }

  function canUseSimpleIntent(intent: 'exact' | 'lemma' | 'similar'): boolean {
    return supportsSimpleIntent(activeSummary.value, intent)
  }

  // ============================================
  // Actions
  // ============================================

  function _upsertSummary(summary: CorpusSummary) {
    const index = corpora.value.findIndex((corpus) => corpus.name === summary.name)
    const existing = index >= 0 ? corpora.value[index] : null
    const next = {
      ...(existing ?? {}),
      ...summary,
      active: summary.active ?? existing?.active ?? false,
    }
    if (index >= 0) {
      corpora.value.splice(index, 1, next)
    } else {
      corpora.value.push(next)
    }
  }

  async function assertProductOperation(
    operationId: string,
    fallbackLabel: string,
    options: ProductOperationAccessOptions = {},
  ): Promise<void> {
    await useProductCapabilitiesStore().assertProductOperationAccess(operationId, fallbackLabel, options)
  }

  /**
   * The corpus named as default corpus in the settings, once per session and
   * only when it is in the catalogue. The placeholder value follows the
   * catalogue, which remembers the last activated corpus.
   */
  let startupPreferenceTaken = false
  function takeStartupCorpusPreference(catalogue: CorpusSummary[]): string | null {
    if (startupPreferenceTaken) return null
    startupPreferenceTaken = true
    // A corpus in the address (deep link) outranks the preference.
    if (typeof window !== 'undefined' && new URLSearchParams(window.location.search).get('corpus')?.trim()) {
      return null
    }
    const preferred = useSettingsStore().preferences.defaultCorpus?.trim()
    if (!preferred || preferred === DEFAULT_CORPUS_PREFERENCE) return null
    return catalogue.some((corpus) => corpus.name === preferred) ? preferred : null
  }

  let catalogueRequested = false
  let catalogueRequestId = 0
  watch(currentLocale, () => {
    if (catalogueRequested) void fetchCorpora()
  })

  async function fetchCorpora(): Promise<void> {
    catalogueRequested = true
    const requestId = ++catalogueRequestId
    isLoading.value = true
    error.value = null
    try {
      await assertProductOperation(CORPUS_CATALOGUE_OPERATIONS.list, t('corpus.capabilitiesStore.loadCatalogue'))
      const confirmedBefore = confirmedActivations
      const result = await getCorpora()
      if (requestId !== catalogueRequestId) return
      corpora.value = result.corpora
      // An activation confirmed while the request ran is newer than the
      // active flag in this response.
      if (confirmedActivations !== confirmedBefore && lastConfirmedCorpus) {
        _markActiveLocally(lastConfirmedCorpus)
      }
      const catalogueActive = result.corpora.find((corpus) => corpus.active)?.name?.trim()
      const clientScopedCorpus = queryStore.filters.corpus?.trim()
      const startupCorpus = clientScopedCorpus ? null : takeStartupCorpusPreference(result.corpora)
      if (startupCorpus && startupCorpus !== catalogueActive) {
        // The default corpus from the settings is activated like a choice in
        // the corpus switcher. A refused activation keeps the catalogue state.
        await setActive(startupCorpus)
      }
      if (catalogueActive && !queryStore.filters.corpus?.trim()) {
        await _commitConfirmedActiveCorpus(catalogueActive, { refreshSystemInfo: false })
      }
      loaded.value = true
    } catch (err) {
      if (requestId === catalogueRequestId) {
        error.value = err instanceof Error ? err.message : t('corpus.capabilitiesStore.loadCorporaFailed')
      }
    } finally {
      if (requestId === catalogueRequestId) isLoading.value = false
    }
  }

  async function fetchCapabilities(name: string): Promise<CorpusSummary | null> {
    try {
      await assertProductOperation(CORPUS_CATALOGUE_OPERATIONS.capabilities, t('corpus.capabilitiesStore.loadCapabilities'))
      const summary = await getCorpusCapabilities(name)
      _upsertSummary(summary)
      return summary
    } catch (err) {
      error.value = err instanceof Error ? err.message : t('corpus.capabilitiesStore.loadCapabilitiesFailed')
      return null
    }
  }

  /**
   * Register an already-built corpus directory. This covers the backend
   * `/corpora/register` route and is intentionally separate from import jobs:
   * no files are converted or copied here.
   */
  async function registerExisting(path: string, activate = false): Promise<CorpusSummary | null> {
    const trimmedPath = path.trim()
    if (!trimmedPath) {
      registerError.value = t('corpus.capabilitiesStore.pathMissing')
      return null
    }
    isRegisteringExisting.value = true
    registerError.value = null
    try {
      await assertProductOperation(CORPUS_CATALOGUE_OPERATIONS.register, t('corpus.capabilitiesStore.registerExisting'))
      const summary = await registerCorpusApi(trimmedPath, activate)
      _upsertSummary(summary)
      if (activate || summary.active) {
        await _commitConfirmedActiveCorpus(summary.name)
      }
      await fetchCorpora()
      return summary
    } catch (err) {
      registerError.value = err instanceof Error ? err.message : t('corpus.capabilitiesStore.registerFailed')
      return null
    } finally {
      isRegisteringExisting.value = false
    }
  }

  async function loadBuildReport(name: string): Promise<CorpusBuildReport | null> {
    if (!name) return null
    loadingBuildReportFor.value = name
    buildReportError.value = null
    try {
      await assertProductOperation(CORPUS_IMPORT_BUILD_REPORT_OPERATION, t('corpus.capabilitiesStore.loadBuildReport'))
      const report = await getCorpusBuildReport(name)
      buildReportsByCorpus.value = { ...buildReportsByCorpus.value, [name]: report }
      return report
    } catch (err) {
      buildReportError.value = err instanceof Error ? err.message : t('corpus.capabilitiesStore.loadBuildReportFailed')
      return null
    } finally {
      loadingBuildReportFor.value = null
    }
  }

  // Reset all per-corpus query state when the active corpus changes so stale
  // KWIC rows / counts from the previous corpus never bleed into the new scope.
  function _resetQueryScope() {
    queryStore.cancelStreaming()
    queryStore.setLoading(false)
    queryStore.setResults([], 0, false)
    queryStore.deselectAll()
    queryStore.setHighlightedRow(null)
    queryStore.setHasMore(false)
    queryStore.setHasPrevious(false)
    queryStore.setNextOffset(0)
    queryStore.setResultOffsetStart(0)
    queryStore.setLastExecutedAt(null)
  }

  // Keep the local `active` badge in sync so the manager catalogue agrees with
  // the single source of truth (exactly one corpus is flagged active).
  function _markActiveLocally(name: string) {
    corpora.value = corpora.value.map((corpus) => ({
      ...corpus,
      active: corpus.name === name,
    }))
  }

  async function _commitConfirmedActiveCorpus(name: string, options: { refreshSystemInfo?: boolean } = {}) {
    confirmedActivations += 1
    lastConfirmedCorpus = name
    const changed = activeCorpus.value !== name
    queryStore.setFilters({ corpus: name })
    if (changed) {
      _resetQueryScope()
    }
    _markActiveLocally(name)
    void fetchCapabilities(name)
    if (options.refreshSystemInfo !== false) {
      const settingsStore = useSettingsStore()
      await settingsStore.loadSystemInfo()
    }
  }

  async function syncBackendActiveCorpus(preferredName?: string): Promise<boolean> {
    const preferred = preferredName?.trim()
    isActivating.value = true
    activationError.value = null
    try {
      await fetchCorpora()
      const settingsStore = useSettingsStore()
      await settingsStore.loadSystemInfo()
      const catalogueActive = corpora.value.find((corpus) => corpus.active)?.name ?? null
      const systemActive = settingsStore.systemInfo.corpusName?.trim() || null
      const confirmed = catalogueActive ?? systemActive
      if (!confirmed) {
        activationError.value = t('corpus.capabilitiesStore.activationUnconfirmed')
        return false
      }
      if (preferred && confirmed !== preferred) {
        activationError.value = t('corpus.capabilitiesStore.activationMismatch', { confirmed, preferred })
        return false
      }
      await _commitConfirmedActiveCorpus(confirmed, { refreshSystemInfo: false })
      return true
    } catch (err) {
      activationError.value =
        err instanceof Error ? err.message : t('corpus.capabilitiesStore.activationSyncFailed')
      return false
    } finally {
      isActivating.value = false
    }
  }

  /**
   * Switch the active corpus. This is the single mutator of the active-corpus
   * truth and reconciles all four previously-divergent surfaces:
   *   - backend default — POST /corpora/{name}/activate
   *   - client filter (queryStore.filters.corpus) — switched only after backend success
   *   - status bar / footer — settingsStore.loadSystemInfo() after activate
   *   - manager "active" badge — corpora[].active
   *
   * Activation intentionally fails closed. A rejected backend activation leaves
   * the current query corpus, catalogue badge, and status bar untouched.
   *
   * Activations run one at a time, in the order they were requested, so the
   * backend receives the latest choice last and the client commits what the
   * backend confirmed. A request replaced by a newer one before it was sent is
   * dropped. Overlapping requests otherwise let the slower response decide,
   * for example the default corpus from the settings over a corpus the user
   * picked while that activation was still running.
   */
  let activationQueue: Promise<void> = Promise.resolve()
  let latestActivationRequest = 0

  async function setActive(
    name: string,
    options: { acknowledgePartialInput?: boolean } = {},
  ): Promise<void> {
    if (!name) return
    try {
      await assertProductOperation(CORPUS_CATALOGUE_OPERATIONS.activate, t('corpus.capabilitiesStore.activate'))
    } catch (err) {
      activationError.value =
        err instanceof Error ? err.message : t('corpus.capabilitiesStore.activationNotEnabled')
      return
    }
    const request = ++latestActivationRequest
    const previous = activationQueue
    let settle: () => void = () => {}
    activationQueue = new Promise<void>((resolve) => {
      settle = resolve
    })
    isActivating.value = true
    activationError.value = null
    activationNotice.value = null
    try {
      await previous
      if (request !== latestActivationRequest) return
      const summary = options.acknowledgePartialInput
        ? await activateCorpusApi(name, options)
        : await activateCorpusApi(name)
      activationNotice.value = summary.activation_notice ?? null
      _upsertSummary(summary)
      await _commitConfirmedActiveCorpus(summary.name)
    } catch (err) {
      if (request === latestActivationRequest) {
        activationError.value =
          err instanceof Error ? err.message : t('corpus.capabilitiesStore.activationFailed')
      }
    } finally {
      settle()
      if (request === latestActivationRequest) isActivating.value = false
    }
  }

  /**
   * Unregister a corpus from the backend registry (does not delete files).
   * Refreshes the corpus list afterwards; if the unregistered corpus was the
   * active one, falls back to the new backend default.
   */
  async function unregister(name: string): Promise<void> {
    if (!name) return
    activationError.value = null
    try {
      await assertProductOperation(
        CORPUS_CATALOGUE_OPERATIONS.unregister,
        t('corpus.capabilitiesStore.unregister'),
        {
          target: name,
          impact: t('corpus.capabilitiesStore.unregisterImpact'),
        },
      )
    } catch (err) {
      activationError.value =
        err instanceof Error ? err.message : t('corpus.capabilitiesStore.unregisterNotEnabled')
      return
    }
    await unregisterCorpusApi(name)
    const wasActive = activeCorpus.value === name
    await fetchCorpora()
    if (wasActive) {
      // The backend picks a new default; re-sync the client truth to it.
      const settingsStore = useSettingsStore()
      await settingsStore.loadSystemInfo()
      const fallback =
        corpora.value.find((corpus) => corpus.active)?.name ??
        settingsStore.systemInfo.corpusName ??
        DEFAULT_CORPUS
      queryStore.setFilters({ corpus: fallback })
      _resetQueryScope()
    }
  }

  return {
    // State
    corpora,
    loaded,
    catalogEmpty,
    isLoading,
    error,
    registerError,
    buildReportError,
    buildReportsByCorpus,
    isActivating,
    activationError,
    activationNotice,
    isRegisteringExisting,
    loadingBuildReportFor,
    // Computed
    activeCorpus,
    activeSummary,
    activeDisplayName,
    activeCorpusTokenCount,
    activeCorpusDocCount,
    isPaired,
    pairAxes,
    canUseParallelGroups,
    canUseParallelKwic,
    hasFreeContrast,
    queryAttributes,
    cqlTokenAttributes,
    frequencyGroups,
    simpleSearchIntents,
    hasSemantic,
    hasSemanticPassageSearch,
    hasSemanticWordSimilarity,
    activeFeatureSummary,
    // Getters
    can,
    canUseTokenAttribute,
    canUseFrequencyGroup,
    canUseSimpleIntent,
    // Actions
    fetchCorpora,
    fetchCapabilities,
    registerExisting,
    loadBuildReport,
    setActive,
    syncBackendActiveCorpus,
    unregister,
  }
})
