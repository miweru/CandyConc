<script setup lang="ts">
/**
 * WordSketchTab - Grammatical relations for a word
 */
import { ref, watch, computed } from 'vue'
import { PenTool, Search, RefreshCw, AlertTriangle, Download } from 'lucide-vue-next'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import { useAnalysisPresetsStore, useCorpusCapabilitiesStore, useDocsetStore, useProductCapabilitiesStore } from '@/stores'
import Button from '@/components/ui/Button.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import CodeSpanText from '@/components/ui/CodeSpanText.vue'
import {
  coerceMethodBlock,
  methodStatEntries,
  type MethodBlock,
  type WordSketchDiffResult,
} from '@/api/client'
import { buildCsv, csvMeta, downloadCsv } from '@/utils/csv'
import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import { resolveWordSketchTerm } from '@/utils/queryTerm'
import { wordSketchRowQuery } from '@/utils/backPathQuery'
import { actionBus } from '@/actions/bus'
import { isCqlfQuery } from '@/lib/cqlDetection'
import {
  corpusFeatureDecisionReason,
} from '@/lib/productCorpusFeatures'
import { useWordSketchOperations } from '@/composables/useWordSketchOperations'
import {
  productOperationFocusMatches,
  useProductOperationFocus,
} from '@/composables/useProductOperationFocus'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

interface CollocateItem {
  word: string
  score: number
  frequency: number
}

interface RelationGroup {
  relation: string
  label: string
  items: CollocateItem[]
  rowLimit: number | null
  totalCandidates: number | null
  totalRows: number | null
  truncated: boolean | null
  minFreq: number | null
}

const { t } = useI18n()
const queryStore = useQueryStore()
const uiStore = useUiStore()
const docsetStore = useDocsetStore()
const presetsStore = useAnalysisPresetsStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const {
  canLoadWordSketch,
  canLoadWordSketchDiff,
  wordSketchBlockReason,
  wordSketchDiffBlockReason,
  loadWordSketch,
  loadWordSketchDiff,
} = useWordSketchOperations()
const { consumeFocusFor, focusMatches, focusIs, modeIs } = useProductOperationFocus()

const searchTerm = ref('')
const isLoading = ref(false)
const data = ref<RelationGroup[]>([])
// Backend-provided gloss map (relation code -> German label) from the r9
// `relations` block. Preferred over the hardcoded fallback below so codes like
// nk/sb_rev/mnr render as human-readable grammatical relation names.
const backendRelationLabels = ref<Record<string, string>>({})
const wordSketchMethod = ref<MethodBlock | null>(null)
// The node form and the scope of the shown sketch, for the back path of a row.
const resultNode = ref<string | null>(null)
const resultScope = ref<{ corpus: string; docsetId: string | null } | null>(null)
const diffScope = ref<{ corpus: string; docsetId: string | null } | null>(null)
const wordSketchDiffMethod = ref<MethodBlock | null>(null)
const error = ref<string | null>(null)
const useDocsetScope = ref(true)
const activeController = ref<AbortController | null>(null)
const canUseCqlf = computed(() =>
  productCapabilities.hasContract && productCapabilities.isVisible('query.cqlf')
)
const wordSketchCorpusDecision = computed(() =>
  productCapabilities.corpusFeatureDecision(
    'analysis.wordsketch',
    corpusCapabilities.activeSummary,
  )
)
const wordSketchKnownUnavailable = computed(() =>
  wordSketchCorpusDecision.value.status === 'blocked' ||
  (
    wordSketchCorpusDecision.value.status !== 'unknown' &&
    (diffMode.value ? !canLoadWordSketchDiff.value : !canLoadWordSketch.value)
  )
)
const wordSketchFeatureMessage = computed(() => {
  const operationReason = diffMode.value
    ? wordSketchDiffBlockReason.value
    : wordSketchBlockReason.value
  if (operationReason) return operationReason
  if (wordSketchCorpusDecision.value.status !== 'blocked') return ''
  return corpusFeatureDecisionReason(t('analysis.operations.wordSketch'), wordSketchCorpusDecision.value) ??
    t('analysis.wordSketch.needsRelNotProvided')
})

// ── Sketch difference (FT-SKETCH-DIFF-DISTRIBUTION): two-term contrast ──
const diffMode = ref(false)
const diffLimit = 30
const profileFocused = computed(() =>
  modeIs('profile') ||
  focusIs('analysis.wordsketch.profile') ||
  focusMatches('analysis.wordsketch.profile')
)
const diffFocused = computed(() =>
  modeIs('diff') ||
  focusIs('analysis.wordsketch.diff') ||
  focusMatches('analysis.wordsketch.diff')
)
const compareTerm = ref('')
const diffData = ref<WordSketchDiffResult | null>(null)
const isLoadingDiff = ref(false)
const diffError = ref<string | null>(null)
const diffController = ref<AbortController | null>(null)
const activeWordSketchMethod = computed(() =>
  diffMode.value ? wordSketchDiffMethod.value : wordSketchMethod.value
)
const exportDocCount = computed(() =>
  docsetStore.hasActiveDocset ? docsetStore.stats.docCount : corpusCapabilities.activeCorpusDocCount
)
const exportTokenCount = computed(() =>
  docsetStore.hasActiveDocset ? docsetStore.stats.tokenCount : corpusCapabilities.activeCorpusTokenCount
)

