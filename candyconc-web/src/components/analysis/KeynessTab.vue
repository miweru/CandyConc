<script setup lang="ts">
/**
 * KeynessTab - Keyness + optional contrast dashboard on shared reference docs
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { ArrowUpDown, Download, Hash, Network, RefreshCw, Scale, Layers, Filter } from 'lucide-vue-next'
import {
  useDocsetStore,
  useQueryStore,
  useUiStore,
  useAnalysisPresetsStore,
  useSubcorporaStore,
  useCorpusCapabilitiesStore,
} from '@/stores'
import type { AnalysisPreset } from '@/stores/analysisPresets'
import { useAnalysisJobsStore } from '@/stores/analysisJobs'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { KEYNESS_OPERATIONS, useKeynessOperations } from '@/composables/useKeynessOperations'
import { useCollocationOperations } from '@/composables/useCollocationOperations'
import { CONTRAST_OPERATIONS, useContrastOperations } from '@/composables/useContrastOperations'
import { FREQUENCY_OPERATIONS, useFrequencyOperations } from '@/composables/useFrequencyOperations'
import { NGRAM_OPERATIONS, useNgramOperations } from '@/composables/useNgramOperations'
import { useParallelOperations } from '@/composables/useParallelOperations'
import Button from '@/components/ui/Button.vue'
import MeasureInfo from '@/components/ui/MeasureInfo.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Modal from '@/components/ui/Modal.vue'
import AlignmentComparison from '@/components/search/AlignmentComparison.vue'
import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import FilterField from '@/components/filters/FilterField.vue'
import { buildCoKwicQuery, coKwicWindowState, mapCoKwicHits } from '@/utils/coKwic'
import {
  alignmentExecutionContractLabel,
  alignmentPairAxesLabel,
  alignmentVariantControlLabel,
} from '@/lib/corpusFeatureOptions'
import { stripCoQueryTerm } from '@/utils/queryTerm'
import { buildCsv as buildHardenedCsv, csvMeta, downloadCsv } from '@/utils/csv'
import { formatDecimal, formatInterval } from '@/i18n/format'
import {
  analysisCompletenessHeaderLines,
  analysisCompletenessNotice,
  completenessStateFromJobRows,
  type AnalysisCompletenessState,
} from './resultState'
import {
  coerceMethodBlock,
  methodStatEntries,
  type AlignmentRefDocResult,
  type AnalysisJobRows,
  type AnalysisJobSnapshot,
  type MethodBlock,
  type KeynessJobParams,
  type ParallelGroup,
} from '@/api/client'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import LexicalDiversityCard from '@/components/analysis/LexicalDiversityCard.vue'
import { actionBus } from '@/actions'
import { formatNumber, formatDate } from '@/i18n/format'
import { isAnchorSide, isVersionSide, pairSideValues, pairSideValuesFromTextTypes, textTypeLabel } from '@/lib/pairSides'
import { useI18n } from 'vue-i18n'

interface KeynessRow {
  word: string
  target_freq?: number
  reference_freq?: number
  target_per_million?: number
  reference_per_million?: number
  diff_per_million?: number
  direction?: 'target' | 'reference' | string
  chi2_cell?: number | null
  /** Full 2x2 Pearson chi-square (df=1) and its signed variant (r7 #2). */
  chi2?: number | null
  chi2_signed?: number | null
  ll: number | null
  chi2_cell_signed?: number
  /** Signed log-likelihood: positive = over-represented in target. Default ordering key. */
  ll_signed?: number
  /** Effect size (log ratio) with its confidence interval. */
  log_ratio?: number | null
  log_ratio_ci_low?: number | null
  log_ratio_ci_high?: number | null
  /** Significance and multiple-comparison correction. */
  p_value?: number | null
  q_value?: number | null
  bic?: number | null
  /** Low-reliability flag (FT-KEYNESS-RESEARCH): expected cell < 5. */
  low_reliability?: boolean | null
  p_method?: string | null
}

interface KeynessVirtualRow {
  virtualRow: { index: number; start: number; end: number }
  row: KeynessRow
}

const KEYNESS_ROW_ESTIMATE_PX = 54
const KEYNESS_FALLBACK_VIRTUAL_ROWS = 80
const KEYNESS_PAGE_SIZE = 500

interface FrequencyDiffRow {
  word: string
  targetFreq: number
  referenceFreq: number
  targetPerMillion: number
  referencePerMillion: number
  diffPerMillion: number
  diffAbs: number
}

interface CollocationDiffRow {
  word: string
  targetFreq: number
  referenceFreq: number
  targetScore: number
  referenceScore: number
  targetPerMillion: number
  referencePerMillion: number
  diffPerMillion: number
  diffScore: number
  diffAbs: number
}

interface NgramDiffRow {
  ngram: string
  targetFreq: number
  referenceFreq: number
  targetPerMillion: number
  referencePerMillion: number
  diffPerMillion: number
  diffAbs: number
}

interface GroupFilters {
  text_type: string
  prompting_method: string
  model: string[]
  register: string[]
  source: string[]
}

type MetaField = 'text_type' | 'prompting_method' | 'model' | 'register' | 'source'

interface ContrastDocset {
  label: string
  docsetId: string
  docCount: number
  tokenCount: number
  refCount: number
  kind: 'group' | 'human'
}

const { t } = useI18n()
const uiStore = useUiStore()
const docsetStore = useDocsetStore()
const queryStore = useQueryStore()
const presetsStore = useAnalysisPresetsStore()
const subcorporaStore = useSubcorporaStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const productCapabilities = useProductCapabilitiesStore()
const analysisJobs = useAnalysisJobsStore()
const { createKeynessAnalysisJob } = useKeynessOperations()
const { loadCollocateKwic } = useCollocationOperations()
const { createCollocationContrastJob } = useContrastOperations()
const { createFrequencyDiffJob } = useFrequencyOperations()
const { createNgramDiffJob } = useNgramOperations()
const {
  canLoadParallelGroups,
  canOpenAlignment,
  parallelGroupsBlockReason,
  alignmentBlockReason,
  loadParallelGroups: requestParallelGroups,
  loadAlignmentRefDoc: requestAlignmentRefDoc,
} = useParallelOperations()

// Parallel explorer + alignment rely on product-level visibility plus the
// explicit per-corpus descriptors for the concrete route.
// The keyness / collocation-diff contrast features work on any corpus.
const canUseParallel = computed(() => canLoadParallelGroups.value)
const parallelPairAxesLabel = computed(() => alignmentPairAxesLabel(corpusCapabilities.activeSummary))
const parallelVariantColumnLabel = computed(() => alignmentVariantControlLabel(corpusCapabilities.activeSummary))
const parallelExecutionContractLabel = computed(() => alignmentExecutionContractLabel(corpusCapabilities.activeSummary))
const canCancelKeynessJob = computed(() => analysisJobs.canCancelJobs)
const cancelKeynessBlockReason = computed(() => analysisJobs.cancelDisabledReason)

const props = withDefaults(defineProps<{ mode?: 'contrast' | 'keyness' }>(), {
  mode: 'contrast',
})

const isContrastMode = computed(() => props.mode === 'contrast')

const GROUP_A = 'A'
const GROUP_B = 'B'
const HUMAN = 'human'

type KeynessMetric = 'll_signed' | 'log_ratio' | 'chi2' | 'chi2_signed' | 'chi2_cell' | 'll'

const metric = ref<KeynessMetric>('ll_signed')
const sortOrder = ref<'desc' | 'asc'>('desc')
const includeHuman = ref(true)

const groupA = ref<GroupFilters>({
  text_type: 'ai',
  prompting_method: '',
  model: [],
  register: [],
  source: [],
})

const groupB = ref<GroupFilters>({
  text_type: 'ai',
  prompting_method: '',
  model: [],
  register: [],
  source: [],
})

const metaOptions = ref<Record<'text_type' | 'prompting_method' | 'model' | 'register' | 'source', string[]>>({
  text_type: [],
  prompting_method: [],
  model: [],
  register: [],
  source: [],
})
const isLoadingOptions = ref(false)
const groupModelOptions = ref<{ A: string[]; B: string[] }>({ A: [], B: [] })
const groupCounts = ref<Record<'A' | 'B', Record<MetaField, Record<string, number>>>>({
  A: { text_type: {}, prompting_method: {}, model: {}, register: {}, source: {} },
  B: { text_type: {}, prompting_method: {}, model: {}, register: {}, source: {} },
})
const groupCountsReady = ref({ A: false, B: false })
let countsRequestId = 0
let countsTimer: number | null = null
let countsAbortController: AbortController | null = null

// The values of the two sides of a pair come from the corpus: anchor and
// version for paired imports from builder revision 2 on, human and ai before
// and in the human/AI research layout.
const pairSides = computed(() => {
  const declared = pairSideValues(corpusCapabilities.activeSummary)
  return declared.anchor === 'anchor' ? declared : pairSideValuesFromTextTypes(metaOptions.value.text_type)
})
const usesAnchorSides = computed(() => pairSides.value.anchor === 'anchor')
const anchorDocsetName = computed(() =>
  usesAnchorSides.value ? t('analysis.keyness.anchor') : t('analysis.keyness.human')
)

const isBuildingIntersection = ref(false)
const intersectionCount = ref(0)
const docsets = ref<ContrastDocset[]>([])
const isDirty = ref(true)
const intersectionError = ref<string | null>(null)
const contrastLastRun = ref<number | null>(null)
const isLoadingContrastDashboard = ref(false)

const isLoadingKeyness = ref(false)
const keynessError = ref<string | null>(null)
const data = ref<KeynessRow[]>([])
const keynessNextOffset = ref(0)
const keynessTotalRows = ref<number | null>(null)
const isLoadingMoreKeyness = ref(false)
const keynessPagingExhausted = ref(false)
const keynessPagingError = ref<string | null>(null)
const keynessTableContainerRef = ref<HTMLDivElement | null>(null)
// F1: server-provided statistical provenance for the keyness result.
const keynessMethod = ref<MethodBlock | null>(null)
const keynessProvenance = ref<{ base: string; meta: string[] } | null>(null)
const keynessCompleteness = ref<AnalysisCompletenessState | null>(null)

// ── External-reference keyness controls (FT-KEYNESS-RESEARCH, r9) ──────
// The reference the target docset is compared against. 'docset' = the chosen
// reference docset in the legacy paired preset; standalone Keyness starts with
// the disjoint remainder of the active corpus as a corpus-agnostic default.
// 'whole' = the active corpus without the target docset; 'corpus' = a second loaded corpus.
// (KEYNESS-02: the 'freqlist' source is gone — no bundled DE list is shipped.)
// min_freq filters low-frequency candidates before the test so FDR-m counts
// only testable items.
type KeynessReferenceSource = 'docset' | 'whole' | 'corpus'
const referenceSource = ref<KeynessReferenceSource>(isContrastMode.value ? 'docset' : 'whole')
const referenceCorpus = ref<string>('')
const keynessMinFreq = ref(5)
const keynessReferenceLimitNote = computed(() => t('analysis.keyness.referenceLimitNote'))
const standaloneReferenceSubcorpusId = ref<string>('')
const standaloneTargetDocset = computed(() =>
  docsetStore.activeDocsetId
    ? {
        docsetId: docsetStore.activeDocsetId,
        label: docsetStore.activeSubcorpusName ?? docsetStore.scopeLabel,
      }
    : null
)
const standaloneReferenceSubcorpora = computed(() =>
  subcorporaStore.parked.filter((snapshot) => snapshot.corpus === activeCorpus.value)
)
const standaloneReferenceSubcorpus = computed(() =>
  standaloneReferenceSubcorpora.value.find((snapshot) => snapshot.id === standaloneReferenceSubcorpusId.value) ?? null
)

const lowReliabilityCount = computed(() =>
  data.value.reduce((acc, row) => (row.low_reliability ? acc + 1 : acc), 0)
)
const keynessCompletenessNotice = computed(() =>
  analysisCompletenessNotice(keynessCompleteness.value, t('analysis.keyness.listLabel'))
)
const frequencyDiffCompletenessNotice = computed(() =>
  analysisCompletenessNotice(frequencyDiffCompleteness.value, t('analysis.keyness.frequencyComparisonLabel'))
)
const frequencyDiffUsesCompleteUnion = computed(() =>
  frequencyDiffMethod.value?.candidate_policy === 'complete_union_before_ranking'
)
const keynessJobSnapshot = ref<AnalysisJobSnapshot | null>(null)
const keynessJobId = ref<string | null>(null)
const sessionPresetId = ref<string | null>(null)
let keynessPollToken = 0

const hasMoreKeynessRows = computed(() => {
  const total = keynessTotalRows.value
  return !keynessPagingExhausted.value
    && typeof total === 'number'
    && keynessNextOffset.value < total
})

const isKeynessJobRunning = computed(() => {
  const status = keynessJobSnapshot.value?.status
  return status === 'running' || status === 'queued'
})

const isLoadingDiffs = ref(false)
const diffError = ref<string | null>(null)
const diffRows = ref<FrequencyDiffRow[]>([])
const frequencyDiffCompleteness = ref<AnalysisCompletenessState | null>(null)
const frequencyDiffMethod = ref<MethodBlock | null>(null)

const collocWindow = ref(5)
const collocWithinSentence = ref(true)
const collocMeasure = ref<'mi' | 'logdice' | 'tscore' | 'lmi' | 'npmi' | 'z'>('logdice')
const collocLimit = ref(200)
const isLoadingCollocDiffs = ref(false)
const collocDiffError = ref<string | null>(null)
const collocDiffRows = ref<CollocationDiffRow[]>([])
// B6: ohne diesen Block faellt MeasureInfo dauerhaft auf den statischen
// Katalog zurueck, und der spiegelt METHOD_META, also die STANDARDFORM.
// Im Kollokations-Kontrast gilt der Paar-Ereignisraum. Der Job liefert den
// Block, /jobs/{id}/rows reicht ihn durch, der Tab warf ihn weg.
const collocDiffMethod = ref<MethodBlock | null>(null)

const ngramSize = ref(2)
const ngramMinFreq = ref(3)
const ngramLimit = ref(300)
const isLoadingNgramDiffs = ref(false)
const ngramDiffError = ref<string | null>(null)
const ngramDiffRows = ref<NgramDiffRow[]>([])

const exportOpen = ref(false)
const exportKeyness = ref(true)
const exportDiffs = ref(true)
const exportCollocs = ref(false)
const exportNgrams = ref(false)
const exportIncludeMeta = ref(true)

const parallelBasisLabel = ref(HUMAN)
const parallelIncludeVariants = ref(true)
const parallelSort = ref<'ref_doc' | 'variant_count'>('variant_count')
const parallelLimit = ref(60)
const parallelOffset = ref(0)
const isLoadingParallel = ref(false)
const parallelError = ref<string | null>(null)
const parallelGroups = ref<ParallelGroup[]>([])
const parallelTotal = ref(0)

const isParallelModalOpen = ref(false)
const parallelAlignmentResult = ref<AlignmentRefDocResult | null>(null)
const parallelAlignmentError = ref<string | null>(null)
const isLoadingParallelAlignment = ref(false)

const targetLabel = ref(GROUP_A)
const referenceLabel = ref(HUMAN)

const activeCorpus = computed(() => docsetStore.activeCorpus)
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
        query: docsetStore.activeDocsetOrigin?.kind === 'search' ? docsetStore.activeDocsetOrigin.query : undefined,
      }
    : null
)

// Save the inputs of the displayed result, even after its controls are edited.
const keynessRunInputs = ref<Pick<AnalysisPreset, 'corpus' | 'docset' | 'queryTerm' | 'params'> | null>(null)
const keynessInputs = computed(() => keynessRunInputs.value ?? {
  corpus: activeCorpus.value,
  docset: docsetSnapshot.value,
  queryTerm: queryStore.term,
  params: {
    metric: metric.value, sortOrder: sortOrder.value, includeHuman: includeHuman.value,
    groupA: groupA.value, groupB: groupB.value,
    targetLabel: targetLabel.value, referenceLabel: referenceLabel.value,
    collocWindow: collocWindow.value, collocWithinSentence: collocWithinSentence.value,
    collocMeasure: collocMeasure.value, ngramSize: ngramSize.value, ngramMinFreq: ngramMinFreq.value,
    referenceSource: referenceSource.value, referenceCorpus: referenceCorpus.value,
    keynessMinFreq: keynessMinFreq.value, standaloneReferenceSubcorpusId: standaloneReferenceSubcorpusId.value,
  },
})

const DIFF_TOP_N = 30
let persistResultTimer: number | null = null
let persistResultInFlight = false
let persistResultQueued = false

async function flushPersistKeynessResult() {
  if (!sessionPresetId.value) return
  const inputs = keynessInputs.value
  const cacheKey = await presetsStore.buildCacheKey({ type: 'keyness', ...inputs })
  await presetsStore.updateResult(
    sessionPresetId.value,
    {
      keynessRows: data.value,
      keynessProvenance: keynessProvenance.value,
      keynessMethod: keynessMethod.value,
      diffRows: diffRows.value,
      collocDiffRows: collocDiffRows.value,
      ngramDiffRows: ngramDiffRows.value,
    },
    {
      corpus: inputs.corpus,
      docsetId: inputs.docset?.docsetId ?? null,
      queryTerm: inputs.queryTerm,
      ...inputs.params,
      docCount: inputs.docset?.stats.docCount,
      tokenCount: inputs.docset?.stats.tokenCount,
      cacheKey,
      cacheVersion: presetsStore.cacheVersion,
      generatedAt: Date.now(),
    }
  )
}

