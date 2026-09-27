<script setup lang="ts">
/**
 * EmbeddingsManager - Manage embedding models for semantic search
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  EMBEDDING_MANAGEMENT_OPERATIONS,
  useSettingsStore,
} from '@/stores/settings'
import { useUiStore } from '@/stores/ui'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import {
  AlertTriangle,
  Brain,
  CheckCircle2,
  Cpu,
  Download,
  HardDrive,
  Play,
  RefreshCw,
  Square,
  Trash2,
} from 'lucide-vue-next'
import LoadingSpinner from '@/components/ui/LoadingSpinner.vue'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const settingsStore = useSettingsStore()
const uiStore = useUiStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const buildScope = ref<'doc' | 'both'>('doc')
const scopeWasChosen = ref(false)

const preflight = computed(() => settingsStore.localSemanticIndexPreflight)
const localBuildRun = computed(() => settingsStore.localSemanticIndexRun)
const localBuildError = computed(() => settingsStore.localSemanticIndexError)
const activeCorpus = computed(() => corpusCapabilities.activeCorpus)
const isLocalBuildRunning = computed(() =>
  localBuildRun.value?.status === 'queued' || localBuildRun.value?.status === 'running'
)
const localBuildAvailability = computed(() =>
  productCapabilities.productOperationAvailability(EMBEDDING_MANAGEMENT_OPERATIONS.localIndexBuild)
)
const localCancelAvailability = computed(() =>
  productCapabilities.productOperationAvailability(EMBEDDING_MANAGEMENT_OPERATIONS.localIndexCancel)
)
const selectedOption = computed(() => preflight.value?.options[buildScope.value] ?? null)
const selectedEstimate = computed(() => preflight.value?.estimates[buildScope.value] ?? null)
const selectedAlreadyAvailable = computed(() => {
  if (!preflight.value) return false
  return buildScope.value === 'doc'
    ? preflight.value.available_levels.doc
    : preflight.value.available_levels.doc && preflight.value.available_levels.sentence
})
const canStartLocalBuild = computed(() =>
  Boolean(
    preflight.value?.platform.supported &&
    selectedOption.value?.can_build &&
    !selectedAlreadyAvailable.value &&
    !isLocalBuildRunning.value &&
    localBuildAvailability.value.enabled
  )
)
const canCancelLocalBuild = computed(() =>
  Boolean(
    isLocalBuildRunning.value &&
    localBuildRun.value?.evidence?.cancellable !== false &&
    localCancelAvailability.value.enabled
  )
)
const isResumable = computed(() =>
  Boolean(localBuildRun.value && ['failed', 'cancelled', 'stale'].includes(localBuildRun.value.status))
)

function formatBytes(bytes: number | null | undefined): string {
  if (!bytes || bytes <= 0) return '0 GB'
  const gib = bytes / 1024 ** 3
  return `${gib >= 10 ? Math.round(gib) : Math.round(gib * 10) / 10} GB`
}

function formatEta(raw: unknown): string | null {
  const seconds = typeof raw === 'number' && Number.isFinite(raw) ? Math.max(0, raw) : null
  if (seconds === null) return null
  if (seconds < 90) return t('settings.embeddings.etaUnderTwo')
  const hours = Math.floor(seconds / 3600)
  const minutes = Math.ceil((seconds % 3600) / 60)
  return hours > 0
    ? t('settings.embeddings.etaHours', { hours, minutes })
    : t('settings.embeddings.etaMinutes', { minutes })
}

const localBuildEta = computed(() => formatEta(localBuildRun.value?.evidence?.eta_seconds))

function selectBuildScope(scope: 'doc' | 'both') {
  scopeWasChosen.value = true
  buildScope.value = scope
}

async function refreshLocalPreflight() {
  if (!corpusCapabilities.loaded) await corpusCapabilities.fetchCorpora()
  await settingsStore.loadLocalSemanticIndexPreflight(activeCorpus.value)
  if (!scopeWasChosen.value && preflight.value) {
    const resumableLevels = preflight.value.resumable_run?.levels ?? []
    if (
      resumableLevels.includes('sentence') ||
      (preflight.value.available_levels.doc && !preflight.value.available_levels.sentence)
    ) {
      buildScope.value = 'both'
    }
  }
}

async function handleLocalBuild() {
  if (!canStartLocalBuild.value) return
  const levels: Array<'doc' | 'sentence'> = buildScope.value === 'both'
    ? ['doc', 'sentence']
    : ['doc']
  const started = await settingsStore.startLocalSemanticIndex(activeCorpus.value, levels)
  if (started) uiStore.showToast(t('settings.embeddings.buildStarted'), 'info')
  else uiStore.showToast(localBuildError.value ?? t('settings.embeddings.buildFailed'), 'error')
}

async function handleLocalCancel() {
  const runId = localBuildRun.value?.run_id
  if (!runId || !canCancelLocalBuild.value) return
  const cancelled = await settingsStore.cancelLocalSemanticIndex(runId)
  if (cancelled) uiStore.showToast(t('settings.embeddings.buildCancelled'), 'info')
}

onMounted(() => {
  void refreshLocalPreflight()
  void settingsStore.loadEmbeddingBackend()
})

watch(activeCorpus, () => {
  scopeWasChosen.value = false
  buildScope.value = 'doc'
  void refreshLocalPreflight()
})

watch(
  () => localBuildRun.value?.status,
  (status) => {
    if (status === 'succeeded') void corpusCapabilities.fetchCapabilities(activeCorpus.value)
  },
)

onBeforeUnmount(() => {
  settingsStore.stopLocalSemanticIndexPolling()
})

const downloadedModels = computed(() => settingsStore.downloadedEmbeddings)
const availableModels = computed(() => settingsStore.availableEmbeddings)
const embeddingBackend = computed(() => settingsStore.embeddingBackend)
const SPACY_MODEL_USE_KEYS: Record<string, string> = {
  passage_queries: 'settings.embeddings.backendUse.passageQueries',
  copilot_word_clusters: 'settings.embeddings.backendUse.copilotWordClusters',
  fallback: 'settings.embeddings.backendUse.fallback',
}
/** What the default pipeline embeds, in words. Unknown codes stay as sent. */
const spacyModelUses = computed(() =>
  (embeddingBackend.value?.spacyModelUsedFor ?? []).map((code) => {
    const key = SPACY_MODEL_USE_KEYS[code]
    return key ? t(key) : code
  })
)
const activeCorpusName = computed(() => corpusCapabilities.activeDisplayName || activeCorpus.value)
/** Where the active corpus takes its word vectors from (server `word_vectors`). */
const activeWordVectorsText = computed(() => {
  const entry = (embeddingBackend.value?.wordVectors ?? []).find((item) => item.corpus === activeCorpus.value)
  if (!entry) return null
  const corpus = activeCorpusName.value
  if (!entry.available) return t('settings.embeddings.corpusVectorsNone', { corpus, reason: entry.reason })
  if (entry.source === 'word_index') return t('settings.embeddings.corpusVectorsIndex', { corpus })
  return t('settings.embeddings.corpusVectorsPipeline', { corpus, pipeline: entry.pipeline ?? '' })
})
const embeddingBackendError = computed(() => settingsStore.embeddingBackendError)
const backendOptions = computed(() => {
  const supported = embeddingBackend.value?.supportedBackends ?? []
  return supported.length ? supported : ['spacy', 'none']
})
const switchingBackend = ref(false)
/**
 * Limits of the embedding capability from the server contract. They say what
 * the backend and the package list do. Older servers send none, the catalog
 * note stands in.
 */
