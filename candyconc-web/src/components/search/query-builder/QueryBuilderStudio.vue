<script setup lang="ts">
/**
 * The advanced CQLF editor. QueryBuilder.vue owns the separate quick-search
 * surface; this component deliberately stays focused on exact query work.
 */
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { AlertTriangle, Code2, Info } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import BuilderHistoryPanel from '@/components/search/query-builder/BuilderHistoryPanel.vue'
import CqlNodeEditor from '@/components/search/query-builder/CqlNodeEditor.vue'
import CqlSuggestionsPanel from '@/components/search/query-builder/CqlSuggestionsPanel.vue'
import CqlPreviewSubmitRow from '@/components/search/query-builder/panels/CqlPreviewSubmitRow.vue'
import type { SuggestionItem } from '@/api/client'
import {
  useCorpusCapabilitiesStore,
  useDocsetStore,
  useProductCapabilitiesStore,
  useQueryStore,
} from '@/stores'
import {
  productOperationFocusIs,
  productOperationFocusMatches,
} from '@/composables/useProductOperationFocus'
import { useCqlfOperations } from '@/composables/useCqlfOperations'
import { useBuilderHistory } from '@/composables/queryBuilder/useBuilderHistory'
import { useCqlSuggestions } from '@/composables/queryBuilder/useCqlSuggestions'
import { useMetaValueOptions } from '@/composables/queryBuilder/useMetaValueOptions'
import { useQuerySamples } from '@/composables/queryBuilder/useQuerySamples'
import { QUERY_SAMPLES_KEY } from '@/lib/queryBuilder/samples'
import {
  collectMetaFields,
  createBuilderRoot,
  generateBuilderQuery,
  nodeTypeLabel,
  type CqlBuilderMode,
  type CqlBuilderNode,
} from '@/lib/queryBuilder/ast'
import { isCqlSuggestionSupported } from '@/lib/corpusFeatureOptions'
import { isSalientCqlSuggestion, sortSuggestionsBySalience } from '@/components/search/cqlAutocomplete'
import { builderGuide, commonMetaFields } from '@/lib/queryBuilder/constants'
import { cloneBuilderNode, starterTemplates } from '@/lib/queryBuilder/fragments'
import type { BuilderTemplate } from '@/lib/queryBuilder/types'
import type { ProductOperationFocus } from '@/stores/ui'

interface Props {
  modelValue?: string
  /**
   * Kept as a compatibility prop for the only parent. The quick mode belongs
   * to QueryBuilder.vue, so the studio always works in advanced mode.
   */
  initialMode?: CqlBuilderMode
  embeddedStudio?: boolean
  focusedProductOperation?: ProductOperationFocus | null
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  initialMode: 'advanced',
  embeddedStudio: false,
  focusedProductOperation: null,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  submit: []
  'request-quick-mode': []
}>()

const { t } = useI18n()
const queryStore = useQueryStore()
const docsetStore = useDocsetStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const {
  canAnalyseQuery,
  analyseBlockReason,
} = useCqlfOperations()

// Words and tags of the active corpus for examples, explanations and starter
// templates. The node and metadata editors receive them through provide.
const querySamples = useQuerySamples()
provide(QUERY_SAMPLES_KEY, querySamples)
const guideItems = computed(() => builderGuide(querySamples.value))
// Example query in the placeholder of the direct input.
const directInputExample = computed(() =>
  `where(genre="${querySamples.value.metaValue}", within(<s>, [lemma="${querySamples.value.verb}"]))`
)
const mode = ref<CqlBuilderMode>('advanced')
const rootNode = ref<CqlBuilderNode>(createBuilderRoot())
const advancedCql = ref('')
const selectedNodeId = ref<string | null>(rootNode.value.id)
const selectedMetaId = ref<string | null>(null)
let isApplyingHydratedNode = false

