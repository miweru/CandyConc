<script setup lang="ts">
/**
 * SemanticTab - Semantic/vector search interface
 */
import { ref, watch, computed, onMounted } from 'vue'
import { useMutation } from '@tanstack/vue-query'
import {
  SemanticSearchError,
  SimilarWordsUnavailableError,
  type SemanticSearchParams,
  type SemanticSearchResultSet,
  type SimilarWordsParams,
  type SimilarWordsResult,
} from '@/api/client'
import { useActions, useMobileDetection } from '@/composables'
import { actionBus } from '@/actions'
import { Brain, Search, FileText, Hash, AlertTriangle, Sparkles, ArrowRightCircle, BookOpen } from 'lucide-vue-next'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import { useAnalysisPresetsStore, useCorpusCapabilitiesStore, useDocsetStore, useProductCapabilitiesStore, useUiStore } from '@/stores'
import {
  corpusFeatureDecisionReason,
} from '@/lib/productCorpusFeatures'
import { ensureUsableResearchScope, executionScopeForApi } from '@/lib/researchScope'
import { useSemanticOperations } from '@/composables/useSemanticOperations'
import { useProductOperationFocus } from '@/composables/useProductOperationFocus'
import {
  type SemanticScoreKind,
  deriveSemanticScoreKind,
  formatSemanticScore,
  semanticBarWidth,
  semanticScoreBand,
  semanticScoreUnitLabel,
} from '@/lib/semanticScore'
import { formatDecimal, formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const { isMobile } = useMobileDetection()
const docsetStore = useDocsetStore()
const presetsStore = useAnalysisPresetsStore()
const uiStore = useUiStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const productCapabilities = useProductCapabilitiesStore()
const {
  canLoadSimilarWords,
  canSearchPassages,
  similarWordsBlockReason,
  semanticPassageBlockReason,
  loadSimilarWords,
  searchPassages,
} = useSemanticOperations()
const { consumeFocusFor, focusMatches, focusIs, modeIs } = useProductOperationFocus()

/**
 * Two modes share one tab:
 * - `passage`: semantic passage search (existing embedding_search surface).
 * - `thesaurus`: distributional thesaurus — ranked neighbour WORDS for a term (F8).
 */
type SemanticMode = 'passage' | 'thesaurus'

const mode = ref<SemanticMode>('passage')
const passageFocused = computed(() =>
  modeIs('passage', 'passages', 'passage_search') ||
  focusIs('analysis.semantic_similarity.passage_search') ||
  focusMatches('analysis.semantic_similarity.passages')
)
const thesaurusFocused = computed(() =>
  modeIs('thesaurus', 'words', 'similar_words') ||
  focusIs('analysis.semantic_similarity.similar_words') ||
  focusMatches('analysis.semantic_similarity.words')
)

// State
const query = ref('')
const topK = ref(20)
const useDocsetScope = ref(true)
const researchScope = computed(() =>
  ensureUsableResearchScope(docsetStore, {
    operation: t('analysis.semantic.operation'),
    useDocsetScope: useDocsetScope.value,
  })
)
const semanticAvailabilityKnown = computed(() => Boolean(corpusCapabilities.activeSummary))
const passageDecision = computed(() =>
  productCapabilities.corpusFeatureDecision(
    'analysis.semantic_similarity',
    corpusCapabilities.activeSummary,
    (route) => route.path === '/api/v1/analysis/embedding_search',
  )
)
const thesaurusDecision = computed(() =>
  productCapabilities.corpusFeatureDecision(
    'analysis.semantic_similarity',
    corpusCapabilities.activeSummary,
    (route) => route.path === '/api/v1/semantic/similar_words',
  )
)
const passageDisabled = computed(() =>
  !semanticAvailabilityKnown.value ||
  passageDecision.value.status !== 'pass' ||
  !canSearchPassages.value
)
const thesaurusDisabled = computed(() =>
  !semanticAvailabilityKnown.value ||
  thesaurusDecision.value.status !== 'pass' ||
  !canLoadSimilarWords.value
)
const semanticUnavailableNotice = computed(() => {
  if (!semanticAvailabilityKnown.value) return t('analysis.semantic.capabilitiesLoading')
  if (mode.value === 'passage' && passageDisabled.value) {
    return semanticPassageBlockReason.value ??
      corpusFeatureDecisionReason(t('analysis.operations.semanticSearch'), passageDecision.value) ??
      t('analysis.semantic.noPassageIndex')
  }
  if (mode.value === 'thesaurus' && thesaurusDisabled.value) {
    return similarWordsBlockReason.value ??
      corpusFeatureDecisionReason(t('analysis.semantic.thesaurusName'), thesaurusDecision.value) ??
      t('analysis.semantic.noWordIndex')
  }
  return null
})
const passageBlockReason = computed(() =>
  semanticPassageBlockReason.value ??
  corpusFeatureDecisionReason(t('analysis.operations.semanticSearch'), passageDecision.value)
)
const thesaurusBlockReason = computed(() =>
  similarWordsBlockReason.value ??
  corpusFeatureDecisionReason(t('analysis.semantic.thesaurusName'), thesaurusDecision.value)
)
const semanticPartialNotice = computed(() => {
  if (!semanticAvailabilityKnown.value || semanticUnavailableNotice.value) return null
  if (passageDisabled.value && !thesaurusDisabled.value) {
    return `${t('analysis.semantic.partialThesaurusOnly')} ${passageBlockReason.value ?? ''}`.trim()
  }
  if (thesaurusDisabled.value && !passageDisabled.value) {
    return `${t('analysis.semantic.partialPassageOnly')} ${thesaurusBlockReason.value ?? ''}`.trim()
  }
  return null
})
watch(
  [semanticAvailabilityKnown, passageDisabled, thesaurusDisabled],
  () => {
    if (!semanticAvailabilityKnown.value) return
    if (mode.value === 'passage' && passageDisabled.value && !thesaurusDisabled.value) {
      mode.value = 'thesaurus'
    } else if (mode.value === 'thesaurus' && thesaurusDisabled.value && !passageDisabled.value) {
      mode.value = 'passage'
    }
  },
  { immediate: true },
)

consumeFocusFor(
  ['analysis.semantic_similarity'],
  (focus) => {
    const slot = focus.surfaceSlot
    const preferred = focus.preferredMode ?? ''
    if (
      focus.operationId === 'analysis.semantic_similarity.similar_words' ||
      slot.includes('.words') ||
      ['thesaurus', 'similar_words', 'words'].includes(preferred)
    ) {
      setMode('thesaurus')
      return
    }
    if (
      focus.operationId === 'analysis.semantic_similarity.passage_search' ||
      slot.includes('.passages') ||
      ['passage', 'passages', 'passage_search'].includes(preferred)
    ) {
      setMode('passage')
    }
  },
)

type SemanticMutationInput = { params: SemanticSearchParams; signal?: AbortSignal }

const activeController = ref<AbortController | null>(null)

// Mutation for semantic search
const { data, mutateAsync, isPending, error, reset } = useMutation({
  mutationFn: ({ params, signal }: SemanticMutationInput) => searchPassages(params, { signal })
})

const results = computed(() => data.value?.rows ?? [])
const searchMeta = computed(() => data.value?.meta)
const semanticError = computed(() =>
  error.value instanceof SemanticSearchError ? error.value : null
)
const rawSemanticErrorMessage = computed(() =>
  semanticError.value?.message ?? (error.value as Error | null)?.message ?? ''
)
const semanticServiceUnreachable = computed(() =>
  /embedding request failed|connection refused|backend[^\n]*not ready|fails:\s*ready/i.test(rawSemanticErrorMessage.value)
)

const errorTitle = computed(() => {
  if (semanticError.value?.code === 'semantic_index_missing') return t('analysis.semantic.indexMissing')
  if (semanticError.value?.code === 'semantic_unavailable') return t('analysis.semantic.unavailable')
  if (semanticServiceUnreachable.value) return t('analysis.semantic.unreachable')
  return t('analysis.semantic.failedTitle')
})

const errorDescription = computed(() => {
  if (semanticError.value?.code === 'semantic_index_missing') {
    return t('analysis.semantic.indexMissingDescription')
  }
  if (semanticError.value?.code === 'semantic_unavailable' || semanticServiceUnreachable.value) {
    return t('analysis.semantic.unreachableDescription')
  }
  return t('analysis.semantic.failedDescription')
})

const docsetSnapshot = computed(() =>
  docsetStore.hasActiveDocset && docsetStore.activeDocsetId
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

const scopeText = computed(() => {
  if (!docsetStore.hasActiveDocset) return t('analysis.shared.wholeCorpus')
  if (!researchScope.value.ok) return researchScope.value.evidence.label
  const docs = formatNumber(docsetStore.stats.docCount)
  const tokens = formatNumber(docsetStore.stats.tokenCount)
  return t('analysis.shared.docsTokens', { docs, tokens })
})

const searchMetaBadges = computed(() => {
  const meta = searchMeta.value
  if (!meta) return []
  const badges: string[] = []
  const mode = meta.exactness ?? meta.candidateGeneration?.searchMode
  if (mode === 'exact') badges.push(t('analysis.semantic.badges.exact'))
  else if (mode === 'approximate') badges.push(t('analysis.semantic.badges.approximate'))
  else if (mode === 'unknown') badges.push(t('analysis.semantic.badges.unknownMode'))
  const candidateCount = meta.candidateGeneration?.candidateCount
  if (typeof candidateCount === 'number') {
    badges.push(t('analysis.semantic.badges.candidates', { count: formatNumber(candidateCount) }, candidateCount))
  }
  if (meta.rerank?.enabled) badges.push(t('analysis.semantic.badges.rerank'))
  if (meta.filtering?.docsetApplied) badges.push(t('analysis.semantic.badges.subcorpusFilter'))
  return badges
})

async function ensureSemanticCapability(): Promise<boolean> {
  if (!productCapabilities.hasContract) {
    await productCapabilities.load()
  }
  if (!semanticAvailabilityKnown.value) {
    await corpusCapabilities.fetchCapabilities(docsetStore.activeCorpus)
  }
  if (semanticUnavailableNotice.value) {
    uiStore.showToast(semanticUnavailableNotice.value, 'warning', 3000)
    return false
  }
  return true
}

async function handleSearch(): Promise<SemanticSearchResultSet | null> {
  if (!(await ensureSemanticCapability())) {
    return null
  }
  if (!researchScope.value.ok) {
    uiStore.showToast(researchScope.value.message ?? t('analysis.semantic.scopeUnusable'), 'warning', 3000)
    return null
  }
  const term = query.value.trim()
  if (!term) return Promise.resolve(null)
  reset()
  const params: SemanticSearchParams = { query: term, top_k: topK.value, corpus: docsetStore.activeCorpus }
  if (researchScope.value.docsetId) params.docsetId = researchScope.value.docsetId
  if (activeController.value) {
    activeController.value.abort()
  }
  const controller = new AbortController()
  activeController.value = controller
  return mutateAsync({ params, signal: controller.signal }).catch((err) => {
    if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') {
      reset()
      return null
    }
    throw err
  }).finally(() => {
    if (activeController.value === controller) {
      activeController.value = null
    }
  })
}

function cancelSearch() {
  if (mode.value === 'thesaurus') {
    if (!thesaurusPending.value) return
    if (thesaurusController.value) {
      thesaurusController.value.abort()
      thesaurusController.value = null
    }
    resetThesaurus()
    uiStore.showToast(t('analysis.semantic.thesaurusCancelled'), 'info')
    return
  }
  if (!isPending.value) return
  if (activeController.value) {
    activeController.value.abort()
    activeController.value = null
  }
  reset()
  uiStore.showToast(t('analysis.semantic.searchCancelled'), 'info')
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    runMode()
  }
}

