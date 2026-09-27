<script setup lang="ts">
/**
 * KwicTable - Virtualized KWIC concordance table
 * 
 * Features:
 * - TanStack Virtual for 100k+ rows
 * - Row selection (single/multi)
 * - Copilot highlighting
 * - Context expansion
 * - Keyboard navigation
 */
import { ref, computed, onMounted, onUnmounted, watch, nextTick, useId, type ComponentPublicInstance } from 'vue'
import { useVirtualizer } from '@tanstack/vue-virtual'
import {
  useDocsetStore,
  useQueryStore,
  useUiStore,
  useSubcorporaStore,
  useParallelPresetsStore,
  useAnnotationsStore,
  useCorpusCapabilitiesStore,
  useSettingsStore,
  rowIdFor,
} from '@/stores'
import { useActions, useElementRegistry, useMobileDetection, useVimNavigation } from '@/composables'
import { useAnnounce } from '@/composables/useAnnounce'
import { useDocumentAccessOperations } from '@/composables/useDocumentAccessOperations'
import { useParallelOperations } from '@/composables/useParallelOperations'
import { useQueryOperations } from '@/composables/useQueryOperations'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { actionBus } from '@/actions'
import type { QueryFilters } from '@/actions/types'
import {
  executeSampledQuery,
  type DocSnippet,
  type AlignmentRefDocResult,
  type KwicSampleProvenance,
  type ParallelKwicResult,
  type ParallelKwicVariant,
  type QueryHit,
} from '@/api/client'
import {
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Copy,
  ClipboardList,
  FileText,
  Maximize2,
  Layers,
  Loader2,
  RefreshCw,
  RotateCcw,
  Pin,
  PinOff,
  Save,
  Star,
  Trash2,
  Tag,
  Tags,
  StickyNote,
  Filter,
  X,
} from 'lucide-vue-next'
import { quickHash } from '@/utils/hashing'
import { extractApiDetail, translateHttpError } from '@/utils/apiError'
import { buildCoKwicQuery, parseCoKwicQuery } from '@/utils/coKwic'
import { kwicSpanDisplay, type KwicSpanDisplay } from '@/utils/kwicSpan'
import { readRowSpacing, type TextSpan } from '@/utils/sourceSpacing'
import {
  alignmentPairAxesLabel,
  alignmentVariantControlLabel,
} from '@/lib/corpusFeatureOptions'
import {
  copyTextToClipboard,
  formatKwicLine,
  formatKwicLineWithCitation,
  formatKwicTsv,
  formatSampleProvenance,
  type KwicCitationRow,
} from '@/lib/kwicCitation'
import Modal from '@/components/ui/Modal.vue'
import AnnotationSchemeEditor from '@/components/search/AnnotationSchemeEditor.vue'
import AlignmentComparison from '@/components/search/AlignmentComparison.vue'
import BackPathChip from '@/components/search/BackPathChip.vue'
import { formatNumber } from '@/i18n/format'
import { textTypeLabel } from '@/lib/pairSides'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const queryStore = useQueryStore()
const uiStore = useUiStore()
const docsetStore = useDocsetStore()
const subcorporaStore = useSubcorporaStore()
const parallelPresetsStore = useParallelPresetsStore()
const annotationsStore = useAnnotationsStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const productCapabilities = useProductCapabilitiesStore()
const settingsStore = useSettingsStore()
const {
  loadDocSnippet,
} = useDocumentAccessOperations()
// KWIC-Zufallsstichprobe (T1): the sampled load path runs through the same
// product-operation gates as the regular page/stream requests.
const { executeKwicPage, streamKwic } = useQueryOperations()
const {
  groupsAvailability: parallelGroupsAvailability,
  parallelKwicAvailability,
  canLoadParallelGroups,
  canOpenAlignment,
  canLoadParallelKwic,
  parallelGroupsBlockReason,
  alignmentBlockReason,
  parallelKwicBlockReason,
  loadParallelGroups,
  loadAlignmentRefDoc,
  loadParallelKwic,
} = useParallelOperations()

// Parallel / alignment / parallel-KWIC require both product-level release
// visibility and the explicit per-corpus descriptors for the concrete route.
// The generic collocation-contrast remains available on every corpus.
const canUseParallelProduct = computed(() =>
  parallelKwicAvailability.value.visible
)
const canUseParallel = computed(() => canLoadParallelKwic.value)
const parallelUnavailableReason = computed(() =>
  parallelKwicBlockReason.value ?? t('kwic.table.parallelNotEnabled')
)

const elementRegistry = useElementRegistry()
const { isMobile } = useMobileDetection()
const { announce } = useAnnounce()

// Register action handlers
useActions({
  'kwic/scrollToRow': async (action) => {
    scrollToRow(action.payload.index)
    return { success: true }
  },
  'kwic/selectRows': async (action) => {
    if (action.payload.indices.length === 0) {
      queryStore.selectAll()
    } else {
      queryStore.deselectAll()
      action.payload.indices.forEach(idx => queryStore.selectRow(idx, true))
    }
    return { success: true }
  },
  'kwic/highlightRow': async (action) => {
    queryStore.setHighlightedRow(action.payload.index)
    scrollToRow(action.payload.index)
    return { success: true }
  },
  'kwic/expandContext': async (action) => {
    await ensureRowExpanded(action.payload.index)
    return { success: true }
  }
})

// Container ref
const containerRef = ref<HTMLElement | null>(null)
const headerScrollRef = ref<HTMLDivElement | null>(null)
let resizeObserver: ResizeObserver | null = null
let resizeTimer: number | null = null
let isScrollSyncing = false

function syncHorizontalScroll(source: HTMLElement, target: HTMLElement) {
  if (isScrollSyncing) return
  isScrollSyncing = true
  target.scrollLeft = source.scrollLeft
  requestAnimationFrame(() => {
    isScrollSyncing = false
  })
}

function handleBodyScroll() {
  if (!headerScrollRef.value || !containerRef.value) return
  syncHorizontalScroll(containerRef.value, headerScrollRef.value)
}

function handleHeaderScroll() {
  if (!headerScrollRef.value || !containerRef.value) return
  syncHorizontalScroll(headerScrollRef.value, containerRef.value)
}