function persistKeynessResult(delay = 250) {
  if (!sessionPresetId.value) return
  persistResultQueued = true
  if (persistResultTimer !== null) {
    window.clearTimeout(persistResultTimer)
  }
  persistResultTimer = window.setTimeout(() => {
    persistResultTimer = null
    void (async () => {
      if (persistResultInFlight) return
      if (!persistResultQueued) return
      persistResultQueued = false
      persistResultInFlight = true
      try {
        await flushPersistKeynessResult()
      } catch {
        persistResultQueued = true
      } finally {
        persistResultInFlight = false
        if (persistResultQueued && sessionPresetId.value) {
          persistKeynessResult(1000)
        }
      }
    })()
  }, delay)
}
const docsetByLabel = computed(() => {
  const map = new Map<string, ContrastDocset>()
  for (const d of docsets.value) map.set(d.label, d)
  return map
})

const docsetOptions = computed(() =>
  docsets.value.map((d) => ({
    label: d.label,
    title:
      d.kind === 'human'
        ? (usesAnchorSides.value ? t('analysis.keyness.anchorReferences') : t('analysis.keyness.humanReferences'))
        : t('analysis.keyness.groupNamed', { label: d.label }),
  }))
)

const hasIntersection = computed(() => docsets.value.length > 0 && intersectionCount.value > 0)
const intersectionReady = computed(() => hasIntersection.value && !isDirty.value)
const contrastReady = computed(() => contrastLastRun.value !== null && !isDirty.value)

const targetDocset = computed(() => docsetByLabel.value.get(targetLabel.value))
const referenceDocset = computed(() => docsetByLabel.value.get(referenceLabel.value))
const parallelBasisDocsetId = computed(() => docsetByLabel.value.get(parallelBasisLabel.value)?.docsetId)

// F4: resolved docset ids for the lexical-diversity card (Human-vs-AI sides).
const diversityTargetDocsetId = computed(() => targetDocset.value?.docsetId ?? null)
const diversityReferenceDocsetId = computed(() => referenceDocset.value?.docsetId ?? null)
const hasDiversitySides = computed(
  () =>
    !!diversityTargetDocsetId.value &&
    !!diversityReferenceDocsetId.value &&
    diversityTargetDocsetId.value !== diversityReferenceDocsetId.value
)

function shortId(id: string): string {
  return id.slice(0, 8)
}

function formatPerMillion(value: number): string {
  return formatNumber(value, {
    maximumFractionDigits: 1,
  })
}

function formatPercent(value: number): string {
  const sign = value > 0 ? '+' : ''
  return `${sign}${formatDecimal(value, 1)}%`
}

function perMillion(freq: number, tokenCount: number): number {
  const denom = tokenCount > 0 ? tokenCount : 1
  return (freq / denom) * 1_000_000
}

function sanitizeFilename(value: string): string {
  return value.replace(/[^a-z0-9-_]+/gi, '_').replace(/_{2,}/g, '_').replace(/^_+|_+$/g, '')
}

/**
 * Serialize the server `method` provenance block into CSV comment lines (F1).
 * Returns an empty list when no method block is available so the export never
 * falls back to stale, hand-maintained formulas.
 */
function methodBlockToCsvLines(label: string, method: MethodBlock | null): string[] {
  if (!method) return []
  const lines: string[] = [`# ${t('analysis.keyness.csvMethodHeader', { label })}`]
  for (const stat of methodStatEntries(method)) {
    const name = typeof stat?.name === 'string' && stat.name ? stat.name : stat.key
    const formula = typeof stat?.latex_formula === 'string' ? ` = ${stat.latex_formula}` : ''
    const smoothing = typeof stat?.smoothing === 'string' ? ` ${t('analysis.keyness.csvSmoothing', { smoothing: stat.smoothing })}` : ''
    lines.push(`# ${name}${formula}${smoothing}`)
  }
  if (typeof method.target_total === 'number') lines.push(`# target_total: ${method.target_total}`)
  if (typeof method.reference_total === 'number') lines.push(`# reference_total: ${method.reference_total}`)
  if (typeof method.window === 'number') lines.push(`# window: ${method.window}`)
  if (typeof method.within_sentence === 'boolean') lines.push(`# within_sentence: ${method.within_sentence}`)
  const fp = method.indexFingerprint ?? method.index_fingerprint
  if (fp) lines.push(`# indexFingerprint: ${fp}`)
  return lines
}

function frequencyDiffCompletenessHeaderLines(): string[] {
  const policy = frequencyDiffMethod.value?.candidate_policy
  return [
    '# FrequencyDiff.basis: complete_vocabulary_union_before_ranking',
    ...(typeof policy === 'string' ? [`# FrequencyDiff.candidate_policy: ${policy}`] : []),
    ...analysisCompletenessHeaderLines(frequencyDiffCompleteness.value, 'FrequencyDiff'),
  ]
}

function buildCsv(headers: string[], rows: Array<Array<string | number | null | undefined>>): string {
  return buildCsvWithMeta([], headers, rows)
}

function buildCsvWithMeta(
  meta: string[],
  headers: string[],
  rows: Array<Array<string | number | null | undefined>>
): string {
  return buildHardenedCsv({ meta, headers, rows })
}

function downloadCsvFile(filename: string, content: string) {
  downloadCsv(content, filename)
}

function contrastFilters(label: string): GroupFilters {
  return label === GROUP_A ? groupA.value : label === GROUP_B ? groupB.value
    : { text_type: pairSides.value.anchor, prompting_method: '', model: [], register: [], source: [] }
}

function exportCsv() {
  const base = sanitizeFilename(`${activeCorpus.value}_${targetLabel.value}_vs_${referenceLabel.value}`)
  const date = new Date().toISOString().slice(0, 10)
  const docsets = getContrastDocsets()
  const targetStats = docsets?.target
  const referenceStats = docsets?.reference

  const targetFilters = contrastFilters(targetLabel.value)
  const referenceFilters = contrastFilters(referenceLabel.value)

  const filterLines = [
    `# TargetFilters.text_type: ${targetFilters.text_type}`,
    `# TargetFilters.prompting_method: ${targetFilters.prompting_method || 'all'}`,
    `# TargetFilters.model: ${targetFilters.model.length ? targetFilters.model.join(' | ') : 'all'}`,
    `# TargetFilters.register: ${targetFilters.register.length ? targetFilters.register.join(' | ') : 'all'}`,
    `# TargetFilters.source: ${targetFilters.source.length ? targetFilters.source.join(' | ') : 'all'}`,
    `# ReferenceFilters.text_type: ${referenceFilters.text_type}`,
    `# ReferenceFilters.prompting_method: ${referenceFilters.prompting_method || 'all'}`,
    `# ReferenceFilters.model: ${referenceFilters.model.length ? referenceFilters.model.join(' | ') : 'all'}`,
    `# ReferenceFilters.register: ${referenceFilters.register.length ? referenceFilters.register.join(' | ') : 'all'}`,
    `# ReferenceFilters.source: ${referenceFilters.source.length ? referenceFilters.source.join(' | ') : 'all'}`,
  ]

  // F1: emit statistical provenance from the SERVER `method` block (single
  // source of truth) instead of hand-maintained formula strings. Falls back to
  // an empty list when the backend has not supplied a method block yet.
  const keynessFormulaLines = methodBlockToCsvLines('Keyness', keynessMethod.value)
  const diffFormulaLines = methodBlockToCsvLines(t('analysis.keyness.frequencyDiffs'), frequencyDiffMethod.value)
  const collocFormulaLines: string[] = []
  const metaBase = exportIncludeMeta.value
    ? [
        '# CandyConc Export',
        '# Analysis: Contrast/Keyness',
        `# Corpus: ${activeCorpus.value}`,
        `# Target: ${targetLabel.value}`,
        `# Reference: ${referenceLabel.value}`,
        `# TargetDocset: ${docsets?.target.docsetId ?? 'n/a'}`,
        `# ReferenceDocset: ${docsets?.reference.docsetId ?? 'n/a'}`,
        `# TargetDocs: ${targetStats?.docCount ?? 'n/a'}`,
        `# TargetTokens: ${targetStats?.tokenCount ?? 'n/a'}`,
        `# ReferenceDocs: ${referenceStats?.docCount ?? 'n/a'}`,
        `# ReferenceTokens: ${referenceStats?.tokenCount ?? 'n/a'}`,
        ...filterLines,
        `# Exported: ${new Date().toISOString()}`,
      ]
    : []

  const exports: Array<{ name: string; content: string }> = []

  if (exportKeyness.value && data.value.length) {
    const keynessHeaders = [
      'word',
      'll_signed',
      'log_ratio',
      'log_ratio_ci_low',
      'log_ratio_ci_high',
      'chi2_cell',
      'll',
      'p_value',
      'q_value',
      'bic',
      'direction',
      'diff_per_million',
      'target_freq',
      'reference_freq',
    ]
    const rows = data.value.map((row) => [
      row.word,
      row.ll_signed ?? llSignedValue(row),
      row.log_ratio ?? '',
      row.log_ratio_ci_low ?? '',
      row.log_ratio_ci_high ?? '',
      chi2CellValue(row),
      row.ll,
      row.p_value ?? '',
      row.q_value ?? '',
      row.bic ?? '',
      row.direction ?? '',
      row.diff_per_million ?? '',
      row.target_freq ?? '',
      row.reference_freq ?? '',
    ])
    exports.push({
      name: `keyness_${keynessProvenance.value?.base ?? "result"}_${date}.csv`,
      content: exportIncludeMeta.value
        ? buildCsvWithMeta(
            [
              '# CandyConc Export',
              '# Analysis: Contrast/Keyness',
              ...(keynessProvenance.value?.meta ?? []),
              csvMeta('Exported', new Date().toISOString()),
              ...keynessFormulaLines,
              ...analysisCompletenessHeaderLines(keynessCompleteness.value, 'KeynessResult'),
            ],
            keynessHeaders,
            rows,
          )
        : buildCsv(keynessHeaders, rows),
    })
  }

  if (exportDiffs.value && diffRows.value.length) {
    const rows = diffRows.value.map((row) => [
      row.word,
      row.targetFreq,
      row.referenceFreq,
      row.targetPerMillion,
      row.referencePerMillion,
      row.diffPerMillion,
      row.diffAbs,
    ])
    exports.push({
      name: `freq_diff_${base}_${date}.csv`,
      content: exportIncludeMeta.value
        ? buildCsvWithMeta(
            [
              ...metaBase,
              `# Diff: Frequency`,
              ...frequencyDiffCompletenessHeaderLines(),
              ...diffFormulaLines,
            ],
            [
              'word',
              'targetFreq',
              'referenceFreq',
              'targetPerMillion',
              'referencePerMillion',
              'diffPerMillion',
              'diffAbs',
            ],
            rows
          )
        : buildCsv(
            [
              'word',
              'targetFreq',
              'referenceFreq',
              'targetPerMillion',
              'referencePerMillion',
              'diffPerMillion',
              'diffAbs',
            ],
            rows
          ),
    })
  }

  if (exportCollocs.value && collocDiffRows.value.length) {
    const rows = collocDiffRows.value.map((row) => [
      row.word,
      row.targetFreq,
      row.referenceFreq,
      row.targetScore,
      row.referenceScore,
      row.targetPerMillion,
      row.referencePerMillion,
      row.diffPerMillion,
      row.diffScore,
      row.diffAbs,
    ])
    exports.push({
      name: `colloc_diff_${base}_${date}.csv`,
      content: exportIncludeMeta.value
        ? buildCsvWithMeta(
            [
              ...metaBase,
              `# Diff: Collocations`,
              `# Window: ${collocWindow.value}`,
              `# WithinSentence: ${collocWithinSentence.value}`,
              `# Measure: ${collocMeasure.value}`,
              ...diffFormulaLines,
              ...collocFormulaLines,
            ],
            [
              'word',
              'targetFreq',
              'referenceFreq',
              'targetScore',
              'referenceScore',
              'targetPerMillion',
              'referencePerMillion',
              'diffPerMillion',
              'diffScore',
              'diffAbs',
            ],
            rows
          )
        : buildCsv(
            [
              'word',
              'targetFreq',
              'referenceFreq',
              'targetScore',
              'referenceScore',
              'targetPerMillion',
              'referencePerMillion',
              'diffPerMillion',
              'diffScore',
              'diffAbs',
            ],
            rows
          ),
    })
  }

  if (exportNgrams.value && ngramDiffRows.value.length) {
    const rows = ngramDiffRows.value.map((row) => [
      row.ngram,
      row.targetFreq,
      row.referenceFreq,
      row.targetPerMillion,
      row.referencePerMillion,
      row.diffPerMillion,
      row.diffAbs,
    ])
    exports.push({
      name: `ngram_diff_${base}_${date}.csv`,
      content: exportIncludeMeta.value
        ? buildCsvWithMeta(
            [
              ...metaBase,
              `# Diff: Ngrams`,
              `# N: ${ngramSize.value}`,
              `# MinFreq: ${ngramMinFreq.value}`,
              ...diffFormulaLines,
            ],
            [
              'ngram',
              'targetFreq',
              'referenceFreq',
              'targetPerMillion',
              'referencePerMillion',
              'diffPerMillion',
              'diffAbs',
            ],
            rows
          )
        : buildCsv(
            [
              'ngram',
              'targetFreq',
              'referenceFreq',
              'targetPerMillion',
              'referencePerMillion',
              'diffPerMillion',
              'diffAbs',
            ],
            rows
          ),
    })
  }

  if (!exports.length) {
    uiStore.showToast(t('analysis.keyness.noCsvData'), 'warning')
    return
  }

  for (const item of exports) {
    downloadCsvFile(item.name, item.content)
  }
  exportOpen.value = false
  uiStore.showToast(t('analysis.keyness.csvExported'), 'success', 2000)
}

function formatParallelVariantCounts(models: ParallelGroup['models']): string {
  if (!models || models.length === 0) return '–'
  return models
    .slice(0, 3)
    .map((m) => `${m.label || m.axis_value || m.model || t('analysis.keyness.variant')} (${m.count})`)
    .join(', ')
}

function formatSources(sources: string[]): string {
  if (!sources || sources.length === 0) return '–'
  return sources.slice(0, 3).join(', ')
}

const contrastStats = computed(() => {
  const target = targetDocset.value
  const reference = referenceDocset.value
  if (!target || !reference) return null
  const docDiff = target.docCount - reference.docCount
  const docBase = reference.docCount || 1
  const docDiffPct = (docDiff / docBase) * 100
  const tokenDiff = target.tokenCount - reference.tokenCount
  const tokenBase = reference.tokenCount || 1
  const tokenDiffPct = (tokenDiff / tokenBase) * 100
  return {
    intersectionCount: intersectionCount.value,
    targetDocs: target.docCount,
    referenceDocs: reference.docCount,
    docDiff,
    docDiffPct,
    targetTokens: target.tokenCount,
    referenceTokens: reference.tokenCount,
    tokenDiff,
    tokenDiffPct,
  }
})

function groupFiltersPayload(group: GroupFilters): Record<string, string | string[]> {
  const filters: Record<string, string | string[]> = {}
  if (group.text_type) filters.text_type = group.text_type
  if (group.prompting_method) filters.prompting_method = group.prompting_method
  if (group.model.length) filters.model = [...group.model]
  if (group.register.length) filters.register = [...group.register]
  if (group.source.length) filters.source = [...group.source]
  return filters
}

function buildCountFilters(group: GroupFilters, exclude?: MetaField): Record<string, string | string[]> | undefined {
  const filters: Record<string, string | string[]> = {}
  if (group.text_type && exclude !== 'text_type') filters.text_type = group.text_type
  if (group.prompting_method && exclude !== 'prompting_method') filters.prompting_method = group.prompting_method
  if (group.model.length && exclude !== 'model') filters.model = [...group.model]
  if (group.register.length && exclude !== 'register') filters.register = [...group.register]
  if (group.source.length && exclude !== 'source') filters.source = [...group.source]
  return Object.keys(filters).length ? filters : undefined
}

function optionCount(group: 'A' | 'B', field: MetaField, value: string): number | null {
  if (!groupCountsReady.value[group]) return null
  const counts = groupCounts.value[group][field]
  if (!counts) return null
  return counts[value] ?? 0
}

function scheduleCountsRefresh() {
  if (countsTimer !== null) {
    window.clearTimeout(countsTimer)
  }
  countsTimer = window.setTimeout(() => {
    countsTimer = null
    void refreshGroupCounts()
  }, 120)
}

async function fetchCountsForGroup(
  group: GroupFilters,
  signal?: AbortSignal
): Promise<Record<MetaField, Record<string, number>>> {
  const result: Record<MetaField, Record<string, number>> = {
    text_type: {},
    prompting_method: {},
    model: {},
    register: {},
    source: {},
  }
  const fields: MetaField[] = ['text_type', 'prompting_method', 'model', 'register', 'source']
  for (const field of fields) {
    const response = await docsetStore.fetchMetaCounts({
      fields: [field],
      corpus: activeCorpus.value,
      filters: buildCountFilters(group, field),
    }, { signal })
    if (!response) return result
    result[field] = response[field] ?? {}
  }
  return result
}

async function refreshGroupCounts() {
  if (isLoadingOptions.value) return
  const requestId = ++countsRequestId
  countsAbortController?.abort()
  countsAbortController = new AbortController()
  groupCountsReady.value = { A: false, B: false }
  try {
    const [aCounts, bCounts] = await Promise.all([
      fetchCountsForGroup(groupA.value, countsAbortController.signal),
      fetchCountsForGroup(groupB.value, countsAbortController.signal),
    ])
    if (requestId !== countsRequestId) return
    groupCounts.value = { A: aCounts, B: bCounts }
    groupCountsReady.value = { A: true, B: true }
  } catch (err) {
    if (requestId !== countsRequestId) return
    if (err instanceof DOMException && err.name === 'AbortError') return
    if (err instanceof Error && (err.name === 'TimeoutError' || (err.message ?? '').includes('fetch'))) return
    if (typeof err === 'object' && err !== null && 'name' in err && (err as { name?: string }).name === 'AbortError') return
    console.warn('Meta-Counts konnten nicht geladen werden', err)
  } finally {
    if (requestId === countsRequestId) {
      countsAbortController = null
    }
  }
}

