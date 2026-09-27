<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, nextTick, defineAsyncComponent, defineComponent, h } from 'vue'
import { Search, Layers3, Wand2, Code2, Info } from 'lucide-vue-next'
import { useI18n } from 'vue-i18n'
import { formatNumber } from '@/i18n/format'
import { useCorpusCapabilitiesStore, useDocsetStore, useQueryStore } from '@/stores'
import { useProductOperationFocus } from '@/composables/useProductOperationFocus'
import { useAnnounce } from '@/composables/useAnnounce'
import { useCorpusExamples } from '@/composables/useCorpusExamples'
import { useSimpleSearchFilters } from '@/composables/queryBuilder/useSimpleSearchFilters'
import CodeSpanText from '@/components/ui/CodeSpanText.vue'
import type { ProductOperationFocus } from '@/stores/ui'
import {
  buildSimpleSearchQuery,
  buildSimpleSearchSummary,
  activeSimpleFilters,
  createDefaultSimpleSearchState,
  hydrateSimpleSearchQuery,
  labelSimpleTokenAttribute,
  type SimpleSearchIntent,
  type SimpleSearchState,
} from '@/lib/queryBuilder/simple'
import type { CorpusQueryAttributeOption } from '@/lib/corpusFeatureOptions'

type QueryMode = 'simple' | 'advanced'

interface Props {
  modelValue?: string
  initialMode?: QueryMode
}

interface SimpleIntentCard {
  intent: SimpleSearchIntent
  title: string
  text: string
  example: string
  icon: typeof Search
}