const embeddingLimits = computed(() =>
  productCapabilities.capabilityFor('settings.embedding_management')?.limits?.filter(Boolean) ?? []
)
const embeddingCatalogueProvenance = computed(() => settingsStore.embeddingCatalogueProvenance)
const embeddingCatalogueIsFresh = computed(() => settingsStore.embeddingCatalogueIsFresh)
const embeddingTrustMessage = computed(() =>
  embeddingCatalogueProvenance.value.freshness === 'fresh'
    ? null
    : embeddingCatalogueProvenance.value.message
)
const downloadProgress = computed(() => settingsStore.downloadProgress)
const downloadRuns = computed(() => settingsStore.embeddingDownloadRunsByModelId)
const downloadAvailability = computed(() =>
  productCapabilities.productOperationAvailability(EMBEDDING_MANAGEMENT_OPERATIONS.download)
)
const removeAvailability = computed(() =>
  productCapabilities.productOperationAvailability(EMBEDDING_MANAGEMENT_OPERATIONS.remove)
)
const activateAvailability = computed(() =>
  productCapabilities.productOperationAvailability(EMBEDDING_MANAGEMENT_OPERATIONS.setActive)
)
const canDownloadEmbeddings = computed(() =>
  downloadAvailability.value.enabled && embeddingCatalogueIsFresh.value
)
const canRemoveEmbeddings = computed(() =>
  removeAvailability.value.enabled && embeddingCatalogueIsFresh.value
)
const canSwitchBackend = computed(() => activateAvailability.value.enabled && !switchingBackend.value)
const staleEmbeddingActionMessage = computed(() => t('settings.embeddings.catalogueStale'))
const downloadAccessMessage = computed(() =>
  !embeddingCatalogueIsFresh.value ? staleEmbeddingActionMessage.value : downloadAvailability.value.disabledReason
)
const removeAccessMessage = computed(() =>
  !embeddingCatalogueIsFresh.value ? staleEmbeddingActionMessage.value : removeAvailability.value.disabledReason
)