// ── Distributional thesaurus (F8) ────────────────────────────────────
type ThesaurusMutationInput = { params: SimilarWordsParams; signal?: AbortSignal }
const thesaurusController = ref<AbortController | null>(null)

const {
  data: thesaurusData,
  mutateAsync: mutateThesaurus,
  isPending: thesaurusPending,
  error: thesaurusError,
  reset: resetThesaurus,
} = useMutation({
  mutationFn: ({ params, signal }: ThesaurusMutationInput) => loadSimilarWords(params, { signal }),
})

const neighbours = computed(() => thesaurusData.value?.neighbours ?? [])
const sharedVectorCount = computed(() => neighbours.value.filter((row) => row.sharedQueryVector === true).length)
const thesaurusBackend = computed(() => thesaurusData.value?.backend ?? null)
const thesaurusUnavailable = computed(
  () => thesaurusError.value instanceof SimilarWordsUnavailableError
)
// The server names why the corpus has no word vectors (pipeline without
// vectors, pipeline not installed). The static text stands in without it.
const thesaurusUnavailableReason = computed(() =>
  thesaurusError.value instanceof SimilarWordsUnavailableError ? thesaurusError.value.reason : null
)
const maxNeighbourScore = computed(() =>
  neighbours.value.reduce((max, n) => (n.score && n.score > max ? n.score : max), 0)
)

