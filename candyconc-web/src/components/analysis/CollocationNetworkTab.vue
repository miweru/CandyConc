<script setup lang="ts">
/**
 * CollocationNetworkTab - Collocation network (graph) view backed by the
 * dedicated /analysis/collocation_network endpoint.
 *
 * Reuses the analysis toolbar, scope pill, empty/loading/error states and the
 * corpus/docset selection used by the other analysis tabs so it feels native.
 */
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import {
  coerceMethodBlock,
  type CollocationAttribute,
  type CollocationNetwork,
  type CollocationNetworkMeasure,
  type MethodBlock,
} from '@/api/client'
import { useDocsetStore, useQueryStore, useAnalysisPresetsStore } from '@/stores'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useMobileDetection } from '@/composables'
import { Network, RefreshCw, Download, AlertTriangle, Tags } from 'lucide-vue-next'
import CollocationNetworkGraph from './charts/CollocationNetworkGraph.vue'
import MeasureInfo from '@/components/ui/MeasureInfo.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'
import { useCollocationNetworkOperations } from '@/composables/useCollocationNetworkOperations'
import { downloadText } from '@/utils/download'
import { actionBus } from '@/actions'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const queryStore = useQueryStore()
const docsetStore = useDocsetStore()
const presetsStore = useAnalysisPresetsStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const { isMobile } = useMobileDetection()
const {
  assertCanLoadCollocationNetwork,
  loadCollocationNetwork,
  canLoadCollocationNetwork,
  collocationNetworkBlockReason,
} = useCollocationNetworkOperations()

// Controls
const windowSize = ref(5)
const measure = ref<CollocationNetworkMeasure>('logdice')
// Zählattribut 'word' | 'lemma' (Lemma nur mit token_attributes.lemma im Index).
const attribute = ref<CollocationAttribute>('word')
const maxNodes = ref(30)
const expandDepth = ref<1 | 2>(1)
const showEdgeLabels = ref(false)
// Aligns the default with the collocates tab (sentence-bounded windows).
const withinSentence = ref(true)

// State
const network = ref<CollocationNetwork | null>(null)
const networkMethod = ref<MethodBlock | null>(null)
const isLoading = ref(false)
const error = ref<string | null>(null)
let requestToken = 0

const MEASURE_OPTIONS: Array<{ value: CollocationNetworkMeasure; label?: string; labelKey?: string }> = [
  { value: 'logdice', label: 'logDice' },
  { value: 'dice', label: 'Dice' },
  { value: 'mi', labelKey: 'analysis.measureOptions.mutualInformation' },
  { value: 'mi3', labelKey: 'analysis.measureOptions.mi3' },
  { value: 'lmi', label: 'LMI' },
  { value: 'npmi', label: 'NPMI' },
  { value: 'z', labelKey: 'analysis.measureOptions.zScore' },
  { value: 't', labelKey: 'analysis.measureOptions.tScore' },
  { value: 'll', labelKey: 'analysis.measureOptions.logLikelihood' },
  { value: 'chi2_cell', labelKey: 'analysis.measureOptions.chi2CellShort' },
]

const measureOptions = computed(() =>
  MEASURE_OPTIONS.map((option) => ({
    value: option.value,
    label: option.labelKey ? t(option.labelKey) : option.label ?? option.value,
  })),
)

const measureLabel = computed(
  () => measureOptions.value.find((m) => m.value === measure.value)?.label ?? measure.value
)

// Lemma-Zählung ist nur mit Lemma-Postings im Index möglich (token_attributes.lemma).
const canUseLemmaAttribute = computed(() => corpusCapabilities.canUseTokenAttribute('lemma'))
const lemmaToggleTitle = computed(() =>
  canUseLemmaAttribute.value
    ? t('analysis.measureOptions.countLemmaTitle')
    : t('analysis.measureOptions.lemmaUnavailable'),
)

function setAttribute(next: CollocationAttribute) {
  if (next === 'lemma' && !canUseLemmaAttribute.value) return
  if (attribute.value !== next) attribute.value = next
}

watch(canUseLemmaAttribute, (available) => {
  if (!available && attribute.value === 'lemma') {
    attribute.value = 'word'
  }
})

const analysisTerm = computed(() => (queryStore.term?.trim() ?? ''))

const scopeText = computed(() => {
  if (!docsetStore.hasActiveDocset) return t('analysis.shared.wholeCorpus')
  const docs = formatNumber(docsetStore.stats.docCount)
  const tokens = formatNumber(docsetStore.stats.tokenCount)
  return t('analysis.shared.docsTokens', { docs, tokens })
})

