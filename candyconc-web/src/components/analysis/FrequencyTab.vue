<script setup lang="ts">
/**
 * FrequencyTab - Word frequency analysis with table and chart views
 */
import { ref, computed, watch, onMounted } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import {
  type FrequencyParams,
  type FrequencyResult,
} from '@/api/client'
import { buildCsv, downloadCsv } from '@/utils/csv'
import { useActions, useDispatch, useMobileDetection } from '@/composables'
import { frequencyRowQuery } from '@/utils/backPathQuery'
import { useAnalysisJobsStore, useDocsetStore, useAnalysisPresetsStore, useQueryStore, useUiStore } from '@/stores'
import { FREQUENCY_OPERATIONS, useFrequencyOperations } from '@/composables/useFrequencyOperations'
import { useSettingsStore } from '@/stores/settings'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { Download, SortAsc, SortDesc, BarChart3, List, AlertTriangle } from 'lucide-vue-next'
import BarChart from './charts/BarChart.vue'
import MeasureInfo from '@/components/ui/MeasureInfo.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import SaveAnalysisButton from '@/components/analysis/SaveAnalysisButton.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import { ensureUsableResearchScope, executionScopeForApi, researchScopeCsvMeta } from '@/lib/researchScope'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const { isMobile } = useMobileDetection()
const settingsStore = useSettingsStore()
const docsetStore = useDocsetStore()
const presetsStore = useAnalysisPresetsStore()
const queryStore = useQueryStore()
const { dispatch } = useDispatch()
const uiStore = useUiStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const analysisJobs = useAnalysisJobsStore()
const queryClient = useQueryClient()
const {
  canStartFrequencyJob,
  canCreateFrequencyJob,
  createFrequencyJob,
  loadFrequencyResult,
  rowsToFrequencyResult,
} = useFrequencyOperations()

// State
const sortBy = ref<'freq' | 'alpha'>('freq')
const sortDir = ref<'asc' | 'desc'>('desc')
const groupBy = ref<'word' | 'lemma' | 'pos'>('word')
const posPrefix = ref('')
const limit = ref(100)
const viewMode = ref<'table' | 'chart'>('table')
const researchScope = computed(() =>
  ensureUsableResearchScope(docsetStore, { operation: t('analysis.frequency.operation') })
)

const effectiveTokenCount = computed(() => {
  if (docsetStore.hasActiveDocset) {
    return docsetStore.stats.tokenCount
  }
  return corpusCapabilities.activeCorpusTokenCount || (
    settingsStore.systemInfoIsFresh ? settingsStore.systemInfo.tokenCount : 0
  )
})

// Mirror effectiveTokenCount for the doc count: the docset-only stat reads 0 on
// the whole corpus, so fall back to the corpus-level doc_count from capabilities
// (one source of truth) when no docset is active.
const effectiveDocCount = computed(() => {
  if (docsetStore.hasActiveDocset) {
    return docsetStore.stats.docCount
  }
  return corpusCapabilities.activeCorpusDocCount
})

const scopeText = computed(() => {
  if (!docsetStore.hasActiveDocset) return t('analysis.shared.wholeCorpus')
  if (!researchScope.value.ok) return researchScope.value.evidence.label
  const docs = formatNumber(docsetStore.stats.docCount)
  const tokens = formatNumber(docsetStore.stats.tokenCount)
  return t('analysis.shared.docsTokens', { docs, tokens })
})

const frequencyGroupOptions = computed(() => corpusCapabilities.frequencyGroups)
const currentGroupAvailable = computed(() => corpusCapabilities.canUseFrequencyGroup(groupBy.value))
const canUsePosPrefixFilter = computed(() =>
  groupBy.value === 'word' && corpusCapabilities.canUseTokenAttribute('pos')
)
const normalizedPosPrefix = computed(() =>
  canUsePosPrefixFilter.value ? posPrefix.value.trim() : ''
)
const frequencyCapabilityNote = computed(() => {
  const labels = frequencyGroupOptions.value.map((option) => option.label).join(', ')
  const groups = t('analysis.frequency.groupsNote', { labels: labels || t('analysis.frequency.wordForm') })
  return corpusCapabilities.canUseTokenAttribute('pos')
    ? `${groups} ${t('analysis.frequency.posPrefixAvailable')}`
    : groups
})