const canUseCqlf = computed(() =>
  productCapabilities.hasContract && productCapabilities.isVisible('query.cqlf')
)
const activeCorpus = computed(() => {
  const corpus = queryStore.filters.corpus
  return typeof corpus === 'string' && corpus.trim()
    ? corpus
    : docsetStore.activeCorpus ?? 'default'
})
const tokenAttributeSuggestions = computed(() =>
  corpusCapabilities.cqlTokenAttributes.length ? corpusCapabilities.cqlTokenAttributes : ['word']
)
const availableStarterTemplates = computed(() =>
  starterTemplates(querySamples.value).filter((template) =>
    (template.requiresTokenAttributes ?? []).every((attribute) =>
      corpusCapabilities.canUseTokenAttribute(attribute)
    )
  )
)
const focusedOperation = computed(() => props.focusedProductOperation)
const cqlfDiagnosticsFocused = computed(() =>
  productOperationFocusIs(focusedOperation.value, 'query.cqlf.analyse') ||
  productOperationFocusMatches(
    focusedOperation.value,
    'query.cqlf.diagnostics',
    'query.cqlf.analyse',
  )
)
const cqlfSuggestionsFocused = computed(() =>
  productOperationFocusIs(focusedOperation.value, 'query.cqlf.lexicon_suggest') ||
  productOperationFocusMatches(
    focusedOperation.value,
    'query.cqlf.suggestions',
    'query.cqlf.lexicon_suggest',
  )
)
const assistantFocus = computed<'diagnostics' | 'suggestions' | null>(() => {
  if (cqlfDiagnosticsFocused.value) return 'diagnostics'
  if (cqlfSuggestionsFocused.value) return 'suggestions'
  return null
})

const generatedCql = computed(() => generateBuilderQuery(rootNode.value))
const previewCql = computed(() => advancedCql.value.trim() || generatedCql.value)
const suggestionCorpus = computed(() => queryStore.filters.corpus || docsetStore.activeCorpus || undefined)

const {
  historyEntries,
  historyIndex,
  queueHistoryLabel,
  flushPendingHistory,
  scheduleHistoryCommit,
  resetHistory,
  markNextHistoryCommitSuppressed,
  consumeHistoryCommitFlags,
  canUndo,
  canRedo,
  visibleHistoryEntries,
  historySummary,
} = useBuilderHistory(rootNode)

const {
  suggestions,
  isSuggesting,
  analysisErrors,
  analysisWarnings,
  diagnosticsStatus,
  diagnosticsError,
  unsupportedReason,
  clearDiagnostics,
  clearSuggestTimer,
  cancelSuggestRequest,
  scheduleSuggest,
} = useCqlSuggestions({
  mode,
  generatedCql,
  corpus: suggestionCorpus,
  enabled: canUseCqlf,
  canAnalyse: canAnalyseQuery,
  analysisBlockReason: analyseBlockReason,
  queueHistoryLabel,
  commitHydratedNode,
})

const {
  metaValueChoices,
  metaValueError,
  clearMetaTimer,
  cancelMetaRequest,
  scheduleMetaValueLoad,
} = useMetaValueOptions({ rootNode, mode, activeCorpus })

// Field names of the active corpus metadata schema. The generic fallback list
// applies only while the schema is unknown.
const metaFieldOptions = computed(() => {
  const schemaFields = docsetStore.metaFields.map((field) => field.name)
  const fromTree = collectMetaFields(rootNode.value)
  return Array.from(new Set([...(schemaFields.length ? schemaFields : commonMetaFields), ...fromTree]))
    .sort((left, right) => left.localeCompare(right, 'de'))
})
const builderStatus = computed(() => {
  if (analysisErrors.value.length) {
    return {
      tone: 'error',
      title: t('querybuilder.studio.statusInvalidTitle'),
      detail: analysisErrors.value[0] ?? t('querybuilder.studio.statusInvalidDetail'),
    }
  }
  if (diagnosticsStatus.value === 'unavailable') {
    return {
      tone: 'warn',
      title: t('querybuilder.studio.statusDiagnosticsTitle'),
      detail: diagnosticsError.value ?? t('querybuilder.studio.statusDiagnosticsDetail'),
    }
  }
  if (unsupportedReason.value) {
    return {
      tone: 'warn',
      title: t('querybuilder.studio.statusFreeTitle'),
      detail: unsupportedReason.value,
    }
  }
  return {
    tone: 'ok',
    title: t('querybuilder.studio.statusOkTitle', { type: nodeTypeLabel(rootNode.value.type) }),
    detail: t('querybuilder.studio.statusOkDetail'),
  }
})
const fixSuggestions = computed(() =>
  suggestions.value.filter((item) =>
    item.kind === 'fix' && isCqlSuggestionSupported(corpusCapabilities.activeSummary, item)
  )
)
const completionSuggestions = computed(() =>
  sortSuggestionsBySalience(
    suggestions.value.filter((item) =>
      item.kind !== 'fix' && isCqlSuggestionSupported(corpusCapabilities.activeSummary, item)
    )
  )
)
const salientSuggestions = computed(() =>
  completionSuggestions.value.filter(isSalientCqlSuggestion)
)
const otherCompletionSuggestions = computed(() =>
  completionSuggestions.value.filter((item) => !isSalientCqlSuggestion(item))
)
const showAssistant = computed(() =>
  Boolean(
    assistantFocus.value ||
    isSuggesting.value ||
    analysisErrors.value.length ||
    analysisWarnings.value.length ||
    diagnosticsStatus.value === 'unavailable' ||
    salientSuggestions.value.length ||
    otherCompletionSuggestions.value.length ||
    fixSuggestions.value.length
  )
)