const CONTEXT_MIN = 40
const CONTEXT_MAX = 600
// This limits request scheduling only. Every requested row still receives the
// complete backend result; we merely avoid flooding the local server when the
// side-by-side view is enabled on a long KWIC page.
const PARALLEL_MAX_CONCURRENT_REQUESTS = 2
const contextSliderValue = ref(queryStore.contextSize)
const autoContextEnabled = ref(true)
// Reserved for future auto-context feature
// const autoContextSize = ref(queryStore.contextSize)
const containerWidth = ref(0)
let autoContextTimer: number | null = null
const autoContextSettledCallbacks = new Set<() => void>()
let parallelPrefetchGeneration = 0
let parallelContextSettling = false
const lastAutoContextSize = ref<number | null>(null)
const contextLeftWidth = ref(0)
const contextRightWidth = ref(0)
const variantLeftWidth = ref(0)
const variantRightWidth = ref(0)
let textMeasureEl: HTMLSpanElement | null = null
let measureFontKey = ''
const textFitCache = new Map<string, string>()
let widthSignature = ''
const isSavingSubcorpus = ref(false)
const nameModalOpen = ref(false)
const subcorpusNameId = useId()
const presetNameId = useId()
const nameDraft = ref('')
const showTrefferAktionen = computed(() => queryStore.hasResults && Boolean(queryStore.term.trim()))
const streamingProgress = computed(() => queryStore.streamingProgress)
const isStreaming = computed(() => queryStore.streamingProgress?.isStreaming ?? false)
const streamingElapsed = computed(() => {
  const elapsedMs = streamingProgress.value?.elapsedMs ?? 0
  if (!elapsedMs) return ''
  const totalSeconds = Math.floor(elapsedMs / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${minutes}:${String(seconds).padStart(2, '0')}`
})
const hitsLabel = computed(() => {
  if (!queryStore.hasResults) return ''
  if (queryStore.countIsLowerBound) {
    return t('kwic.table.hitsPartial', { count: formatNumber(queryStore.totalHits) }, queryStore.totalHits)
  }
  if (!queryStore.totalKnown) {
    return t('kwic.table.counting')
  }
  if (queryStore.rowsIncomplete) {
    return t(
      'kwic.table.hitsLoaded',
      { count: formatNumber(queryStore.totalHits), loaded: formatNumber(queryStore.results.length) },
      queryStore.totalHits,
    )
  }
  return t('kwic.table.hits', { count: formatNumber(queryStore.totalHits) }, queryStore.totalHits)
})
// The action handler surfaces raw transport messages like
// "HTTP 429: Too Many Requests" into queryStore.error. Translate any
// "HTTP <status>: …" string into a friendly German message via the shared
// util so users never see the untranslated status line.
const HTTP_STATUS_RE = /^HTTP\s+(\d{3})\b\s*:?\s*(.*)$/i
function translateQueryError(raw: string | null): { message: string; status: number | null } {
  if (!raw) return { message: '', status: null }
  const match = raw.match(HTTP_STATUS_RE)
  if (!match) return { message: raw, status: null }
  const status = Number.parseInt(match[1]!, 10)
  const detail = match[2]?.trim() || null
  return { message: translateHttpError(status, detail), status }
}
const friendlyError = computed(() => translateQueryError(queryStore.error))
const errorMessage = computed(() => friendlyError.value.message)
// A rate-limit (429) is transient: show it as a non-destructive notice that
// keeps whatever results are already loaded visible, rather than as the
// blocking error banner.
const isRateLimited = computed(() => friendlyError.value.status === 429)
const showRateLimitNotice = computed(() => isRateLimited.value && queryStore.hasResults)
const showErrorBanner = computed(() => Boolean(queryStore.error) && !showRateLimitNotice.value)
const coKwicState = computed(() => parseCoKwicQuery(queryStore.term))
const coKwicCollocates = computed(() => coKwicState.value?.collocates ?? [])
const coKwicTermLabel = computed(() => coKwicState.value?.term ?? '')
// A Co-KWIC row is a node hit, while the collocation row counts collocate
// tokens (O11) in the union of all windows. Both numbers are shown so the
// concordance and the table can be compared.
const coKwicTokenLabel = computed(() => {
  const counts = queryStore.coKwicCounts
  if (!counts || !coKwicState.value) return ''
  const parts = Object.entries(counts.collocateTokens)
    .map(([word, n]) => `${word} ${formatNumber(n)}`)
  return parts.length ? t('kwic.table.coKwicO11', { counts: parts.join(', ') }) : ''
})
const coKwicTokenTitle = computed(() => {
  const counts = queryStore.coKwicCounts
  const state = coKwicState.value
  if (!counts || !state) return ''
  const win = String(counts.window ?? state.window)
  const unit = counts.attribute === 'lemma' ? t('kwic.table.coKwicUnitLemma') : t('kwic.table.coKwicUnitWord')
  const rows = counts.withinSentence === false
    ? t('kwic.table.coKwicRows', { term: state.term, unit, window: win })
    : t('kwic.table.coKwicRowsSentence', { term: state.term, unit, window: win })
  const parts = [rows, t('kwic.table.coKwicO11Explained')]
  if (counts.nodeHits !== null) {
    parts.push(t('kwic.table.coKwicNodeHits', { term: state.term, count: formatNumber(counts.nodeHits) }))
  }
  return parts.join(' ')
})

const refDocOverride = ref<number | null>(null)
const refDocOptions = ref<number[]>([])
const isLoadingRefDocs = ref(false)
const refDocError = ref<string | null>(null)

const refDocOverrideValue = computed({
  get: () => (refDocOverride.value === null ? 'auto' : String(refDocOverride.value)),
  set: (value: string) => {
    if (value === 'auto') {
      refDocOverride.value = null
      return
    }
    const parsed = Number.parseInt(value, 10)
    refDocOverride.value = Number.isFinite(parsed) ? parsed : null
  },
})

// ref_doc selection only makes sense for released paired/alignment corpora.
// Visibility alone is true for every corpus, so a metadata scope on a plain
// corpus would show the block reason twice, once in red.
const showRefDocControl = computed(() =>
  parallelGroupsAvailability.value.visible && canLoadParallelGroups.value && docsetStore.hasActiveDocset
)

const parallelPresetId = ref<string | null>(null)
const presetModalOpen = ref(false)
const presetNameDraft = ref('')
const presetFavorite = ref(true)
const parallelPinnedModels = ref<string[]>([])

const sortedPresets = computed(() => parallelPresetsStore.sortedPresets)
const favoritePresets = computed(() => parallelPresetsStore.favorites)
const activePreset = computed(() =>
  sortedPresets.value.find((preset) => preset.id === parallelPresetId.value) ?? null
)

const orderedParallelModels = computed(() => {
  const pinned = new Set(parallelPinnedModels.value)
  const pinnedList = parallelModels.value.filter((model) => pinned.has(model))
  const unpinnedList = parallelModels.value.filter((model) => !pinned.has(model))
  return [...pinnedList, ...unpinnedList]
})

const parallelHeaderLabels = computed(() => {
  if (!parallelEnabled.value) return []
  return orderedParallelModels.value
})
const parallelPairAxesLabel = computed(() => alignmentPairAxesLabel(corpusCapabilities.activeSummary))
const parallelVariantSelectLabel = computed(() => alignmentVariantControlLabel(corpusCapabilities.activeSummary))

const parallelSummary = computed(() => {
  if (!parallelEnabled.value) return ''
  const variantLabel =
    parallelModels.value.length > 0
      ? orderedParallelModels.value.join(', ')
      : t('kwic.table.noneSelected')
  return t('kwic.table.parallelSummary', { variants: variantLabel, axes: parallelPairAxesLabel.value, margin: parallelSentenceMargin.value })
})

const parallelAutoVariantNote = computed(() =>
  parallelEnabled.value && parallelModels.value.length === 0
    ? t('kwic.table.parallelPickVariant')
    : '',
)

const parallelChipLabel = computed(() => {
  if (!parallelEnabled.value) return ''
  if (activePreset.value) {
    return t('kwic.table.parallelChipPreset', { name: activePreset.value.name })
  }
  return t('kwic.table.parallelChip', { summary: parallelSummary.value })
})

function clampContextSize(value: number): number {
  return clamp(Math.round(value), CONTEXT_MIN, CONTEXT_MAX)
}

watch(
  () => queryStore.contextSize,
  (size) => {
    contextSliderValue.value = clampContextSize(size)
  }
)

watch(
  () => queryStore.term,
  () => {
    if (autoContextEnabled.value) {
      scheduleAutoContextRecompute()
    }
  }
)

watch(
  () => docsetStore.activeDocsetId,
  () => {
    refDocOverride.value = null
    refDocOptions.value = []
    void loadRefDocOptions()
  },
  { immediate: true }
)

watch(refDocOverride, () => {
  alignmentDetails.value = new Map()
})

watch(
  () => uiStore.activeTab,
  (tab) => {
    if (tab !== 'kwic') {
      refDocOverride.value = null
    }
  }
)

function disableParallel() {
  parallelEnabled.value = false
  parallelModels.value = []
  parallelPresetId.value = null
}

async function loadRefDocOptions() {
  if (!canLoadParallelGroups.value || !docsetStore.hasActiveDocset || !docsetStore.activeDocsetId) {
    // Not an error: the corpus has no parallel groups or the operation is not
    // released. The control is hidden in that case.
    refDocOptions.value = []
    refDocError.value = null
    return
  }
  if (isLoadingRefDocs.value) return
  isLoadingRefDocs.value = true
  refDocError.value = null
  try {
    const result = await loadParallelGroups({
      corpus: docsetStore.activeCorpus,
      docsetId: docsetStore.activeDocsetId,
      includeAllVariants: true,
      limit: 200,
      sort: 'variant_count',
    })
    const refs = (result.groups ?? []).map((group) => group.ref_doc)
    refDocOptions.value = refs
  } catch (err) {
    refDocError.value = err instanceof Error ? err.message : t('kwic.table.refDocsFailed')
    refDocOptions.value = []
  } finally {
    isLoadingRefDocs.value = false
  }
}

const presetSelectValue = computed({
  get: () => parallelPresetId.value ?? 'custom',
  set: (value: string) => {
    if (value === 'custom') {
      parallelPresetId.value = null
      return
    }
    const preset = sortedPresets.value.find((p) => p.id === value)
    if (preset) {
      applyParallelPreset(preset)
    }
  },
})

function presetModelsSignature(models: string[], pinned: string[] = []): string {
  return `${models.join('|')}::${pinned.join('|')}`
}

function matchesPreset(preset: { models: string[]; pinnedModels?: string[]; maxVariants: number; sentenceMargin: number }): boolean {
  return (
    presetModelsSignature(preset.models, preset.pinnedModels ?? []) ===
      presetModelsSignature(orderedParallelModels.value, parallelPinnedModels.value) &&
    preset.maxVariants === parallelMaxVariants.value &&
    preset.sentenceMargin === parallelSentenceMargin.value
  )
}

function applyParallelPreset(preset: { id?: string; models: string[]; pinnedModels?: string[]; maxVariants: number; sentenceMargin: number }) {
  parallelEnabled.value = true
  parallelModels.value = [...preset.models]
  parallelPinnedModels.value = [...(preset.pinnedModels ?? [])]
  parallelMaxVariants.value = preset.maxVariants
  parallelSentenceMargin.value = preset.sentenceMargin
  if (preset.id) parallelPresetId.value = preset.id
}

function openPresetModal() {
  presetNameDraft.value =
    parallelModels.value.length > 0
      ? t('kwic.table.presetNameVariants', { variants: orderedParallelModels.value.join(', ') })
      : t('kwic.table.presetNameAuto', { max: parallelMaxVariants.value })
  presetFavorite.value = true
  presetModalOpen.value = true
}

function savePreset() {
  const name = presetNameDraft.value.trim() || t('kwic.table.presetDefaultName')
  const preset = parallelPresetsStore.createPreset({
    name,
    favorite: presetFavorite.value,
    models: [...orderedParallelModels.value],
    pinnedModels: [...parallelPinnedModels.value],
    maxVariants: parallelMaxVariants.value,
    sentenceMargin: parallelSentenceMargin.value,
  })
  parallelPresetsStore.add(preset)
  parallelPresetId.value = preset.id
  presetModalOpen.value = false
}

function togglePresetFavorite() {
  if (!activePreset.value) return
  parallelPresetsStore.update(activePreset.value.id, { favorite: !activePreset.value.favorite })
}

function removePreset() {
  if (!activePreset.value) return
  parallelPresetsStore.remove(activePreset.value.id)
  parallelPresetId.value = null
}

function resetParallelConfig() {
  parallelModels.value = []
  parallelPinnedModels.value = []
  parallelPresetId.value = null
}

function syncPinnedModels() {
  const modelSet = new Set(parallelModels.value)
  const nextPinned = parallelPinnedModels.value.filter((model) => modelSet.has(model))
  // The pinned-model watcher calls this helper. Do not replace an unchanged
  // array: a fresh [] would retrigger that watcher indefinitely when Parallel
  // is switched off.
  if (
    nextPinned.length === parallelPinnedModels.value.length &&
    nextPinned.every((model, index) => model === parallelPinnedModels.value[index])
  ) {
    return
  }
  parallelPinnedModels.value = nextPinned
}

function togglePinnedModel(model: string) {
  if (parallelPinnedModels.value.includes(model)) {
    parallelPinnedModels.value = parallelPinnedModels.value.filter((m) => m !== model)
  } else {
    parallelPinnedModels.value = [...parallelPinnedModels.value, model]
  }
  syncPinnedModels()
}

function moveParallelModel(model: string, direction: 'up' | 'down') {
  const pinnedSet = new Set(parallelPinnedModels.value)
  const pinnedList = parallelModels.value.filter((m) => pinnedSet.has(m))
  const unpinnedList = parallelModels.value.filter((m) => !pinnedSet.has(m))
  const list = pinnedSet.has(model) ? pinnedList : unpinnedList
  const idx = list.indexOf(model)
  if (idx === -1) return
  const nextIdx = direction === 'up' ? idx - 1 : idx + 1
  if (nextIdx < 0 || nextIdx >= list.length) return
  const next = [...list]
  const temp = next[idx]!
  next[idx] = next[nextIdx]!
  next[nextIdx] = temp
  const nextPinned = pinnedSet.has(model) ? next : pinnedList
  const nextUnpinned = pinnedSet.has(model) ? unpinnedList : next
  parallelModels.value = [...nextPinned, ...nextUnpinned]
}

function removeParallelModel(model: string) {
  parallelModels.value = parallelModels.value.filter((m) => m !== model)
  syncPinnedModels()
}

function canMoveParallelModel(model: string, direction: 'up' | 'down'): boolean {
  const pinnedSet = new Set(parallelPinnedModels.value)
  const pinnedList = parallelModels.value.filter((m) => pinnedSet.has(m))
  const unpinnedList = parallelModels.value.filter((m) => !pinnedSet.has(m))
  const list = pinnedSet.has(model) ? pinnedList : unpinnedList
  const idx = list.indexOf(model)
  if (idx === -1) return false
  if (direction === 'up') return idx > 0
  return idx < list.length - 1
}

// Manual context-size control (DT-FE-UX-CORE): when the user disables
// auto-context, a slider re-runs the query with the chosen token window.
async function applyContextSize(nextSize: number) {
  const size = clampContextSize(nextSize)
  contextSliderValue.value = size
  if (size === queryStore.contextSize && queryStore.hasResults) return
  queryStore.setContextSize(size)
  if (!queryStore.term) return
  try {
    await actionBus.dispatch(
      {
        type: 'query/execute',
        payload: {
          term: queryStore.term,
          contextSize: size,
          filters: queryStore.filters,
        },
      },
      { source: 'user', requestId: 'kwic:context-size' }
    )
    void remeasureVirtualizer()
  } catch {
    // Toasts/Errors are handled inside the action handler.
  }
}

let contextApplyTimer: number | null = null
// Drag the slider freely; only re-query once the value settles (debounced).
function onContextSliderInput(value: number) {
  contextSliderValue.value = clampContextSize(value)
  if (contextApplyTimer !== null) window.clearTimeout(contextApplyTimer)
  contextApplyTimer = window.setTimeout(() => {
    contextApplyTimer = null
    void applyContextSize(contextSliderValue.value)
  }, 350)
}

function toggleAutoContext() {
  autoContextEnabled.value = !autoContextEnabled.value
}

// ── KWIC Sort Controls ──────────────────────────────────────────────
// Single source of truth lives in the query store (sortBy/sortDir). The
// controls toggle the store and re-run the query through the action bus so
// the backend returns the rows in the requested order.
type KwicSortField = NonNullable<typeof queryStore.sortBy>

const LEFT_SORT_FIELDS: KwicSortField[] = ['1L', '2L', '3L']
const RIGHT_SORT_FIELDS: KwicSortField[] = ['1R', '2R', '3R']

const activeSortField = computed(() => queryStore.sortBy)
const activeSortDir = computed(() => queryStore.sortDir)
const hasCustomSort = computed(() => queryStore.sortBy !== null)

function isSortActive(field: KwicSortField): boolean {
  return queryStore.sortBy === field
}

function sortDirIndicator(field: KwicSortField): string {
  if (queryStore.sortBy !== field) return ''
  return queryStore.sortDir === 'asc' ? '▲' : '▼'
}

async function rerunQueryForSort() {
  const term = queryStore.term.trim()
  if (!term) return
  try {
    await actionBus.dispatch(
      {
        type: 'query/execute',
        payload: {
          term,
          contextSize: queryStore.contextSize,
          filters: queryStore.filters,
        },
      },
      { source: 'user', requestId: 'kwic:sort' }
    )
  } catch {
    // Fehlerhandling erfolgt im Action-Handler.
  }
}

async function applySort(field: KwicSortField) {
  queryStore.toggleSort(field)
  // Aktive Stichprobe: neu sortieren heißt dieselbe Stichprobe (gleicher Seed)
  // erneut ziehen — der Server sortiert die gezogene Stichprobe, nicht die
  // Vollmenge (Kontrakt T1: Sort/Paging operieren auf der Stichprobe).
  if (queryStore.sampleActive) {
    await runSampledQuery()
    return
  }
  await rerunQueryForSort()
}

async function resetSort() {
  if (!hasCustomSort.value) return
  queryStore.resetSort()
  if (queryStore.sampleActive) {
    await runSampledQuery()
    return
  }
  await rerunQueryForSort()
}

// ── KWIC-Zufallsstichprobe (Thinning, T1) ───────────────────────────
// Uniforme Stichprobe ohne Zurücklegen aus der GESAMTEN Treffermenge; der
// Seed ist Pflicht und sichtbar, damit die Ziehung reproduzierbar zitiert
// werden kann. Konfiguration lebt im Query-Store (sampleActive/-Size/-Seed);
// die Server-Provenienz (X-CandyConc-Sample bzw. done.sample) landet in
// queryStore.sampleProvenance und speist Chip + TSV-Kopie.

/** Frontend-Spiegel des Backend-Caps QUERY_SAMPLE_MAX (routes/query.py). */
const KWIC_SAMPLE_MAX = 10000

const isSampling = ref(false)

/** Zufälliger Vorbefüllungs-Seed; sichtbar und editierbar (Reproduzierbarkeit). */
function newRandomSeed(): number {
  return Math.floor(Math.random() * 1_000_000)
}

const sampleSizeModel = computed({
  get: () => queryStore.sampleSize,
  set: (value: number) => {
    if (Number.isFinite(value) && value >= 1) {
      queryStore.sampleSize = Math.min(KWIC_SAMPLE_MAX, Math.round(value))
    }
  },
})

const sampleSeedModel = computed<number | null>({
  get: () => queryStore.sampleSeed,
  set: (value: number | null) => {
    queryStore.sampleSeed =
      typeof value === 'number' && Number.isFinite(value) && value >= 0
        ? Math.round(value)
        : null
  },
})

const sampleChipLabel = computed(() => {
  const provenance = queryStore.sampleProvenance
  if (!provenance) return ''
  const population = formatNumber(provenance.population)
  const populationLabel = provenance.populationPartial ? `≥ ${population}` : population
  return t('kwic.table.sampleChip', { drawn: formatNumber(provenance.drawn), population: populationLabel, seed: provenance.seed })
})

const sampleChipTitle = computed(() => {
  const provenance = queryStore.sampleProvenance
  if (!provenance) return ''
  return t('kwic.table.sampleChipTitle', { provenance: formatSampleProvenance(provenance) })
})

/**
 * Mirror of the private `resolveQueryFilters` in `actions/handlers.ts` (TABU
 * file): maps the stored QueryFilters onto the REST `date`/`genre` params so
 * the sampled request covers the same population as the regular query.
 */
function resolveKwicSampleFilters(filters: QueryFilters): { date?: string; genre?: string } {
  let date: string | undefined
  let genre: string | undefined
  if (filters.dateRange) {
    const from = filters.dateRange.from?.trim()
    const to = filters.dateRange.to?.trim()
    if (from && to && from !== to) date = `${from}..${to}`
    else date = from || to || undefined
  }
  const meta = filters.metadata ?? {}
  if (!date && typeof meta.date === 'string' && meta.date.trim()) date = meta.date.trim()
  if (typeof meta.genre === 'string' && meta.genre.trim()) genre = meta.genre.trim()
  return { date, genre }
}

function mapSampledHit(hit: QueryHit): (typeof queryStore.results)[number] {
  return {
    position: hit.position,
    left: hit.left,
    match: hit.match,
    right: hit.right,
    docId: hit.doc_id,
    docTitle: hit.doc_title,
    metadata: hit.metadata,
    matchOffsets: hit.match_offsets,
    ...readRowSpacing(hit),
  }
}

/** Stichprobe ziehen (oder mit identischem Seed reproduzieren) und anzeigen. */
async function runSampledQuery() {
  if (isSampling.value) return
  const term = queryStore.term.trim()
  if (!term) {
    uiStore.showToast(t('kwic.table.sampleNeedsResult'), 'info')
    return
  }
  const seed = queryStore.sampleSeed
  if (seed === null || seed < 0) {
    uiStore.showToast(t('kwic.table.sampleSeedRequired'), 'warning')
    return
  }
  const size = Math.max(1, Math.min(Math.round(queryStore.sampleSize || 1), KWIC_SAMPLE_MAX))
  isSampling.value = true
  try {
    const { date, genre } = resolveKwicSampleFilters(queryStore.filters)
    const docsetId = docsetStore.hasActiveDocset
      ? docsetStore.activeDocsetId ?? undefined
      : undefined
    let hits: QueryHit[] = []
    let provenance: KwicSampleProvenance | null = null
    if (docsetId) {
      // GET /query kennt kein docset_id; der Stream spiegelt sample/seed und
      // ist docset-fähig. Streaming liefert Korpusreihenfolge — eine aktive
      // Sortierung wäre auf diesem Pfad nicht anwendbar und wird ehrlich
      // zurückgesetzt statt still ignoriert.
      if (queryStore.sortBy !== null) {
        queryStore.resetSort()
        uiStore.showToast(
          t('kwic.table.sampleSortReset'),
          'info'
        )
      }
      for await (const event of streamKwic({
        term,
        context: queryStore.contextSize,
        corpus: docsetStore.activeCorpus,
        docsetId,
        date,
        genre,
        batchSize: 200,
        caseInsensitive: !queryStore.caseSensitive,
        sample: size,
        seed,
      })) {
        if (event.type === 'batch' && event.hits) hits.push(...event.hits)
        else if (event.type === 'done') provenance = event.sample ?? null
        else if (event.type === 'error') throw new Error(event.error ?? t('kwic.table.sampleStreamFailed'))
      }
    } else {
      const result = await executeSampledQuery(
        {
          term,
          context: queryStore.contextSize,
          corpus: docsetStore.activeCorpus,
          date,
          genre,
          sortBy: queryStore.sortBy,
          sortDir: queryStore.sortDir,
          caseInsensitive: !queryStore.caseSensitive,
          sample: size,
          seed,
        },
        (pageParams) => executeKwicPage(pageParams)
      )
      hits = result.hits
      provenance = result.sample ?? null
    }
    if (!provenance) {
      // Ohne Server-Provenienz keine Übernahme: ein Resultat, das nicht als
      // Stichprobe ausgewiesen werden kann, wäre wissenschaftlich unbrauchbar.
      uiStore.showToast(
        t('kwic.table.sampleNoProvenance'),
        'error'
      )
      return
    }
    queryStore.setResults(hits.map(mapSampledHit), provenance.drawn, true, false)
    queryStore.setResultOffsetStart(0)
    queryStore.setHasPrevious(false)
    queryStore.setHasMore(false)
    queryStore.setNextOffset(0)
    queryStore.setTotalHits(provenance.drawn, true, false)
    queryStore.setSampleProvenance(provenance)
    queryStore.setLastExecutedAt(Date.now())
    announce(t('kwic.table.sampleAnnounce', { drawn: provenance.drawn, population: provenance.population, seed: provenance.seed }))
  } catch (err) {
    const detail = await extractApiDetail(err)
    uiStore.showToast(detail || t('kwic.table.sampleFailed'), 'error')
  } finally {
    isSampling.value = false
  }
}

/** Toggle: aktivieren zieht sofort (Seed wird vorbefüllt), deaktivieren lädt die Vollmenge. */
async function toggleSampleActive() {
  if (queryStore.sampleActive) {
    queryStore.clearSample()
    const term = queryStore.term.trim()
    if (!term) return
    try {
      await actionBus.dispatch(
        {
          type: 'query/execute',
          payload: {
            term,
            contextSize: queryStore.contextSize,
            filters: queryStore.filters,
          },
        },
        { source: 'user', requestId: 'kwic:sample-off' }
      )
    } catch {
      // Fehlerhandling erfolgt im Action-Handler.
    }
    return
  }
  if (queryStore.sampleSeed === null) {
    queryStore.setSampleConfig(true, undefined, newRandomSeed())
  } else {
    queryStore.setSampleConfig(true)
  }
  if (queryStore.term.trim()) await runSampledQuery()
}

async function retryQuery() {
  const term = queryStore.term.trim()
  if (!term) return
  try {
    await actionBus.dispatch(
      {
        type: 'query/execute',
        payload: {
          term,
          contextSize: queryStore.contextSize,
          filters: queryStore.filters,
        },
      },
      'system'
    )
  } catch {
    // Fehlerhandling erfolgt im Action-Handler.
  }
}

async function loadMoreResults() {
  if (!queryStore.hasMore || isStreaming.value) return
  try {
    await actionBus.dispatch(
      { type: 'query/loadMore', payload: { direction: 'next' } },
      { source: 'user', requestId: 'kwic:load-more:next' }
    )
  } catch {
    // Fehlerhandling erfolgt im Action-Handler.
  }
}

async function loadPreviousResults() {
  if (!queryStore.hasPrevious || isStreaming.value || !containerRef.value) return
  const beforeScrollTop = containerRef.value.scrollTop
  const containerRect = containerRef.value.getBoundingClientRect()
  const anchorIndex = virtualRows.value[0]?.index ?? null
  const anchorEl = anchorIndex !== null
    ? containerRef.value.querySelector(`[data-row-index="${anchorIndex}"]`) as HTMLElement | null
    : null
  const anchorOffset = anchorEl ? anchorEl.getBoundingClientRect().top - containerRect.top : null
  const estimator = rowVirtualizer.value.options.estimateSize
  const estimatedRowHeight = typeof estimator === 'function' ? estimator(0) : ROW_HEIGHT
  try {
    const result = await actionBus.dispatch(
      { type: 'query/loadMore', payload: { direction: 'prev' } },
      { source: 'user', requestId: 'kwic:load-more:prev' }
    )
    const added = typeof result.data === 'object' && result.data
      ? Number((result.data as { added?: number }).added ?? 0)
      : 0
    if (added > 0) {
      // Rows were prepended: every existing row moved down by `added`. Re-key
      // the index-keyed detail caches so cached snippets/alignments stay bound
      // to their original rows instead of aliasing the new leading rows.
      shiftRowCaches(added)
      await nextTick()
      const anchorAfterIndex = anchorIndex !== null ? anchorIndex + added : null
      const anchorAfterEl = anchorAfterIndex !== null
        ? containerRef.value.querySelector(`[data-row-index="${anchorAfterIndex}"]`) as HTMLElement | null
        : null
      if (anchorAfterEl && anchorOffset !== null) {
        const afterOffset = anchorAfterEl.getBoundingClientRect().top - containerRect.top
        const delta = afterOffset - anchorOffset
        containerRef.value.scrollTop = beforeScrollTop + delta
      } else {
        containerRef.value.scrollTop = beforeScrollTop + added * estimatedRowHeight
      }
    }
  } catch {
    // Fehlerhandling erfolgt im Action-Handler.
  }
}

async function removeCoAnchor(anchor: string) {
  const state = coKwicState.value
  if (!state) return
  const remaining = state.collocates.filter((value) => value !== anchor)
  const nextTerm = remaining.length
    ? buildCoKwicQuery({
        term: state.term,
        collocates: remaining,
        window: state.window,
        withinSentence: state.withinSentence,
        attribute: state.attribute,
      })
    : state.term

  await actionBus.dispatch(
    {
      type: 'query/execute',
      payload: {
        term: nextTerm,
        contextSize: queryStore.contextSize,
        filters: queryStore.filters,
      },
    },
    { source: 'user', requestId: `kwic:remove-co-anchor:${anchor}` }
  )
}

function ensureMeasureElement(referenceEl?: HTMLElement | null) {
  if (!textMeasureEl) {
    textMeasureEl = document.createElement('span')
    textMeasureEl.style.position = 'absolute'
    textMeasureEl.style.visibility = 'hidden'
    textMeasureEl.style.whiteSpace = 'nowrap'
    textMeasureEl.style.top = '-99999px'
    textMeasureEl.style.left = '-99999px'
    document.body.appendChild(textMeasureEl)
  }
  const el = referenceEl ?? (measureFontKey ? null : containerRef.value)
  if (!el || !textMeasureEl) return
  const style = window.getComputedStyle(el)
  const fontKey = `${style.fontWeight}|${style.fontSize}|${style.fontFamily}|${style.letterSpacing}`
  if (fontKey !== measureFontKey) {
    measureFontKey = fontKey
    textMeasureEl.style.font = style.font
    textMeasureEl.style.letterSpacing = style.letterSpacing
  }
}

function measureTextWidth(text: string): number {
  if (!textMeasureEl) return 0
  textMeasureEl.textContent = text
  return textMeasureEl.getBoundingClientRect().width
}

function fallbackContextWidth(): number {
  const width = containerWidth.value || 1200
  const variantCount = parallelEnabled.value ? parallelColumnCount.value : 0
  const matchWidth = 80
  const reserved = 72 + matchWidth + variantCount * 260 + 40
  const available = Math.max(220, width - reserved)
  return Math.floor(available / 2)
}

function estimateCharWidth(): number {
  ensureMeasureElement(containerRef.value)
  if (!textMeasureEl) return 7
  const sample = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'
  const width = measureTextWidth(sample)
  if (!width) return 7
  return width / sample.length
}

function estimateAverageTokenLength(): number {
  const sampleRow = queryStore.results[0]
  const sampleText = sampleRow
    ? `${sampleRow.left ?? ''} ${sampleRow.right ?? ''}`.trim()
    : ''
  if (!sampleText) return 6
  const spans = tokenSpans(sampleText)
  if (!spans.length) return 6
  const totalChars = spans.reduce((sum, span) => sum + (span.end - span.start), 0)
  return Math.max(3, totalChars / spans.length)
}

function computeAutoContextSize(): number | null {
  const leftWidth = contextLeftWidth.value || fallbackContextWidth()
  const rightWidth = contextRightWidth.value || fallbackContextWidth()
  const charWidth = estimateCharWidth()
  if (!charWidth || !Number.isFinite(charWidth)) return null
  const avgTokenLen = estimateAverageTokenLength()
  const tokenUnit = Math.max(3, avgTokenLen + 1)
  const leftChars = Math.max(12, Math.floor(leftWidth / charWidth))
  const rightChars = Math.max(12, Math.floor(rightWidth / charWidth))
  const tokensLeft = Math.ceil(leftChars / tokenUnit)
  const tokensRight = Math.ceil(rightChars / tokenUnit)
  const desired = Math.ceil(Math.max(tokensLeft, tokensRight) * 1.9)
  return clamp(desired, CONTEXT_MIN, CONTEXT_MAX)
}

function computeUnderfillContextSize(): number | null {
  const firstIndex = virtualRows.value[0]?.index
  if (firstIndex === undefined) return null
  const row = queryStore.results[firstIndex]
  if (!row) return null
  const leftWidth = contextLeftWidth.value || fallbackContextWidth()
  const rightWidth = contextRightWidth.value || fallbackContextWidth()
  ensureMeasureElement(containerRef.value)
  const leftText = cleanLeft(row.left ?? '')
  const rightText = cleanRight(row.right ?? '')
  if (!leftText && !rightText) return null
  const leftMeasured = leftText ? measureTextWidth(leftText) : 0
  const rightMeasured = rightText ? measureTextWidth(rightText) : 0
  const leftTrimmed = leftText ? fitLeft(leftText, leftWidth) : ''
  const rightTrimmed = rightText ? fitRight(rightText, rightWidth) : ''
  const leftUnderfills = leftText.length > 0
    && leftTrimmed.length === leftText.length
    && leftMeasured < leftWidth * 0.92
  const rightUnderfills = rightText.length > 0
    && rightTrimmed.length === rightText.length
    && rightMeasured < rightWidth * 0.92
  if (!leftUnderfills && !rightUnderfills) return null
  const charWidth = estimateCharWidth() || 7
  const tokenUnit = Math.max(3, estimateAverageTokenLength() + 1)
  const extraLeftChars = leftUnderfills
    ? Math.max(0, Math.ceil((leftWidth - leftMeasured) / charWidth))
    : 0
  const extraRightChars = rightUnderfills
    ? Math.max(0, Math.ceil((rightWidth - rightMeasured) / charWidth))
    : 0
  const extraChars = Math.max(extraLeftChars, extraRightChars)
  if (!extraChars) return null
  const extraTokens = Math.ceil(extraChars / tokenUnit)
  const bump = Math.max(6, extraTokens)
  return clamp(queryStore.contextSize + bump, CONTEXT_MIN, CONTEXT_MAX)
}

async function applyAutoContextSize() {
  const computed = computeAutoContextSize()
  const underfill = computeUnderfillContextSize()
  const desiredCandidates = [computed, underfill].filter((val): val is number => typeof val === 'number')
  const desired = desiredCandidates.length ? Math.max(...desiredCandidates) : null
  if (!desired) return
  if (Math.abs(desired - queryStore.contextSize) < 4) {
    lastAutoContextSize.value = desired
    return
  }
  if (lastAutoContextSize.value === desired) return
  lastAutoContextSize.value = desired
  contextSliderValue.value = desired
  queryStore.setContextSize(desired)
}

type ContextSegment = { text: string; highlight?: 'match' | 'collocate' }


function tokenSpans(text: string): TextSpan[] {
  const spans: TextSpan[] = []
  const length = text.length
  let i = 0
  while (i < length) {
    while (i < length && /\s/.test(text[i]!)) i += 1
    if (i >= length) break
    const start = i
    while (i < length && !/\s/.test(text[i]!)) i += 1
    spans.push({ start, end: i })
  }
  return spans
}

function segmentsFromTypedRanges(
  text: string,
  ranges: Array<{ start: number; end: number; type: 'match' | 'collocate' }>
): ContextSegment[] {
  if (!text) return []
  if (!ranges.length) return [{ text }]
  const merged = ranges
    .map((range) => ({
      start: Math.max(0, Math.min(text.length, range.start)),
      end: Math.max(0, Math.min(text.length, range.end)),
      type: range.type,
    }))
    .filter((range) => range.end > range.start)
    .sort((a, b) => a.start - b.start)
  if (!merged.length) return [{ text }]
  const segments: ContextSegment[] = []
  let cursor = 0
  for (const range of merged) {
    if (range.start > cursor) {
      segments.push({ text: text.slice(cursor, range.start) })
    }
    segments.push({ text: text.slice(range.start, range.end), highlight: range.type })
    cursor = range.end
  }
  if (cursor < text.length) {
    segments.push({ text: text.slice(cursor) })
  }
  return mergeWhitespaceSegments(segments.filter(segment => segment.text.length > 0))
}

function fallbackSegmentsByString(text: string): ContextSegment[] {
  if (!text) return []
  const collocateSet = new Set(
    coKwicCollocates.value.map(value => value.trim()).filter(Boolean)
  )
  if (!collocateSet.size) return [{ text }]
  const parts = text.split(/(\s+)/)
  const segments: ContextSegment[] = []
  for (const part of parts) {
    if (!part) continue
    if (/^\s+$/.test(part)) {
      segments.push({ text: part })
      continue
    }
    segments.push({ text: part, highlight: collocateSet.has(part) ? 'collocate' : undefined })
  }
  return mergeWhitespaceSegments(segments)
}

function mergeWhitespaceSegments(segments: ContextSegment[]): ContextSegment[] {
  if (!segments.length) return segments
  const merged: ContextSegment[] = []
  let leadingWhitespace = ''

  for (const segment of segments) {
    if (!segment.text) continue
    if (/^\s+$/.test(segment.text)) {
      if (merged.length) {
        const last = merged[merged.length - 1]!
        merged[merged.length - 1] = { ...last, text: last.text + segment.text }
      } else {
        leadingWhitespace += segment.text
      }
      continue
    }

    const text = leadingWhitespace ? `${leadingWhitespace}${segment.text}` : segment.text
    leadingWhitespace = ''
    const last = merged[merged.length - 1]
    if (last && last.highlight === segment.highlight) {
      merged[merged.length - 1] = { ...last, text: `${last.text}${text}` }
      continue
    }
    merged.push({ ...segment, text })
  }

  if (leadingWhitespace) {
    if (merged.length) {
      const last = merged[merged.length - 1]!
      merged[merged.length - 1] = { ...last, text: `${last.text}${leadingWhitespace}` }
    } else {
      merged.push({ text: leadingWhitespace })
    }
  }

  return merged
}

function tokenIndicesFromOffsets(
  tokenCount: number,
  offsets: number[],
  side: 'left' | 'right'
): Set<number> {
  const indices = new Set<number>()
  if (!tokenCount) return indices
  for (const offset of offsets) {
    if (side === 'left' && offset < 0) {
      const index = tokenCount + offset
      if (index >= 0 && index < tokenCount) indices.add(index)
    }
    if (side === 'right' && offset > 0) {
      const index = offset - 1
      if (index >= 0 && index < tokenCount) indices.add(index)
    }
  }
  return indices
}

/**
 * Token spans of a cleaned context text. `rawSpans` are the spans of the raw
 * text of a row with the original spacing (token_starts), shifted past what
 * cleanLeft removed at the start or cut where cleanRight removed the end.
 * Without them the tokens are the whitespace-separated chunks.
 */
function contextTokenSpans(
  rawText: string,
  cleaned: string,
  side: 'left' | 'right',
  rawSpans?: TextSpan[]
): TextSpan[] {
  if (!rawSpans) return tokenSpans(cleaned)
  if (side === 'left') {
    const removed = rawText.length - cleaned.length
    return rawSpans
      .filter((span) => span.start >= removed)
      .map((span) => ({ start: span.start - removed, end: span.end - removed }))
  }
  return rawSpans.filter((span) => span.end <= cleaned.length)
}

function segmentsForContextText(
  rawText: string,
  collocateOffsets: number[],
  matchOffsets: number[],
  side: 'left' | 'right',
  maxWidth?: number,
  rawSpans?: TextSpan[]
): ContextSegment[] {
  const cleaned = side === 'left' ? cleanLeft(rawText) : cleanRight(rawText)
  if (!cleaned) return []
  const width = maxWidth !== undefined
    ? (maxWidth > 0 ? maxWidth : fallbackContextWidth())
    : null
  const truncated = width === null
    ? cleaned
    : (side === 'left' ? fitLeft(rawText, width) : fitRight(rawText, width))
  const spans = contextTokenSpans(rawText, cleaned, side, rawSpans)
  if (!spans.length) return [{ text: truncated }]
  const collocateIdx = tokenIndicesFromOffsets(spans.length, collocateOffsets, side)
  const matchIdx = tokenIndicesFromOffsets(spans.length, matchOffsets, side)
  if (!collocateIdx.size && !matchIdx.size) {
    return fallbackSegmentsByString(truncated)
  }
  const truncStart = side === 'left' ? Math.max(0, cleaned.length - truncated.length) : 0
  const truncEnd = truncStart + truncated.length
  const typedRanges: Array<{ start: number; end: number; type: 'match' | 'collocate' }> = []
  spans.forEach((span, index) => {
    if (span.start < truncStart || span.end > truncEnd) return
    const type = matchIdx.has(index)
      ? 'match'
      : collocateIdx.has(index)
        ? 'collocate'
        : null
    if (!type) return
    typedRanges.push({
      start: span.start - truncStart,
      end: span.end - truncStart,
      type,
    })
  })
  if (!typedRanges.length) {
    return fallbackSegmentsByString(truncated)
  }
  return segmentsFromTypedRanges(truncated, typedRanges)
}

function getRowCollocateOffsets(index: number): number[] {
  const row = queryStore.results[index]
  if (!row?.collocateOffsets || !Array.isArray(row.collocateOffsets)) return []
  return row.collocateOffsets.filter((value) => Number.isFinite(value))
}

function getRowMatchOffsets(index: number): number[] {
  const row = queryStore.results[index]
  if (!row?.matchOffsets || !Array.isArray(row.matchOffsets)) return []
  return row.matchOffsets.filter((value) => Number.isFinite(value))
}

// A multi-token match is shown whole in the match column.
function displayRow(index: number): KwicSpanDisplay {
  const row = queryStore.results[index]
  return kwicSpanDisplay({
    left: row?.left ?? '',
    match: row?.match ?? '',
    right: row?.right ?? '',
    matchOffsets: getRowMatchOffsets(index),
    collocateOffsets: getRowCollocateOffsets(index),
    tokenStarts: row?.tokenStarts,
    wsBeforeKw: row?.wsBeforeKw,
    wsAfterKw: row?.wsAfterKw,
  })
}

function contextSegmentsForRow(
  index: number,
  side: 'left' | 'right',
  maxWidth?: number,
  overrideText?: string
): ContextSegment[] {
  if (overrideText !== undefined) {
    return segmentsForContextText(overrideText, getRowCollocateOffsets(index), getRowMatchOffsets(index), side, maxWidth)
  }
  const shown = displayRow(index)
  const text = side === 'left' ? shown.left : shown.right
  const spans = side === 'left' ? shown.leftSpans : shown.rightSpans
  return segmentsForContextText(text, shown.collocateOffsets, shown.matchOffsets, side, maxWidth, spans)
}

/**
 * Whether the rendered context for a row is clipped (width-fitted shorter than
 * the available text). Drives the `…` truncation marker so the linguist can see
 * at a glance that more context exists beyond what the column shows.
 */
function isContextTruncated(index: number, side: 'left' | 'right', maxWidth?: number): boolean {
  if (maxWidth === undefined) return false
  const width = maxWidth > 0 ? maxWidth : fallbackContextWidth()
  if (width <= 0) return false
  const shown = displayRow(index)
  const raw = side === 'left' ? shown.left : shown.right
  const cleaned = side === 'left' ? cleanLeft(raw) : cleanRight(raw)
  if (!cleaned) return false
  const fitted = side === 'left' ? fitLeft(raw, width) : fitRight(raw, width)
  return fitted.length < cleaned.length
}

async function updateContextMetrics() {
  await nextTick()
  const firstIndex = virtualRows.value[0]?.index
  const rowEl = firstIndex !== undefined
    ? containerRef.value?.querySelector(`[data-row-index="${firstIndex}"]`)
    : null
  const leftEl = rowEl?.querySelector('.row-left') as HTMLElement | null
  const rightEl = rowEl?.querySelector('.row-right') as HTMLElement | null
  const variantLeftEl = rowEl?.querySelector('.variant-left') as HTMLElement | null
  const variantRightEl = rowEl?.querySelector('.variant-right') as HTMLElement | null

  if (leftEl) {
    ensureMeasureElement(leftEl)
    contextLeftWidth.value = leftEl.getBoundingClientRect().width
  } else {
    contextLeftWidth.value = contextLeftWidth.value || fallbackContextWidth()
  }
  if (rightEl) {
    ensureMeasureElement(rightEl)
    contextRightWidth.value = rightEl.getBoundingClientRect().width
  } else {
    contextRightWidth.value = contextRightWidth.value || fallbackContextWidth()
  }

  if (variantLeftEl) {
    ensureMeasureElement(variantLeftEl)
    variantLeftWidth.value = variantLeftEl.getBoundingClientRect().width
  } else {
    variantLeftWidth.value = variantLeftWidth.value || contextLeftWidth.value
  }
  if (variantRightEl) {
    ensureMeasureElement(variantRightEl)
    variantRightWidth.value = variantRightEl.getBoundingClientRect().width
  } else {
    variantRightWidth.value = variantRightWidth.value || contextRightWidth.value
  }

  const nextSignature = [
    contextLeftWidth.value,
    contextRightWidth.value,
    variantLeftWidth.value,
    variantRightWidth.value,
    measureFontKey,
  ].join('|')

  if (nextSignature !== widthSignature) {
    widthSignature = nextSignature
    textFitCache.clear()
  }
}

function scheduleAutoContextRecompute(onSettled?: () => void) {
  if (onSettled) autoContextSettledCallbacks.add(onSettled)
  if (parallelContextSettling && !onSettled) return
  if (autoContextTimer !== null) {
    window.clearTimeout(autoContextTimer)
  }
  autoContextTimer = window.setTimeout(async () => {
    autoContextTimer = null
    try {
      await updateContextMetrics()
      if (autoContextEnabled.value) {
        await applyAutoContextSize()
      }
    } finally {
      const callbacks = Array.from(autoContextSettledCallbacks)
      autoContextSettledCallbacks.clear()
      callbacks.forEach((callback) => callback())
    }
  }, 60)
}

function updateContainerWidth() {
  if (!containerRef.value) return
  const nextWidth = containerRef.value.clientWidth || 0
  if (nextWidth !== containerWidth.value) {
    containerWidth.value = nextWidth
  }
  scheduleAutoContextRecompute()
}

async function saveSubcorpusFromHits() {
  if (!queryStore.term.trim()) return
  nameDraft.value = subcorporaStore.suggestName({
    term: queryStore.term.trim(),
    corpus: docsetStore.activeCorpus,
    filters: docsetStore.filters,
    filterSpec: docsetStore.hasActiveDocset ? docsetStore.activeFilterSpec : null,
    includeAi: docsetStore.includeAi,
    includeHuman: docsetStore.includeHuman,
  })
  nameModalOpen.value = true
}

async function confirmSaveSubcorpus() {
  if (isSavingSubcorpus.value) return
  isSavingSubcorpus.value = true
  try {
    const term = queryStore.term.trim()
    // The subcorpus holds the documents with hits of this query inside the
    // active scope. Its definition keeps the scope's metadata filter, so it
    // resolves to the same documents later (without the filter "freedom" in
    // party=Republican would resolve to 62 instead of 33 documents). The
    // active scope itself stays unchanged.
    const hits = await docsetStore.buildHitsDocset(term)
    if (!hits) {
      uiStore.showToast(t('kwic.table.subcorpusCreateFailed'), 'error')
      return
    }
    const snapshot = subcorporaStore.createSnapshot({
      name: nameDraft.value.trim() || subcorporaStore.suggestName({
        term,
        corpus: docsetStore.activeCorpus,
        filters: docsetStore.filters,
        filterSpec: hits.filterSpec,
        includeAi: docsetStore.includeAi,
        includeHuman: docsetStore.includeHuman,
      }),
      status: 'parked',
      corpus: docsetStore.activeCorpus,
      docsetId: hits.docsetId,
      stats: {
        docCount: hits.stats.docCount,
        tokenCount: hits.stats.tokenCount,
        refDocCount: hits.stats.refDocCount,
      },
      filters: {
        prompting_method: [...docsetStore.filters.prompting_method],
        model: [...docsetStore.filters.model],
        register: [...docsetStore.filters.register],
        source: [...docsetStore.filters.source],
      },
      filterSpec: hits.filterSpec ?? undefined,
      includeAi: docsetStore.includeAi,
      includeHuman: docsetStore.includeHuman,
      metadataSchemaHash: docsetStore.metaSchemaHash ?? undefined,
      origin: { type: 'query', query: term },
    })
    subcorporaStore.add(snapshot)
    uiStore.showToast(t('kwic.table.subcorpusSaved'), 'success', 2000)
    nameModalOpen.value = false
  } finally {
    isSavingSubcorpus.value = false
  }
}

function goToContrast() {
  void actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'contrast' } })
}

// ── KWIC copy / cite ────────────────────────────────────────────────
// The most common linguist micro-action: lift a concordance line into a
// paper. We copy the *raw* left/node/right (whitespace preserved) — not the
// width-truncated display strings — so the citation is faithful.
function citationRowForIndex(index: number): KwicCitationRow | null {
  const row = queryStore.results[index]
  if (!row) return null
  return {
    position: row.position,
    left: row.left ?? '',
    match: row.match ?? '',
    right: row.right ?? '',
    docId: row.docId ?? null,
    docTitle: row.docTitle ?? null,
    metadata: getRowMeta(index) ?? row.metadata ?? null,
    matchOffsets: getRowMatchOffsets(index),
  }
}

async function copyResult(text: string, successMessage: string) {
  const ok = await copyTextToClipboard(text)
  if (ok) {
    uiStore.showToast(successMessage, 'success', 2000)
  } else {
    uiStore.showToast(t('kwic.table.copyBlocked'), 'error')
  }
}

async function copyRowLine(index: number) {
  const row = citationRowForIndex(index)
  if (!row) return
  await copyResult(formatKwicLine(row), t('kwic.table.lineCopied'))
}

async function copyRowWithCitation(index: number) {
  const row = citationRowForIndex(index)
  if (!row) return
  await copyResult(formatKwicLineWithCitation(row), t('kwic.table.lineCitedCopied'))
}

async function copyVisibleRows() {
  const rows = queryStore.results
    .map((_, index) => citationRowForIndex(index))
    .filter((row): row is KwicCitationRow => row !== null)
  if (!rows.length) return
  await copyResult(
    // Kopien einer Stichprobe tragen die Provenienz (drawn/population/seed)
    // als Kommentarzeile, damit die Teilmenge zitierbar bleibt.
    formatKwicTsv(rows, { sample: queryStore.sampleProvenance }),
    t('kwic.table.tsvCopied', { count: formatNumber(rows.length) }, rows.length)
  )
}

// ── KWIC annotation layer (F7) ──────────────────────────────────────
// Row-level coding: each KWIC line gets a stable row_id (file+pos, fallback
// text hash) so annotations survive sort/paging/re-query. A row carries at
// most one category plus a free-text note (single-select, per spec).
const schemeEditorOpen = computed({
  get: () => uiStore.annotationReviewOpen,
  set: (open: boolean) => {
    if (open) uiStore.openAnnotationReview()
    else uiStore.closeAnnotationReview()
  },
})
// Index of the row whose annotation popover is open (null = none).
const annotationPopoverIndex = ref<number | null>(null)
const noteDraft = ref('')
const categoryDraftId = ref<string | null>(null)
const annotationSaving = ref(false)

function rowIdForIndex(index: number): string | null {
  const row = queryStore.results[index]
  if (!row) return null
  // Corpus-namespaced so annotations never alias across corpora (docId is a
  // per-corpus index that restarts at 0).
  return rowIdFor(row, docsetStore.activeCorpus)
}

function getRowAnnotation(index: number) {
  const id = rowIdForIndex(index)
  return id ? annotationsStore.getAnnotation(id) : undefined
}

function rowCategory(index: number) {
  const id = rowIdForIndex(index)
  return id ? annotationsStore.categoryFor(id) : undefined
}

function isRowAnnotated(index: number): boolean {
  return Boolean(getRowAnnotation(index))
}

function openAnnotationPopover(index: number) {
  if (!annotationsStore.canWriteAnnotations) {
    uiStore.showToast(
      annotationsStore.annotationsWriteBlockReason ?? t('kwic.table.annotationsReadOnly'),
      'warning'
    )
    return
  }
  annotationPopoverIndex.value = index
  noteDraft.value = getRowAnnotation(index)?.note ?? ''
  categoryDraftId.value = rowCategory(index)?.id ?? null
}

function closeAnnotationPopover() {
  if (annotationSaving.value) return
  annotationPopoverIndex.value = null
  noteDraft.value = ''
  categoryDraftId.value = null
}

function normalizedNoteDraft(): string | null {
  return noteDraft.value && noteDraft.value.trim() ? noteDraft.value : null
}

async function persistAnnotationDraft(
  index: number,
  input: { categoryId?: string | null; note?: string | null },
  errorMessage: string,
): Promise<boolean> {
  const id = rowIdForIndex(index)
  if (!id) return false
  annotationSaving.value = true
  try {
    await annotationsStore.setAnnotation(id, {
      ...input,
      note: input.note !== undefined ? input.note : normalizedNoteDraft(),
    })
    return true
  } catch {
    uiStore.showToast(errorMessage, 'error')
    return false
  } finally {
    annotationSaving.value = false
  }
}

async function assignCategoryImmediately(index: number, categoryId: string | null) {
  await persistAnnotationDraft(index, { categoryId }, t('kwic.table.categorySaveFailed'))
}

async function saveAnnotation(index: number): Promise<boolean> {
  const saved = await persistAnnotationDraft(
    index,
    { categoryId: categoryDraftId.value, note: normalizedNoteDraft() },
    t('kwic.table.annotationSaveFailed'),
  )
  if (saved) {
    uiStore.showToast(t('kwic.table.annotationSaved'), 'success', 1500)
  }
  return saved
}

async function saveAnnotationAndClose(index: number) {
  if (await saveAnnotation(index)) closeAnnotationPopover()
}

async function clearRowAnnotation(index: number) {
  const id = rowIdForIndex(index)
  if (!id) return
  if (!settingsStore.confirmDeletion()) return
  try {
    await annotationsStore.removeAnnotation(id)
    closeAnnotationPopover()
  } catch {
    uiStore.showToast(t('kwic.table.annotationRemoveFailed'), 'error')
  }
}

// ── Filter loaded rows (DT-FE-UX-CORE) ──────────────────────────────
// A client-side text filter over the already-loaded KWIC rows. It does NOT
// re-query the backend; it just hides rows whose left/match/right/meta do not
// match. A leading `/…/` (optionally `/…/i`) is treated as a regex; otherwise
// a case-insensitive substring match. An invalid regex degrades to substring.
const rowFilterText = ref('')
const rowFilterRegexError = ref<string | null>(null)

interface CompiledRowFilter {
  test: (haystack: string) => boolean
}

const compiledRowFilter = computed<CompiledRowFilter | null>(() => {
  const raw = rowFilterText.value.trim()
  rowFilterRegexError.value = null
  if (!raw) return null
  const regexMatch = raw.match(/^\/(.+)\/([a-z]*)$/i)
  if (regexMatch) {
    try {
      const flags = regexMatch[2]!.includes('i') ? regexMatch[2]! : `${regexMatch[2]}i`
      const re = new RegExp(regexMatch[1]!, flags)
      return { test: (haystack: string) => re.test(haystack) }
    } catch (err) {
      rowFilterRegexError.value = err instanceof Error ? err.message : t('kwic.table.invalidRegex')
      // Fall through to substring matching on the raw pattern body.
      const needle = regexMatch[1]!.toLowerCase()
      return { test: (haystack: string) => haystack.toLowerCase().includes(needle) }
    }
  }
  const needle = raw.toLowerCase()
  return { test: (haystack: string) => haystack.toLowerCase().includes(needle) }
})

const isRowFilterActive = computed(() => compiledRowFilter.value !== null)

function rowFilterHaystack(index: number): string {
  const row = queryStore.results[index]
  if (!row) return ''
  const meta = getRowMeta(index)
  const metaText = meta
    ? Object.values(meta).filter((v) => typeof v === 'string').join(' ')
    : ''
  return [row.left ?? '', row.match ?? '', row.right ?? '', metaText].join(' ')
}

function isRowVisibleByTextFilter(index: number): boolean {
  const filter = compiledRowFilter.value
  if (!filter) return true
  return filter.test(rowFilterHaystack(index))
}

function isRowVisibleByCategory(index: number): boolean {
  if (!annotationsStore.filterEnabled) return true
  const id = rowIdForIndex(index)
  return id ? annotationsStore.rowMatchesFilter(id) : false
}

// Combined visibility: a filtered-out row keeps its slot in the virtualizer (so
// every index stays stable for selection/parallel logic) but is visually
// collapsed to ~0px via the `is-filtered-out` class, which zeroes the row's
// min-height, padding and border on top of skipping the inner content render.
function isRowVisibleByFilter(index: number): boolean {
  return isRowVisibleByCategory(index) && isRowVisibleByTextFilter(index)
}

function clearRowFilter() {
  rowFilterText.value = ''
  void remeasureVirtualizer()
}

watch(rowFilterText, () => {
  void remeasureVirtualizer()
})

const categoryFilterCount = computed(() => {
  if (!annotationsStore.filterEnabled && !isRowFilterActive.value) return queryStore.results.length
  return queryStore.results.reduce(
    (acc, _row, index) => (isRowVisibleByFilter(index) ? acc + 1 : acc),
    0
  )
})

function toggleCategoryFilter(categoryId: string | null) {
  if (annotationsStore.filterEnabled && annotationsStore.filterCategoryId === categoryId) {
    annotationsStore.clearFilter()
  } else {
    annotationsStore.setFilter(categoryId, true)
  }
  void remeasureVirtualizer()
}

// Keyboard coding: with a single row selected, pressing a category's shortcut
// key assigns it (toggles off if already assigned). Wired into handleKeyDown.
function handleAnnotationShortcut(event: KeyboardEvent): boolean {
  if (event.metaKey || event.ctrlKey || event.altKey) return false
  const key = event.key
  if (!key || key.length !== 1) return false
  const category = annotationsStore.categories.find(
    (c) => c.shortcut && c.shortcut.toLowerCase() === key.toLowerCase()
  )
  if (!category) return false
  const selected = Array.from(queryStore.selectedRows)
  if (selected.length !== 1) return false
  const index = selected[0]!
  const current = rowCategory(index)
  void assignCategoryImmediately(index, current?.id === category.id ? null : category.id)
  return true
}

// Expanded context rows
const expandedContextRows = ref<Set<number>>(new Set())

interface RowDetailState {
  loading: boolean
  error: string | null
  snippet?: DocSnippet
}

const rowDetails = ref<Map<number, RowDetailState>>(new Map())
const DETAIL_CTX = 120
const META_CHIP_KEYS = ['source', 'text_type', 'model', 'variant', 'register', 'reference_kind', 'ref_doc']

const META_OMIT_KEYS = new Set(['path', 'doc_id'])

interface ParallelState {
  loading: boolean
  error: string | null
  result?: ParallelKwicResult
}

const parallelEnabled = ref(false)
const parallelModels = ref<string[]>([])
const parallelMaxVariants = ref(3)
const parallelSentenceMargin = ref(6)
const parallelDetails = ref<Map<number, ParallelState>>(new Map())
const PARALLEL_MAX_VARIANTS = 6
const parallelQueue = new Set<number>()
const parallelInFlightRows = new Set<string>()
let activeParallelRequests = 0
let parallelRequestGeneration = 0

// A side-by-side column must name one stable variant. Auto-selecting a different
// model for each row is useful neither as a comparison nor as research evidence.
const canRunParallel = computed(() =>
  canUseParallel.value && parallelModels.value.length > 0,
)

function clampParallelVariants(value: number): number {
  if (!Number.isFinite(value)) return 1
  return Math.max(1, Math.min(Math.round(value), PARALLEL_MAX_VARIANTS))
}

function computeAutoAlignSlice(width: number, height: number): number {
  if (!height || height <= 0) return autoAlignSlice.value
  const baseRowPx = 74
  let rows = Math.floor(height / baseRowPx)
  const widthAdj = clamp((width - 1200) / 1200, -0.3, 0.4)
  rows = Math.round(rows * (1 + widthAdj * 0.35))
  return clamp(rows, 8, 20)
}

function computeAutoAlignWindow(slice: number): number {
  return clamp(slice * 3, 24, 120)
}

function alignmentWindowSize(result: AlignmentRefDocResult | undefined): number {
  if (!result) return 0
  return Math.max(0, result.reference.window_end - result.reference.window_start)
}

function maybeRefetchExpandedAlignments(desiredWindow: number) {
  for (const index of expandedContextRows.value) {
    const refDoc = getRowRefDoc(index)
    if (refDoc === null) continue
    const state = getAlignmentState(index)
    if (!state?.result) continue
    const currentWindow = alignmentWindowSize(state.result)
    if (currentWindow + 6 >= desiredWindow) continue
    void fetchAlignment(index, { force: true, windowSentences: desiredWindow })
  }
}

function recomputeAutoAlign(reason: 'resize' | 'init' = 'resize') {
  const el = containerRef.value
  if (!el) return
  const nextWidth = Math.max(320, el.clientWidth)
  const nextHeight = Math.max(320, el.clientHeight)
  const prevWindow = autoAlignWindowSentences.value
  const nextSlice = computeAutoAlignSlice(nextWidth, nextHeight)
  const nextWindow = computeAutoAlignWindow(nextSlice)
  autoAlignSlice.value = nextSlice
  autoAlignWindowSentences.value = nextWindow
  if (reason !== 'init' && nextWindow > prevWindow + 4) {
    maybeRefetchExpandedAlignments(nextWindow)
  }
}

function scheduleAutoAlignRecompute() {
  if (resizeTimer !== null) {
    window.clearTimeout(resizeTimer)
  }
  resizeTimer = window.setTimeout(() => {
    resizeTimer = null
    recomputeAutoAlign('resize')
  }, 120)
}

function setRowDetail(index: number, state: RowDetailState) {
  rowDetails.value.set(index, state)
  rowDetails.value = new Map(rowDetails.value)
}

function getRowDetailState(index: number): RowDetailState | undefined {
  return rowDetails.value.get(index)
}

function setParallelDetail(index: number, state: ParallelState) {
  parallelDetails.value.set(index, state)
  parallelDetails.value = new Map(parallelDetails.value)
}

function getParallelState(index: number): ParallelState | undefined {
  return parallelDetails.value.get(index)
}

/**
 * Re-key all index-keyed row detail caches by `+shift` after `shift` rows are
 * prepended to `queryStore.results`. Without this, caches keyed by array index
 * alias to the wrong rows (wrong snippet/alignment shown) once rows shift down.
 */
function shiftRowCaches(shift: number) {
  if (shift <= 0) return
  const shiftMap = <V>(source: Map<number, V>): Map<number, V> => {
    const next = new Map<number, V>()
    source.forEach((value, key) => next.set(key + shift, value))
    return next
  }
  rowDetails.value = shiftMap(rowDetails.value)
  parallelDetails.value = shiftMap(parallelDetails.value)
  alignmentDetails.value = shiftMap(alignmentDetails.value)
  if (parallelQueue.size) {
    const shiftedQueue = Array.from(parallelQueue, (index) => index + shift)
    parallelQueue.clear()
    shiftedQueue.forEach((index) => parallelQueue.add(index))
  }
  const nextExpanded = new Set<number>()
  expandedContextRows.value.forEach((idx) => nextExpanded.add(idx + shift))
  expandedContextRows.value = nextExpanded
}

function getDetailSnippet(index: number): DocSnippet | undefined {
  return getRowDetailState(index)?.snippet
}

function getRowMeta(index: number): Record<string, string> | undefined {
  const snippetMeta = getDetailSnippet(index)?.meta
  if (snippetMeta && Object.keys(snippetMeta).length > 0) return snippetMeta
  return queryStore.results[index]?.metadata
}

function getRowDocLabel(index: number): string {
  return (
    getDetailSnippet(index)?.doc ||
    queryStore.results[index]?.docTitle ||
    queryStore.results[index]?.docId ||
    ''
  )
}

function getRowParts(index: number): { left: string; match: string; right: string } {
  const snippet = getDetailSnippet(index)
  const row = queryStore.results[index]
  return {
    left: snippet?.left ?? row?.left ?? '',
    match: snippet?.kw ?? row?.match ?? '',
    right: snippet?.right ?? row?.right ?? '',
  }
}

// The line in the annotation dialog shows this many words on each side of
// the node. The whole context is in the document panel. With the full
// context of the search (up to several hundred tokens) the code and the note
// moved below the fold of the dialog.
const ANNOTATION_PREVIEW_WORDS = 12

function annotationPreview(index: number): { left: string; leftCut: boolean; match: string; right: string; rightCut: boolean } {
  const parts = getRowParts(index)
  const leftWords = parts.left.trim().split(/\s+/).filter(Boolean)
  const rightWords = parts.right.trim().split(/\s+/).filter(Boolean)
  return {
    left: leftWords.slice(-ANNOTATION_PREVIEW_WORDS).join(' '),
    leftCut: leftWords.length > ANNOTATION_PREVIEW_WORDS,
    match: parts.match,
    right: rightWords.slice(0, ANNOTATION_PREVIEW_WORDS).join(' '),
    rightCut: rightWords.length > ANNOTATION_PREVIEW_WORDS,
  }
}

const annotationPreviewLine = computed(() =>
  annotationPopoverIndex.value === null ? null : annotationPreview(annotationPopoverIndex.value),
)

/** The whole counterpart sentence of a parallel cell, for its title. */
function variantSentence(variant: { left?: string | null; kw?: string | null; right?: string | null } | null | undefined): string | undefined {
  if (!variant) return undefined
  const text = [variant.left, variant.kw, variant.right].map((part) => (part ?? '').trim()).filter(Boolean).join(' ')
  return text || undefined
}

function getMetaChips(index: number): Array<{ key: string; value: string; label: string }> {
  const meta = getRowMeta(index)
  if (!meta) return []
  const chips: Array<{ key: string; value: string; label: string }> = []
  for (const key of META_CHIP_KEYS) {
    const value = meta[key]
    // text_type names the side of a pair (anchor/version, older human/ai).
    if (value) chips.push({ key, value, label: key === 'text_type' ? textTypeLabel(value) : value })
  }
  return chips
}

function getMetaSummary(index: number): string {
  const meta = getRowMeta(index)
  if (!meta) return ''
  const chips = new Set(META_CHIP_KEYS)
  const rest = Object.entries(meta)
    .filter(([key, value]) => {
      if (!value) return false
      if (chips.has(key)) return false
      if (META_OMIT_KEYS.has(key)) return false
      return true
    })
    .slice(0, 8)
    .map(([key, value]) => `${key}: ${value}`)
  return rest.join(' · ')
}

interface AlignmentState {
  loading: boolean
  error: string | null
  result?: AlignmentRefDocResult
}

const alignmentDetails = ref<Map<number, AlignmentState>>(new Map())
const ALIGN_MAX_VARIANTS = 6
const autoAlignSlice = ref(12)
const autoAlignWindowSentences = ref(36)

function clamp(n: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, n))
}

const parallelColumnCount = computed(() => {
  if (!parallelEnabled.value || parallelModels.value.length === 0) return 0
  return clampParallelVariants(parallelModels.value.length)
})

function parallelColumnsForRow(index: number): Array<ParallelKwicVariant | null> {
  const count = parallelColumnCount.value
  if (count <= 0) return []
  const state = getParallelState(index)
  const variants = state?.result?.variants ?? []
  const slots: Array<ParallelKwicVariant | null> = Array.from({ length: count }, () => null)
  if (parallelModels.value.length > 0) {
    const byModel = new Map<string, ParallelKwicVariant>()
    for (const variant of variants) {
      const model = variant.model?.trim()
      if (!model) continue
      if (!byModel.has(model)) byModel.set(model, variant)
    }
    orderedParallelModels.value.slice(0, count).forEach((model, idx) => {
      slots[idx] = byModel.get(model) ?? null
    })
    return slots
  }
  variants.slice(0, count).forEach((variant, idx) => {
    slots[idx] = variant
  })
  return slots
}

function parallelVariantLabel(variant: ParallelKwicVariant | null, fallbackIndex: number): string {
  if (!variant) return t('kwic.table.variantN', { n: fallbackIndex + 1 })
  const explicit = variant.label?.trim() || variant.axis_value?.trim()
  if (explicit) return explicit
  const model = variant.model?.trim()
  if (model) return model
  if (variant.text_type) return textTypeLabel(variant.text_type)
  return t('kwic.table.variantN', { n: fallbackIndex + 1 })
}

function parallelCellPlaceholder(index: number): string {
  const state = getParallelState(index)
  if (state?.loading) return t('kwic.table.loading')
  if (state?.error) return t('kwic.table.error')
  return '—'
}

function formatFloat(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '–'
  return value.toFixed(digits)
}

function setAlignmentDetail(index: number, state: AlignmentState) {
  alignmentDetails.value.set(index, state)
  alignmentDetails.value = new Map(alignmentDetails.value)
}

function getAlignmentState(index: number): AlignmentState | undefined {
  return alignmentDetails.value.get(index)
}

function parseRefDoc(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.trunc(value)
  }
  if (typeof value === 'string') {
    const match = value.match(/\d+/)
    if (match) return Number.parseInt(match[0], 10)
  }
  return null
}

function getRowRefDoc(index: number): number | null {
  if (refDocOverride.value !== null) return refDocOverride.value
  const meta = getRowMeta(index)
  const refFromMeta = parseRefDoc(meta?.ref_doc ?? meta?.refDoc)
  if (refFromMeta !== null) return refFromMeta
  const snippetRef = parseRefDoc(getDetailSnippet(index)?.doc_id)
  if (snippetRef !== null) return snippetRef
  const docIdRef = parseRefDoc(queryStore.results[index]?.docId)
  return docIdRef
}

function alignmentVisibleSentenceCount(index: number): number {
  const sentenceCount = getAlignmentState(index)?.result?.reference.sentences.length ?? 0
  return Math.min(sentenceCount, autoAlignSlice.value)
}

const contextFr = computed(() => {
  const width = containerWidth.value || 1200
  const variantCount = parallelEnabled.value ? parallelColumnCount.value : 0
  const reserved = 72 + 60 + 40 + variantCount * 260 + 40
  const available = Math.max(300, width - reserved)
  const fr = Math.min(1.8, Math.max(0.8, available / 520))
  return Number(fr.toFixed(2))
})

// Width of the widest node among the loaded lines, in the font of the node
// cell. The node track is at least that wide, up to 40 percent of the table,
// so that a node of two tokens such as "American freedoms" is not cut.
const nodeTextWidth = ref(0)
let nodeMeasureCanvas: HTMLCanvasElement | null = null

// The node cell is semibold with 4 px padding on each side (.row-match px-1
// and .kwic-match), in the font of the table.
const NODE_CELL_PADDING_PX = 12

function measureNodeTextWidth() {
  const table = containerRef.value
  if (!table || isMobile.value) return
  const style = getComputedStyle(table)
  const fontSize = parseFloat(style.fontSize) || 16
  let context: CanvasRenderingContext2D | null = null
  if (style.fontFamily) {
    nodeMeasureCanvas ??= document.createElement('canvas')
    context = nodeMeasureCanvas.getContext('2d')
    if (context) context.font = `600 ${fontSize}px ${style.fontFamily}`
  }
  let widest = 0
  for (let index = 0; index < queryStore.results.length; index += 1) {
    const text = displayRow(index).match
    if (!text) continue
    const width = context ? context.measureText(text).width : text.length * fontSize * 0.6
    if (width > widest) widest = width
  }
  nodeTextWidth.value = Math.ceil(widest + NODE_CELL_PADDING_PX)
}

watch(
  () => [queryStore.results.length, queryStore.results[0]?.match, isMobile.value, containerRef.value] as const,
  () => { void nextTick(measureNodeTextWidth) },
  { immediate: true },
)

const nodeTrackMin = computed(() => {
  const cap = Math.max(120, Math.floor((containerWidth.value || 1200) * 0.4))
  return Math.min(cap, Math.max(120, nodeTextWidth.value))
})

const kwicMinWidth = computed(() => {
  const variantCount = parallelEnabled.value ? parallelColumnCount.value : 0
  const base = 72 + 2 * 220 + nodeTrackMin.value + variantCount * 220 + 60
  const width = containerWidth.value || 0
  return Math.max(base, width)
})

const rowDesktopStyle = computed<Record<string, string>>(() => {
  const variantCount = parallelEnabled.value ? parallelColumnCount.value : 0
  // The sticky header and every body row are independent CSS grids. A
  // content-sized `auto` Match/Actions track therefore resolves to a DIFFERENT
  // width in the header (short labels) than in the data rows (long node tokens),
  // so the header labels slide off their columns ("MATCHRECHTER KONTEXT"). Use
  // deterministic, content-independent tracks so all grids compute identical
  // columns and the header sits exactly over the body (DESIGN-UX-GLOBAL-01).
  const columns = [
    '72px',
    `minmax(0, ${contextFr.value}fr)`,
    `minmax(${nodeTrackMin.value}px, 0.55fr)`,
    `minmax(0, ${contextFr.value}fr)`,
    ...Array.from({ length: variantCount }, () => 'minmax(220px, 1fr)'),
    '96px',
  ]
  return { gridTemplateColumns: columns.join(' ') }
})

async function fetchAlignment(
  index: number,
  opts?: { force?: boolean; windowSentences?: number }
) {
  if (!canOpenAlignment.value) {
    setAlignmentDetail(index, {
      loading: false,
      error: alignmentBlockReason.value ?? t('kwic.table.alignmentNotEnabled'),
    })
    return
  }
  const row = queryStore.results[index]
  if (!row) return
  const refDoc = getRowRefDoc(index)
  if (refDoc === null) return
  const existing = getAlignmentState(index)
  const force = Boolean(opts?.force)
  if (existing?.loading) return
  if (existing?.result && !force) return
  setAlignmentDetail(index, { loading: true, error: null })
  try {
    const windowSentences = Math.max(12, opts?.windowSentences ?? autoAlignWindowSentences.value)
    const openedDocId = parseRefDoc(row.docId)
    const openedVariant = refDocOverride.value === null
      && openedDocId !== null
      && openedDocId !== refDoc
    const result = await loadAlignmentRefDoc({
      refDoc,
      corpus: queryStore.filters.corpus,
      focusPos: refDocOverride.value === null ? row.position : undefined,
      includeDocIds: openedVariant && openedDocId !== null ? [openedDocId] : undefined,
      windowSentences,
      maxVariants: openedVariant ? 1 : ALIGN_MAX_VARIANTS,
    })
    setAlignmentDetail(index, { loading: false, error: null, result })
    void remeasureVirtualizer()
  } catch (err) {
    const message = err instanceof Error ? err.message : t('kwic.table.alignmentFailed')
    setAlignmentDetail(index, { loading: false, error: message })
    void remeasureVirtualizer()
  }
}

function clearParallelDetails() {
  parallelRequestGeneration += 1
  parallelPrefetchGeneration += 1
  parallelContextSettling = false
  parallelQueue.clear()
  parallelDetails.value = new Map()
}

function currentParallelRowIndex(index: number, position: number, docId: string): number | null {
  const atIndex = queryStore.results[index]
  if (atIndex?.position === position && atIndex.docId === docId) return index
  const relocated = queryStore.results.findIndex((candidate) =>
    candidate.position === position && candidate.docId === docId
  )
  return relocated >= 0 ? relocated : null
}

function parallelRowKey(index: number): string | null {
  const row = queryStore.results[index]
  if (!row) return null
  return `${row.docId}\u001f${row.position}`
}

async function fetchParallelKwic(index: number, generation: number) {
  if (!parallelEnabled.value || !canRunParallel.value) return
  if (!canLoadParallelKwic.value) {
    setParallelDetail(index, {
      loading: false,
      error: parallelKwicBlockReason.value ?? t('kwic.table.parallelNotEnabled'),
    })
    return
  }
  const row = queryStore.results[index]
  if (!row) return
  const rowPosition = row.position
  const rowDocId = row.docId
  const existing = getParallelState(index)
  if (existing?.loading || existing?.result) return
  const keyword = row.match?.trim() || queryStore.term?.trim() || ''
  if (!keyword) return
  setParallelDetail(index, { loading: true, error: null })
  try {
    const maxVariants = clampParallelVariants(
      Math.max(parallelModels.value.length, parallelMaxVariants.value)
    )
    const result = await loadParallelKwic({
      pos: rowPosition,
      keyword,
      ctx: queryStore.contextSize,
      corpus: queryStore.filters.corpus,
      includeModels: parallelModels.value.length > 0 ? orderedParallelModels.value : undefined,
      maxVariants,
      sentenceMargin: parallelSentenceMargin.value,
      excludeBase: true,
    })
    if (generation !== parallelRequestGeneration || !parallelEnabled.value) return
    const targetIndex = currentParallelRowIndex(index, rowPosition, rowDocId)
    if (targetIndex === null) return
    setParallelDetail(targetIndex, { loading: false, error: null, result })
    void remeasureVirtualizer()
  } catch (err) {
    if (generation !== parallelRequestGeneration || !parallelEnabled.value) return
    const targetIndex = currentParallelRowIndex(index, rowPosition, rowDocId)
    if (targetIndex === null) return
    const message = err instanceof Error ? err.message : t('kwic.table.parallelFailed')
    setParallelDetail(targetIndex, { loading: false, error: message })
    void remeasureVirtualizer()
  }
}

function drainParallelQueue() {
  let deferredInFlightRows = 0
  while (
    parallelEnabled.value &&
    canRunParallel.value &&
    activeParallelRequests < PARALLEL_MAX_CONCURRENT_REQUESTS &&
    parallelQueue.size > 0
  ) {
    const nextIndex = parallelQueue.values().next().value as number | undefined
    if (nextIndex === undefined) return
    parallelQueue.delete(nextIndex)
    const rowKey = parallelRowKey(nextIndex)
    if (!rowKey) {
      deferredInFlightRows = 0
      continue
    }
    if (parallelInFlightRows.has(rowKey)) {
      // A stale request for this exact KWIC row is still finishing after a
      // configuration change. Keep the current request queued rather than
      // issuing the same backend call twice in parallel.
      parallelQueue.add(nextIndex)
      deferredInFlightRows += 1
      if (deferredInFlightRows >= parallelQueue.size) return
      continue
    }
    deferredInFlightRows = 0
    const generation = parallelRequestGeneration
    parallelInFlightRows.add(rowKey)
    activeParallelRequests += 1
    void fetchParallelKwic(nextIndex, generation).finally(() => {
      activeParallelRequests -= 1
      parallelInFlightRows.delete(rowKey)
      drainParallelQueue()
    })
  }
}

function ensureParallelForRow(index: number) {
  if (!parallelEnabled.value || !canRunParallel.value) return
  const existing = getParallelState(index)
  if (existing?.loading || existing?.result || parallelQueue.has(index)) return
  parallelQueue.add(index)
  drainParallelQueue()
}

function prefetchParallelForVisibleRows() {
  if (!parallelEnabled.value || !canRunParallel.value || parallelContextSettling) return

  // TanStack includes an overscan buffer in `virtualRows`. Queue only rows
  // intersecting the actual viewport: researchers see a complete comparison
  // for the rows in front of them, while a fast scroll does not create a long
  // backlog of now-invisible alignment requests.
  const container = containerRef.value
  const viewportTop = container?.scrollTop ?? 0
  const viewportBottom = viewportTop + (container?.clientHeight ?? 0)
  const visibleIndices = new Set(
    virtualRows.value
      .filter((virtualRow) => {
        if (!container || viewportBottom <= viewportTop) return true
        const rowStart = virtualRow.start
        const rowEnd = rowStart + virtualRow.size
        return rowEnd > viewportTop && rowStart < viewportBottom
      })
      .map((virtualRow) => virtualRow.index),
  )

  // Requests which have not started yet are no longer useful after a scroll.
  // Running requests finish normally and are kept as a cache for a possible
  // return to that row; at most two can exist at any time.
  for (const index of Array.from(parallelQueue)) {
    if (!visibleIndices.has(index)) parallelQueue.delete(index)
  }
  for (const index of visibleIndices) {
    ensureParallelForRow(index)
  }
}

function scheduleParallelPrefetch(settleContext = false) {
  const generation = ++parallelPrefetchGeneration
  if (!parallelEnabled.value || !canRunParallel.value) return
  if (!settleContext || !autoContextEnabled.value) {
    parallelContextSettling = false
    void nextTick(() => {
      if (
        generation !== parallelPrefetchGeneration ||
        !parallelEnabled.value ||
        !canRunParallel.value ||
        parallelContextSettling
      ) return
      prefetchParallelForVisibleRows()
    })
    return
  }

  // Parallel columns change the usable context width. Settle that width before
  // sending the first row requests, so enabling the projection does not issue
  // one stale batch followed by the same rows with a different context size.
  parallelContextSettling = true
  scheduleAutoContextRecompute(() => {
    if (generation !== parallelPrefetchGeneration) return
    parallelContextSettling = false
    if (parallelEnabled.value && canRunParallel.value) {
      prefetchParallelForVisibleRows()
    }
  })
}

async function fetchRowDetail(index: number) {
  const row = queryStore.results[index]
  if (!row) return
  const existing = getRowDetailState(index)
  if (existing?.loading || existing?.snippet) return
  setRowDetail(index, { loading: true, error: null })
  try {
    const snippet = await loadDocSnippet({
      pos: row.position,
      ctx: DETAIL_CTX,
      corpus: queryStore.filters.corpus,
    })
    setRowDetail(index, { loading: false, error: null, snippet })
    void remeasureVirtualizer()
  } catch (err) {
    const message = err instanceof Error ? err.message : t('kwic.table.snippetFailed')
    setRowDetail(index, { loading: false, error: message })
    void remeasureVirtualizer()
  }
}

async function ensureRowExpanded(index: number) {
  if (!expandedContextRows.value.has(index)) {
    expandedContextRows.value.add(index)
  }
  await fetchRowDetail(index)
  if (canOpenAlignment.value) {
    await fetchAlignment(index)
  }
}

// Track scroll position for history and session recovery
function handleScroll() {
  if (!containerRef.value) return
  queryStore.setScrollPosition(containerRef.value.scrollTop)
  maybeAutoLoadMore()
}

let autoLoadTimer: number | null = null
let autoLoadPrevTimer: number | null = null
const AUTOLOAD_THRESHOLD_PX = 600
const AUTOLOAD_TOP_PX = 260

function maybeAutoLoadMore() {
  if (!containerRef.value || isStreaming.value) return
  const el = containerRef.value
  if (queryStore.hasPrevious && el.scrollTop < AUTOLOAD_TOP_PX) {
    if (autoLoadPrevTimer !== null) return
    autoLoadPrevTimer = window.setTimeout(async () => {
      autoLoadPrevTimer = null
      await loadPreviousResults()
    }, 80)
  }
  if (!queryStore.hasMore) return
  const remaining = el.scrollHeight - (el.scrollTop + el.clientHeight)
  if (remaining > AUTOLOAD_THRESHOLD_PX) return
  if (autoLoadTimer !== null) return
  autoLoadTimer = window.setTimeout(async () => {
    autoLoadTimer = null
    await loadMoreResults()
  }, 80)
}

// Virtualizer setup - useVirtualizer returns a Ref, so we use it directly
const rowVirtualizer = useVirtualizer(
  computed(() => ({
    count: queryStore.results.length,
    getScrollElement: () => containerRef.value,
    estimateSize: () => 48, // Base row height in px
    overscan: 10,
    getItemKey: (index: number) => queryStore.results[index]?.position ?? index
  }))
)

const virtualRows = computed(() => rowVirtualizer.value.getVirtualItems())
const totalSize = computed(() => rowVirtualizer.value.getTotalSize())

function measureRow(refEl: Element | ComponentPublicInstance | null) {
  if (!refEl) return
  const el = refEl instanceof Element ? refEl : (refEl.$el as Element | undefined)
  if (!el) return
  rowVirtualizer.value.measureElement(el as HTMLElement)
}

async function remeasureVirtualizer() {
  await nextTick()
  rowVirtualizer.value.measure()
}

// Scroll to specific row
function scrollToRow(index: number) {
  rowVirtualizer.value.scrollToIndex(index, { align: 'center' })
}

// Register virtual rows in element registry for ghost cursor targeting
const ROW_HEIGHT = 48

function registerVirtualRow(index: number) {
  const elementId = `kwic-row-${index}`

  return elementRegistry.registerVirtual(elementId, {
    getPosition: () => {
      if (!containerRef.value) return null

      const containerRect = containerRef.value.getBoundingClientRect()
      const scrollTop = containerRef.value.scrollTop

      // Calculate row position relative to viewport
      const rowTop = ROW_HEIGHT * index - scrollTop
      const rowCenter = rowTop + ROW_HEIGHT / 2

      return {
        x: containerRect.left + containerRect.width / 2,
        y: containerRect.top + rowCenter,
        width: containerRect.width,
        height: ROW_HEIGHT
      }
    },
    scrollIntoView: async () => {
      rowVirtualizer.value.scrollToIndex(index, { align: 'center' })
      await nextTick()
      // Small delay for scroll animation
      await new Promise(resolve => setTimeout(resolve, 100))
    },
    getActivationAction: () => ({
      type: 'kwic/selectRows',
      payload: { indices: [index] },
    }),
    metadata: {
      type: 'kwic-row',
      index
    }
  })
}

// Track registered rows
const registeredRowCount = ref(0)

// Register rows when results change
watch(
  () => queryStore.results.length,
  (newCount, oldCount) => {
    // When rows are removed/replaced the row count shrinks. Re-register from
    // scratch and prune any cache entries whose index no longer exists, so the
    // index-keyed caches never alias a stale row. (Prepends keep the count
    // growing and are handled by shiftRowCaches; the registration loop below
    // covers pure appends.)
    if (oldCount !== undefined && newCount < oldCount) {
      elementRegistry.clearMatching(/^kwic-row-/)
      registeredRowCount.value = 0

      // Keep only entries for indices that still exist
      const validIndices = new Set<number>()
      for (let i = 0; i < newCount; i++) validIndices.add(i)

      for (const key of rowDetails.value.keys()) {
        if (!validIndices.has(key)) rowDetails.value.delete(key)
      }
      for (const key of alignmentDetails.value.keys()) {
        if (!validIndices.has(key)) alignmentDetails.value.delete(key)
      }
      for (const key of parallelDetails.value.keys()) {
        if (!validIndices.has(key)) parallelDetails.value.delete(key)
      }
      for (const index of parallelQueue) {
        if (!validIndices.has(index)) parallelQueue.delete(index)
      }
      for (const idx of expandedContextRows.value) {
        if (!validIndices.has(idx)) expandedContextRows.value.delete(idx)
      }
    }

    // Register new rows
    for (let i = registeredRowCount.value; i < newCount; i++) {
      registerVirtualRow(i)
    }
    registeredRowCount.value = newCount
    if (newCount > 0) {
      void remeasureVirtualizer()
    }
  },
  { immediate: true }
)

// Reset row details and expanded contexts when the search term changes
watch(
  () => queryStore.term,
  () => {
    expandedContextRows.value = new Set()
    rowDetails.value = new Map()
    alignmentDetails.value = new Map()
    clearParallelDetails()
  }
)

// A repeated search can keep the same literal term while changing filters or
// scope. Invalidate in-flight parallel rows as soon as the new search starts
// so no old alignment can appear in the replacement result set.
watch(
  () => queryStore.isLoading,
  (loading) => {
    if (loading && parallelEnabled.value) clearParallelDetails()
  }
)

// If product or corpus state stops allowing Parallel-KWIC, force the projection
// off so its endpoint is never invoked.
watch(
  canUseParallel,
  (allowed) => {
    if (!allowed && parallelEnabled.value) {
      disableParallel()
    }
  },
  { immediate: true }
)

watch(parallelEnabled, (enabled) => {
  if (enabled) {
    // Parallel-KWIC only needs the model axis. Loading it independently keeps
    // the selector usable for valid pre-aligned corpora that do not expose the
    // complete legacy prompting/register/source filter quartet.
    void docsetStore.loadModelOptionsForPrompt()
    clearParallelDetails()
    scheduleParallelPrefetch(true)
    return
  }
  clearParallelDetails()
  parallelPresetId.value = null
  parallelPinnedModels.value = []
}, { flush: 'sync' })

watch(
  () => parallelModels.value.slice(),
  () => {
    if (!parallelEnabled.value) return
    syncPinnedModels()
    const desiredMax = clampParallelVariants(
      Math.max(parallelModels.value.length, parallelMaxVariants.value)
    )
    if (desiredMax !== parallelMaxVariants.value) {
      parallelMaxVariants.value = desiredMax
      return
    }
    clearParallelDetails()
    scheduleParallelPrefetch(true)
    if (activePreset.value && !matchesPreset(activePreset.value)) {
      parallelPresetId.value = null
    }
  }
)

watch(
  () => parallelMaxVariants.value,
  (value) => {
    const clamped = clampParallelVariants(value)
    if (clamped !== value) {
      parallelMaxVariants.value = clamped
      return
    }
    if (!parallelEnabled.value) return
    clearParallelDetails()
    scheduleParallelPrefetch(true)
    if (activePreset.value && !matchesPreset(activePreset.value)) {
      parallelPresetId.value = null
    }
  }
)

watch(
  () => parallelSentenceMargin.value,
  () => {
    if (!parallelEnabled.value) return
    clearParallelDetails()
    scheduleParallelPrefetch()
    if (activePreset.value && !matchesPreset(activePreset.value)) {
      parallelPresetId.value = null
    }
  }
)

watch(
  () => parallelPinnedModels.value.slice(),
  () => {
    syncPinnedModels()
    if (activePreset.value && !matchesPreset(activePreset.value)) {
      parallelPresetId.value = null
    }
  }
)

watch(
  () => queryStore.contextSize,
  () => {
    if (!parallelEnabled.value || parallelContextSettling) return
    clearParallelDetails()
    scheduleParallelPrefetch()
  }
)

watch(
  () => queryStore.filters.corpus,
  () => {
    if (!parallelEnabled.value) return
    clearParallelDetails()
    scheduleParallelPrefetch()
  }
)

watch(
  () => virtualRows.value,
  () => {
    if (!parallelEnabled.value || parallelContextSettling) return
    prefetchParallelForVisibleRows()
  },
  { immediate: true }
)

watch(
  () => isStreaming.value,
  (streaming) => {
    if (streaming) return
    requestAnimationFrame(() => {
      maybeAutoLoadMore()
    })
  }
)

// Attach scroll tracking
onMounted(() => {
  void productCapabilities.load()
  parallelPresetsStore.init()
  containerRef.value?.addEventListener('scroll', handleScroll, { passive: true })
  void nextTick(() => {
    recomputeAutoAlign('init')
    updateContainerWidth()
    scheduleAutoContextRecompute()
    if (containerRef.value && typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        updateContainerWidth()
        scheduleAutoAlignRecompute()
        scheduleAutoContextRecompute()
      })
      resizeObserver.observe(containerRef.value)
    }
  })
})

// Cleanup on unmount
onUnmounted(() => {
  containerRef.value?.removeEventListener('scroll', handleScroll)
  containerRef.value?.removeEventListener('scroll', handleBodyScroll)
  headerScrollRef.value?.removeEventListener('scroll', handleHeaderScroll)
  if (resizeObserver && containerRef.value) {
    resizeObserver.unobserve(containerRef.value)
  }
  resizeObserver?.disconnect()
  resizeObserver = null
  if (resizeTimer !== null) {
    window.clearTimeout(resizeTimer)
    resizeTimer = null
  }
  if (autoContextTimer !== null) {
    window.clearTimeout(autoContextTimer)
    autoContextTimer = null
  }
  autoContextSettledCallbacks.clear()
  if (autoLoadTimer !== null) {
    window.clearTimeout(autoLoadTimer)
    autoLoadTimer = null
  }
  if (autoLoadPrevTimer !== null) {
    window.clearTimeout(autoLoadPrevTimer)
    autoLoadPrevTimer = null
  }
  if (textMeasureEl) {
    textMeasureEl.remove()
    textMeasureEl = null
  }
  elementRegistry.clearMatching(/^kwic-row-/)
})

// Restore scroll position when requested by history/session recovery
watch(
  () => queryStore.pendingScrollPosition,
  async (pending) => {
    if (pending === null || !containerRef.value) return
    await nextTick()
    containerRef.value.scrollTop = pending
    queryStore.setPendingScrollPosition(null)
  }
)

watch(
  () => [autoContextEnabled.value, parallelEnabled.value, parallelColumnCount.value],
  () => {
    if (autoContextEnabled.value) {
      scheduleAutoContextRecompute()
    }
  }
)

watch(
  () => autoContextEnabled.value,
  (enabled) => {
    if (enabled) {
      scheduleAutoContextRecompute()
    } else {
      contextSliderValue.value = queryStore.contextSize
    }
  }
)

watch(
  () => queryStore.results.length,
  () => {
    textFitCache.clear()
    widthSignature = ''
    scheduleAutoContextRecompute()
  }
)

watch(
  () => queryStore.term,
  () => {
    textFitCache.clear()
    widthSignature = ''
    scheduleAutoContextRecompute()
  }
)

// Row selection handlers
function handleRowClick(index: number, event: MouseEvent) {
  const isModified = event.shiftKey || event.metaKey || event.ctrlKey
  if (event.shiftKey && queryStore.selectedRows.size > 0) {
    // Range selection
    const lastSelected = Math.max(...Array.from(queryStore.selectedRows))
    const start = Math.min(lastSelected, index)
    const end = Math.max(lastSelected, index)
    
    queryStore.deselectAll()
    for (let i = start; i <= end; i++) {
      queryStore.selectRow(i, true)
    }
  } else if (event.metaKey || event.ctrlKey) {
    // Multi-selection
    queryStore.toggleRow(index)
  } else {
    // Single selection
    queryStore.selectRow(index, false)
  }

  // A plain click should open the row detail view.
  if (!isModified) {
    openDocumentForRow(index)
  }
}

function openDocumentForRow(index: number) {
  const row = queryStore.results[index]
  if (!row?.docId) return
  void actionBus.dispatch(
    {
      type: 'nav/openDocument',
      payload: {
        docId: String(row.docId),
        corpus: queryStore.filters.corpus ?? docsetStore.activeCorpus,
        highlight: row.match?.trim(),
        highlightPosition: row.position,
        highlightLeft: row.left,
        highlightRight: row.right,
      },
    },
    { source: 'user' },
  )
}

function isRowSelected(index: number): boolean {
  return queryStore.selectedRows.has(index)
}

function isRowHighlighted(index: number): boolean {
  return queryStore.highlightedRow === index
}

function isContextExpanded(index: number): boolean {
  return expandedContextRows.value.has(index)
}

function toggleContext(index: number) {
  if (expandedContextRows.value.has(index)) {
    expandedContextRows.value.delete(index)
  } else {
    expandedContextRows.value.add(index)
    void fetchRowDetail(index)
  }
  void remeasureVirtualizer()
}

// ── Active row (WAI-ARIA grid) ──────────────────────────────────────
// `aria-activedescendant` on the grid viewport points at the active row's DOM
// id. The active row is the highlighted row when set, else the last selected
// row. Every navigation path funnels through `selectAndRevealRow` so selection,
// highlight, scroll, DOM focus and SR announcement stay a single source of truth.
const activeRowIndex = computed<number | null>(() => {
  if (queryStore.highlightedRow !== null) return queryStore.highlightedRow
  const selected = queryStore.selectedRows
  if (selected.size === 0) return null
  return Math.max(...Array.from(selected))
})

function rowDomId(index: number): string {
  return `kwic-grid-row-${index}`
}

const activeDescendantId = computed(() =>
  activeRowIndex.value !== null ? rowDomId(activeRowIndex.value) : undefined
)

function focusActiveRow(index: number) {
  void nextTick(() => {
    const el = containerRef.value?.querySelector(`[data-row-index="${index}"]`) as HTMLElement | null
    // `scrollIntoView` is absent in some (non-browser) environments; guard it.
    if (el && typeof el.scrollIntoView === 'function') {
      el.scrollIntoView({ block: 'nearest' })
    }
  })
}

function announceRow(index: number) {
  const total = queryStore.results.length
  const row = queryStore.results[index]
  const match = row?.match?.trim() || '—'
  announce(t('kwic.table.announceRow', { n: index + 1, total, match }))
}

/**
 * The one source of truth for keyboard-driven row movement. Selects the row
 * (extending the selection with Shift), marks it as the active/highlighted row,
 * scrolls it into view, and announces it to screen readers.
 */
function selectAndRevealRow(index: number, extend = false) {
  const total = queryStore.results.length
  if (total === 0) return
  const clamped = Math.max(0, Math.min(total - 1, index))
  queryStore.selectRow(clamped, extend)
  queryStore.setHighlightedRow(clamped)
  vimNavigation.setIndex(clamped)
  scrollToRow(clamped)
  focusActiveRow(clamped)
  announceRow(clamped)
}

// Vim-style navigation (j/k/gg/G/Enter/Escape) reuses the same reveal path.
const vimNavigation = useVimNavigation({
  totalItems: () => queryStore.results.length,
  enabled: () => uiStore.activeTab === 'kwic' && queryStore.hasResults,
  onNavigate: (index) => {
    queryStore.setHighlightedRow(index)
    queryStore.selectRow(index, false)
    scrollToRow(index)
    focusActiveRow(index)
    announceRow(index)
  },
  onSelect: (index) => {
    queryStore.selectRow(index, false)
    scrollToRow(index)
  },
  onEscape: () => {
    queryStore.setHighlightedRow(null)
    queryStore.deselectAll()
  }
})

// Keep vim navigation index in sync with external highlight changes
watch(
  () => queryStore.highlightedRow,
  (index) => {
    if (index !== null) {
      vimNavigation.setIndex(index)
    }
  }
)

// How many rows make up one "page" for PageUp/PageDown (visible-row estimate).
function pageStep(): number {
  return Math.max(1, virtualRows.value.length - 1)
}

// Keyboard navigation. Works from an EMPTY selection: Arrow/Home/End/PageUp/
// PageDown all seed a row even when nothing is selected yet (the prior
// behaviour early-returned, making the grid keyboard-unusable).
function handleKeyDown(event: KeyboardEvent) {
  if (queryStore.results.length === 0) return

  // Annotation coding shortcut takes precedence (single-row selection only).
  if (handleAnnotationShortcut(event)) {
    event.preventDefault()
    return
  }

  const hasSelection = queryStore.selectedRows.size > 0
  const current = activeRowIndex.value
  const lastIndex = queryStore.results.length - 1

  switch (event.key) {
    case 'ArrowUp':
      event.preventDefault()
      // From an empty selection ArrowUp seeds the last row; otherwise step up.
      selectAndRevealRow(current === null ? lastIndex : current - 1, event.shiftKey)
      break

    case 'ArrowDown':
      event.preventDefault()
      // From an empty selection ArrowDown seeds row 0; otherwise step down.
      selectAndRevealRow(current === null ? 0 : current + 1, event.shiftKey)
      break

    case 'Home':
      event.preventDefault()
      selectAndRevealRow(0, event.shiftKey)
      break

    case 'End':
      event.preventDefault()
      selectAndRevealRow(lastIndex, event.shiftKey)
      break

    case 'PageDown':
      event.preventDefault()
      selectAndRevealRow(current === null ? 0 : current + pageStep(), event.shiftKey)
      break

    case 'PageUp':
      event.preventDefault()
      selectAndRevealRow(current === null ? lastIndex : current - pageStep(), event.shiftKey)
      break

    case 'Enter':
      event.preventDefault()
      if (current !== null) openDocumentForRow(current)
      break

    case ' ':
      // Space selects the active row (matches the vim Space binding) but only
      // when a row is active, so it never hijacks scrolling on an empty grid.
      if (hasSelection || current !== null) {
        event.preventDefault()
        selectAndRevealRow(current ?? 0, false)
      }
      break

    case 'Escape':
      event.preventDefault()
      queryStore.deselectAll()
      queryStore.setHighlightedRow(null)
      break
  }
}

onMounted(() => {
  containerRef.value?.focus()
  containerRef.value?.addEventListener('scroll', handleBodyScroll, { passive: true })
  scheduleAutoContextRecompute()
})

// Format numbers
function formatPosition(pos: number): string {
  return formatNumber(pos)
}

function cleanLeft(text: string): string {
  if (!text) return ''
  return text.replace(/^(\.\.\.|…)\s*/, '')
}

function cleanRight(text: string): string {
  if (!text) return ''
  return text.replace(/\s*(\.\.\.|…)$/, '')
}

function fitTextToWidthChars(text: string, maxWidth: number, mode: 'left' | 'right'): string {
  if (!text) return ''
  if (maxWidth <= 0) return ''
  ensureMeasureElement(containerRef.value)

  const fullWidth = measureTextWidth(text)
  if (fullWidth <= maxWidth) return text

  let low = 1
  let high = text.length
  let best = ''

  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const candidate = mode === 'left' ? text.slice(text.length - mid) : text.slice(0, mid)
    const width = measureTextWidth(candidate)
    if (width <= maxWidth) {
      best = candidate
      low = mid + 1
    } else {
      high = mid - 1
    }
  }

  return best
}

function fitTextToWidth(text: string, maxWidth: number, mode: 'left' | 'right'): string {
  if (!text) return ''
  if (maxWidth <= 0) return ''
  ensureMeasureElement(containerRef.value)

  const fullWidth = measureTextWidth(text)
  if (fullWidth <= maxWidth) return text

  const spans = tokenSpans(text)
  if (!spans.length) {
    return fitTextToWidthChars(text, maxWidth, mode)
  }

  if (mode === 'left') {
    const last = spans[spans.length - 1]!
    const lastToken = text.slice(last.start, last.end)
    if (measureTextWidth(lastToken) > maxWidth) {
      return fitTextToWidthChars(text, maxWidth, mode)
    }
    let low = 0
    let high = spans.length - 1
    let best = spans.length - 1
    while (low <= high) {
      const mid = Math.floor((low + high) / 2)
      const candidate = text.slice(spans[mid]!.start)
      const width = measureTextWidth(candidate)
      if (width <= maxWidth) {
        best = mid
        high = mid - 1
      } else {
        low = mid + 1
      }
    }
    return text.slice(spans[best]!.start)
  }

  const first = spans[0]!
  const firstToken = text.slice(first.start, first.end)
  if (measureTextWidth(firstToken) > maxWidth) {
    return fitTextToWidthChars(text, maxWidth, mode)
  }
  let low = 0
  let high = spans.length - 1
  let best = 0
  while (low <= high) {
    const mid = Math.floor((low + high) / 2)
    const candidate = text.slice(0, spans[mid]!.end)
    const width = measureTextWidth(candidate)
    if (width <= maxWidth) {
      best = mid
      low = mid + 1
    } else {
      high = mid - 1
    }
  }
  return text.slice(0, spans[best]!.end)
}

function fitLeft(text: string, maxWidth: number): string {
  const cleaned = cleanLeft(text)
  if (!cleaned) return ''
  const width = maxWidth > 0 ? maxWidth : fallbackContextWidth()
  const key = `L|${width}|${quickHash(cleaned)}`
  const cached = textFitCache.get(key)
  if (cached !== undefined) return cached
  const result = fitTextToWidth(cleaned, width, 'left')
  textFitCache.set(key, result)
  if (textFitCache.size > 20000) {
    textFitCache.clear()
  }
  return result
}

function fitRight(text: string, maxWidth: number): string {
  const cleaned = cleanRight(text)
  if (!cleaned) return ''
  const width = maxWidth > 0 ? maxWidth : fallbackContextWidth()
  const key = `R|${width}|${quickHash(cleaned)}`
  const cached = textFitCache.get(key)
  if (cached !== undefined) return cached
  const result = fitTextToWidth(cleaned, width, 'right')
  textFitCache.set(key, result)
  if (textFitCache.size > 20000) {
    textFitCache.clear()
  }
  return result
}
</script>

<template>
  <div class="kwic-table-container" data-onboarding="kwic" data-testid="kwic-table">
    <!-- Header -->
    <div class="table-header" data-testid="kwic-table-header">
    <div class="header-left">
        <span class="text-sm text-neutral-600 dark:text-neutral-400">
          {{ hitsLabel }}
        </span>
        <span 
          v-if="queryStore.selectedCount > 0"
          class="text-sm text-primary-600 dark:text-primary-400"
        >
          · {{ t('kwic.table.selected', { count: queryStore.selectedCount }) }}
        </span>
        <div v-if="coKwicState" class="co-anchors">
          <span class="co-anchors-label">{{ t('kwic.table.coAnchors') }}</span>
          <span class="co-anchors-term" :title="t('kwic.table.coAnchorTerm', { term: coKwicTermLabel })">
            {{ coKwicTermLabel }}
          </span>
          <span class="co-anchors-plus">+</span>
          <button
            v-for="anchor in coKwicCollocates"
            :key="`co-anchor-${anchor}`"
            class="co-anchor-chip"
            type="button"
            :title="t('kwic.table.removeCoAnchor', { anchor })"
            @click="removeCoAnchor(anchor)"
          >
            <span class="co-anchor-text">{{ anchor }}</span>
            <X class="w-3 h-3" />
          </button>
          <span
            v-if="coKwicTokenLabel"
            class="co-anchors-label"
            data-testid="co-kwic-o11"
            :title="coKwicTokenTitle"
          >
            · {{ coKwicTokenLabel }}
          </span>
        </div>
        <span
          v-if="queryStore.sampleProvenance"
          class="sample-chip"
          :title="sampleChipTitle"
          data-testid="kwic-sample-chip"
        >
          {{ sampleChipLabel }}
        </span>
        <span v-if="parallelEnabled" class="parallel-chip" :title="parallelSummary">
          {{ parallelChipLabel }}
        </span>
        <div v-if="isStreaming" class="streaming-pill" :title="t('kwic.table.streamingTitle', { count: streamingProgress?.count ?? 0 }, streamingProgress?.count ?? 0)">
          <span class="streaming-dot" />
          <span>{{ t('kwic.table.streaming') }}</span>
          <span v-if="streamingProgress?.count" class="streaming-count">
            {{ formatNumber(streamingProgress.count) }}
          </span>
          <span v-if="streamingElapsed" class="streaming-elapsed">
            · {{ streamingElapsed }}
          </span>
          <button
            type="button"
            class="streaming-cancel"
            :title="t('kwic.table.cancelSearch')"
            @click="queryStore.cancelStreaming()"
          >
            {{ t('kwic.table.cancel') }}
          </button>
        </div>
      </div>
      
      <div class="header-right">
        <button
          class="header-btn"
          :disabled="!queryStore.hasResults"
          @click="copyVisibleRows"
          :title="t('kwic.table.copyRowsTitle')"
        >
          <ClipboardList class="w-4 h-4" />
          {{ t('kwic.table.copyRows') }}
        </button>
        <button
          class="header-btn"
          :disabled="!queryStore.term || isSavingSubcorpus"
          @click="saveSubcorpusFromHits"
          :title="t('kwic.table.saveSubcorpusTitle')"
        >
          <Layers class="w-4 h-4" />
          {{ t('kwic.table.saveSubcorpus') }}
        </button>
        <button
          class="header-btn"
          type="button"
          :disabled="!annotationsStore.canReadAnnotations"
          :title="annotationsStore.annotationsReadBlockReason ?? t('kwic.table.codesTitle')"
          @click="schemeEditorOpen = true"
        >
          <Tags class="w-4 h-4" />
          {{ t('kwic.table.codes') }}
          <span v-if="annotationsStore.annotatedCount > 0" class="ann-count-badge">
            {{ formatNumber(annotationsStore.annotatedCount) }}
          </span>
        </button>
        <div class="sample-control" data-testid="kwic-sample-control">
          <label
            class="sample-toggle"
            :title="t('kwic.table.sampleToggleTitle')"
          >
            <input
              type="checkbox"
              :checked="queryStore.sampleActive"
              :disabled="isSampling"
              data-testid="kwic-sample-toggle"
              @change="toggleSampleActive"
            />
            <span>{{ t('kwic.table.sampleToggle') }}</span>
          </label>
          <template v-if="queryStore.sampleActive">
            <label class="sample-field">
              <span class="sample-field-label">N</span>
              <input
                v-model.number="sampleSizeModel"
                type="number"
                min="1"
                :max="KWIC_SAMPLE_MAX"
                class="sample-input"
                :aria-label="t('kwic.table.sampleSize')"
                data-testid="kwic-sample-size"
              />
            </label>
            <label
              class="sample-field"
              :title="t('kwic.table.sampleSeedTitle')"
            >
              <span class="sample-field-label">Seed</span>
              <input
                v-model.number="sampleSeedModel"
                type="number"
                min="0"
                class="sample-input sample-input--seed"
                :aria-label="t('kwic.table.sampleSeedAria')"
                data-testid="kwic-sample-seed"
              />
            </label>
            <button
              type="button"
              class="sample-draw"
              :disabled="isSampling || !queryStore.term"
              :title="t('kwic.table.sampleDrawTitle')"
              data-testid="kwic-sample-draw"
              @click="runSampledQuery"
            >
              {{ isSampling ? t('kwic.table.sampleDrawing') : t('kwic.table.sampleDraw') }}
            </button>
          </template>
        </div>
        <div class="context-control" :title="t('kwic.table.contextTitle')">
          <span class="context-label">{{ t('kwic.table.context') }}</span>
          <button
            type="button"
            class="context-auto-toggle"
            :class="{ active: autoContextEnabled }"
            :aria-pressed="autoContextEnabled"
            :title="t('kwic.table.contextAutoTitle')"
            @click="toggleAutoContext"
          >
            {{ t('kwic.table.contextAuto') }}
          </button>
          <template v-if="!autoContextEnabled">
            <input
              type="range"
              class="context-slider"
              :min="CONTEXT_MIN"
              :max="CONTEXT_MAX"
              step="10"
              :value="contextSliderValue"
              :aria-label="t('kwic.table.contextSliderAria')"
              @input="onContextSliderInput(Number(($event.target as HTMLInputElement).value))"
            />
            <span class="context-value">{{ contextSliderValue }}</span>
          </template>
          <span v-else class="context-auto-label">{{ t('kwic.table.contextAutomatic') }}</span>
        </div>
        <button
          v-if="canUseParallelProduct && !canUseParallel"
          class="header-btn parallel-unpaired-hint"
          type="button"
          :title="t('kwic.table.contrastInsteadTitle', { reason: parallelUnavailableReason })"
          @click="goToContrast"
        >
          {{ t('kwic.table.contrastInstead') }}
        </button>
        <!-- One entry to the contrast view. Unpaired corpora get it above as
             the alternative to the parallel concordance. -->
        <button
          v-else-if="showTrefferAktionen"
          class="header-btn"
          type="button"
          @click="goToContrast"
        >
          {{ t('kwic.table.startContrast') }}
        </button>
        <div v-if="canUseParallel" class="parallel-control">
          <label
            class="parallel-toggle"
            :title="t('kwic.table.parallelToggleTitle')"
          >
            <input v-model="parallelEnabled" type="checkbox" />
            <span>{{ t('kwic.table.parallelToggle') }}</span>
          </label>
          <div v-if="parallelEnabled && !isMobile" class="parallel-options">
            <label class="parallel-field">
              <span class="parallel-label">{{ parallelVariantSelectLabel }}</span>
              <select
                v-model="parallelModels"
                class="parallel-select parallel-select--models"
                multiple
                size="4"
                :disabled="docsetStore.isLoadingOptions"
              >
                <option
                  v-for="opt in docsetStore.metaOptions.model"
                  :key="opt"
                  :value="opt"
                >
                  {{ opt }}
                </option>
              </select>
              <span
                v-if="parallelModels.length === 0"
                class="parallel-hint"
                :title="t('kwic.table.pickModelTitle')"
              >
                {{ t('kwic.table.pickModel') }}
              </span>
              <span class="parallel-hint">
                {{ t('kwic.table.pairing', { axes: parallelPairAxesLabel }) }}
              </span>
              <span class="parallel-hint">
                {{ t('kwic.table.pairingByReference') }}
              </span>
              <span class="parallel-hint">
                {{ t('kwic.table.parallelLoadingNote') }}
              </span>
            </label>
            <div class="parallel-field variant-manager" v-if="parallelModels.length > 0">
              <span class="parallel-label">{{ t('kwic.table.variantManager') }}</span>
              <div class="variant-list">
                <div
                  v-for="model in orderedParallelModels"
                  :key="`variant-${model}`"
                  class="variant-item"
                >
                  <span
                    class="variant-name"
                    :class="{ pinned: parallelPinnedModels.includes(model) }"
                  >
                    {{ model }}
                  </span>
                  <div class="variant-actions">
                    <button
                      class="variant-btn"
                      type="button"
                      :disabled="!canMoveParallelModel(model, 'up')"
                      :title="t('kwic.table.moveUp')"
                      @click="moveParallelModel(model, 'up')"
                    >
                      <ArrowUp class="w-3.5 h-3.5" />
                    </button>
                    <button
                      class="variant-btn"
                      type="button"
                      :disabled="!canMoveParallelModel(model, 'down')"
                      :title="t('kwic.table.moveDown')"
                      @click="moveParallelModel(model, 'down')"
                    >
                      <ArrowDown class="w-3.5 h-3.5" />
                    </button>
                    <button
                      class="variant-btn"
                      type="button"
                      :title="parallelPinnedModels.includes(model) ? t('kwic.table.unpin') : t('kwic.table.pin')"
                      @click="togglePinnedModel(model)"
                    >
                      <Pin v-if="!parallelPinnedModels.includes(model)" class="w-3.5 h-3.5" />
                      <PinOff v-else class="w-3.5 h-3.5" />
                    </button>
                    <button
                      class="variant-btn danger"
                      type="button"
                      :title="t('kwic.table.hideVariant')"
                      @click="removeParallelModel(model)"
                    >
                      <X class="w-3.5 h-3.5" />
                    </button>
                  </div>
                </div>
              </div>
            </div>
            <label class="parallel-field">
              <span class="parallel-label">{{ t('kwic.table.variants') }}</span>
              <select v-model.number="parallelMaxVariants" class="parallel-select parallel-select--count">
                <option v-for="n in PARALLEL_MAX_VARIANTS" :key="`pv-${n}`" :value="n">
                  {{ n }}
                </option>
              </select>
            </label>
            <label class="parallel-field">
              <span class="parallel-label">{{ t('kwic.table.sentenceWindow') }}</span>
              <select v-model.number="parallelSentenceMargin" class="parallel-select parallel-select--count">
                <option v-for="n in 12" :key="`pm-${n}`" :value="n">
                  ±{{ n }}
                </option>
              </select>
            </label>
            <div class="parallel-field parallel-presets">
              <span class="parallel-label">{{ t('kwic.table.presets') }}</span>
              <div class="preset-row">
                <select v-model="presetSelectValue" class="parallel-select parallel-select--presets">
                  <option value="custom">{{ t('kwic.table.noPreset') }}</option>
                  <option v-for="preset in sortedPresets" :key="preset.id" :value="preset.id">
                    {{ preset.name }}
                  </option>
                </select>
                <span v-if="activePreset" class="preset-badge">{{ t('kwic.table.presetActive') }}</span>
                <button class="preset-btn" type="button" @click="openPresetModal">
                  <Save class="w-3.5 h-3.5" />
                  {{ t('kwic.table.save') }}
                </button>
                <button
                  v-if="activePreset"
                  class="preset-btn"
                  type="button"
                  :title="activePreset.favorite ? t('kwic.table.unfavorite') : t('kwic.table.favorite')"
                  @click="togglePresetFavorite"
                >
                  <Star class="w-3.5 h-3.5" />
                </button>
                <button
                  v-if="activePreset"
                  class="preset-btn danger"
                  type="button"
                  :title="t('kwic.table.deletePreset')"
                  @click="removePreset"
                >
                  <Trash2 class="w-3.5 h-3.5" />
                </button>
                <button
                  class="preset-btn"
                  type="button"
                  :title="t('kwic.table.resetParallel')"
                  @click="resetParallelConfig"
                >
                  <RotateCcw class="w-3.5 h-3.5" />
                </button>
              </div>
              <div v-if="favoritePresets.length" class="preset-favorites">
                <button
                  v-for="preset in favoritePresets"
                  :key="`fav-${preset.id}`"
                  class="preset-chip"
                  type="button"
                  @click="applyParallelPreset(preset)"
                >
                  ★ {{ preset.name }}
                </button>
              </div>
            </div>
          </div>
        </div>
        <div v-if="showRefDocControl" class="refdoc-control">
          <span class="refdoc-label">ref_doc</span>
          <span v-if="refDocOptions.length > 0" class="refdoc-count">
            {{ t('kwic.table.refDocCount', { count: refDocOptions.length }, refDocOptions.length) }}
          </span>
          <span v-if="isLoadingRefDocs" class="refdoc-loading">
            <Loader2 class="w-3.5 h-3.5 animate-spin" />
            {{ t('kwic.table.loading') }}
          </span>
          <select
            v-model="refDocOverrideValue"
            class="refdoc-select"
            :disabled="isLoadingRefDocs || refDocOptions.length === 0 || !canLoadParallelGroups"
            :title="refDocOverride !== null ? t('kwic.table.override', { ref: refDocOverride }) : t('kwic.table.contextAutomatic')"
          >
            <option value="auto">{{ t('kwic.table.contextAuto') }}</option>
            <option v-for="ref in refDocOptions" :key="`refdoc-${ref}`" :value="String(ref)">
              #{{ ref }}
            </option>
          </select>
          <button
            class="refdoc-refresh"
            type="button"
            :title="!canLoadParallelGroups ? parallelGroupsBlockReason ?? t('kwic.table.parallelGroupsNotEnabled') : t('kwic.table.refreshRefs')"
            :disabled="isLoadingRefDocs || !canLoadParallelGroups"
            @click="loadRefDocOptions"
          >
            <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isLoadingRefDocs }" />
          </button>
          <button
            v-if="refDocOverride !== null"
            type="button"
            class="refdoc-clear"
            :title="t('kwic.table.resetOverride')"
            @click="refDocOverride = null"
          >
            {{ t('kwic.table.reset') }}
          </button>
          <span v-if="refDocOverride !== null" class="refdoc-badge">
            {{ t('kwic.table.override', { ref: refDocOverride }) }}
          </span>
          <span v-else-if="refDocOptions.length === 0" class="refdoc-hint">
            {{ parallelGroupsBlockReason ?? t('kwic.table.noRefs') }}
          </span>
          <span v-if="refDocError" class="refdoc-error">
            {{ refDocError }}
          </span>
        </div>
        <button
          v-if="queryStore.selectedCount > 0"
          class="header-btn"
          @click="queryStore.deselectAll()"
        >
          {{ t('kwic.table.clearSelection') }}
        </button>
      </div>
    </div>

    <!-- Analysis row this concordance was opened from -->
    <BackPathChip />

    <!-- Annotation category filter + frequency counts (F7) -->
    <div
      v-if="annotationsStore.categories.length || annotationsStore.annotatedCount"
      class="annotation-bar"
      role="group"
      :aria-label="t('kwic.table.filterByCode')"
    >
      <Filter class="w-3.5 h-3.5 text-neutral-400" />
      <button
        type="button"
        class="ann-filter-chip"
        :class="{ active: annotationsStore.filterEnabled && annotationsStore.filterCategoryId === null }"
        :title="t('kwic.table.onlyAnnotatedTitle')"
        @click="toggleCategoryFilter(null)"
      >
        {{ t('kwic.table.annotated') }}
        <span class="ann-filter-count">{{ annotationsStore.annotatedCount }}</span>
      </button>
      <button
        v-for="cat in annotationsStore.categories"
        :key="`filter-${cat.id}`"
        type="button"
        class="ann-filter-chip"
        :class="{ active: annotationsStore.filterEnabled && annotationsStore.filterCategoryId === cat.id }"
        :style="{ borderColor: cat.color || '#6366f1' }"
        :title="t('kwic.table.filterByCodeNamed', { label: cat.label })"
        @click="toggleCategoryFilter(cat.id)"
      >
        <span class="ann-filter-dot" :style="{ backgroundColor: cat.color || '#6366f1' }" />
        {{ cat.label }}
        <span class="ann-filter-count">{{ annotationsStore.categoryCounts.byCategory[cat.id] ?? 0 }}</span>
      </button>
      <button
        v-if="annotationsStore.filterEnabled"
        type="button"
        class="ann-filter-clear"
        @click="annotationsStore.clearFilter(); remeasureVirtualizer()"
      >
        {{ t('kwic.table.resetFilter') }}
        <span class="ann-filter-shown">{{ t('kwic.table.visibleParen', { count: categoryFilterCount }) }}</span>
      </button>
    </div>

    <!-- Filter loaded rows (DT-FE-UX-CORE): client-side text/regex filter -->
    <div v-if="queryStore.hasResults" class="row-filter-bar" role="search">
      <Filter class="w-3.5 h-3.5 text-neutral-400" />
      <input
        v-model="rowFilterText"
        type="text"
        class="row-filter-input"
        :placeholder="t('kwic.table.rowFilterPlaceholder')"
        :aria-label="t('kwic.table.rowFilterAria')"
        spellcheck="false"
      />
      <span v-if="rowFilterRegexError" class="row-filter-error" :title="rowFilterRegexError">
        {{ t('kwic.table.regexFallback') }}
      </span>
      <span v-if="isRowFilterActive" class="row-filter-count">
        {{ t('kwic.table.visible', { count: formatNumber(categoryFilterCount) }) }}
      </span>
      <button
        v-if="isRowFilterActive"
        type="button"
        class="row-filter-clear"
        :title="t('kwic.table.resetFilter')"
        @click="clearRowFilter"
      >
        <X class="w-3.5 h-3.5" />
      </button>
    </div>

    <!-- KWIC sort controls (AntConc convention: 1L = token left of match) -->
    <div class="sort-bar" role="group" :aria-label="t('kwic.table.sortAria')">
      <div class="sort-group">
        <span class="sort-group-label">{{ t('kwic.table.sortLeft') }}</span>
        <button
          v-for="field in LEFT_SORT_FIELDS"
          :key="`sort-${field}`"
          type="button"
          class="sort-btn"
          :class="{ 'sort-btn--active': isSortActive(field) }"
          :aria-pressed="isSortActive(field)"
          :title="t('kwic.table.sortByToken', { field })"
          @click="applySort(field)"
        >
          {{ field }}
          <span v-if="isSortActive(field)" class="sort-indicator">{{ sortDirIndicator(field) }}</span>
        </button>
      </div>

      <div class="sort-group">
        <span class="sort-group-label">{{ t('kwic.table.sortNode') }}</span>
        <button
          type="button"
          class="sort-btn"
          :class="{ 'sort-btn--active': isSortActive('node') }"
          :aria-pressed="isSortActive('node')"
          :title="t('kwic.table.sortNodeTitle')"
          @click="applySort('node')"
        >
          node
          <span v-if="isSortActive('node')" class="sort-indicator">{{ sortDirIndicator('node') }}</span>
        </button>
      </div>

      <div class="sort-group">
        <span class="sort-group-label">{{ t('kwic.table.sortRight') }}</span>
        <button
          v-for="field in RIGHT_SORT_FIELDS"
          :key="`sort-${field}`"
          type="button"
          class="sort-btn"
          :class="{ 'sort-btn--active': isSortActive(field) }"
          :aria-pressed="isSortActive(field)"
          :title="t('kwic.table.sortByToken', { field })"
          @click="applySort(field)"
        >
          {{ field }}
          <span v-if="isSortActive(field)" class="sort-indicator">{{ sortDirIndicator(field) }}</span>
        </button>
      </div>

      <button
        type="button"
        class="sort-btn sort-btn--reset"
        :disabled="!hasCustomSort"
        :title="t('kwic.table.sortResetTitle')"
        @click="resetSort"
      >
        {{ t('kwic.table.sortDefault') }}
      </button>

      <span v-if="hasCustomSort" class="sort-status" aria-live="polite">
        {{ t('kwic.table.sortedBy', { field: activeSortField, direction: activeSortDir === 'asc' ? t('kwic.table.ascending') : t('kwic.table.descending') }) }}
      </span>
    </div>

    <!-- Rate-limit (429): non-destructive notice that preserves the loaded
         table instead of the blocking error banner. -->
    <div
      v-if="showRateLimitNotice"
      class="kwic-ratelimit"
      role="status"
      aria-live="polite"
    >
      <span class="kwic-ratelimit-text">{{ errorMessage }}</span>
      <button class="kwic-error-btn" type="button" @click="retryQuery">
        {{ t('kwic.table.retry') }}
      </button>
      <button
        class="kwic-error-btn kwic-error-btn-secondary"
        type="button"
        @click="queryStore.setError(null)"
      >
        {{ t('kwic.table.close') }}
      </button>
    </div>

    <div v-else-if="showErrorBanner" class="kwic-error">
      <span class="kwic-error-text">{{ errorMessage }}</span>
      <button class="kwic-error-btn" type="button" @click="retryQuery">
        {{ t('kwic.table.retry') }}
      </button>
      <button
        class="kwic-error-btn kwic-error-btn-secondary"
        type="button"
        @click="queryStore.setError(null)"
      >
        {{ t('kwic.table.close') }}
      </button>
    </div>

    <div v-if="parallelEnabled" class="cowic-banner">
      <div class="cowic-info">
        <span class="cowic-title">{{ t('kwic.table.parallelActive') }}</span>
        <span class="cowic-summary">{{ parallelSummary }}</span>
        <span v-if="parallelAutoVariantNote" class="cowic-auto-note">{{ parallelAutoVariantNote }}</span>
        <span v-if="refDocOverride !== null" class="cowic-badge">{{ t('kwic.table.refDocOverride') }}</span>
      </div>
      <div class="cowic-actions">
        <button class="header-btn" type="button" @click="disableParallel">
          {{ t('kwic.table.endParallel') }}
        </button>
      </div>
    </div>

    <div v-if="!isMobile && queryStore.hasResults" class="column-header">
      <div ref="headerScrollRef" class="column-header-scroll" @scroll="handleHeaderScroll">
        <div class="column-header-grid" :style="{ ...rowDesktopStyle, minWidth: `${kwicMinWidth}px` }">
          <div class="col-head col-head--pos">#</div>
          <button
            type="button"
            class="col-head col-head--sortable"
            :class="{ 'col-head--active': isSortActive('1L') }"
            :aria-pressed="isSortActive('1L')"
            :title="t('kwic.table.sortLeftContext')"
            @click="applySort('1L')"
          >
            {{ t('kwic.table.leftContext') }}
            <span v-if="isSortActive('1L')" class="col-head-indicator">{{ sortDirIndicator('1L') }}</span>
          </button>
          <button
            type="button"
            class="col-head col-head--match col-head--sortable"
            :class="{ 'col-head--active': isSortActive('node') }"
            :aria-pressed="isSortActive('node')"
            :title="t('kwic.table.sortNodeTitle')"
            @click="applySort('node')"
          >
            {{ t('kwic.table.matchColumn') }}
            <span v-if="isSortActive('node')" class="col-head-indicator">{{ sortDirIndicator('node') }}</span>
          </button>
          <button
            type="button"
            class="col-head col-head--sortable"
            :class="{ 'col-head--active': isSortActive('1R') }"
            :aria-pressed="isSortActive('1R')"
            :title="t('kwic.table.sortRightContext')"
            @click="applySort('1R')"
          >
            {{ t('kwic.table.rightContext') }}
            <span v-if="isSortActive('1R')" class="col-head-indicator">{{ sortDirIndicator('1R') }}</span>
          </button>
          <div
            v-for="(label, idx) in parallelHeaderLabels"
            :key="`col-${label}-${idx}`"
            class="col-head col-head--variant"
          >
            {{ label }}
          </div>
          <div class="col-head col-head--actions">{{ t('kwic.table.actionColumn') }}</div>
        </div>
      </div>
    </div>

    <!-- Table (WAI-ARIA grid pattern: role=grid + roving aria-activedescendant) -->
    <div
      ref="containerRef"
      class="table-viewport"
      tabindex="0"
      role="grid"
      :aria-label="t('kwic.table.gridAria')"
      aria-multiselectable="true"
      :aria-rowcount="queryStore.results.length"
      :aria-activedescendant="activeDescendantId"
      @keydown="handleKeyDown"
    >
      <!-- sr-only header row so screen readers announce the grid columns -->
      <div class="sr-only" role="row" aria-rowindex="0">
        <span role="columnheader">{{ t('kwic.table.position') }}</span>
        <span role="columnheader">{{ t('kwic.table.leftContext') }}</span>
        <span role="columnheader">{{ t('kwic.table.sortNode') }}</span>
        <span role="columnheader">{{ t('kwic.table.rightContext') }}</span>
        <span role="columnheader">{{ t('kwic.table.actions') }}</span>
      </div>
      <div
        class="table-content"
        :style="{ height: `${totalSize}px`, minWidth: `${kwicMinWidth}px` }"
      >
        <div
          v-for="virtualRow in virtualRows"
          :key="String(virtualRow.key)"
          :id="rowDomId(virtualRow.index)"
          class="table-row"
          role="row"
          :aria-rowindex="virtualRow.index + 1"
          :aria-selected="isRowSelected(virtualRow.index)"
          :class="{
            'is-selected': isRowSelected(virtualRow.index),
            'is-highlighted': isRowHighlighted(virtualRow.index),
            'is-expanded': isContextExpanded(virtualRow.index),
            'is-active': activeRowIndex === virtualRow.index,
            'is-filtered-out': !isRowVisibleByFilter(virtualRow.index)
          }"
          :ref="measureRow"
          :data-index="virtualRow.index"
          :data-row-index="virtualRow.index"
          :data-testid="`kwic-row-${virtualRow.index}`"
          :style="{
            position: 'absolute',
            top: 0,
            left: 0,
            width: '100%',
            transform: `translateY(${virtualRow.start}px)`
          }"
          @click="handleRowClick(virtualRow.index, $event)"
        >
          <!-- Desktop: 3-Column Layout -->
          <div v-if="!isMobile && isRowVisibleByFilter(virtualRow.index)" class="row-desktop" :style="rowDesktopStyle">
            <!-- Position -->
            <div class="row-position" role="gridcell">
              {{ formatPosition(queryStore.results[virtualRow.index]!.position) }}
            </div>

            <!-- Left Context -->
            <div class="row-left" role="gridcell" data-testid="kwic-row-left">
              <span class="shrink-0">
                <span
                  v-if="isContextTruncated(virtualRow.index, 'left', contextLeftWidth)"
                  class="kwic-truncation"
                  :title="t('kwic.table.truncated')"
                  aria-hidden="true"
                >…</span>
                <template
                  v-for="(segment, segIdx) in contextSegmentsForRow(virtualRow.index, 'left', contextLeftWidth)"
                  :key="`left-${virtualRow.index}-${segIdx}`"
                >
                  <span
                    :class="
                      segment.highlight === 'match'
                        ? 'kwic-match'
                        : segment.highlight === 'collocate'
                          ? 'kwic-collocate'
                          : undefined
                    "
                  >
                    {{ segment.text }}
                  </span>
                </template>
              </span>
            </div>

            <!-- Match (highlighted) -->
            <div
              class="row-match kwic-match"
              role="gridcell"
              data-testid="kwic-row-match"
              :title="displayRow(virtualRow.index).match"
            >
              {{ displayRow(virtualRow.index).match }}
            </div>

            <!-- Right Context -->
            <div class="row-right" role="gridcell" data-testid="kwic-row-right">
              <template
                v-for="(segment, segIdx) in contextSegmentsForRow(virtualRow.index, 'right', contextRightWidth)"
                :key="`right-${virtualRow.index}-${segIdx}`"
              >
                <span
                  :class="
                    segment.highlight === 'match'
                      ? 'kwic-match'
                      : segment.highlight === 'collocate'
                        ? 'kwic-collocate'
                        : undefined
                  "
                >
                  {{ segment.text }}
                </span>
              </template>
              <span
                v-if="isContextTruncated(virtualRow.index, 'right', contextRightWidth)"
                class="kwic-truncation"
                :title="t('kwic.table.truncated')"
                aria-hidden="true"
              >…</span>
            </div>

            <div
              v-if="parallelEnabled"
              v-for="(variant, vIdx) in parallelColumnsForRow(virtualRow.index)"
              :key="`parallel-${virtualRow.index}-${vIdx}`"
              class="row-variant"
              :class="{
                'variant-missing': !variant,
                'variant-unmatched': variant && !variant.matched
              }"
            >
              <div class="variant-meta">
                <div class="variant-badges">
                  <span class="variant-badge variant-badge--model">{{ parallelVariantLabel(variant, vIdx) }}</span>
                  <span v-if="variant?.prompting_method" class="variant-badge variant-badge--prompt">
                    {{ variant.prompting_method }}
                  </span>
                </div>
                <span v-if="variant?.similarity !== null && variant?.similarity !== undefined" class="variant-score">
                  {{ t('kwic.table.similarity', { value: formatFloat(variant.similarity * 100, 0) }) }}
                </span>
              </div>
              <!-- The counterpart is a sentence of its own: it wraps (up to three
                   lines) instead of being cut to the width of a narrow column. -->
              <div class="variant-context" :title="variantSentence(variant)">
                <span class="variant-left">{{ variant?.left ?? '' }}</span>
                <span class="kwic-match" :class="{ 'kwic-unmatched': variant && !variant.matched }">
                  {{ variant?.kw || parallelCellPlaceholder(virtualRow.index) }}
                </span>
                <span class="variant-right">{{ variant?.right ?? '' }}</span>
              </div>
              <div v-if="variant?.med !== null && variant?.med !== undefined" class="variant-metrics">
                MED {{ variant.med }}
              </div>
            </div>

            <!-- Annotation badge (category + note marker) -->
            <div
              v-if="isRowAnnotated(virtualRow.index)"
              class="row-annotation-badge"
            >
              <span
                v-if="rowCategory(virtualRow.index)"
                class="ann-cat-chip"
                :style="{ backgroundColor: rowCategory(virtualRow.index)?.color || '#6366f1' }"
                :title="t('kwic.table.codeTitle', { label: rowCategory(virtualRow.index)?.label ?? '' })"
              >
                {{ rowCategory(virtualRow.index)?.label }}
              </span>
              <StickyNote
                v-if="getRowAnnotation(virtualRow.index)?.note"
                class="ann-note-icon"
                :class="{ 'no-cat': !rowCategory(virtualRow.index) }"
                :title="getRowAnnotation(virtualRow.index)?.note || ''"
              />
            </div>

            <!-- Actions -->
            <div class="row-actions" role="gridcell">
              <button
                class="action-btn"
                :aria-label="t('kwic.table.openDocumentNamed', { doc: getRowDocLabel(virtualRow.index) })"
                :title="t('kwic.table.openDocument')"
                @click.stop="openDocumentForRow(virtualRow.index)"
              >
                <FileText class="w-4 h-4" />
              </button>
              <button
                class="action-btn ann-btn"
                :class="{ active: isRowAnnotated(virtualRow.index) }"
                :disabled="!annotationsStore.canWriteAnnotations"
                :aria-label="t('kwic.table.annotateAria')"
                :title="annotationsStore.annotationsWriteBlockReason ?? t('kwic.table.annotateTitle')"
                @click.stop="openAnnotationPopover(virtualRow.index)"
              >
                <Tag class="w-4 h-4" />
              </button>
              <button
                class="action-btn"
                :title="t('kwic.table.copyLineTitle')"
                @click.stop="copyRowLine(virtualRow.index)"
              >
                <Copy class="w-4 h-4" />
              </button>
              <button
                class="action-btn"
                :title="t('kwic.table.copyCitedTitle')"
                @click.stop="copyRowWithCitation(virtualRow.index)"
              >
                <ClipboardList class="w-4 h-4" />
              </button>
              <button
                class="action-btn"
                :title="isContextExpanded(virtualRow.index) ? t('kwic.table.collapseContext') : t('kwic.table.expandContext')"
                @click.stop="toggleContext(virtualRow.index)"
              >
                <Maximize2 class="w-4 h-4" />
              </button>
            </div>
          </div>

          <!-- Mobile: Stacked Layout -->
          <div v-else-if="isMobile && isRowVisibleByFilter(virtualRow.index)" class="row-mobile">
            <div class="match-line">
              <span class="kwic-match">{{ displayRow(virtualRow.index).match }}</span>
              <span class="position">{{ formatPosition(queryStore.results[virtualRow.index]!.position) }}</span>
            </div>
            <div class="context-line">
              <span class="context-text">...{{ displayRow(virtualRow.index).left }}</span>
              <span class="context-separator"> | </span>
              <span class="context-text">{{ displayRow(virtualRow.index).right }}...</span>
            </div>
          </div>

          <!-- Expanded Context -->
          <div
            v-if="isContextExpanded(virtualRow.index) && isRowVisibleByFilter(virtualRow.index)"
            class="expanded-context"
          >
            <div class="context-metadata">
              <div class="metadata-head">
                <span class="doc-label">
                  {{ getRowDocLabel(virtualRow.index) }}
                </span>
                <div v-if="getMetaChips(virtualRow.index).length > 0" class="meta-chips">
                  <span
                    v-for="chip in getMetaChips(virtualRow.index)"
                    :key="`${chip.key}:${chip.value}`"
                    class="meta-chip"
                    :title="`${chip.key}=${chip.value}`"
                  >
                    {{ chip.key }}: {{ chip.label }}
                  </span>
                </div>
              </div>
              <div v-if="getMetaSummary(virtualRow.index)" class="meta-summary">
                {{ getMetaSummary(virtualRow.index) }}
              </div>
            </div>

            <div v-if="getRowDetailState(virtualRow.index)?.loading" class="detail-loading">
              {{ t('kwic.table.loadingContext') }}
            </div>
            <div v-else-if="getRowDetailState(virtualRow.index)?.error" class="detail-error">
              <span>{{ getRowDetailState(virtualRow.index)?.error }}</span>
              <button
                class="detail-retry"
                type="button"
                @click.stop="fetchRowDetail(virtualRow.index)"
              >
                {{ t('kwic.table.reload') }}
              </button>
            </div>
            <div v-else class="context-text">
              <ChevronLeft class="w-4 h-4 text-neutral-400" />
              <span class="text-neutral-600 dark:text-neutral-400">
                <template
                  v-for="(segment, segIdx) in contextSegmentsForRow(virtualRow.index, 'left', undefined, getRowParts(virtualRow.index).left)"
                  :key="`detail-left-${virtualRow.index}-${segIdx}`"
                >
                  <span
                    :class="
                      segment.highlight === 'match'
                        ? 'kwic-match'
                        : segment.highlight === 'collocate'
                          ? 'kwic-collocate'
                          : undefined
                    "
                  >
                    {{ segment.text }}
                  </span>
                </template>
              </span>
              <span class="kwic-match mx-1">
                {{ getRowParts(virtualRow.index).match }}
              </span>
              <span class="text-neutral-600 dark:text-neutral-400">
                <template
                  v-for="(segment, segIdx) in contextSegmentsForRow(virtualRow.index, 'right', undefined, getRowParts(virtualRow.index).right)"
                  :key="`detail-right-${virtualRow.index}-${segIdx}`"
                >
                  <span
                    :class="
                      segment.highlight === 'match'
                        ? 'kwic-match'
                        : segment.highlight === 'collocate'
                          ? 'kwic-collocate'
                          : undefined
                    "
                  >
                    {{ segment.text }}
                  </span>
                </template>
              </span>
              <ChevronRight class="w-4 h-4 text-neutral-400" />
            </div>

            <div v-if="canOpenAlignment && getRowRefDoc(virtualRow.index) !== null" class="alignment-panel">
              <div class="alignment-head">
                <div class="alignment-title">
                  {{ t('kwic.table.compareVariants') }}
                  <span v-if="refDocOverride !== null" class="alignment-override">{{ t('kwic.table.manualReference') }}</span>
                </div>
                <button
                  class="alignment-btn"
                  type="button"
                  @click.stop="fetchAlignment(virtualRow.index, { force: true })"
                >
                  {{ t('kwic.table.refresh') }}
                </button>
              </div>

              <div v-if="getAlignmentState(virtualRow.index)?.loading" class="alignment-loading">
                {{ t('kwic.table.loadingVariants') }}
              </div>
              <div v-else-if="getAlignmentState(virtualRow.index)?.error" class="alignment-error">
                <span>{{ getAlignmentState(virtualRow.index)?.error }}</span>
                <button class="alignment-retry" type="button" @click.stop="fetchAlignment(virtualRow.index)">
                  {{ t('kwic.table.loadAgain') }}
                </button>
              </div>
              <div v-else-if="getAlignmentState(virtualRow.index)?.result" class="alignment-body">
                <div class="alignment-summary">
                  {{ t('kwic.table.alignReferenceSentences', { count: getAlignmentState(virtualRow.index)?.result?.reference.sentence_count ?? 0 }) }}
                  · {{ t('kwic.table.alignWindow') }}
                  {{ getAlignmentState(virtualRow.index)?.result?.reference.window_start }}
                  –
                  {{ getAlignmentState(virtualRow.index)?.result?.reference.window_end }}
                  · {{ t('kwic.table.alignVariants', { count: getAlignmentState(virtualRow.index)?.result?.variant_count ?? 0 }) }}
                  · {{ t('kwic.table.alignShown', { count: alignmentVisibleSentenceCount(virtualRow.index) }) }}
                  · {{ t('kwic.table.alignAutoWindow', { count: autoAlignWindowSentences }) }}
                </div>
                <AlignmentComparison
                  :result="getAlignmentState(virtualRow.index)?.result!"
                  :max-rows="autoAlignSlice"
                />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  <!-- div moved -->

  <Modal
    v-model="nameModalOpen"
    :title="t('kwic.table.nameSubcorpusTitle')"
    :description="t('kwic.table.nameSubcorpusDescription')"
  >
    <div class="name-modal">
      <label class="name-label" :for="subcorpusNameId">{{ t('kwic.table.name') }}</label>
      <input :id="subcorpusNameId" v-model="nameDraft" class="name-input" type="text" />
      <div class="name-actions">
        <button class="header-btn" type="button" @click="nameModalOpen = false">
          {{ t('kwic.table.cancel') }}
        </button>
        <button class="header-btn" type="button" @click="confirmSaveSubcorpus">
          {{ t('kwic.table.save') }}
        </button>
      </div>
    </div>
  </Modal>

  <Modal
    v-model="presetModalOpen"
    :title="t('kwic.table.savePresetTitle')"
    :description="t('kwic.table.savePresetDescription')"
  >
    <div class="name-modal">
      <label class="name-label" :for="presetNameId">{{ t('kwic.table.name') }}</label>
      <input :id="presetNameId" v-model="presetNameDraft" class="name-input" type="text" />
      <label class="preset-favorite">
        <input v-model="presetFavorite" type="checkbox" />
        <span>{{ t('kwic.table.saveAsFavorite') }}</span>
      </label>
      <div class="name-actions">
        <button class="header-btn" type="button" @click="presetModalOpen = false">
          {{ t('kwic.table.cancel') }}
        </button>
        <button class="header-btn" type="button" @click="savePreset">
          {{ t('kwic.table.save') }}
        </button>
      </div>
    </div>
  </Modal>

  <!-- Per-row annotation editor (F7): one explicit save keeps code and note together. -->
  <Modal
    :model-value="annotationPopoverIndex !== null"
    @update:model-value="(open) => { if (!open) closeAnnotationPopover() }"
    :title="t('kwic.table.annotateModalTitle')"
    :description="t('kwic.table.annotateModalDescription')"
    size="md"
  >
    <div v-if="annotationPopoverIndex !== null" class="annotation-editor">
      <div v-if="annotationPreviewLine" class="ann-row-preview">
        <span class="ann-preview-left">{{ annotationPreviewLine.leftCut ? '…' : '' }}{{ annotationPreviewLine.left }}</span>
        <span class="kwic-match ann-preview-match">{{ annotationPreviewLine.match }}</span>
        <span class="ann-preview-right">{{ annotationPreviewLine.right }}{{ annotationPreviewLine.rightCut ? '…' : '' }}</span>
      </div>

      <div class="ann-field">
        <label class="ann-label">{{ t('kwic.table.code') }}</label>
        <div v-if="annotationsStore.categories.length" class="ann-category-grid">
          <button
            type="button"
            class="ann-category-btn"
            :class="{ active: !categoryDraftId }"
            @click="categoryDraftId = null"
            :disabled="!annotationsStore.canWriteAnnotations || annotationSaving"
          >
            {{ t('kwic.table.noCode') }}
          </button>
          <button
            v-for="cat in annotationsStore.categories"
            :key="cat.id"
            type="button"
            class="ann-category-btn"
            :class="{ active: categoryDraftId === cat.id }"
            :style="categoryDraftId === cat.id
              ? { backgroundColor: cat.color || '#6366f1', borderColor: cat.color || '#6366f1', color: '#fff' }
              : { borderColor: cat.color || '#6366f1' }"
            @click="categoryDraftId = cat.id"
            :disabled="!annotationsStore.canWriteAnnotations || annotationSaving"
          >
            {{ cat.label }}
            <span v-if="cat.shortcut" class="ann-cat-key">{{ cat.shortcut }}</span>
          </button>
        </div>
        <p v-else class="ann-empty-scheme">
          {{ t('kwic.table.noCodesYet') }}
          <button type="button" class="ann-link" @click="schemeEditorOpen = true">{{ t('kwic.table.createCodes') }}</button>
        </p>
      </div>

      <div class="ann-field">
        <label class="ann-label" for="ann-note">{{ t('kwic.table.note') }}</label>
        <textarea
          id="ann-note"
          v-model="noteDraft"
          class="ann-note-input"
          rows="3"
          :placeholder="t('kwic.table.notePlaceholder')"
          :disabled="annotationSaving"
        />
      </div>
    </div>

    <template #footer>
      <button
        v-if="annotationPopoverIndex !== null && isRowAnnotated(annotationPopoverIndex)"
        class="ann-footer-delete"
        type="button"
        @click="clearRowAnnotation(annotationPopoverIndex)"
        :disabled="!annotationsStore.canDeleteAnnotations || annotationSaving"
      >
        <Trash2 class="w-4 h-4" />
        {{ t('kwic.table.removeAnnotation') }}
      </button>
      <div class="ann-footer-spacer" />
      <button class="ann-footer-cancel" type="button" @click="closeAnnotationPopover" :disabled="annotationSaving">{{ t('kwic.table.close') }}</button>
      <button
        v-if="annotationPopoverIndex !== null"
        class="ann-footer-save"
        type="button"
        @click="saveAnnotationAndClose(annotationPopoverIndex)"
        :disabled="!annotationsStore.canWriteAnnotations || annotationSaving"
      >
        {{ t('kwic.table.saveCodeNote') }}
      </button>
    </template>
  </Modal>

  <AnnotationSchemeEditor v-model="schemeEditorOpen" />
  </div>
</template>

<style scoped>
@reference "../../style.css";

.kwic-table-container {
  /* Fills the tab and grows with its controls. The tab area scrolls when the
     controls and the minimum height of the lines exceed it (App.vue). */
  @apply flex flex-col bg-white dark:bg-neutral-900;
  flex: 1 0 auto;
  overflow-x: clip;
}

.table-header {
  @apply flex items-center justify-between px-3 md:px-4 py-2 md:py-3;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply flex-wrap gap-2;
}

.header-left {
  @apply flex items-center gap-2;
}

.header-right {
  @apply flex items-center gap-2 flex-wrap justify-end;
}

.context-control {
  @apply flex items-center gap-2 px-2.5 py-1.5 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-xs md:text-sm text-neutral-700 dark:text-neutral-200;
}

.context-label {
  @apply font-medium;
}

.context-auto-label {
  @apply text-xs md:text-sm text-neutral-600 dark:text-neutral-300;
}

.context-auto-toggle {
  @apply px-2 py-0.5 rounded text-xs font-medium;
  @apply border border-neutral-300 dark:border-neutral-600;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply transition-colors;
}

.context-auto-toggle.active {
  @apply bg-primary-100 text-primary-700 border-primary-300;
  @apply dark:bg-primary-900/40 dark:text-primary-300 dark:border-primary-700;
}

.context-controls {
  @apply flex items-center gap-2;
}

.context-auto {
  @apply inline-flex items-center gap-1 text-xs;
  @apply text-neutral-600 dark:text-neutral-300;
}

.context-slider {
  width: 120px;
  @apply accent-primary-600;
}

.context-value {
  @apply font-mono text-xs md:text-sm text-neutral-600 dark:text-neutral-300;
  min-width: 2.25rem;
  text-align: right;
}

.parallel-control {
  @apply flex items-center gap-2 px-2.5 py-1.5 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-xs md:text-sm text-neutral-700 dark:text-neutral-200;
}

.parallel-toggle {
  @apply flex items-center gap-2 font-medium;
}

.parallel-options {
  @apply flex items-start gap-3 flex-wrap;
}

.parallel-field {
  @apply flex flex-col gap-1;
}

.parallel-label {
  @apply text-[11px] font-medium text-neutral-500 dark:text-neutral-400;
}

.parallel-select {
  @apply px-2 py-1 rounded-md text-xs md:text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.parallel-select--models {
  min-width: 180px;
  min-height: 96px;
}

.parallel-select--count {
  min-width: 72px;
}

.parallel-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.parallel-presets {
  min-width: 220px;
}

.variant-manager {
  min-width: 200px;
}

.variant-list {
  @apply flex flex-col gap-1;
}

.variant-item {
  @apply flex items-center justify-between gap-2;
  @apply px-2 py-1 rounded-md;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.variant-name {
  @apply text-[11px] text-neutral-700 dark:text-neutral-200 truncate;
  max-width: 140px;
}

.variant-name.pinned {
  @apply text-primary-700 dark:text-primary-300;
}

.variant-actions {
  @apply flex items-center gap-1;
}

.variant-btn {
  @apply p-1 rounded-md text-neutral-500 dark:text-neutral-400;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply disabled:opacity-40 disabled:cursor-not-allowed;
}

.variant-btn.danger {
  @apply text-error-600 dark:text-error-400;
}

.preset-row {
  @apply flex items-center gap-2 flex-wrap;
}

.preset-badge {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.parallel-select--presets {
  min-width: 180px;
}

.preset-btn {
  @apply inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px];
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.preset-btn.danger {
  @apply text-error-600 dark:text-error-400;
}

.preset-favorites {
  @apply flex flex-wrap items-center gap-1.5 mt-1;
}

.preset-chip {
  @apply px-2 py-0.5 rounded-full text-[10px] font-medium;
  @apply bg-neutral-200/70 dark:bg-neutral-700/70;
  @apply text-neutral-700 dark:text-neutral-200;
  @apply hover:bg-neutral-300 dark:hover:bg-neutral-600;
}

.preset-favorite {
  @apply flex items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300;
}

.refdoc-control {
  @apply flex flex-wrap items-center gap-2 px-2 py-1 rounded-lg;
  @apply bg-neutral-100/70 dark:bg-neutral-800/70;
  @apply text-xs text-neutral-600 dark:text-neutral-300;
}

.refdoc-label {
  @apply font-medium text-neutral-700 dark:text-neutral-200;
}

.refdoc-select {
  @apply px-2 py-1 rounded-md text-xs;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.refdoc-clear {
  @apply px-2 py-0.5 rounded-md text-[11px];
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.refdoc-badge {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.refdoc-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.refdoc-loading {
  @apply inline-flex items-center gap-1.5 text-[11px];
  @apply text-neutral-500 dark:text-neutral-400;
}

.refdoc-count {
  @apply text-[11px] text-neutral-600 dark:text-neutral-300;
}

.refdoc-refresh {
  @apply p-1 rounded-md text-neutral-500 dark:text-neutral-400;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply disabled:opacity-40 disabled:cursor-not-allowed;
}

.refdoc-error {
  @apply text-[11px] text-error-600 dark:text-error-400;
}

.header-btn {
  @apply px-3 py-1.5 text-sm rounded-md;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors;
  @apply inline-flex items-center gap-2;
}

.cowic-banner {
  @apply flex flex-wrap items-center justify-between gap-3 px-3 md:px-4 py-2;
  @apply bg-neutral-50 dark:bg-neutral-800/60;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.cowic-info {
  @apply flex flex-wrap items-center gap-2 text-xs text-neutral-600 dark:text-neutral-300;
}

.cowic-title {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.cowic-summary {
  @apply text-[11px];
}

.cowic-auto-note {
  @apply max-w-2xl text-[11px] leading-relaxed text-neutral-500 dark:text-neutral-400;
}

.cowic-badge {
  @apply px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-amber-100 text-amber-700;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
}

.cowic-actions {
  @apply flex items-center gap-2;
}

.kwic-error {
  @apply mt-2 flex items-center gap-3 text-sm;
  @apply px-3 py-2 rounded-lg;
  @apply bg-error-50 text-error-700;
  @apply dark:bg-error-900/30 dark:text-error-200;
  @apply border border-error-200/60 dark:border-error-700/60;
}

.kwic-error-text {
  @apply flex-1 text-sm;
}

.kwic-error-btn {
  @apply px-2.5 py-1 rounded-md text-xs font-medium;
  @apply bg-white/80 text-error-700;
  @apply dark:bg-error-900/60 dark:text-error-100;
  @apply hover:bg-white dark:hover:bg-error-900;
}

.kwic-error-btn-secondary {
  @apply bg-transparent text-error-600;
  @apply dark:bg-transparent dark:text-error-200;
}

/* Rate-limit notice: amber (warning), non-blocking — sits above the still-
   visible results table rather than replacing it. */
.kwic-ratelimit {
  @apply mt-2 flex items-center gap-3 text-sm;
  @apply px-3 py-2 rounded-lg;
  @apply bg-amber-50 text-amber-800;
  @apply dark:bg-amber-900/30 dark:text-amber-200;
  @apply border border-amber-200/60 dark:border-amber-700/60;
}

.kwic-ratelimit-text {
  @apply flex-1 text-sm;
}

.sort-bar {
  @apply flex flex-wrap items-center gap-x-4 gap-y-2;
  @apply px-3 md:px-4 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-neutral-50 dark:bg-neutral-900;
}

.sort-group {
  @apply flex items-center gap-1.5;
}

.sort-group-label {
  @apply text-[11px] uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
  @apply mr-1;
}

.sort-btn {
  @apply inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors;
}

.sort-btn--active {
  @apply bg-primary-600 text-white border-primary-600;
  @apply hover:bg-primary-700;
}

.sort-btn--reset {
  @apply ml-auto;
}

.sort-btn:disabled {
  @apply opacity-40 cursor-not-allowed;
}

.sort-indicator {
  @apply text-[10px] leading-none;
}

.sort-status {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.column-header {
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-neutral-50 dark:bg-neutral-900;
}

.column-header-scroll {
  @apply overflow-x-auto;
}

.column-header-grid {
  @apply grid items-center;
  @apply px-3 md:px-4 py-1.5;
  @apply text-[11px] text-neutral-500 dark:text-neutral-400 uppercase tracking-wide;
}

.col-head {
  @apply truncate;
}

.col-head--pos {
  @apply text-center;
}

.col-head--match {
  @apply text-neutral-600 dark:text-neutral-300;
}

.col-head--variant {
  @apply text-neutral-600 dark:text-neutral-300;
}

.col-head--actions {
  @apply text-right;
}

.col-head--sortable {
  @apply inline-flex items-center gap-1 text-left;
  @apply uppercase tracking-wide;
  @apply cursor-pointer rounded px-1 -mx-1;
  @apply transition-colors;
}

.col-head--sortable:hover {
  @apply text-neutral-700 dark:text-neutral-200;
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.col-head--sortable.col-head--match {
  @apply justify-center text-center;
}

.col-head--active {
  @apply text-primary-600 dark:text-primary-400 font-semibold;
}

.col-head-indicator {
  @apply text-[10px];
}

.kwic-truncation {
  @apply text-neutral-400 dark:text-neutral-500 select-none;
}

.scope-chip {
  @apply inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-xs;
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-300;
}

.scope-chip.active {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.co-anchors {
  @apply flex flex-wrap items-center gap-1.5 text-[11px];
}

.co-anchors-label {
  @apply text-neutral-500 dark:text-neutral-400;
}

.co-anchors-term {
  @apply inline-flex items-center px-2 py-0.5 rounded-full;
  @apply bg-neutral-100 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-200;
  @apply font-medium;
}

.co-anchors-plus {
  @apply text-neutral-500 dark:text-neutral-400;
}

.co-anchor-chip {
  @apply inline-flex items-center gap-1 px-2 py-0.5 rounded-full;
  @apply bg-amber-50 text-amber-700 border border-amber-200/80;
  @apply dark:bg-amber-900/30 dark:text-amber-200 dark:border-amber-700/60;
  @apply hover:bg-amber-100 dark:hover:bg-amber-900/50;
  @apply transition-colors;
}

.co-anchor-text {
  @apply max-w-[140px] truncate;
}

.parallel-chip {
  @apply inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-[11px];
  @apply bg-indigo-50 text-indigo-700;
  @apply dark:bg-indigo-900/40 dark:text-indigo-200;
  @apply border border-indigo-200/60 dark:border-indigo-700/50;
}

/* KWIC-Zufallsstichprobe (T1): Provenienz-Chip + Konfigurations-Control */
.sample-chip {
  @apply inline-flex items-center gap-2 px-2.5 py-1 rounded-full text-[11px];
  @apply bg-amber-50 text-amber-800;
  @apply dark:bg-amber-900/40 dark:text-amber-200;
  @apply border border-amber-200/60 dark:border-amber-700/50;
}

.sample-control {
  @apply flex items-center gap-2 text-xs;
}

.sample-toggle {
  @apply inline-flex items-center gap-1.5 cursor-pointer select-none;
}

.sample-field {
  @apply inline-flex items-center gap-1;
}

.sample-field-label {
  @apply text-neutral-500 dark:text-neutral-400;
}

.sample-input {
  @apply w-16 px-1.5 py-0.5 rounded border text-xs font-mono;
  @apply border-neutral-300 dark:border-neutral-600;
  @apply bg-white dark:bg-neutral-900;
}

.sample-input--seed {
  @apply w-20;
}

.sample-draw {
  @apply px-2 py-0.5 rounded border text-xs;
  @apply border-neutral-300 dark:border-neutral-600;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
}

.streaming-pill {
  @apply inline-flex items-center gap-2 text-[11px] px-2.5 py-1 rounded-full;
  @apply bg-primary-50 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
  @apply border border-primary-200/60 dark:border-primary-700/50;
}

.streaming-dot {
  @apply w-2 h-2 rounded-full bg-primary-500 animate-pulse;
}

.streaming-count {
  @apply font-mono;
}

.streaming-elapsed {
  @apply font-mono text-[10px] text-primary-600;
  @apply dark:text-primary-200;
}

.streaming-cancel {
  @apply text-[11px] font-medium;
  @apply text-primary-700 dark:text-primary-200;
  @apply hover:underline;
}

.name-modal {
  @apply flex flex-col gap-3;
}

.name-label {
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-400;
}

.name-input {
  @apply w-full px-3 py-2 rounded-lg text-sm;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.name-actions {
  @apply flex items-center justify-end gap-2;
}

.table-viewport {
  @apply overflow-auto;
  @apply overflow-x-auto;
  @apply focus:outline-none;
  /* The lines take the rest of the tab, and never less than 20rem or the
     whole tab height, whichever is smaller. */
  flex: 1 1 0;
  min-height: min(20rem, 100cqh);
}

.table-content {
  @apply relative w-full whitespace-nowrap;
}

.table-row {
  @apply px-3 md:px-4 py-2 md:py-3;
  @apply border-b border-neutral-100 dark:border-neutral-800;
  @apply cursor-pointer;
  @apply transition-colors;
  min-height: 44px;
}

@media (min-width: 768px) {
  .table-row {
    min-height: 48px;
  }
}

.table-row:hover {
  @apply bg-neutral-50 dark:bg-neutral-800/50;
}

.table-row.is-selected {
  @apply bg-primary-50 dark:bg-primary-900/20;
}

.table-row.is-highlighted {
  @apply ring-2 ring-copilot-primary ring-inset;
  box-shadow: var(--shadow-copilot);
}

/* Keyboard-active row (aria-activedescendant target): visible focus ring. */
.table-row.is-active {
  @apply ring-2 ring-primary-500 ring-inset;
}

.table-row.is-expanded {
  @apply bg-neutral-50 dark:bg-neutral-800;
  min-height: auto;
}

/*
 * Category-filtered-out row: collapse to ~0px for real. The inner content is
 * already skipped (v-if), but the wrapper's min-height + py padding + border
 * would otherwise leave a ~48-72px ghost gap. Zero them all so the row truly
 * disappears while its virtualizer slot/index stays intact.
 */
.table-row.is-filtered-out {
  min-height: 0;
  padding-top: 0;
  padding-bottom: 0;
  border-bottom-width: 0;
  overflow: hidden;
  pointer-events: none;
}

/* Desktop: Full-Width KWIC Layout */
.row-desktop {
  @apply grid items-center gap-3 md:gap-4;
  @apply whitespace-nowrap;
  /* Fallback only; the inline rowDesktopStyle drives the real tracks and
     must match this shape so header and body grids align (DESIGN-UX-GLOBAL-01). */
  grid-template-columns: 72px minmax(0, 1fr) minmax(120px, 0.55fr) minmax(0, 1fr) 96px;
}

.row-position {
  @apply text-xs text-neutral-500 font-mono text-right pr-1;
}

.row-left {
  @apply flex justify-end;
  @apply text-right text-neutral-700 dark:text-neutral-300;
  @apply min-w-0 whitespace-nowrap overflow-hidden;
}

.row-match {
  @apply font-semibold px-1;
  @apply whitespace-nowrap overflow-hidden text-ellipsis;
}

.row-right {
  @apply text-left text-neutral-700 dark:text-neutral-300;
  @apply min-w-0 whitespace-nowrap overflow-hidden text-ellipsis;
}

.row-actions {
  @apply flex items-center gap-1 opacity-0;
  @apply transition-opacity;
}

.table-row:hover .row-actions {
  @apply opacity-100;
}

.action-btn {
  @apply p-1.5 rounded;
  @apply text-neutral-500 hover:text-neutral-700 dark:hover:text-neutral-300;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors;
}

.row-variant {
  @apply flex flex-col gap-1 rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800/60;
  @apply px-2 py-1.5;
  min-width: 0;
}

.variant-meta {
  @apply flex items-center justify-between gap-2;
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.variant-badges {
  @apply flex flex-wrap items-center gap-1;
}

.variant-badge {
  @apply px-1.5 py-0.5 rounded-md text-[10px] font-medium;
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-700 dark:text-neutral-200;
}

.variant-badge--prompt {
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.variant-badge--model {
  @apply bg-neutral-200 text-neutral-700;
  @apply dark:bg-neutral-700 dark:text-neutral-200;
}

.variant-score {
  @apply font-mono;
}

.variant-context {
  @apply text-neutral-700 dark:text-neutral-300 whitespace-normal;
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 3;
  overflow: hidden;
  overflow-wrap: anywhere;
}

.variant-left,
.variant-right {
  @apply inline;
}

.variant-context .kwic-match {
  @apply mx-1;
}

.variant-metrics {
  @apply text-[11px] font-mono text-neutral-500 dark:text-neutral-400;
}

.variant-missing {
  @apply opacity-70;
}

.variant-unmatched {
  @apply border-dashed;
}

.kwic-unmatched {
  @apply opacity-70 italic;
}

/* Mobile: Stacked Layout */
.row-mobile {
  @apply flex flex-col gap-1;
}

.match-line {
  @apply flex items-center justify-between;
}

.match-line .position {
  @apply text-xs text-neutral-500 font-mono;
}

.context-line {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
  @apply truncate;
}

.context-line .context-text {
  @apply truncate;
}

.context-separator {
  @apply text-neutral-300 dark:text-neutral-600;
}

.expanded-context {
  @apply mt-3 pt-3 border-t border-neutral-200 dark:border-neutral-700;
  @apply space-y-2;
}

.context-metadata {
  @apply flex flex-col gap-1 text-sm;
}

.metadata-head {
  @apply flex flex-col gap-2;
}

@media (min-width: 768px) {
  .metadata-head {
    @apply flex-row items-center justify-between;
  }
}

.doc-label {
  @apply font-medium text-neutral-800 dark:text-neutral-100;
  word-break: break-all;
}

.meta-chips {
  @apply flex flex-wrap gap-1;
}

.meta-chip {
  @apply px-2 py-0.5 rounded-full text-xs;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-300;
}

.meta-summary {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
  word-break: break-word;
}

.detail-loading,
.detail-error {
  @apply text-sm px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.detail-loading {
  @apply text-neutral-600 dark:text-neutral-300;
}

.detail-error {
  @apply text-error-600 dark:text-error-400;
  @apply flex items-center gap-2;
}

.detail-retry {
  @apply px-2 py-0.5 rounded-md text-[11px] font-medium;
  @apply bg-error-50 text-error-700;
  @apply dark:bg-error-900/40 dark:text-error-200;
  @apply hover:bg-error-100 dark:hover:bg-error-900;
}

.expanded-context .context-text {
  @apply flex items-center gap-2 p-3 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply text-sm;
}

.alignment-panel {
  @apply mt-2 p-3 rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply space-y-2;
}

.alignment-head {
  @apply flex flex-wrap items-center justify-between gap-2;
}

.alignment-title {
  @apply text-sm font-semibold text-neutral-800 dark:text-neutral-100;
}

.alignment-override {
  @apply ml-2 px-2 py-0.5 rounded-full text-[10px] font-semibold uppercase tracking-wide;
  @apply bg-primary-100 text-primary-700;
  @apply dark:bg-primary-900/40 dark:text-primary-200;
}

.alignment-btn {
  @apply px-2.5 py-1 text-xs rounded-md border;
  @apply border-neutral-300 dark:border-neutral-600;
  @apply text-neutral-700 dark:text-neutral-200;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.alignment-loading,
.alignment-error {
  @apply text-sm px-3 py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.alignment-loading {
  @apply text-neutral-600 dark:text-neutral-300;
}

.alignment-error {
  @apply text-error-600 dark:text-error-400;
  @apply flex items-center gap-2;
}

.alignment-retry {
  @apply px-2 py-0.5 rounded-md text-[11px] font-medium;
  @apply bg-neutral-100 text-neutral-700;
  @apply dark:bg-neutral-800 dark:text-neutral-200;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
}

.alignment-summary {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.alignment-body {
  @apply space-y-2;
}

/* ── KWIC annotation layer (F7) ──────────────────────────────────── */
.ann-count-badge {
  @apply ml-1 px-1.5 rounded-full text-[10px] font-semibold;
  @apply bg-copilot-primary text-white;
}

.annotation-bar {
  @apply flex items-center flex-wrap gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-neutral-50/60 dark:bg-neutral-900/40;
}

/* ── Filter-loaded-rows bar (DT-FE-UX-CORE) ──────────────────────── */
.row-filter-bar {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-neutral-50/60 dark:bg-neutral-900/40;
}

.row-filter-input {
  @apply flex-1 min-w-0 px-2.5 py-1 rounded-md text-sm;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-900 dark:text-neutral-100;
  @apply focus:outline-none focus:ring-2 focus:ring-primary-500;
}

.row-filter-error {
  @apply text-xs text-amber-700 dark:text-amber-300;
}

.row-filter-count {
  @apply text-xs tabular-nums text-neutral-500 dark:text-neutral-400 flex-shrink-0;
}

.row-filter-clear {
  @apply p-1 rounded-md text-neutral-500;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply transition-colors flex-shrink-0;
}

.ann-filter-chip {
  @apply inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium;
  @apply border border-neutral-300 dark:border-neutral-700;
  @apply text-neutral-700 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
  @apply transition-colors;
}

.ann-filter-chip.active {
  @apply bg-copilot-primary text-white border-copilot-primary;
}

.ann-filter-dot {
  @apply w-2.5 h-2.5 rounded-full flex-shrink-0;
}

.ann-filter-count {
  @apply px-1 rounded text-[10px] tabular-nums;
  @apply bg-neutral-200/70 dark:bg-neutral-700/70;
}

.ann-filter-chip.active .ann-filter-count {
  @apply bg-white/25;
}

.ann-filter-clear {
  @apply inline-flex items-center gap-1 px-2 py-1 text-xs;
  @apply text-neutral-500 hover:text-copilot-primary;
  @apply transition-colors;
}

.ann-filter-shown {
  @apply text-[10px] text-neutral-400;
}

/* Per-row badge + button */
.row-annotation-badge {
  @apply inline-flex items-center gap-1 mr-1;
}

.ann-cat-chip {
  @apply px-1.5 py-0.5 rounded-full text-[10px] font-semibold text-white;
  @apply max-w-[8rem] truncate;
}

.ann-note-icon {
  @apply w-3.5 h-3.5 text-copilot-primary;
}

.ann-note-icon.no-cat {
  @apply text-neutral-400;
}

.ann-btn.active {
  @apply text-copilot-primary;
}

/* Annotation editor modal */
.annotation-editor {
  @apply space-y-4;
}

.ann-row-preview {
  @apply text-sm leading-relaxed p-3 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-neutral-600 dark:text-neutral-300;
}

.ann-preview-match {
  @apply font-semibold mx-1;
}

.ann-field {
  @apply space-y-2;
}

.ann-label {
  @apply block text-sm font-medium text-neutral-700 dark:text-neutral-300;
}

.ann-category-grid {
  @apply flex flex-wrap gap-2;
}

.ann-category-btn {
  @apply inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm;
  @apply border-2 bg-white dark:bg-neutral-900;
  @apply text-neutral-700 dark:text-neutral-200;
  @apply transition-colors;
}

.ann-category-btn.active {
  @apply font-semibold;
}

.ann-cat-key {
  @apply px-1 rounded text-[10px] uppercase;
  @apply bg-neutral-200/70 dark:bg-neutral-700/70;
}

.ann-empty-scheme {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.ann-link {
  @apply text-copilot-primary hover:underline;
}

.ann-note-input {
  @apply w-full px-3 py-2 rounded-lg text-sm resize-y;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply focus:ring-2 focus:ring-primary-500 focus:outline-none;
}

.ann-footer-delete {
  @apply inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm;
  @apply text-error-600 hover:bg-error-50 dark:hover:bg-error-900/20;
  @apply transition-colors;
}

.ann-footer-spacer {
  @apply flex-1;
}

.ann-footer-cancel {
  @apply px-3 py-2 rounded-lg text-sm;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.ann-footer-save {
  @apply px-3 py-2 rounded-lg text-sm font-medium;
  @apply bg-copilot-primary text-white hover:bg-copilot-secondary;
  @apply transition-colors;
}
</style>