const props = withDefaults(defineProps<Props>(), {
  modelValue: '',
  initialMode: 'simple',
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'submit': []
}>()

const { t } = useI18n()
const queryStore = useQueryStore()
const docsetStore = useDocsetStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const { announce, announceError, announceSuccess } = useAnnounce()
// Example terms and tags come from the active corpus: its most frequent nouns
// and verbs and a tag of its recognised part-of-speech tagset.
const { examples: corpusExamples, posTagset: corpusPosTagset } = useCorpusExamples()
const exampleNoun = computed(() => corpusExamples.value.nouns[0] ?? null)
const exampleVerb = computed(() => corpusExamples.value.verbLemmas[0] ?? null)

const mode = ref<QueryMode>(props.initialMode)
const simpleSearch = ref<SimpleSearchState>(createDefaultSimpleSearchState())
const simpleShowFilters = ref(false)
const simpleModeNotice = ref<string | null>(null)
const studioValue = ref(props.modelValue)
const studioLoadState = ref<'idle' | 'loading' | 'ready' | 'error'>('idle')
const studioRenderKey = ref(0)
const shellRef = ref<HTMLElement | null>(null)
const quickSearchInputRef = ref<HTMLInputElement | null>(null)
const focusedCqlfOperation = ref<ProductOperationFocus | null>(null)
let studioFocusTimer: ReturnType<typeof setTimeout> | null = null
const quickSearchHintId = 'quick-search-hint'
const quickSearchSummaryId = 'quick-search-summary'
const quickSearchFiltersId = 'quick-search-filters'
const quickSearchTokenAttributeId = 'quick-search-token-attribute'
const queryModeOrder: readonly [QueryMode, ...QueryMode[]] = ['simple', 'advanced']
const availableSimpleIntentCards = computed(() =>
  simpleIntentCards
    .filter((card) => corpusCapabilities.canUseSimpleIntent(card.intent))
    .map((card) => card.intent === 'exact' ? exactIntentCardForSelectedAttribute(card) : card)
)
const simpleIntentOrder = computed<SimpleSearchIntent[]>(() =>
  availableSimpleIntentCards.value.map((card) => card.intent)
)
const simpleTokenAttributeOptions = computed<CorpusQueryAttributeOption[]>(() =>
  corpusCapabilities.queryAttributes.filter((option) => option.cqlAttribute !== 'sim')
)
const selectedSimpleTokenAttribute = computed<CorpusQueryAttributeOption>(() => {
  const attr = simpleSearch.value.intent === 'lemma'
    ? 'lemma'
    : simpleSearch.value.tokenAttribute || 'word'
  const option = simpleTokenAttributeOptions.value.find((entry) =>
    entry.cqlAttribute === attr || entry.attr === attr
  )
  if (option) return option
  const label = simpleSearch.value.tokenAttributeLabel || labelSimpleTokenAttribute(attr)
  return { attr, cqlAttribute: attr, label, requires: [] }
})
const visibleSimpleTokenAttributeOptions = computed<CorpusQueryAttributeOption[]>(() => {
  const options = simpleTokenAttributeOptions.value
  const selected = selectedSimpleTokenAttribute.value
  if (options.some((entry) => entry.cqlAttribute === selected.cqlAttribute)) return options
  return [selected, ...options]
})
const simpleUsesTokenAttribute = computed(() => simpleSearch.value.intent !== 'similar')
const { consumeFocusFor } = useProductOperationFocus()

const QueryBuilderStudioLoading = defineComponent({
  name: 'QueryBuilderStudioLoading',
  setup() {
    return () =>
      h('div', {
        class: 'studio-loader',
        role: 'status',
        'aria-live': 'polite',
      }, [
        h('div', { class: 'studio-loader-title' }, t('querybuilder.shell.studioLoading')),
        h('p', { class: 'studio-loader-text' }, t('querybuilder.shell.studioLoadingText')),
      ])
  },
})

const QueryBuilderStudioError = defineComponent({
  name: 'QueryBuilderStudioError',
  setup() {
    return () =>
      h('div', {
        class: 'studio-loader studio-loader-error',
        role: 'alert',
        'aria-live': 'assertive',
      }, [
        h('div', { class: 'studio-loader-title' }, t('querybuilder.shell.studioLoadFailed')),
        h('p', { class: 'studio-loader-text' }, t('querybuilder.shell.studioLoadFailedText')),
      ])
  },
})

const QueryBuilderStudio = defineAsyncComponent({
  loader: async () => {
    studioLoadState.value = 'loading'
    try {
      const mod = await import('@/components/search/query-builder/QueryBuilderStudio.vue')
      studioLoadState.value = 'ready'
      return mod
    } catch (error) {
      studioLoadState.value = 'error'
      throw error
    }
  },
  delay: 120,
  timeout: 15000,
  suspensible: false,
  loadingComponent: QueryBuilderStudioLoading,
  errorComponent: QueryBuilderStudioError,
})

const simpleSimilarityChoices = [10, 20, 40]
// Titles and texts are getters that follow the interface language. Example
// values come from the active corpus, "…" stands in when it offers none.
const simpleIntentCards: SimpleIntentCard[] = [
  {
    intent: 'exact',
    get title() { return t('querybuilder.simple.exactTitle') },
    get text() { return t('querybuilder.simple.exactText') },
    get example() { return `[word="${exampleNoun.value ?? '…'}"]` },
    icon: Search,
  },
  {
    intent: 'lemma',
    get title() { return t('querybuilder.simple.lemmaTitle') },
    get text() { return t('querybuilder.simple.lemmaText', { forms: t('querybuilder.simple.lemmaForms') }) },
    get example() { return `[lemma="${exampleVerb.value ?? '…'}"]` },
    icon: Layers3,
  },
  {
    intent: 'similar',
    get title() { return t('querybuilder.simple.similarTitle') },
    get text() { return t('querybuilder.simple.similarText') },
    get example() { return `[sim="${exampleNoun.value ?? '…'}" & k=20]` },
    icon: Wand2,
  },
]


const simpleFilters = useSimpleSearchFilters({ state: simpleSearch, open: simpleShowFilters })
// Example chips fit the search type and the selected token attribute: nouns
// for word forms and similar words, verb lemmas for lemmas, the most frequent
// tags of the corpus for part of speech, none for other attributes.
const simpleExampleTerms = computed<string[]>(() => {
  const intent = simpleSearch.value.intent
  if (intent === 'lemma') return corpusExamples.value.verbLemmas
  if (intent === 'similar') return corpusExamples.value.nouns
  const attr = selectedSimpleTokenAttribute.value.cqlAttribute
  if (attr === 'word') return corpusExamples.value.nouns
  if (attr === 'lemma') return corpusExamples.value.verbLemmas
  if (attr === 'pos') {
    return corpusPosTagset.tags.value
      .filter((tag) => /[A-Za-z]/.test(tag) && tag !== 'PUNCT' && tag !== 'SPACE')
      .slice(0, 3)
  }
  return []
})
const simpleSearchSummary = computed(() => buildSimpleSearchSummary(simpleSearch.value))
const simpleFilterCount = simpleFilters.activeCount
const previewCql = computed(() => buildSimpleSearchQuery(simpleSearch.value))
// Placeholder examples are values of the active corpus. Named entity, morphology
// and dependency examples are labels of the Universal Dependencies and spaCy
// schemes the import writes.
const simpleTermPlaceholderExample = computed<string | null>(() => {
  if (simpleSearch.value.intent === 'similar') return exampleNoun.value
  const attr = selectedSimpleTokenAttribute.value.cqlAttribute
  if (attr === 'lemma') return exampleVerb.value
  if (attr === 'pos') return corpusPosTagset.exampleTag.value
  if (attr === 'ner') return 'PERSON'
  if (attr === 'morph') return 'Number=Plur'
  if (attr === 'rel') return 'nsubj'
  return exampleNoun.value
})
const simpleTermPlaceholder = computed(() =>
  simpleTermPlaceholderExample.value
    ? t('querybuilder.common.forExample', { example: simpleTermPlaceholderExample.value })
    : t('querybuilder.simple.termPlaceholder')
)
const simpleTermHint = computed(() => {
  if (simpleSearch.value.intent === 'lemma') return t('querybuilder.simple.hintLemma')
  if (simpleSearch.value.intent === 'similar') return t('querybuilder.simple.hintSimilar')
  const attr = selectedSimpleTokenAttribute.value.cqlAttribute
  if (attr === 'word') return t('querybuilder.simple.hintWord')
  return t('querybuilder.simple.hintAttr', { label: selectedSimpleTokenAttribute.value.label })
})
const simpleTokenAttributeHint = computed(() => {
  const option = selectedSimpleTokenAttribute.value
  if (option.cqlAttribute === 'word') return t('querybuilder.simple.attrHintWord')
  return t('querybuilder.simple.attrHintOther', { syntax: `[${option.cqlAttribute}="…"]` })
})
const busyStatusText = computed(() => {
  if (mode.value !== 'advanced') return ''
  if (studioLoadState.value === 'loading') return t('querybuilder.shell.studioLoading')
  if (studioLoadState.value === 'error') return t('querybuilder.shell.studioLoadFailed')
  return t('querybuilder.shell.studioReady')
})
function normalizeQuery(text: string): string {
  return String(text ?? '').replace(/\r\n?/g, '\n').trim()
}

function clearStudioFocusTimer() {
  if (studioFocusTimer) {
    clearTimeout(studioFocusTimer)
    studioFocusTimer = null
  }
}

function cycleOption<T>(options: readonly [T, ...T[]], current: T, direction: 1 | -1): T {
  const currentIndex = options.indexOf(current)
  if (currentIndex === -1) return options[0]
  const nextIndex = (currentIndex + direction + options.length) % options.length
  return options[nextIndex] ?? options[0]
}

function getLastOption<T>(options: readonly [T, ...T[]]): T {
  return options[options.length - 1] ?? options[0]
}

function exactIntentCardForSelectedAttribute(card: SimpleIntentCard): SimpleIntentCard {
  const option = selectedSimpleTokenAttribute.value
  if (option.cqlAttribute === 'word') return card
  return {
    ...card,
    title: t('querybuilder.simple.attrTitle', { label: option.label }),
    text: t('querybuilder.simple.attrText', { label: option.label }),
    example: `[${option.cqlAttribute}="${option.cqlAttribute === 'pos' ? (corpusPosTagset.exampleTag.value ?? '…') : '…'}"]`,
  }
}

function tokenAttributeOptionFor(attr: string): CorpusQueryAttributeOption | null {
  return visibleSimpleTokenAttributeOptions.value.find((option) =>
    option.cqlAttribute === attr || option.attr === attr
  ) ?? null
}

function tokenAttributeForIntent(intent: SimpleSearchIntent): CorpusQueryAttributeOption | null {
  if (intent === 'similar') return selectedSimpleTokenAttribute.value
  if (intent === 'lemma') return tokenAttributeOptionFor('lemma')
  const current = selectedSimpleTokenAttribute.value
  if (current.cqlAttribute !== 'lemma' && current.cqlAttribute !== 'sim') return current
  return tokenAttributeOptionFor('word') ?? visibleSimpleTokenAttributeOptions.value[0] ?? current
}

function canUseSimpleSearchState(state: SimpleSearchState): boolean {
  if (!corpusCapabilities.loaded && !corpusCapabilities.activeSummary) return true
  if (!corpusCapabilities.canUseSimpleIntent(state.intent)) return false
  if (state.intent === 'exact') {
    return corpusCapabilities.canUseTokenAttribute(state.tokenAttribute || 'word')
  }
  if (state.intent === 'lemma') {
    return corpusCapabilities.canUseTokenAttribute('lemma')
  }
  return true
}

function cycleSimpleIntent(current: SimpleSearchIntent, direction: 1 | -1): SimpleSearchIntent {
  const options = simpleIntentOrder.value
  if (!options.length) return 'exact'
  const currentIndex = options.indexOf(current)
  if (currentIndex === -1) return options[0] ?? 'exact'
  const nextIndex = (currentIndex + direction + options.length) % options.length
  return options[nextIndex] ?? options[0] ?? 'exact'
}

function lastSimpleIntent(): SimpleSearchIntent {
  const options = simpleIntentOrder.value
  return options[options.length - 1] ?? 'exact'
}

async function focusQuickInput() {
  await nextTick()
  quickSearchInputRef.value?.focus()
  quickSearchInputRef.value?.select()
}

function focusStudioPrimaryControl(attempt = 0) {
  clearStudioFocusTimer()
  const root = shellRef.value
  const focusTarget = root?.querySelector<HTMLTextAreaElement>('.cql-textarea')
    ?? root?.querySelector<HTMLButtonElement>('.command-launcher-btn')
  if (focusTarget) {
    focusTarget.focus()
    return
  }
  if (attempt >= 20) return
  studioFocusTimer = setTimeout(() => focusStudioPrimaryControl(attempt + 1), 80)
}

function applySimpleSearchState(state: SimpleSearchState | null) {
  const nextState = state ? { ...state } : createDefaultSimpleSearchState()
  simpleSearch.value = nextState
  // Open the filter area for a query with filters. Never close it here: with
  // v-model every keystroke returns as modelValue and is hydrated again.
  if (activeSimpleFilters(nextState).length) simpleShowFilters.value = true
}

function focusModeControl(targetMode: QueryMode) {
  nextTick(() => {
    shellRef.value
      ?.querySelector<HTMLButtonElement>(`[data-mode-option="${targetMode}"]`)
      ?.focus()
  })
}

function focusIntentControl(targetIntent: SimpleSearchIntent) {
  nextTick(() => {
    shellRef.value
      ?.querySelector<HTMLButtonElement>(`[data-intent-option="${targetIntent}"]`)
      ?.focus()
  })
}

function hydrateSimpleModeFromValue(rawValue: string): boolean {
  const normalized = normalizeQuery(rawValue)
  const hydrated = hydrateSimpleSearchQuery(normalized)
  if (!hydrated) {
    if (!normalized) {
      applySimpleSearchState(createDefaultSimpleSearchState())
      simpleModeNotice.value = null
      return true
    }
    simpleModeNotice.value = t('querybuilder.shell.noticeStudioFeatures')
    return false
  }
  if (!canUseSimpleSearchState(hydrated)) {
    simpleModeNotice.value = t('querybuilder.shell.noticeCorpusFeature')
    return false
  }
  applySimpleSearchState(hydrated)
  simpleModeNotice.value = null
  return true
}

function selectSimpleIntent(intent: SimpleSearchIntent) {
  if (!corpusCapabilities.canUseSimpleIntent(intent)) {
    simpleModeNotice.value = t('querybuilder.shell.noticeIntentUnavailable')
    return
  }
  const option = tokenAttributeForIntent(intent)
  simpleSearch.value = {
    ...simpleSearch.value,
    intent,
    tokenAttribute: option?.cqlAttribute ?? simpleSearch.value.tokenAttribute,
    tokenAttributeLabel: option?.label ?? simpleSearch.value.tokenAttributeLabel,
    similarityK: intent === 'similar' ? simpleSearch.value.similarityK || 20 : simpleSearch.value.similarityK,
  }
}

function selectSimpleTokenAttribute(attr: string) {
  const option = tokenAttributeOptionFor(attr)
  if (!option || !corpusCapabilities.canUseTokenAttribute(option.cqlAttribute)) {
    simpleModeNotice.value = t('querybuilder.shell.noticeAttributeUnavailable')
    return
  }
  simpleSearch.value = {
    ...simpleSearch.value,
    intent: option.cqlAttribute === 'lemma' ? 'lemma' : 'exact',
    tokenAttribute: option.cqlAttribute,
    tokenAttributeLabel: option.label,
  }
}

function applySimpleExample(term: string) {
  simpleSearch.value = {
    ...simpleSearch.value,
    term,
  }
}

function clearSimpleFilters() {
  simpleSearch.value = {
    ...simpleSearch.value,
    filters: {},
  }
}

function setSimpleFilter(field: string, value: string) {
  const filters = { ...simpleSearch.value.filters }
  if (value) filters[field] = value
  else delete filters[field]
  simpleSearch.value = { ...simpleSearch.value, filters }
}

function handleModeKeydown(event: KeyboardEvent, currentMode: QueryMode) {
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    event.preventDefault()
    const nextMode = cycleOption(queryModeOrder, currentMode, 1)
    switchMode(nextMode)
    focusModeControl(nextMode)
    return
  }
  if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    event.preventDefault()
    const nextMode = cycleOption(queryModeOrder, currentMode, -1)
    switchMode(nextMode)
    focusModeControl(nextMode)
    return
  }
  if (event.key === 'Home') {
    event.preventDefault()
    switchMode(queryModeOrder[0])
    focusModeControl(queryModeOrder[0])
    return
  }
  if (event.key === 'End') {
    event.preventDefault()
    const lastMode = getLastOption(queryModeOrder)
    switchMode(lastMode)
    focusModeControl(lastMode)
  }
}