function normalizeCql(value: string): string {
  return String(value ?? '').replace(/\r\n?/g, '\n').trim()
}

function replaceRoot(next: CqlBuilderNode) {
  queueHistoryLabel(t('querybuilder.studio.historyStructureChanged'))
  rootNode.value = next
  selectedNodeId.value = next.id
  selectedMetaId.value = null
}

function selectNode(id: string) {
  selectedNodeId.value = id
  selectedMetaId.value = null
}

function selectMeta(id: string) {
  selectedMetaId.value = id
  selectedNodeId.value = null
}

function applyTemplate(template: BuilderTemplate) {
  const missing = (template.requiresTokenAttributes ?? []).filter((attribute) =>
    !corpusCapabilities.canUseTokenAttribute(attribute)
  )
  if (missing.length) return

  queueHistoryLabel(t('querybuilder.studio.historyTemplate', { title: template.title }))
  const next = template.create()
  rootNode.value = next
  selectedNodeId.value = next.id
  selectedMetaId.value = null
  advancedCql.value = generateBuilderQuery(next)
  clearDiagnostics()
  scheduleMetaValueLoad()
  scheduleSuggest(advancedCql.value)
}

function commitHydratedNode(next: CqlBuilderNode) {
  isApplyingHydratedNode = true
  rootNode.value = next
  selectedNodeId.value = next.id
  selectedMetaId.value = null
  isApplyingHydratedNode = false
}

function applySuggestion(item: SuggestionItem) {
  queueHistoryLabel(t('querybuilder.studio.historySuggestionApplied'))
  advancedCql.value = normalizeCql(item.text)
}

function handleManualInput() {
  clearDiagnostics()
}

function restoreHistory(index: number) {
  flushPendingHistory()
  const entry = historyEntries.value[index]
  if (!entry) return

  markNextHistoryCommitSuppressed()
  const restored = cloneBuilderNode(entry.node)
  rootNode.value = restored
  selectedNodeId.value = restored.id
  selectedMetaId.value = null
  advancedCql.value = entry.cql
  historyIndex.value = index
  clearDiagnostics()
  scheduleMetaValueLoad()
  scheduleSuggest(entry.cql)
}

function undoHistory() {
  flushPendingHistory()
  if (canUndo.value) restoreHistory(historyIndex.value - 1)
}

function redoHistory() {
  flushPendingHistory()
  if (canRedo.value) restoreHistory(historyIndex.value + 1)
}

function jumpToHistory(index: number) {
  if (index !== historyIndex.value) restoreHistory(index)
}

