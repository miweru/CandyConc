<script setup lang="ts">
/**
 * SearchBar - Main query input with history and query builder
 */
import { ref, computed, watch, onMounted, onUnmounted, defineAsyncComponent } from 'vue'
import { useQueryStore, useUiStore, useSearchHistoryStore, useOnboardingStore } from '@/stores'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useDispatch } from '@/composables'
import { useCqlfOperations } from '@/composables/useCqlfOperations'
import { useCorpusPosTagset } from '@/composables/useCorpusPosTagset'
import { isDescribedPosTag, POS_GROUP_ORDER, posTagGroup } from '@/lib/posTagset'
import type { SuggestionItem } from '@/api/client'
import {
  analyseQuery,
  humanizeSuggestionHint,
  isSalientCqlSuggestion,
  looksLikeCqlEntry,
  mergeAutocompleteSuggestions,
  normalizeSuggestionHint,
  sortSuggestionsBySalience,
} from '@/components/search/cqlAutocomplete'
import {
  normalizeBuilderSeedTerm,
  shouldOpenQueryBuilderInAdvancedMode,
} from '@/utils/queryTerm'
import { isCqlfQuery, isPlainPhraseQuery, plainPhraseToCql } from '@/lib/cqlDetection'
import {
  isCqlSuggestionSupported,
  normalizeCqlAttribute,
} from '@/lib/corpusFeatureOptions'
import { Search, X, Loader2, Wand2 } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import Modal from '@/components/ui/Modal.vue'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// Lazy load QueryBuilder (only shown on demand via modal)
const QueryBuilder = defineAsyncComponent({
  loader: () => import('@/components/search/QueryBuilder.vue'),
  delay: 100
})

const queryStore = useQueryStore()
const uiStore = useUiStore()
const searchHistoryStore = useSearchHistoryStore()
const onboardingStore = useOnboardingStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const { dispatch } = useDispatch()
const {
  canUseCqlf,
  canAnalyseQuery,
  canSuggestLexicon,
  analyseBlockReason,
  lexiconSuggestBlockReason,
  loadSuggestions,
  loadLexiconSuggestions,
} = useCqlfOperations()

const inputRef = ref<HTMLInputElement | null>(null)
const localTerm = ref(queryStore.term)
const builderTerm = ref(localTerm.value)
const builderMode = ref<'simple' | 'advanced'>('simple')
const isFocused = ref(false)
const suggestions = ref<SuggestionItem[]>([])
const activeSuggestionIndex = ref(-1)
const isSuggesting = ref(false)

let suggestTimer: ReturnType<typeof setTimeout> | null = null
let blurTimer: ReturnType<typeof setTimeout> | null = null
let suggestAbort: AbortController | null = null
let suggestRequestId = 0

const isSearching = computed(() => queryStore.isLoading)
const isStreaming = computed(() => queryStore.streamingProgress?.isStreaming ?? false)
const caseSensitive = computed(() => queryStore.caseSensitive)
const isCqlInput = computed(() => isCqlfQuery(localTerm.value))
const caseButtonTitle = computed(() =>
  isCqlInput.value || looksLikeBareCql.value
    ? t('search.searchBar.caseTitleCql')
    : t('search.searchBar.caseTitle')
)
const cqlCaseModeNotice = computed(() =>
  canUseCqlf.value && isCqlInput.value
    ? t('search.searchBar.caseNotice')
    : null
)
const cqlAssistAttributes = computed(() => corpusCapabilities.queryAttributes)
// The corpus word attribute used to translate a plain phrase to a token sequence.
const wordCqlAttribute = computed(
  () =>
    corpusCapabilities.queryAttributes.find((option) => option.attr === 'word')?.cqlAttribute ??
    'word'
)
// Tag descriptions and groups follow the tagset the corpus pos values belong
// to (Universal POS from spaCy, STTS from some VRT sources), never a fixed one.
const corpusPosTagset = useCorpusPosTagset({ immediate: false })
const hasPosTagsetLabels = computed(() => corpusPosTagset.tagset.value !== null)
const cqlAssistFeatureNotice = computed(() => {
  if (!canUseCqlf.value) return null
  return t('search.searchBar.assistFeatures', { attributes: corpusCapabilities.activeFeatureSummary.queryAttributes })
})
const searchPlaceholder = computed(() =>
  canUseCqlf.value
    ? t('search.searchBar.placeholderQuery')
    : t('search.searchBar.placeholder')
)
const searchAriaLabel = computed(() =>
  canUseCqlf.value
    ? t('search.searchBar.ariaQuery')
    : t('search.searchBar.aria')
)

// Inline CQL diagnostics (DT-FE-UX-CORE): bare-CQL detection + structural
// errors/warnings shown beneath the search bar without blocking submit.
const queryDiagnostics = computed(() => canUseCqlf.value ? analyseQuery(localTerm.value) : [])
const looksLikeBareCql = computed(() => canUseCqlf.value && looksLikeCqlEntry(localTerm.value))

function applyCqlPrefix() {
  if (!canUseCqlf.value) {
    uiStore.showToast(t('search.searchBar.cqlNotEnabled'), 'warning')
    return
  }
  const trimmed = localTerm.value.trim()
  if (!trimmed || trimmed.toLowerCase().startsWith('cql:')) return
  localTerm.value = `cql:${trimmed}`
  inputRef.value?.focus()
}