function coerceAvailableGroupBy(next: 'word' | 'lemma' | 'pos' | undefined): 'word' | 'lemma' | 'pos' {
  if (next && corpusCapabilities.canUseFrequencyGroup(next)) return next
  if (next && next !== 'word') {
    uiStore.showToast(t('analysis.frequency.savedGroupUnavailable'), 'info', 2500)
  }
  return 'word'
}

// Query
const queryParams = computed<FrequencyParams>(() => ({
  groupBy: groupBy.value,
  posPrefix: normalizedPosPrefix.value || undefined,
  sortBy: sortBy.value,
  limit: limit.value,
  tokenCount: effectiveTokenCount.value,
  corpus: docsetStore.activeCorpus,
  docsetId: researchScope.value.docsetId,
}))

const canUseFrequencyJobEndpoint = computed(() =>
  canCreateFrequencyJob(queryParams.value) &&
  canStartFrequencyJob.value &&
  analysisJobs.canRefreshJobs &&
  analysisJobs.canLoadJobRows
)
const queryKey = computed(() => ['frequency', queryParams.value, canUseFrequencyJobEndpoint.value])
const frequencyJobSnapshot = computed(() => analysisJobs.activeSnapshot('frequency'))
const activeFrequencyJobId = computed(() => analysisJobs.activeJobId('frequency'))

async function runFrequencyJob(params: FrequencyParams, signal?: AbortSignal): Promise<FrequencyResult> {
  const rowsResponse = await analysisJobs.runJobRows<{ word: string; f: number }>({
    scope: 'frequency',
    kind: 'frequency_list',
    corpus: params.corpus,
    signal,
    rowsLimit: Math.max(params.limit ?? 200, 1),
    queuedMessage: t('analysis.frequency.jobStarted'),
    productOperation: {
      operationId: FREQUENCY_OPERATIONS.job,
      surfaceId: 'analysis.frequency',
      label: t('analysis.operations.frequencyJob'),
      detail: params.groupBy ?? params.corpus ?? null,
    },
    start: () => createFrequencyJob(params, {
      target: params.corpus ? t('analysis.shared.corpusNamed', { name: params.corpus }) : t('analysis.shared.activeCorpus'),
      impact: t('analysis.frequency.jobImpact'),
      contextualConfirmation: {
        surfaceId: 'analysis.frequency',
        interaction: 'frequency.tab.job',
        source: 'native_surface',
      },
    }),
  })
  return rowsToFrequencyResult(rowsResponse, params)
}

const { data, isLoading, error, refetch } = useQuery({
  queryKey,
  queryFn: ({ signal }) => {
    if (!researchScope.value.ok) throw new Error(researchScope.value.message)
    if (canUseFrequencyJobEndpoint.value) {
      return runFrequencyJob(queryParams.value, signal)
    }
    analysisJobs.clearScope('frequency')
    return loadFrequencyResult(queryParams.value, { signal })
  },
  staleTime: 5 * 60 * 1000 // 5 min cache
})
const restoredData = ref<Array<{ item: string; frequency: number; relative: number }> | null>(null)
const frequencyMeta = computed<FrequencyResult | null>(() => data.value ?? null)
const effectiveError = computed(() => {
  const err = error.value as Error | null
  if (!err) return null
  if ('name' in err && err.name === 'AbortError') return null
  return err
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
        query: queryStore.term,
      }
    : null
)

// Sorted Data
const effectiveData = computed(() => restoredData.value ?? data.value?.rows ?? [])

/**
 * Row to concordance: the KWIC of exactly the tokens the row counts, in the
 * same scope, with the same case folding and POS prefix. The KWIC total then
 * equals the row frequency (checked on sotu_en and dta_de).
 */