function handleHistoryKeydown(event: KeyboardEvent) {
  const target = event.target
  if (
    target instanceof HTMLInputElement ||
    target instanceof HTMLTextAreaElement ||
    target instanceof HTMLSelectElement ||
    (target instanceof HTMLElement && target.isContentEditable)
  ) {
    return
  }
  if (!(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z') return

  event.preventDefault()
  if (event.shiftKey) redoHistory()
  else undoHistory()
}

function submit() {
  if (previewCql.value.trim()) emit('submit')
}

watch(
  () => props.modelValue,
  (value) => {
    advancedCql.value = normalizeCql(value)
    scheduleSuggest(advancedCql.value)
  },
  { immediate: true }
)

watch(
  () => advancedCql.value,
  (value) => {
    scheduleSuggest(value)
  }
)

watch(
  rootNode,
  () => {
    const { label, suppress } = consumeHistoryCommitFlags()
    if (!isApplyingHydratedNode) {
      advancedCql.value = generateBuilderQuery(rootNode.value)
      clearDiagnostics()
    }
    scheduleMetaValueLoad()
    if (!suppress) scheduleHistoryCommit(label)
  },
  { deep: true }
)

watch(previewCql, (value) => {
  emit('update:modelValue', value)
})

watch(activeCorpus, () => {
  void docsetStore.loadMetaOptions(true)
  scheduleMetaValueLoad()
  scheduleSuggest(previewCql.value)
})

watch(canUseCqlf, (enabled) => {
  if (enabled) scheduleSuggest(previewCql.value)
})

onMounted(() => {
  void productCapabilities.load()
  if (!corpusCapabilities.loaded) void corpusCapabilities.fetchCorpora()
  void docsetStore.loadMetaOptions()
  resetHistory(t('querybuilder.studio.historyStart'))
  window.addEventListener('keydown', handleHistoryKeydown)
  scheduleMetaValueLoad()
  scheduleSuggest(advancedCql.value || generatedCql.value)
})

onUnmounted(() => {
  flushPendingHistory()
  window.removeEventListener('keydown', handleHistoryKeydown)
  clearSuggestTimer()
  cancelSuggestRequest()
  clearMetaTimer()
  cancelMetaRequest()
})
</script>

<template>
  <div class="query-builder advanced-mode">
    <header v-if="props.embeddedStudio" class="studio-entry-bar">
      <div>
        <h2 class="studio-entry-title">{{ t('querybuilder.studio.title') }}</h2>
        <p class="studio-entry-text">
          {{ t('querybuilder.studio.intro') }}
        </p>
      </div>
      <button type="button" class="simple-link-btn studio-entry-btn" @click="emit('request-quick-mode')">
        {{ t('querybuilder.studio.toQuick') }}
      </button>
    </header>

    <section class="builder-guide" :aria-label="t('querybuilder.studio.guideLabel')">
      <div class="builder-guide-header">
        <Info class="w-4 h-4" aria-hidden="true" />
        <span>{{ t('querybuilder.studio.guideTitle') }}</span>
      </div>
      <div class="builder-guide-grid">
        <article v-for="item in guideItems" :key="item.title" class="guide-card">
          <div class="guide-title-row">
            <component :is="item.icon" class="w-4 h-4" aria-hidden="true" />
            <h3 class="guide-title">{{ item.title }}</h3>
          </div>
          <p class="guide-text">{{ item.text }}</p>
          <code class="guide-example">{{ item.example }}</code>
        </article>
      </div>
    </section>

    <section
      :class="[
        'builder-status',
        builderStatus.tone === 'error' ? 'is-error' : builderStatus.tone === 'warn' ? 'is-warn' : 'is-ok',
      ]"
      aria-live="polite"
    >
      <AlertTriangle v-if="builderStatus.tone !== 'ok'" class="w-4 h-4" aria-hidden="true" />
      <Info v-else class="w-4 h-4" aria-hidden="true" />
      <div>
        <h3 class="builder-status-title">{{ builderStatus.title }}</h3>
        <p class="builder-status-text">{{ builderStatus.detail }}</p>
      </div>
    </section>

    <section class="starter-section">
      <div class="section-header">
        <h3 class="section-title">{{ t('querybuilder.studio.startersTitle') }}</h3>
        <p class="section-detail">{{ t('querybuilder.studio.startersDetail') }}</p>
      </div>
      <div class="starter-grid">
        <button
          v-for="template in availableStarterTemplates"
          :key="template.id"
          type="button"
          class="starter-card"
          @click="applyTemplate(template)"
        >
          <span class="starter-card-header">
            <component :is="template.icon" class="w-4 h-4" aria-hidden="true" />
            <span>{{ template.title }}</span>
          </span>
          <span class="starter-card-text">{{ template.text }}</span>
          <code class="starter-card-code">{{ template.example }}</code>
        </button>
      </div>
    </section>

    <section class="ast-section">
      <div class="section-header">
        <h3 class="section-title">{{ t('querybuilder.studio.astTitle') }}</h3>
        <p class="section-detail">{{ t('querybuilder.studio.astDetail') }}</p>
      </div>
      <CqlNodeEditor
        :node="rootNode"
        :meta-field-options="metaFieldOptions"
        :meta-value-choices="metaValueChoices"
        :token-attribute-suggestions="tokenAttributeSuggestions"
        :selected-node-id="selectedNodeId"
        :selected-meta-id="selectedMetaId"
        @replace="replaceRoot"
        @select-node="selectNode"
        @select-meta="selectMeta"
      />
      <p v-if="metaValueError" class="section-detail" role="status">
        {{ metaValueError }}
      </p>
      <datalist id="query-builder-meta-fields">
        <option v-for="field in metaFieldOptions" :key="field" :value="field" />
      </datalist>
    </section>

    <section class="cql-override">
      <label class="override-label" for="cql-direct-input">
        <Code2 class="w-4 h-4" aria-hidden="true" />
        {{ t('querybuilder.studio.directInput') }}
      </label>
      <textarea
        id="cql-direct-input"
        v-model="advancedCql"
        class="cql-textarea"
        rows="5"
        :placeholder="t('querybuilder.common.forExample', { example: directInputExample })"
        @input="handleManualInput"
        @keydown.ctrl.enter.prevent="submit"
        @keydown.meta.enter.prevent="submit"
      />
      <p class="override-note">
        {{ t('querybuilder.studio.directNote') }}
      </p>
    </section>

    <CqlSuggestionsPanel
      v-if="showAssistant"
      :class="{ 'operation-focused': assistantFocus }"
      :is-suggesting="isSuggesting"
      :analysis-errors="analysisErrors"
      :analysis-warnings="analysisWarnings"
      :diagnostics-status="diagnosticsStatus"
      :diagnostics-error="diagnosticsError"
      :focused-mode="assistantFocus"
      :salient-suggestions="salientSuggestions"
      :other-completion-suggestions="otherCompletionSuggestions"
      :fix-suggestions="fixSuggestions"
      @apply="applySuggestion"
    />

    <BuilderHistoryPanel
      :summary="historySummary"
      :can-undo="canUndo"
      :can-redo="canRedo"
      :entries="visibleHistoryEntries"
      @undo="undoHistory"
      @redo="redoHistory"
      @jump="jumpToHistory"
    />

    <CqlPreviewSubmitRow
      :preview-cql="previewCql"
      @submit="submit"
    />
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.query-builder {
  @apply min-w-0 space-y-4 pb-24 md:pb-6;
}

.studio-entry-bar {
  @apply flex flex-col gap-3 rounded-xl border border-neutral-200 bg-white px-4 py-4 dark:border-neutral-700 dark:bg-neutral-900/70 md:flex-row md:items-center md:justify-between;
}

.studio-entry-title {
  @apply text-base font-semibold text-neutral-900 dark:text-neutral-100;
}

.studio-entry-text,
.section-detail,
.guide-text,
.builder-status-text,
.override-note {
  @apply mt-1 text-sm leading-6 text-neutral-600 dark:text-neutral-300;
}

.studio-entry-btn {
  @apply self-start md:self-auto;
}

.builder-guide,
.starter-section,
.ast-section,
.cql-override {
  @apply rounded-xl border border-neutral-200 bg-white p-4 dark:border-neutral-700 dark:bg-neutral-900/80;
}

.builder-guide-header,
.guide-title-row,
.override-label {
  @apply flex items-center gap-2 text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.builder-guide-grid {
  @apply mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-4;
}

.guide-card {
  @apply rounded-lg border border-neutral-200 bg-neutral-50 p-3 dark:border-neutral-700 dark:bg-neutral-800/70;
}

.guide-title {
  @apply text-sm font-semibold;
}

.guide-example,
.starter-card-code {
  @apply mt-2 block overflow-x-auto rounded bg-neutral-950 px-2 py-1.5 font-mono text-xs text-emerald-300;
}

.builder-status {
  @apply flex gap-3 rounded-xl border p-4;
}

.builder-status.is-ok {
  @apply border-emerald-200 bg-emerald-50 text-emerald-950 dark:border-emerald-500/30 dark:bg-emerald-950/30 dark:text-emerald-100;
}

.builder-status.is-warn {
  @apply border-amber-200 bg-amber-50 text-amber-950 dark:border-amber-500/30 dark:bg-amber-950/30 dark:text-amber-100;
}

.builder-status.is-error {
  @apply border-rose-200 bg-rose-50 text-rose-950 dark:border-rose-500/30 dark:bg-rose-950/30 dark:text-rose-100;
}

.builder-status-title {
  @apply font-semibold;
}

.builder-status-text {
  @apply text-current opacity-80;
}

.section-header {
  @apply mb-3;
}

.section-title {
  @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.starter-grid {
  @apply grid gap-3 sm:grid-cols-2 xl:grid-cols-3;
}

.starter-card {
  @apply flex min-w-0 flex-col items-start rounded-lg border border-neutral-200 bg-neutral-50 p-3 text-left transition-colors hover:border-primary-300 hover:bg-primary-50/60 dark:border-neutral-700 dark:bg-neutral-800/70 dark:hover:bg-neutral-800;
}

.starter-card-header {
  @apply flex items-center gap-2 text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.starter-card-text {
  @apply mt-2 text-sm leading-5 text-neutral-600 dark:text-neutral-300;
}

.cql-textarea {
  @apply mt-2 w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 font-mono text-sm text-neutral-900 outline-none focus:border-primary-500 focus:ring-2 focus:ring-primary-500/30 dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-100;
}

@media (max-width: 640px) {
  .builder-guide,
  .starter-section,
  .ast-section,
  .cql-override {
    @apply p-3;
  }
}
</style>