function handleIntentKeydown(event: KeyboardEvent, currentIntent: SimpleSearchIntent) {
  if (event.key === 'ArrowRight' || event.key === 'ArrowDown') {
    event.preventDefault()
    const nextIntent = cycleSimpleIntent(currentIntent, 1)
    selectSimpleIntent(nextIntent)
    focusIntentControl(nextIntent)
    return
  }
  if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') {
    event.preventDefault()
    const nextIntent = cycleSimpleIntent(currentIntent, -1)
    selectSimpleIntent(nextIntent)
    focusIntentControl(nextIntent)
    return
  }
  if (event.key === 'Home') {
    event.preventDefault()
    const firstIntent = simpleIntentOrder.value[0] ?? 'exact'
    selectSimpleIntent(firstIntent)
    focusIntentControl(firstIntent)
    return
  }
  if (event.key === 'End') {
    event.preventDefault()
    const lastIntent = lastSimpleIntent()
    selectSimpleIntent(lastIntent)
    focusIntentControl(lastIntent)
  }
}

function retryStudioLoad() {
  if (mode.value !== 'advanced') return
  studioLoadState.value = 'loading'
  studioRenderKey.value += 1
  announce(t('querybuilder.shell.studioReloading'))
}

function restoreQuickModeAfterStudioError() {
  const couldHydrate = hydrateSimpleModeFromValue(studioValue.value || props.modelValue)
  if (!couldHydrate) {
    applySimpleSearchState(createDefaultSimpleSearchState())
    simpleModeNotice.value = t('querybuilder.shell.studioUnavailableRebuild')
  } else {
    simpleModeNotice.value = t('querybuilder.shell.studioUnavailableContinue')
  }
  studioLoadState.value = 'idle'
  mode.value = 'simple'
  announceError(t('querybuilder.shell.studioUnavailableAnnounce'))
}