function markDirty() {
  isDirty.value = true
  contrastLastRun.value = null
  scheduleCountsRefresh()
}

function textTypeFlags(textType: string): { includeAi: boolean; includeHuman: boolean } {
  const value = textType?.toLowerCase?.() ?? ''
  if (isAnchorSide(value) || value.includes('human') || value.includes('mensch')) {
    return { includeAi: false, includeHuman: true }
  }
  if (isVersionSide(value) || value.includes('ai') || value.includes('ki')) {
    return { includeAi: true, includeHuman: false }
  }
  return { includeAi: true, includeHuman: true }
}

function buildSnapshotFilters(group: GroupFilters): {
  prompting_method: string[]
  model: string[]
  register: string[]
  source: string[]
} {
  return {
    prompting_method: group.prompting_method ? [group.prompting_method] : [],
    model: [...group.model],
    register: [...group.register],
    source: [...group.source],
  }
}

function saveIntersectionAsSubcorpora() {
  if (!intersectionReady.value) return
  if (!docsets.value.length) return
  if (!subcorporaStore.canSaveSubcorpora) {
    uiStore.showToast(subcorporaStore.saveAvailability.disabledReason ?? t('analysis.keyness.saveSubcorporaNotEnabled'), 'warning')
    return
  }
  const createdAt = formatDate(new Date())
  const scopeLabel = `Intersection ${GROUP_A}/${GROUP_B} · ${createdAt}`
  const groupFilters: Record<string, GroupFilters> = {
    [GROUP_A]: groupA.value,
    [GROUP_B]: groupB.value,
  }

  let savedCount = 0

  for (const d of docsets.value) {
    const isHuman = d.kind === 'human' || d.label === HUMAN
    const filters = isHuman ? buildSnapshotFilters({
      text_type: pairSides.value.anchor,
      prompting_method: '',
      model: [],
      register: [],
      source: [],
    }) : buildSnapshotFilters(groupFilters[d.label] ?? groupA.value)

    const flags = isHuman ? { includeAi: false, includeHuman: true } : textTypeFlags(groupFilters[d.label]?.text_type ?? pairSides.value.version)

    const suggested = subcorporaStore.suggestName({
      term: '',
      corpus: activeCorpus.value,
      filters,
      includeAi: flags.includeAi,
      includeHuman: flags.includeHuman,
    })

    const namePrefix = isHuman ? anchorDocsetName.value : t('analysis.keyness.groupNamed', { label: d.label })
    const snapshot = subcorporaStore.createSnapshot({
      name: `${namePrefix} · ${suggested}`,
      status: 'parked',
      corpus: activeCorpus.value,
      docsetId: d.docsetId,
      stats: {
        docCount: d.docCount,
        tokenCount: d.tokenCount,
        refDocCount: d.refCount,
      },
      filters,
      includeAi: flags.includeAi,
      includeHuman: flags.includeHuman,
      origin: { type: 'intersection', label: scopeLabel },
    })
    if (subcorporaStore.add(snapshot)) {
      savedCount += 1
    }
  }

  if (savedCount > 0) {
    uiStore.showToast(t('analysis.keyness.subcorporaSaved', { count: savedCount }, savedCount), 'success', 2400)
  } else {
    uiStore.showToast(subcorporaStore.error ?? t('analysis.keyness.subcorporaSaveFailed'), 'warning')
  }
}

async function loadMetaOptions() {
  if (isLoadingOptions.value) return
  isLoadingOptions.value = true
  try {
    const values = await docsetStore.fetchMetaValues({
      fields: ['text_type', 'prompting_method', 'model', 'register', 'source'],
      corpus: activeCorpus.value,
    })
    if (!values) {
      uiStore.showToast(docsetStore.error ?? t('analysis.keyness.metaNotEnabled'), 'warning')
      return
    }
    metaOptions.value = {
      text_type: [...(values.text_type ?? [])].sort(),
      prompting_method: [...(values.prompting_method ?? [])].sort(),
      model: [...(values.model ?? [])].sort(),
      register: [...(values.register ?? [])].sort(),
      source: [...(values.source ?? [])].sort(),
    }
    // The groups start on the version side, whose value differs between
    // corpora (ai or version). A default the corpus does not have filtered
    // every document out.
    for (const group of [groupA, groupB]) {
      const options = metaOptions.value.text_type
      if (options.length && !options.includes(group.value.text_type)) {
        group.value.text_type = options.includes(pairSides.value.version) ? pairSides.value.version : options[0]!
      }
    }
    if (!groupA.value.prompting_method) {
      groupModelOptions.value.A = [...metaOptions.value.model]
    }
    if (!groupB.value.prompting_method) {
      groupModelOptions.value.B = [...metaOptions.value.model]
    }
    scheduleCountsRefresh()
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.metaLoadFailed')
    uiStore.showToast(message, 'error')
  } finally {
    isLoadingOptions.value = false
  }
}

function clampModelSelection(group: 'A' | 'B', options: string[]) {
  const allowed = new Set(options)
  if (group === 'A') {
    groupA.value.model = groupA.value.model.filter((m) => allowed.has(m))
  } else {
    groupB.value.model = groupB.value.model.filter((m) => allowed.has(m))
  }
}

async function refreshGroupModelOptions(group: 'A' | 'B') {
  const promptingMethod = group === 'A' ? groupA.value.prompting_method : groupB.value.prompting_method
  if (!promptingMethod) {
    const base = [...metaOptions.value.model]
    if (group === 'A') {
      groupModelOptions.value.A = base
    } else {
      groupModelOptions.value.B = base
    }
    clampModelSelection(group, base)
    return
  }

  try {
    const values = await docsetStore.fetchMetaValues({
      fields: ['model'],
      corpus: activeCorpus.value,
      filters: { prompting_method: promptingMethod },
    }, {}, t('analysis.keyness.variantMetaValues'))
    if (!values) return
    const next = [...(values.model ?? [])].sort()
    if (group === 'A') {
      groupModelOptions.value.A = next
    } else {
      groupModelOptions.value.B = next
    }
    clampModelSelection(group, next)
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.variantsLoadFailed')
    uiStore.showToast(message, 'error')
  }
}

const step1Badge = computed(() => {
  if (intersectionReady.value) return { label: t('analysis.keyness.badge.computed'), tone: 'done' }
  if (isDirty.value) return { label: t('analysis.keyness.badge.changes'), tone: 'warn' }
  return { label: t('analysis.keyness.badge.ready'), tone: 'idle' }
})

const step2Badge = computed(() => {
  if (!intersectionReady.value) return { label: t('analysis.keyness.badge.waiting'), tone: 'muted' }
  if (contrastReady.value) return { label: t('analysis.keyness.badge.computed'), tone: 'done' }
  return { label: t('analysis.keyness.badge.ready'), tone: 'idle' }
})

function ensureValidTargets() {
  const labels = new Set(docsets.value.map((d) => d.label))
  if (!labels.has(targetLabel.value)) {
    targetLabel.value = labels.has(GROUP_A) ? GROUP_A : docsets.value[0]?.label ?? GROUP_A
  }
  if (!labels.has(referenceLabel.value) || referenceLabel.value === targetLabel.value) {
    if (labels.has(HUMAN) && HUMAN !== targetLabel.value) {
      referenceLabel.value = HUMAN
    } else if (labels.has(GROUP_B) && GROUP_B !== targetLabel.value) {
      referenceLabel.value = GROUP_B
    } else {
      const fallback = docsets.value.find((d) => d.label !== targetLabel.value)
      referenceLabel.value = fallback?.label ?? targetLabel.value
    }
  }
}

function ensureValidParallelBasis() {
  const labels = new Set(docsets.value.map((d) => d.label))
  if (!labels.has(parallelBasisLabel.value)) {
    if (labels.has(HUMAN)) {
      parallelBasisLabel.value = HUMAN
    } else {
      parallelBasisLabel.value = docsets.value[0]?.label ?? GROUP_A
    }
  }
}

async function buildIntersection(force = false): Promise<boolean> {
  if (isBuildingIntersection.value) return false
  if (!force && !isDirty.value && hasIntersection.value) return true

  isBuildingIntersection.value = true
  intersectionError.value = null

  try {
    if (!docsetStore.canBuildDocsetIntersection) {
      intersectionError.value = docsetStore.docsetIntersectionAvailability.disabledReason
        ?? t('analysis.keyness.intersectionNotEnabled')
      return false
    }
    const result = await docsetStore.fetchDocsetIntersection({
      corpus: activeCorpus.value,
      includeHuman: includeHuman.value,
      groups: [
        { label: GROUP_A, filters: groupFiltersPayload(groupA.value) },
        { label: GROUP_B, filters: groupFiltersPayload(groupB.value) },
      ],
    })
    if (!result) {
      intersectionError.value = docsetStore.error ?? t('analysis.keyness.intersectionNotEnabled')
      return false
    }

    intersectionCount.value = result.intersection_count ?? 0
    const nextDocsets: ContrastDocset[] = (result.groups ?? []).map((g) => ({
      label: g.label,
      docsetId: g.docset_id,
      docCount: g.doc_count,
      tokenCount: g.token_count ?? 0,
      refCount: g.ref_count ?? 0,
      kind: 'group',
    }))

    if (includeHuman.value && result.human?.docset_id) {
      nextDocsets.push({
        label: HUMAN,
        docsetId: result.human.docset_id,
        docCount: result.human.doc_count,
        tokenCount: result.human.token_count ?? 0,
        refCount: result.intersection_count ?? 0,
        kind: 'human',
      })
    }

    docsets.value = nextDocsets
    ensureValidTargets()
    ensureValidParallelBasis()
    isDirty.value = false
    contrastLastRun.value = null
    diffRows.value = []
    diffError.value = null
    frequencyDiffCompleteness.value = null
    frequencyDiffMethod.value = null
    collocDiffRows.value = []
    collocDiffMethod.value = null
    collocDiffError.value = null
    ngramDiffRows.value = []
    ngramDiffError.value = null
    parallelGroups.value = []
    parallelError.value = null
    return true
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.intersectionFailed')
    intersectionError.value = message
    uiStore.showToast(message, 'error')
    return false
  } finally {
    isBuildingIntersection.value = false
  }
}

async function ensureIntersectionReady(force = false): Promise<boolean> {
  if (!force && !isDirty.value && hasIntersection.value) return true
  return buildIntersection(true)
}

function getContrastDocsets(): { target: ContrastDocset; reference: ContrastDocset } | null {
  const target = targetDocset.value
  const reference = referenceDocset.value
  if (!target || !reference) return null
  if (!target.docsetId || !reference.docsetId) return null
  if (target.docsetId === reference.docsetId) return null
  return { target, reference }
}