async function handleThesaurus(): Promise<SimilarWordsResult | null> {
  if (!(await ensureSemanticCapability())) {
    return null
  }
  if (!researchScope.value.ok) {
    uiStore.showToast(researchScope.value.message ?? t('analysis.semantic.scopeUnusable'), 'warning', 3000)
    return null
  }
  const term = query.value.trim()
  if (!term) return Promise.resolve(null)
  resetThesaurus()
  const params: SimilarWordsParams = { term, k: topK.value, corpus: docsetStore.activeCorpus }
  if (researchScope.value.docsetId) params.docsetId = researchScope.value.docsetId
  if (thesaurusController.value) thesaurusController.value.abort()
  const controller = new AbortController()
  thesaurusController.value = controller
  return mutateThesaurus({ params, signal: controller.signal })
    .catch((err) => {
      if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') {
        resetThesaurus()
        return null
      }
      if (err instanceof SimilarWordsUnavailableError) {
        return null
      }
      throw err
    })
    .finally(() => {
      if (thesaurusController.value === controller) thesaurusController.value = null
    })
}

function runMode(): void {
  const run = mode.value === 'thesaurus' ? handleThesaurus() : handleSearch()
  // The mutation state renders the failure in the tab. Keep a failed click or
  // Enter key from also becoming an unhandled browser rejection.
  void run.catch(() => undefined)
}