function switchMode(newMode: QueryMode) {
  if (newMode === mode.value) return

  if (newMode === 'advanced') {
    simpleModeNotice.value = null
    studioValue.value = previewCql.value.trim()
    studioLoadState.value = 'loading'
    studioRenderKey.value += 1
    mode.value = 'advanced'
    announce(t('querybuilder.shell.studioOpening'))
    return
  }

  if (!hydrateSimpleModeFromValue(studioValue.value || props.modelValue)) {
    announceError(t('querybuilder.shell.cannotConvert'))
    return
  }

  mode.value = 'simple'
  announceSuccess(t('querybuilder.shell.quickModeActive'))
}

function applyFocusedCqlfOperation(focus: ProductOperationFocus) {
  focusedCqlfOperation.value = focus
  if (mode.value !== 'advanced') {
    switchMode('advanced')
  } else {
    focusStudioPrimaryControl()
  }
}

function handleStudioUpdate(value: string) {
  studioValue.value = value
  studioLoadState.value = 'ready'
  emit('update:modelValue', value)
}

function handleStudioRequestQuickMode() {
  switchMode('simple')
}

function handleSubmit() {
  const currentValue = mode.value === 'simple' ? previewCql.value : studioValue.value
  if (currentValue.trim()) {
    emit('submit')
  }
}

