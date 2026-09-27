<script setup lang="ts">
/**
 * NgramsTab - N-gram analysis view
 *
 * Two modes:
 * - "frequency": n-gram frequency list for the whole corpus or the active docset
 *   (POST /analysis/ngrams/job, polled via /analysis/jobs/{id} + /rows).
 * - "diff": target vs. reference subcorpus contrast
 *   (POST /analysis/ngrams_diff/job), reusing saved subcorpora; docset ids are
 *   re-resolved through the docset store (ids are transient cache hints).
 */
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { Hash, Download, RefreshCw, ArrowLeftRight, BarChart3, AlertTriangle, Info } from 'lucide-vue-next'
import { HTTPError } from 'ky'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import { useAnalysisJobsStore, useAnalysisPresetsStore, useDocsetStore, useSubcorporaStore } from '@/stores'
import { useSettingsStore } from '@/stores/settings'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import type { DocsetSnapshot } from '@/stores/docset'
import type { SubcorpusSnapshot } from '@/stores/subcorpora'
import Button from '@/components/ui/Button.vue'
import MeasureInfo from '@/components/ui/MeasureInfo.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import type { AnalysisJobRows } from '@/api/client'
import { NGRAM_OPERATIONS, useNgramOperations } from '@/composables/useNgramOperations'
import { downloadText } from '@/utils/download'
import {
  NGRAM_SIZES,
  buildNgramResultStateHeader,
  buildNgramResultStateSummary,
  buildNgramCsv,
  buildNgramFormulaLines,
  mapNgramDiffRows,
  mapNgramFrequencyRows,
  formatPerMillion,
  perMillion,
  sortNgramRows,
  type NgramResultState,
  type NgramDiffRow,
  type NgramRow,
} from '@/components/analysis/ngrams'
import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import { actionBus } from '@/actions/bus'
import { ngramRowQuery } from '@/utils/backPathQuery'
import { formatDecimal } from '@/i18n/format'
import { coerceMethodBlock, type MethodBlock } from '@/api/client'
import { ensureUsableResearchScope, researchScopeCsvMeta } from '@/lib/researchScope'
import {
  productOperationFocusMatches,
  useProductOperationFocus,
} from '@/composables/useProductOperationFocus'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const ROW_LIMIT = 500

const { t } = useI18n()
const queryStore = useQueryStore()

/**
 * Row to concordance: the exact word sequence inside one document, like the
 * n-gram count, in the same scope. The KWIC total equals the row frequency
 * (checked on sotu_en and dta_de, n = 1 to 5, corpus and docset).
 */
async function openRowConcordance(row: { ngram: string }) {
  if (!row.ngram.trim()) return
  const docsetId = researchScope.value.docsetId ?? undefined
  const result = await actionBus.dispatch({
    type: 'query/execute',
    payload: { term: ngramRowQuery(row.ngram), contextSize: queryStore.contextSize, ...(docsetId ? { docsetId } : {}) },
  })
  if (result.success) await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
}
const uiStore = useUiStore()
const settingsStore = useSettingsStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const docsetStore = useDocsetStore()
const subcorporaStore = useSubcorporaStore()
const presetsStore = useAnalysisPresetsStore()
const analysisJobs = useAnalysisJobsStore()
const {
  createNgramFrequencyJob,
  createNgramDiffJob,
} = useNgramOperations()
const { consumeFocusFor, focusMatches, focusIs, modeIs } = useProductOperationFocus()

// Settings
const mode = ref<'frequency' | 'diff'>('frequency')
const frequencyFocused = computed(() =>
  modeIs('job', 'frequency', 'frequency_job') ||
  focusIs('analysis.ngrams.frequency_job') ||
  focusMatches('analysis.ngrams.job', 'analysis.ngrams.frequency')
)
const diffFocused = computed(() =>
  modeIs('diff') ||
  focusIs('analysis.ngrams.diff_job') ||
  focusMatches('analysis.ngrams.diff')
)
const ngramSize = ref(2)
const minFreq = ref(5)
const sortBy = ref<'frequency' | 'relative'>('frequency')
const researchScope = computed(() =>
  ensureUsableResearchScope(docsetStore, { operation: t('analysis.ngrams.operation') })
)

// Diff mode scope
const targetSubId = ref<string | null>(null)
const referenceSubId = ref<string | null>(null)

// Data
const isLoading = ref(false)
const data = ref<NgramRow[]>([])
const diffRows = ref<NgramDiffRow[]>([])
const jobError = ref<string | null>(null)
const sessionPresetId = ref<string | null>(null)
const resultState = ref<NgramResultState | null>(null)
// F1: statistical provenance from the server method block (sync + diff).
const ngramMethod = ref<MethodBlock | null>(null)
let runToken = 0
let runController: AbortController | null = null