function setMode(next: SemanticMode) {
  if (mode.value === next) return
  mode.value = next
}

/**
 * Close the loop to KWIC: inject a neighbour into the live search. `expand`
 * uses the backend `sim("word")` query-expansion macro; otherwise a plain
 * word search. Switches to the KWIC tab so the linguist sees concordances.
 */
async function injectIntoSearch(word: string, expand = false) {
  const term = expand ? `sim("${word}")` : word
  try {
    await actionBus.dispatch({
      type: 'query/execute',
      payload: {
        term,
        filters: { corpus: docsetStore.activeCorpus },
      },
    })
    await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
    uiStore.showToast(
      expand ? t('analysis.semantic.searchSimilar', { word }) : t('analysis.semantic.searchWord', { word }),
      'info',
      2500
    )
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.semantic.searchStartFailed')
    uiStore.showToast(message, 'error')
  }
}

const thesaurusExamples = computed(() => [
  t('analysis.semantic.examples.word1'),
  t('analysis.semantic.examples.word2'),
  t('analysis.semantic.examples.word3'),
])

const passageExamples = computed(() => [
  { label: t('analysis.semantic.examples.passage1Label'), query: t('analysis.semantic.examples.passage1Query') },
  { label: t('analysis.semantic.examples.passage2Label'), query: t('analysis.semantic.examples.passage2Query') },
  { label: t('analysis.semantic.examples.passage3Label'), query: t('analysis.semantic.examples.passage3Query') },
])

function formatFrequency(value: number | null): string {
  if (value === null) return '–'
  return formatNumber(value)
}

// SEM-01: the PASSAGE search score is a cosine only on a true vector path; on the
// lexical/rerank path it is a relevance rank that merely lands inside [-1, 1].
// The KIND travels in the response meta — derive it once and let formatting,
// colour band and bar width all key off it so a rerank "1.0" is never painted as
// a green "100 % perfect match". The THESAURUS neighbour scores are always true
// spaCy cosines, so they keep the cosine treatment unconditionally.
const passageScoreKind = computed<SemanticScoreKind>(() =>
  deriveSemanticScoreKind(searchMeta.value)
)

function formatNeighbourScore(score: number): string {
  return formatSemanticScore(score, 'cosine')
}

// Bar width as a fraction of the strongest neighbour, clamped to [0, 100] so a
// negative cosine never yields a negative-width bar.
function neighbourBarWidth(score: number | null): string {
  if (score === null) return '0%'
  return `${semanticBarWidth(score, 'cosine', maxNeighbourScore.value)}%`
}

// Truncate text for preview
function truncateText(text: string, maxLength: number = 200): string {
  if (text.length <= maxLength) return text
  return text.slice(0, maxLength).trim() + '...'
}

function metadataText(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return ''
}

// Register action handler for Copilot
useActions({
  'analysis/semantic': async (action) => {
    if (action.payload?.mode === 'thesaurus' || action.payload?.mode === 'passage') {
      mode.value = action.payload.mode
    }
    if (action.payload?.query) {
      query.value = action.payload.query
    }
    if (action.payload?.topK) {
      topK.value = action.payload.topK
    }
    const executionScope = executionScopeForApi(
      docsetStore,
      docsetStore.activeCorpus,
      researchScope.value.docsetId,
    )
    const result = mode.value === 'thesaurus' ? await handleThesaurus() : await handleSearch()
    if (!result) {
      return { success: false, error: semanticUnavailableNotice.value ?? t('analysis.semantic.analysisFailed') }
    }
    return { success: true, data: result, executionScope }
  }
})

watch(
  () => presetsStore.pendingPreset,
  (preset) => {
    if (!preset || preset.type !== 'semantic') return
    const params = preset.params as { query?: string; topK?: number }
    if (params.query) query.value = params.query
    if (params.topK) topK.value = params.topK
    presetsStore.setPending(null)
    void handleSearch()
  }
)

watch(
  () => useDocsetScope.value,
  () => {
    if (query.value.trim()) {
      runMode()
    }
  }
)

// Passages and neighbours belong to the corpus they came from. After a
// corpus switch the tab is empty: it does not search again on its own,
// because a passage search embeds the query with the model of the new corpus.
watch(
  () => docsetStore.activeCorpus,
  (corpus, previous) => {
    if (corpus === previous) return
    activeController.value?.abort()
    thesaurusController.value?.abort()
    reset()
    resetThesaurus()
  }
)