async function openRowConcordance(row: { item: string }) {
  if (!row.item.trim()) return
  const term = frequencyRowQuery({
    item: row.item,
    groupBy: groupBy.value,
    posPrefix: normalizedPosPrefix.value || null,
    caseFolded: groupBy.value !== 'pos',
  })
  const docsetId = researchScope.value.docsetId ?? undefined
  const result = await dispatch({
    type: 'query/execute',
    payload: { term, contextSize: queryStore.contextSize, ...(docsetId ? { docsetId } : {}) },
  })
  if (result.success) await dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
}

const groupByLabel = computed(() => {
  if (groupBy.value === 'lemma') return t('analysis.frequency.lemma')
  if (groupBy.value === 'pos') return t('analysis.frequency.posTag')
  return frequencyMeta.value?.casePolicy === 'case_insensitive (lowercase)'
    ? t('analysis.frequency.wordFormFolded')
    : t('analysis.frequency.wordForm')
})

const frequencyTruthNote = computed(() => {
  const meta = frequencyMeta.value
  const parts = [t('analysis.frequency.truth.basis', { label: groupByLabel.value })]
  if (meta?.posPrefix || normalizedPosPrefix.value) {
    parts.push(t('analysis.frequency.truth.posPrefix', { prefix: meta?.posPrefix ?? normalizedPosPrefix.value }))
  }
  if (meta?.casePolicy === 'case_insensitive (lowercase)') {
    parts.push(t('analysis.frequency.truth.caseFolded'))
  } else if (meta?.casePolicy) {
    parts.push(t('analysis.frequency.truth.casePolicy', { policy: meta.casePolicy }))
  }
  if (meta?.filteredTokenPolicy) {
    parts.push(t('analysis.frequency.truth.tokenPolicy', { policy: meta.filteredTokenPolicy }))
  }
  if (meta?.truncated && meta.totalCandidates) {
    parts.push(t('analysis.frequency.truth.shown', { shown: formatNumber(effectiveData.value.length), total: formatNumber(meta.totalCandidates) }))
  }
  if (sortBy.value === 'alpha' && meta?.truncated) {
    parts.push(t('analysis.frequency.truth.alphaTopN'))
  }
  return parts.join(' · ')
})
const frequencyBoundaryNotes = computed(() =>
  [frequencyTruthNote.value, frequencyCapabilityNote.value].filter(Boolean)
)

const sortedData = computed(() => {
  if (!effectiveData.value) return []
  const rows = [...effectiveData.value]

  if (sortDir.value === 'asc') {
    if (sortBy.value === 'freq') {
      rows.sort((a, b) => a.frequency - b.frequency)
    } else {
      rows.sort((a, b) => a.item.localeCompare(b.item))
    }
  } else {
    if (sortBy.value === 'freq') {
      rows.sort((a, b) => b.frequency - a.frequency)
    } else {
      rows.sort((a, b) => b.item.localeCompare(a.item))
    }
  }
  return rows
})

// Transform data for chart
const chartData = computed(() =>
  sortedData.value.slice(0, 20).map(r => ({
    token: r.item,
    freq: r.frequency
  }))
)

// Max frequency for bar width calculation
const maxFreq = computed(() => sortedData.value[0]?.frequency || 1)

// Toggle sort
function toggleSort(column: 'freq' | 'alpha') {
  if (sortBy.value === column) {
    sortDir.value = sortDir.value === 'desc' ? 'asc' : 'desc'
  } else {
    sortBy.value = column
    sortDir.value = column === 'freq' ? 'desc' : 'asc'
  }
}