async function loadFrequencyDiffs() {
  diffError.value = null
  diffRows.value = []
  frequencyDiffCompleteness.value = null
  frequencyDiffMethod.value = null
  const ok = await ensureIntersectionReady()
  if (!ok) return
  const docsets = getContrastDocsets()
  if (!docsets) {
    const message = t('analysis.keyness.pickDifferent')
    diffError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const { target, reference } = docsets
  isLoadingDiffs.value = true
  try {
    const start = await createFrequencyDiffJob({
      targetDocsetId: target.docsetId,
      referenceDocsetId: reference.docsetId,
      minFreq: 1,
      limit: DIFF_TOP_N,
      corpus: activeCorpus.value,
    })
    const rowsResponse = await analysisJobs.resumeJobRows<Record<string, unknown>>({
      scope: `keyness-frequency-diff:${activeCorpus.value}`,
      jobId: start.job_id,
      kind: 'frequency_diff',
      corpus: activeCorpus.value,
      rowsLimit: DIFF_TOP_N,
      pollMs: 700,
      queuedMessage: t('analysis.keyness.frequencyDiffStarted'),
      productOperation: {
        operationId: FREQUENCY_OPERATIONS.diffJob,
        surfaceId: 'analysis.contrast',
        label: t('analysis.operations.frequencyContrastJob'),
        detail: `${target.label} vs. ${reference.label}`,
      },
    })
    frequencyDiffMethod.value = coerceMethodBlock(rowsResponse.method) ?? null
    frequencyDiffCompleteness.value = completenessStateFromJobRows(rowsResponse, {
      loadedRows: Array.isArray(rowsResponse.rows) ? rowsResponse.rows.length : 0,
      fallbackRowLimit: DIFF_TOP_N,
    })
    diffRows.value = (rowsResponse.rows ?? [])
      .map((row) => {
        const word = String(row.word ?? '').trim()
        const targetFreq = typeof row.target_freq === 'number' ? row.target_freq : 0
        const referenceFreq = typeof row.reference_freq === 'number' ? row.reference_freq : 0
        const targetPerMillion = typeof row.target_per_million === 'number' ? row.target_per_million : 0
        const referencePerMillion = typeof row.reference_per_million === 'number' ? row.reference_per_million : 0
        const diffPerMillion = typeof row.diff_per_million === 'number'
          ? row.diff_per_million
          : targetPerMillion - referencePerMillion
        const diffAbs = typeof row.diff_abs === 'number' ? row.diff_abs : Math.abs(diffPerMillion)
        return {
          word,
          targetFreq,
          referenceFreq,
          targetPerMillion,
          referencePerMillion,
          diffPerMillion,
          diffAbs,
        } satisfies FrequencyDiffRow
      })
      .filter((row) => row.word)
    persistKeynessResult()
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.frequencyDiffsFailed')
    diffError.value = message
    uiStore.showToast(message, 'error')
  } finally {
    isLoadingDiffs.value = false
  }
}

function updateKeynessSnapshot(currentToken: number, snap: AnalysisJobSnapshot): void {
  if (currentToken !== keynessPollToken) return
  keynessJobSnapshot.value = snap
  if (sessionPresetId.value) {
    void presetsStore.updateJobStatus(sessionPresetId.value, snap)
  }
}

function applyKeynessRows(rowsResponse: AnalysisJobRows<KeynessRow>, reset = false): void {
  const method = coerceMethodBlock((rowsResponse as { method?: unknown }).method)
  if (method) keynessMethod.value = method
  else if (reset) keynessMethod.value = null
  const rows = (rowsResponse.rows ?? []).map((row: any) => ({
    word: row.word,
    target_freq: row.target_freq,
    reference_freq: row.reference_freq,
    target_per_million: row.target_per_million,
    reference_per_million: row.reference_per_million,
    diff_per_million: row.diff_per_million,
    direction: row.direction,
    chi2_cell: row.chi2_cell ?? null,
    chi2: row.chi2 ?? null,
    chi2_signed: row.chi2_signed ?? null,
    ll: row.ll ?? null,
    chi2_cell_signed: row.chi2_cell_signed,
    ll_signed: row.ll_signed,
    log_ratio: row.log_ratio ?? null,
    log_ratio_ci_low: row.log_ratio_ci_low ?? null,
    log_ratio_ci_high: row.log_ratio_ci_high ?? null,
    p_value: row.p_value ?? null,
    q_value: row.q_value ?? null,
    bic: row.bic ?? null,
    low_reliability: row.low_reliability ?? null,
    p_method: row.p_method ?? null,
  }))
  if (reset) {
    data.value = rows
    keynessNextOffset.value = rows.length
    keynessTotalRows.value = null
    keynessPagingExhausted.value = false
    keynessPagingError.value = null
  } else {
    data.value.push(...rows)
    keynessNextOffset.value += rows.length
  }
  const totalRows = rowsResponse.total_rows ?? rowsResponse.total
  if (typeof totalRows === 'number' && Number.isFinite(totalRows) && totalRows >= 0) {
    keynessTotalRows.value = totalRows
  }
  if (rowsResponse.job_id) keynessJobId.value = rowsResponse.job_id
  keynessCompleteness.value = completenessStateFromJobRows(rowsResponse, {
    loadedRows: data.value.length,
    fallbackRowLimit: KEYNESS_PAGE_SIZE,
  })
  persistKeynessResult()
}

async function loadMoreKeynessRows() {
  const jobId = keynessJobId.value
  if (!jobId || isLoadingMoreKeyness.value || !hasMoreKeynessRows.value) return
  const currentToken = keynessPollToken
  isLoadingMoreKeyness.value = true
  keynessPagingError.value = null
  try {
    const response = await analysisJobs.rows<KeynessRow>(
      jobId,
      keynessNextOffset.value,
      KEYNESS_PAGE_SIZE,
    )
    if (currentToken !== keynessPollToken || jobId !== keynessJobId.value) return
    const rows = response.rows ?? []
    applyKeynessRows(response)
    if (rows.length === 0 && hasMoreKeynessRows.value) {
      keynessPagingExhausted.value = true
      keynessPagingError.value = t('analysis.keyness.pagingExhausted')
    }
  } catch (err) {
    if (currentToken !== keynessPollToken || jobId !== keynessJobId.value) return
    const message = err instanceof Error ? err.message : t('analysis.keyness.unknownError')
    keynessPagingError.value = t('analysis.keyness.pagingFailed', { message })
  } finally {
    if (currentToken === keynessPollToken && jobId === keynessJobId.value) {
      isLoadingMoreKeyness.value = false
    }
  }
}

function isAbortError(err: unknown): boolean {
  return err instanceof Error && err.name === 'AbortError'
}

async function cancelKeynessJob() {
  if (!keynessJobId.value || !isKeynessJobRunning.value) return
  if (!canCancelKeynessJob.value) {
    uiStore.showToast(cancelKeynessBlockReason.value ?? t('analysis.keyness.cancelNotEnabled'), 'warning')
    return
  }
  try {
    keynessPollToken += 1
    const snap = await analysisJobs.cancelJob(keynessJobId.value)
    keynessJobSnapshot.value = snap
    if (sessionPresetId.value) {
      void presetsStore.updateJobStatus(sessionPresetId.value, snap)
    }
    keynessError.value = null
    isLoadingKeyness.value = false
    uiStore.showToast(t('analysis.keyness.cancelling'), 'info')
  } catch (err) {
    uiStore.showToast(t('analysis.keyness.cancelFailed'), 'error')
  }
}

async function loadKeyness(options?: { skipIntersection?: boolean }) {
  keynessError.value = null
  data.value = []
  keynessMethod.value = null
  keynessProvenance.value = null
  keynessRunInputs.value = null
  keynessCompleteness.value = null
  keynessJobId.value = null
  keynessNextOffset.value = 0
  keynessTotalRows.value = null
  isLoadingMoreKeyness.value = false
  keynessPagingExhausted.value = false
  keynessPagingError.value = null
  diffRows.value = []
  diffError.value = null
  frequencyDiffCompleteness.value = null
  frequencyDiffMethod.value = null

  const standalone = !isContrastMode.value
  if (!standalone) {
    const ok = options?.skipIntersection ? hasIntersection.value : await ensureIntersectionReady(true)
    if (!ok) {
      if (!options?.skipIntersection) return
      const rebuilt = await ensureIntersectionReady(true)
      if (!rebuilt) return
    }
  }

  const useExternalReference = referenceSource.value !== 'docset'
  const docsets = standalone ? null : getContrastDocsets()
  // The docset-vs-docset path needs both sides; an external reference only needs
  // the target docset (the reference is resolved server-side).
  const target = standalone
    ? standaloneTargetDocset.value
    : docsets?.target ?? targetDocset.value
  if (!target?.docsetId) {
    const message = standalone
      ? t('analysis.keyness.needTarget')
      : useExternalReference
        ? t('analysis.keyness.needTargetDocset')
        : t('analysis.keyness.needBothDocsets')
    keynessError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  if (!standalone && !useExternalReference && !docsets) {
    const message = t('analysis.keyness.needBothDocsets')
    keynessError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const reference = docsets?.reference
  const selectedReference = standaloneReferenceSubcorpus.value
  const source = referenceSource.value
  const referenceName = source === 'whole' ? t('analysis.keyness.refWhole')
    : source === 'corpus' ? referenceCorpus.value : standalone ? selectedReference?.name : reference?.label
  const request: KeynessJobParams = {
    targetDocsetId: target.docsetId,
    referenceDocsetId: useExternalReference ? undefined : reference?.docsetId,
    corpus: activeCorpus.value,
    minFreq: keynessMinFreq.value,
    ...(useExternalReference ? { referenceSource: source } : {}),
    ...(source === 'corpus' ? { referenceCorpus: referenceCorpus.value } : {}),
  }
  // Capture the inputs with the result, before resolving or starting a job.
  // Editing controls later must not relabel an already calculated comparison.
  const targetStats = standalone ? docsetStore.stats : docsets?.target
  const inputs = JSON.parse(JSON.stringify(keynessInputs.value)) as typeof keynessInputs.value
  const provenance = {
    base: sanitizeFilename(`${request.corpus}_${target.label}_vs_${referenceName}`),
    meta: Object.entries({
      Corpus: request.corpus, Target: target.label, Reference: referenceName,
      TargetDocset: target.docsetId, TargetDocs: targetStats?.docCount, TargetTokens: targetStats?.tokenCount,
      TargetFilters: JSON.stringify(standalone ? docsetStore.activeFilterSpec ?? docsetStore.filters : contrastFilters(target.label)),
      ...(standalone ? { TargetOrigin: JSON.stringify(docsetStore.activeDocsetOrigin) } : {}),
      ReferenceSource: source, ReferenceCorpus: request.referenceCorpus ?? request.corpus,
      ...(source === 'whole' ? { ReferenceExcludedDocset: target.docsetId } : {}),
      ...(source === 'docset' ? {
        ReferenceFilters: JSON.stringify(standalone ? selectedReference?.filterSpec ?? selectedReference?.filters : contrastFilters(reference!.label)),
      } : {}),
      MinFreq: request.minFreq,
    }).map(([key, value]) => csvMeta(key, value)),
  }
  if (standalone && !useExternalReference) {
    if (!selectedReference) {
      const message = t('analysis.keyness.needReferenceSubcorpus')
      keynessError.value = message
      uiStore.showToast(message, 'warning')
      return
    }
    let resolvedReference: Awaited<ReturnType<typeof docsetStore.resolveNamedSubcorpusDocset>>
    try {
      resolvedReference = await docsetStore.resolveNamedSubcorpusDocset(
        subcorporaStore.durableNameForSnapshot(selectedReference),
        selectedReference.corpus,
      )
    } catch (err) {
      const message = err instanceof Error
        ? err.message
        : t('analysis.keyness.referenceResolveFailed')
      keynessError.value = message
      uiStore.showToast(message, 'warning')
      return
    }
    if (!resolvedReference?.docset_id) {
      const message = docsetStore.error ?? t('analysis.keyness.referenceResolveFailed')
      keynessError.value = message
      uiStore.showToast(message, 'warning')
      return
    }
    request.referenceDocsetId = resolvedReference.docset_id
    provenance.meta.push(csvMeta('ReferenceDocs', resolvedReference.doc_count), csvMeta('ReferenceTokens', resolvedReference.token_count))
    if (request.referenceDocsetId === target.docsetId) {
      const message = t('analysis.keyness.sameDocuments')
      keynessError.value = message
      uiStore.showToast(message, 'warning')
      return
    }
  }

  if (request.referenceDocsetId) provenance.meta.push(csvMeta('ReferenceDocset', request.referenceDocsetId))
  if (!standalone && reference && !useExternalReference) {
    provenance.meta.push(csvMeta('ReferenceDocs', reference.docCount), csvMeta('ReferenceTokens', reference.tokenCount))
  }
  if (request.corpus !== activeCorpus.value) return
  keynessProvenance.value = provenance
  keynessRunInputs.value = { ...inputs, params: { ...inputs.params, keynessProvenance: provenance } }
  isLoadingKeyness.value = true
  let currentToken = keynessPollToken
  try {
    currentToken = keynessPollToken + 1
    keynessPollToken = currentToken
    const rowsResponse = await analysisJobs.runJobRows<KeynessRow>({
      scope: `keyness:${activeCorpus.value}`,
      kind: 'keyness',
      corpus: activeCorpus.value,
      rowsLimit: KEYNESS_PAGE_SIZE,
      pollMs: 800,
      queuedMessage: t('analysis.keyness.started'),
      productOperation: {
        operationId: KEYNESS_OPERATIONS.job,
        surfaceId: 'analysis.keyness',
        label: t('analysis.operations.keynessJob'),
        detail: `${target.label} vs. ${referenceName}`,
      },
      start: () => createKeynessAnalysisJob(request, {
        target: activeCorpus.value ? t('analysis.shared.corpusNamed', { name: activeCorpus.value }) : t('analysis.shared.activeCorpus'),
        impact: t('analysis.keyness.jobImpact'),
        contextualConfirmation: {
          surfaceId: 'analysis.keyness',
          interaction: 'keyness.tab.job',
          source: 'native_surface',
        },
      }),
      onStarted: async (start) => {
        if (currentToken !== keynessPollToken) return
        keynessJobId.value = start.job_id
        try {
          const session = await presetsStore.upsertJobSession({
            id: sessionPresetId.value ?? undefined,
            name: t('analysis.keyness.defaultName', { query: queryStore.term || t('analysis.keyness.noQuery') }),
            type: 'keyness',
            ...keynessInputs.value,
            status: 'queued',
            jobId: start.job_id,
            kind: sessionPresetId.value ? undefined : 'session',
          })
          sessionPresetId.value = session.id
        } catch (err) {
          console.warn('Analysis session could not be saved', err)
        }
      },
      onSnapshot: (snap) => updateKeynessSnapshot(currentToken, snap),
    })
    if (currentToken !== keynessPollToken) return
    applyKeynessRows(rowsResponse, true)
    // Frequency diffs need both docset sides; skip them for an external reference.
    if (isContrastMode.value && !useExternalReference) {
      await loadFrequencyDiffs()
    }
  } catch (err) {
    if (currentToken !== keynessPollToken) return
    if (isAbortError(err)) return
    const message = err instanceof Error ? err.message : t('analysis.keyness.loadFailed')
    keynessError.value = message
    uiStore.showToast(message, 'error')
  } finally {
    if (currentToken === keynessPollToken) {
      isLoadingKeyness.value = false
    }
  }
}

async function resumeKeynessJob(existingJobId: string) {
  const currentToken = keynessPollToken + 1
  keynessPollToken = currentToken
  keynessError.value = null
  keynessJobSnapshot.value = null
  keynessJobId.value = existingJobId
  isLoadingKeyness.value = true
  try {
    const rowsResponse = await analysisJobs.resumeJobRows<KeynessRow>({
      scope: `keyness:${activeCorpus.value}`,
      jobId: existingJobId,
      rowsLimit: KEYNESS_PAGE_SIZE,
      pollMs: 800,
      onSnapshot: (snap) => updateKeynessSnapshot(currentToken, snap),
    })
    if (currentToken !== keynessPollToken) return
    applyKeynessRows(rowsResponse, true)
  } catch (err) {
    if (currentToken !== keynessPollToken || isAbortError(err)) return
    keynessError.value = err instanceof Error ? err.message : t('analysis.keyness.jobLoadFailed')
  } finally {
    if (currentToken === keynessPollToken) {
      isLoadingKeyness.value = false
    }
  }
}

async function waitForAnalysisJobRows<T>(
  jobId: string,
  mapRows: (rows: Array<Record<string, any>>) => T[],
  limit = 200,
  productOperation?: {
    operationId: string
    surfaceId: string
    label: string
    detail?: string | null
  },
  onMethod?: (method: MethodBlock | null) => void
): Promise<T[]> {
  const rowsResponse = await analysisJobs.resumeJobRows<Record<string, any>>({
    scope: `keyness-dashboard:${jobId}`,
    jobId,
    kind: productOperation?.label,
    corpus: activeCorpus.value,
    rowsLimit: Math.max(limit, 200),
    pollMs: 700,
    queuedMessage: productOperation ? t('analysis.keyness.labelStarted', { label: productOperation.label }) : undefined,
    productOperation: productOperation
      ? {
          operationId: productOperation.operationId,
          surfaceId: productOperation.surfaceId,
          label: productOperation.label,
          detail: productOperation.detail ?? null,
        }
      : undefined,
  })
  if (onMethod) onMethod(coerceMethodBlock((rowsResponse as Record<string, any>).method) ?? null)
  const rows = Array.isArray(rowsResponse.rows) ? rowsResponse.rows : []
  return mapRows(rows)
}

async function loadCollocationDiffs() {
  collocDiffError.value = null
  collocDiffRows.value = []
  collocDiffMethod.value = null
  const term = stripCoQueryTerm(queryStore.term)
  if (!term) {
    const message = t('analysis.keyness.needSearch')
    collocDiffError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const ok = await ensureIntersectionReady()
  if (!ok) return
  const docsets = getContrastDocsets()
  if (!docsets) {
    const message = t('analysis.keyness.pickDifferent')
    collocDiffError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const { target, reference } = docsets
  isLoadingCollocDiffs.value = true
  try {
    const start = await createCollocationContrastJob({
      term,
      targetDocsetId: target.docsetId,
      referenceDocsetId: reference.docsetId,
      window: collocWindow.value,
      withinSentence: collocWithinSentence.value,
      sortBy: collocMeasure.value === 'tscore'
        ? 't'
        : collocMeasure.value === 'lmi'
          ? 'lmi'
          : collocMeasure.value === 'npmi'
            ? 'npmi'
            : collocMeasure.value === 'z'
              ? 'z'
              : collocMeasure.value === 'mi'
                ? 'mi'
                : 'logdice',
      limit: collocLimit.value,
      corpus: activeCorpus.value,
    })
    collocDiffRows.value = await waitForAnalysisJobRows(
      start.job_id,
      (rows) => rows
        .map((row) => {
          const word = String(row.word ?? '').trim()
          const targetFreq = typeof row.target_freq === 'number' ? row.target_freq : 0
          const referenceFreq = typeof row.reference_freq === 'number' ? row.reference_freq : 0
          const targetScore = typeof row.target_score === 'number' ? row.target_score : 0
          const referenceScore = typeof row.reference_score === 'number' ? row.reference_score : 0
          const targetPerMillion = typeof row.target_per_million === 'number' ? row.target_per_million : perMillion(targetFreq, target.tokenCount)
          const referencePerMillion = typeof row.reference_per_million === 'number' ? row.reference_per_million : perMillion(referenceFreq, reference.tokenCount)
          const diffPerMillion = typeof row.diff_per_million === 'number' ? row.diff_per_million : targetPerMillion - referencePerMillion
          const diffScore = typeof row.diff_score === 'number' ? row.diff_score : targetScore - referenceScore
          const diffAbs = typeof row.diff_abs === 'number' ? row.diff_abs : Math.abs(diffPerMillion)
          return {
            word,
            targetFreq,
            referenceFreq,
            targetScore,
            referenceScore,
            targetPerMillion,
            referencePerMillion,
            diffPerMillion,
            diffScore,
            diffAbs,
          } satisfies CollocationDiffRow
        })
        .filter((row) => row.word)
        .slice(0, collocLimit.value),
      collocLimit.value,
      {
        operationId: CONTRAST_OPERATIONS.collocationsDiffJob,
        surfaceId: 'analysis.contrast',
        label: t('analysis.operations.collocationContrastJob'),
        detail: term,
      },
      (method) => { collocDiffMethod.value = method }
    )
    persistKeynessResult()
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.collocDiffsFailed')
    collocDiffError.value = message
    uiStore.showToast(message, 'error')
  } finally {
    isLoadingCollocDiffs.value = false
  }
}

async function loadNgramDiffs() {
  ngramDiffError.value = null
  ngramDiffRows.value = []
  const ok = await ensureIntersectionReady()
  if (!ok) return
  const docsets = getContrastDocsets()
  if (!docsets) {
    const message = t('analysis.keyness.pickDifferent')
    ngramDiffError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const { target, reference } = docsets
  isLoadingNgramDiffs.value = true
  try {
    const start = await createNgramDiffJob({
      targetDocsetId: target.docsetId,
      referenceDocsetId: reference.docsetId,
      n: ngramSize.value,
      minFreq: ngramMinFreq.value,
      limit: ngramLimit.value,
      corpus: activeCorpus.value,
    })
    ngramDiffRows.value = await waitForAnalysisJobRows(
      start.job_id,
      (rows) => rows
        .map((row) => {
          const ngram = String(row.ngram ?? '').trim()
          const targetFreq = typeof row.target_freq === 'number' ? row.target_freq : 0
          const referenceFreq = typeof row.reference_freq === 'number' ? row.reference_freq : 0
          const targetPerMillion = typeof row.target_per_million === 'number' ? row.target_per_million : 0
          const referencePerMillion = typeof row.reference_per_million === 'number' ? row.reference_per_million : 0
          const diffPerMillion = typeof row.diff_per_million === 'number' ? row.diff_per_million : 0
          const diffAbs = typeof row.diff_abs === 'number' ? row.diff_abs : Math.abs(diffPerMillion)
          return {
            ngram,
            targetFreq,
            referenceFreq,
            targetPerMillion,
            referencePerMillion,
            diffPerMillion,
            diffAbs,
          } satisfies NgramDiffRow
        })
        .filter((row) => row.ngram && (row.targetFreq >= ngramMinFreq.value || row.referenceFreq >= ngramMinFreq.value))
        .slice(0, ngramLimit.value),
      ngramLimit.value,
      {
        operationId: NGRAM_OPERATIONS.diffJob,
        surfaceId: 'analysis.ngrams',
        label: t('analysis.operations.ngramContrastJob'),
        detail: t('analysis.ngrams.sizeN', { n: ngramSize.value }),
      }
    )
    persistKeynessResult()
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.ngramDiffsFailed')
    ngramDiffError.value = message
    uiStore.showToast(message, 'error')
  } finally {
    isLoadingNgramDiffs.value = false
  }
}

async function loadParallelGroups() {
  parallelError.value = null
  parallelGroups.value = []
  if (!canUseParallel.value) {
    parallelError.value = parallelGroupsBlockReason.value ?? t('analysis.keyness.parallelNotEnabled')
    return
  }
  const ok = await ensureIntersectionReady()
  if (!ok) return
  const basisId = parallelBasisDocsetId.value
  if (!basisId) {
    const message = t('analysis.keyness.needBasis')
    parallelError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  isLoadingParallel.value = true
  try {
    const result = await requestParallelGroups({
      corpus: activeCorpus.value,
      docsetId: basisId,
      includeAllVariants: parallelIncludeVariants.value,
      limit: parallelLimit.value,
      offset: parallelOffset.value,
      sort: parallelSort.value,
    })
    parallelGroups.value = result.groups ?? []
    parallelTotal.value = result.total ?? 0
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.parallelFailed')
    parallelError.value = message
    uiStore.showToast(message, 'error')
  } finally {
    isLoadingParallel.value = false
  }
}

async function loadContrastDashboard() {
  if (
    isLoadingContrastDashboard.value
    || isLoadingCollocDiffs.value
    || isLoadingNgramDiffs.value
    || isLoadingParallel.value
  ) {
    return
  }
  const ok = await ensureIntersectionReady(true)
  if (!ok) return
  isLoadingContrastDashboard.value = true
  contrastLastRun.value = null
  try {
    await loadKeyness({ skipIntersection: true })
    void Promise.allSettled([
      loadCollocationDiffs(),
      loadNgramDiffs(),
      // Parallel groups require product visibility plus paired corpus metadata.
      ...(canUseParallel.value ? [loadParallelGroups()] : []),
    ]).then(() => {
      contrastLastRun.value = Date.now()
    })
  } finally {
    isLoadingContrastDashboard.value = false
  }
}

async function openCooccurrenceKwic(word: string) {
  const term = stripCoQueryTerm(queryStore.term)
  if (!term || !word) return
  const docsets = getContrastDocsets()
  if (!docsets) {
    uiStore.showToast(t('analysis.keyness.needDocsets'), 'warning')
    return
  }
  const { target } = docsets
  try {
    const coQuery = buildCoKwicQuery({
      term,
      collocate: word,
      window: collocWindow.value,
      withinSentence: collocWithinSentence.value,
    })
    queryStore.setLoading(true)
    queryStore.setTerm(coQuery)
    queryStore.setFilters({ corpus: activeCorpus.value })
    queryStore.deselectAll()
    queryStore.setHighlightedRow(null)
    queryStore.setScrollPosition(0)
    queryStore.setPendingScrollPosition(null)
    const result = await loadCollocateKwic({
      term,
      collocate: word,
      window: collocWindow.value,
      withinSentence: collocWithinSentence.value,
      ctx: queryStore.contextSize,
      corpus: activeCorpus.value,
      docsetId: target.docsetId,
      limit: 1000,
    })
    const windowState = coKwicWindowState(result)
    queryStore.setResults(mapCoKwicHits(result), result.total, windowState.totalKnown, windowState.totalPartial)
    queryStore.setCoKwicCounts(result.coKwic)
    queryStore.setResultOffsetStart(0)
    queryStore.setHasPrevious(false)
    queryStore.setHasMore(windowState.hasMore)
    queryStore.setNextOffset(windowState.nextOffset)
    queryStore.setTotalHits(result.total, windowState.totalKnown, windowState.totalPartial)
    queryStore.setLastExecutedAt(Date.now())
    queryStore.finishStreaming()
    await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
    uiStore.showToast(`Co-KWIC: ${term} + ${word}`, 'info', 2500)
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.coKwicFailed')
    uiStore.showToast(message, 'error')
    queryStore.setError(message)
    queryStore.finishStreaming()
  } finally {
    queryStore.setLoading(false)
  }
}

async function openParallelAlignment(refDoc: number) {
  if (!canOpenAlignment.value) {
    parallelAlignmentError.value = alignmentBlockReason.value ?? t('analysis.keyness.alignmentNotEnabled')
    return
  }
  parallelAlignmentError.value = null
  parallelAlignmentResult.value = null
  isParallelModalOpen.value = true
  isLoadingParallelAlignment.value = true
  try {
    parallelAlignmentResult.value = await requestAlignmentRefDoc({
      refDoc,
      corpus: activeCorpus.value,
      windowSentences: 24,
      maxVariants: 6,
    })
  } catch (err) {
    const message = err instanceof Error ? err.message : t('analysis.keyness.alignmentFailed')
    parallelAlignmentError.value = message
  } finally {
    isLoadingParallelAlignment.value = false
  }
}

function closeParallelModal() {
  isParallelModalOpen.value = false
  parallelAlignmentResult.value = null
  parallelAlignmentError.value = null
}

const sortedData = computed(() => {
  return [...data.value].sort((a, b) => {
    const diff = metricRawValue(b) - metricRawValue(a)
    return sortOrder.value === 'desc' ? diff : -diff
  })
})

const keynessVirtualizer = useVirtualizer(
  computed(() => ({
    count: sortedData.value.length,
    getScrollElement: () => keynessTableContainerRef.value,
    estimateSize: () => KEYNESS_ROW_ESTIMATE_PX,
    initialRect: { width: 1200, height: 600 },
    overscan: 12,
    getItemKey: (index: number) => sortedData.value[index]?.word ?? index,
  }))
)

const virtualKeynessRows = computed<KeynessVirtualRow[]>(() => {
  const rows: KeynessVirtualRow[] = []
  const virtualItems = keynessVirtualizer.value.getVirtualItems()
  if (!virtualItems.length && sortedData.value.length) {
    const count = Math.min(sortedData.value.length, KEYNESS_FALLBACK_VIRTUAL_ROWS)
    for (let index = 0; index < count; index += 1) {
      const row = sortedData.value[index]
      if (row) {
        rows.push({
          virtualRow: {
            index,
            start: index * KEYNESS_ROW_ESTIMATE_PX,
            end: (index + 1) * KEYNESS_ROW_ESTIMATE_PX,
          },
          row,
        })
      }
    }
    return rows
  }
  for (const virtualRow of virtualItems) {
    const row = sortedData.value[virtualRow.index]
    if (row) rows.push({ virtualRow, row })
  }
  return rows
})
const keynessTopPadding = computed(() => virtualKeynessRows.value[0]?.virtualRow.start ?? 0)
const keynessBottomPadding = computed(() => {
  const rows = virtualKeynessRows.value
  const last = rows.length ? rows[rows.length - 1]?.virtualRow : undefined
  const totalSize = Math.max(
    keynessVirtualizer.value.getTotalSize(),
    sortedData.value.length * KEYNESS_ROW_ESTIMATE_PX,
  )
  return Math.max(0, totalSize - (last?.end ?? 0))
})
const keynessColumnCount = computed(() => hasFullChi2.value ? 10 : 9)

function toggleSort() {
  sortOrder.value = sortOrder.value === 'desc' ? 'asc' : 'desc'
}

function normalizeKeynessMetric(raw: unknown): KeynessMetric {
  if (
    raw === 'll'
    || raw === 'chi2_cell'
    || raw === 'chi2'
    || raw === 'chi2_signed'
    || raw === 'log_ratio'
    || raw === 'll_signed'
  ) {
    return raw
  }
  return 'll_signed'
}

function chi2CellValue(row: KeynessRow): number {
  return row.chi2_cell ?? 0
}

/** Full 2x2 Pearson chi-square magnitude (defensive: may be absent). */
function chi2Value(row: KeynessRow): number {
  return typeof row.chi2 === 'number' ? row.chi2 : 0
}

/**
 * Signed full chi-square: positive = over-represented in target. Falls back to
 * applying the row direction to the unsigned chi-square when the backend omits
 * the pre-signed field.
 */
function chi2SignedValue(row: KeynessRow): number {
  if (typeof row.chi2_signed === 'number') return row.chi2_signed
  const c = chi2Value(row)
  return row.direction === 'reference' ? -c : c
}

/** Whether the backend supplied the full 2x2 chi-square on any row. */
const hasFullChi2 = computed(() =>
  data.value.some((row) => typeof row.chi2 === 'number')
)

function llSignedValue(row: KeynessRow): number {
  // Prefer the signed log-likelihood; fall back to direction-applied raw LL.
  if (typeof row.ll_signed === 'number') return row.ll_signed
  const ll = row.ll ?? 0
  return row.direction === 'reference' ? -ll : ll
}

function logRatioValue(row: KeynessRow): number | null {
  return typeof row.log_ratio === 'number' ? row.log_ratio : null
}

function handleMetricSort(nextMetric: KeynessMetric) {
  if (metric.value === nextMetric) {
    toggleSort()
  } else {
    metric.value = nextMetric
    sortOrder.value = 'desc'
  }
}

/** Raw value used purely for ordering rows by the active metric. */
function metricRawValue(row: KeynessRow): number {
  switch (metric.value) {
    case 'll_signed':
      return llSignedValue(row)
    case 'log_ratio':
      return logRatioValue(row) ?? -1e12
    case 'chi2':
      return chi2Value(row)
    case 'chi2_signed':
      return chi2SignedValue(row)
    case 'chi2_cell':
      return chi2CellValue(row)
    case 'll':
    default:
      return row.ll ?? -1e12
  }
}

/** Value driving the visualization bar (magnitude). */
function metricValue(row: KeynessRow): number {
  switch (metric.value) {
    case 'log_ratio':
      return logRatioValue(row) ?? 0
    case 'll_signed':
      return llSignedValue(row)
    case 'chi2':
      return chi2Value(row)
    case 'chi2_signed':
      return chi2SignedValue(row)
    case 'chi2_cell':
      return chi2CellValue(row)
    case 'll':
    default:
      return row.ll ?? 0
  }
}

function metricWidth(row: KeynessRow): number {
  const value = metricValue(row)
  const scale =
    metric.value === 'chi2_cell'
      ? 10
      : metric.value === 'chi2' || metric.value === 'chi2_signed'
        ? 100
        : metric.value === 'log_ratio'
          ? 3
          : 50
  if (scale <= 0) return 0
  return Math.min(Math.max((Math.abs(value) / scale) * 100, 0), 100)
}

function formatLogRatio(row: KeynessRow): string {
  const lr = logRatioValue(row)
  if (lr === null) return '–'
  const low = row.log_ratio_ci_low
  const high = row.log_ratio_ci_high
  if (typeof low === 'number' && typeof high === 'number') {
    return `${formatDecimal(lr, 2)} (${formatInterval(low, high, 1)})`
  }
  return formatDecimal(lr, 2)
}

function formatPValue(value: number | null | undefined): string {
  if (typeof value !== 'number' || Number.isNaN(value)) return '–'
  if (value === 0) return '0'
  if (value < 0.001) return formatNumber(value, { notation: 'scientific', maximumFractionDigits: 1 })
  return formatDecimal(value, 3)
}

watch(
  () => [groupA.value, groupB.value, includeHuman.value, activeCorpus.value] as const,
  () => {
    markDirty()
  },
  { deep: true }
)

watch(
  () => groupA.value.prompting_method,
  () => {
    void refreshGroupModelOptions('A')
  }
)

watch(
  () => groupB.value.prompting_method,
  () => {
    void refreshGroupModelOptions('B')
  }
)

watch(
  () => activeCorpus.value,
  () => {
    void loadMetaOptions()
    void refreshGroupModelOptions('A')
    void refreshGroupModelOptions('B')
  }
)

// Results belong to the corpus they were computed on. After a corpus switch
// the tables are empty: keyness needs a target subcorpus of the new corpus,
// and a job still running for the old one no longer writes its rows.
watch(
  () => activeCorpus.value,
  (corpus, previous) => {
    if (corpus === previous) return
    keynessPollToken += 1
    isLoadingKeyness.value = false
    keynessError.value = null
    data.value = []
    keynessMethod.value = null
    keynessProvenance.value = null
    keynessRunInputs.value = null
    keynessCompleteness.value = null
    keynessJobId.value = null
    keynessNextOffset.value = 0
    keynessTotalRows.value = null
    isLoadingMoreKeyness.value = false
    keynessPagingExhausted.value = false
    keynessPagingError.value = null
    diffRows.value = []
    diffError.value = null
    frequencyDiffCompleteness.value = null
    frequencyDiffMethod.value = null
    collocDiffRows.value = []
  }
)

watch(isContrastMode, (enabled) => {
  if (!enabled && referenceSource.value === 'docset') {
    referenceSource.value = 'whole'
  }
})

watch(
  () => [activeCorpus.value, standaloneReferenceSubcorpora.value.map((snapshot) => snapshot.id).join('|')] as const,
  () => {
    const available = new Set(standaloneReferenceSubcorpora.value.map((snapshot) => snapshot.id))
    if (standaloneReferenceSubcorpusId.value && !available.has(standaloneReferenceSubcorpusId.value)) {
      standaloneReferenceSubcorpusId.value = ''
    }
    if (!isContrastMode.value && referenceSource.value === 'docset' && !standaloneReferenceSubcorpora.value.length) {
      referenceSource.value = 'whole'
    }
  },
)

watch([targetLabel, referenceLabel], () => {
  keynessError.value = null
  diffRows.value = []
  frequencyDiffCompleteness.value = null
  frequencyDiffMethod.value = null
  collocDiffRows.value = []
  collocDiffMethod.value = null
  ngramDiffRows.value = []
})

watch(
  () => queryStore.term,
  () => {
    collocDiffRows.value = []
    collocDiffMethod.value = null
    collocDiffError.value = null
  }
)

watch(canUseParallel, (allowed) => {
  if (allowed) return
  parallelGroups.value = []
  parallelTotal.value = 0
  parallelError.value = null
  parallelAlignmentResult.value = null
  isParallelModalOpen.value = false
})

watch(
  () => collocWithinSentence.value,
  () => {
    collocDiffRows.value = []
    collocDiffMethod.value = null
    collocDiffError.value = null
  }
)

onMounted(() => {
  void productCapabilities.load()
  if (!subcorporaStore.initialized) void subcorporaStore.init()
  void loadMetaOptions()
})

watch(
  () => presetsStore.pendingPreset,
  async (preset) => {
    if (!preset || preset.type !== 'keyness') return
    sessionPresetId.value = preset.id
    let hasValidResult = false
    const params = preset.params as Record<string, unknown>
    keynessRunInputs.value = JSON.parse(JSON.stringify({
      corpus: preset.corpus, docset: preset.docset, queryTerm: preset.queryTerm, params,
    }))
    referenceSource.value = params.referenceSource === 'docset' || params.referenceSource === 'corpus' || params.referenceSource === 'whole'
      ? params.referenceSource : isContrastMode.value ? 'docset' : 'whole'
    referenceCorpus.value = typeof params.referenceCorpus === 'string' ? params.referenceCorpus : ''
    keynessMinFreq.value = typeof params.keynessMinFreq === 'number' ? params.keynessMinFreq : 5
    standaloneReferenceSubcorpusId.value = typeof params.standaloneReferenceSubcorpusId === 'string'
      ? params.standaloneReferenceSubcorpusId : ''
    keynessProvenance.value = params.keynessProvenance as typeof keynessProvenance.value ?? null
    if (typeof params.metric === 'string') metric.value = normalizeKeynessMetric(params.metric)
    if (typeof params.sortOrder === 'string') sortOrder.value = params.sortOrder as any
    if (typeof params.includeHuman === 'boolean') includeHuman.value = params.includeHuman
    if (params.groupA) groupA.value = params.groupA as any
    if (params.groupB) groupB.value = params.groupB as any
    if (typeof params.targetLabel === 'string') targetLabel.value = params.targetLabel
    if (typeof params.referenceLabel === 'string') referenceLabel.value = params.referenceLabel
    if (typeof params.collocWindow === 'number') collocWindow.value = params.collocWindow
    if (typeof params.collocWithinSentence === 'boolean') collocWithinSentence.value = params.collocWithinSentence
    if (typeof params.collocMeasure === 'string') collocMeasure.value = params.collocMeasure as any
    if (typeof params.ngramSize === 'number') ngramSize.value = params.ngramSize
    if (typeof params.ngramMinFreq === 'number') ngramMinFreq.value = params.ngramMinFreq
    presetsStore.setPending(null)
    if (preset.result && typeof preset.result === 'object') {
      const valid = await presetsStore.isResultValid(preset)
      if (valid) {
        const result = preset.result as any
        data.value = (result.keynessRows ?? []) as KeynessRow[]
        keynessProvenance.value = result.keynessProvenance ?? keynessProvenance.value
        keynessMethod.value = coerceMethodBlock(result.keynessMethod) ?? null
        diffRows.value = (result.diffRows ?? []) as FrequencyDiffRow[]
        collocDiffRows.value = (result.collocDiffRows ?? []) as CollocationDiffRow[]
        ngramDiffRows.value = (result.ngramDiffRows ?? []) as NgramDiffRow[]
        keynessError.value = null
        isLoadingKeyness.value = false
        keynessJobSnapshot.value = null
        hasValidResult = true
      } else {
        uiStore.showToast(t('analysis.shared.staleSaved'), 'info', 2500)
      }
    }
    if (isContrastMode.value && !(await buildIntersection(true))) return
    if (preset.jobId && (preset.status === 'running' || preset.status === 'queued')) {
      await resumeKeynessJob(preset.jobId)
    } else if (!hasValidResult) {
      await loadKeyness({ skipIntersection: true })
    }
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  if (countsTimer !== null) {
    window.clearTimeout(countsTimer)
    countsTimer = null
  }
  if (persistResultTimer !== null) {
    window.clearTimeout(persistResultTimer)
    persistResultTimer = null
  }
  countsAbortController?.abort()
  countsAbortController = null
})
</script>

<template>
  <div class="keyness-tab">
    <AnalysisToolbar>
      <template #left>
        <div class="scope-pill" :class="{ active: docsetStore.hasActiveDocset }">
          {{ t('analysis.keyness.scopePill', { scope: docsetStore.scopeLabel, corpus: activeCorpus }) }}
        </div>
        <div v-if="queryStore.term" class="scope-pill scope-pill-muted">
          {{ t('analysis.keyness.queryPill', { query: queryStore.term }) }}
        </div>
      </template>

      <template #center>
        <label v-if="isContrastMode" class="method-option">
          <input v-model="includeHuman" type="checkbox" />
          <span>{{ usesAnchorSides ? t('analysis.keyness.includeAnchor') : t('analysis.keyness.includeHuman') }}</span>
        </label>
        <div class="method-selector">
          <label class="method-option">
            <input v-model="metric" type="radio" value="ll_signed" />
            <span>{{ t('analysis.keyness.signedLl') }}</span>
          </label>
          <label class="method-option">
            <input v-model="metric" type="radio" value="log_ratio" />
            <span>{{ t('analysis.keyness.logRatioEffect') }}</span>
          </label>
          <label v-if="hasFullChi2" class="method-option">
            <input v-model="metric" type="radio" value="chi2" />
            <span>Chi² (2x2 Pearson)</span><!-- i18n-ignore: statistic name, same in both languages -->
          </label>
          <label v-if="hasFullChi2" class="method-option">
            <input v-model="metric" type="radio" value="chi2_signed" />
            <span>{{ t('analysis.keyness.chi2Signed') }}</span>
          </label>
          <label class="method-option">
            <input v-model="metric" type="radio" value="chi2_cell" />
            <span>{{ t('analysis.measureOptions.chi2CellShort') }}</span>
          </label>
          <label class="method-option">
            <input v-model="metric" type="radio" value="ll" />
            <span>{{ t('analysis.measureOptions.logLikelihood') }}</span>
          </label>
          <MeasureInfo :measure-key="metric" :method="keynessMethod" />
        </div>
        <!-- Reference source + min-freq (FT-KEYNESS-RESEARCH) -->
        <div class="keyness-reference">
          <label class="ref-field">
            <span class="ref-label">{{ t('analysis.keyness.reference') }}</span>
            <select v-model="referenceSource" class="ref-select" :title="t('analysis.keyness.referenceTitle')">
              <option v-if="isContrastMode" value="docset">{{ t('analysis.keyness.refDocset') }}</option>
              <option v-else value="docset" :disabled="!standaloneReferenceSubcorpora.length">
                {{ t('analysis.keyness.refSaved') }}
              </option>
              <option value="whole">{{ t('analysis.keyness.refWhole') }}</option>
              <option value="corpus">{{ t('analysis.keyness.refCorpus') }}</option>
              <!-- KEYNESS-02: the 'freqlist' reference is removed — the backend
                   ships no bundled DE list and requires an inline word→freq map,
                   so the only configured option (deref_de_core) always 422'd. -->
            </select>
          </label>
          <label v-if="!isContrastMode && referenceSource === 'docset'" class="ref-field">
            <span class="ref-label">{{ t('analysis.keyness.referenceSubcorpus') }}</span>
            <select
              v-model="standaloneReferenceSubcorpusId"
              class="ref-select"
              :aria-label="t('analysis.keyness.referenceSubcorpusAria')"
            >
              <option value="">{{ t('analysis.keyness.select') }}</option>
              <option
                v-for="snapshot in standaloneReferenceSubcorpora"
                :key="snapshot.id"
                :value="snapshot.id"
              >
                {{ snapshot.name }}
              </option>
            </select>
          </label>
          <label v-if="referenceSource === 'corpus'" class="ref-field">
            <span class="ref-label">{{ t('analysis.keyness.corpus') }}</span>
            <input
              v-model="referenceCorpus"
              type="text"
              class="ref-input"
              :placeholder="t('analysis.keyness.corpusPlaceholder')"
            />
          </label>
          <label class="ref-field">
            <span class="ref-label">{{ t('analysis.keyness.minFreq') }}</span>
            <input
              v-model.number="keynessMinFreq"
              type="number"
              min="1"
              max="100"
              class="ref-input ref-input--num"
              :title="t('analysis.keyness.minFreqTitle')"
            />
          </label>
        </div>
        <p class="method-note method-note--limit">
          {{ keynessReferenceLimitNote }}
        </p>
        <i18n-t v-if="isContrastMode" keypath="analysis.keyness.contrastNote" tag="p" class="method-note" scope="global">
          <template #logRatio><strong>{{ t('analysis.keyness.logRatio') }}</strong></template>
          <template #p><strong>p</strong></template>
          <template #q><strong>q</strong></template>
          <template #chi2cell><code>chi2_cell</code></template>
        </i18n-t>
        <p v-else class="method-note">
          {{ t('analysis.keyness.standaloneNote') }}
        </p>
      </template>

      <template #right>
        <JobStatusPill
          v-if="keynessJobSnapshot && isKeynessJobRunning"
          :status="keynessJobSnapshot.status"
          :progress="keynessJobSnapshot.progress"
          :message="keynessJobSnapshot.message"
          :canCancel="canCancelKeynessJob"
          @cancel="cancelKeynessJob"
        />
        <SaveAnalysisButton
          type="keyness"
          :defaultName="t('analysis.keyness.defaultName', { query: queryStore.term || t('analysis.keyness.noQuery') })"
          :corpus="keynessInputs.corpus"
          :docset="keynessInputs.docset"
          :queryTerm="keynessInputs.queryTerm"
          :params="{ ...keynessInputs.params, metric, sortOrder }"
          :result="data.length || diffRows.length || collocDiffRows.length || ngramDiffRows.length ? {
            keynessRows: data,
            keynessProvenance,
            keynessMethod,
            diffRows,
            collocDiffRows,
            ngramDiffRows,
          } : undefined"
          :resultMeta="data.length || diffRows.length || collocDiffRows.length || ngramDiffRows.length ? {
            corpus: keynessInputs.corpus,
            docsetId: keynessInputs.docset?.docsetId ?? null,
            queryTerm: keynessInputs.queryTerm,
            ...keynessInputs.params,
            docCount: keynessInputs.docset?.stats.docCount,
            tokenCount: keynessInputs.docset?.stats.tokenCount,
            generatedAt: Date.now(),
          } : undefined"
        />
        <Button
          variant="ghost"
          size="sm"
          :icon="Scale"
          :loading="isLoadingKeyness"
          @click="() => loadKeyness()"
        >
          Keyness
        </Button>
        <Button variant="ghost" size="sm" :icon="Download" @click="exportOpen = true">
          CSV
        </Button>
      </template>
    </AnalysisToolbar>

    <CapabilityBoundaryPanel
      capability-id="analysis.keyness"
      :method="keynessMethod"
      class="keyness-method"
    />
    <div v-if="keynessCompletenessNotice" class="result-warning" role="status" aria-live="polite">
      {{ keynessCompletenessNotice }}
    </div>
    <div v-if="keynessPagingError" class="result-warning" role="alert">
      {{ keynessPagingError }}
    </div>

    <!-- Config Panel -->
    <div class="config-panel">
      <div v-if="isContrastMode" class="flow-panel">
        <div class="flow-step" :class="{ done: intersectionReady, active: isBuildingIntersection }">
          <div class="flow-step-head">
            <span class="flow-step-index">1</span>
            <div class="flow-step-copy">
              <div class="flow-step-title">{{ t('analysis.keyness.step1Title') }}</div>
              <div class="flow-step-desc">
                {{ t('analysis.keyness.step1Desc') }}
              </div>
            </div>
            <span class="flow-step-badge" :class="`tone-${step1Badge.tone}`">
              {{ step1Badge.label }}
            </span>
          </div>
          <div class="flow-step-note">
            {{ t('analysis.keyness.step1Note') }}
          </div>
          <Button
            variant="ghost"
            size="sm"
            :icon="RefreshCw"
            :loading="isBuildingIntersection"
            @click="buildIntersection(true)"
          >
            {{ t('analysis.keyness.computeIntersection') }}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            :icon="Layers"
            :disabled="!intersectionReady"
            @click="saveIntersectionAsSubcorpora"
          >
            {{ t('analysis.keyness.saveSubcorpora') }}
          </Button>
          <div v-if="intersectionReady" class="flow-step-status" role="status" aria-live="polite">
            {{ t('analysis.keyness.sharedRefDocs', { count: formatNumber(intersectionCount) }) }}
          </div>
          <div v-else-if="isDirty" class="flow-step-hint" role="status" aria-live="polite">
            {{ t('analysis.keyness.filtersChangedShort') }}
          </div>
          <div v-else-if="intersectionError" class="flow-step-hint" role="alert">
            {{ intersectionError }}
          </div>
        </div>

        <div class="flow-divider" />

      <div
        class="flow-step"
        :class="{
          disabled: !intersectionReady,
          active: isLoadingContrastDashboard || isLoadingKeyness || isLoadingCollocDiffs || isLoadingNgramDiffs || isLoadingParallel,
        }"
      >
          <div class="flow-step-head">
            <span class="flow-step-index">2</span>
            <div class="flow-step-copy">
              <div class="flow-step-title">{{ t('analysis.keyness.startContrast') }}</div>
              <div class="flow-step-desc">
                {{ t('analysis.keyness.step2Desc') }}
              </div>
            </div>
            <span class="flow-step-badge" :class="`tone-${step2Badge.tone}`">
              {{ step2Badge.label }}
            </span>
          </div>
          <div class="flow-step-note">
            {{ t('analysis.keyness.step2Note') }}
          </div>
          <Button
            variant="primary"
            size="sm"
            :icon="Scale"
            :loading="isLoadingContrastDashboard"
            :disabled="!intersectionReady || isLoadingKeyness || isLoadingCollocDiffs || isLoadingNgramDiffs || isLoadingParallel"
            @click="loadContrastDashboard"
          >
            {{ t('analysis.keyness.startContrast') }}
          </Button>
          <div v-if="contrastReady" class="flow-step-status">
            {{ t('analysis.keyness.lastComputed') }}
          </div>
        </div>
      </div>

      <div v-if="isContrastMode" class="structure-hint">
        {{ t('analysis.keyness.structure') }}
      </div>

      <div v-if="isContrastMode" class="group-grid">
        <div class="group-card">
          <div class="group-title">{{ t('analysis.keyness.groupNamed', { label: 'A' }) }}</div>
          <FilterField :label="t('analysis.keyness.textTypeLabel')">
            <select v-model="groupA.text_type" class="select" @change="markDirty">
              <option v-for="opt in metaOptions.text_type" :key="`a-${opt}`" :value="opt">
                {{ textTypeLabel(opt) }}{{ optionCount('A', 'text_type', opt) !== null ? ` · ${formatNumber(optionCount('A', 'text_type', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField :label="t('analysis.keyness.promptType')">
            <select v-model="groupA.prompting_method" class="select" @change="markDirty">
              <option value="">{{ t('analysis.keyness.all') }}</option>
              <option
                v-for="opt in metaOptions.prompting_method"
                :key="`a-prompt-${opt}`"
                :value="opt"
                :disabled="optionCount('A', 'prompting_method', opt) === 0"
              >
                {{ opt }}{{ optionCount('A', 'prompting_method', opt) !== null ? ` · ${formatNumber(optionCount('A', 'prompting_method', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField
            :label="t('analysis.keyness.variantLabel')"
            :hint="groupA.prompting_method ? t('analysis.keyness.variantsFor', { method: groupA.prompting_method }) : t('analysis.keyness.compatibleField')"
          >
            <select v-model="groupA.model" multiple size="6" class="select select-multi" @change="markDirty">
              <option
                v-for="opt in groupModelOptions.A"
                :key="`a-model-${opt}`"
                :value="opt"
                :disabled="optionCount('A', 'model', opt) === 0"
              >
                {{ opt }}{{ optionCount('A', 'model', opt) !== null ? ` · ${formatNumber(optionCount('A', 'model', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField :label="t('analysis.keyness.register')">
            <select v-model="groupA.register" multiple size="6" class="select select-multi" @change="markDirty">
              <option
                v-for="opt in metaOptions.register"
                :key="`a-reg-${opt}`"
                :value="opt"
                :disabled="optionCount('A', 'register', opt) === 0"
              >
                {{ opt }}{{ optionCount('A', 'register', opt) !== null ? ` · ${formatNumber(optionCount('A', 'register', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField :label="t('analysis.keyness.source')">
            <select v-model="groupA.source" multiple size="6" class="select select-multi" @change="markDirty">
              <option
                v-for="opt in metaOptions.source"
                :key="`a-source-${opt}`"
                :value="opt"
                :disabled="optionCount('A', 'source', opt) === 0"
              >
                {{ opt }}{{ optionCount('A', 'source', opt) !== null ? ` · ${formatNumber(optionCount('A', 'source', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
        </div>

        <div class="group-card">
          <div class="group-title">{{ t('analysis.keyness.groupNamed', { label: 'B' }) }}</div>
          <FilterField :label="t('analysis.keyness.textTypeLabel')">
            <select v-model="groupB.text_type" class="select" @change="markDirty">
              <option v-for="opt in metaOptions.text_type" :key="`b-${opt}`" :value="opt">
                {{ textTypeLabel(opt) }}{{ optionCount('B', 'text_type', opt) !== null ? ` · ${formatNumber(optionCount('B', 'text_type', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField :label="t('analysis.keyness.promptType')">
            <select v-model="groupB.prompting_method" class="select" @change="markDirty">
              <option value="">{{ t('analysis.keyness.all') }}</option>
              <option
                v-for="opt in metaOptions.prompting_method"
                :key="`b-prompt-${opt}`"
                :value="opt"
                :disabled="optionCount('B', 'prompting_method', opt) === 0"
              >
                {{ opt }}{{ optionCount('B', 'prompting_method', opt) !== null ? ` · ${formatNumber(optionCount('B', 'prompting_method', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField
            :label="t('analysis.keyness.variantLabel')"
            :hint="groupB.prompting_method ? t('analysis.keyness.variantsFor', { method: groupB.prompting_method }) : t('analysis.keyness.compatibleField')"
          >
            <select v-model="groupB.model" multiple size="6" class="select select-multi" @change="markDirty">
              <option
                v-for="opt in groupModelOptions.B"
                :key="`b-model-${opt}`"
                :value="opt"
                :disabled="optionCount('B', 'model', opt) === 0"
              >
                {{ opt }}{{ optionCount('B', 'model', opt) !== null ? ` · ${formatNumber(optionCount('B', 'model', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField :label="t('analysis.keyness.register')">
            <select v-model="groupB.register" multiple size="6" class="select select-multi" @change="markDirty">
              <option
                v-for="opt in metaOptions.register"
                :key="`b-reg-${opt}`"
                :value="opt"
                :disabled="optionCount('B', 'register', opt) === 0"
              >
                {{ opt }}{{ optionCount('B', 'register', opt) !== null ? ` · ${formatNumber(optionCount('B', 'register', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
          <FilterField :label="t('analysis.keyness.source')">
            <select v-model="groupB.source" multiple size="6" class="select select-multi" @change="markDirty">
              <option
                v-for="opt in metaOptions.source"
                :key="`b-source-${opt}`"
                :value="opt"
                :disabled="optionCount('B', 'source', opt) === 0"
              >
                {{ opt }}{{ optionCount('B', 'source', opt) !== null ? ` · ${formatNumber(optionCount('B', 'source', opt) || 0)}` : '' }}
              </option>
            </select>
          </FilterField>
        </div>
      </div>
    </div>

    <div v-if="!isContrastMode" class="summary-panel">
      <div class="summary-head">
        <div class="summary-pill" :class="{ stale: !standaloneTargetDocset }">
          {{ t('analysis.keyness.targetPill', { target: standaloneTargetDocset?.label ?? t('analysis.keyness.noActiveSubcorpus') }) }}
        </div>
        <div v-if="keynessError" class="summary-error" role="alert">
          {{ keynessError }}
          <div class="error-actions">
            <Button variant="ghost" size="sm" :icon="Filter" @click="uiStore.openSubcorpus()">
              {{ t('analysis.shared.checkSubcorpus') }}
            </Button>
          </div>
        </div>
        <div v-else-if="!standaloneTargetDocset" class="summary-hint" role="status">
          {{ t('analysis.keyness.standaloneHint') }}
        </div>
      </div>
    </div>

    <div v-if="isContrastMode" class="summary-panel">
      <div class="summary-head">
        <div class="summary-pill" :class="{ stale: isDirty }">
          {{ t('analysis.keyness.sharedReferences', { count: formatNumber(intersectionCount) }) }}
        </div>
        <div v-if="intersectionError" class="summary-error" role="alert">
          {{ intersectionError }}
        </div>
        <div v-else-if="isDirty" class="summary-hint" role="status" aria-live="polite">
          {{ t('analysis.keyness.filtersChanged') }}
        </div>
      </div>

      <div v-if="docsets.length" class="docset-row">
        <div
          v-for="docset in docsets"
          :key="docset.label"
          class="docset-card"
        >
          <div class="docset-title">
            {{ docset.kind === 'human' ? anchorDocsetName : t('analysis.keyness.groupNamed', { label: docset.label }) }}
          </div>
          <div class="docset-stats">
            {{ t('analysis.shared.docsTokens', { docs: formatNumber(docset.docCount), tokens: formatNumber(docset.tokenCount) }) }}
          </div>
          <div class="docset-id">#{{ shortId(docset.docsetId) }}</div>
        </div>
      </div>

      <div v-if="docsetOptions.length" class="target-row">
        <label class="target-field" for="contrastTargetSelect">
          <span class="field-label">{{ t('analysis.keyness.target') }}</span>
          <select
            v-model="targetLabel"
            class="select"
            id="contrastTargetSelect"
            :aria-label="t('analysis.keyness.targetAria')"
          >
            <option v-for="opt in docsetOptions" :key="`target-${opt.label}`" :value="opt.label">
              {{ opt.title }}
            </option>
          </select>
        </label>
        <div class="vs-label compact">vs.</div>
        <label class="target-field" for="contrastReferenceSelect">
          <span class="field-label">{{ t('analysis.keyness.reference') }}</span>
          <select
            v-model="referenceLabel"
            class="select"
            id="contrastReferenceSelect"
            :aria-label="t('analysis.keyness.referenceAria')"
          >
            <option v-for="opt in docsetOptions" :key="`ref-${opt.label}`" :value="opt.label">
              {{ opt.title }}
            </option>
          </select>
        </label>
        <div v-if="keynessError" class="summary-error" role="alert">
          {{ keynessError }}
          <div class="error-actions">
          <Button variant="ghost" size="sm" :icon="RefreshCw" @click="() => loadKeyness()">
            {{ t('analysis.shared.retry') }}
          </Button>
            <Button variant="ghost" size="sm" :icon="Filter" @click="uiStore.openSubcorpus()">
              {{ t('analysis.shared.checkSubcorpus') }}
            </Button>
          </div>
        </div>
      </div>

      <div v-if="contrastStats" class="contrast-stats">
        <div class="stat-chip">
          {{ t('analysis.keyness.targetStats', { docs: formatNumber(contrastStats.targetDocs), tokens: formatNumber(contrastStats.targetTokens) }) }}
        </div>
        <div class="stat-chip">
          {{ t('analysis.keyness.referenceStats', { docs: formatNumber(contrastStats.referenceDocs), tokens: formatNumber(contrastStats.referenceTokens) }) }}
        </div>
        <div
          class="stat-chip delta"
          :class="{ positive: contrastStats.tokenDiff >= 0, negative: contrastStats.tokenDiff < 0 }"
        >
          {{ t('analysis.keyness.tokenDelta', { delta: formatNumber(contrastStats.tokenDiff), percent: formatPercent(contrastStats.tokenDiffPct) }) }}
        </div>
        <div
          class="stat-chip delta"
          :class="{ positive: contrastStats.docDiff >= 0, negative: contrastStats.docDiff < 0 }"
        >
          {{ t('analysis.keyness.docDelta', { delta: formatNumber(contrastStats.docDiff), percent: formatPercent(contrastStats.docDiffPct) }) }}
        </div>
      </div>
    </div>

    <!-- F4: Lexical-Diversity card (prominent in the Human-vs-AI compare view) -->
    <div v-if="isContrastMode && hasDiversitySides" class="diversity-panel">
      <LexicalDiversityCard
        :corpus="activeCorpus"
        :target-docset-id="diversityTargetDocsetId"
        :reference-docset-id="diversityReferenceDocsetId"
        :target-label="targetLabel"
        :reference-label="referenceLabel"
        :auto-load="true"
      />
    </div>

    <div v-if="isContrastMode && (isLoadingDiffs || diffRows.length || diffError)" class="diff-panel">
      <div class="diff-head">
        <div class="diff-title">{{ t('analysis.keyness.diffTitle') }}</div>
        <div class="diff-hint">{{ t('analysis.keyness.diffHint', { count: diffRows.length || DIFF_TOP_N }) }}</div>
      </div>
      <p v-if="frequencyDiffUsesCompleteUnion" class="diff-method" role="status">
        {{ t('analysis.keyness.completeUnion') }}
      </p>
      <div v-if="frequencyDiffCompletenessNotice" class="result-warning compact" role="status" aria-live="polite">
        {{ frequencyDiffCompletenessNotice }}
      </div>
      <div v-if="isLoadingDiffs" class="diff-loading">
        {{ t('analysis.keyness.computingDiffs') }}
      </div>
      <div v-else-if="diffError" class="diff-error">
        {{ diffError }}
        <div class="error-actions">
          <Button variant="ghost" size="sm" :icon="RefreshCw" @click="loadFrequencyDiffs">
            {{ t('analysis.shared.retry') }}
          </Button>
          <Button variant="ghost" size="sm" :icon="Filter" @click="uiStore.openSubcorpus()">
            {{ t('analysis.shared.checkSubcorpus') }}
          </Button>
        </div>
      </div>
      <div v-else class="diff-table-wrap">
        <table class="diff-table">
          <thead>
            <tr>
              <th>{{ t('analysis.keyness.word') }}</th>
              <th class="num">{{ t('analysis.keyness.targetPerMillion') }}</th>
              <th class="num">{{ t('analysis.keyness.refPerMillion') }}</th>
              <th class="num">{{ t('analysis.keyness.deltaPerMillionHeader') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in diffRows" :key="`diff-${row.word}`">
              <td class="word">{{ row.word }}</td>
              <td class="num">{{ formatPerMillion(row.targetPerMillion) }}</td>
              <td class="num">{{ formatPerMillion(row.referencePerMillion) }}</td>
              <td class="num delta" :class="{ positive: row.diffPerMillion >= 0, negative: row.diffPerMillion < 0 }">
                {{ formatPerMillion(row.diffPerMillion) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div v-if="isContrastMode" class="contrast-panel">
      <div class="panel-head">
        <div class="panel-title">
          <Network class="w-4 h-4" />
          {{ t('analysis.keyness.collocContrast') }}
        </div>
        <div class="panel-actions">
          <label class="panel-field">
            <span>{{ t('analysis.keyness.window') }}</span>
            <input v-model.number="collocWindow" type="number" min="1" max="12" />
          </label>
          <label class="panel-field" :title="t('analysis.collocations.withinSentenceTitle')">
            <input v-model="collocWithinSentence" type="checkbox" />
            <span>{{ t('analysis.measureOptions.withinSentence') }}</span>
          </label>
          <label class="panel-field">
            <span>Score</span>
            <select v-model="collocMeasure">
              <option value="logdice">Log-Dice</option>
              <option value="mi">MI</option>
              <option value="lmi">LMI</option>
              <option value="npmi">NPMI</option>
              <option value="z">{{ t('analysis.measureOptions.zScore') }}</option>
              <option value="tscore">{{ t('analysis.measureOptions.tScore') }}</option>
            </select>
          </label>
          <MeasureInfo :measure-key="collocMeasure" :method="collocDiffMethod" />
          <Button variant="ghost" size="sm" :icon="Network" :loading="isLoadingCollocDiffs" @click="loadCollocationDiffs">
            {{ t('analysis.keyness.compute') }}
          </Button>
        </div>
      </div>
      <div v-if="!queryStore.term" class="panel-hint" role="status" aria-live="polite">
        {{ t('analysis.keyness.collocNeedSearch') }}
      </div>
      <div v-else-if="isLoadingCollocDiffs" class="panel-loading" role="status" aria-live="polite">
        {{ t('analysis.keyness.collocLoading') }}
      </div>
      <div v-else-if="collocDiffError" class="panel-error" role="alert">
        {{ collocDiffError }}
        <div class="error-actions">
          <Button variant="ghost" size="sm" :icon="RefreshCw" @click="loadCollocationDiffs">
            {{ t('analysis.shared.retry') }}
          </Button>
          <Button variant="ghost" size="sm" :icon="Filter" @click="uiStore.openSubcorpus()">
            {{ t('analysis.shared.checkSubcorpus') }}
          </Button>
        </div>
      </div>
      <div v-else-if="collocDiffRows.length" class="panel-table-wrap">
        <table class="panel-table">
          <thead>
            <tr>
              <th>{{ t('analysis.keyness.word') }}</th>
              <th class="num">{{ t('analysis.keyness.targetPerMillion') }}</th>
              <th class="num">{{ t('analysis.keyness.refPerMillion') }}</th>
              <th class="num">{{ t('analysis.keyness.deltaPerMillionHeader') }}</th>
              <th class="num">{{ t('analysis.keyness.deltaScore') }}</th>
              <th class="action">KWIC</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in collocDiffRows" :key="`colloc-${row.word}`">
              <td class="word">{{ row.word }}</td>
              <td class="num">{{ formatPerMillion(row.targetPerMillion) }}</td>
              <td class="num">{{ formatPerMillion(row.referencePerMillion) }}</td>
              <td class="num delta" :class="{ positive: row.diffPerMillion >= 0, negative: row.diffPerMillion < 0 }">
                {{ formatPerMillion(row.diffPerMillion) }}
              </td>
              <td class="num">{{ formatDecimal(row.diffScore, 3) }}</td>
              <td class="action">
                <button class="link-btn" type="button" @click="openCooccurrenceKwic(row.word)">
                  KWIC
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="panel-hint" role="status" aria-live="polite">
        {{ t('analysis.keyness.collocEmpty') }}
      </div>
    </div>

    <div v-if="isContrastMode" class="contrast-panel">
      <div class="panel-head">
        <div class="panel-title">
          <Hash class="w-4 h-4" />
          {{ t('analysis.keyness.ngramContrast') }}
        </div>
        <div class="panel-actions">
          <label class="panel-field">
            <span>N</span>
            <select v-model="ngramSize">
              <option :value="2">2</option>
              <option :value="3">3</option>
              <option :value="4">4</option>
              <option :value="5">5</option>
            </select>
          </label>
          <label class="panel-field">
            <span>{{ t('analysis.keyness.minFreqShort') }}</span>
            <input v-model.number="ngramMinFreq" type="number" min="1" max="9999" />
          </label>
          <Button variant="ghost" size="sm" :icon="Hash" :loading="isLoadingNgramDiffs" @click="loadNgramDiffs">
            {{ t('analysis.keyness.compute') }}
          </Button>
        </div>
      </div>
      <div v-if="isLoadingNgramDiffs" class="panel-loading" role="status" aria-live="polite">
        {{ t('analysis.keyness.ngramLoading') }}
      </div>
      <div v-else-if="ngramDiffError" class="panel-error" role="alert">
        {{ ngramDiffError }}
        <div class="error-actions">
          <Button variant="ghost" size="sm" :icon="RefreshCw" @click="loadNgramDiffs">
            {{ t('analysis.shared.retry') }}
          </Button>
          <Button variant="ghost" size="sm" :icon="Filter" @click="uiStore.openSubcorpus()">
            {{ t('analysis.shared.checkSubcorpus') }}
          </Button>
        </div>
      </div>
      <div v-else-if="ngramDiffRows.length" class="panel-table-wrap">
        <table class="panel-table">
          <thead>
            <tr>
              <th>{{ t('analysis.keyness.ngram') }}</th>
              <th class="num">{{ t('analysis.keyness.targetPerMillion') }}</th>
              <th class="num">{{ t('analysis.keyness.refPerMillion') }}</th>
              <th class="num">{{ t('analysis.keyness.deltaPerMillionHeader') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in ngramDiffRows" :key="`ngram-${row.ngram}`">
              <td class="word">{{ row.ngram }}</td>
              <td class="num">{{ formatPerMillion(row.targetPerMillion) }}</td>
              <td class="num">{{ formatPerMillion(row.referencePerMillion) }}</td>
              <td class="num delta" :class="{ positive: row.diffPerMillion >= 0, negative: row.diffPerMillion < 0 }">
                {{ formatPerMillion(row.diffPerMillion) }}
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-else class="panel-hint" role="status" aria-live="polite">
        {{ t('analysis.keyness.ngramEmpty') }}
      </div>
    </div>

    <div v-if="isContrastMode && canUseParallel" class="contrast-panel">
      <div class="panel-head">
        <div class="panel-title">
          <Layers class="w-4 h-4" />
          {{ t('analysis.keyness.parallelExplorer') }}
        </div>
        <div class="panel-actions">
          <label class="panel-field" for="parallelBasisSelect">
            <span>{{ t('analysis.keyness.basis') }}</span>
            <select
              v-model="parallelBasisLabel"
              id="parallelBasisSelect"
              :aria-label="t('analysis.keyness.basisAria')"
            >
              <option v-for="opt in docsetOptions" :key="`basis-${opt.label}`" :value="opt.label">
                {{ opt.title }}
              </option>
            </select>
          </label>
          <label class="panel-field" for="parallelSortSelect">
            <span>{{ t('analysis.keyness.sort') }}</span>
            <select
              v-model="parallelSort"
              id="parallelSortSelect"
              :aria-label="t('analysis.keyness.sortAria')"
            >
              <option value="variant_count">{{ t('analysis.keyness.variants') }}</option>
              <option value="ref_doc">ref_doc</option>
            </select>
          </label>
          <label class="panel-field" for="parallelIncludeVariants">
            <input v-model="parallelIncludeVariants" type="checkbox" id="parallelIncludeVariants" />
            <span>{{ t('analysis.keyness.allVariants') }}</span>
          </label>
          <label class="panel-field" for="parallelLimitInput">
            <span>{{ t('analysis.keyness.limit') }}</span>
            <input
              v-model.number="parallelLimit"
              type="number"
              min="10"
              max="500"
              id="parallelLimitInput"
              :aria-label="t('analysis.keyness.limitAria')"
            />
          </label>
          <Button variant="ghost" size="sm" :icon="Layers" :loading="isLoadingParallel" @click="loadParallelGroups">
            {{ t('analysis.keyness.load') }}
          </Button>
        </div>
      </div>
      <p class="panel-hint">
        {{ t('analysis.keyness.pairingEvidence', { axes: parallelPairAxesLabel, contract: parallelExecutionContractLabel }) }}
      </p>
      <div v-if="isLoadingParallel" class="panel-loading" role="status" aria-live="polite">
        {{ t('analysis.keyness.parallelLoading') }}
      </div>
      <div v-else-if="parallelError" class="panel-error" role="alert">
        {{ parallelError }}
      </div>
      <div v-else-if="parallelGroups.length" class="panel-table-wrap">
        <table class="panel-table">
          <thead>
            <tr>
              <th>ref_doc</th>
              <th class="num">{{ t('analysis.keyness.docs') }}</th>
              <th>{{ parallelVariantColumnLabel }}</th>
              <th>{{ t('analysis.keyness.sources') }}</th>
              <th class="action">Alignment</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="group in parallelGroups" :key="`parallel-${group.ref_doc}`">
              <td class="word">
                #{{ group.ref_doc }}
                <span v-if="group.label" class="muted">· {{ group.label }}</span>
              </td>
              <td class="num">{{ group.doc_count }}</td>
              <td>{{ formatParallelVariantCounts(group.models) }}</td>
              <td>{{ formatSources(group.sources) }}</td>
              <td class="action">
                <button class="link-btn" type="button" @click="openParallelAlignment(group.ref_doc)">
                  Alignment
                </button>
              </td>
            </tr>
          </tbody>
        </table>
        <div v-if="parallelTotal > parallelGroups.length" class="panel-hint" role="status" aria-live="polite">
          {{ t('analysis.keyness.groupsShown', { shown: parallelGroups.length, total: formatNumber(parallelTotal) }) }}
        </div>
      </div>
      <div v-else class="panel-hint" role="status" aria-live="polite">
        {{ t('analysis.keyness.parallelEmpty') }}
      </div>
    </div>

    <!-- Results Table -->
    <div ref="keynessTableContainerRef" class="table-container">
      <i18n-t v-if="!isLoadingKeyness && lowReliabilityCount > 0" keypath="analysis.keyness.reliabilitySummary" tag="div" class="reliability-summary" scope="global">
        <template #count>{{ lowReliabilityCount }}</template>
        <template #total>{{ data.length }}</template>
        <template #low><strong>{{ t('analysis.keyness.lowReliable') }}</strong></template>
      </i18n-t>
      <table v-if="!isLoadingKeyness && data.length > 0" class="keyness-table">
        <thead>
          <tr>
            <th class="col-rank">#</th>
            <th class="col-word">{{ t('analysis.keyness.word') }}</th>
            <th class="col-metric" @click="handleMetricSort('ll_signed')">
              <span>{{ t('analysis.keyness.signedLl') }}</span>
              <ArrowUpDown v-if="metric === 'll_signed'" class="w-3.5 h-3.5 ml-1" />
            </th>
            <th class="col-metric" :title="t('analysis.keyness.logRatioTitle')" @click="handleMetricSort('log_ratio')">
              <span>{{ t('analysis.keyness.logRatioCi') }}</span>
              <ArrowUpDown v-if="metric === 'log_ratio'" class="w-3.5 h-3.5 ml-1" />
            </th>
            <th
              v-if="hasFullChi2"
              class="col-metric"
              :title="t('analysis.keyness.chi2FullTitle')"
              @click="handleMetricSort('chi2')"
            >
              <span>χ² (2x2 Pearson)</span><!-- i18n-ignore: statistic name, same in both languages -->
              <ArrowUpDown v-if="metric === 'chi2'" class="w-3.5 h-3.5 ml-1" />
            </th>
            <th class="col-metric" :title="t('analysis.keyness.chi2CellTitle')" @click="handleMetricSort('chi2_cell')">
              <span>{{ t('analysis.keyness.chi2CellColumn') }}</span>
              <ArrowUpDown v-if="metric === 'chi2_cell'" class="w-3.5 h-3.5 ml-1" />
            </th>
            <th class="col-metric" :title="t('analysis.keyness.pTitle')">p</th>
            <th class="col-metric" :title="t('analysis.keyness.qTitle')">q (FDR)</th>
            <th class="col-metric">{{ t('analysis.keyness.direction') }}</th>
            <th class="col-bar">{{ t('analysis.keyness.visualization') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="keynessTopPadding > 0" class="virtual-spacer" aria-hidden="true">
            <td :colspan="keynessColumnCount" :style="{ height: `${keynessTopPadding}px` }" />
          </tr>
          <tr v-for="{ row, virtualRow } in virtualKeynessRows" :key="row.word">
            <td class="col-rank">{{ virtualRow.index + 1 }}</td>
            <td class="col-word">
              {{ row.word }}
              <span
                v-if="row.low_reliability"
                class="reliability-badge"
                :title="row.p_method ? t('analysis.keyness.lowReliabilityTitleMethod', { method: row.p_method }) : t('analysis.keyness.lowReliabilityTitle')"
              >
                {{ t('analysis.keyness.lowBadge') }}
              </span>
            </td>
            <td class="col-metric">
              {{ formatDecimal(typeof row.ll_signed === 'number' ? row.ll_signed : llSignedValue(row), 2) }}
            </td>
            <td class="col-metric col-interval">
              {{ formatLogRatio(row) }}
            </td>
            <td v-if="hasFullChi2" class="col-metric">
              {{ typeof row.chi2 === 'number' ? formatDecimal(chi2Value(row), 4) : '–' }}
            </td>
            <td class="col-metric">
              {{ formatDecimal(chi2CellValue(row), 4) }}
            </td>
            <td class="col-metric">
              {{ formatPValue(row.p_value) }}
            </td>
            <td class="col-metric">
              {{ formatPValue(row.q_value) }}
            </td>
            <td class="col-metric">
              <span :class="['direction-pill', row.direction === 'reference' ? 'reference' : 'target']">
                {{ row.direction === 'reference' ? t('analysis.keyness.directionReference') : t('analysis.keyness.directionTarget') }}
              </span>
              <span v-if="typeof row.diff_per_million === 'number'" class="muted">
                {{ t('analysis.keyness.deltaPerMillion', { value: formatDecimal(row.diff_per_million, 1) }) }}
              </span>
            </td>
            <td class="col-bar">
              <div class="keyness-bar-container">
                <div
                  class="keyness-bar"
                  :class="{ active: metricValue(row) > 0, negative: metricValue(row) < 0 }"
                  :style="{ width: `${metricWidth(row)}%` }"
                />
              </div>
            </td>
          </tr>
          <tr v-if="keynessBottomPadding > 0" class="virtual-spacer" aria-hidden="true">
            <td :colspan="keynessColumnCount" :style="{ height: `${keynessBottomPadding}px` }" />
          </tr>
          <tr v-if="hasMoreKeynessRows || isLoadingMoreKeyness" class="load-more-row">
            <td :colspan="keynessColumnCount">
              <div class="load-more">
                <span v-if="isLoadingMoreKeyness">{{ t('analysis.keyness.loadingMore') }}</span>
                <button
                  v-else
                  type="button"
                  class="link-btn"
                  :aria-label="t('analysis.keyness.loadMore')"
                  @click="loadMoreKeynessRows"
                >
                  {{ t('analysis.keyness.loadMore') }}
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
      <i18n-t v-if="!isLoadingKeyness && data.length > 0" keypath="analysis.keyness.legend" tag="p" class="keyness-legend" scope="global">
        <template #logRatio><strong>{{ t('analysis.keyness.logRatio') }}</strong></template>
        <template #q><strong>q (FDR)</strong></template>
      </i18n-t>

      <!-- Loading -->
      <div v-else-if="isLoadingKeyness" class="loading-state">
        <Skeleton v-for="i in 10" :key="i" height="2.5rem" class="mb-2" />
      </div>

      <!-- Empty State -->
      <EmptyState
        v-else
        :icon="Scale"
        :title="t('analysis.keyness.emptyTitle')"
        :description="t('analysis.keyness.emptyDescription')"
        size="sm"
      />
    </div>

    <Modal
      v-model="exportOpen"
      :title="t('analysis.keyness.exportTitle')"
      :description="t('analysis.keyness.exportDescription')"
    >
      <div class="export-modal">
        <label class="export-option">
          <input v-model="exportKeyness" type="checkbox" :disabled="!data.length" />
          <span>Keyness</span>
          <span class="export-count">{{ data.length }}</span>
        </label>
        <label class="export-option">
          <input v-model="exportDiffs" type="checkbox" :disabled="!diffRows.length" />
          <span>{{ t('analysis.keyness.exportFrequency') }}</span>
          <span class="export-count">{{ diffRows.length }}</span>
        </label>
        <label class="export-option">
          <input v-model="exportCollocs" type="checkbox" :disabled="!collocDiffRows.length" />
          <span>{{ t('analysis.keyness.exportCollocations') }}</span>
          <span class="export-count">{{ collocDiffRows.length }}</span>
        </label>
        <label class="export-option">
          <input v-model="exportNgrams" type="checkbox" :disabled="!ngramDiffRows.length" />
          <span>{{ t('analysis.keyness.exportNgrams') }}</span>
          <span class="export-count">{{ ngramDiffRows.length }}</span>
        </label>
        <label class="export-option export-option--meta">
          <input v-model="exportIncludeMeta" type="checkbox" />
          <span>{{ t('analysis.keyness.exportIncludeMeta') }}</span>
        </label>

        <div class="export-actions">
          <Button variant="ghost" size="sm" @click="exportOpen = false">{{ t('analysis.keyness.cancel') }}</Button>
          <Button variant="primary" size="sm" @click="exportCsv">{{ t('analysis.keyness.export') }}</Button>
        </div>
      </div>
    </Modal>

    <Modal
      v-model="isParallelModalOpen"
      size="xl"
      :title="t('analysis.keyness.variantsModalTitle')"
      :description="t('analysis.keyness.variantsModalDescription')"
      @close="closeParallelModal"
    >
      <div v-if="isLoadingParallelAlignment" class="panel-loading" role="status" aria-live="polite">
        {{ t('analysis.keyness.variantsLoading') }}
      </div>
      <div v-else-if="parallelAlignmentError" class="panel-error" role="alert">
        {{ parallelAlignmentError }}
      </div>
      <AlignmentComparison v-else-if="parallelAlignmentResult" :result="parallelAlignmentResult" />
      <div v-else class="panel-hint" role="status" aria-live="polite">
        {{ t('analysis.keyness.noAlignment') }}
      </div>
    </Modal>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.keyness-tab {
  /* At least as high as the tab, grows with its content: the tab area
     scrolls (App.vue .tab-content). */
  @apply flex flex-col min-h-full;
}

.config-panel {
  @apply p-4 space-y-4;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.config-row {
  @apply flex items-center gap-4;
}

.actions-row {
  @apply justify-between;
}

.scope-row {
  @apply flex flex-wrap items-center justify-between gap-3;
}

.scope-pill {
  @apply px-3 py-1 rounded-full text-xs md:text-sm font-medium;
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-pill.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.scope-pill-muted {
  @apply bg-neutral-100 text-neutral-600;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.flow-panel {
  @apply grid gap-4;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  @apply p-3 rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
}

.flow-step {
  @apply flex flex-col gap-2;
}

.flow-step-head {
  @apply flex items-center gap-3;
}

.flow-step-index {
  @apply w-7 h-7 rounded-full flex items-center justify-center text-xs font-semibold;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.flow-step-copy {
  @apply flex flex-col gap-0.5;
}

.flow-step-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.flow-step-desc {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.flow-step-badge {
  @apply ml-auto px-2.5 py-1 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-neutral-100 text-neutral-500;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.flow-step-badge.tone-done {
  @apply bg-emerald-100 text-emerald-800;
  @apply dark:bg-emerald-900/40 dark:text-emerald-200;
}

.flow-step-badge.tone-warn {
  @apply bg-amber-100 text-amber-800;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.flow-step-badge.tone-muted {
  @apply bg-neutral-100 text-neutral-500;
  @apply dark:bg-neutral-800 dark:text-neutral-400;
}

.flow-step-badge.tone-idle {
  @apply bg-neutral-100 text-neutral-500;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.flow-step-note {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.flow-step-status {
  @apply text-xs text-success-600 dark:text-success-400 font-medium;
}

.flow-step-hint {
  @apply text-xs text-amber-600 dark:text-amber-300;
}

.flow-step.disabled {
  @apply opacity-60;
}

.flow-divider {
  @apply hidden;
}

.structure-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
  @apply mb-2;
}

.group-grid {
  @apply grid gap-4;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
}

.group-card {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply p-3 space-y-3;
}

.export-modal {
  @apply flex flex-col gap-3;
}

.export-option {
  @apply flex items-center gap-3 text-sm text-neutral-700 dark:text-neutral-200;
  @apply px-2 py-1 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-900/60;
}

.export-option--meta {
  @apply text-xs text-neutral-600 dark:text-neutral-400;
}

.export-count {
  @apply ml-auto text-[11px] text-neutral-500 dark:text-neutral-400;
}

.export-actions {
  @apply flex items-center justify-end gap-2;
}

.group-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.config-item {
  @apply flex-1;
}

.config-item label {
  @apply block text-xs font-medium uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400 mb-1;
}

.config-item select {
  @apply w-full px-3 py-2 rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm;
}

.vs-label {
  @apply text-neutral-400 dark:text-neutral-600 font-medium;
  @apply pt-5;
}

.vs-label.compact {
  @apply pt-0 self-end pb-2;
}

.method-selector {
  @apply flex gap-4;
}

.method-option {
  @apply flex items-center gap-2 cursor-pointer;
  @apply text-sm text-neutral-700 dark:text-neutral-300;
}

.method-option input {
  @apply text-primary-600;
}

.method-note {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.method-note--limit {
  @apply rounded-lg border border-amber-200 bg-amber-50/70 px-2 py-1 text-amber-800;
  @apply dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200;
}

.result-warning {
  @apply mx-4 mt-3 px-3 py-2 rounded-lg text-xs font-medium;
  @apply bg-amber-50 text-amber-800 border border-amber-200;
  @apply dark:bg-amber-950/30 dark:text-amber-200 dark:border-amber-800;
}

.result-warning.compact {
  @apply mx-0 mt-0;
}

/* Keyness reference-source + min-freq controls (FT-KEYNESS-RESEARCH) */
.keyness-reference {
  @apply flex flex-wrap items-end gap-3;
}

.ref-field {
  @apply flex flex-col gap-1;
}

.ref-label {
  @apply text-[11px] uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.ref-select,
.ref-input {
  @apply px-2 py-1 rounded-md text-sm;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500;
}

.ref-input--num {
  @apply w-20;
}

.reliability-badge {
  @apply ml-1.5 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-semibold;
  @apply bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200;
}

.reliability-summary {
  @apply mb-3 px-3 py-2 rounded-md text-xs;
  @apply bg-amber-50 text-amber-800 dark:bg-amber-900/30 dark:text-amber-200;
  @apply border border-amber-200 dark:border-amber-800;
}

.config-actions {
  @apply flex flex-wrap gap-2 ml-auto;
}

.field {
  @apply flex flex-col gap-1.5;
}

.field-label {
  @apply text-xs font-medium uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
}

.field-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400 mt-1;
}

.select {
  @apply w-full px-3 py-2 rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.select-multi {
  min-height: 132px;
}

.summary-panel {
  @apply px-4 py-3 border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
  @apply flex flex-col gap-3;
}

.summary-head {
  @apply flex flex-wrap items-center gap-3;
}

.summary-pill {
  @apply px-3 py-1 rounded-full text-xs md:text-sm font-medium;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.summary-pill.stale {
  @apply ring-1 ring-amber-400/70;
}

.summary-hint {
  @apply text-xs text-amber-600 dark:text-amber-400;
}

.summary-error {
  @apply text-sm text-error-600 dark:text-error-400;
}

.error-actions {
  @apply mt-2 flex flex-wrap gap-2;
}

.docset-row {
  @apply grid gap-3;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
}

.docset-card {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800/60;
  @apply px-3 py-2 space-y-0.5;
}

.docset-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.docset-stats {
  @apply text-xs text-neutral-600 dark:text-neutral-300;
}

.docset-id {
  @apply text-[11px] font-mono text-neutral-500 dark:text-neutral-400;
}

.target-row {
  @apply flex flex-wrap items-end gap-3;
}

.target-field {
  @apply flex-1 min-w-[180px] flex flex-col gap-1;
}

.contrast-stats {
  @apply flex flex-wrap gap-2;
}

.stat-chip {
  @apply px-3 py-1.5 rounded-full text-xs md:text-sm font-medium;
  @apply bg-neutral-100 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-200;
}

.stat-chip.delta.positive {
  @apply bg-emerald-100 text-emerald-800;
  @apply dark:bg-emerald-900/40 dark:text-emerald-300;
}

.stat-chip.delta.negative {
  @apply bg-rose-100 text-rose-800;
  @apply dark:bg-rose-900/40 dark:text-rose-300;
}

.diversity-panel {
  @apply px-4 py-3 border-b border-neutral-200 dark:border-neutral-800;
}

.diff-panel {
  @apply px-4 py-3 border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-neutral-50 dark:bg-neutral-900;
  @apply flex flex-col gap-2;
}

.diff-head {
  @apply flex flex-wrap items-center justify-between gap-2;
}

.diff-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.diff-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.diff-method {
  @apply text-xs text-neutral-600 dark:text-neutral-300;
}

.diff-loading,
.diff-error {
  @apply text-sm px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.diff-loading {
  @apply text-neutral-600 dark:text-neutral-300;
}

.diff-error {
  @apply text-error-600 dark:text-error-400;
}

.diff-table-wrap {
  @apply overflow-auto rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
}

.diff-table {
  @apply w-full border-collapse text-sm;
}

.diff-table th,
.diff-table td {
  @apply px-3 py-2 border-b border-neutral-200 dark:border-neutral-800;
}

.diff-table th {
  @apply text-xs uppercase tracking-wider text-neutral-500 dark:text-neutral-400;
  @apply bg-neutral-50 dark:bg-neutral-800/60;
}

.diff-table td.word {
  @apply font-medium text-neutral-800 dark:text-neutral-100;
}

.diff-table td.num,
.diff-table th.num {
  @apply text-right font-mono;
}

.diff-table td.delta.positive {
  @apply text-emerald-700 dark:text-emerald-300;
}

.diff-table td.delta.negative {
  @apply text-rose-700 dark:text-rose-300;
}

.contrast-panel {
  @apply px-4 py-3 border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
  @apply flex flex-col gap-2;
}

.panel-head {
  @apply flex flex-wrap items-center justify-between gap-3;
}

.panel-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
  @apply flex items-center gap-2;
}

.panel-actions {
  @apply flex flex-wrap items-center gap-2 ml-auto;
}

.panel-field {
  @apply flex items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400;
}

.panel-field input[type='number'],
.panel-field input[type='text'],
.panel-field select {
  @apply px-2 py-1.5 rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm text-neutral-700 dark:text-neutral-200;
}

.panel-field input[type='checkbox'] {
  @apply accent-primary-600;
}

.panel-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.panel-loading,
.panel-error {
  @apply text-sm px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.panel-loading {
  @apply text-neutral-600 dark:text-neutral-300;
}

.panel-error {
  @apply text-error-600 dark:text-error-400;
}

.panel-table-wrap {
  @apply overflow-auto rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
}

.panel-table {
  @apply w-full border-collapse text-sm;
}

.panel-table th,
.panel-table td {
  @apply px-3 py-2 border-b border-neutral-200 dark:border-neutral-800;
}

.panel-table th {
  @apply text-xs uppercase tracking-wider text-neutral-500 dark:text-neutral-400;
  @apply bg-neutral-50 dark:bg-neutral-800/60;
}

.panel-table td.word {
  @apply font-medium text-neutral-800 dark:text-neutral-100;
}

.panel-table td.num,
.panel-table th.num {
  @apply text-right font-mono;
}

.panel-table th.action,
.panel-table td.action {
  @apply text-center;
}

.panel-table td.delta.positive {
  @apply text-emerald-700 dark:text-emerald-300;
}

.panel-table td.delta.negative {
  @apply text-rose-700 dark:text-rose-300;
}

.link-btn {
  @apply text-xs font-medium text-primary-600 hover:text-primary-700 hover:underline;
  @apply dark:text-primary-300 dark:hover:text-primary-200;
}

.muted {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.table-container {
  /* Result table: its natural height, at most the visible tab (100cqh).
     Toolbars above it scroll away with the tab. */
  flex: 1 0 auto;
  max-height: 100cqh;
  /* No top padding: the sticky header row closes flush with the tab. */
  @apply overflow-auto px-4 pb-4;
}

.keyness-table {
  @apply w-full border-collapse;
}

.keyness-table th,
.keyness-table td {
  @apply px-4 py-3;
  @apply text-left;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.keyness-table th {
  @apply text-xs font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply sticky top-0;
}

.keyness-table th.col-metric {
  @apply cursor-pointer whitespace-nowrap;
}

/* A flex th leaves the table layout and stacks the header cells vertically. */
.keyness-table th.col-metric > svg {
  @apply inline-block align-middle;
}

.keyness-table tbody tr:hover {
  @apply bg-neutral-50 dark:bg-neutral-800/50;
}

.keyness-table tbody tr.virtual-spacer:hover {
  @apply bg-transparent;
}

.keyness-table .virtual-spacer td {
  @apply p-0 border-0;
}

.load-more-row td {
  @apply px-3 md:px-4 py-3;
}

.load-more {
  @apply flex items-center justify-center text-sm text-neutral-500 dark:text-neutral-400;
}

.col-rank {
  @apply w-12 text-center text-neutral-500;
}

.col-word {
  @apply font-medium;
}

.col-metric {
  @apply w-32 text-right font-mono font-medium;
  @apply text-neutral-700 dark:text-neutral-300;
}

/* Value and interval on one line ("3,96 (3,4 bis 4,5)"). */
.col-interval {
  @apply whitespace-nowrap;
}

.direction-pill {
  @apply inline-flex items-center justify-center rounded-full px-2 py-0.5 mr-1;
  @apply text-[11px] font-semibold;
}

.direction-pill.target {
  @apply bg-emerald-100 text-emerald-800;
  @apply dark:bg-emerald-900/40 dark:text-emerald-300;
}

.direction-pill.reference {
  @apply bg-rose-100 text-rose-800;
  @apply dark:bg-rose-900/40 dark:text-rose-300;
}

.col-bar {
  @apply w-40;
}

.keyness-bar-container {
  @apply h-4 rounded-full overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.keyness-bar {
  @apply h-full rounded-full;
  transition: width 0.3s ease;
  @apply bg-neutral-400 dark:bg-neutral-600;
}

.keyness-bar.active {
  @apply bg-primary-500;
}

.keyness-bar.negative {
  @apply bg-error-500;
}

.keyness-legend {
  @apply px-3 md:px-4 py-2 text-xs text-neutral-500 dark:text-neutral-400;
}

.loading-state {
  @apply space-y-2;
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
}
</style>