const nodes = computed(() => network.value?.nodes ?? [])
const edges = computed(() => network.value?.edges ?? [])
const isTruncated = computed(() => Boolean(network.value?.diagnostics?.truncated))
const refreshTitle = computed(() =>
  collocationNetworkBlockReason.value ?? t('analysis.shared.recompute'),
)
const secondOrderCount = computed(() => {
  const raw = network.value?.diagnostics?.second_order_count
  return typeof raw === 'number' ? raw : 0
})

async function loadNetwork() {
  const term = analysisTerm.value
  if (!term) {
    network.value = null
    return
  }
  const token = ++requestToken
  isLoading.value = true
  error.value = null
  try {
    await assertCanLoadCollocationNetwork()
    // Keep the docset live only after the product operation is allowed.
    if (docsetStore.hasActiveDocset && docsetStore.isDirty) {
      const rebuilt = await docsetStore.buildDocset(true, term)
      if (!rebuilt || !docsetStore.activeDocsetId) {
        error.value = docsetStore.error || t('analysis.collocations.docsetStale')
        return
      }
    }
    const result = await loadCollocationNetwork({
      term,
      window: windowSize.value,
      measure: measure.value,
      maxNodes: maxNodes.value,
      expandDepth: expandDepth.value,
      withinSentence: withinSentence.value,
      attribute: attribute.value,
      corpus: docsetStore.activeCorpus,
      docsetId: docsetStore.hasActiveDocset
        ? docsetStore.activeDocsetId ?? undefined
        : undefined,
    })
    if (token !== requestToken) return
    network.value = result
    networkMethod.value = coerceMethodBlock(result.method) ?? null
  } catch (err) {
    if (token !== requestToken) return
    error.value =
      err instanceof Error ? err.message : t('analysis.network.loadFailed')
    network.value = null
    networkMethod.value = null
  } finally {
    if (token === requestToken) isLoading.value = false
  }
}

const networkParams = computed(() => ({
  window: windowSize.value,
  measure: measure.value,
  attribute: attribute.value,
  maxNodes: maxNodes.value,
  expandDepth: expandDepth.value,
  withinSentence: withinSentence.value,
}))

const docsetSnapshot = computed(() =>
  docsetStore.hasActiveDocset && docsetStore.activeDocsetId && !docsetStore.isDirty
    ? {
        corpus: docsetStore.activeCorpus,
        docsetId: docsetStore.activeDocsetId,
        stats: docsetStore.stats,
        filters: docsetStore.filters,
        includeAi: docsetStore.includeAi,
        includeHuman: docsetStore.includeHuman,
        filterSpec: docsetStore.activeFilterSpec ?? undefined,
        metadataSchemaHash: docsetStore.metaSchemaHash ?? undefined,
      }
    : null
)

function exportJSON() {
  if (!network.value) return
  downloadText(
    JSON.stringify(network.value, null, 2),
    `collocation_network_${analysisTerm.value || 'term'}.json`,
    'application/json',
  )
}

watch(
  () => analysisTerm.value,
  () => {
    if (actionBus.isActionInProgress('analysis/collocationNetwork')) return
    if (analysisTerm.value) loadNetwork()
  },
  { immediate: true }
)

// A corpus switch keeps the search term, but the network belongs to the
// corpus it was computed on. The tab computes it again for the new corpus,
// like frequency, dispersion and n-grams, and is empty without a term.
watch(
  () => docsetStore.activeCorpus,
  (corpus, previous) => {
    if (corpus === previous) return
    if (actionBus.isActionInProgress('analysis/collocationNetwork')) return
    requestToken += 1
    network.value = null
    networkMethod.value = null
    error.value = null
    if (analysisTerm.value) loadNetwork()
  }
)

watch([windowSize, measure, maxNodes, expandDepth, withinSentence, attribute], () => {
  if (actionBus.isActionInProgress('analysis/collocationNetwork')) return
  if (analysisTerm.value) loadNetwork()
})

watch(
  () => presetsStore.pendingPreset,
  async (preset) => {
    if (!preset || preset.type !== 'collocation_network') return
    const params = preset.params as {
      window?: number
      measure?: CollocationNetworkMeasure
      attribute?: CollocationAttribute
      maxNodes?: number
      expandDepth?: 1 | 2
      withinSentence?: boolean
    }
    if (typeof params.window === 'number') windowSize.value = params.window
    if (params.measure) measure.value = params.measure
    if (params.attribute === 'word' || (params.attribute === 'lemma' && canUseLemmaAttribute.value)) {
      attribute.value = params.attribute
    }
    if (typeof params.maxNodes === 'number') maxNodes.value = params.maxNodes
    if (params.expandDepth === 1 || params.expandDepth === 2) expandDepth.value = params.expandDepth
    if (typeof params.withinSentence === 'boolean') withinSentence.value = params.withinSentence
    presetsStore.setPending(null)

    // Hydrate the cached graph when still valid; otherwise recompute.
    let hydrated = false
    const cached = preset.result as CollocationNetwork | undefined
    if (cached && Array.isArray(cached.nodes) && Array.isArray(cached.edges)) {
      const valid = await presetsStore.isResultValid(preset)
      if (valid) {
        network.value = cached
        networkMethod.value = coerceMethodBlock(cached.method) ?? null
        error.value = null
        isLoading.value = false
        hydrated = true
      }
    }
    if (!hydrated && analysisTerm.value) {
      await loadNetwork()
    }
  }
)