watch(previewCql, (value) => {
  if (mode.value !== 'simple') return
  emit('update:modelValue', value)
})

watch(
  () => props.modelValue,
  (value) => {
    const normalized = normalizeQuery(value)
    studioValue.value = normalized
    if (mode.value === 'simple') {
      if (!hydrateSimpleModeFromValue(normalized)) {
        mode.value = 'advanced'
        studioLoadState.value = 'loading'
        studioRenderKey.value += 1
      }
    }
  },
  { immediate: true }
)

watch(
  () => props.initialMode,
  (value) => {
    mode.value = value
    if (value === 'simple') {
      studioLoadState.value = 'idle'
      if (!hydrateSimpleModeFromValue(props.modelValue)) {
        mode.value = 'advanced'
        studioValue.value = normalizeQuery(props.modelValue)
        studioLoadState.value = 'loading'
        studioRenderKey.value += 1
      }
      return
    }
    studioValue.value = normalizeQuery(props.modelValue)
    studioLoadState.value = 'loading'
    studioRenderKey.value += 1
  },
  { immediate: true }
)

consumeFocusFor(['query.cqlf'], applyFocusedCqlfOperation)

watch(mode, (newMode) => {
  if (newMode === 'simple') {
    studioLoadState.value = 'idle'
    clearStudioFocusTimer()
    void focusQuickInput()
    return
  }
  studioLoadState.value = 'loading'
  focusStudioPrimaryControl()
})

watch(studioLoadState, (state) => {
  if (state === 'ready') {
    announceSuccess(t('querybuilder.shell.studioReady'))
    focusStudioPrimaryControl()
  } else if (state === 'error') {
    announceError(t('querybuilder.shell.studioLoadFailedAnnounce'))
  }
})

watch(simpleModeNotice, (value) => {
  if (value) {
    announceError(value)
  }
})

watch(
  () => queryStore.filters.corpus,
  () => {
    // Metadata values belong to one corpus, a filter from another corpus would match nothing.
    if (activeSimpleFilters(simpleSearch.value).length) clearSimpleFilters()
    void docsetStore.loadMetaOptions(true)
  }
)

watch([simpleIntentOrder, simpleTokenAttributeOptions], () => {
  if (canUseSimpleSearchState(simpleSearch.value)) return
  studioValue.value = previewCql.value
  mode.value = 'advanced'
  studioLoadState.value = 'loading'
  studioRenderKey.value += 1
  simpleModeNotice.value = t('querybuilder.shell.noticeQuickOptionsMissing')
})

onMounted(() => {
  if (!corpusCapabilities.loaded) void corpusCapabilities.fetchCorpora()
  void docsetStore.loadMetaOptions()
  if (mode.value === 'simple') {
    void focusQuickInput()
  } else {
    studioLoadState.value = 'loading'
    focusStudioPrimaryControl()
  }
})

onUnmounted(() => {
  clearStudioFocusTimer()
})
</script>