// Active-locale decimals, consistent with kappa, Frequency and Keyness,
// instead of the dot-decimal toFixed that mixed locales on the same screen.
const _de1 = (value: number): string =>
  formatNumber(value, { minimumFractionDigits: 1, maximumFractionDigits: 1 })
const _de3 = (value: number): string =>
  formatNumber(value, { minimumFractionDigits: 3, maximumFractionDigits: 3 })

function formatScore(value: number | null): string {
  return typeof value === 'number' ? _de3(value) : '–'
}

function formatFrequency(value: number | null | undefined): string {
  return typeof value === 'number' ? formatNumber(value) : '–'
}

function formatDelta(value: number | null): string {
  if (typeof value !== 'number') return '–'
  const sign = value > 0 ? '+' : ''
  return `${sign}${_de1(value)}`
}

function methodBlockToCsvLines(method: MethodBlock | null): string[] {
  if (!method) return []
  const lines: string[] = [`# ${t('analysis.wordSketch.csvMethodHeader')}`]
  for (const stat of methodStatEntries(method)) {
    const name = typeof stat?.name === 'string' && stat.name ? stat.name : stat.key
    const formula = typeof stat?.latex_formula === 'string' ? ` = ${stat.latex_formula}` : ''
    lines.push(`# ${name}${formula}`)
  }
  const fp = method.indexFingerprint ?? method.index_fingerprint
  if (fp) lines.push(csvMeta('indexFingerprint', fp))
  if (typeof method.default_sort === 'string') lines.push(csvMeta('default_sort', method.default_sort))
  if (typeof method.min_freq === 'number') lines.push(csvMeta('min_freq', method.min_freq))
  return lines
}

function relationMetaCsvLines(groups: RelationGroup[]): string[] {
  return groups.flatMap((group) => [
    csvMeta(`Relation.${group.relation}.label`, group.label),
    csvMeta(`Relation.${group.relation}.row_limit`, group.rowLimit ?? ''),
    csvMeta(`Relation.${group.relation}.total_candidates`, group.totalCandidates ?? ''),
    csvMeta(`Relation.${group.relation}.total_rows`, group.totalRows ?? group.items.length),
    csvMeta(`Relation.${group.relation}.truncated`, group.truncated ?? false),
    csvMeta(`Relation.${group.relation}.min_freq`, group.minFreq ?? ''),
  ])
}

function filenameTerm(): string {
  const raw = (searchTerm.value || queryStore.term || 'term').trim()
  return raw.replace(/[^\p{L}\p{N}_-]+/gu, '_').replace(/^_+|_+$/g, '') || 'term'
}

function exportCSV() {
  if (diffMode.value || !data.value.length) return
  const groups = data.value
  const csv = buildCsv({
    meta: [
      '# CandyConc Export',
      '# Analysis: WordSketch',
      csvMeta('Term', searchTerm.value || queryStore.term),
      csvMeta('Corpus', docsetStore.activeCorpus),
      csvMeta('Docset', docsetStore.activeDocsetId ?? 'all'),
      csvMeta('Docs', exportDocCount.value ?? ''), // i18n-ignore: CSV metadata key
      csvMeta('Tokens', exportTokenCount.value ?? ''),
      ...methodBlockToCsvLines(wordSketchMethod.value),
      ...relationMetaCsvLines(groups),
      csvMeta('Exported', new Date().toISOString()), // i18n-ignore: CSV metadata key
    ],
    headers: [
      'relation',
      'label',
      'word',
      'frequency',
      'score',
      'row_limit',
      'total_candidates',
      'total_rows',
      'truncated',
      'min_freq',
    ],
    rows: groups.flatMap((group) =>
      group.items.map((item) => [
        group.relation,
        group.label,
        item.word,
        item.frequency,
        item.score.toFixed(4),
        group.rowLimit ?? '',
        group.totalCandidates ?? '',
        group.totalRows ?? group.items.length,
        group.truncated ?? false,
        group.minFreq ?? '',
      ])
    ),
  })
  downloadCsv(csv, `wordsketch_${filenameTerm()}.csv`)
  uiStore.showToast(t('analysis.wordSketch.csvExported'), 'success', 2000)
}