onBeforeUnmount(() => {
  requestToken++
})
</script>

<template>
  <div class="collocation-network-tab">
    <AnalysisToolbar>
      <template #left>
        <div
          class="scope-pill"
          :class="{ active: docsetStore.hasActiveDocset, stale: docsetStore.isDirty }"
        >
          {{ scopeText }}
        </div>

        <label class="slider-label">
          <span class="label-text">{{ t('analysis.measureOptions.windowLabel') }}</span>
          <input v-model.number="windowSize" type="range" min="1" max="10" class="slider" />
          <span class="slider-value">{{ windowSize }}</span>
        </label>

        <select
          v-model="measure"
          class="select"
          :aria-label="t('analysis.measureOptions.associationMeasure')"
        >
          <option v-for="opt in measureOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
        <MeasureInfo
          :measure-key="measure"
          :method="networkMethod"
          :fallback-label="measureLabel"
        />

        <div class="attribute-toggle" role="group" :aria-label="t('analysis.measureOptions.countAttribute')">
          <button
            type="button"
            :class="{ active: attribute === 'word' }"
            :aria-pressed="attribute === 'word'"
            :title="t('analysis.measureOptions.countWordTitle')"
            @click="setAttribute('word')"
          >
            {{ t('analysis.measureOptions.wordForm') }}
          </button>
          <button
            type="button"
            :class="{ active: attribute === 'lemma' }"
            :aria-pressed="attribute === 'lemma'"
            :disabled="!canUseLemmaAttribute"
            :title="lemmaToggleTitle"
            @click="setAttribute('lemma')"
          >
            {{ t('analysis.measureOptions.lemma') }}
          </button>
        </div>

        <select
          v-model.number="expandDepth"
          class="select"
          :title="t('analysis.network.depthTitle')"
          :aria-label="t('analysis.network.depth')"
        >
          <option :value="1">{{ t('analysis.network.depth1') }}</option>
          <option :value="2">{{ t('analysis.network.depth2') }}</option>
        </select>

        <label class="slider-label">
          <span class="label-text">{{ t('analysis.network.nodesLabel') }}</span>
          <input v-model.number="maxNodes" type="range" min="5" max="80" step="5" class="slider" />
          <span class="slider-value">{{ maxNodes }}</span>
        </label>

        <label class="checkbox-label" :title="t('analysis.network.withinSentenceTitle')">
          <input v-model="withinSentence" type="checkbox" />
          <span class="label-text">{{ t('analysis.measureOptions.withinSentence') }}</span>
        </label>
      </template>

      <template #right>
        <button
          class="btn-icon"
          :class="{ active: showEdgeLabels }"
          :title="t('analysis.network.edgeLabels')"
          @click="showEdgeLabels = !showEdgeLabels"
        >
          <Tags class="w-4 h-4" />
        </button>

        <button
          class="btn-icon"
          :disabled="isLoading || !canLoadCollocationNetwork"
          :title="refreshTitle"
          @click="loadNetwork"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': isLoading }" />
        </button>

        <button
          class="btn-icon"
          :disabled="!network || !nodes.length"
          :title="t('analysis.network.exportJson')"
          @click="exportJSON"
        >
          <Download class="w-4 h-4" />
        </button>

        <SaveAnalysisButton
          type="collocation_network"
          :defaultName="t('analysis.network.defaultName', { query: analysisTerm || t('analysis.network.noQuery') })"
          :corpus="docsetStore.activeCorpus"
          :docset="docsetSnapshot"
          :queryTerm="analysisTerm"
          :params="networkParams"
          :result="network ?? undefined"
        />
      </template>
    </AnalysisToolbar>

    <CapabilityBoundaryPanel
      capability-id="analysis.collocation_network"
      :method="networkMethod"
      class="network-method"
    />

    <!-- No Query State -->
    <EmptyState
      v-if="!analysisTerm"
      :icon="Network"
      :title="t('analysis.network.noQueryTitle')"
      :description="t('analysis.network.noQueryDescription')"
      size="sm"
    />

    <EmptyState
      v-else-if="collocationNetworkBlockReason"
      :icon="AlertTriangle"
      :title="t('analysis.network.unavailable')"
      :description="collocationNetworkBlockReason"
      size="sm"
    />

    <!-- Loading -->
    <div v-else-if="isLoading" class="loading-container">
      <Skeleton height="420px" class="w-full" />
    </div>

    <!-- Error -->
    <EmptyState
      v-else-if="error"
      :icon="AlertTriangle"
      :title="t('analysis.collocations.errorTitle')"
      :description="error"
      :action-label="t('analysis.shared.retry')"
      size="sm"
      @action="loadNetwork"
    />

    <!-- Empty Results -->
    <EmptyState
      v-else-if="!nodes.length || edges.length === 0"
      :icon="Network"
      :title="t('analysis.network.emptyTitle')"
      :description="t('analysis.network.emptyDescription', { term: analysisTerm })"
      :action-label="t('analysis.shared.recompute')"
      size="sm"
      @action="loadNetwork"
    />

    <!-- Graph -->
    <div v-else class="graph-container">
      <CollocationNetworkGraph
        :nodes="nodes"
        :edges="edges"
        :measure-label="measureLabel"
        :show-edge-labels="showEdgeLabels"
        :height="isMobile ? 360 : 520"
      />
      <div class="graph-legend">
        <span class="legend-item">
          <span class="dot dot-seed" /> {{ t('analysis.charts.seed') }}
        </span>
        <span class="legend-item">
          <span class="dot dot-first" /> {{ t('analysis.charts.firstOrder') }}
        </span>
        <span v-if="expandDepth === 2" class="legend-item">
          <span class="dot dot-second" /> {{ t('analysis.charts.secondOrder') }}
        </span>
        <span class="legend-meta">
          {{ t('analysis.network.legend', { measure: measureLabel }) }}
        </span>
        <span v-if="secondOrderCount > 0" class="legend-meta">
          · {{ t('analysis.network.secondOrderCount', { count: secondOrderCount }, secondOrderCount) }}
        </span>
        <span v-if="isTruncated" class="legend-warn">
          · {{ t('analysis.network.truncated') }}
        </span>
        <span class="legend-meta">
          · {{ t('analysis.network.zoomHint') }}
        </span>
      </div>

    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.collocation-network-tab {
  /* At least as high as the tab, grows with its content: the tab area
     scrolls (App.vue .tab-content). */
  @apply flex flex-col min-h-full;
}