function toggleCaseSensitive() {
  queryStore.setCaseSensitive(!queryStore.caseSensitive)
}
const suggestionCorpus = computed(() => queryStore.filters.corpus || undefined)
const streamingCount = computed(() => queryStore.streamingProgress?.count ?? 0)
const streamingElapsed = computed(() => {
  const elapsedMs = queryStore.streamingProgress?.elapsedMs ?? 0
  if (!elapsedMs) return ''
  const totalSeconds = Math.floor(elapsedMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
})
const hasHistory = computed(() => searchHistoryStore.hasHistory)
const recentSearches = computed(() => searchHistoryStore.recentSearches)
const showAssistPanel = computed(() => isFocused.value)
const hasSuggestions = computed(() => displaySuggestions.value.length > 0)

const legendItems = computed(() => [
  { key: 'Enter', label: t('search.searchBar.legendEnter') },
  { key: 'Esc', label: t('search.searchBar.legendEsc') },
  { key: '↑/↓', label: t('search.searchBar.legendArrows') },
  ...(canUseCqlf.value ? [{ key: 'cql:', label: t('search.searchBar.legendCql') }] : []),
])

const completionSuggestions = computed(() =>
  suggestions.value.filter(
    (item) => item.kind !== 'fix' && isCqlSuggestionSupported(corpusCapabilities.activeSummary, item)
  )
)
const fixSuggestions = computed(() =>
  suggestions.value.filter(
    (item) => item.kind === 'fix' && isCqlSuggestionSupported(corpusCapabilities.activeSummary, item)
  )
)
const suggestionIndexMap = computed(() => {
  const map = new Map<SuggestionItem, number>()
  displaySuggestions.value.forEach((item, idx) => map.set(item, idx))
  return map
})

const posGroupOrder: readonly string[] = POS_GROUP_ORDER

function getPosGroup(tag: string): string {
  return posTagGroup(tag.trim().toUpperCase(), corpusPosTagset.tagset.value)
}

// Hint prefixes are an internal protocol between the lexicon, the server
// suggestions and the grouping below, so they stay as they are. Only the
// displayed label is translated.
const HINT_PREFIX_KEYS: Record<string, string> = {
  pos: 'search.searchBar.attrPos',
  lemma: 'search.searchBar.attrLemma',
  wort: 'search.searchBar.attrWord',
  ner: 'search.searchBar.attrNer',
  'entität': 'search.searchBar.attrNer',
  morphologie: 'search.searchBar.attrMorph',
  relation: 'search.searchBar.attrRel',
  attribut: 'search.searchBar.attrGeneric',
}

function hintPrefixLabel(prefix: string): string {
  const key = HINT_PREFIX_KEYS[prefix.trim().toLowerCase()]
  return key ? t(key) : prefix
}

function displayHint(hint: string): string {
  const match = hint.match(/^([^:]+):\s*(.*)$/)
  if (!match || !match[1]) return hint
  const key = HINT_PREFIX_KEYS[match[1].trim().toLowerCase()]
  return key ? `${t(key)}: ${match[2] ?? ''}` : hint
}

// Internal hint prefix (see HINT_PREFIX_KEYS), not display text.
// i18n-ignore-start
function cqlAttributeSuggestionLabel(attr: string): string {
  const normalized = attr.trim().toLowerCase()
  if (normalized === 'pos') return 'POS'
  if (normalized === 'lemma') return 'Lemma'
  if (normalized === 'word') return 'Wort'
  if (normalized === 'ent' || normalized === 'ner') return 'NER'
  if (normalized === 'morph') return 'Morphologie'
  if (normalized === 'rel') return 'Relation'
  return normalized || 'Attribut'
}
// i18n-ignore-end

const completionBlocks = computed(() => {
  const posItems: SuggestionItem[] = []
  const lemmaItems: SuggestionItem[] = []
  const wordItems: SuggestionItem[] = []
  const nerItems: SuggestionItem[] = []
  const morphItems: SuggestionItem[] = []
  const relItems: SuggestionItem[] = []
  const genericItems: SuggestionItem[] = []

  completionSuggestions.value.forEach((item) => {
    const match = item.hint?.match(/^([^:]+):/i)
    if (!match || !match[1]) {
      genericItems.push(item)
      return
    }
    const label = match[1].trim().toLowerCase()
    if (label === 'pos') {
      posItems.push(item)
    } else if (label === 'lemma') {
      lemmaItems.push(item)
    } else if (label === 'wort') {
      wordItems.push(item)
    } else if (label === 'ner' || label === 'entität') {
      nerItems.push(item)
    } else if (label === 'morphologie') {
      morphItems.push(item)
    } else if (label === 'relation') {
      relItems.push(item)
    } else {
      genericItems.push(item)
    }
  })

  const blocks: Array<{ title: string; items: SuggestionItem[] }> = []

  if (posItems.length) {
    if (!hasPosTagsetLabels.value) {
      blocks.push({ title: 'POS', items: posItems })
    } else {
      const grouped: Record<string, SuggestionItem[]> = {}
      posItems.forEach((item) => {
        const tag = item.hint?.split(':')[1]?.trim() ?? ''
        const group = getPosGroup(tag)
        if (!grouped[group]) grouped[group] = []
        grouped[group].push(item)
      })
      posGroupOrder.forEach((group) => {
        const items = grouped[group]
        if (items?.length) {
          blocks.push({ title: t('search.searchBar.blockPosGroup', { group: t(`search.searchBar.posGroups.${group}`) }), items })
        }
      })
    }
  }

  if (wordItems.length) blocks.push({ title: t('search.searchBar.blockWords'), items: wordItems })
  if (lemmaItems.length) blocks.push({ title: t('search.searchBar.blockLemmas'), items: lemmaItems })
  if (nerItems.length) blocks.push({ title: t('search.searchBar.blockEntities'), items: nerItems })
  if (morphItems.length) blocks.push({ title: t('search.searchBar.blockMorph'), items: morphItems })
  if (relItems.length) blocks.push({ title: t('search.searchBar.blockRelations'), items: relItems })
  if (genericItems.length) {
    const rankedGenericItems = sortSuggestionsBySalience(genericItems)
    const salientGenericItems = rankedGenericItems.filter(isSalientCqlSuggestion)
    const otherGenericItems = rankedGenericItems.filter((item) => !isSalientCqlSuggestion(item))

    if (salientGenericItems.length) {
      blocks.push({ title: t('search.searchBar.blockSalient'), items: salientGenericItems })
    }
    if (otherGenericItems.length) {
      blocks.push({
        title: salientGenericItems.length ? t('search.searchBar.blockMore') : t('search.searchBar.blockGeneric'),
        items: otherGenericItems,
      })
    }
  }

  return blocks
})

const displaySuggestions = computed(() => {
  const list: SuggestionItem[] = []
  completionBlocks.value.forEach((block) => list.push(...block.items))
  list.push(...fixSuggestions.value)
  return list
})
const assistHint = ref<string | null>(null)

// Server hints (normalized) mapped to catalog keys for their explanation.
const suggestionHintKeys: Record<string, string> = {
  'token lemma set': 'search.searchBar.hintLemmaSet',
  'token lemma equals': 'search.searchBar.hintLemmaEquals',
  'token word equals': 'search.searchBar.hintWordEquals',
  'token pos equals': 'search.searchBar.hintPosEquals',
  'token semantic similarity': 'search.searchBar.hintSemantic',
  'wrapper within sentence': 'search.searchBar.hintWithinSentence',
  'wrapper doc filter + query': 'search.searchBar.hintDocFilter',
  'anzahl ähnlicher wörter': 'search.searchBar.hintTopK',
  'group': 'search.searchBar.hintGroup',
}

// Tag description in the recognised tagset of the corpus (search.searchBar.upos
// or search.searchBar.stts), null for tags outside it.
function posTagLabel(tag: string): string | null {
  const upper = tag.trim().toUpperCase()
  const tagset = corpusPosTagset.tagset.value
  if (!tagset || !isDescribedPosTag(upper, tagset)) return null
  return tagset === 'upos' ? t(`search.searchBar.upos.${upper}`) : t(`search.searchBar.stts.${upper}`)
}

function normalizeHintLabel(value: string): string {
  return normalizeSuggestionHint(value)
}

function formatSuggestionHint(item: SuggestionItem): string | null {
  if (item.hint) {
    const normalized = normalizeHintLabel(item.hint)
    const key = suggestionHintKeys[normalized]
    if (key) return t(key)
    return displayHint(humanizeSuggestionHint(item.hint) ?? item.hint)
  }
  if (item.hasPlaceholders) return t('search.searchBar.replacePlaceholdersExample')
  return null
}

function formatSuggestionLabel(item: SuggestionItem): string {
  if (item.kind === 'fix') return formatSuggestionHint(item) ?? t('search.searchBar.repair')
  if (item.hint) {
    const match = item.hint.match(/^(POS|Lemma|Wort|NER):\s*(.+)$/i)
    if (match && match[1] && match[2]) {
      const rawValue = match[2]
      if (match[1].toLowerCase() === 'pos') {
        const pretty = hasPosTagsetLabels.value ? posTagLabel(rawValue) : null
        const posLabel = hintPrefixLabel('pos')
        return pretty ? `${posLabel}: ${rawValue} · ${pretty}` : `${posLabel}: ${rawValue}`
      }
      return `${hintPrefixLabel(match[1])}: ${rawValue}`
    }
  }
  if (item.hint) return displayHint(item.hint)
  return t('search.searchBar.insert')
}

function nextStepHint(text: string): string | null {
  if (text.endsWith('="') || text.endsWith("='")) return t('search.searchBar.stepEnterWord')
  if (text.endsWith('[')) return t('search.searchBar.stepStartToken')
  if (text.endsWith(']')) return t('search.searchBar.stepNextToken')
  return null
}

function buildCqlAssist(term: string): { suggestions: SuggestionItem[]; hint: string | null } {
  const lower = term.toLowerCase()
  if (!lower.startsWith('cql:')) {
    return { suggestions: [], hint: null }
  }

  const suggestions: SuggestionItem[] = []
  const raw = term
  const lastOpen = raw.lastIndexOf('[')
  const lastClose = raw.lastIndexOf(']')
  const insideToken = lastOpen > lastClose
  const attrOptions = cqlAssistAttributes.value

  const pushSuggestion = (text: string, hint: string) => {
    if (text === raw) return
    suggestions.push({ text, hint, kind: 'complete' })
  }

  if (!insideToken) {
    const needsSpace = raw.length > 0 && !raw.endsWith(' ') && !raw.endsWith(':') && !raw.endsWith('[')
    const spacer = needsSpace ? ' ' : ''
    attrOptions.forEach(option => {
      pushSuggestion(`${raw}${spacer}[${option.cqlAttribute}="`, t('search.searchBar.assistStartToken', { label: option.label }))
    })
    return { suggestions, hint: null }
  }

  const tokenContent = raw.slice(lastOpen + 1)
  const eqIndex = tokenContent.indexOf('=')
  if (eqIndex === -1) {
    const partial = tokenContent.trim()
    const base = raw.slice(0, lastOpen + 1)
    attrOptions.forEach(option => {
      if (!partial || option.cqlAttribute.startsWith(partial)) {
        pushSuggestion(`${base}${option.cqlAttribute}="`, t('search.searchBar.assistAttribute', { label: option.label }))
      }
    })
    return { suggestions, hint: null }
  }

  const tokenAttr = tokenContent.slice(0, eqIndex).trim().toLowerCase()
  const tokenHasSim = tokenAttr === 'sim'
  const tokenHasK = /\bk\s*=\s*\d+/i.test(tokenContent)

  const afterEq = tokenContent.slice(eqIndex + 1)
  const quoteIndex = afterEq.indexOf('"')
  if (quoteIndex === -1) {
    pushSuggestion(`${raw}"`, t('search.searchBar.assistOpenQuote'))
    return { suggestions, hint: null }
  }

  const afterQuote = afterEq.slice(quoteIndex + 1)
  const closingQuoteIndex = afterQuote.indexOf('"')
  if (closingQuoteIndex === -1) {
    if (afterQuote.length === 0) {
      return { suggestions: [], hint: t('search.searchBar.assistNowWord') }
    }
    pushSuggestion(`${raw}"]`, t('search.searchBar.assistCloseToken'))
    return { suggestions, hint: null }
  }

  if (!raw.trim().endsWith(']')) {
    pushSuggestion(`${raw}]`, t('search.searchBar.assistCloseToken'))
    return { suggestions, hint: null }
  }

  if (tokenHasSim && !tokenHasK) {
    const closeIdx = raw.lastIndexOf(']')
    if (closeIdx >= 0) {
      pushSuggestion(`${raw.slice(0, closeIdx)}&k=20]${raw.slice(closeIdx + 1)}`, t('search.searchBar.assistTopK'))
    }
  }

  const needsSpace = !raw.endsWith(' ')
  const spacer = needsSpace ? ' ' : ''
  attrOptions.forEach(option => {
    pushSuggestion(`${raw}${spacer}[${option.cqlAttribute}="`, t('search.searchBar.assistNextToken', { label: option.label }))
  })
  return { suggestions, hint: null }
}

function extractValueContext(term: string): { attr: string; valueStart: number; valuePrefix: string } | null {
  const lower = term.toLowerCase()
  if (!lower.startsWith('cql:')) return null
  const lastOpen = term.lastIndexOf('[')
  const lastClose = term.lastIndexOf(']')
  if (lastOpen < 0 || lastOpen < lastClose) return null

  const token = term.slice(lastOpen + 1)
  const eqIndex = token.indexOf('=')
  if (eqIndex < 0) return null
  let attr = token.slice(0, eqIndex).trim().toLowerCase()
  const normalizedAttr = normalizeCqlAttribute(attr)
  if (!normalizedAttr || normalizedAttr === 'sim') return null
  if (!corpusCapabilities.canUseTokenAttribute(normalizedAttr)) return null
  attr = normalizedAttr === 'ner' ? 'ent' : normalizedAttr

  const afterEq = token.slice(eqIndex + 1)
  const firstQuote = afterEq.indexOf('"')
  if (firstQuote < 0) return null

  const valueStart = lastOpen + 1 + eqIndex + 1 + firstQuote + 1
  const afterValue = term.slice(valueStart)
  if (afterValue.includes('"')) {
    return null
  }
  return { attr, valueStart, valuePrefix: afterValue }
}

function formatSuggestionDetail(item: SuggestionItem): string | null {
  const base = localTerm.value.trim()
  const suggestionText = item.text
  if (item.hint) {
    const match = item.hint.match(/^(POS|Lemma|Wort|NER):\s*(.+)$/i)
    if (match && match[1] && match[2]) {
      const value = match[2]
      if (match[1].toLowerCase() === 'pos') {
        const pretty = hasPosTagsetLabels.value ? posTagLabel(value) : null
        if (pretty) {
          const extras = [nextStepHint(suggestionText)].filter(Boolean).join(' · ')
          return extras ? `${pretty} · ${extras}` : pretty
        }
      }
      const stepHint = nextStepHint(suggestionText)
      const extras = [stepHint, item.hasPlaceholders ? t('search.searchBar.replacePlaceholders') : null]
        .filter(Boolean)
        .join(' · ')
      return extras
        ? `${t('search.searchBar.insertValue', { value })} · ${extras}`
        : t('search.searchBar.insertValue', { value })
    }
  }
  let suffix = suggestionText
  if (base && suggestionText.startsWith(base)) {
    suffix = suggestionText.slice(base.length).trim()
  }
  const shown = suffix || suggestionText
  const baseText = item.kind === 'fix'
    ? t('search.searchBar.corrected', { value: shown })
    : t('search.searchBar.insertValue', { value: shown })
  const stepHint = item.kind === 'fix' ? null : nextStepHint(suggestionText)
  const placeholderHint = item.hasPlaceholders ? t('search.searchBar.replacePlaceholders') : null
  const extras = [stepHint, placeholderHint].filter(Boolean).join(' · ')
  return extras ? `${baseText} · ${extras}` : baseText
}

function getSuggestionBadge(item: SuggestionItem): { label: string; className: string } | null {
  if (!item.hint) return null
  const match = item.hint.match(/^(POS|Lemma|Wort|NER):/i)
  if (!match || !match[1]) return null
  const tag = match[1].toLowerCase()
  if (tag === 'pos') return { label: hintPrefixLabel('pos'), className: 'badge-pos' }
  if (tag === 'lemma') return { label: hintPrefixLabel('lemma'), className: 'badge-lemma' }
  if (tag === 'wort') return { label: hintPrefixLabel('wort'), className: 'badge-word' }
  if (tag === 'ner') return { label: hintPrefixLabel('ner'), className: 'badge-ner' }
  return null
}

// Keep local input in sync when the term changes elsewhere (history/bookmarks/etc.)
watch(
  () => queryStore.term,
  (term) => {
    if (term !== localTerm.value) {
      localTerm.value = term
    }
  }
)

function syncBuilderSeed(raw: string) {
  builderTerm.value = normalizeBuilderSeedTerm(raw)
  builderMode.value = shouldOpenQueryBuilderInAdvancedMode(raw) ? 'advanced' : 'simple'
}

// Prefill the builder with the current input when it opens
watch(
  () => uiStore.queryBuilderOpen,
  (isOpen) => {
    if (isOpen) {
      syncBuilderSeed(localTerm.value)
    }
  }
)

async function handleSubmit() {
  const term = localTerm.value.trim()
  if (!term) {
    // Empty submit (e.g. cleared the box, then pressed Enter): drop any stale
    // results so the old KWIC table + "N Treffer" don't linger, and surface the
    // friendly hint instead of silently doing nothing. With results cleared the
    // app falls back to the empty "Starte eine Suche" placeholder.
    cancelSuggestRequest()
    resetSuggestions()
    if (queryStore.hasResults || queryStore.totalKnown || queryStore.error) {
      queryStore.clear()
    }
    localTerm.value = ''
    uiStore.showToast(t('search.searchBar.enterTerm'), 'info', 2500)
    focusForCorrection()
    return
  }
  if (term !== localTerm.value) localTerm.value = term
  if (isCqlfQuery(term) && !canUseCqlf.value) {
    cancelSuggestRequest()
    resetSuggestions()
    const message = t('search.searchBar.cqlNotEnabledPlain')
    queryStore.rejectAttempt(term, message)
    uiStore.showToast(message, 'warning')
    focusForCorrection()
    return
  }

  // A plain space-separated phrase ("der Klimawandel") cannot run on the
  // single-token plain-search path (the backend rejects it with a raw
  // "Unexpected token"). Translate it to the token-sequence CQL the engine
  // supports when CQLF is available; otherwise hand the user the exact repair
  // instead of letting the raw parser error through (SEARCH-KWIC-01).
  let submitTerm = term
  if (isPlainPhraseQuery(term)) {
    const phraseCql = plainPhraseToCql(term, wordCqlAttribute.value)
    if (phraseCql && canUseCqlf.value) {
      submitTerm = phraseCql
    } else if (phraseCql) {
      cancelSuggestRequest()
      resetSuggestions()
      const hint = t('search.searchBar.phraseNeedsTokens', { query: phraseCql.slice(4) })
      queryStore.rejectAttempt(term, hint)
      uiStore.showToast(hint, 'warning')
      focusForCorrection()
      return
    }
  }

  cancelSuggestRequest()
  resetSuggestions()
  isFocused.value = false
  inputRef.value?.blur()

  const tabAtSubmit = uiStore.activeTab
  const result = await dispatch({
    type: 'query/execute',
    payload: { term: submitTerm, contextSize: queryStore.contextSize }
  })
  if (result.success) {
    // A direct search is an instruction to inspect concordance evidence. Keep
    // an unrelated analysis from remaining frontmost while the new KWIC result
    // appears only as a small counter in the global header. A tab chosen
    // while the search ran stays: the finished search does not pull the
    // reader back to KWIC.
    if (uiStore.activeTab === tabAtSubmit) uiStore.setActiveTab('kwic')
    return
  }
  if (!result.success) {
    const message =
      result.policyReason ||
      result.error ||
      t('search.searchBar.searchFailed')
    // A policy middleware can reject before the query handler gets a chance to
    // invalidate prior evidence. Do it here as well, so a rejected input never
    // leaves an earlier query visible under a new search term.
    if (result.blocked) {
      queryStore.rejectAttempt(submitTerm, message)
    } else {
      queryStore.setError(message)
    }
    // showToast coalesces identical messages. That gives middleware-only
    // rejections their one visible explanation without stacking a second toast
    // when the action handler already reported the same reason.
    uiStore.showToast(message, result.blocked ? 'warning' : 'error')
    focusForCorrection()
  }
}

function handleClear() {
  localTerm.value = ''
  queryStore.clear()
  inputRef.value?.focus()
}

function handleCancel() {
  queryStore.cancelStreaming()
}

function openQueryBuilder() {
  if (!canUseCqlf.value) {
    uiStore.showToast(t('search.searchBar.builderNotEnabled'), 'warning')
    return
  }
  syncBuilderSeed(localTerm.value)
  if (!onboardingStore.hasCompletedOnboarding) {
    onboardingStore.skip()
  }
  uiStore.openQueryBuilder()
}

function closeQueryBuilder() {
  uiStore.closeQueryBuilder()
}

function clearSuggestTimer() {
  if (suggestTimer) {
    clearTimeout(suggestTimer)
    suggestTimer = null
  }
}

function cancelSuggestRequest() {
  if (suggestAbort) {
    suggestAbort.abort()
    suggestAbort = null
  }
}

function resetSuggestions() {
  suggestions.value = []
  activeSuggestionIndex.value = -1
  isSuggesting.value = false
  assistHint.value = null
}

function focusForCorrection() {
  // Let researchers immediately repair a rejected query without reopening the
  // large assistant surface over its error and the cleared KWIC evidence.
  inputRef.value?.focus()
  clearSuggestTimer()
  cancelSuggestRequest()
  resetSuggestions()
  isFocused.value = false
}

function scheduleSuggest(term: string) {
  clearSuggestTimer()
  cancelSuggestRequest()

  const trimmed = term.trim()
  if (!canUseCqlf.value) {
    resetSuggestions()
    return
  }
  if (!isFocused.value || trimmed.length < 2) {
    resetSuggestions()
    return
  }
  if (!trimmed.toLowerCase().startsWith('cql:')) {
    resetSuggestions()
    return
  }

  suggestRequestId += 1
  const requestId = suggestRequestId
  suggestAbort = new AbortController()

  suggestTimer = setTimeout(async () => {
    isSuggesting.value = true
    const assist = buildCqlAssist(trimmed)
    assistHint.value = assist.hint
    suggestions.value = assist.suggestions
    activeSuggestionIndex.value = -1
    const valueContext = extractValueContext(trimmed)
    let valueSuggestions: SuggestionItem[] = []
    if (valueContext && canSuggestLexicon.value) {
      try {
        const values = await loadLexiconSuggestions(
          valueContext.attr,
          valueContext.valuePrefix.trim(),
          valueContext.attr === 'pos' ? 200 : 30,
          suggestAbort?.signal,
          suggestionCorpus.value
        )
        const labelPrefix = cqlAttributeSuggestionLabel(valueContext.attr)
        const rawPrefix = valueContext.valuePrefix.trim()
        const prefixLower = rawPrefix.toLowerCase()
        const seenLower = new Set<string>()
        const filteredValues = values
          .filter((val) => {
            const lower = val.toLowerCase()
            if (seenLower.has(lower)) return false
            seenLower.add(lower)
            return true
          })
        let candidateValues = filteredValues
        let fallbackExact = false
        if (prefixLower) {
          const longer = filteredValues.filter(
            (val) => val.length > prefixLower.length && val.toLowerCase() !== prefixLower
          )
          if (longer.length) {
            candidateValues = longer
          } else {
            const exact = filteredValues.filter((val) => val.toLowerCase() === prefixLower)
            if (exact.length) {
              candidateValues = exact.slice(0, 1)
              fallbackExact = true
              assistHint.value = t('search.searchBar.exactFallback')
            } else {
              candidateValues = filteredValues
            }
          }
        }
        let sortedValues = candidateValues
        if (valueContext.attr === 'pos') await corpusPosTagset.ensureLoaded()
        if (valueContext.attr === 'pos' && hasPosTagsetLabels.value) {
          sortedValues = [...candidateValues].sort((a, b) => {
            const groupA = posGroupOrder.indexOf(getPosGroup(a))
            const groupB = posGroupOrder.indexOf(getPosGroup(b))
            if (groupA !== groupB) return groupA - groupB
            return a.length - b.length
          })
        }
        valueSuggestions = sortedValues.map((val) => ({
          text: `${trimmed.slice(0, valueContext.valueStart)}${val}`,
          hint: fallbackExact ? `${labelPrefix}: ${val} ${t('search.searchBar.exactSuffix')}` : `${labelPrefix}: ${val}`,
          kind: 'complete',
        }))
      } catch {
        valueSuggestions = []
      }
    } else if (valueContext && !assistHint.value) {
      assistHint.value = lexiconSuggestBlockReason.value ?? t('search.searchBar.lexiconNotEnabled')
    }

    if (!canAnalyseQuery.value) {
      if (requestId !== suggestRequestId) return
      const maxSuggestions = valueContext?.attr === 'pos' ? 60 : 12
      suggestions.value = mergeAutocompleteSuggestions({
        rawQuery: trimmed,
        assistSuggestions: assist.suggestions,
        valueSuggestions: valueSuggestions.slice(0, valueContext?.attr === 'pos' ? 40 : 6),
        maxSuggestions,
      })
      activeSuggestionIndex.value = -1
      if (!assistHint.value) {
        assistHint.value = analyseBlockReason.value ?? t('search.searchBar.diagnosticsNotEnabled')
      }
      isSuggesting.value = false
      return
    }

    try {
      const results = await loadSuggestions(trimmed, suggestAbort?.signal, suggestionCorpus.value)
      if (requestId !== suggestRequestId) return
      const maxSuggestions = valueContext?.attr === 'pos' ? 60 : 20
      suggestions.value = mergeAutocompleteSuggestions({
        rawQuery: trimmed,
        assistSuggestions: assist.suggestions,
        valueSuggestions: valueSuggestions.slice(0, valueContext?.attr === 'pos' ? 40 : 10),
        backendSuggestions: results.filter((item) => isCqlSuggestionSupported(corpusCapabilities.activeSummary, item)),
        maxSuggestions,
      })
      activeSuggestionIndex.value = -1
    } catch {
      if (requestId !== suggestRequestId) return
      const maxSuggestions = valueContext?.attr === 'pos' ? 60 : 12
      suggestions.value = mergeAutocompleteSuggestions({
        rawQuery: trimmed,
        assistSuggestions: assist.suggestions,
        valueSuggestions: valueSuggestions.slice(0, valueContext?.attr === 'pos' ? 40 : 6),
        maxSuggestions,
      })
      activeSuggestionIndex.value = -1
    } finally {
      if (requestId === suggestRequestId) {
        isSuggesting.value = false
      }
    }
  }, 250)
}

function formatHistoryTime(timestamp: number): string {
  const now = Date.now()
  const diff = now - timestamp
  const minutes = Math.floor(diff / 60000)
  const hours = Math.floor(diff / 3600000)
  const days = Math.floor(diff / 86400000)

  if (minutes < 1) return t('search.searchBar.justNow')
  if (minutes < 60) return t('search.searchBar.minutesAgo', { n: minutes })
  if (hours < 24) return t('search.searchBar.hoursAgo', { n: hours })
  return t('search.searchBar.daysAgo', { n: days }, days)
}

function acceptSuggestion(suggestion: SuggestionItem) {
  localTerm.value = suggestion.text
  resetSuggestions()
  inputRef.value?.focus()
}

async function handleBuilderSubmit() {
  const term = builderTerm.value.trim()
  if (!term) return
  localTerm.value = term
  await handleSubmit()
  uiStore.closeQueryBuilder()
}

async function handleHistorySelect(query: string) {
  localTerm.value = query
  inputRef.value?.focus()
  resetSuggestions()
  await handleSubmit()
}

function handleFocus() {
  if (blurTimer) {
    clearTimeout(blurTimer)
    blurTimer = null
  }
  isFocused.value = true
  scheduleSuggest(localTerm.value)
}

function handleBlur() {
  blurTimer = setTimeout(() => {
    isFocused.value = false
    cancelSuggestRequest()
    resetSuggestions()
  }, 120)
}

function handleKeydown(event: KeyboardEvent) {
  if (event.key === 'ArrowDown' && hasSuggestions.value) {
    event.preventDefault()
    if (activeSuggestionIndex.value < 0) {
      activeSuggestionIndex.value = 0
    } else {
      activeSuggestionIndex.value = Math.min(
        displaySuggestions.value.length - 1,
        activeSuggestionIndex.value + 1
      )
    }
    return
  }

  if (event.key === 'ArrowUp' && hasSuggestions.value) {
    event.preventDefault()
    if (activeSuggestionIndex.value < 0) {
      activeSuggestionIndex.value = displaySuggestions.value.length - 1
    } else {
      activeSuggestionIndex.value = Math.max(0, activeSuggestionIndex.value - 1)
    }
    return
  }

  if (event.key === 'Enter') {
    if (hasSuggestions.value && activeSuggestionIndex.value >= 0) {
      event.preventDefault()
      const suggestion = displaySuggestions.value[activeSuggestionIndex.value]
      if (suggestion) {
        acceptSuggestion(suggestion)
        return
      }
    }
    handleSubmit()
  } else if (event.key === 'Escape') {
    resetSuggestions()
    inputRef.value?.blur()
  }
}

watch(localTerm, (term) => {
  scheduleSuggest(term)
})

onMounted(() => {
  searchHistoryStore.init()
  void productCapabilities.load()
  if (!corpusCapabilities.loaded) void corpusCapabilities.fetchCorpora()
})

watch(canUseCqlf, (enabled) => {
  if (!enabled) {
    cancelSuggestRequest()
    resetSuggestions()
    if (uiStore.queryBuilderOpen) {
      uiStore.closeQueryBuilder()
    }
  } else if (isFocused.value) {
    scheduleSuggest(localTerm.value)
  }
})

// Cleanup timers on unmount to prevent memory leaks
onUnmounted(() => {
  if (suggestTimer) {
    clearTimeout(suggestTimer)
    suggestTimer = null
  }
  if (blurTimer) {
    clearTimeout(blurTimer)
    blurTimer = null
  }
  cancelSuggestRequest()
})
</script>

<template>
  <div class="search-bar-wrapper">
    <div
      class="search-bar"
      :class="{ 'is-focused': isFocused }"
      role="search"
      :aria-label="t('search.searchBar.searchRole')"
    >
      <Search class="search-icon" aria-hidden="true" />

      <input
        ref="inputRef"
        v-model="localTerm"
        type="search"
        inputmode="search"
        enterkeyhint="search"
        autocapitalize="none"
        spellcheck="false"
        autocomplete="off"
        class="search-input"
        :placeholder="searchPlaceholder"
        :aria-label="searchAriaLabel"
        aria-haspopup="dialog"
        :aria-expanded="showAssistPanel"
        :aria-controls="showAssistPanel ? 'kwic-assist' : undefined"
        :aria-activedescendant="activeSuggestionIndex >= 0 ? `kwic-suggestion-${activeSuggestionIndex}` : undefined"
        data-search-input
        :disabled="isSearching"
        @keydown="handleKeydown"
        @focus="handleFocus"
        @blur="handleBlur"
      />

      <button
        type="button"
        class="case-btn"
        :class="{ active: caseSensitive }"
        :title="caseButtonTitle"
        :aria-label="caseButtonTitle"
        :aria-pressed="caseSensitive"
        :disabled="isSearching"
        @click="toggleCaseSensitive"
      >
        Aa
      </button>

      <button
        v-if="canUseCqlf"
        type="button"
        class="builder-btn"
        :title="t('search.searchBar.builder')"
        :aria-label="t('search.searchBar.openBuilder')"
        :disabled="isSearching"
        @click="openQueryBuilder"
      >
        <Wand2 class="w-4 h-4" />
      </button>

      <!-- Loading/Streaming indicator -->
      <div
        v-if="isSearching"
        class="streaming-indicator"
        :title="isStreaming ? t('search.searchBar.streamingTitle', { count: streamingCount }, streamingCount) : t('search.searchBar.searching')"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <Loader2 class="w-5 h-5 text-primary-500 animate-spin" aria-hidden="true" />
        <span v-if="isStreaming" class="streaming-label">{{ t('search.searchBar.streaming') }}</span>
        <span v-if="isStreaming && streamingCount > 0" class="streaming-count">
          {{ formatNumber(streamingCount) }}
        </span>
        <span v-if="isStreaming && streamingElapsed" class="streaming-elapsed">
          · {{ streamingElapsed }}
        </span>
        <button
          v-if="isStreaming"
          type="button"
          class="cancel-btn"
          :title="t('search.searchBar.cancel')"
          :aria-label="t('search.searchBar.cancel')"
          @click="handleCancel"
        >
          <X class="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>

      <!-- Clear button -->
      <button
        v-else-if="localTerm"
        class="clear-btn"
        :title="t('search.searchBar.clear')"
        :aria-label="t('search.searchBar.clear')"
        @click="handleClear"
      >
        <X class="w-4 h-4" aria-hidden="true" />
      </button>

      <!-- Search button -->
      <button
        class="submit-btn"
        :disabled="!localTerm.trim() || isSearching"
        :aria-label="t('search.searchBar.start')"
        :title="t('search.searchBar.start')"
        @click="handleSubmit"
      >
        {{ t('search.searchBar.submit') }}
      </button>
    </div>

    <div
      v-if="isCqlInput && !canUseCqlf"
      class="cql-disabled-notice"
      role="status"
      aria-live="polite"
    >
      {{ t('search.searchBar.cqlDisabledNotice') }}
    </div>

    <div
      v-else-if="isCqlInput && cqlAssistFeatureNotice"
      class="cql-feature-notice"
      role="status"
      aria-live="polite"
    >
      {{ cqlAssistFeatureNotice }}
    </div>

    <div
      v-if="cqlCaseModeNotice"
      class="cql-feature-notice"
      role="status"
      aria-live="polite"
    >
      {{ cqlCaseModeNotice }}
    </div>

    <!-- Inline CQL diagnostics (DT-FE-UX-CORE) -->
    <div
      v-if="queryDiagnostics.length"
      class="cql-diagnostics"
      role="status"
      aria-live="polite"
    >
      <div
        v-for="(diag, idx) in queryDiagnostics"
        :key="`diag-${idx}`"
        class="cql-diagnostic"
        :class="`cql-diagnostic--${diag.severity}`"
      >
        <span class="cql-diagnostic-text">{{ diag.message }}</span>
        <button
          v-if="diag.severity === 'info' && looksLikeBareCql"
          type="button"
          class="cql-diagnostic-action"
          @mousedown.prevent="applyCqlPrefix"
        >
          {{ t('search.searchBar.addPrefix') }}
        </button>
      </div>
    </div>

    <Transition name="assist">
      <div
        v-if="showAssistPanel"
        id="kwic-assist"
        class="assist-dropdown"
        role="dialog"
        :aria-label="t('search.searchBar.assistant')"
      >
        <div
          v-if="isSuggesting || suggestions.length > 0 || assistHint"
          class="assist-section"
          role="listbox"
          :aria-label="t('search.searchBar.suggestionsAria')"
          :aria-busy="isSuggesting"
        >
          <div class="assist-header">{{ t('search.searchBar.suggestions') }}</div>
          <div v-if="assistHint" class="assist-hint" role="status" aria-live="polite">
            {{ assistHint }}
          </div>
          <div v-if="isSuggesting" class="suggestion-loading" role="status" aria-live="polite">
            <Loader2 class="w-4 h-4 animate-spin" aria-hidden="true" />
            <span>{{ t('search.searchBar.loadingSuggestions') }}</span>
          </div>

          <div class="suggestions-scroll">
            <div v-if="completionBlocks.length" class="suggestion-group">
              <template v-for="block in completionBlocks" :key="block.title">
                <div class="suggestion-group-title">{{ block.title }}</div>
                <button
                  v-for="suggestion in block.items"
                  :key="`complete-${suggestion.text}-${suggestionIndexMap.get(suggestion)}`"
                  :id="`kwic-suggestion-${suggestionIndexMap.get(suggestion)}`"
                  type="button"
                  class="suggestion-item"
                  :class="{ active: suggestionIndexMap.get(suggestion) === activeSuggestionIndex }"
                  role="option"
                  :aria-selected="suggestionIndexMap.get(suggestion) === activeSuggestionIndex"
                  :aria-label="t('search.searchBar.acceptSuggestion', { text: suggestion.text })"
                  @mousedown.prevent="acceptSuggestion(suggestion)"
                >
                  <Search class="w-4 h-4 suggestion-icon" aria-hidden="true" />
                  <span
                    v-if="getSuggestionBadge(suggestion)"
                    :class="['suggestion-badge', getSuggestionBadge(suggestion)?.className]"
                  >
                    {{ getSuggestionBadge(suggestion)?.label }}
                  </span>
                  <span class="suggestion-content">
                    <span class="suggestion-text">{{ formatSuggestionLabel(suggestion) }}</span>
                    <span class="suggestion-hint">{{ formatSuggestionDetail(suggestion) }}</span>
                  </span>
                </button>
              </template>
            </div>

            <div v-if="fixSuggestions.length" class="suggestion-group">
              <div class="suggestion-group-title">{{ t('search.searchBar.repairs') }}</div>
              <button
                v-for="suggestion in fixSuggestions"
                :key="`fix-${suggestion.text}-${suggestionIndexMap.get(suggestion)}`"
                :id="`kwic-suggestion-${suggestionIndexMap.get(suggestion)}`"
                type="button"
                class="suggestion-item"
                :class="{ active: suggestionIndexMap.get(suggestion) === activeSuggestionIndex }"
                role="option"
                :aria-selected="suggestionIndexMap.get(suggestion) === activeSuggestionIndex"
                :aria-label="t('search.searchBar.acceptRepair', { text: suggestion.text })"
                @mousedown.prevent="acceptSuggestion(suggestion)"
              >
                <Search class="w-4 h-4 suggestion-icon" aria-hidden="true" />
                <span class="suggestion-content">
                  <span class="suggestion-text">{{ formatSuggestionLabel(suggestion) }}</span>
                  <span class="suggestion-hint">{{ formatSuggestionDetail(suggestion) }}</span>
                </span>
              </button>
            </div>
          </div>
        </div>

        <div v-if="hasHistory" class="assist-section history-section">
          <div class="assist-header history-header">
            <span>{{ t('search.searchBar.recent') }}</span>
            <button
              type="button"
              class="clear-history-btn"
              :title="t('search.searchBar.clearHistory')"
              :aria-label="t('search.searchBar.clearHistory')"
              @mousedown.prevent
              @click="searchHistoryStore.clear()"
            >
              {{ t('search.searchBar.clearAll') }}
            </button>
          </div>

          <div class="history-list" role="list">
            <button
              v-for="item in recentSearches"
              :key="item.id"
              type="button"
              class="history-item"
              role="listitem"
              :aria-label="t('search.searchBar.repeatSearch', { query: item.query })"
              @mousedown.prevent="handleHistorySelect(item.query)"
            >
              <div class="history-query">{{ item.query }}</div>
              <div class="history-meta">
                {{ t('search.searchBar.historyHits', { count: formatNumber(item.resultCount) }, item.resultCount) }}
                <span class="separator">·</span>
                {{ formatHistoryTime(item.timestamp) }}
              </div>
            </button>
          </div>
        </div>

        <div class="assist-legend">
          <span class="legend-title">{{ t('search.searchBar.keyboard') }}</span>
          <div class="legend-items">
            <span v-for="item in legendItems" :key="item.key" class="legend-chip">
              <kbd class="legend-key">{{ item.key }}</kbd>
              <span class="legend-label">{{ item.label }}</span>
            </span>
          </div>
        </div>
      </div>
    </Transition>
  </div>

  <!-- Query‑Builder Dialog -->
  <Modal
    v-if="canUseCqlf"
    :model-value="uiStore.queryBuilderOpen"
    :title="t('search.searchBar.builder')"
    :description="t('search.searchBar.builderDescription')"
    size="xl"
    @update:model-value="uiStore.queryBuilderOpen = $event"
    @close="closeQueryBuilder"
  >
    <QueryBuilder
      v-model="builderTerm"
      :initial-mode="builderMode"
      @submit="handleBuilderSubmit"
    />

    <template #footer>
      <Button variant="ghost" @click="closeQueryBuilder">
        {{ t('search.searchBar.cancelBuilder') }}
      </Button>
      <Button
        variant="primary"
        :disabled="!builderTerm.trim()"
        @click="handleBuilderSubmit"
      >
        {{ t('search.searchBar.applySearch') }}
      </Button>
    </template>
  </Modal>
</template>

<style scoped>
@reference "../../style.css";

.search-bar-wrapper {
  @apply relative w-full;
}

.search-bar {
  @apply flex items-center gap-3 px-4 py-3;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply rounded-lg;
  @apply border-2 border-transparent;
  @apply transition-all duration-200;
  width: 100%;
  max-width: none;
}

.search-bar.is-focused {
  @apply border-primary-500;
  @apply bg-white dark:bg-neutral-900;
}

.search-icon {
  @apply w-5 h-5 text-neutral-400 flex-shrink-0;
}

.search-input {
  @apply flex-1 bg-transparent;
  @apply text-base text-neutral-900 dark:text-neutral-100;
  @apply placeholder-neutral-500;
  @apply outline-none;
  /* Without this the input keeps its intrinsic width of about 20 characters
     and pushes the search button out of the bar in a narrow main area. */
  min-width: 0;
}

/* The clear button next to the input already clears it. The browser's own
   cancel control of type=search showed a second, differently styled X. */
.search-input::-webkit-search-cancel-button {
  -webkit-appearance: none;
  appearance: none;
}

.builder-btn {
  @apply p-1.5 rounded;
  @apply text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.case-btn {
  @apply px-2 py-1 rounded text-sm font-semibold leading-none;
  @apply text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
}

.case-btn.active {
  @apply bg-primary-100 dark:bg-primary-900/30;
  @apply text-primary-700 dark:text-primary-300;
}

.clear-btn {
  @apply p-1 rounded;
  @apply text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.submit-btn {
  @apply px-3 py-1 text-sm font-medium rounded-md flex-shrink-0;
  @apply bg-primary-500 text-white;
  @apply hover:bg-primary-600;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

/* Below ~420px the input and trailing buttons need tighter spacing so the
   primary search button stays fully visible. */
@media (max-width: 420px) {
  .search-bar {
    @apply gap-1.5 px-2.5;
  }
}

.cql-diagnostics {
  @apply mt-1.5 flex flex-col gap-1;
}

.cql-disabled-notice {
  @apply mt-1.5 rounded-md border border-warning-200 bg-warning-50 px-3 py-2 text-xs leading-relaxed text-warning-800;
  @apply dark:border-warning-900/50 dark:bg-warning-900/20 dark:text-warning-200;
}

.cql-feature-notice {
  @apply mt-1.5 rounded-md border border-neutral-200 bg-neutral-50 px-3 py-2 text-xs leading-relaxed text-neutral-700;
  @apply dark:border-neutral-800 dark:bg-neutral-900/60 dark:text-neutral-300;
}

.cql-diagnostic {
  @apply flex items-center justify-between gap-2 px-3 py-1.5 rounded-md text-xs;
}

.cql-diagnostic--error {
  @apply bg-error-50 text-error-700 dark:bg-error-900/30 dark:text-error-300;
}

.cql-diagnostic--warning {
  @apply bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300;
}

.cql-diagnostic--info {
  @apply bg-primary-50 text-primary-700 dark:bg-primary-900/20 dark:text-primary-300;
}

.cql-diagnostic-action {
  @apply px-2 py-0.5 rounded text-xs font-medium;
  @apply bg-primary-500 text-white hover:bg-primary-600;
  @apply transition-colors flex-shrink-0;
}

.assist-dropdown {
  @apply absolute left-0 right-0 mt-2;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply rounded-xl shadow-xl;
  @apply overflow-hidden;
  z-index: var(--z-modal);
}

.assist-section {
  @apply py-2;
}

.assist-header {
  @apply px-4 py-1.5 text-[11px] uppercase tracking-wide;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.history-header {
  @apply flex items-center justify-between;
}

.clear-history-btn {
  @apply text-[11px] font-medium;
  @apply text-neutral-400 hover:text-error-500;
  @apply transition-colors;
}

.suggestion-loading {
  @apply flex items-center gap-2 px-4 py-2 text-sm;
  @apply text-neutral-600 dark:text-neutral-300;
}

.suggestions-scroll {
  max-height: 320px;
  overflow-y: auto;
}

.assist-hint {
  @apply px-4 py-2 text-sm;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.suggestion-item {
  @apply w-full flex items-start gap-2 px-4 py-2 text-left text-sm;
  @apply text-neutral-800 dark:text-neutral-200;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-800;
  @apply transition-colors;
}

.suggestion-item.active {
  @apply bg-primary-50 dark:bg-primary-900/20;
  @apply text-primary-700 dark:text-primary-300;
}

.suggestion-icon {
  @apply text-neutral-400;
}

.suggestion-item.active .suggestion-icon {
  @apply text-primary-500;
}

.suggestion-group {
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.suggestion-group:last-of-type {
  @apply border-b-0;
}

.suggestion-group-title {
  @apply px-4 pt-2 text-[11px] uppercase tracking-wide;
  @apply text-neutral-400 dark:text-neutral-500;
}

.suggestion-text {
  @apply font-medium text-neutral-800 dark:text-neutral-100;
}

.suggestion-content {
  @apply flex flex-col gap-0.5 min-w-0;
}

.suggestion-badge {
  @apply inline-flex items-center justify-center px-1.5 py-0.5 rounded;
  @apply text-[10px] font-semibold uppercase tracking-wide;
  @apply border;
  @apply shrink-0;
  margin-top: 2px;
}

.badge-pos {
  @apply text-indigo-700 dark:text-indigo-200;
  @apply bg-indigo-100 dark:bg-indigo-900/30;
  @apply border-indigo-200 dark:border-indigo-800;
}

.badge-lemma {
  @apply text-emerald-700 dark:text-emerald-200;
  @apply bg-emerald-100 dark:bg-emerald-900/30;
  @apply border-emerald-200 dark:border-emerald-800;
}

.badge-word {
  @apply text-amber-700 dark:text-amber-200;
  @apply bg-amber-100 dark:bg-amber-900/30;
  @apply border-amber-200 dark:border-amber-800;
}

.badge-ner {
  @apply text-sky-700 dark:text-sky-200;
  @apply bg-sky-100 dark:bg-sky-900/30;
  @apply border-sky-200 dark:border-sky-800;
}

.suggestion-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
  @apply font-mono;
  @apply block;
}

.history-list {
  @apply max-h-60 overflow-y-auto;
}

.history-item {
  @apply w-full text-left px-4 py-2;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-800;
  @apply transition-colors;
}

.history-query {
  @apply text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate;
}

.history-meta {
  @apply text-xs text-neutral-500 dark:text-neutral-400 mt-0.5;
}

.separator {
  @apply mx-1;
}

.assist-legend {
  @apply px-4 py-2 border-t border-neutral-100 dark:border-neutral-800;
  @apply bg-neutral-50/60 dark:bg-neutral-900/60;
}

.legend-title {
  @apply block text-[11px] uppercase tracking-wide text-neutral-400 dark:text-neutral-500;
  @apply mb-1;
}

.legend-items {
  @apply flex flex-wrap gap-2;
}

.legend-chip {
  @apply inline-flex items-center gap-1.5;
  @apply text-xs text-neutral-600 dark:text-neutral-300;
}

.legend-key {
  @apply px-1.5 py-0.5 rounded border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-800;
  @apply font-mono text-[10px];
}

.legend-label {
  @apply text-xs;
}

.assist-enter-active {
  @apply transition-all duration-150 ease-out;
}

.assist-leave-active {
  @apply transition-all duration-100 ease-in;
}

.assist-enter-from,
.assist-leave-to {
  @apply opacity-0 -translate-y-2;
}

.streaming-indicator {
  @apply flex items-center gap-1.5;
}

.streaming-label {
  @apply text-[11px] font-medium text-primary-700 dark:text-primary-300;
}

.streaming-count {
  @apply text-xs font-medium text-primary-600 dark:text-primary-400;
  @apply tabular-nums;
  min-width: 3ch;
}

.streaming-elapsed {
  @apply text-[11px] font-mono text-primary-600 dark:text-primary-300;
  @apply tabular-nums;
}

.cancel-btn {
  @apply p-1 rounded;
  @apply text-neutral-400 hover:text-error-500;
  @apply hover:bg-error-50 dark:hover:bg-error-900/30;
  @apply transition-colors;
}

:deep(.modal-panel:has(.query-builder .template-studio) .modal-footer) {
  display: none;
}
</style>