// Export CSV
function exportCSV() {
  const filters = docsetStore.filters
  const filterLines = [
    `# Filter.prompting_method: ${filters.prompting_method.length ? filters.prompting_method.join(' | ') : 'all'}`,
    `# Filter.model: ${filters.model.length ? filters.model.join(' | ') : 'all'}`,
    `# Filter.register: ${filters.register.length ? filters.register.join(' | ') : 'all'}`,
    `# Filter.source: ${filters.source.length ? filters.source.join(' | ') : 'all'}`,
    `# IncludeAI: ${docsetStore.includeAi}`,
    `# IncludeHuman: ${docsetStore.includeHuman}`,
  ]
  const formulaLines = [
    '# Formulae:',
    '# Relative = frequency / tokenCount',
  ]
  const meta = [
    '# CandyConc Export',
    '# Analysis: Frequency',
    `# GroupBy: ${groupBy.value}`,
    `# PosPrefix: ${normalizedPosPrefix.value || 'none'}`,
    `# SortBy: ${sortBy.value}`,
    `# SortDir: ${sortDir.value}`,
    `# Limit: ${limit.value}`,
    `# RowLimit: ${frequencyMeta.value?.rowLimit ?? limit.value}`,
    `# TotalCandidates: ${frequencyMeta.value?.totalCandidates ?? sortedData.value.length}`,
    `# Truncated: ${frequencyMeta.value?.truncated ? 'true' : 'false'}`,
    `# Basis: ${frequencyMeta.value?.basis ?? 'analyst_token_frequency'}`,
    `# CasePolicy: ${frequencyMeta.value?.casePolicy ?? t('analysis.frequency.notReported')}`,
    `# TokenPolicy: ${frequencyMeta.value?.filteredTokenPolicy ?? t('analysis.frequency.defaultTokenPolicy')}`,
    `# Corpus: ${docsetStore.activeCorpus}`,
    `# Docset: ${docsetStore.activeDocsetId ?? 'all'}`,
    // FREQ-CSV-DOCCOUNT: like Tokens below, emit the effective scope's doc count
    // (corpus total when no docset) instead of the docset-only stat that reads 0
    // on the whole corpus.
    `# Docs: ${effectiveDocCount.value}`,
    // FREQ-CSV-TOKENCOUNT: emit the SAME denominator the `relative` column was
    // divided by (effectiveTokenCount = corpus total when no docset), not the
    // docset-only stat that reads 0 on the whole corpus.
    `# Tokens: ${effectiveTokenCount.value}`,
    `# Query: ${queryStore.term || 'n/a'}`,
    ...researchScopeCsvMeta({
      ...docsetStore,
      stats: {
        ...docsetStore.stats,
        docCount: effectiveDocCount.value,
        tokenCount: effectiveTokenCount.value,
      },
    }),
    ...filterLines,
    ...formulaLines,
    `# Exported: ${new Date().toISOString()}`,
  ]
  const csv = buildCsv({
    meta,
    headers: ['item', 'frequency', 'relative'],
    rows: sortedData.value.map((r) => [r.item, r.frequency, r.relative.toFixed(6)]),
  })
  downloadCsv(csv, 'frequency.csv')
}

function cancelFrequency() {
  if (!isLoading.value) return
  const jobId = activeFrequencyJobId.value
  if (jobId) {
    void analysisJobs.cancelScope('frequency').catch((err) => {
      console.warn('Frequency job could not be cancelled', err)
    })
  }
  void queryClient.cancelQueries({ queryKey: queryKey.value })
  uiStore.showToast(t('analysis.frequency.cancelled'), 'info')
}

// Register action handler for Copilot
useActions({
  'analysis/frequency': async () => {
    const params = queryParams.value
    const result = await refetch()
    if (result.error) {
      return {
        success: false,
        error: result.error instanceof Error ? result.error.message : t('analysis.frequency.failed'),
      }
    }
    return {
      success: true,
      data: result.data ?? data.value,
      executionScope: executionScopeForApi(docsetStore, params.corpus ?? docsetStore.activeCorpus, params.docsetId),
    }
  }
})