onMounted(() => {
  if (!corpusCapabilities.loaded) void corpusCapabilities.fetchCorpora()
})
</script>

<template>
  <div class="semantic-tab">
    <AnalysisToolbar>
      <template #left>
        <div class="mode-switch" role="tablist" :aria-label="t('analysis.semantic.mode')">
          <button
            type="button"
            role="tab"
            class="mode-btn"
            :class="{ active: mode === 'passage', 'operation-focused': passageFocused }"
            :aria-selected="mode === 'passage'"
            :disabled="passageDisabled"
            :title="passageBlockReason ?? t('analysis.operations.semanticSearch')"
            @click="setMode('passage')"
          >
            <Brain class="w-4 h-4" />
            <span>{{ t('analysis.semantic.passages') }}</span>
            <span v-if="passageDisabled" class="mode-status">{{ t('analysis.semantic.missing') }}</span>
          </button>
          <button
            type="button"
            role="tab"
            class="mode-btn"
            :class="{ active: mode === 'thesaurus', 'operation-focused': thesaurusFocused }"
            :aria-selected="mode === 'thesaurus'"
            :disabled="thesaurusDisabled"
            :title="thesaurusBlockReason ?? t('analysis.operations.similarWords')"
            @click="setMode('thesaurus')"
          >
            <BookOpen class="w-4 h-4" />
            <span>{{ t('analysis.semantic.thesaurus') }}</span>
            <span v-if="thesaurusDisabled" class="mode-status">{{ t('analysis.semantic.missing') }}</span>
          </button>
        </div>
        <div class="search-input-wrapper">
          <component :is="mode === 'thesaurus' ? BookOpen : Brain" class="search-icon" />
          <input
            v-model="query"
            type="text"
            class="search-input"
            :placeholder="mode === 'thesaurus'
              ? t('analysis.semantic.placeholderThesaurus')
              : t('analysis.semantic.placeholderPassage')"
            :disabled="!!semanticUnavailableNotice"
            @keydown="handleKeydown"
          />
          <button
            class="search-btn"
            :disabled="!!semanticUnavailableNotice || (mode === 'thesaurus' ? thesaurusPending : isPending) || !query.trim()"
            @click="runMode"
          >
            <Search class="w-5 h-5" />
          </button>
        </div>
        <div
          class="scope-pill"
          :class="{ active: docsetStore.hasActiveDocset, stale: !researchScope.ok || docsetStore.activeScopeStale }"
          :title="researchScope.message ?? researchScope.evidence.warning"
        >
          {{ scopeText }}
        </div>
        <label v-if="docsetStore.hasActiveDocset" class="scope-toggle">
          <input v-model="useDocsetScope" type="checkbox" />
          <span>{{ t('analysis.shared.subcorpus') }}</span>
        </label>
      </template>

      <template #right>
        <JobStatusPill
          v-if="mode === 'passage' ? isPending : thesaurusPending"
          status="running"
          :progress="0"
          :message="t('analysis.shared.loading')"
          :canCancel="true"
          @cancel="cancelSearch"
        />
        <label class="top-k-label">
          <span>{{ t('analysis.semantic.top') }}</span>
          <select v-model="topK" class="select-sm">
            <option :value="10">10</option>
            <option :value="20">20</option>
            <option :value="50">50</option>
            <option :value="100">100</option>
          </select>
          <span>{{ mode === 'thesaurus' ? t('analysis.semantic.neighbours') : t('analysis.semantic.results') }}</span>
        </label>
        <SaveAnalysisButton
          v-if="mode === 'passage'"
          type="semantic"
          :defaultName="t('analysis.semantic.defaultName', { query: query || t('analysis.semantic.noQuery') })"
          :corpus="docsetStore.activeCorpus"
          :docset="docsetSnapshot"
          :params="{ query, topK }"
        />
      </template>
    </AnalysisToolbar>

    <div v-if="semanticPartialNotice" class="semantic-partial-notice">
      <AlertTriangle class="w-4 h-4" />
      <span>{{ semanticPartialNotice }}</span>
    </div>

    <EmptyState
      v-if="semanticUnavailableNotice"
      :icon="AlertTriangle"
      :title="t('analysis.semantic.indexMissing')"
      :description="semanticUnavailableNotice"
      size="sm"
    />

    <!-- ════════════════ THESAURUS MODE (F8) ════════════════ -->
    <template v-if="!semanticUnavailableNotice && mode === 'thesaurus'">
      <!-- Loading -->
      <div v-if="thesaurusPending" class="loading-container">
        <div class="thesaurus-list">
          <Skeleton v-for="i in 8" :key="i" height="44px" />
        </div>
      </div>

      <!-- Embeddings unavailable (soft degrade) -->
      <EmptyState
        v-else-if="thesaurusUnavailable"
        :icon="AlertTriangle"
        :title="t('analysis.semantic.embeddingsUnavailable')"
        :description="thesaurusUnavailableReason ?? t('analysis.semantic.embeddingsUnavailableDescription')"
        size="sm"
      />

      <!-- Hard error -->
      <EmptyState
        v-else-if="thesaurusError"
        :icon="AlertTriangle"
        :title="t('analysis.semantic.thesaurusError')"
        :description="(thesaurusError as Error)?.message ?? t('analysis.semantic.unknownError')"
        :action-label="t('analysis.shared.retry')"
        size="sm"
        @action="handleThesaurus"
      />

      <!-- Empty (no query yet) -->
      <EmptyState
        v-else-if="!neighbours.length && !query"
        :icon="BookOpen"
        :title="t('analysis.semantic.thesaurusName')"
        :description="t('analysis.semantic.thesaurusIntro')"
        size="md"
      >
        <div class="mt-6 flex flex-wrap gap-2 justify-center">
          <button
            v-for="example in thesaurusExamples"
            :key="example"
            class="suggestion-chip"
            @click="query = example; handleThesaurus()"
          >
            {{ example }}
          </button>
        </div>
      </EmptyState>

      <!-- No neighbours -->
      <EmptyState
        v-else-if="thesaurusData && !neighbours.length"
        :icon="Search"
        :title="t('analysis.semantic.noNeighboursTitle')"
        :description="t('analysis.semantic.noNeighboursDescription', { query })"
        :action-label="t('analysis.semantic.newSearch')"
        size="sm"
        @action="() => { resetThesaurus(); query = '' }"
      />

      <!-- Neighbour list -->
      <div v-else-if="neighbours.length" class="results-container">
        <div class="results-header">
          <div class="results-summary">
            <span class="results-count">{{ t('analysis.semantic.neighboursCount', { count: neighbours.length, term: thesaurusData?.term ?? query }, neighbours.length) }}</span>
            <div class="meta-badges">
              <span v-if="thesaurusBackend" class="meta-badge">{{ t('analysis.semantic.backendBadge', { backend: thesaurusBackend }) }}</span>
              <span class="meta-badge">{{ t('analysis.semantic.corpusRestricted') }}</span>
            </div>
          </div>
          <button class="btn-reset" @click="resetThesaurus(); query = ''">{{ t('analysis.semantic.newSearch') }}</button>
        </div>

        <p v-if="sharedVectorCount" class="semantic-partial-notice" role="note">
          {{ t('analysis.semantic.sharedVectors', { count: formatNumber(sharedVectorCount), term: thesaurusData?.term ?? query }, sharedVectorCount) }}
        </p>
        <div class="thesaurus-list">
          <div
            v-for="(n, idx) in neighbours"
            :key="`neighbour-${n.word}-${idx}`"
            class="neighbour-row"
          >
            <span class="neighbour-rank">#{{ idx + 1 }}</span>
            <button
              class="neighbour-word"
              :title="t('analysis.semantic.searchInConcordance', { word: n.word })"
              @click="injectIntoSearch(n.word)"
            >
              {{ n.word }}
              <ArrowRightCircle class="w-3.5 h-3.5 neighbour-go" />
            </button>
            <div class="neighbour-score-bar" aria-hidden="true">
              <div
                class="neighbour-score-fill"
                :style="{ width: neighbourBarWidth(n.score) }"
              />
            </div>
            <span class="neighbour-score">{{ n.score !== null ? formatNeighbourScore(n.score) : '–' }}</span>
            <span class="neighbour-freq" :title="t('analysis.semantic.corpusFrequency')">
              <Hash class="w-3 h-3" />{{ formatFrequency(n.corpusFrequency) }}
            </span>
            <button
              class="neighbour-expand"
              :title="t('analysis.semantic.simSearchTitle')"
              @click="injectIntoSearch(n.word, true)"
            >
              <Sparkles class="w-3.5 h-3.5" />
              sim
            </button>
          </div>
        </div>
      </div>
    </template>

    <!-- ════════════════ PASSAGE MODE ════════════════ -->
    <template v-else-if="!semanticUnavailableNotice">

    <!-- Loading -->
    <div v-if="isPending" class="loading-container">
      <div class="loading-grid">
        <Skeleton v-for="i in 6" :key="i" height="120px" />
      </div>
    </div>

    <!-- Error -->
    <EmptyState
      v-else-if="error"
      :icon="AlertTriangle"
      :title="errorTitle"
      :description="errorDescription"
      :action-label="t('analysis.shared.retry')"
      size="sm"
      @action="handleSearch"
    />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!results.length && !query"
      :icon="Brain"
      :title="t('analysis.semantic.passageName')"
      :description="t('analysis.semantic.passageIntro')"
      size="md"
    >
      <div class="mt-6 flex flex-wrap gap-2 justify-center">
        <button
          v-for="example in passageExamples"
          :key="example.label"
          class="suggestion-chip"
          @click="query = example.query; handleSearch()"
        >
          {{ example.label }}
        </button>
      </div>
    </EmptyState>

    <!-- No Results -->
    <EmptyState
      v-else-if="data && !results.length"
      :icon="Search"
      :title="t('analysis.semantic.noResultsTitle')"
      :description="t('analysis.semantic.noResultsDescription', { query })"
      :action-label="t('analysis.semantic.newSearch')"
      size="sm"
      @action="() => { reset(); query = '' }"
    />

    <!-- Results -->
    <div v-else-if="results.length" class="results-container">
      <div class="results-header">
        <div class="results-summary">
          <span class="results-count">{{ t('analysis.semantic.resultsCount', { count: results.length }, results.length) }}</span>
          <div v-if="searchMetaBadges.length" class="meta-badges">
            <span v-for="badge in searchMetaBadges" :key="badge" class="meta-badge">
              {{ badge }}
            </span>
          </div>
        </div>
        <button class="btn-reset" @click="reset(); query = ''">
          {{ t('analysis.semantic.newSearch') }}
        </button>
      </div>

      <div class="results-grid">
        <div
          v-for="(result, idx) in results"
          :key="result.chunk_id"
          class="result-card"
        >
          <div class="result-header">
            <span class="result-rank">#{{ idx + 1 }}</span>
            <span
              class="result-score"
              :class="`score-${semanticScoreBand(result.score, passageScoreKind)}`"
              :title="passageScoreKind === 'cosine'
                ? t('analysis.semantic.cosineTitle', { score: formatDecimal(result.score, 3) })
                : t('analysis.semantic.relevanceTitle', { score: formatDecimal(result.score, 3) })"
            >
              <span class="result-score-unit">{{ semanticScoreUnitLabel(passageScoreKind) }}</span>
              {{ formatSemanticScore(result.score, passageScoreKind) }}
            </span>
          </div>

          <p class="result-text">{{ truncateText(result.text, isMobile ? 150 : 250) }}</p>

          <div class="result-footer">
            <div class="result-meta">
              <FileText class="w-3.5 h-3.5" />
              <span>{{ result.doc_id }}</span>
            </div>
            <div v-if="metadataText(result.metadata?.source)" class="result-meta">
              <Hash class="w-3.5 h-3.5" />
              <span>{{ metadataText(result.metadata?.source) }}</span>
            </div>
          </div>
        </div>
      </div>
    </div>
    </template>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.semantic-tab {
  /* At least as high as the tab, grows with its content: the tab area
     scrolls (App.vue .tab-content). */
  @apply flex flex-col min-h-full;
}

