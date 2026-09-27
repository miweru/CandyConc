<script setup lang="ts">
/**
 * FreeContrastPanel — pairing-free A-vs-B contrast for ANY corpus.
 *
 * Unlike the legacy paired preset (KeynessTab, hardwired to text_type/model/…
 * pairwise axes), this panel drives both group selectors from the live
 * `GET /analysis/meta_schema` of the active corpus, so a user can pick
 * "field = X" vs "field = Y" on a generic corpus, OR contrast two saved
 * subcorpora. It resolves each side to a docset and calls the pairing-free
 * `POST /analysis/contrast` endpoint (async job).
 *
 * Single source of truth for the active corpus: corpusCapabilities.activeCorpus.
 */
import { ref, computed, onMounted, watch } from 'vue'
import { Scale, RefreshCw, ArrowRight } from 'lucide-vue-next'
import Button from '@/components/ui/Button.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useQueryStore } from '@/stores/query'
import { useAnalysisJobsStore } from '@/stores/analysisJobs'
import { MAX_ENUM_FACET_VALUES, useDocsetStore, isIdentityField } from '@/stores/docset'
import { useSubcorporaStore, type SubcorpusSnapshot } from '@/stores/subcorpora'
import { CONTRAST_OPERATIONS, useContrastOperations } from '@/composables/useContrastOperations'
import {
  productOperationFocusMatches,
  useProductOperationFocus,
} from '@/composables/useProductOperationFocus'
import {
  coerceMethodBlock,
  type FilterSpec,
  type MethodBlock,
} from '@/api/client'
import type { MetaSchemaResponse } from '@/api/schemas'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import LexicalDiversityCard from '@/components/analysis/LexicalDiversityCard.vue'
import { stripCoQueryTerm } from '@/utils/queryTerm'
import { buildCoKwicQuery } from '@/utils/coKwic'
import { actionBus } from '@/actions/bus'
import { useUiStore } from '@/stores/ui'
import { formatDecimal, formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const corpusStore = useCorpusCapabilitiesStore()
const queryStore = useQueryStore()
const analysisJobs = useAnalysisJobsStore()
const docsetStore = useDocsetStore()
const subcorporaStore = useSubcorporaStore()
const uiStore = useUiStore()
const {
  canStartFreeContrastJob,
  canStartCollocationContrastJob,
  canLoadLexicalDiversity,
  freeContrastJobBlockReason,
  collocationContrastJobBlockReason,
  createFreeContrastJob,
  createCollocationContrastJob,
} = useContrastOperations()
const { consumeFocusFor, focusMatches, focusIs, modeIs } = useProductOperationFocus()

const activeCorpus = computed(() => corpusStore.activeCorpus)
const canUseLexicalDiversity = computed(() => canLoadLexicalDiversity.value)
type ContrastAnalysisKind = 'free' | 'collocations'
type ContrastSortBy = 'mi' | 'lmi' | 'npmi' | 'z' | 'chi2_cell' | 'dice' | 'logdice' | 't' | 'll' | 'f'
const analysisKind = ref<ContrastAnalysisKind>('free')
const windowSize = ref(5)
const withinSentence = ref(true)
const sortBy = ref<ContrastSortBy>('logdice')
const freeContrastFocused = computed(() =>
  modeIs('free') || focusIs('analysis.contrast.free_job') || focusMatches('analysis.contrast.free')
)
const collocationContrastFocused = computed(() =>
  modeIs('collocations') ||
  focusIs('analysis.contrast.collocations_diff_job') ||
  focusMatches('analysis.contrast.collocations', 'analysis.contrast.collocations_diff')
)
const lexicalDiversityFocused = computed(() =>
  modeIs('lexical_diversity') ||
  focusIs('analysis.contrast.lexical_diversity') ||
  focusMatches('analysis.contrast.lexical_diversity')
)

// ── Group selection model ───────────────────────────────────────────────────
// A group is EITHER a metadata field=value filter OR a saved subcorpus name.
type GroupMode = 'field' | 'subcorpus'
interface GroupSelection {
  mode: GroupMode
  field: string
  value: string
  subcorpus: string
}

function emptyGroup(): GroupSelection {
  return { mode: 'field', field: '', value: '', subcorpus: '' }
}

const groupA = ref<GroupSelection>(emptyGroup())
const groupB = ref<GroupSelection>(emptyGroup())

// ── Schema / option data ────────────────────────────────────────────────────
const schema = ref<MetaSchemaResponse | null>(null)
const subcorpora = ref<SubcorpusSnapshot[]>([])
const valuesByField = ref<Record<string, string[]>>({})
const isLoadingSchema = ref(false)
const schemaError = ref<string | null>(null)

// Identity fields are not research axes, and a field with hundreds of distinct
// values is not a usable A/B picker. Both remain available through a deliberate
// subcorpus definition rather than causing an unbounded value-list request.
const highCardinalityMetaFields = computed(() =>
  (schema.value?.metadataFields ?? [])
    .filter((field) => {
      const count = field.stringValueCount
      return Boolean(field.name) && typeof count === 'number' && count > MAX_ENUM_FACET_VALUES
    })
    .map((field) => field.name)
)
const metaFields = computed(() =>
  (schema.value?.metadataFields ?? [])
    .filter((field) => {
      if (!field.name || isIdentityField(field.name) || field.placeholder) return false
      const count = field.stringValueCount
      return typeof count !== 'number' || count <= MAX_ENUM_FACET_VALUES
    })
    .map((field) => field.name)
)
const hasMetaFields = computed(() => metaFields.value.length > 0)
const subcorporaForCorpus = computed(() =>
  subcorpora.value.filter((s) => (s.corpus ?? 'default') === activeCorpus.value)
)

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

async function loadSchema() {
  isLoadingSchema.value = true
  schemaError.value = null
  try {
    const [sch] = await Promise.all([
      docsetStore.fetchMetaSchema(activeCorpus.value),
      subcorporaStore.init(),
    ])
    if (!sch) throw new Error(docsetStore.error ?? t('analysis.freeContrast.schemaFailed'))
    schema.value = sch
    subcorpora.value = [...subcorporaStore.parked]
  } catch (err) {
    // validateResponse THROWS on a contract mismatch — surface it, don't crash.
    schemaError.value =
      err instanceof Error ? err.message : t('analysis.freeContrast.schemaFailed')
    schema.value = null
  } finally {
    isLoadingSchema.value = false
  }
}

async function ensureValues(field: string) {
  if (!field || valuesByField.value[field]) return
  try {
    const result = await docsetStore.fetchMetaValues({ fields: [field], corpus: activeCorpus.value })
    valuesByField.value = {
      ...valuesByField.value,
      [field]: [...(result?.[field] ?? [])].sort(),
    }
  } catch {
    valuesByField.value = { ...valuesByField.value, [field]: [] }
  }
}

function onFieldChange(group: GroupSelection) {
  group.value = ''
  void ensureValues(group.field)
  resetResults()
}

// ── Results ─────────────────────────────────────────────────────────────────
interface ContrastRow {
  word: string
  /** Co-occurrence tokens (O11) of the collocate in group A and group B. */
  targetFreq: number
  referenceFreq: number
  targetPerMillion: number
  referencePerMillion: number
  diffPerMillion: number
  targetScore: number | null
  referenceScore: number | null
  diffScore: number | null
  scoreKey: string | null
  logRatio: number | null
  oneSided: boolean
}

const rows = ref<ContrastRow[]>([])
// Settings of the shown result, for the back path of a row to the concordance.
interface ContrastRunContext {
  term: string
  window: number
  withinSentence: boolean
  target: GroupSelection
  reference: GroupSelection
}
const runContext = ref<ContrastRunContext | null>(null)
const isRunning = ref(false)
const runError = ref<string | null>(null)
const lastRunAt = ref<number | null>(null)
const totalResults = ref<number | null>(null)
const truncated = ref(false)
// F1: statistical provenance from the server method block.
const contrastMethod = ref<MethodBlock | null>(null)
const TOP_N = 50

interface ResolvedSide {
  docsetId: string
  label: string
}

const resolvedDiversityComparison = ref<{
  targetDocsetId: string
  referenceDocsetId: string
  targetLabel: string
  referenceLabel: string
} | null>(null)

function resetResults() {
  rows.value = []
  runContext.value = null
  runError.value = null
  lastRunAt.value = null
  totalResults.value = null
  truncated.value = false
  contrastMethod.value = null
  resolvedDiversityComparison.value = null
}

function selectAnalysisKind(kind: ContrastAnalysisKind) {
  if (analysisKind.value === kind) return
  analysisKind.value = kind
  resetResults()
}

const term = computed(() => stripCoQueryTerm(queryStore.term))

function groupLabel(group: GroupSelection): string {
  if (group.mode === 'subcorpus') return group.subcorpus || '—'
  if (group.field && group.value) return `${group.field} = ${group.value}`
  return '—'
}

function groupReady(group: GroupSelection): boolean {
  if (group.mode === 'subcorpus') return Boolean(group.subcorpus)
  return Boolean(group.field && group.value)
}

const canRun = computed(() => {
  if (!term.value) return false
  if (!groupReady(groupA.value) || !groupReady(groupB.value)) return false
  if (analysisKind.value === 'free' && !canStartFreeContrastJob.value) return false
  if (analysisKind.value === 'collocations' && !canStartCollocationContrastJob.value) return false
  // Two distinct sides required.
  return groupLabel(groupA.value) !== groupLabel(groupB.value)
})
const activeOperationBlockReason = computed(() =>
  analysisKind.value === 'collocations'
    ? collocationContrastJobBlockReason.value
    : freeContrastJobBlockReason.value
)
const hasScoreColumns = computed(() =>
  rows.value.some((row) =>
    row.targetScore !== null ||
    row.referenceScore !== null ||
    row.diffScore !== null
  )
)
const visibleScoreKey = computed(() =>
  rows.value.find((row) => row.scoreKey)?.scoreKey ?? sortBy.value
)
const visibleScoreLabel = computed(() => scoreLabel(visibleScoreKey.value))

/** Resolve both side types to docsets so contrast and diversity share one scope. */
async function resolveSide(group: GroupSelection): Promise<ResolvedSide> {
  if (group.mode === 'subcorpus') {
    const result = await docsetStore.resolveNamedSubcorpusDocset(group.subcorpus, activeCorpus.value)
    if (!result) throw new Error(docsetStore.error ?? t('analysis.freeContrast.subcorpusResolveFailed'))
    return { docsetId: result.docset_id, label: group.subcorpus }
  }
  const spec: FilterSpec = { [group.field]: group.value }
  const result = await docsetStore.createTransientDocsetFromMeta(
    spec,
    activeCorpus.value
  )
  if (!result) throw new Error(docsetStore.error ?? t('analysis.freeContrast.metaDocsetFailed'))
  return { docsetId: result.docset_id, label: groupLabel(group) }
}

async function run() {
  if (!canRun.value || isRunning.value) return
  isRunning.value = true
  runError.value = null
  rows.value = []
  contrastMethod.value = null
  try {
    const [target, reference] = await Promise.all([
      resolveSide(groupA.value),
      resolveSide(groupB.value),
    ])
    resolvedDiversityComparison.value =
      target.docsetId !== reference.docsetId
        ? {
            targetDocsetId: target.docsetId,
            referenceDocsetId: reference.docsetId,
            targetLabel: target.label,
            referenceLabel: reference.label,
          }
        : null
    const response = await analysisJobs.runJobRows<Record<string, unknown>>({
      scope: `${analysisKind.value === 'collocations' ? 'collocates-diff' : 'free-contrast'}:${activeCorpus.value}`,
      kind: analysisKind.value === 'collocations' ? 'collocates_diff' : 'contrast',
      corpus: activeCorpus.value,
      rowsLimit: TOP_N,
      queuedMessage: analysisKind.value === 'collocations'
        ? t('analysis.freeContrast.collocationStarted')
        : t('analysis.freeContrast.contrastStarted'),
      productOperation: {
        operationId: analysisKind.value === 'collocations'
          ? CONTRAST_OPERATIONS.collocationsDiffJob
          : CONTRAST_OPERATIONS.freeJob,
        surfaceId: 'analysis.contrast',
        label: analysisKind.value === 'collocations'
          ? t('analysis.operations.collocationContrastJob')
          : t('analysis.operations.freeContrastJob'),
        detail: `${target.label} vs. ${reference.label}`,
      },
      start: () => analysisKind.value === 'collocations'
        ? createCollocationContrastJob({
            term: term.value,
            targetDocsetId: target.docsetId,
            referenceDocsetId: reference.docsetId,
            window: windowSize.value,
            withinSentence: withinSentence.value,
            sortBy: sortBy.value,
            corpus: activeCorpus.value,
            limit: TOP_N,
          })
        : createFreeContrastJob({
            term: term.value,
            targetDocsetId: target.docsetId,
            referenceDocsetId: reference.docsetId,
            window: windowSize.value,
            withinSentence: withinSentence.value,
            sortBy: sortBy.value,
            corpus: activeCorpus.value,
            limit: TOP_N,
          }),
    })
    rows.value = mapContrastRows(response)
    runContext.value = {
      term: term.value,
      window: windowSize.value,
      withinSentence: withinSentence.value,
      target: { ...groupA.value },
      reference: { ...groupB.value },
    }
    lastRunAt.value = Date.now()
  } catch (err) {
    if (isAbortError(err)) return
    runError.value =
      err instanceof Error ? err.message : t('analysis.freeContrast.failed')
  } finally {
    isRunning.value = false
  }
}

function mapContrastRows(response: {
  rows?: Record<string, unknown>[]
  method?: unknown
  total?: number | null
  total_rows?: number | null
  total_candidates?: number | null
  truncated?: boolean
}): ContrastRow[] {
  const raw = Array.isArray(response.rows) ? response.rows : []
  contrastMethod.value = coerceMethodBlock(response.method) ?? null
  // The banner must reflect the true candidate POOL (total_candidates, e.g. 2756),
  // not the bounded page count — `total_rows === rows.length` would render a
  // tautological "Top 50 von 50" that hides how much was dropped. Same disclosure
  // seam the FrequencyTab banner uses (total_candidates ?? total_rows). total/
  // truncated stay optional for older backends (SUBC-04).
  const total = response.total_candidates ?? response.total_rows ?? response.total ?? null
  totalResults.value = typeof total === 'number' ? total : null
  truncated.value = response.truncated === true
    || (typeof total === 'number' && total > raw.length)
  return raw.map((row) => {
    const word = String(row.word ?? '').trim()
    const t = num(row.target_per_million ?? row.target_freq)
    const r = num(row.reference_per_million ?? row.reference_freq)
    const d = num(row.diff_per_million ?? t - r)
    const targetScore = maybeNum(row.target_score)
    const referenceScore = maybeNum(row.reference_score)
    const diffScore = maybeNum(row.diff_score)
    const lr = typeof row.log_ratio === 'number' && Number.isFinite(row.log_ratio)
      ? row.log_ratio
      : null
    return {
      word,
      targetFreq: num(row.target_freq),
      referenceFreq: num(row.reference_freq),
      targetPerMillion: t,
      referencePerMillion: r,
      diffPerMillion: d,
      targetScore,
      referenceScore,
      diffScore,
      scoreKey: typeof row.score_key === 'string' && row.score_key.trim()
        ? row.score_key.trim()
        : null,
      logRatio: lr,
      oneSided: row.one_sided === true,
    }
  })
}

/**
 * Row to concordance: the scope becomes the group of the column, and the
 * concordance shows the hits of the node with the collocate in their window,
 * with the window and sentence limit of the contrast. Its co-occurrence
 * count equals the row's count on that side (checked on sotu_en and dta_de,
 * 20,785 sides of rows). The number of lines is the number of node hits and
 * can differ, as with a collocation row.
 */
function sideCount(row: ContrastRow, side: 'target' | 'reference'): number {
  return side === 'target' ? row.targetFreq : row.referenceFreq
}

function sideTitle(row: ContrastRow, side: 'target' | 'reference'): string {
  const ctx = runContext.value
  if (!ctx) return ''
  const group = groupLabel(side === 'target' ? ctx.target : ctx.reference)
  if (!sideCount(row, side)) return t('analysis.freeContrast.noLinesInGroup', { group })
  return t('analysis.freeContrast.openInGroup', { node: ctx.term, collocate: row.word, group })
}

async function activateGroupScope(group: GroupSelection): Promise<boolean> {
  if (group.mode === 'field') {
    return docsetStore.setMetaScope({ [group.field]: group.value })
  }
  const snapshot = subcorporaForCorpus.value.find((candidate) => candidate.name === group.subcorpus)
  if (!snapshot) return false
  await docsetStore.applySnapshot({
    corpus: snapshot.corpus,
    docsetId: snapshot.docsetId ?? '',
    name: subcorporaStore.durableNameForSnapshot(snapshot),
    filterSpec: snapshot.filterSpec,
    metadataSchemaHash: snapshot.metadataSchemaHash,
    stats: {
      docCount: snapshot.stats.docCount,
      hitDocCount: 0,
      refDocCount: snapshot.stats.refDocCount,
      tokenCount: snapshot.stats.tokenCount,
    },
    filters: snapshot.filters,
    includeAi: snapshot.includeAi,
    includeHuman: snapshot.includeHuman,
    query: snapshot.origin.query,
  })
  return Boolean(docsetStore.activeDocsetId)
}

async function openSideConcordance(row: ContrastRow, side: 'target' | 'reference') {
  const ctx = runContext.value
  const count = sideCount(row, side)
  if (!ctx || !count) return
  const group = side === 'target' ? ctx.target : ctx.reference
  if (!(await activateGroupScope(group))) {
    uiStore.showToast(docsetStore.error ?? t('analysis.freeContrast.groupScopeFailed', { group: groupLabel(group) }), 'warning')
    return
  }
  const coTerm = buildCoKwicQuery({
    term: ctx.term,
    collocates: [row.word],
    window: ctx.window,
    withinSentence: ctx.withinSentence,
  })
  queryStore.setBackPathOrigin({
    kind: 'contrast',
    term: coTerm,
    node: ctx.term,
    collocate: row.word,
    side,
    group: groupLabel(group),
    cooccurrences: count,
    perMillion: side === 'target' ? row.targetPerMillion : row.referencePerMillion,
  })
  const result = await actionBus.dispatch({
    type: 'query/execute',
    payload: { term: coTerm, contextSize: queryStore.contextSize, docsetId: docsetStore.activeDocsetId ?? undefined },
  })
  if (!result.success) {
    queryStore.setBackPathOrigin(null)
    return
  }
  await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
}

function num(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0
}

function maybeNum(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatPerMillion(value: number): string {
  return formatNumber(value, { maximumFractionDigits: 1 })
}

function formatScore(value: number | null): string {
  if (value === null) return '–'
  return formatNumber(value, { maximumFractionDigits: 3 })
}

function formatLogRatio(value: number | null): string {
  if (value === null) return '–'
  return formatDecimal(value, 2)
}

function scoreLabel(value: string | null): string {
  const normalized = (value ?? '').toLowerCase()
  switch (normalized) {
    case 'logdice': return 'logDice'
    case 'mi': return 'MI'
    case 'lmi': return 'LMI'
    case 'npmi': return 'NPMI'
    case 'z': return t('analysis.measureOptions.zScore')
    case 't': return t('analysis.measureOptions.tScore')
    case 'll': return t('analysis.measureOptions.logLikelihood')
    case 'f': return t('analysis.freeContrast.frequency')
    case 'chi2_cell': return t('analysis.measureOptions.chi2Cell')
    case 'dice': return 'Dice'
    default: return value ?? 'Score'
  }
}

onMounted(loadSchema)
consumeFocusFor(
  ['analysis.contrast.free', 'analysis.contrast.collocations', 'analysis.contrast.collocations_diff'],
  (focus) => {
    if (
      focus.operationId === 'analysis.contrast.collocations_diff_job' ||
      focus.preferredMode === 'collocations' ||
      productOperationFocusMatches(focus, 'analysis.contrast.collocations', 'analysis.contrast.collocations_diff')
    ) {
      selectAnalysisKind('collocations')
      return
    }
    selectAnalysisKind('free')
  },
)
// Reload schema/options when the active corpus changes (single source of truth).
watch(activeCorpus, () => {
  groupA.value = emptyGroup()
  groupB.value = emptyGroup()
  valuesByField.value = {}
  resetResults()
  void loadSchema()
})
</script>

<template>
  <div class="free-contrast">
    <header class="fc-head">
      <div class="fc-title">
        <Scale class="w-4 h-4" aria-hidden="true" />
        <span>{{ t('analysis.freeContrast.title') }}</span>
      </div>
      <p class="fc-sub">
        {{ t('analysis.freeContrast.subtitle', { term: term || '…' }) }}
      </p>
    </header>

    <div v-if="isLoadingSchema && !schema" class="fc-loading">{{ t('analysis.freeContrast.loadingMeta') }}</div>
    <div v-else-if="schemaError" class="fc-error">
      {{ schemaError }}
      <Button variant="ghost" size="sm" :icon="RefreshCw" @click="loadSchema">{{ t('analysis.freeContrast.again') }}</Button>
    </div>

    <EmptyState
      v-else-if="!hasMetaFields && !subcorporaForCorpus.length"
      :icon="Scale"
      :title="t('analysis.freeContrast.noMetaTitle')"
      :description="t('analysis.freeContrast.noMetaDescription')"
    />

    <template v-else>
      <section class="fc-analysis-kind" :aria-label="t('analysis.freeContrast.kind')">
        <button
          type="button"
          class="fc-kind"
          :class="{ active: analysisKind === 'free', 'operation-focused': freeContrastFocused }"
          :disabled="!canStartFreeContrastJob"
          :title="freeContrastJobBlockReason ?? t('analysis.freeContrast.freeKindTitle')"
          @click="selectAnalysisKind('free')"
        >
          <strong>{{ t('analysis.freeContrast.freeKind') }}</strong>
          <span>{{ t('analysis.freeContrast.freeKindDescription') }}</span>
        </button>
        <button
          type="button"
          class="fc-kind"
          :class="{ active: analysisKind === 'collocations', 'operation-focused': collocationContrastFocused }"
          :disabled="!canStartCollocationContrastJob"
          :title="collocationContrastJobBlockReason ?? t('analysis.freeContrast.collocationKindTitle')"
          @click="selectAnalysisKind('collocations')"
        >
          <strong>{{ t('analysis.freeContrast.collocationKind') }}</strong>
          <span>{{ t('analysis.freeContrast.collocationKindDescription') }}</span>
        </button>
      </section>

      <div class="fc-groups">
        <!-- Group A -->
        <fieldset class="fc-group">
          <legend>{{ t('analysis.freeContrast.groupA') }}</legend>
          <label class="fc-mode">
            <input v-model="groupA.mode" type="radio" value="field" @change="resetResults" />
            {{ t('analysis.freeContrast.metadataField') }}
          </label>
          <label class="fc-mode" :class="{ disabled: !subcorporaForCorpus.length }">
            <input
              v-model="groupA.mode"
              type="radio"
              value="subcorpus"
              :disabled="!subcorporaForCorpus.length"
              @change="resetResults"
            />
            {{ t('analysis.shared.subcorpus') }}
          </label>

          <template v-if="groupA.mode === 'field'">
            <select
              v-model="groupA.field"
              class="fc-select"
              :aria-label="t('analysis.freeContrast.fieldA')"
              @change="onFieldChange(groupA)"
            >
              <option value="">{{ t('analysis.freeContrast.pickField') }}</option>
              <option v-for="f in metaFields" :key="`a-${f}`" :value="f">{{ f }}</option>
            </select>
            <select
              v-model="groupA.value"
              class="fc-select"
              :aria-label="t('analysis.freeContrast.valueA')"
              :disabled="!groupA.field"
              @change="resetResults"
            >
              <option value="">{{ t('analysis.freeContrast.pickValue') }}</option>
              <option v-for="v in valuesByField[groupA.field] ?? []" :key="`av-${v}`" :value="v">
                {{ v }}
              </option>
            </select>
          </template>
          <template v-else>
            <select
              v-model="groupA.subcorpus"
              class="fc-select"
              :aria-label="t('analysis.freeContrast.subcorpusA')"
              @change="resetResults"
            >
              <option value="">{{ t('analysis.freeContrast.pickSubcorpus') }}</option>
              <option v-for="s in subcorporaForCorpus" :key="`as-${s.name}`" :value="s.name">
                {{ s.name }}
              </option>
            </select>
          </template>
        </fieldset>

        <ArrowRight class="fc-vs" aria-hidden="true" />

        <!-- Group B -->
        <fieldset class="fc-group">
          <legend>{{ t('analysis.freeContrast.groupB') }}</legend>
          <label class="fc-mode">
            <input v-model="groupB.mode" type="radio" value="field" @change="resetResults" />
            {{ t('analysis.freeContrast.metadataField') }}
          </label>
          <label class="fc-mode" :class="{ disabled: !subcorporaForCorpus.length }">
            <input
              v-model="groupB.mode"
              type="radio"
              value="subcorpus"
              :disabled="!subcorporaForCorpus.length"
              @change="resetResults"
            />
            {{ t('analysis.shared.subcorpus') }}
          </label>

          <template v-if="groupB.mode === 'field'">
            <select
              v-model="groupB.field"
              class="fc-select"
              :aria-label="t('analysis.freeContrast.fieldB')"
              @change="onFieldChange(groupB)"
            >
              <option value="">{{ t('analysis.freeContrast.pickField') }}</option>
              <option v-for="f in metaFields" :key="`b-${f}`" :value="f">{{ f }}</option>
            </select>
            <select
              v-model="groupB.value"
              class="fc-select"
              :aria-label="t('analysis.freeContrast.valueB')"
              :disabled="!groupB.field"
              @change="resetResults"
            >
              <option value="">{{ t('analysis.freeContrast.pickValue') }}</option>
              <option v-for="v in valuesByField[groupB.field] ?? []" :key="`bv-${v}`" :value="v">
                {{ v }}
              </option>
            </select>
          </template>
          <template v-else>
            <select
              v-model="groupB.subcorpus"
              class="fc-select"
              :aria-label="t('analysis.freeContrast.subcorpusB')"
              @change="resetResults"
            >
              <option value="">{{ t('analysis.freeContrast.pickSubcorpus') }}</option>
              <option v-for="s in subcorporaForCorpus" :key="`bs-${s.name}`" :value="s.name">
                {{ s.name }}
              </option>
            </select>
          </template>
        </fieldset>
      </div>
      <p v-if="highCardinalityMetaFields.length" class="fc-hint">
        {{ t('analysis.freeContrast.highCardinality', { fields: highCardinalityMetaFields.join(', ') }) }}
      </p>

      <div class="fc-params">
        <label>
          {{ t('analysis.freeContrast.window') }}
          <input
            v-model.number="windowSize"
            type="number"
            min="1"
            max="25"
            class="fc-number"
            @change="resetResults"
          />
        </label>
        <label>
          {{ t('analysis.freeContrast.sort') }}
          <select v-model="sortBy" class="fc-select fc-select--compact" @change="resetResults">
            <option value="logdice">logDice</option>
            <option value="mi">MI</option>
            <option value="lmi">LMI</option>
            <option value="npmi">NPMI</option>
            <option value="z">{{ t('analysis.measureOptions.zScore') }}</option>
            <option value="t">{{ t('analysis.measureOptions.tScore') }}</option>
            <option value="ll">{{ t('analysis.measureOptions.logLikelihood') }}</option>
            <option value="f">{{ t('analysis.freeContrast.frequency') }}</option>
          </select>
        </label>
        <label class="fc-checkbox">
          <input v-model="withinSentence" type="checkbox" @change="resetResults" />
          {{ t('analysis.freeContrast.withinSentence') }}
        </label>
      </div>

      <div class="fc-actions">
        <Button
          variant="primary"
          size="sm"
          :icon="Scale"
          :loading="isRunning"
          :disabled="!canRun"
          @click="run"
        >
          {{ t('analysis.freeContrast.compute') }}
        </Button>
        <span v-if="!term" class="fc-hint">{{ t('analysis.freeContrast.needSearch') }}</span>
        <span v-else-if="activeOperationBlockReason" class="fc-hint">{{ activeOperationBlockReason }}</span>
        <span v-else-if="!canRun" class="fc-hint">{{ t('analysis.freeContrast.needTwoGroups') }}</span>
      </div>

      <CapabilityBoundaryPanel
        capability-id="analysis.contrast"
        :method="contrastMethod"
        class="fc-method"
      />

      <div v-if="runError" class="fc-error">
        {{ runError }}
        <Button variant="ghost" size="sm" :icon="RefreshCw" @click="run">{{ t('analysis.freeContrast.again') }}</Button>
      </div>

      <div
        v-if="resolvedDiversityComparison && canUseLexicalDiversity && !runError"
        class="fc-diversity"
        :class="{ 'operation-focused': lexicalDiversityFocused }"
      >
        <LexicalDiversityCard
          :corpus="activeCorpus"
          :target-docset-id="resolvedDiversityComparison.targetDocsetId"
          :reference-docset-id="resolvedDiversityComparison.referenceDocsetId"
          :target-label="resolvedDiversityComparison.targetLabel"
          :reference-label="resolvedDiversityComparison.referenceLabel"
          :auto-load="true"
        />
      </div>

      <div v-if="!runError && rows.length" class="fc-results">
        <div class="fc-results-head">
          <span class="fc-result-kind">
            {{ analysisKind === 'collocations' ? t('analysis.freeContrast.collocationKind') : t('analysis.contrast.free') }}
          </span>
          <span class="fc-result-method">{{ t('analysis.freeContrast.ranking', { score: visibleScoreLabel, top: TOP_N }) }}</span>
          <span class="fc-grp-a">{{ groupLabel(groupA) }}</span>
          <span class="fc-vs-label">{{ t('analysis.freeContrast.vs') }}</span>
          <span class="fc-grp-b">{{ groupLabel(groupB) }}</span>
        </div>
        <div v-if="truncated" class="fc-truncated" role="status">
          {{ totalResults ? t('analysis.freeContrast.truncatedOf', { top: rows.length, total: formatNumber(totalResults) }) : t('analysis.freeContrast.truncated', { top: rows.length }) }}
        </div>
        <table class="fc-table">
          <thead>
            <tr>
              <th>{{ t('analysis.freeContrast.word') }}</th>
              <th v-if="hasScoreColumns" class="num" :title="t('analysis.freeContrast.scoreInTarget', { score: visibleScoreLabel })">
                A {{ visibleScoreLabel }}
              </th>
              <th v-if="hasScoreColumns" class="num" :title="t('analysis.freeContrast.scoreInReference', { score: visibleScoreLabel })">
                B {{ visibleScoreLabel }}
              </th>
              <th v-if="hasScoreColumns" class="num" :title="t('analysis.freeContrast.scoreDiffTitle')">
                Δ Score
              </th>
              <th class="num">{{ t('analysis.freeContrast.aPerMillion') }}</th>
              <th class="num">{{ t('analysis.freeContrast.bPerMillion') }}</th>
              <th class="num">{{ t('analysis.freeContrast.deltaPerMillion') }}</th>
              <th class="num" :title="t('analysis.freeContrast.logRatioTitle')">{{ t('analysis.freeContrast.logRatio') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="`fc-${row.word}`">
              <td class="word">{{ row.word }}</td>
              <td v-if="hasScoreColumns" class="num">{{ formatScore(row.targetScore) }}</td>
              <td v-if="hasScoreColumns" class="num">{{ formatScore(row.referenceScore) }}</td>
              <td v-if="hasScoreColumns" class="num">{{ formatScore(row.diffScore) }}</td>
              <td class="num">
                <button
                  type="button"
                  class="fc-side-link"
                  data-testid="contrast-open-target"
                  :disabled="!row.targetFreq"
                  :title="sideTitle(row, 'target')"
                  :aria-label="sideTitle(row, 'target')"
                  @click="openSideConcordance(row, 'target')"
                >
                  {{ formatPerMillion(row.targetPerMillion) }}
                </button>
              </td>
              <td class="num">
                <button
                  type="button"
                  class="fc-side-link"
                  data-testid="contrast-open-reference"
                  :disabled="!row.referenceFreq"
                  :title="sideTitle(row, 'reference')"
                  :aria-label="sideTitle(row, 'reference')"
                  @click="openSideConcordance(row, 'reference')"
                >
                  {{ formatPerMillion(row.referencePerMillion) }}
                </button>
              </td>
              <td
                class="num delta"
                :class="{ positive: row.diffPerMillion >= 0, negative: row.diffPerMillion < 0 }"
              >
                {{ formatPerMillion(row.diffPerMillion) }}
              </td>
              <td class="num">
                <span v-if="row.oneSided" class="fc-one-sided" :title="t('analysis.freeContrast.oneSidedTitle')">
                  {{ t('analysis.freeContrast.oneSided') }}
                </span>
                <span v-else>{{ formatLogRatio(row.logRatio) }}</span>
              </td>
            </tr>
          </tbody>
        </table>
        <i18n-t keypath="analysis.freeContrast.legend" tag="p" class="fc-legend" scope="global">
          <template #logRatio><strong>{{ t('analysis.freeContrast.logRatio') }}</strong></template>
        </i18n-t>

      </div>

      <div v-else-if="!runError && lastRunAt" class="fc-empty">{{ t('analysis.freeContrast.empty') }}</div>
    </template>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.free-contrast {
  @apply flex flex-col gap-4 p-4;
}

.fc-title {
  @apply flex items-center gap-2 font-semibold text-neutral-800 dark:text-neutral-100;
}

.fc-sub {
  @apply mt-1 text-sm text-neutral-500 dark:text-neutral-400;
}

.fc-loading {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.fc-error {
  @apply flex items-center gap-3 text-sm text-error-600 dark:text-error-400;
}

.fc-diversity {
  @apply mt-1;
}

.fc-diversity.operation-focused,
.fc-kind.operation-focused {
  @apply ring-2 ring-amber-300 ring-offset-2 ring-offset-white;
  @apply dark:ring-amber-500/80 dark:ring-offset-neutral-950;
}

.fc-analysis-kind {
  @apply grid gap-3 md:grid-cols-2;
}

.fc-kind {
  @apply text-left p-3 rounded-lg border transition-colors;
  @apply border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
}

.fc-kind.active {
  @apply border-primary-400 bg-primary-50 text-primary-900;
  @apply dark:border-primary-500 dark:bg-primary-900/30 dark:text-primary-100;
}

.fc-kind:disabled {
  @apply opacity-50 cursor-not-allowed;
}

.fc-kind strong {
  @apply block text-sm font-semibold;
}

.fc-kind span {
  @apply mt-1 block text-xs text-neutral-500 dark:text-neutral-400;
}

.fc-groups {
  @apply flex items-stretch gap-4 flex-wrap;
}

.fc-group {
  @apply flex flex-col gap-2 p-3 rounded-lg flex-1 min-w-[14rem];
  @apply border border-neutral-200 dark:border-neutral-700;
}

.fc-group legend {
  @apply px-1 text-xs font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.fc-mode {
  @apply flex items-center gap-2 text-sm text-neutral-700 dark:text-neutral-200;
}

.fc-mode.disabled {
  @apply opacity-50;
}

.fc-select {
  @apply w-full px-2 py-1.5 rounded-md text-sm;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-800 dark:text-neutral-100;
}

.fc-select--compact {
  @apply w-auto min-w-[10rem];
}

.fc-params {
  @apply flex flex-wrap items-center gap-4 text-sm text-neutral-600 dark:text-neutral-300;
}

.fc-params label {
  @apply flex items-center gap-2;
}

.fc-number {
  @apply w-20 px-2 py-1.5 rounded-md text-sm;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-800 dark:text-neutral-100;
}

.fc-checkbox {
  @apply font-medium;
}

.fc-vs {
  @apply self-center w-5 h-5 text-neutral-400;
}

.fc-actions {
  @apply flex items-center gap-3;
}

.fc-hint {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.fc-results-head {
  @apply flex flex-wrap items-center gap-2 mb-2 text-sm font-medium;
}

.fc-result-kind {
  @apply px-2 py-0.5 rounded-full text-xs font-semibold;
  @apply bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300;
}

.fc-result-method {
  @apply px-2 py-0.5 rounded-full text-xs font-semibold;
  @apply bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300;
}

.fc-grp-a {
  @apply text-primary-600 dark:text-primary-400;
}

.fc-grp-b {
  @apply text-neutral-600 dark:text-neutral-300;
}

.fc-vs-label {
  @apply text-neutral-400;
}

.fc-table {
  @apply w-full text-sm border-collapse;
}

.fc-table th,
.fc-table td {
  @apply px-3 py-1.5 border-b border-neutral-100 dark:border-neutral-800 text-left;
}

.fc-table th.num,
.fc-table td.num {
  @apply text-right tabular-nums;
}

.fc-table .word {
  @apply font-medium text-neutral-800 dark:text-neutral-100;
}

.fc-table .delta.positive {
  @apply text-success-600 dark:text-success-400;
}

.fc-table .delta.negative {
  @apply text-error-600 dark:text-error-400;
}

.fc-empty {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.fc-truncated {
  @apply mb-2 px-2 py-1 rounded-md text-xs font-medium;
  @apply bg-amber-50 text-amber-800 border border-amber-200;
  @apply dark:bg-amber-950/30 dark:text-amber-200 dark:border-amber-800;
}

.fc-one-sided {
  @apply text-xs italic text-neutral-500 dark:text-neutral-400;
}

.fc-legend {
  @apply mt-2 text-xs text-neutral-500 dark:text-neutral-400;
}

.fc-method {
  @apply mt-3;
}

.fc-side-link {
  @apply tabular-nums underline decoration-dotted underline-offset-2;
  @apply text-primary-700 dark:text-primary-300 rounded px-0.5;
  @apply hover:bg-primary-50 dark:hover:bg-primary-900/30;
  @apply focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500;
}

.fc-side-link:disabled {
  @apply no-underline text-neutral-500 dark:text-neutral-400 cursor-default hover:bg-transparent;
}
</style>