// Apply saved preset
watch(
  () => presetsStore.pendingPreset,
  async (preset) => {
    if (!preset || preset.type !== 'frequency') return
    let shouldRefetch = true
    const params = preset.params as {
      groupBy?: 'word' | 'lemma' | 'pos'
      posPrefix?: string
      sortBy?: 'freq' | 'alpha'
      sortDir?: 'asc' | 'desc'
      limit?: number
      viewMode?: 'table' | 'chart'
    }
    if (params.groupBy) groupBy.value = coerceAvailableGroupBy(params.groupBy)
    posPrefix.value = params.posPrefix ?? ''
    if (params.sortBy) sortBy.value = params.sortBy
    if (params.sortDir) sortDir.value = params.sortDir
    if (params.limit) limit.value = params.limit
    if (params.viewMode) viewMode.value = params.viewMode
    presetsStore.setPending(null)
    if (preset.result && typeof preset.result === 'object') {
      const valid = await presetsStore.isResultValid(preset)
      if (valid) {
        const result = preset.result as any
        restoredData.value = (result.rows ?? []) as Array<{ item: string; frequency: number; relative: number }>
        shouldRefetch = false
      } else {
        uiStore.showToast(t('analysis.shared.staleSaved'), 'info', 2500)
      }
    }
    if (shouldRefetch) {
      await refetch()
    }
  }
)

watch(
  () => data.value,
  (result) => {
    if (result?.rows?.length) restoredData.value = null
  }
)

watch(frequencyGroupOptions, () => {
  if (currentGroupAvailable.value) return
  groupBy.value = coerceAvailableGroupBy(groupBy.value)
})

watch(groupBy, (value) => {
  if (corpusCapabilities.canUseFrequencyGroup(value)) return
  groupBy.value = coerceAvailableGroupBy(value)
})

watch(canUsePosPrefixFilter, (enabled) => {
  if (!enabled) posPrefix.value = ''
})

onMounted(() => {
  if (!corpusCapabilities.loaded) void corpusCapabilities.fetchCorpora()
})
</script>