function downloadRunStatusLabel(modelId: string): string {
  const status = downloadRuns.value[modelId]?.status
  if (status === 'queued') return t('settings.embeddings.runQueued')
  if (status === 'running') return t('settings.embeddings.runRunning')
  if (status === 'succeeded') return t('settings.embeddings.runSucceeded')
  if (status === 'failed') return t('settings.embeddings.runFailed')
  if (status === 'cancelled') return t('settings.embeddings.runCancelled')
  if (status === 'stale') return t('settings.embeddings.runStale')
  return t('settings.embeddings.runChecking')
}

function downloadRunMessage(modelId: string): string {
  const run = downloadRuns.value[modelId]
  return run?.error ?? run?.message ?? t('settings.embeddings.runObserved')
}

async function handleDownload(modelId: string) {
  if (!canDownloadEmbeddings.value) {
    uiStore.showToast(downloadAccessMessage.value ?? t('settings.embeddings.downloadNotEnabled'), 'warning')
    return
  }
  const result = await settingsStore.downloadEmbedding(modelId)
  if (result === 'installed') {
    uiStore.showToast(t('settings.embeddings.installed'), 'success')
  } else if (result === 'queued') {
    uiStore.showToast(t('settings.embeddings.downloadQueued'), 'info')
  } else {
    uiStore.showToast(t('settings.embeddings.downloadFailed'), 'error')
  }
}

async function handleRemove(modelId: string) {
  if (!canRemoveEmbeddings.value) {
    uiStore.showToast(removeAccessMessage.value ?? t('settings.embeddings.removeNotEnabled'), 'warning')
    return
  }
  const success = await settingsStore.removeEmbedding(modelId)
  if (success) {
    uiStore.showToast(t('settings.embeddings.removed'), 'info')
  }
}

function backendLabel(backend: string): string {
  if (backend === 'spacy') return t('settings.embeddings.backendSpacy')
  if (backend === 'none') return t('settings.embeddings.backendNone')
  return backend
}

async function handleBackend(backend: string) {
  if (embeddingBackend.value?.backend === backend) return
  if (!canSwitchBackend.value) {
    uiStore.showToast(activateAvailability.value.disabledReason ?? t('settings.embeddings.backendNotEnabled'), 'warning')
    return
  }
  switchingBackend.value = true
  try {
    const success = await settingsStore.setEmbeddingBackend(backend)
    if (success) uiStore.showToast(t('settings.embeddings.backendSwitched', { backend: backendLabel(backend) }), 'success')
    else uiStore.showToast(embeddingBackendError.value ?? t('settings.embeddings.backendSwitchFailed'), 'error')
  } finally {
    switchingBackend.value = false
  }
}
</script>