async function loadDiff() {
  const termA = (searchTerm.value.trim() || queryStore.term).trim()
  const termB = compareTerm.value.trim()
  if (!termA || !termB) {
    const message = t('analysis.wordSketch.needTwoWords')
    diffError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  if (!(await ensureWordSketchCapability('diff'))) return
  if (!(await ensureCqlfTermsAllowed(termA, termB))) return
  const wantsDocsetScope = docsetStore.hasActiveDocset && useDocsetScope.value
  if (wantsDocsetScope && docsetStore.isDirty) {
    const message = t('analysis.wordSketch.docsetStale')
    diffError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const scopedDocsetId = wantsDocsetScope ? docsetStore.activeDocsetId ?? undefined : undefined
  isLoadingDiff.value = true
  diffError.value = null
  if (diffController.value) diffController.value.abort()
  const controller = new AbortController()
  diffController.value = controller
  try {
    diffData.value = await loadWordSketchDiff(
      { termA, termB, limit: diffLimit, corpus: docsetStore.activeCorpus, docsetId: scopedDocsetId },
      { signal: controller.signal }
    )
    wordSketchDiffMethod.value = coerceMethodBlock(diffData.value.method) ?? null
    diffScope.value = { corpus: docsetStore.activeCorpus, docsetId: scopedDocsetId ?? null }
  } catch (err) {
    if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') return
    const message = err instanceof Error ? err.message : t('analysis.wordSketch.diffLoadFailed')
    diffError.value = message
    wordSketchDiffMethod.value = null
    uiStore.showToast(message, 'error')
  } finally {
    if (diffController.value === controller) {
      isLoadingDiff.value = false
      diffController.value = null
    }
  }
}

const diffRelationLabels = computed(() =>
  (diffData.value?.relations ?? []).map((rel) => ({
    ...rel,
    label: labelForDiffRelation(rel.relation),
  }))
)

function fallbackRelationLabel(relation: string): string | undefined {
  switch (relation) {
    case 'obj':
    case 'object_of': return t('analysis.wordSketch.relations.objectOf')
    case 'amod': return t('analysis.wordSketch.relations.adjectiveModifiers')
    case 'nsubj':
    case 'subject_of': return t('analysis.wordSketch.relations.subjectOf')
    case 'conj':
    case 'coordinated': return t('analysis.wordSketch.relations.coordinatedWith')
    case 'compound': return t('analysis.wordSketch.relations.compounds')
    case 'modifier_left': return t('analysis.wordSketch.relations.modifiersLeft')
    default: return undefined
  }
}

function labelForRelation(relation: string): string {
  // Prefer the backend gloss, then the local fallback map, then the raw code.
  return (
    backendRelationLabels.value[relation] ??
    fallbackRelationLabel(relation) ??
    relation.replace(/_/g, ' ')
  )
}

/**
 * The relation in the dependency search syntax. Relations named with _rev
 * list heads of the term, so the term is the dependent: freedom <dobj
 * defend. The others list its dependents: freedom >amod political.
 */
function relationSearchOperator(relation: string): string {
  return relation.endsWith('_rev') ? `<${relation.slice(0, -4)}` : `>${relation}`
}

function relationSearchTitle(relation: string, term: string, collocate: string | undefined): string {
  const example = [term || '…', relationSearchOperator(relation), collocate || '…'].join(' ')
  return t('analysis.wordSketch.relationSearchTitle', { relation, example })
}

function labelForDiffRelation(relation: string): string {
  return (
    diffData.value?.relationLabels?.[relation] ??
    labelForRelation(relation)
  )
}

async function loadData() {
  const rawInput = searchTerm.value.trim() || queryStore.term
  if (!(await ensureWordSketchCapability('profile'))) return
  if (!(await ensureCqlfTermsAllowed(rawInput))) return
  const resolved = resolveWordSketchTerm(rawInput)
  if (!resolved.term) {
    const message = resolved.reason ?? t('analysis.wordSketch.needSingleWord')
    if (rawInput) {
      error.value = message
      uiStore.showToast(message, 'warning')
    }
    return
  }
  const term = resolved.term
  if (searchTerm.value.trim() && searchTerm.value.trim() !== term) {
    searchTerm.value = term
  }

  const wantsDocsetScope = docsetStore.hasActiveDocset && useDocsetScope.value
  if (wantsDocsetScope && docsetStore.isDirty) {
    const message = t('analysis.wordSketch.docsetStale')
    error.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const scopedDocsetId = wantsDocsetScope ? docsetStore.activeDocsetId ?? undefined : undefined

  isLoading.value = true
  error.value = null
  if (activeController.value) {
    activeController.value.abort()
  }
  const controller = new AbortController()
  activeController.value = controller
  try {
    const result = await loadWordSketch({
      term,
      limit: 50,
      corpus: docsetStore.activeCorpus,
      docsetId: scopedDocsetId,
    }, { signal: controller.signal })
    // Capture the backend gloss map before labelling so human-readable
    // relation names are used instead of raw codes (e.g. "Subjekt von …").
    backendRelationLabels.value = result.relationLabels ?? {}
    resultNode.value = result.node ?? null
    resultScope.value = { corpus: docsetStore.activeCorpus, docsetId: scopedDocsetId ?? null }
    data.value = result.relations.map((relation) => ({
      relation: relation.relation,
      label: labelForRelation(relation.relation),
      rowLimit: relation.rowLimit ?? null,
      totalCandidates: relation.totalCandidates ?? null,
      totalRows: relation.totalRows ?? null,
      truncated: relation.truncated ?? null,
      minFreq: relation.minFreq ?? null,
      items: relation.words
        .map((word) => ({
          word: word.word,
          score: word.score ?? 0,
          frequency: word.frequency ?? 0,
        }))
        .sort((a, b) => b.score - a.score),
    }))
    wordSketchMethod.value = coerceMethodBlock(result.method) ?? null
  } catch (err) {
    if (err && typeof err === 'object' && 'name' in err && err.name === 'AbortError') {
      return
    }
    const message = err instanceof Error ? err.message : t('analysis.wordSketch.loadFailed')
    error.value = message
    uiStore.showToast(message, 'error')
  } finally {
    if (activeController.value === controller) {
      isLoading.value = false
      activeController.value = null
    }
  }
}

/**
 * Row to concordance: the dependency search of node, relation and collocate
 * in the scope of the sketch. The sketch counts pairs of head and dependent,
 * the concordance one line per head. Both agree unless a head has several
 * dependents of the collocate form in the relation (sotu_en and dta_de: 1.7 %
 * of the rows), and the concordance header names both numbers then.
 */
function rowQuery(relation: string, collocate: string) {
  return resultNode.value ? wordSketchRowQuery(resultNode.value, relation, collocate) : null
}

function rowTitle(group: RelationGroup, item: CollocateItem): string {
  if (!resultNode.value) return t('analysis.wordSketch.backPathCql')
  if (!rowQuery(group.relation, item.word)) return t('analysis.wordSketch.backPathUnavailable')
  return t('analysis.wordSketch.openRow', { node: resultNode.value, relation: group.label, collocate: item.word })
}

async function openRowConcordance(group: RelationGroup, item: CollocateItem) {
  await openPairConcordance({
    node: resultNode.value,
    relation: group.relation,
    relationLabel: group.label,
    collocate: item.word,
    pairs: item.frequency,
    scope: resultScope.value,
    fromComparison: false,
  })
}

/** Rows of the sketch comparison: side A counts the first word, B the second. */
function diffNode(side: 'a' | 'b'): string | null {
  return (side === 'a' ? diffData.value?.nodeA : diffData.value?.nodeB) ?? null
}

function diffQuery(side: 'a' | 'b', relation: string, collocate: string) {
  const node = diffNode(side)
  return node ? wordSketchRowQuery(node, relation, collocate) : null
}

function diffTitle(side: 'a' | 'b', relation: string, relationLabel: string, collocate: string): string {
  const node = diffNode(side)
  if (!node) return t('analysis.wordSketch.backPathCql')
  if (!diffQuery(side, relation, collocate)) return t('analysis.wordSketch.backPathUnavailable')
  return t('analysis.wordSketch.openRow', { node, relation: relationLabel, collocate })
}

async function openDiffConcordance(
  side: 'a' | 'b',
  relation: string,
  relationLabel: string,
  collocate: string,
  pairs: number | null | undefined,
) {
  if (!pairs) return
  await openPairConcordance({
    node: diffNode(side),
    relation,
    relationLabel,
    collocate,
    pairs,
    scope: diffScope.value,
    fromComparison: true,
  })
}

async function openPairConcordance(pair: {
  node: string | null
  relation: string
  relationLabel: string
  collocate: string
  pairs: number
  scope: { corpus: string; docsetId: string | null } | null
  fromComparison: boolean
}) {
  const { node, scope } = pair
  const query = node ? wordSketchRowQuery(node, pair.relation, pair.collocate) : null
  if (!node || !query || !scope) return
  const activeDocsetId = docsetStore.hasActiveDocset ? docsetStore.activeDocsetId ?? null : null
  if (scope.corpus !== docsetStore.activeCorpus || scope.docsetId !== activeDocsetId) {
    uiStore.showToast(t('analysis.wordSketch.backPathDetached'), 'warning')
    return
  }
  // Set before the search runs, so that this tab keeps the sketch of the node
  // when the search term changes to the dependency query (see the term watch).
  queryStore.setBackPathOrigin({
    kind: 'wordSketch',
    term: query.term,
    node,
    relation: pair.relation,
    relationLabel: pair.relationLabel,
    collocate: pair.collocate,
    pairs: pair.pairs,
    exact: query.exact,
    fromComparison: pair.fromComparison,
  })
  const result = await actionBus.dispatch({
    type: 'query/execute',
    payload: {
      term: query.term,
      contextSize: queryStore.contextSize,
      ...(scope.docsetId ? { docsetId: scope.docsetId } : {}),
    },
  })
  if (!result.success) {
    queryStore.setBackPathOrigin(null)
    return
  }
  await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
}

function handleSearch() {
  loadData()
}

function cancelSearch() {
  if (!isLoading.value) return
  if (activeController.value) {
    activeController.value.abort()
    activeController.value = null
  }
  error.value = null
  isLoading.value = false
  uiStore.showToast(t('analysis.wordSketch.cancelled'), 'info')
}

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

const scopeText = computed(() => {
  if (!docsetStore.hasActiveDocset) return t('analysis.shared.wholeCorpus')
  const docs = formatNumber(docsetStore.stats.docCount)
  const tokens = formatNumber(docsetStore.stats.tokenCount)
  return t('analysis.shared.docsTokens', { docs, tokens })
})
const isCqlWordSketch = computed(() =>
  canUseCqlf.value && isCqlfQuery(searchTerm.value.trim() || queryStore.term.trim())
)

async function ensureCqlfTermsAllowed(...terms: string[]): Promise<boolean> {
  if (!terms.some((term) => isCqlfQuery(term))) return true
  if (!productCapabilities.hasContract) {
    await productCapabilities.load()
  }
  if (productCapabilities.hasContract && productCapabilities.isVisible('query.cqlf')) return true
  const message = t('analysis.wordSketch.cqlfNotEnabled')
  error.value = message
  diffError.value = message
  uiStore.showToast(message, 'warning')
  return false
}

async function ensureWordSketchCapability(operation: 'profile' | 'diff'): Promise<boolean> {
  if (!productCapabilities.hasContract) {
    await productCapabilities.load()
  }
  const activeCorpus = docsetStore.activeCorpus
  if (!corpusCapabilities.activeSummary || corpusCapabilities.activeSummary.name !== activeCorpus) {
    await corpusCapabilities.fetchCapabilities(activeCorpus)
  }
  const allowed = operation === 'diff'
    ? canLoadWordSketchDiff.value
    : canLoadWordSketch.value
  if (wordSketchCorpusDecision.value.status === 'pass' && allowed) return true
  const operationReason = operation === 'diff'
    ? wordSketchDiffBlockReason.value
    : wordSketchBlockReason.value
  const message = operationReason ||
    wordSketchFeatureMessage.value ||
    t('analysis.wordSketch.needsRel')
  error.value = message
  diffError.value = message
  uiStore.showToast(message, 'warning')
  return false
}

/** The sketch term behind a search term: the node when a sketch row opened it. */
function sketchTermFor(term: string): string {
  const origin = queryStore.backPathOrigin
  return origin?.kind === 'wordSketch' && origin.term === term ? origin.node : term
}

// Load on mount if query exists
watch(() => queryStore.term, (rawTerm) => {
  // A row of the shown sketch comparison opened the concordance: both words stay.
  const origin = queryStore.backPathOrigin
  if (origin?.kind === 'wordSketch' && origin.fromComparison && origin.term === rawTerm && diffData.value) return
  const term = rawTerm ? sketchTermFor(rawTerm) : rawTerm
  // A row of this sketch opened the concordance: the sketch stays as it is.
  if (term && term !== rawTerm && term === searchTerm.value && data.value.length) return
  if (term) {
    const resolved = resolveWordSketchTerm(term)
    if (!resolved.term) {
      const message = resolved.reason ?? t('analysis.wordSketch.needSingleWord')
      error.value = message
      uiStore.showToast(message, 'warning')
      return
    }
    searchTerm.value = resolved.term
    loadData()
  }
}, { immediate: true })

watch(
  () => presetsStore.pendingPreset,
  (preset) => {
    if (!preset || preset.type !== 'wordsketch') return
    const params = preset.params as { term?: string }
    if (params.term) searchTerm.value = params.term
    presetsStore.setPending(null)
    loadData()
  }
)

watch(
  () => useDocsetScope.value,
  () => {
    if (searchTerm.value.trim() || queryStore.term) {
      loadData()
    }
  }
)

// A corpus switch keeps the search term, but a sketch belongs to the corpus
// it was computed on. The tab computes it again for the new corpus, like
// frequency, dispersion and n-grams, and is empty without a term.
watch(
  () => docsetStore.activeCorpus,
  (corpus, previous) => {
    if (corpus === previous) return
    activeController.value?.abort()
    data.value = []
    error.value = null
    diffData.value = null
    diffError.value = null
    if (diffMode.value) {
      if ((searchTerm.value.trim() || queryStore.term) && compareTerm.value.trim()) loadDiff()
      return
    }
    if (searchTerm.value.trim() || queryStore.term) loadData()
  }
)

consumeFocusFor(['analysis.wordsketch'], (focus) => {
  diffMode.value =
    focus.operationId === 'analysis.wordsketch.diff' ||
    focus.preferredMode === 'diff' ||
    productOperationFocusMatches(focus, 'analysis.wordsketch.diff')
})
</script>

<template>
  <div class="wordsketch-tab">
    <AnalysisToolbar>
      <template #left>
        <div class="search-wrapper" :class="{ 'operation-focused': profileFocused }">
          <Search class="search-icon" />
          <input
            v-model="searchTerm"
            type="text"
            class="search-input"
            :disabled="wordSketchKnownUnavailable"
            :placeholder="canUseCqlf ? t('analysis.wordSketch.placeholderCql') : t('analysis.wordSketch.placeholder')"
            @keyup.enter="diffMode ? loadDiff() : handleSearch()"
          />
          <input
            v-if="diffMode"
            v-model="compareTerm"
            type="text"
            class="search-input"
            :disabled="wordSketchKnownUnavailable"
            :placeholder="t('analysis.wordSketch.comparePlaceholder')"
            @keyup.enter="loadDiff"
          />
          <Button
            variant="primary"
            size="sm"
            :icon="RefreshCw"
            :loading="diffMode ? isLoadingDiff : isLoading"
            :disabled="wordSketchKnownUnavailable"
            @click="diffMode ? loadDiff() : handleSearch()"
          >
            {{ diffMode ? t('analysis.wordSketch.compare') : t('analysis.wordSketch.analyze') }}
          </Button>
        </div>
        <label
          class="scope-toggle"
          :class="{ 'operation-focused': diffFocused }"
          :title="t('analysis.wordSketch.diffToggleTitle')"
        >
          <input v-model="diffMode" type="checkbox" data-testid="diff-toggle" />
          <span>{{ t('analysis.wordSketch.diffToggle') }}</span>
        </label>
        <div class="scope-pill" :class="{ active: docsetStore.hasActiveDocset, stale: docsetStore.isDirty }">
          {{ scopeText }}
        </div>
        <label v-if="docsetStore.hasActiveDocset" class="scope-toggle">
          <input v-model="useDocsetScope" type="checkbox" data-testid="scope-toggle" />
          <span>{{ t('analysis.shared.subcorpus') }}</span>
        </label>
      </template>

      <template #right>
        <JobStatusPill
          v-if="isLoading"
          status="running"
          :progress="0"
          :message="t('analysis.shared.loading')"
          :canCancel="true"
          @cancel="cancelSearch"
        />
        <Button
          v-if="!diffMode"
          variant="ghost"
          size="sm"
          :icon="Download"
          :disabled="!data.length"
          :aria-label="t('analysis.wordSketch.exportCsv')"
          @click="exportCSV"
        >
          CSV
        </Button>
        <SaveAnalysisButton
          type="wordsketch"
          :defaultName="t('analysis.wordSketch.defaultName', { query: searchTerm || queryStore.term || t('analysis.wordSketch.noQuery') })"
          :corpus="docsetStore.activeCorpus"
          :docset="docsetSnapshot"
          :queryTerm="searchTerm || queryStore.term"
          :params="{ term: searchTerm || queryStore.term }"
        />
      </template>
    </AnalysisToolbar>
    <CapabilityBoundaryPanel
      capability-id="analysis.wordsketch"
      :method="activeWordSketchMethod"
      class="ws-method"
    />
    <i18n-t v-if="searchTerm" keypath="analysis.wordSketch.sketchFor" tag="p" class="search-hint ws-heading" scope="global">
      <template #term><strong>{{ searchTerm }}</strong></template>
    </i18n-t>
    <p v-if="isCqlWordSketch" class="method-warning">
      {{ t('analysis.wordSketch.cqlLimited') }}
    </p>
    <p v-if="wordSketchFeatureMessage" class="method-warning">
      <CodeSpanText :text="wordSketchFeatureMessage" />
    </p>

    <!-- Results -->
    <div class="results-container">
      <!-- Sketch difference (two-term contrast) -->
      <template v-if="diffMode">
        <EmptyState
          v-if="diffError"
          :icon="AlertTriangle"
          :title="t('analysis.shared.loadError')"
          :description="diffError"
          :action-label="t('analysis.shared.retry')"
          size="sm"
          @action="loadDiff"
        />
        <div v-else-if="isLoadingDiff" class="loading-grid">
          <div v-for="i in 4" :key="i" class="loading-card">
            <Skeleton height="1.5rem" width="60%" class="mb-3" />
            <Skeleton v-for="j in 4" :key="j" height="2rem" class="mb-2" />
          </div>
        </div>
        <template v-else-if="diffData && diffRelationLabels.length">
          <i18n-t keypath="analysis.wordSketch.diffHeading" tag="p" class="search-hint" scope="global">
            <template #a><strong>{{ diffData.termA }}</strong></template>
            <template #b><strong>{{ diffData.termB }}</strong></template>
          </i18n-t>
          <p class="search-hint">{{ t('analysis.wordSketch.diffLimit', { limit: diffLimit }) }}</p>
          <div class="relations-grid">
            <div v-for="group in diffRelationLabels" :key="`diff-${group.relation}`" class="relation-card">
              <div class="relation-head">
                <h3 class="relation-title">{{ group.label }}</h3>
                <code
                  class="relation-code"
                  :title="relationSearchTitle(group.relation, diffData.termA, group.common[0]?.word ?? group.onlyA?.[0]?.word)"
                >{{ relationSearchOperator(group.relation) }}</code>
              </div>

              <div v-if="group.common.length" class="diff-section">
                <h4 class="diff-subtitle">{{ t('analysis.wordSketch.common') }}</h4>
                <table class="relation-table">
                  <thead>
                    <tr>
                      <th class="diff-th">{{ t('analysis.wordSketch.word') }}</th>
                      <th class="diff-th diff-th--num">f {{ diffData.termA }}</th>
                      <th class="diff-th diff-th--num">f {{ diffData.termB }}</th>
                      <th class="diff-th diff-th--num">{{ diffData.termA }}</th>
                      <th class="diff-th diff-th--num">{{ diffData.termB }}</th>
                      <th class="diff-th diff-th--num">Δ</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="item in group.common" :key="`common-${item.word}`">
                      <td class="item-word">{{ item.word }}</td>
                      <td class="diff-num">
                        <button
                          type="button"
                          class="diff-link"
                          data-testid="wordsketch-diff-open-a"
                          :disabled="!item.frequencyA || !diffQuery('a', group.relation, item.word)"
                          :title="diffTitle('a', group.relation, group.label, item.word)"
                          @click="openDiffConcordance('a', group.relation, group.label, item.word, item.frequencyA)"
                        >
                          {{ formatFrequency(item.frequencyA) }}
                        </button>
                      </td>
                      <td class="diff-num">
                        <button
                          type="button"
                          class="diff-link"
                          data-testid="wordsketch-diff-open-b"
                          :disabled="!item.frequencyB || !diffQuery('b', group.relation, item.word)"
                          :title="diffTitle('b', group.relation, group.label, item.word)"
                          @click="openDiffConcordance('b', group.relation, group.label, item.word, item.frequencyB)"
                        >
                          {{ formatFrequency(item.frequencyB) }}
                        </button>
                      </td>
                      <td class="diff-num">{{ formatScore(item.scoreA) }}</td>
                      <td class="diff-num">{{ formatScore(item.scoreB) }}</td>
                      <td
                        class="diff-num diff-delta"
                        :class="{ 'delta-pos': (item.delta ?? 0) > 0, 'delta-neg': (item.delta ?? 0) < 0 }"
                      >
                        {{ formatDelta(item.delta) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <div class="diff-only-grid">
                <div class="diff-only">
                  <h4 class="diff-subtitle">{{ t('analysis.wordSketch.onlyTerm', { term: diffData.termA }) }}</h4>
                  <ul class="diff-only-list">
                    <li
                      v-for="item in group.onlyA"
                      :key="`a-${item.word}`"
                      :class="{ 'row-link': diffQuery('a', group.relation, item.word) && item.frequency }"
                      :tabindex="diffQuery('a', group.relation, item.word) && item.frequency ? 0 : undefined"
                      :title="diffTitle('a', group.relation, group.label, item.word)"
                      data-testid="wordsketch-diff-only-a"
                      @click="openDiffConcordance('a', group.relation, group.label, item.word, item.frequency)"
                      @keydown.enter="openDiffConcordance('a', group.relation, group.label, item.word, item.frequency)"
                    >
                      {{ item.word }}
                      <span class="diff-only-score">f={{ formatFrequency(item.frequency) }} · {{ formatScore(item.score) }}</span>
                    </li>
                    <li v-if="!group.onlyA.length" class="diff-only-empty">—</li>
                  </ul>
                </div>
                <div class="diff-only">
                  <h4 class="diff-subtitle">{{ t('analysis.wordSketch.onlyTerm', { term: diffData.termB }) }}</h4>
                  <ul class="diff-only-list">
                    <li
                      v-for="item in group.onlyB"
                      :key="`b-${item.word}`"
                      :class="{ 'row-link': diffQuery('b', group.relation, item.word) && item.frequency }"
                      :tabindex="diffQuery('b', group.relation, item.word) && item.frequency ? 0 : undefined"
                      :title="diffTitle('b', group.relation, group.label, item.word)"
                      data-testid="wordsketch-diff-only-b"
                      @click="openDiffConcordance('b', group.relation, group.label, item.word, item.frequency)"
                      @keydown.enter="openDiffConcordance('b', group.relation, group.label, item.word, item.frequency)"
                    >
                      {{ item.word }}
                      <span class="diff-only-score">f={{ formatFrequency(item.frequency) }} · {{ formatScore(item.score) }}</span>
                    </li>
                    <li v-if="!group.onlyB.length" class="diff-only-empty">—</li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </template>
        <EmptyState
          v-else
          :icon="PenTool"
          :title="t('analysis.wordSketch.noDiffTitle')"
          :description="t('analysis.wordSketch.noDiffDescription')"
          size="sm"
        />
      </template>

      <EmptyState
        v-else-if="error"
        :icon="AlertTriangle"
        :title="t('analysis.shared.loadError')"
        :description="error"
        :action-label="t('analysis.shared.retry')"
        :secondary-action-label="t('analysis.shared.checkSubcorpus')"
        size="sm"
        @action="loadData"
        @secondaryAction="uiStore.openSubcorpus()"
      />

      <template v-else-if="!isLoading && data.length > 0">
        <div class="relations-grid">
          <div v-for="group in data" :key="group.relation" class="relation-card">
            <div class="relation-head">
              <h3 class="relation-title">{{ group.label }}</h3>
              <code
                class="relation-code"
                :title="relationSearchTitle(group.relation, searchTerm.trim(), group.items[0]?.word)"
              >{{ relationSearchOperator(group.relation) }}</code>
            </div>
            <p v-if="group.totalCandidates !== null" class="relation-meta">
              {{ t('analysis.wordSketch.shownOf', { shown: formatNumber(group.items.length), total: formatNumber(group.totalCandidates) }) }}
              <span v-if="group.truncated">· {{ t('analysis.wordSketch.capped') }}</span>
            </p>
            <table class="relation-table">
              <tbody>
                <tr
                  v-for="item in group.items"
                  :key="item.word"
                  :class="{ 'row-link': rowQuery(group.relation, item.word) }"
                  :tabindex="rowQuery(group.relation, item.word) ? 0 : undefined"
                  :title="rowTitle(group, item)"
                  data-testid="wordsketch-row"
                  @click="openRowConcordance(group, item)"
                  @keydown.enter="openRowConcordance(group, item)"
                >
                  <td class="item-word">{{ item.word }}</td>
                  <td class="item-freq">({{ item.frequency }})</td>
                  <td class="item-score" :title="t('analysis.wordSketch.scoreTitle')">
                    <div class="score-bar">
                      <div class="score-fill" :style="{ width: `${item.score * 7}%` }" />
                    </div>
                    <span>{{ formatScore(item.score) }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

      </template>

      <!-- Loading -->
      <div v-else-if="isLoading" class="loading-grid">
        <div v-for="i in 4" :key="i" class="loading-card">
          <Skeleton height="1.5rem" width="60%" class="mb-3" />
          <Skeleton v-for="j in 4" :key="j" height="2rem" class="mb-2" />
        </div>
      </div>

      <!-- Empty State -->
      <EmptyState
        v-else
        :icon="PenTool"
        :title="t('analysis.wordSketch.emptyTitle')"
        :description="t('analysis.wordSketch.emptyDescription')"
        size="sm"
      />
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.wordsketch-tab {
  /* At least as high as the tab, grows with its content: the tab area
     scrolls (App.vue .tab-content). */
  @apply flex flex-col min-h-full;
}

.search-wrapper {
  @apply flex items-center gap-2;
}

.search-wrapper.operation-focused,
.scope-toggle.operation-focused {
  @apply ring-2 ring-amber-300 ring-offset-2 ring-offset-white;
  @apply dark:ring-amber-500/80 dark:ring-offset-neutral-950;
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
  @apply w-5 h-5 text-neutral-400;
}

.search-input {
  @apply flex-1 px-4 py-2 rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-base;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.search-hint {
  @apply mt-2 text-sm text-neutral-500 dark:text-neutral-400;
}

/* Outside the padded results container: the same inset as the cards. */
.ws-heading {
  @apply px-4;
}

.search-hint strong {
  @apply text-primary-600 dark:text-primary-400;
}

.method-warning {
  @apply mt-1 px-4 text-xs text-amber-700 dark:text-amber-300;
}

.results-container {
  /* Results in the flow of the tab, which scrolls as a whole. */
  flex: 1 0 auto;
  @apply p-4;
}

.relations-grid {
  @apply grid grid-cols-2 gap-4;
}

.ws-method {
  @apply mt-4;
}

/* Sketch difference (FT-SKETCH-DIFF-DISTRIBUTION) */
.diff-section {
  @apply mb-3;
}

.diff-subtitle {
  @apply text-[11px] font-semibold uppercase tracking-wide;
  @apply text-neutral-500 dark:text-neutral-400 mb-1;
}

.diff-th {
  @apply text-[11px] font-medium text-neutral-500 dark:text-neutral-400 text-left pb-1;
}

.diff-th--num,
.diff-num {
  @apply text-right tabular-nums;
}

.diff-num {
  @apply text-xs font-mono text-neutral-600 dark:text-neutral-300 py-1;
}

.diff-delta.delta-pos {
  @apply text-emerald-600 dark:text-emerald-400;
}

.diff-delta.delta-neg {
  @apply text-rose-600 dark:text-rose-400;
}

.diff-only-grid {
  @apply grid grid-cols-2 gap-3;
}

.diff-only-list {
  @apply text-sm space-y-1;
}

.diff-only-list li {
  @apply flex items-center justify-between gap-2;
  @apply text-neutral-800 dark:text-neutral-200;
}

.diff-only-score {
  @apply text-xs font-mono text-neutral-400;
}

.diff-only-list li.row-link {
  @apply cursor-pointer rounded px-1 -mx-1;
}

.diff-only-list li.row-link:hover,
.diff-only-list li.row-link:focus-visible {
  @apply bg-primary-50 dark:bg-primary-900/20 outline-none;
}

.diff-link {
  @apply tabular-nums underline decoration-dotted underline-offset-2 rounded px-0.5;
  @apply text-primary-700 dark:text-primary-300;
  @apply hover:bg-primary-50 dark:hover:bg-primary-900/30;
  @apply focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500;
}

.diff-link:disabled {
  @apply no-underline text-neutral-500 dark:text-neutral-400 cursor-default hover:bg-transparent;
}

.diff-only-empty {
  @apply text-neutral-400 dark:text-neutral-500;
}

@media (max-width: 768px) {
  .relations-grid {
    @apply grid-cols-1;
  }
}

.relation-card {
  @apply p-4 rounded-xl;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.relation-head {
  @apply flex items-baseline justify-between gap-2;
  @apply mb-3 pb-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.relation-title {
  @apply text-sm font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
}

/* The relation as the dependency search writes it, to copy into a query. */
.relation-code {
  @apply shrink-0 rounded px-1.5 py-0.5 font-mono text-xs;
  @apply bg-neutral-100 text-neutral-700 dark:bg-neutral-700 dark:text-neutral-200;
  user-select: all;
}

.relation-meta {
  @apply -mt-2 mb-3 text-xs;
  @apply text-neutral-500 dark:text-neutral-400;
}

.relation-table {
  @apply w-full;
}

.relation-table tr {
  @apply border-b border-neutral-100 dark:border-neutral-700/50;
}

.relation-table tr:last-child {
  @apply border-b-0;
}

.relation-table tr.row-link {
  @apply cursor-pointer;
}

.relation-table tr.row-link:hover,
.relation-table tr.row-link:focus-visible {
  @apply bg-primary-50 dark:bg-primary-900/20 outline-none;
}

.relation-table td {
  @apply py-2;
}

.item-word {
  @apply font-medium text-neutral-900 dark:text-neutral-100;
}

.item-freq {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
  @apply text-right pr-4;
}

.item-score {
  @apply flex items-center gap-2;
  @apply w-24;
}

.score-bar {
  @apply flex-1 h-2 rounded-full overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.score-fill {
  @apply h-full rounded-full;
  @apply bg-primary-500;
}

.item-score span {
  @apply text-xs font-mono text-neutral-600 dark:text-neutral-400;
  @apply w-8 text-right;
}

.loading-grid {
  @apply grid grid-cols-2 gap-4;
}

.loading-card {
  @apply p-4 rounded-xl;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.empty-state {
  @apply flex flex-col items-center justify-center;
  @apply py-16 text-center;
}

.empty-icon {
  @apply w-16 h-16 mb-4;
  @apply text-neutral-300 dark:text-neutral-600;
}

.empty-title {
  @apply font-medium text-neutral-900 dark:text-neutral-100;
}

.empty-desc {
  @apply text-sm text-neutral-500 dark:text-neutral-400 mt-1;
  @apply max-w-xs;
}
</style>