<template>
  <div class="frequency-tab" data-testid="frequency-tab">
    <!-- Toolbar -->
    <AnalysisToolbar>
      <template #left>
        <div
          class="scope-pill"
          :class="{ active: docsetStore.hasActiveDocset, stale: !researchScope.ok || docsetStore.activeScopeStale }"
          :title="researchScope.message ?? researchScope.evidence.warning"
        >
          {{ scopeText }}
        </div>

        <select v-model="groupBy" class="select">
          <option
            v-for="option in frequencyGroupOptions"
            :key="option.value"
            :value="option.value"
          >
            {{ option.label }}
          </option>
        </select>
        <MeasureInfo measure-key="frequency" :fallback-label="t('analysis.frequency.frequency')" />

        <label
          v-if="canUsePosPrefixFilter"
          class="pos-prefix-label"
          :title="t('analysis.frequency.posPrefixTitle')"
        >
          <span class="hidden md:inline">POS:</span>
          <input
            v-model.trim="posPrefix"
            class="input input-sm pos-prefix-input"
            data-testid="frequency-pos-prefix"
            placeholder="N"
            :aria-label="t('analysis.frequency.posPrefixAria')"
          />
        </label>

        <label class="limit-label">
          <span class="hidden md:inline">Limit:</span>
          <select v-model="limit" class="select select-sm">
            <option :value="50">50</option>
            <option :value="100">100</option>
            <option :value="250">250</option>
            <option :value="500">500</option>
          </select>
        </label>
      </template>

      <template #right>
        <JobStatusPill
          v-if="frequencyJobSnapshot && isLoading"
          :status="frequencyJobSnapshot.status"
          :progress="frequencyJobSnapshot.progress"
          :message="frequencyJobSnapshot.message"
          :canCancel="analysisJobs.canCancelJobs"
          @cancel="cancelFrequency"
        />
        <JobStatusPill
          v-else-if="isLoading"
          status="running"
          :progress="0"
          :message="t('analysis.shared.loading')"
          :canCancel="true"
          @cancel="cancelFrequency"
        />
        <div class="view-toggle">
          <button
            :class="{ active: viewMode === 'table' }"
            @click="viewMode = 'table'"
            :title="t('analysis.frequency.tableView')"
          >
            <List class="w-4 h-4" />
            <span class="hidden md:inline">{{ t('analysis.frequency.table') }}</span>
          </button>
          <button
            :class="{ active: viewMode === 'chart' }"
            @click="viewMode = 'chart'"
            :title="t('analysis.frequency.chartView')"
          >
            <BarChart3 class="w-4 h-4" />
            <span class="hidden md:inline">{{ t('analysis.frequency.chart') }}</span>
          </button>
        </div>

        <SaveAnalysisButton
          type="frequency"
          :defaultName="t('analysis.frequency.defaultName', { scope: docsetStore.hasActiveDocset ? t('analysis.shared.subcorpus') : t('analysis.shared.wholeCorpus') })"
          :corpus="docsetStore.activeCorpus"
          :docset="docsetSnapshot"
          :queryTerm="queryStore.term"
          :params="{ groupBy, posPrefix: normalizedPosPrefix || undefined, sortBy, sortDir, limit, viewMode }"
          :result="effectiveData.length ? { rows: effectiveData } : undefined"
          :resultMeta="effectiveData.length ? {
            groupBy,
            posPrefix: normalizedPosPrefix || undefined,
            sortBy,
            sortDir,
            limit,
            corpus: docsetStore.activeCorpus,
            docsetId: docsetStore.activeDocsetId ?? null,
            docCount: docsetStore.stats.docCount,
            tokenCount: docsetStore.stats.tokenCount,
            rowLimit: frequencyMeta?.rowLimit ?? limit,
            totalCandidates: frequencyMeta?.totalCandidates ?? effectiveData.length,
            truncated: frequencyMeta?.truncated ?? false,
            basis: frequencyMeta?.basis ?? 'analyst_token_frequency',
            casePolicy: frequencyMeta?.casePolicy ?? t('analysis.frequency.notReported'),
            filteredTokenPolicy: frequencyMeta?.filteredTokenPolicy,
            generatedAt: Date.now(),
          } : undefined"
        />
        <button class="btn-export" @click="exportCSV" :disabled="!sortedData.length">
          <Download class="w-4 h-4" />
          <span class="hidden md:inline">CSV</span>
        </button>
      </template>
    </AnalysisToolbar>

    <!-- The truth + capability notes render once inside the boundary panel's
         "Ergebnis-Evidence" block (via :runtime-notes). They used to ALSO render
         as standalone divs here, so every note appeared twice. -->
    <CapabilityBoundaryPanel
      capability-id="analysis.frequency"
      :runtime-notes="frequencyBoundaryNotes"
      compact
    />

    <!-- Loading -->
    <div v-if="isLoading" class="loading-container">
      <Skeleton v-for="i in 10" :key="i" height="48px" class="mb-2" />
    </div>

    <!-- Error -->
    <EmptyState
      v-else-if="effectiveError"
      :icon="AlertTriangle"
      :title="t('analysis.shared.loadError')"
      :description="effectiveError.message"
      :action-label="t('analysis.shared.retry')"
      :secondary-action-label="t('analysis.shared.checkSubcorpus')"
      @action="() => refetch()"
      @secondaryAction="uiStore.openSubcorpus()"
      size="sm"
    />

    <!-- Empty State -->
    <EmptyState
      v-else-if="!sortedData.length"
      :icon="BarChart3"
      :title="t('analysis.frequency.emptyTitle')"
      :description="t('analysis.frequency.emptyDescription')"
      :action-label="t('analysis.shared.recompute')"
      @action="() => refetch()"
      size="sm"
    />

    <!-- Chart View -->
    <div v-else-if="viewMode === 'chart'" class="chart-container">
      <BarChart :data="chartData" :height="isMobile ? 300 : 400" />
    </div>

    <!-- Table View -->
    <div v-else class="table-container">
      <table class="freq-table" data-testid="frequency-table">
        <thead>
          <tr>
            <th class="rank">#</th>
            <th class="token sortable" @click="toggleSort('alpha')">
              <span>{{ groupByLabel }}</span>
              <SortAsc v-if="sortBy === 'alpha' && sortDir === 'asc'" class="sort-icon" />
              <SortDesc v-if="sortBy === 'alpha' && sortDir === 'desc'" class="sort-icon" />
            </th>
            <th class="freq sortable" @click="toggleSort('freq')">
              <span>{{ t('analysis.frequency.frequency') }}</span>
              <SortAsc v-if="sortBy === 'freq' && sortDir === 'asc'" class="sort-icon" />
              <SortDesc v-if="sortBy === 'freq' && sortDir === 'desc'" class="sort-icon" />
            </th>
            <th v-if="!isMobile" class="bar">{{ t('analysis.frequency.distribution') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="(row, idx) in sortedData"
            :key="row.item"
            :data-testid="`frequency-row-${idx}`"
            class="row-link"
            tabindex="0"
            :title="t('analysis.frequency.openRow')"
            @click="openRowConcordance(row)"
            @keydown.enter="openRowConcordance(row)"
          >
            <td class="rank">{{ idx + 1 }}</td>
            <td class="token" data-testid="frequency-row-item">{{ row.item }}</td>
            <td class="freq" data-testid="frequency-row-count">{{ formatNumber(row.frequency) }}</td>
            <td v-if="!isMobile" class="bar">
              <div class="bar-bg">
                <div
                  class="bar-fill"
                  :style="{ width: `${(row.frequency / maxFreq) * 100}%` }"
                />
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.row-link {
  @apply cursor-pointer;
}

.frequency-tab {
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

.select {
  @apply px-2 md:px-3 py-1.5 md:py-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply border-none text-sm;
  @apply focus:ring-2 focus:ring-primary-500;
}

.select-sm {
  @apply w-16 md:w-20;
}

.limit-label {
  @apply flex items-center gap-1 text-sm text-neutral-600 dark:text-neutral-400;
}

.pos-prefix-label {
  @apply flex items-center gap-1 text-sm text-neutral-600 dark:text-neutral-400;
}

.pos-prefix-input {
  @apply w-16 rounded-lg bg-neutral-100 px-2 py-1.5 text-sm uppercase;
  @apply dark:bg-neutral-800;
  @apply focus:ring-2 focus:ring-primary-500;
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

.view-toggle button:not(.active) {
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-800;
}

.btn-export {
  @apply flex items-center gap-1 md:gap-2 px-2 md:px-3 py-1.5 md:py-2;
  @apply rounded-lg bg-neutral-100 dark:bg-neutral-800;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply text-sm transition-colors;
}

.loading-container,
.error-container,
.empty-state {
  @apply flex-1 flex flex-col items-center justify-center p-4;
}

.btn-retry {
  @apply mt-4 px-4 py-2 rounded-lg;
  @apply bg-primary-500 text-white;
  @apply hover:bg-primary-600;
}

.chart-container {
  /* Results in the flow of the tab, which scrolls as a whole. */
  flex: 1 0 auto;
  @apply p-4;
}

.table-container {
  /* Result table: its natural height, at most the visible tab (100cqh).
     Toolbars above it scroll away with the tab. */
  flex: 1 0 auto;
  max-height: 100cqh;
  @apply overflow-auto;
}

.freq-table {
  @apply w-full text-sm;
}

.freq-table th {
  @apply sticky top-0 px-3 md:px-4 py-2 md:py-3 text-left;
  @apply bg-neutral-50 dark:bg-neutral-900;
  @apply font-medium;
  @apply border-b border-neutral-200 dark:border-neutral-800;
}

.freq-table th.sortable {
  @apply cursor-pointer select-none;
}

.freq-table th.sortable:hover {
  @apply bg-neutral-100 dark:bg-neutral-800;
}

.sort-icon {
  @apply inline-block w-4 h-4 ml-1 text-neutral-500;
}

.freq-table td {
  @apply px-3 md:px-4 py-2;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.rank {
  @apply w-12 md:w-16 text-neutral-500;
}

.token {
  @apply font-medium;
}

.freq {
  @apply w-20 md:w-24 text-right font-mono;
}

.bar {
  @apply w-32 md:w-40;
}

.bar-bg {
  @apply h-4 bg-neutral-100 dark:bg-neutral-800 rounded-full overflow-hidden;
}

.bar-fill {
  @apply h-full bg-primary-500 rounded-full transition-all;
}
</style>
