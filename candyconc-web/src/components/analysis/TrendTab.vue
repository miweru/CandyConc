<script setup lang="ts">
/**
 * TrendTab - Frequenzverlauf (Diachronie) einer Abfrage über ein
 * Metadaten-Datumsfeld (POST /analysis/trend).
 *
 * Rendert pro Periode die Rate pro Million Tokens mit Wilson-95%-CI als
 * Linienchart plus Ergebnistabelle; der Bucket 'undatiert' wird sichtbar
 * getrennt ausgewiesen und nie in die Zeitachse gemischt.
 */
import { computed, onMounted, ref, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { TrendingUp, RefreshCw, Download, AlertTriangle, CalendarOff } from 'lucide-vue-next'
import { getAnalysisTrend, type TrendGranularity, type TrendParams, type TrendPeriod, type TrendResult } from '@/api/client'
import { actionBus } from '@/actions/bus'
import { useQueryStore, useDocsetStore, useUiStore } from '@/stores'
import { buildCsv, downloadCsv } from '@/utils/csv'
import { formatDecimal, formatInterval } from '@/i18n/format'
import { extractApiDetail, genericApiError } from '@/utils/apiError'
import { ensureUsableResearchScope, researchScopeCsvMeta } from '@/lib/researchScope'
import LineChart, { type LineChartPoint } from './charts/LineChart.vue'
import EmptyState from '@/components/ui/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import JobStatusPill from '@/components/analysis/JobStatusPill.vue'
import AnalysisToolbar from '@/components/analysis/AnalysisToolbar.vue'
import CapabilityBoundaryPanel from '@/components/analysis/CapabilityBoundaryPanel.vue'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const queryStore = useQueryStore()
const docsetStore = useDocsetStore()
const uiStore = useUiStore()
const queryClient = useQueryClient()

const UNDATED_PERIOD = 'undatiert' // i18n-ignore: period key sent by the server
const undatedLabel = computed(() => t('analysis.trend.undatedLabel'))

function periodLabel(period: string): string {
  return period === UNDATED_PERIOD ? undatedLabel.value : period
}

// ---- Datumsfeld-Auswahl aus dem Meta-Schema --------------------------------

/** Namensheuristik für Felder, die wie ein Datum/Jahr aussehen. */
const DATE_NAME_RE = /(^|_)(date|datum|jahr|year|time|zeit|created|published|erschienen)/i

const metaFields = computed(() => docsetStore.metaFields)

const dateLikeFields = computed(() =>
  metaFields.value.filter(
    (field) => field.kind === 'date' || DATE_NAME_RE.test(field.name)
  )
)

const otherFields = computed(() =>
  metaFields.value.filter(
    (field) => !dateLikeFields.value.some((candidate) => candidate.name === field.name)
  )
)

const hasMetaFields = computed(() => metaFields.value.length > 0)
const hasDateLikeField = computed(() => dateLikeFields.value.length > 0)

const dateField = ref('')
const granularity = ref<TrendGranularity>('year')

onMounted(() => {
  void docsetStore.loadMetaSchema().then(() => {
    if (!dateField.value && dateLikeFields.value.length) {
      dateField.value = dateLikeFields.value[0]!.name
    }
  })
})

// ---- Scope -----------------------------------------------------------------

const researchScope = computed(() =>
  ensureUsableResearchScope(docsetStore, { operation: t('analysis.trend.operation') })
)

const scopeText = computed(() => {
  if (!docsetStore.hasActiveDocset) return t('analysis.shared.wholeCorpus')
  if (!researchScope.value.ok) return researchScope.value.evidence.label
  const docs = formatNumber(docsetStore.stats.docCount)
  const tokens = formatNumber(docsetStore.stats.tokenCount)
  return t('analysis.shared.docsTokens', { docs, tokens })
})

// ---- Abfrage ---------------------------------------------------------------

const trendParams = computed<TrendParams>(() => ({
  query: queryStore.term,
  dateField: dateField.value,
  granularity: granularity.value,
  corpus: docsetStore.activeCorpus,
  docsetId: researchScope.value.docsetId,
  periodValues: true,
}))

const queryKey = computed(() => ['analysis-trend', trendParams.value])
const queryEnabled = computed(() =>
  Boolean(queryStore.term) && Boolean(dateField.value)
)

const { data, isLoading, error, refetch } = useQuery<TrendResult>({
  queryKey,
  queryFn: ({ signal }) => {
    if (!researchScope.value.ok) throw new Error(researchScope.value.message)
    return getAnalysisTrend(trendParams.value, { signal })
  },
  enabled: queryEnabled,
  staleTime: 5 * 60 * 1000,
})

const effectiveError = computed(() => {
  const err = error.value as Error | null
  if (!err) return null
  if ('name' in err && err.name === 'AbortError') return null
  return err
})

const errorDescription = ref<string>(genericApiError())
watch(
  effectiveError,
  async (err) => {
    if (!err) {
      errorDescription.value = genericApiError()
      return
    }
    errorDescription.value = await extractApiDetail(err)
  },
  { immediate: true }
)

function cancelTrend() {
  if (!isLoading.value) return
  void queryClient.cancelQueries({ queryKey: queryKey.value })
  uiStore.showToast(t('analysis.trend.cancelled'), 'info')
}

// ---- Ableitungen -----------------------------------------------------------

const datedPeriods = computed(() =>
  (data.value?.periods ?? []).filter((row) => row.period !== UNDATED_PERIOD)
)

const undatedPeriod = computed(
  () => (data.value?.periods ?? []).find((row) => row.period === UNDATED_PERIOD) ?? null
)

/** Nur datierte Perioden gehen in die Zeitachse; 'undatiert' ist kein Zeitpunkt. */
const chartData = computed<LineChartPoint[]>(() =>
  datedPeriods.value.map((row) => ({
    label: row.period,
    value: row.perMillion,
    ciLow: row.ciLow,
    ciHigh: row.ciHigh,
    hits: row.hits,
    tokens: row.tokens,
  }))
)

const trendWarnings = computed(() => data.value?.warnings ?? [])

const trendBoundaryNotes = computed(() => {
  const result = data.value
  if (!result) return []
  const notes = [
    t('analysis.trend.noteDateField', { field: result.dateField }),
    t('analysis.trend.noteGranularity', { granularity: result.granularity === 'month' ? t('analysis.trend.month') : t('analysis.trend.year') }),
    t('analysis.trend.noteDatedPeriods', { count: formatNumber(datedPeriods.value.length) }, datedPeriods.value.length),
  ]
  if (undatedPeriod.value) {
    notes.push(
      t('analysis.trend.noteUndated', { bucket: undatedLabel.value, count: formatNumber(undatedPeriod.value.documents) }, undatedPeriod.value.documents)
    )
  }
  return notes
})

// ---- Rückweg in die Konkordanz ---------------------------------------------

/**
 * Period to concordance: the scope is narrowed to the documents whose date
 * field has one of the values of the period, and the same search runs there.
 * The trend counted the hits of the query in exactly these documents, so the
 * concordance count equals the period's hits (checked on sotu_en and dta_de
 * for every period of year, date and decade, with and without a scope).
 * The undated bucket has no values and no back path.
 */
function canOpenPeriod(row: TrendPeriod): boolean {
  return row.period !== UNDATED_PERIOD && Boolean(row.values?.length)
}

async function openPeriodConcordance(row: TrendPeriod) {
  const result = data.value
  if (!result || !canOpenPeriod(row)) return
  const query = queryStore.term
  if (!query) return
  const narrowed = await docsetStore.narrowScope(result.dateField, [...(row.values ?? [])])
  if (!narrowed) {
    uiStore.showToast(docsetStore.error ?? t('analysis.trend.backPathFailed'), 'warning')
    return
  }
  queryStore.setBackPathOrigin({
    kind: 'trend',
    term: query,
    query,
    field: result.dateField,
    period: row.period,
    granularity: result.granularity === 'month' ? 'month' : 'year',
    hits: row.hits,
  })
  const executed = await actionBus.dispatch({
    type: 'query/execute',
    payload: { term: query, contextSize: queryStore.contextSize, docsetId: docsetStore.activeDocsetId ?? undefined },
  })
  if (!executed.success) {
    queryStore.setBackPathOrigin(null)
    return
  }
  await actionBus.dispatch({ type: 'nav/switchTab', payload: { tab: 'kwic' } })
}

function openChartPoint(point: LineChartPoint) {
  const row = datedPeriods.value.find((candidate) => candidate.period === point.label)
  if (row) void openPeriodConcordance(row)
}

function formatCi(low: number, high: number): string {
  return formatInterval(low, high, 2)
}

// ---- CSV-Export ------------------------------------------------------------

function exportCSV() {
  const result = data.value
  if (!result) return
  const method = result.method ?? {}
  const meta = [
    '# CandyConc Export',
    `# Analysis: ${t('analysis.trend.csvAnalysis')}`,
    `# Query: ${result.query || 'n/a'}`,
    `# DateField: ${result.dateField}`,
    `# Granularity: ${result.granularity}`,
    `# Corpus: ${docsetStore.activeCorpus}`,
    `# Docset: ${docsetStore.activeDocsetId ?? 'all'}`,
    ...researchScopeCsvMeta(docsetStore),
    '# Formulae:',
    `# per_million: ${String(method.rate_definition ?? t('analysis.trend.csvRateDefinition'))}`,
    `# ci_method: ${String(method.ci_method ?? 'wilson_score')}`,
    `# ci_level: ${String(method.ci_level ?? 0.95)}`,
    `# undated_policy: ${String(method.undated_policy ?? t('analysis.trend.csvUndatedPolicy', { bucket: UNDATED_PERIOD }))}`,
    ...trendWarnings.value.map((warning) => `# Warning: ${warning}`),
    `# Exported: ${new Date().toISOString()}`,
  ]
  const csv = buildCsv({
    meta,
    headers: ['period', 'documents', 'hits', 'tokens', 'per_million', 'ci_low', 'ci_high'],
    rows: (result.periods ?? []).map((row) => [
      row.period,
      row.documents,
      row.hits,
      row.tokens,
      row.perMillion,
      row.ciLow,
      row.ciHigh,
    ]),
  })
  downloadCsv(csv, `trend_${queryStore.term || 'query'}_${result.dateField}.csv`)
}
</script>

<template>
  <div class="trend-tab">
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

        <label class="control-label">
          <span class="label-text">{{ t('analysis.trend.dateFieldLabel') }}</span>
          <select
            v-model="dateField"
            class="select"
            :aria-label="t('analysis.trend.dateField')"
            :disabled="!hasMetaFields"
          >
            <option value="" disabled>{{ t('analysis.trend.selectField') }}</option>
            <optgroup v-if="dateLikeFields.length" :label="t('analysis.trend.dateFields')">
              <option v-for="field in dateLikeFields" :key="field.name" :value="field.name">
                {{ field.name }}
              </option>
            </optgroup>
            <optgroup v-if="otherFields.length" :label="t('analysis.trend.otherFields')">
              <option v-for="field in otherFields" :key="field.name" :value="field.name">
                {{ field.name }}
              </option>
            </optgroup>
          </select>
        </label>

        <label class="control-label">
          <span class="label-text">{{ t('analysis.trend.granularityLabel') }}</span>
          <select v-model="granularity" class="select" :aria-label="t('analysis.trend.granularity')">
            <option value="year">{{ t('analysis.trend.year') }}</option>
            <option value="month">{{ t('analysis.trend.month') }}</option>
          </select>
        </label>
      </template>

      <template #right>
        <JobStatusPill
          v-if="isLoading"
          status="running"
          :progress="0"
          :message="t('analysis.shared.loading')"
          :canCancel="true"
          @cancel="cancelTrend"
        />
        <button
          class="btn-icon"
          :aria-label="t('analysis.trend.exportCsv')"
          :disabled="!data"
          @click="exportCSV"
        >
          <Download class="w-4 h-4" />
        </button>
        <button
          class="btn-icon"
          :aria-label="t('analysis.trend.refresh')"
          :disabled="isLoading || !queryEnabled"
          @click="() => refetch()"
        >
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': isLoading }" />
        </button>
      </template>
    </AnalysisToolbar>

    <!-- Kein Metadatenfeld: ehrlicher Leerzustand statt verstecktem Tab -->
    <EmptyState
      v-if="!hasMetaFields"
      :icon="CalendarOff"
      :title="t('analysis.trend.noMetaTitle')"
      :description="t('analysis.trend.noMetaDescription')"
      size="sm"
    />

    <!-- Keine aktive Suche -->
    <EmptyState
      v-else-if="!queryStore.term"
      :icon="TrendingUp"
      :title="t('analysis.trend.noQueryTitle')"
      :description="t('analysis.trend.noQueryDescription')"
      size="sm"
    />

    <!-- Kein Datumsfeld gewählt -->
    <EmptyState
      v-else-if="!dateField"
      :icon="CalendarOff"
      :title="t('analysis.trend.noDateFieldTitle')"
      :description="hasDateLikeField
        ? t('analysis.trend.noDateFieldDescription')
        : t('analysis.trend.noDateLikeField', { bucket: undatedLabel })"
      size="sm"
    />

    <!-- Loading -->
    <div v-else-if="isLoading" class="loading-container">
      <div class="w-full max-w-2xl">
        <Skeleton height="220px" class="mb-4" />
        <Skeleton height="120px" />
      </div>
    </div>

    <!-- Error -->
    <EmptyState
      v-else-if="effectiveError"
      :icon="AlertTriangle"
      :title="t('analysis.shared.loadError')"
      :description="errorDescription"
      :action-label="t('analysis.shared.retry')"
      size="sm"
      @action="() => refetch()"
    />

    <!-- Content -->
    <div v-else-if="data" class="content">
      <div class="chart-container">
        <h3 class="chart-title">{{ t('analysis.trend.chartTitle') }}</h3>
        <p class="chart-subtitle">
          {{ t('analysis.trend.chartSubtitle') }}
          <template v-if="undatedPeriod">
            {{ t('analysis.trend.chartUndated', { bucket: undatedLabel }) }}
          </template>
        </p>
        <LineChart
          v-if="chartData.length"
          :data="chartData"
          :height="320"
          clickable
          @point-click="openChartPoint"
        />
        <p v-else class="chart-empty">
          {{ t('analysis.trend.noDatedPeriods') }}
        </p>
      </div>

      <div v-if="undatedPeriod" class="undated-banner" role="note">
        <CalendarOff class="w-4 h-4 shrink-0" aria-hidden="true" />
        <span>
          {{ t('analysis.trend.undatedBanner', { count: formatNumber(undatedPeriod.documents), field: data.dateField, bucket: undatedLabel, hits: formatNumber(undatedPeriod.hits) }, undatedPeriod.documents) }}
        </span>
      </div>

      <!-- Ergebnistabelle -->
      <div class="table-container">
        <table class="trend-table">
          <thead>
            <tr>
              <th scope="col">{{ t('analysis.trend.period') }}</th>
              <th scope="col" class="num">{{ t('analysis.trend.documents') }}</th>
              <th scope="col" class="num">{{ t('analysis.trend.hits') }}</th>
              <th scope="col" class="num">{{ t('analysis.trend.tokens') }}</th>
              <th scope="col" class="num">{{ t('analysis.trend.perMillion') }}</th>
              <th scope="col" class="num">{{ t('analysis.trend.ci95') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="row in data.periods"
              :key="row.period"
              :class="{ 'undated-row': row.period === UNDATED_PERIOD, 'row-link': canOpenPeriod(row) }"
              :tabindex="canOpenPeriod(row) ? 0 : undefined"
              :title="canOpenPeriod(row)
                ? t('analysis.trend.openPeriod', { period: periodLabel(row.period), field: data.dateField })
                : row.period === UNDATED_PERIOD ? t('analysis.trend.undatedNoBackPath') : undefined"
              data-testid="trend-row"
              @click="openPeriodConcordance(row)"
              @keydown.enter="openPeriodConcordance(row)"
            >
              <td class="period-cell">
                {{ periodLabel(row.period) }}
                <span v-if="row.period === UNDATED_PERIOD" class="undated-chip">{{ t('analysis.trend.noDate') }}</span>
              </td>
              <td class="num">{{ formatNumber(row.documents) }}</td>
              <td class="num">{{ formatNumber(row.hits) }}</td>
              <td class="num">{{ formatNumber(row.tokens) }}</td>
              <td class="num">{{ formatDecimal(row.perMillion, 2) }}</td>
              <td class="num whitespace-nowrap">{{ formatCi(row.ciLow, row.ciHigh) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <CapabilityBoundaryPanel
        capability-id="analysis.trend"
        :method="data.method ?? null"
        :runtime-limitations="trendWarnings"
        :runtime-notes="trendBoundaryNotes"
        compact
      />
    </div>

    <EmptyState
      v-else
      :icon="TrendingUp"
      :title="t('analysis.trend.emptyTitle')"
      :description="t('analysis.trend.emptyDescription')"
      :action-label="t('analysis.shared.recompute')"
      size="sm"
      @action="() => refetch()"
    />
  </div>
</template>

<style scoped>
@reference "../../style.css";

.trend-tab {
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

.control-label {
  @apply flex items-center gap-2 text-sm;
}

.label-text {
  @apply text-neutral-600 dark:text-neutral-400;
}

.select {
  @apply rounded-lg border border-neutral-300 bg-white px-2 py-1.5 text-sm;
  @apply text-neutral-800 dark:border-neutral-600 dark:bg-neutral-800 dark:text-neutral-100;
  @apply disabled:opacity-50;
  max-width: 14rem;
}

.btn-icon {
  @apply p-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
}

.loading-container {
  @apply flex-1 flex flex-col items-center justify-center p-4;
}

.content {
  /* Results in the flow of the tab, which scrolls as a whole. */
  flex: 1 0 auto;
  @apply p-4 space-y-4;
}

.chart-container {
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.chart-title {
  @apply text-sm font-medium text-neutral-700 dark:text-neutral-300;
}

.chart-subtitle {
  @apply text-xs text-neutral-500 dark:text-neutral-500 mb-3;
}

.chart-empty {
  @apply py-8 text-center text-sm text-neutral-500 dark:text-neutral-400;
}

.undated-banner {
  @apply flex items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm text-amber-900;
  @apply dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200;
}

.table-container {
  @apply overflow-x-auto rounded-xl border border-neutral-200 dark:border-neutral-700;
}

.trend-table {
  @apply w-full text-sm;
  border-collapse: collapse;
}

.trend-table th {
  @apply px-3 py-2 text-left font-medium text-neutral-500 dark:text-neutral-400;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.trend-table td {
  @apply px-3 py-1.5 text-neutral-800 dark:text-neutral-200;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.trend-table .num {
  @apply text-right font-mono;
}

.period-cell {
  @apply font-medium whitespace-nowrap;
}

.undated-row {
  @apply bg-amber-50/60 dark:bg-amber-950/20;
}

.trend-table tr.row-link {
  @apply cursor-pointer;
}

.trend-table tr.row-link:hover,
.trend-table tr.row-link:focus-visible {
  @apply bg-primary-50 dark:bg-primary-900/20 outline-none;
}

.undated-chip {
  @apply ml-2 rounded-full bg-amber-200 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-900;
  @apply dark:bg-amber-800 dark:text-amber-100;
}
</style>