const effectiveTokenCount = computed(() => {
  if (docsetStore.hasActiveDocset) {
    return docsetStore.stats.tokenCount
  }
  return corpusCapabilities.activeCorpusTokenCount || (
    settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.tokenCount : 0
  )
})
const effectiveDocCount = computed(() =>
  docsetStore.hasActiveDocset ? docsetStore.stats.docCount : corpusCapabilities.activeCorpusDocCount
)

const scopeText = computed(() => {
  if (!docsetStore.hasActiveDocset) return t('analysis.shared.wholeCorpus')
  if (!researchScope.value.ok) return researchScope.value.evidence.label
  const docs = formatNumber(docsetStore.stats.docCount)
  const tokens = formatNumber(docsetStore.stats.tokenCount)
  return t('analysis.shared.docsTokens', { docs, tokens })
})

const jobScope = computed(() => mode.value === 'diff' ? 'ngrams_diff' : 'ngrams')
const jobSnapshot = computed(() => analysisJobs.activeSnapshot(jobScope.value))

const isJobRunning = computed(() => {
  const status = jobSnapshot.value?.status
  return status === 'running' || status === 'queued'
})

const displayedResultRows = computed(() => mode.value === 'diff' ? diffRows.value.length : data.value.length)
const resultStateSummary = computed(() => buildNgramResultStateSummary(resultState.value, {
  displayedRows: displayedResultRows.value,
  minFreq: minFreq.value,
  mode: mode.value,
}))

const parkedSubcorpora = computed(() =>
  subcorporaStore.parked.filter((s) => s.corpus === docsetStore.activeCorpus)
)

const targetSubcorpus = computed(
  () => parkedSubcorpora.value.find((s) => s.id === targetSubId.value) ?? null
)
const referenceSubcorpus = computed(
  () => parkedSubcorpora.value.find((s) => s.id === referenceSubId.value) ?? null
)

/** Extract the backend's `detail` message from a ky HTTPError (e.g. max_n cap). */
async function describeApiError(err: unknown, fallback: string): Promise<string> {
  if (err instanceof HTTPError) {
    try {
      const body = (await err.response.clone().json()) as { detail?: unknown }
      if (body && typeof body.detail === 'string' && body.detail) return body.detail
    } catch {
      // body not JSON / already consumed - fall through
    }
  }
  if (err instanceof Error && err.message) return err.message
  return fallback
}

function resetForNewRun() {
  runToken += 1
  runController?.abort()
  runController = new AbortController()
  analysisJobs.clearScope('ngrams')
  analysisJobs.clearScope('ngrams_diff')
  jobError.value = null
  data.value = []
  diffRows.value = []
  resultState.value = null
  ngramMethod.value = null
  isLoading.value = true
  return { token: runToken, signal: runController.signal }
}

function captureResultState(response: AnalysisJobRows<unknown>, loadedRows: number) {
  resultState.value = {
    truncated: response.truncated,
    rowLimit: response.row_limit,
    totalCandidates: response.total_candidates,
    loadedRows,
  }
}

function isAbortError(error: unknown): boolean {
  return error instanceof Error && error.name === 'AbortError'
}

function isCurrentRun(token: number): boolean {
  return token === runToken
}