.scope-pill {
  @apply px-2.5 py-1 rounded-full text-xs md:text-sm font-medium;
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
  white-space: nowrap;
}

.scope-pill.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.scope-pill.stale {
  @apply ring-1 ring-amber-400/70;
}

.slider-label {
  @apply flex items-center gap-2 text-sm;
}

.checkbox-label {
  @apply inline-flex items-center gap-1.5 text-sm cursor-pointer;
}

.attribute-toggle {
  @apply flex rounded-lg overflow-hidden;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.attribute-toggle button {
  @apply px-2 md:px-3 py-1.5 text-xs md:text-sm transition-colors;
}

.attribute-toggle button.active {
  @apply bg-primary-500 text-white;
}

.attribute-toggle button:not(.active) {
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.attribute-toggle button:disabled {
  @apply opacity-50 cursor-not-allowed;
}

.network-method {
  @apply mt-3;
}

.label-text {
  @apply text-neutral-600 dark:text-neutral-400;
}

.slider {
  @apply w-20 md:w-24 h-2 rounded-full;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply accent-primary-500;
}

.slider-value {
  @apply w-6 text-center font-mono text-neutral-700 dark:text-neutral-300;
}

.select {
  @apply px-2 md:px-3 py-1.5 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border-none text-sm;
  @apply focus:ring-2 focus:ring-primary-500;
}

.btn-icon {
  @apply p-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

.btn-icon.active {
  @apply bg-primary-500 text-white;
}

.loading-container {
  @apply flex-1 p-4;
}

.graph-container {
  /* Results in the flow of the tab, which scrolls as a whole. */
  flex: 1 0 auto;
  @apply p-4 flex flex-col;
}

.graph-legend {
  @apply mt-2 flex flex-wrap items-center gap-3 text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}

.legend-item {
  @apply inline-flex items-center gap-1.5;
}

.dot {
  @apply inline-block w-3 h-3 rounded-full;
}

.dot-seed {
  @apply bg-primary-500;
}

.dot-first {
  @apply bg-primary-300;
}

.dot-second {
  background-color: var(--color-copilot-primary);
}

.legend-meta {
  @apply text-neutral-400 dark:text-neutral-500;
}

.legend-warn {
  @apply text-amber-600 dark:text-amber-400;
}
</style>