/* Mode switch (Passagen vs Wort-Thesaurus) */
.mode-switch {
  @apply inline-flex items-center gap-1 p-1 rounded-xl;
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.mode-btn {
  @apply inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs md:text-sm font-medium;
  @apply text-neutral-600 dark:text-neutral-400;
  @apply transition-colors;
}

.mode-btn:hover {
  @apply text-neutral-900 dark:text-neutral-100;
}

.mode-btn.active {
  @apply bg-white dark:bg-neutral-900;
  @apply text-copilot-primary;
  @apply shadow-sm;
}

.mode-btn.operation-focused {
  @apply ring-2 ring-amber-300 ring-offset-2 ring-offset-neutral-100;
  @apply dark:ring-amber-500/80 dark:ring-offset-neutral-800;
}

.mode-btn:disabled {
  @apply opacity-50 cursor-not-allowed;
}

.mode-status {
  @apply rounded-full bg-warning-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-warning-700 dark:bg-warning-900/30 dark:text-warning-200;
}

.semantic-partial-notice {
  @apply mx-4 mt-3 flex items-start gap-2 rounded-xl border border-warning-200 bg-warning-50 px-3 py-2 text-xs text-warning-800;
  @apply dark:border-warning-900/60 dark:bg-warning-900/20 dark:text-warning-200;
}

/* Thesaurus neighbour list */
.thesaurus-list {
  @apply flex flex-col gap-1.5 w-full max-w-3xl mx-auto;
}

.neighbour-row {
  @apply flex items-center gap-3 px-3 py-2 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply transition-colors;
}

.neighbour-row:hover {
  @apply border-copilot-primary dark:border-copilot-primary;
}

.neighbour-rank {
  @apply text-xs font-medium text-neutral-400 w-8 flex-shrink-0;
}

.neighbour-word {
  @apply inline-flex items-center gap-1.5 font-medium;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply hover:text-copilot-primary;
  @apply transition-colors;
  min-width: 8rem;
}

.neighbour-go {
  @apply opacity-0 transition-opacity;
}

.neighbour-word:hover .neighbour-go {
  @apply opacity-100;
}

.neighbour-score-bar {
  @apply flex-1 h-1.5 rounded-full overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
  min-width: 3rem;
}

.neighbour-score-fill {
  @apply h-full rounded-full;
  @apply bg-copilot-primary;
  transition: width 0.3s ease;
}

.neighbour-score {
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-300;
  @apply tabular-nums w-12 text-right flex-shrink-0;
}

.neighbour-freq {
  @apply inline-flex items-center gap-0.5 text-xs text-neutral-500;
  @apply tabular-nums w-16 justify-end flex-shrink-0;
}

.neighbour-expand {
  @apply inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs;
  @apply bg-copilot-bg text-copilot-primary;
  @apply hover:bg-copilot-primary hover:text-white;
  @apply transition-colors flex-shrink-0;
}

.search-input-wrapper {
  @apply flex items-center gap-3;
  @apply px-4 py-3 rounded-xl;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply ring-1 ring-transparent;
  @apply focus-within:ring-copilot-primary;
  @apply transition-shadow;
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

.scope-toggle {
  @apply inline-flex items-center gap-1.5 text-xs md:text-sm;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply px-2 py-1 rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
}

.search-icon {
  @apply w-5 h-5 text-copilot-primary flex-shrink-0;
}

.search-input {
  @apply flex-1 bg-transparent border-none;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply placeholder-neutral-500;
  @apply focus:outline-none;
}

.search-btn {
  @apply p-2 rounded-lg;
  @apply bg-copilot-primary text-white;
  @apply hover:bg-copilot-secondary;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

.search-options {
  @apply flex items-center justify-end;
}

.top-k-label {
  @apply flex items-center gap-2;
  @apply text-sm text-neutral-600 dark:text-neutral-400;
}

.select-sm {
  @apply px-2 py-1 rounded;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border-none text-sm;
}

.loading-container,
.error-container,
.empty-state {
  @apply flex-1 flex flex-col items-center justify-center p-4;
}

.loading-grid {
  @apply grid grid-cols-1 md:grid-cols-2 gap-4 w-full max-w-2xl;
}

.btn-retry,
.btn-reset {
  @apply px-4 py-2 rounded-lg text-sm;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.suggestion-chip {
  @apply px-4 py-2 text-sm rounded-full;
  @apply bg-copilot-bg text-copilot-primary;
  @apply hover:bg-copilot-primary hover:text-white;
  @apply transition-colors;
}

.results-container {
  /* Result table: its natural height, at most the visible tab (100cqh).
     Toolbars above it scroll away with the tab. */
  flex: 1 0 auto;
  max-height: 100cqh;
  @apply overflow-auto p-4;
}

.results-header {
  @apply flex items-center justify-between mb-4;
}

.results-summary {
  @apply flex flex-col gap-2;
}

.results-count {
  @apply text-sm text-neutral-600 dark:text-neutral-400;
}

.meta-badges {
  @apply flex flex-wrap gap-1.5;
}

.meta-badge {
  @apply px-2 py-0.5 rounded-full text-xs font-medium;
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.results-grid {
  @apply grid grid-cols-1 md:grid-cols-2 gap-4;
}

.result-card {
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply hover:border-copilot-primary dark:hover:border-copilot-primary;
  @apply transition-colors;
}

.result-header {
  @apply flex items-center justify-between mb-2;
}

.result-rank {
  @apply text-sm font-medium text-neutral-500;
}

.result-score {
  @apply inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium;
}

.result-score-unit {
  @apply text-[10px] font-normal uppercase tracking-wide opacity-70;
}

.score-high {
  @apply bg-success-100 dark:bg-success-900/30 text-success-700 dark:text-success-400;
}

.score-medium {
  @apply bg-warning-100 dark:bg-warning-900/30 text-warning-700 dark:text-warning-400;
}

.score-low {
  @apply bg-neutral-100 dark:bg-neutral-700 text-neutral-600 dark:text-neutral-400;
}

.result-text {
  @apply text-sm text-neutral-700 dark:text-neutral-300;
  @apply leading-relaxed;
}

.result-footer {
  @apply flex flex-wrap items-center gap-3 mt-3;
  @apply pt-3 border-t border-neutral-200 dark:border-neutral-700;
}

.result-meta {
  @apply flex items-center gap-1;
  @apply text-xs text-neutral-500;
}
</style>