<template>
  <div
    ref="shellRef"
    class="query-builder-shell"
    :aria-busy="mode === 'advanced' && studioLoadState === 'loading' ? 'true' : 'false'"
  >
    <p v-if="busyStatusText" class="sr-only" aria-live="polite">
      {{ busyStatusText }}
    </p>

    <template v-if="mode === 'simple'">
      <div class="mode-toggle" role="radiogroup" :aria-label="t('querybuilder.shell.modeGroup')">
        <button
          class="mode-btn active"
          type="button"
          data-mode-option="simple"
          role="radio"
          aria-checked="true"
          @click="switchMode('simple')"
          @keydown="handleModeKeydown($event, 'simple')"
        >
          <Wand2 class="w-4 h-4" />
          <span class="mode-btn-copy">
            <span>{{ t('querybuilder.shell.modeQuick') }}</span>
            <span class="mode-btn-detail">{{ t('querybuilder.shell.modeQuickDetail') }}</span>
          </span>
        </button>
        <button
          class="mode-btn"
          type="button"
          data-mode-option="advanced"
          role="radio"
          aria-checked="false"
          @click="switchMode('advanced')"
          @keydown="handleModeKeydown($event, 'advanced')"
        >
            <Code2 class="w-4 h-4" />
            <span class="mode-btn-copy">
              <span>{{ t('querybuilder.shell.modeStudio') }}</span>
              <span class="mode-btn-detail">{{ t('querybuilder.shell.modeStudioDetail') }}</span>
            </span>
          </button>
      </div>

      <p v-if="simpleModeNotice" class="mode-notice">
        {{ simpleModeNotice }}
      </p>

      <div class="simple-mode">
        <section class="simple-hero">
          <div class="simple-hero-copy">
            <div class="simple-hero-title">{{ t('querybuilder.simple.heroTitle') }}</div>
            <p class="simple-hero-text">
              {{ t('querybuilder.simple.heroText') }}
            </p>
          </div>
          <div class="simple-hero-summary">
            {{ simpleSearchSummary }}
          </div>
        </section>

        <section class="simple-intent-grid" role="radiogroup" :aria-label="t('querybuilder.simple.intentGroup')">
          <button
            v-for="card in availableSimpleIntentCards"
            :key="card.intent"
            type="button"
            :data-intent-option="card.intent"
            :class="['simple-intent-card', { active: simpleSearch.intent === card.intent }]"
            role="radio"
            :aria-checked="simpleSearch.intent === card.intent"
            @click="selectSimpleIntent(card.intent)"
            @keydown="handleIntentKeydown($event, card.intent)"
          >
            <div class="simple-intent-title-row">
              <component :is="card.icon" class="w-4 h-4" />
              <span>{{ card.title }}</span>
            </div>
            <p class="simple-intent-text"><CodeSpanText :text="card.text" /></p>
            <code class="simple-card-example">{{ card.example }}</code>
          </button>
        </section>

        <section class="simple-panel">
          <label class="simple-field-label" for="quick-search-term">{{ t('querybuilder.simple.termLabel') }}</label>
          <input
            ref="quickSearchInputRef"
            id="quick-search-term"
            v-model="simpleSearch.term"
            type="text"
            class="simple-input"
            :aria-describedby="`${quickSearchHintId} ${quickSearchSummaryId}`"
            :placeholder="simpleTermPlaceholder"
            @keydown.enter="handleSubmit"
            @keydown.ctrl.enter.prevent="handleSubmit"
            @keydown.meta.enter.prevent="handleSubmit"
          />
          <p :id="quickSearchHintId" class="mode-hint">
            {{ simpleTermHint }}
          </p>
          <div v-if="simpleExampleTerms.length" class="simple-example-row">
            <span class="simple-example-label">{{ t('querybuilder.simple.examples') }}</span>
            <button
              v-for="example in simpleExampleTerms"
              :key="example"
              type="button"
              class="simple-example-chip"
              @click="applySimpleExample(example)"
            >
              {{ example }}
            </button>
          </div>
        </section>

        <section class="simple-precision-grid">
          <div
            v-if="simpleUsesTokenAttribute && visibleSimpleTokenAttributeOptions.length > 1"
            class="simple-panel"
          >
            <label class="simple-field-label" :for="quickSearchTokenAttributeId">{{ t('querybuilder.simple.tokenAttribute') }}</label>
            <select
              :id="quickSearchTokenAttributeId"
              :value="selectedSimpleTokenAttribute.cqlAttribute"
              class="simple-select"
              @change="selectSimpleTokenAttribute(($event.target as HTMLSelectElement).value)"
            >
              <option
                v-for="option in visibleSimpleTokenAttributeOptions"
                :key="option.cqlAttribute"
                :value="option.cqlAttribute"
              >
                {{ option.label }}
              </option>
            </select>
            <p class="mode-hint">{{ simpleTokenAttributeHint }}</p>
          </div>

          <div v-if="simpleSearch.intent === 'similar'" class="simple-panel">
            <label class="simple-field-label" for="quick-search-k">{{ t('querybuilder.simple.similarityLabel') }}</label>
            <select id="quick-search-k" v-model.number="simpleSearch.similarityK" class="simple-select">
              <option v-for="choice in simpleSimilarityChoices" :key="choice" :value="choice">
                {{ t('querybuilder.simple.similarityOption', { k: formatNumber(choice) }) }}
              </option>
            </select>
            <p class="mode-hint">{{ t('querybuilder.simple.similarityHint') }}</p>
          </div>

          <div class="simple-panel">
            <div class="simple-panel-header">
              <div class="simple-panel-copy">
                <div class="simple-field-label">{{ t('querybuilder.simple.narrowTitle') }}</div>
                <p class="mode-hint">{{ t('querybuilder.simple.narrowHint') }}</p>
              </div>
              <button
                type="button"
                class="simple-link-btn"
                :aria-expanded="simpleShowFilters ? 'true' : 'false'"
                :aria-controls="quickSearchFiltersId"
                @click="simpleShowFilters = !simpleShowFilters"
              >
                {{
                  simpleShowFilters
                    ? t('querybuilder.simple.filtersHide')
                    : simpleFilterCount
                      ? t('querybuilder.simple.filtersActive', { count: formatNumber(simpleFilterCount) }, simpleFilterCount)
                      : t('querybuilder.simple.filtersShow')
                }}
              </button>
            </div>

            <div
              v-if="simpleShowFilters"
              :id="quickSearchFiltersId"
              class="simple-filter-grid"
            >
              <p v-if="simpleFilters.error.value" class="mode-hint simple-filter-note" role="alert">
                {{ simpleFilters.error.value }}
              </p>
              <p v-else-if="!simpleFilters.fields.value.length" class="mode-hint simple-filter-note">
                {{ simpleFilters.schemaKnown.value ? t('querybuilder.simple.noFilterFields') : t('querybuilder.simple.filtersUnavailable') }}
              </p>
              <label
                v-for="field in simpleFilters.fields.value"
                :key="field"
                class="simple-select-field"
              >
                <!-- i18n-ignore: metadata field name of the corpus -->
                <span class="simple-select-label">{{ field }}</span>
                <select
                  class="simple-select"
                  :data-filter-field="field"
                  :value="simpleSearch.filters[field] ?? ''"
                  :aria-busy="simpleFilters.loading.value ? 'true' : 'false'"
                  @change="setSimpleFilter(field, ($event.target as HTMLSelectElement).value)"
                >
                  <option value="">
                    {{ simpleFilters.loading.value ? t('querybuilder.simple.filtersLoading') : t('querybuilder.simple.allValues') }}
                  </option>
                  <option v-for="value in simpleFilters.choices(field)" :key="value" :value="value">
                    {{ value }}
                  </option>
                </select>
              </label>

              <div class="simple-filter-actions">
                <button type="button" class="simple-link-btn" :disabled="!simpleFilterCount" @click="clearSimpleFilters">
                  {{ t('querybuilder.simple.clearFilters') }}
                </button>
              </div>
            </div>
          </div>
        </section>

        <section class="simple-panel simple-translation-panel">
          <div class="simple-translation-title-row">
            <Info class="w-4 h-4" />
            <span>{{ t('querybuilder.simple.translationTitle') }}</span>
          </div>
          <p :id="quickSearchSummaryId" class="simple-translation-text" aria-live="polite">{{ simpleSearchSummary }}</p>
          <code class="simple-card-example">{{ previewCql || t('querybuilder.common.empty') }}</code>
        </section>
      </div>
    </template>

    <template v-else>
      <div
        v-if="studioLoadState === 'error'"
        class="studio-shell-error"
        role="alert"
        aria-live="assertive"
      >
        <div class="studio-shell-error-copy">
          <div class="studio-shell-error-title">{{ t('querybuilder.shell.studioLoadFailed') }}</div>
          <p class="studio-shell-error-text">
            {{ t('querybuilder.shell.errorText') }}
          </p>
        </div>
        <div class="studio-shell-error-actions">
          <button type="button" class="simple-link-btn" @click="retryStudioLoad">
            {{ t('querybuilder.shell.retry') }}
          </button>
          <button type="button" class="simple-link-btn" @click="restoreQuickModeAfterStudioError">
            {{ t('querybuilder.shell.toQuick') }}
          </button>
        </div>
      </div>

      <QueryBuilderStudio
        v-else
        :key="studioRenderKey"
        :model-value="studioValue"
        :focused-product-operation="focusedCqlfOperation"
        initial-mode="advanced"
        embedded-studio
        @update:model-value="handleStudioUpdate"
        @request-quick-mode="handleStudioRequestQuickMode"
        @submit="emit('submit')"
      />
    </template>
  </div>