async function loadData() {
  if (mode.value !== 'frequency') return
  const run = resetForNewRun()
  try {
    if (!researchScope.value.ok) throw new Error(researchScope.value.message)
    const rowsResponse = await analysisJobs.runJobRows<Record<string, unknown>>({
      scope: 'ngrams',
      kind: 'ngrams',
      corpus: docsetStore.activeCorpus,
      signal: run.signal,
      rowsLimit: ROW_LIMIT,
      queuedMessage: t('analysis.ngrams.jobStarted'),
      productOperation: {
        operationId: NGRAM_OPERATIONS.frequencyJob,
        surfaceId: 'analysis.ngrams',
        label: t('analysis.operations.ngramFrequencyJob'),
        detail: t('analysis.ngrams.sizeN', { n: ngramSize.value }),
      },
      start: () => createNgramFrequencyJob({
        n: ngramSize.value,
        minFreq: minFreq.value,
        limit: ROW_LIMIT,
        corpus: docsetStore.activeCorpus,
        docsetId: researchScope.value.docsetId,
      }, {
        target: docsetStore.activeCorpus ? t('analysis.shared.corpusNamed', { name: docsetStore.activeCorpus }) : t('analysis.shared.activeCorpus'),
        impact: t('analysis.ngrams.frequencyJobImpact'),
        contextualConfirmation: {
          surfaceId: 'analysis.ngrams',
          interaction: 'ngrams.tab.frequency_job',
          source: 'native_surface',
        },
      }),
      onStarted: async (start) => {
        try {
          const session = await presetsStore.upsertJobSession({
            id: sessionPresetId.value ?? undefined,
            name: t('analysis.ngrams.defaultName', { query: queryStore.term || t('analysis.ngrams.noQuery') }),
            type: 'ngrams',
            corpus: docsetStore.activeCorpus,
            docset: docsetSnapshot.value,
            queryTerm: queryStore.term,
            params: { ngramSize: ngramSize.value, minFreq: minFreq.value, sortBy: sortBy.value },
            status: 'queued',
            jobId: start.job_id,
            kind: sessionPresetId.value ? undefined : 'session',
          })
          sessionPresetId.value = session.id
        } catch (err) {
          console.warn('Analysis session could not be saved', err)
        }
      },
      onSnapshot: (snapshot) => {
        if (isCurrentRun(run.token) && sessionPresetId.value) {
          void presetsStore.updateJobStatus(sessionPresetId.value, snapshot)
        }
      },
    })
    if (!isCurrentRun(run.token)) return
    const rows = (rowsResponse.rows ?? []) as Array<Record<string, unknown>>
    captureResultState(rowsResponse, rows.length)
    const method = coerceMethodBlock((rowsResponse as { method?: unknown }).method) ?? null
    ngramMethod.value = method
    data.value = mapNgramFrequencyRows(rows, {
      minFreq: minFreq.value,
      tokenCount: effectiveTokenCount.value,
      targetTotal: method?.target_total,
    })
    if (sessionPresetId.value) {
      const cacheKey = await presetsStore.buildCacheKey({
        type: 'ngrams',
        corpus: docsetStore.activeCorpus,
        docset: docsetSnapshot.value,
        queryTerm: queryStore.term,
        params: { ngramSize: ngramSize.value, minFreq: minFreq.value, sortBy: sortBy.value },
      })
      void presetsStore.updateResult(
        sessionPresetId.value,
        { rows: data.value },
        {
          n: ngramSize.value,
          minFreq: minFreq.value,
          sortBy: sortBy.value,
          corpus: docsetStore.activeCorpus,
          docsetId: docsetStore.activeDocsetId ?? null,
          docCount: effectiveDocCount.value,
          tokenCount: effectiveTokenCount.value,
          cacheKey,
          cacheVersion: presetsStore.cacheVersion,
          generatedAt: Date.now(),
        }
      )
    }
  } catch (error) {
    if (isAbortError(error)) return
    jobError.value = await describeApiError(error, t('analysis.ngrams.loadFailed'))
    uiStore.showToast(jobError.value, 'error')
  } finally {
    if (isCurrentRun(run.token)) {
      isLoading.value = false
    }
  }
}

/** Rebuild a saved subcorpus into a docset-store snapshot for re-resolution. */
function toDocsetSnapshot(s: SubcorpusSnapshot): DocsetSnapshot {
  return {
    corpus: s.corpus,
    docsetId: s.docsetId ?? '',
    stats: {
      docCount: s.stats.docCount,
      hitDocCount: s.stats.docCount,
      refDocCount: s.stats.refDocCount,
      tokenCount: s.stats.tokenCount,
    },
    filters: {
      prompting_method: [...s.filters.prompting_method],
      model: [...s.filters.model],
      register: [...s.filters.register],
      source: [...s.filters.source],
    },
    includeAi: s.includeAi,
    includeHuman: s.includeHuman,
    query: s.origin.query,
    name: s.name,
    filterSpec: s.filterSpec,
    metadataSchemaHash: s.metadataSchemaHash,
  }
}