<template>
  <div class="embeddings-manager">
    <div class="section-header">
      <Brain class="w-5 h-5 text-primary-500" />
      <div>
        <h3 class="section-title">{{ t('settings.embeddings.title') }}</h3>
        <p class="section-description">
          {{ t('settings.embeddings.description') }}
        </p>
      </div>
    </div>

    <div
      v-if="embeddingTrustMessage"
      class="cache-warning"
      data-testid="embedding-provenance"
    >
      {{ embeddingTrustMessage }}
    </div>

    <section class="local-index-tool" data-testid="local-semantic-index">
      <div class="local-index-heading">
        <div>
          <h4>{{ t('settings.embeddings.localIndex') }}</h4>
          <p>{{ corpusCapabilities.activeDisplayName }}</p>
        </div>
        <button
          type="button"
          class="icon-button"
          :title="t('settings.embeddings.refreshPreflight')"
          :aria-label="t('settings.embeddings.refreshPreflight')"
          :disabled="settingsStore.isLoadingLocalSemanticIndex"
          @click="refreshLocalPreflight"
        >
          <RefreshCw
            class="w-4 h-4"
            :class="{ 'animate-spin': settingsStore.isLoadingLocalSemanticIndex }"
          />
        </button>
      </div>

      <div v-if="settingsStore.isLoadingLocalSemanticIndex && !preflight" class="local-index-loading">
        <LoadingSpinner />
        <span>{{ t('settings.embeddings.checkingSystem') }}</span>
      </div>

      <div v-else-if="localBuildError && !preflight" class="local-index-warning">
        <AlertTriangle class="w-4 h-4" />
        <span>{{ localBuildError }}</span>
      </div>

      <template v-else-if="preflight">
        <div
          v-if="!preflight.platform.supported"
          class="local-index-warning"
          data-testid="local-semantic-index-unsupported"
        >
          <AlertTriangle class="w-4 h-4" />
          <span>{{ t('settings.embeddings.appleSiliconOnly') }}</span>
        </div>

        <div v-else class="local-index-facts">
          <span><Cpu class="w-4 h-4" /> {{ formatBytes(preflight.platform.memory_bytes) }} RAM</span>
          <span><HardDrive class="w-4 h-4" /> {{ t('settings.embeddings.diskFree', { size: formatBytes(preflight.disk.free_bytes) }) }}</span>
          <span>{{ t('settings.embeddings.documents', { count: formatNumber(preflight.counts.documents) }) }}</span>
          <span>{{ t('settings.embeddings.sentences', { count: formatNumber(preflight.counts.sentences) }) }}</span>
        </div>

        <div v-if="preflight.platform.supported" class="scope-control" :aria-label="t('settings.embeddings.indexScope')">
          <button
            type="button"
            :class="{ active: buildScope === 'doc' }"
            @click="selectBuildScope('doc')"
          >
            {{ t('settings.embeddings.scopeDocuments') }}
            <CheckCircle2 v-if="preflight.available_levels.doc" class="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            :class="{ active: buildScope === 'both' }"
            @click="selectBuildScope('both')"
          >
            {{ t('settings.embeddings.scopeBoth') }}
            <CheckCircle2
              v-if="preflight.available_levels.doc && preflight.available_levels.sentence"
              class="w-3.5 h-3.5"
            />
          </button>
        </div>

        <div v-if="preflight.platform.supported && selectedEstimate && selectedOption" class="resource-summary">
          <div>
            <span>{{ t('settings.embeddings.indexSize') }}</span>
            <strong>{{ formatBytes(selectedEstimate.final_bytes) }}</strong>
          </div>
          <div>
            <span>{{ t('settings.embeddings.freeSpaceRequired') }}</span>
            <strong>{{ formatBytes(selectedOption.required_free_bytes) }}</strong>
          </div>
          <div>
            <span>{{ t('settings.embeddings.searchMemory') }}</span>
            <strong>{{ formatBytes(selectedEstimate.warm_search_bytes) }}</strong>
          </div>
          <div>
            <span>{{ t('settings.embeddings.model') }}</span>
            <strong>EmbeddingGemma 300M</strong>
          </div>
        </div>

        <div v-for="warning in preflight.warnings" :key="warning" class="local-index-warning compact">
          <AlertTriangle class="w-4 h-4" />
          <span>{{ warning }}</span>
        </div>

        <div v-if="localBuildRun" class="local-build-status" data-testid="local-semantic-index-run">
          <div class="local-build-status-heading">
            <strong>{{ localBuildRun.message }}</strong>
            <span>{{ localBuildRun.progress ?? 0 }} %</span>
          </div>
          <div class="progress-track" :aria-label="t('settings.embeddings.buildProgress')">
            <span :style="{ width: `${localBuildRun.progress ?? 0}%` }" />
          </div>
          <div class="local-build-meta">
            <span>{{ localBuildRun.phase }}</span>
            <span v-if="localBuildEta">{{ localBuildEta }}</span>
          </div>
          <p v-if="localBuildRun.error" class="local-build-error">{{ localBuildRun.error }}</p>
        </div>

        <div v-if="preflight.platform.supported" class="local-index-actions">
          <span v-if="selectedAlreadyAvailable" class="available-state">
            <CheckCircle2 class="w-4 h-4" /> {{ t('settings.embeddings.available') }}
          </span>
          <button
            v-else
            type="button"
            class="btn-local-build"
            :disabled="!canStartLocalBuild"
            :title="localBuildAvailability.disabledReason ?? t('settings.embeddings.createIndex')"
            @click="handleLocalBuild"
          >
            <Play class="w-4 h-4" />
            <span>{{ isResumable ? t('settings.embeddings.resume') : t('settings.embeddings.create') }}</span>
          </button>
          <button
            v-if="isLocalBuildRunning"
            type="button"
            class="btn-local-cancel"
            :disabled="!canCancelLocalBuild"
            :title="t('settings.embeddings.cancelBuild')"
            @click="handleLocalCancel"
          >
            <Square class="w-4 h-4" />
            <span>{{ t('settings.embeddings.cancel') }}</span>
          </button>
        </div>
      </template>
    </section>

    <!-- Embedding backend of the server: spacy or none -->
    <section v-if="embeddingBackend" class="backend-section" data-testid="embedding-backend">
      <h4 class="group-title">{{ t('settings.embeddings.backendTitle') }}</h4>
      <p class="section-description">{{ t('settings.embeddings.backendDescription') }}</p>
      <div class="backend-toggle" role="radiogroup" :aria-label="t('settings.embeddings.backendTitle')">
        <button
          v-for="option in backendOptions"
          :key="option"
          type="button"
          role="radio"
          class="backend-option"
          :class="{ active: embeddingBackend.backend === option }"
          :data-embedding-backend="option"
          :aria-checked="embeddingBackend.backend === option ? 'true' : 'false'"
          :disabled="!canSwitchBackend"
          :title="activateAvailability.enabled ? backendLabel(option) : activateAvailability.disabledReason ?? t('settings.general.notEnabled')"
          @click="handleBackend(option)"
        >
          {{ backendLabel(option) }}
        </button>
      </div>
      <p v-if="activeWordVectorsText" class="backend-model" data-testid="corpus-word-vectors">{{ activeWordVectorsText }}</p>
      <p v-if="embeddingBackend.spacyModel" class="backend-model">
        {{ t('settings.embeddings.backendModel', { model: embeddingBackend.spacyModel }) }}
        <template v-if="spacyModelUses.length">{{ t('settings.embeddings.backendModelUses') }}</template>
      </p>
      <ul v-if="embeddingBackend.spacyModel && spacyModelUses.length" class="backend-model-uses">
        <li v-for="use in spacyModelUses" :key="use">{{ use }}</li>
      </ul>
    </section>
    <p v-else-if="embeddingBackendError" class="backend-error" role="alert">{{ embeddingBackendError }}</p>

    <!-- Downloaded Models -->
    <div v-if="downloadedModels.length > 0" class="model-group">
      <h4 class="group-title">{{ t('settings.embeddings.installedVectors') }}</h4>
      <div class="model-list">
        <div
          v-for="model in downloadedModels"
          :key="model.id"
          class="model-card"
        >
          <div class="model-info">
            <div class="model-name">
              {{ model.name }}
            </div>
            <div class="model-meta">
              <span><HardDrive class="w-3.5 h-3.5" /> {{ model.size }}</span>
              <span>{{ (model.language ?? 'multi').toUpperCase() }}</span>
            </div>
          </div>
          <div class="model-actions">
            <button
              type="button"
              class="btn-remove"
              :disabled="!canRemoveEmbeddings"
              :title="!canRemoveEmbeddings ? removeAccessMessage ?? t('settings.general.notEnabled') : t('settings.embeddings.removeModel')"
              @click="handleRemove(model.id)"
            >
              <Trash2 class="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Available Models -->
    <div v-if="availableModels.length > 0" class="model-group">
      <h4 class="group-title">{{ t('settings.embeddings.additionalVectors') }}</h4>
      <div class="model-list">
        <div
          v-for="model in availableModels"
          :key="model.id"
          class="model-card"
        >
          <div class="model-info">
            <div class="model-name">{{ model.name }}</div>
            <div class="model-meta">
              <span><HardDrive class="w-3.5 h-3.5" /> {{ model.size }}</span>
              <span>{{ (model.language ?? 'multi').toUpperCase() }}</span>
            </div>
          </div>
          <div class="model-actions">
            <button
              v-if="downloadProgress[model.id] === undefined"
              type="button"
              class="btn-download"
              :disabled="!canDownloadEmbeddings"
              :title="!canDownloadEmbeddings ? downloadAccessMessage ?? t('settings.general.notEnabled') : t('settings.embeddings.downloadModel')"
              @click="handleDownload(model.id)"
            >
              <Download class="w-4 h-4" />
              <span>{{ t('settings.embeddings.download') }}</span>
            </button>
            <div v-else class="download-progress">
              <LoadingSpinner
                variant="progress"
                :progress="downloadProgress[model.id]"
              />
              <div class="download-status">
                <strong>{{ downloadRunStatusLabel(model.id) }}</strong>
                <span>{{ downloadRunMessage(model.id) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- Empty State -->
    <div v-if="downloadedModels.length === 0 && availableModels.length === 0" class="empty-state">
      <Brain class="w-12 h-12 text-neutral-300 dark:text-neutral-600" />
      <p>{{ t('settings.embeddings.noPackages') }}</p>
    </div>

    <!-- Info Box -->
    <div class="info-box">
      <h4>{{ t('settings.embeddings.noteTitle') }}</h4>
      <template v-if="embeddingLimits.length">
        <p v-for="limit in embeddingLimits" :key="limit">{{ limit }}</p>
      </template>
      <p v-else>
        {{ t('settings.embeddings.note') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.embeddings-manager {
  @apply space-y-6;
}

.section-header {
  @apply flex items-start gap-3;
  @apply pb-4 border-b border-neutral-200 dark:border-neutral-700;
}

.section-title {
  @apply text-base font-semibold;
  @apply text-neutral-900 dark:text-neutral-100;
}

.section-description {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.cache-warning {
  @apply rounded-xl border border-warning-200 bg-warning-50 p-3 text-sm;
  @apply text-warning-700 dark:border-warning-800 dark:bg-warning-900/20 dark:text-warning-300;
}

.local-index-tool {
  @apply space-y-4 border-y border-neutral-200 py-4;
  @apply dark:border-neutral-700;
}

.local-index-heading {
  @apply flex items-center justify-between gap-4;
}

.local-index-heading h4 {
  @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.local-index-heading p {
  @apply mt-0.5 truncate text-xs text-neutral-500 dark:text-neutral-400;
}

.icon-button {
  @apply grid h-8 w-8 flex-none place-items-center rounded-md;
  @apply text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800;
  @apply disabled:cursor-not-allowed disabled:opacity-50;
  @apply dark:text-neutral-400 dark:hover:bg-neutral-800 dark:hover:text-neutral-100;
}

.local-index-loading,
.local-index-warning {
  @apply flex items-center gap-2 text-sm;
}

.local-index-loading {
  @apply text-neutral-500 dark:text-neutral-400;
}

.local-index-warning {
  @apply rounded-md border border-warning-200 bg-warning-50 p-3 text-warning-800;
  @apply dark:border-warning-800 dark:bg-warning-900/20 dark:text-warning-200;
}

.local-index-warning.compact {
  @apply py-2 text-xs;
}

.local-index-facts {
  @apply grid grid-cols-2 gap-x-4 gap-y-2 text-xs text-neutral-600;
  @apply dark:text-neutral-300;
}

.local-index-facts span {
  @apply flex min-w-0 items-center gap-1.5;
}

.scope-control {
  @apply grid grid-cols-2 rounded-md bg-neutral-100 p-1 dark:bg-neutral-800;
}

.scope-control button {
  @apply flex min-h-9 items-center justify-center gap-2 rounded px-3 text-xs font-medium;
  @apply text-neutral-600 transition-colors dark:text-neutral-300;
}

.scope-control button.active {
  @apply bg-white text-neutral-900 shadow-sm dark:bg-neutral-700 dark:text-white;
}

.resource-summary {
  @apply grid grid-cols-2 gap-x-5 gap-y-3;
}

.resource-summary div {
  @apply flex min-w-0 flex-col gap-0.5;
}

.resource-summary span,
.local-build-meta {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.resource-summary strong {
  @apply break-words text-sm font-medium leading-tight text-neutral-900 dark:text-neutral-100;
}

.local-build-status {
  @apply space-y-2 rounded-md border border-neutral-200 bg-neutral-50 p-3;
  @apply dark:border-neutral-700 dark:bg-neutral-800/60;
}

.local-build-status-heading,
.local-build-meta,
.local-index-actions {
  @apply flex items-center justify-between gap-3;
}

.local-build-status-heading {
  @apply text-xs text-neutral-800 dark:text-neutral-200;
}

.progress-track {
  @apply h-1.5 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-700;
}

.progress-track span {
  @apply block h-full bg-primary-600 transition-[width];
}

.local-build-error {
  @apply text-xs text-error-600 dark:text-error-400;
}

.local-index-actions {
  @apply justify-end;
}

.available-state {
  @apply inline-flex items-center gap-1.5 text-sm font-medium text-success-700;
  @apply dark:text-success-300;
}

.btn-local-build,
.btn-local-cancel {
  @apply inline-flex min-h-9 items-center gap-2 rounded-md px-3 text-sm font-medium;
  @apply transition-colors disabled:cursor-not-allowed disabled:opacity-50;
}

.btn-local-build {
  @apply bg-primary-600 text-white hover:bg-primary-700;
}

.btn-local-cancel {
  @apply border border-neutral-300 text-neutral-700 hover:bg-neutral-100;
  @apply dark:border-neutral-600 dark:text-neutral-200 dark:hover:bg-neutral-800;
}

.model-group {
  @apply space-y-3;
}

.group-title {
  @apply text-xs font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
}

.model-list {
  @apply space-y-2;
}

.model-card {
  @apply flex items-center justify-between gap-4;
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply transition-colors;
}

.model-info {
  @apply flex-1 min-w-0;
}

.model-name {
  @apply flex items-center gap-2;
  @apply font-medium text-neutral-900 dark:text-neutral-100;
}

.model-meta {
  @apply flex items-center gap-3 mt-1;
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.model-meta span {
  @apply inline-flex items-center gap-1;
}

.model-actions {
  @apply flex items-center gap-2;
}

.backend-section {
  @apply space-y-2;
}

.backend-toggle {
  @apply inline-flex rounded-lg p-0.5;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.backend-option {
  @apply px-3 py-1.5 rounded-md text-sm font-medium;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply transition-colors;
}

.backend-option.active {
  @apply bg-white text-primary-700 shadow-sm dark:bg-neutral-900 dark:text-primary-300;
}

.backend-option:disabled {
  @apply cursor-not-allowed opacity-60;
}

.backend-model {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.backend-model-uses {
  @apply mt-1 list-disc pl-5 text-xs text-neutral-500 dark:text-neutral-400;
}

.backend-error {
  @apply text-sm text-error-600 dark:text-error-400;
}

.btn-download {
  @apply inline-flex items-center gap-2;
  @apply px-3 py-1.5 rounded-lg;
  @apply text-sm font-medium;
  @apply text-white;
  @apply bg-primary-600 hover:bg-primary-700;
  @apply transition-colors;
}

.btn-remove {
  @apply p-2 rounded-lg;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply hover:text-error-600 dark:hover:text-error-400;
  @apply hover:bg-error-50 dark:hover:bg-error-900/20;
  @apply transition-colors;
}

.download-progress {
  @apply flex min-w-44 items-center gap-3;
}

.download-status {
  @apply flex flex-col;
  @apply text-xs leading-snug text-neutral-500 dark:text-neutral-400;
}

.download-status strong {
  @apply text-neutral-800 dark:text-neutral-200;
}

.empty-state {
  @apply flex flex-col items-center gap-3;
  @apply py-8;
  @apply text-neutral-500 dark:text-neutral-400;
}

.info-box {
  @apply p-4 rounded-xl;
  @apply bg-primary-50 dark:bg-primary-900/20;
  @apply border border-primary-200 dark:border-primary-800;
}

.info-box h4 {
  @apply text-sm font-medium text-primary-700 dark:text-primary-300 mb-1;
}

.info-box p {
  @apply text-sm text-primary-600 dark:text-primary-400;
}

.info-box p + p {
  @apply mt-2;
}
</style>