</template>

<style scoped>
.query-builder-shell {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 1rem;
  padding-bottom: 6rem;
}

.mode-toggle {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.25rem;
  border-radius: 0.75rem;
  background: #f3f4f6;
}

.mode-btn {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border: 0;
  border-radius: 0.5rem;
  background: transparent;
  color: #525252;
  font-size: 0.875rem;
  font-weight: 600;
  transition: color 160ms ease, background-color 160ms ease, box-shadow 160ms ease;
}

.mode-btn-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  text-align: left;
  line-height: 1.2;
}

.mode-btn-detail {
  font-size: 0.75rem;
  font-weight: 500;
  color: #737373;
}

.mode-btn.active {
  background: #ffffff;
  color: #171717;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.mode-btn:hover:not(.active) {
  color: #171717;
}

.mode-notice {
  padding: 0.75rem 1rem;
  border: 1px solid #fcd34d;
  border-radius: 0.75rem;
  background: #fffbeb;
  color: #78350f;
  font-size: 0.875rem;
  line-height: 1.6;
}

.simple-mode {
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

.simple-hero,
.simple-panel,
.studio-loader {
  border: 1px solid #e5e7eb;
  border-radius: 1rem;
  background: #ffffff;
}

.simple-hero {
  display: grid;
  gap: 1rem;
  padding: 1.25rem;
}

.simple-hero-copy {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.simple-hero-title,
.studio-loader-title {
  color: #171717;
  font-size: 1.125rem;
  font-weight: 700;
}

.simple-hero-text,
.simple-translation-text,
.simple-intent-text,
.studio-loader-text {
  color: #525252;
  font-size: 0.875rem;
  line-height: 1.6;
}

.simple-hero-summary {
  padding: 1rem;
  border-radius: 1rem;
  background: #eff6ff;
  color: #1e3a8a;
  font-size: 0.875rem;
  font-weight: 600;
  line-height: 1.6;
}

.simple-intent-grid {
  display: grid;
  gap: 0.75rem;
}

.simple-intent-card {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
  border: 1px solid #e5e7eb;
  border-radius: 1rem;
  background: #ffffff;
  text-align: left;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.simple-intent-card.active {
  border-color: #60a5fa;
  background: #eff6ff;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08);
}

.simple-intent-title-row,
.simple-translation-title-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: #171717;
  font-size: 0.875rem;
  font-weight: 700;
}

.simple-card-example {
  display: block;
  padding: 0.5rem 0.75rem;
  border-radius: 0.75rem;
  background: #0a0a0a;
  color: #86efac;
  font-size: 0.75rem;
  line-height: 1.6;
  word-break: break-word;
}

.simple-field-label {
  display: block;
  color: #171717;
  font-size: 0.875rem;
  font-weight: 700;
}

.simple-panel,
.studio-loader {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
}

.studio-shell-error {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
  padding: 1rem;
  border: 1px solid #fecaca;
  border-radius: 1rem;
  background: #fef2f2;
}

.studio-shell-error-copy {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.studio-shell-error-title {
  color: #7f1d1d;
  font-size: 1rem;
  font-weight: 700;
}

.studio-shell-error-text {
  color: #991b1b;
  font-size: 0.875rem;
  line-height: 1.6;
}

.studio-shell-error-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.5rem;
}

.simple-example-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.5rem;
}

.simple-example-label,
.simple-select-label {
  color: #737373;
  font-size: 0.75rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.simple-example-chip,
.simple-link-btn {
  padding: 0.375rem 0.75rem;
  border: 1px solid #e5e7eb;
  border-radius: 999px;
  background: #fafafa;
  color: #404040;
  font-size: 0.875rem;
  font-weight: 600;
  transition: border-color 160ms ease, background-color 160ms ease;
}

.simple-example-chip:hover,
.simple-link-btn:hover,
.simple-intent-card:hover,
.mode-btn:hover {
  background: #f5f5f5;
}

.simple-link-btn:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.simple-precision-grid {
  display: grid;
  gap: 1rem;
}

.simple-panel-header {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.simple-panel-copy {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
}

.simple-filter-grid {
  display: grid;
  gap: 0.75rem;
}

.simple-select-field {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.simple-filter-actions {
  display: flex;
  justify-content: flex-end;
}

.simple-filter-note {
  grid-column: 1 / -1;
  margin: 0;
}

.simple-select,
.simple-input {
  width: 100%;
  padding: 0.625rem 0.75rem;
  border: 1px solid #e5e7eb;
  border-radius: 0.75rem;
  background: #ffffff;
  color: #171717;
  font-size: 0.875rem;
}

.simple-input:focus,
.simple-select:focus,
.mode-btn:focus-visible,
.simple-intent-card:focus-visible,
.simple-example-chip:focus-visible,
.simple-link-btn:focus-visible {
  outline: 2px solid #3b82f6;
  outline-offset: 2px;
}

.simple-translation-panel {
  border-style: dashed;
  background: #fafafa;
}

.mode-hint {
  color: #737373;
  font-size: 0.875rem;
}

.studio-loader {
  min-height: 14rem;
  justify-content: center;
}

.studio-loader-error {
  border-color: #fecaca;
  background: #fef2f2;
}

@media (prefers-color-scheme: dark) {
  .mode-toggle {
    background: #262626;
  }

  .mode-btn {
    color: #a3a3a3;
  }

  .mode-btn.active {
    background: #404040;
    color: #fafafa;
  }

  .mode-btn:hover:not(.active) {
    color: #fafafa;
  }

  .mode-btn-detail,
  .mode-hint,
  .simple-example-label,
  .simple-select-label {
    color: #a3a3a3;
  }

  .simple-hero,
  .simple-panel,
  .studio-loader {
    border-color: #3f3f46;
    background: rgba(23, 23, 23, 0.88);
  }

  .simple-hero-title,
  .simple-field-label,
  .simple-intent-title-row,
  .simple-translation-title-row,
  .studio-loader-title {
    color: #fafafa;
  }

  .simple-hero-text,
  .simple-translation-text,
  .simple-intent-text,
  .studio-loader-text {
    color: #d4d4d8;
  }

  .simple-hero-summary {
    background: rgba(59, 130, 246, 0.14);
    color: #dbeafe;
  }

  .simple-intent-card {
    border-color: #3f3f46;
    background: rgba(23, 23, 23, 0.88);
  }

  .simple-intent-card.active {
    border-color: #60a5fa;
    background: rgba(59, 130, 246, 0.12);
  }

  .simple-example-chip,
  .simple-link-btn {
    border-color: #3f3f46;
    background: #262626;
    color: #e5e7eb;
  }

  .simple-example-chip:hover,
  .simple-link-btn:hover,
  .simple-intent-card:hover,
  .mode-btn:hover {
    background: #303030;
  }

  .simple-select,
  .simple-input {
    border-color: #3f3f46;
    background: #262626;
    color: #fafafa;
  }

  .simple-translation-panel {
    background: rgba(10, 10, 10, 0.45);
  }

  .studio-loader-error {
    border-color: rgba(248, 113, 113, 0.45);
    background: rgba(127, 29, 29, 0.22);
  }

  .studio-shell-error {
    border-color: rgba(248, 113, 113, 0.45);
    background: rgba(127, 29, 29, 0.22);
  }

  .studio-shell-error-title {
    color: #fecaca;
  }

  .studio-shell-error-text {
    color: #fca5a5;
  }
}

@media (min-width: 768px) {
  .query-builder-shell {
    padding-bottom: 1.5rem;
  }

  .mode-toggle {
    flex-direction: row;
  }

  .simple-panel-header {
    flex-direction: row;
    align-items: flex-start;
    justify-content: space-between;
  }

  .simple-filter-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .simple-filter-actions {
    grid-column: span 2 / span 2;
  }
}

@media (min-width: 1024px) {
  .simple-hero {
    grid-template-columns: minmax(0, 1fr) 22rem;
  }
}

@media (min-width: 1280px) {
  .simple-intent-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .simple-precision-grid {
    grid-template-columns: minmax(0, 16rem) minmax(0, 1fr);
  }
}
</style>