async function runDiff() {
  const target = targetSubcorpus.value
  const reference = referenceSubcorpus.value
  if (!target || !reference) {
    const message = t('analysis.ngrams.pickBoth')
    jobError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  if (target.id === reference.id) {
    const message = t('analysis.ngrams.pickDifferent')
    jobError.value = message
    uiStore.showToast(message, 'warning')
    return
  }
  const run = resetForNewRun()
  try {
    const [targetDocsetId, referenceDocsetId] = await Promise.all([
      docsetStore.resolveDocset(toDocsetSnapshot(target)),
      docsetStore.resolveDocset(toDocsetSnapshot(reference)),
    ])
    if (!targetDocsetId || !referenceDocsetId) {
      throw new Error(t('analysis.ngrams.resolveFailed'))
    }
    if (targetDocsetId === referenceDocsetId) {
      jobError.value = t('analysis.ngrams.sameDocuments')
      isLoading.value = false
      return
    }
    const rowsResponse = await analysisJobs.runJobRows<Record<string, unknown>>({
      scope: 'ngrams_diff',
      kind: 'ngrams_diff',
      corpus: docsetStore.activeCorpus,
      signal: run.signal,
      rowsLimit: ROW_LIMIT,
      queuedMessage: t('analysis.ngrams.diffStarted'),
      productOperation: {
        operationId: NGRAM_OPERATIONS.diffJob,
        surfaceId: 'analysis.ngrams',
        label: t('analysis.operations.ngramContrastJob'),
        detail: t('analysis.ngrams.sizeN', { n: ngramSize.value }),
      },
      start: () => createNgramDiffJob({
        targetDocsetId,
        referenceDocsetId,
        n: ngramSize.value,
        minFreq: minFreq.value,
        limit: ROW_LIMIT,
        corpus: docsetStore.activeCorpus,
      }, {
        target: docsetStore.activeCorpus ? t('analysis.shared.corpusNamed', { name: docsetStore.activeCorpus }) : t('analysis.shared.activeCorpus'),
        impact: t('analysis.ngrams.diffJobImpact'),
        contextualConfirmation: {
          surfaceId: 'analysis.ngrams',
          interaction: 'ngrams.tab.diff_job',
          source: 'native_surface',
        },
      }),
    })
    if (!isCurrentRun(run.token)) return
    const rows = (rowsResponse.rows ?? []) as Array<Record<string, unknown>>
    captureResultState(rowsResponse, rows.length)
    ngramMethod.value = coerceMethodBlock((rowsResponse as { method?: unknown }).method) ?? null
    diffRows.value = mapNgramDiffRows(rows, { minFreq: minFreq.value, limit: ROW_LIMIT })
  } catch (error) {
    if (isAbortError(error)) return
    jobError.value = await describeApiError(error, t('analysis.ngrams.diffLoadFailed'))
    uiStore.showToast(jobError.value, 'error')
  } finally {
    if (isCurrentRun(run.token)) {
      isLoading.value = false
    }
  }
}

async function cancelJob() {
  const activeJobId = analysisJobs.activeJobId(jobScope.value)
  if (!activeJobId || !isJobRunning.value) return
  try {
    const snap = await analysisJobs.cancelJob(activeJobId)
    analysisJobs.clearScope(jobScope.value)
    if (mode.value === 'frequency' && sessionPresetId.value) {
      void presetsStore.updateJobStatus(sessionPresetId.value, snap)
    }
    runController?.abort()
    jobError.value = null
    isLoading.value = false
    uiStore.showToast(t('analysis.ngrams.cancelling'), 'info')
  } catch (err) {
    uiStore.showToast(t('analysis.ngrams.cancelFailed'), 'error')
  }
}

async function resumeJob(existingJobId: string) {
  runToken += 1
  runController?.abort()
  runController = new AbortController()
  const token = runToken
  jobError.value = null
  isLoading.value = true
  try {
    const rowsResponse = await analysisJobs.resumeJobRows<Record<string, unknown>>({
      scope: 'ngrams',
      jobId: existingJobId,
      signal: runController.signal,
      rowsLimit: ROW_LIMIT,
      onSnapshot: (snapshot) => {
        if (isCurrentRun(token) && sessionPresetId.value) {
          void presetsStore.updateJobStatus(sessionPresetId.value, snapshot)
        }
      },
    })
    if (!isCurrentRun(token)) return
    const rows = (rowsResponse.rows ?? []) as Array<Record<string, unknown>>
    captureResultState(rowsResponse, rows.length)
    const method = coerceMethodBlock((rowsResponse as { method?: unknown }).method) ?? null
    ngramMethod.value = method
    data.value = mapNgramFrequencyRows(rows, {
      minFreq: minFreq.value,
      tokenCount: effectiveTokenCount.value,
      targetTotal: method?.target_total,
    })
  } catch (error) {
    if (isAbortError(error)) return
    jobError.value = await describeApiError(error, t('analysis.ngrams.jobLoadFailed'))
  } finally {
    if (isCurrentRun(token)) {
      isLoading.value = false
    }
  }
}

function refresh() {
  if (mode.value === 'frequency') {
    void loadData()
  } else {
    void runDiff()
  }
}

const sortedData = computed(() => sortNgramRows(data.value, sortBy.value))

function exportCSV() {
  const commonHeader = [
    '# CandyConc Export',
    `# N: ${ngramSize.value}`,
    `# MinFreq: ${minFreq.value}`,
    `# Corpus: ${docsetStore.activeCorpus}`,
    `# Exported: ${new Date().toISOString()}`,
  ]
  let csv: string
  let filename: string
  if (mode.value === 'diff') {
    if (!diffRows.value.length) return
    csv = buildNgramCsv(
      [
        commonHeader[0]!,
        '# Analysis: Ngrams Diff',
        ...commonHeader.slice(1, 4),
        `# Target: ${targetSubcorpus.value?.name ?? 'n/a'}`,
        `# Reference: ${referenceSubcorpus.value?.name ?? 'n/a'}`,
        ...buildNgramResultStateHeader(resultState.value),
        ...buildNgramFormulaLines(ngramMethod.value, 'diff'),
        commonHeader[4]!,
      ],
      [
        'ngram',
        'target_freq',
        'target_per_million',
        'reference_freq',
        'reference_per_million',
        'diff_per_million',
      ],
      diffRows.value.map((row) => [
        row.ngram,
        row.targetFreq,
        row.targetPerMillion.toFixed(4),
        row.referenceFreq,
        row.referencePerMillion.toFixed(4),
        row.diffPerMillion.toFixed(4),
      ])
    )
    filename = `ngrams_diff_${ngramSize.value}.csv`
  } else {
    if (!sortedData.value.length) return
    const filters = docsetStore.filters
    csv = buildNgramCsv(
      [
        commonHeader[0]!,
        '# Analysis: Ngrams',
        ...commonHeader.slice(1, 4),
        `# SortBy: ${sortBy.value}`,
        `# Docset: ${docsetStore.activeDocsetId ?? 'all'}`,
        `# Docs: ${effectiveDocCount.value}`,
        `# Tokens: ${effectiveTokenCount.value}`,
        `# Query: ${queryStore.term || 'n/a'}`,
        ...researchScopeCsvMeta(docsetStore),
        `# Filter.prompting_method: ${filters.prompting_method.length ? filters.prompting_method.join(' | ') : 'all'}`,
        `# Filter.model: ${filters.model.length ? filters.model.join(' | ') : 'all'}`,
        `# Filter.register: ${filters.register.length ? filters.register.join(' | ') : 'all'}`,
        `# Filter.source: ${filters.source.length ? filters.source.join(' | ') : 'all'}`,
        `# IncludeAI: ${docsetStore.includeAi}`,
        `# IncludeHuman: ${docsetStore.includeHuman}`,
        ...buildNgramResultStateHeader(resultState.value),
        ...buildNgramFormulaLines(ngramMethod.value, 'frequency'),
        commonHeader[4]!,
      ],
      ['ngram', 'frequency', 'per_million'],
      sortedData.value.map((row) => [row.ngram, row.frequency, formatPerMillion(row.relative, 4)])
    )
    filename = `ngrams_${ngramSize.value}.csv`
  }
  downloadText(csv, filename, 'text/csv')
}

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
        query: queryStore.term,
      }
    : null
)

// Reload (frequency mode) when the scope changes; n-grams need no query term.
watch(
  () => [queryStore.term, docsetStore.activeDocsetId, docsetStore.activeCorpus],
  () => {
    if (actionBus.isActionInProgress('analysis/ngramFrequency')) return
    if (mode.value === 'frequency') void loadData()
  },
  { immediate: true }
)

// Diff selections are per-corpus.
watch(
  () => docsetStore.activeCorpus,
  () => {
    targetSubId.value = null
    referenceSubId.value = null
    diffRows.value = []
  }
)

watch(mode, (next) => {
  runToken += 1
  runController?.abort()
  analysisJobs.clearScope('ngrams')
  analysisJobs.clearScope('ngrams_diff')
  jobError.value = null
  isLoading.value = false
  resultState.value = null
  if (actionBus.isActionInProgress('analysis/ngramFrequency')) return
  if (next === 'frequency' && !data.value.length) void loadData()
})

consumeFocusFor(['analysis.ngrams'], (focus) => {
  mode.value =
    focus.operationId === 'analysis.ngrams.diff_job' ||
    focus.preferredMode === 'diff' ||
    productOperationFocusMatches(focus, 'analysis.ngrams.diff')
      ? 'diff'
      : 'frequency'
})

watch(
  () => presetsStore.pendingPreset,
  async (preset) => {
    if (!preset || preset.type !== 'ngrams') return
    mode.value = 'frequency'
    sessionPresetId.value = preset.id
    let hasValidResult = false
    const params = preset.params as { ngramSize?: number; minFreq?: number; sortBy?: 'frequency' | 'relative' }
    if (params.ngramSize) ngramSize.value = params.ngramSize
    if (params.minFreq) minFreq.value = params.minFreq
    if (params.sortBy) sortBy.value = params.sortBy
    presetsStore.setPending(null)
    if (preset.result && typeof preset.result === 'object' && (preset.result as any).rows) {
      const valid = await presetsStore.isResultValid(preset)
      if (valid) {
        data.value = ((preset.result as any).rows ?? []) as NgramRow[]
        jobError.value = null
        isLoading.value = false
        analysisJobs.clearScope('ngrams')
        hasValidResult = true
      } else {
        uiStore.showToast(t('analysis.shared.staleSaved'), 'info', 2500)
      }
    }
    if (preset.jobId && (preset.status === 'running' || preset.status === 'queued')) {
      await resumeJob(preset.jobId)
    } else if (!hasValidResult) {
      await loadData()
    }
  }
)

onMounted(() => {
  void subcorporaStore.init()
})

onBeforeUnmount(() => {
  runToken += 1
  runController?.abort()
  analysisJobs.clearScope('ngrams')
  analysisJobs.clearScope('ngrams_diff')
})
</script>

<template>
  <div class="ngrams-tab">
    <!-- Toolbar -->
    <AnalysisToolbar>
      <template #left>
        <div class="view-toggle" role="tablist" :aria-label="t('analysis.ngrams.mode')">
          <button
            :class="{ active: mode === 'frequency', 'operation-focused': frequencyFocused }"
            :title="t('analysis.ngrams.frequencyList')"
            @click="mode = 'frequency'"
          >
            <BarChart3 class="w-4 h-4" />
            <span class="hidden md:inline">{{ t('analysis.ngrams.frequency') }}</span>
          </button>
          <button
            :class="{ active: mode === 'diff', 'operation-focused': diffFocused }"
            :title="t('analysis.ngrams.subcorpusContrast')"
            @click="mode = 'diff'"
          >
            <ArrowLeftRight class="w-4 h-4" />
            <span class="hidden md:inline">{{ t('analysis.ngrams.contrast') }}</span>
          </button>
        </div>

        <div
          v-if="mode === 'frequency'"
          class="scope-pill"
          :class="{ active: docsetStore.hasActiveDocset, stale: !researchScope.ok || docsetStore.activeScopeStale }"
          :title="researchScope.message ?? researchScope.evidence.warning"
        >
          {{ scopeText }}
        </div>

        <label class="toolbar-select">
          <span>{{ t('analysis.ngrams.ngramLabel') }}</span>
          <select v-model="ngramSize" @change="refresh">
            <option v-for="n in NGRAM_SIZES" :key="n" :value="n">
              {{ n === 2 ? t('analysis.ngrams.bigrams') : n === 3 ? t('analysis.ngrams.trigrams') : t('analysis.ngrams.sizeN', { n }) }}
            </option>
          </select>
        </label>

        <label class="toolbar-input">
          <span>{{ t('analysis.ngrams.minFreqLabel') }}</span>
          <input v-model.number="minFreq" type="number" min="1" @change="refresh" />
        </label>

        <label v-if="mode === 'frequency'" class="toolbar-select">
          <span>{{ t('analysis.ngrams.sortLabel') }}</span>
          <select v-model="sortBy">
            <option value="frequency">{{ t('analysis.ngrams.frequency') }}</option>
            <option value="relative">{{ t('analysis.ngrams.perMillionShort') }}</option>
          </select>
        </label>
        <MeasureInfo
          v-if="mode === 'frequency'"
          :measure-key="sortBy === 'relative' ? 'per_million' : 'frequency'"
          :method="ngramMethod"
        />

        <template v-if="mode === 'diff'">
          <label class="toolbar-select">
            <span>{{ t('analysis.ngrams.targetLabel') }}</span>
            <select v-model="targetSubId">
              <option :value="null" disabled>{{ t('analysis.ngrams.pickSubcorpus') }}</option>
              <option v-for="s in parkedSubcorpora" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </label>
          <label class="toolbar-select">
            <span>{{ t('analysis.ngrams.referenceLabel') }}</span>
            <select v-model="referenceSubId">
              <option :value="null" disabled>{{ t('analysis.ngrams.pickSubcorpus') }}</option>
              <option v-for="s in parkedSubcorpora" :key="s.id" :value="s.id">{{ s.name }}</option>
            </select>
          </label>
        </template>
      </template>

      <template #right>
        <JobStatusPill
          v-if="jobSnapshot && (jobSnapshot.status === 'running' || jobSnapshot.status === 'queued')"
          :status="jobSnapshot.status"
          :progress="jobSnapshot.progress"
          :message="jobSnapshot.message"
          :canCancel="analysisJobs.canCancelJobs"
          @cancel="cancelJob"
        />
        <SaveAnalysisButton
          v-if="mode === 'frequency'"
          type="ngrams"
          :defaultName="t('analysis.ngrams.defaultName', { query: queryStore.term || t('analysis.ngrams.noQuery') })"
          :corpus="docsetStore.activeCorpus"
          :docset="docsetSnapshot"
          :queryTerm="queryStore.term"
          :params="{ ngramSize, minFreq, sortBy }"
          :result="data.length ? { rows: data } : undefined"
          :resultMeta="data.length ? {
            n: ngramSize,
            minFreq,
            sortBy,
            corpus: docsetStore.activeCorpus,
            docsetId: docsetStore.activeDocsetId ?? null,
            docCount: effectiveDocCount,
            tokenCount: effectiveTokenCount,
            resultState: resultState ? { ...resultState } : null,
            generatedAt: Date.now(),
          } : undefined"
        />
        <Button variant="ghost" size="sm" :icon="RefreshCw" :loading="isLoading" @click="refresh">
          {{ mode === 'frequency' ? t('analysis.ngrams.refresh') : t('analysis.ngrams.compute') }}
        </Button>
        <Button variant="ghost" size="sm" :icon="Download" @click="exportCSV">
          CSV
        </Button>
      </template>
    </AnalysisToolbar>

    <CapabilityBoundaryPanel
      capability-id="analysis.ngrams"
      :method="ngramMethod"
      class="ngram-method"
    />

    <!-- Table -->
    <div class="table-container">
      <div
        v-if="resultStateSummary && !isLoading && !jobError"
        class="result-state-banner"
        :class="{ 'is-truncated': resultState?.truncated }"
        role="status"
      >
        <AlertTriangle v-if="resultState?.truncated" class="w-4 h-4" />
        <Info v-else class="w-4 h-4" />
        <span>{{ resultStateSummary }}</span>
      </div>

      <!-- Frequency mode -->
      <table
        v-if="mode === 'frequency' && !isLoading && !jobError && data.length > 0"
        class="ngram-table"
      >
        <thead>
          <tr>
            <th class="col-rank">#</th>
            <th class="col-ngram">{{ t('analysis.ngrams.ngram') }}</th>
            <th class="col-freq">{{ t('analysis.ngrams.frequency') }}</th>
            <th class="col-relative">{{ t('analysis.ngrams.perMillionTokens') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, idx) in sortedData"
            :key="row.ngram"
            class="row-link"
            tabindex="0"
            :title="t('analysis.ngrams.openRow')"
            :data-testid="`ngram-row-${idx}`"
            @click="openRowConcordance(row)"
            @keydown.enter="openRowConcordance(row)"
          >
            <td class="col-rank">{{ idx + 1 }}</td>
            <td class="col-ngram">{{ row.ngram }}</td>
            <td class="col-freq">{{ formatNumber(row.frequency) }}</td>
            <td class="col-relative">
              {{ formatDecimal(perMillion(row.relative), 2) }}
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Diff mode -->
      <table
        v-else-if="mode === 'diff' && !isLoading && !jobError && diffRows.length > 0"
        class="ngram-table"
      >
        <thead>
          <tr>
            <th class="col-rank">#</th>
            <th class="col-ngram">{{ t('analysis.ngrams.ngram') }}</th>
            <th class="col-freq">{{ t('analysis.ngrams.targetF') }}</th>
            <th class="col-freq">{{ t('analysis.ngrams.targetPm') }}</th>
            <th class="col-freq">{{ t('analysis.ngrams.refF') }}</th>
            <th class="col-freq">{{ t('analysis.ngrams.refPm') }}</th>
            <th class="col-freq">Δ pM</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(row, idx) in diffRows" :key="row.ngram">
            <td class="col-rank">{{ idx + 1 }}</td>
            <td class="col-ngram">{{ row.ngram }}</td>
            <td class="col-freq">{{ formatNumber(row.targetFreq) }}</td>
            <td class="col-freq">{{ formatDecimal(row.targetPerMillion, 2) }}</td>
            <td class="col-freq">{{ formatNumber(row.referenceFreq) }}</td>
            <td class="col-freq">{{ formatDecimal(row.referencePerMillion, 2) }}</td>
            <td class="col-freq col-diff" :class="row.diffPerMillion >= 0 ? 'positive' : 'negative'">
              {{ row.diffPerMillion >= 0 ? '+' : '' }}{{ formatDecimal(row.diffPerMillion, 2) }}
            </td>
          </tr>
        </tbody>
      </table>

      <!-- Loading -->
      <div v-else-if="isLoading" class="loading-state">
        <Skeleton v-for="i in 10" :key="i" height="2.5rem" class="mb-2" />
      </div>

      <!-- Error State -->
      <EmptyState
        v-else-if="jobError"
        :icon="Hash"
        :title="t('analysis.ngrams.failed')"
        :description="jobError"
        :action-label="t('analysis.ngrams.restart')"
        :secondary-action-label="t('analysis.shared.checkSubcorpus')"
        size="sm"
        @action="refresh"
        @secondaryAction="uiStore.openSubcorpus()"
      />

      <!-- Diff empty states -->
      <EmptyState
        v-else-if="mode === 'diff' && parkedSubcorpora.length < 2"
        :icon="ArrowLeftRight"
        :title="t('analysis.ngrams.tooFewTitle')"
        :description="t('analysis.ngrams.tooFewDescription')"
        :action-label="t('analysis.ngrams.createSubcorpus')"
        size="sm"
        @action="uiStore.openSubcorpus()"
      />
      <EmptyState
        v-else-if="mode === 'diff'"
        :icon="ArrowLeftRight"
        :title="t('analysis.ngrams.compareTitle')"
        :description="t('analysis.ngrams.compareDescription')"
        :action-label="t('analysis.ngrams.compute')"
        size="sm"
        @action="runDiff"
      />

      <!-- Frequency empty state -->
      <EmptyState
        v-else
        :icon="Hash"
        :title="t('analysis.ngrams.emptyTitle')"
        :description="t('analysis.ngrams.emptyDescription')"
        :action-label="t('analysis.ngrams.refresh')"
        size="sm"
        @action="loadData"
      />

    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.ngrams-tab {
  /* At least as high as the tab, grows with its content: the tab area
     scrolls (App.vue .tab-content). */
  @apply flex flex-col min-h-full;
}

.ngram-method {
  @apply mt-3;
}

.view-toggle {
  @apply flex rounded-lg overflow-hidden;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.view-toggle button {
  @apply flex items-center gap-1 px-2 md:px-3 py-1.5 text-sm;
  @apply transition-colors;
}

.view-toggle button.active {
  @apply bg-primary-500 text-white;
}

.view-toggle button.operation-focused {
  @apply ring-2 ring-amber-300 ring-offset-2 ring-offset-white;
  @apply dark:ring-amber-500/80 dark:ring-offset-neutral-950;
}

.view-toggle button:not(.active) {
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
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

.toolbar-select,
.toolbar-input {
  @apply flex items-center gap-2;
  @apply text-sm text-neutral-600 dark:text-neutral-400;
}

.toolbar-select select,
.toolbar-input input {
  @apply px-2 py-1.5 rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm;
}

.toolbar-select select {
  @apply max-w-44 truncate;
}

.toolbar-input input {
  @apply w-20 text-center;
}

.table-container {
  /* Result table: its natural height, at most the visible tab (100cqh).
     Toolbars above it scroll away with the tab. */
  flex: 1 0 auto;
  max-height: 100cqh;
  /* No top padding: the sticky header row closes flush with the tab. */
  @apply overflow-auto;
  @apply px-4 pb-4;
}

.result-state-banner {
  @apply mb-3 flex items-center gap-2 rounded-lg border px-3 py-2 text-sm;
  @apply border-sky-200 bg-sky-50 text-sky-800;
  @apply dark:border-sky-800 dark:bg-sky-950/30 dark:text-sky-200;
}

.result-state-banner.is-truncated {
  @apply border-amber-200 bg-amber-50 text-amber-800;
  @apply dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200;
}

.ngram-table {
  @apply w-full border-collapse;
}

.ngram-table th,
.ngram-table td {
  @apply px-4 py-3;
  @apply text-left;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.ngram-table th {
  @apply text-xs font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply bg-neutral-50 dark:bg-neutral-800/50;
  @apply sticky top-0;
}

.ngram-table tbody tr:hover {
  @apply bg-neutral-50 dark:bg-neutral-800/50;
}

.ngram-table tbody tr.row-link {
  @apply cursor-pointer;
}

.col-rank {
  @apply w-12 text-center text-neutral-500 dark:text-neutral-400;
}

.col-ngram {
  @apply font-mono;
}

.col-freq,
.col-relative {
  @apply w-24 text-right font-mono;
}

.col-diff.positive {
  @apply text-success-600 dark:text-success-400;
}

.col-diff.negative {
  @apply text-error-600 dark:text-error-400;
}

.loading-state {
  @apply space-y-2;
}
</style>
