<script setup lang="ts">
/**
 * DispersionTab - Corpus dispersion analysis with Gries DP and heatmap
 */
import { ref, computed, watch } from 'vue'
import { useQuery, useQueryClient } from '@tanstack/vue-query'
import { type DispersionOffsetsResult, type DispersionParams, type DispersionResult } from '@/api/client'
import { useDispersionOperations } from '@/composables/useDispersionOperations'
import { useProductOperationFocus } from '@/composables/useProductOperationFocus'
import { buildCsv, downloadCsv } from '@/utils/csv'
import { formatDecimal } from '@/i18n/format'
import { extractApiDetail, genericApiError } from '@/utils/apiError'
import { useQueryStore, useAnalysisPresetsStore, useDocsetStore, useUiStore } from '@/stores'
import { useActions } from '@/composables'
import { useSettingsStore } from '@/stores/settings'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { Map, RefreshCw, Info, Download, AlertTriangle } from 'lucide-vue-next'
import Heatmap from './charts/Heatmap.vue'
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
const queryStore = useQueryStore()
const settingsStore = useSettingsStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const docsetStore = useDocsetStore()
const presetsStore = useAnalysisPresetsStore()
const uiStore = useUiStore()
const queryClient = useQueryClient()
const {
  loadDispersion,
  loadDispersionOffsets,
  canLoadDispersionOffsets,
  dispersionOffsetsBlockReason,
} = useDispersionOperations()
const { consumeFocusFor, focusMatches, focusIs, modeIs } = useProductOperationFocus()

// State
const partitions = ref(50)
const researchScope = computed(() =>
  ensureUsableResearchScope(docsetStore, { operation: t('analysis.operations.dispersion') })
)

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

// Query params
const queryParams = computed<DispersionParams>(() => ({
  term: queryStore.term,
  partitions: partitions.value,
  tokenCount: effectiveTokenCount.value,
  corpus: docsetStore.activeCorpus,
  docsetId: researchScope.value.docsetId,
}))

// Query
const queryKey = computed(() => ['dispersion', queryParams.value])
const { data, isLoading, error, refetch } = useQuery({
  queryKey,
  queryFn: ({ signal }) => {
    if (!researchScope.value.ok) throw new Error(researchScope.value.message)
    return loadDispersion(queryParams.value, { signal })
  },
  enabled: computed(() => !!queryStore.term),
  staleTime: 5 * 60 * 1000
})
const sessionPresetId = ref<string | null>(null)
type DispersionViewResult = DispersionResult & {
  // detail nullable: the backend's honest 'not_found' limitation sends detail:null.
  limitations?: Array<{ code?: string; message?: string; detail?: string | null }>
}

const restoredData = ref<DispersionViewResult | null>(null)
const offsetsEvidence = ref<DispersionOffsetsResult | null>(null)
const offsetsEvidenceLoading = ref(false)
const offsetsEvidenceError = ref<string | null>(null)
const offsetsEvidenceFocused = computed(() =>
  modeIs('offset_evidence') ||
  focusIs('analysis.dispersion.offsets') ||
  focusMatches('analysis.dispersion.offsets')
)
const effectiveError = computed(() => {
  const err = error.value as Error | null
  if (!err) return null
  if ('name' in err && err.name === 'AbortError') return null
  return err
})

// Resolve the backend's normalized `detail` from the (possibly ky HTTPError)
// error asynchronously, so the template never shows the raw URL/status string.
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

// Heatmap data transformation
const effectiveData = computed(() => restoredData.value ?? data.value ?? null)

const heatmapData = computed(() => {
  if (!effectiveData.value?.partitions) return []

  return effectiveData.value.partitions.map((count, i) => ({
    x: i,
    value: count
  }))
})

// Total occurrences
const totalOccurrences = computed(() =>
  effectiveData.value?.partitions?.reduce((sum, count) => sum + count, 0) || 0
)
const documentPartitionCount = computed(() => effectiveData.value?.partitions?.length ?? 0)
const positionalWindowCount = computed(() => {
  const result = effectiveData.value
  if (!result || typeof result.positional_dp_windowed !== 'number') return null
  return result.positional_window_count ?? partitions.value
})
const positionalWindowLabel = computed(() => {
  const count = positionalWindowCount.value
  const value = effectiveData.value?.positional_dp_windowed
  if (count === null || typeof value !== 'number') return null
  return t('analysis.dispersion.windowsDp', { count: formatNumber(count), value: formatDecimal(value, 4) })
})

const dispersionBasisLabel = computed(() => {
  const basis = effectiveData.value?.basis
  if (!basis) return t('analysis.dispersion.basis.notReported')
  if (basis === 'docset_local') return t('analysis.dispersion.basis.docsetLocal')
  if (basis === 'global') return t('analysis.dispersion.basis.global')
  return t('analysis.dispersion.basis.partial', { basis })
})

const dispersionWarnings = computed(() => {
  const result = effectiveData.value
  const warnings: string[] = []
  if (!result) return warnings
  if (result.partial || result.fallback) {
    warnings.push(t('analysis.dispersion.partialWarning'))
  }
  for (const item of result.limitations ?? []) {
    if (item.message) warnings.push(item.message)
  }
  return warnings
})
const dispersionBoundaryNotes = computed(() => {
  const result = effectiveData.value
  if (!result) return []
  const notes = [dispersionBasisLabel.value]
  if (typeof result.token_count === 'number') {
    notes.push(t('analysis.dispersion.tokenBasis', { count: formatNumber(result.token_count) }))
  }
  if (documentPartitionCount.value) {
    notes.push(t('analysis.dispersion.documentBasis', { count: formatNumber(documentPartitionCount.value) }))
  }
  if (positionalWindowLabel.value) {
    notes.push(t('analysis.dispersion.windowComparison', { label: positionalWindowLabel.value }))
  }
  return notes
})
const offsetsEvidenceSample = computed(() =>
  offsetsEvidence.value?.offsets?.slice(0, 12) ?? []
)
const offsetsEvidenceLabel = computed(() => {
  const result = offsetsEvidence.value
  if (!result) return t('analysis.dispersion.offsets.notLoaded')
  const count = result.offsets?.length ?? 0
  const basis = result.basis ?? t('analysis.dispersion.notReported')
  const tokenCount = typeof result.token_count === 'number'
    ? formatNumber(result.token_count)
    : 'n/a'
  // A capped page is a strict subset of the full hit set: show "500 von 919"
  // rather than implying the 500 shown offsets are the whole occurrence set.
  const capped = (result.truncated || result.partial)
    && typeof result.total === 'number'
    && result.total > count
  const offsetLabel = capped
    ? t('analysis.dispersion.offsets.countOf', { count: formatNumber(count), total: formatNumber(result.total!) })
    : t('analysis.dispersion.offsets.count', { count: formatNumber(count) }, count)
  return t('analysis.dispersion.offsets.summary', { offsets: offsetLabel, basis, tokens: tokenCount })
})

consumeFocusFor(['analysis.dispersion'], () => undefined)

// Honest labels for the backend classification string (raw Gries DP over docs).
// The backend flags a zero-frequency term distinctly (not "even").
function classificationLabel(classification: string): string {
  switch (classification) {
    case 'even': return t('analysis.dispersion.class.even')
    case 'fairly_even': return t('analysis.dispersion.class.fairlyEven')
    case 'fairly_clustered': return t('analysis.dispersion.class.fairlyClustered')
    case 'clustered': return t('analysis.dispersion.class.clustered')
    case 'not_found': return t('analysis.dispersion.class.notFound')
    default: return classification
  }
}

// DP interpretation: prefer the backend classification, fall back to dp thresholds.
const dpInterpretation = computed(() => {
  const classification = effectiveData.value?.classification
  if (classification) {
    return classificationLabel(classification)
  }
  const dp = effectiveData.value?.dp
  if (typeof dp !== 'number') return ''
  if (dp < 0.2) return t('analysis.dispersion.class.veryEven')
  if (dp < 0.4) return t('analysis.dispersion.class.fairlyEven')
  if (dp < 0.6) return t('analysis.dispersion.class.fairlyClustered')
  if (dp < 0.8) return t('analysis.dispersion.class.clustered')
  return t('analysis.dispersion.class.veryClustered')
})

const dispersionUnitLabel = computed(() => {
  const unit = effectiveData.value?.unit
  if (!unit) return t('analysis.dispersion.documents')
  if (unit === 'document' || unit === 'documents') return t('analysis.dispersion.documents')
  return unit
})

// Dispersion family (FT-DISPERSION-FAMILY). Each card renders only when the
// backend actually supplied the measure, so older indexes (DP only) stay clean.
type DispersionFamilyKey = 'juilland_d' | 'carroll_d2' | 'range_prop' | 'vc'

interface DispersionFamilyCard {
  key: DispersionFamilyKey
  label: string
  value: number
  hint: string
  title: string
}

function familyValue(key: DispersionFamilyKey): number | null {
  const raw = effectiveData.value?.[key]
  return typeof raw === 'number' && Number.isFinite(raw) ? raw : null
}

const dispersionFamilyCards = computed<DispersionFamilyCard[]>(() => {
  const cards: DispersionFamilyCard[] = []
  const juilland = familyValue('juilland_d')
  if (juilland !== null) {
    cards.push({
      key: 'juilland_d',
      label: "Juilland's D",
      value: juilland,
      hint: t('analysis.dispersion.family.evenHint'),
      title: t('analysis.dispersion.family.juillandTitle'),
    })
  }
  const carroll = familyValue('carroll_d2')
  if (carroll !== null) {
    cards.push({
      key: 'carroll_d2',
      label: "Carroll's D2",
      value: carroll,
      hint: t('analysis.dispersion.family.evenHint'),
      title: t('analysis.dispersion.family.carrollTitle'),
    })
  }
  const range = familyValue('range_prop')
  if (range !== null) {
    cards.push({
      key: 'range_prop',
      label: 'Range',
      value: range,
      hint: t('analysis.dispersion.family.rangeHint'),
      title: t('analysis.dispersion.family.rangeTitle'),
    })
  }
  const vc = familyValue('vc')
  if (vc !== null) {
    cards.push({
      key: 'vc',
      label: 'VC',
      value: vc,
      hint: t('analysis.dispersion.family.vcHint'),
      title: t('analysis.dispersion.family.vcTitle'),
    })
  }
  return cards
})

function cancelDispersion() {
  if (!isLoading.value) return
  void queryClient.cancelQueries({ queryKey: queryKey.value })
  uiStore.showToast(t('analysis.dispersion.cancelled'), 'info')
}

async function loadOffsetEvidence() {
  if (!canLoadDispersionOffsets.value || offsetsEvidenceLoading.value || !queryStore.term) return
  offsetsEvidenceLoading.value = true
  offsetsEvidenceError.value = null
  try {
    offsetsEvidence.value = await loadDispersionOffsets(queryParams.value)
  } catch (err) {
    offsetsEvidenceError.value = err instanceof Error
      ? err.message
      : t('analysis.dispersion.offsets.loadFailed')
  } finally {
    offsetsEvidenceLoading.value = false
  }
}

function exportCSV() {
  if (!effectiveData.value) return
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
    '# DP = Gries Deviation of Proportions (raw) over documents; 0 = evenly dispersed, 1 = clustered',
    '# DPnorm = DP normalized for the number of parts (corrects DP_min bias)',
    `# DP (raw): ${typeof effectiveData.value.dp === 'number' ? effectiveData.value.dp : 'n/a'}`,
    `# DPnorm: ${typeof effectiveData.value.dpnorm === 'number' ? effectiveData.value.dpnorm : 'n/a'}`,
    `# JuillandD: ${typeof effectiveData.value.juilland_d === 'number' ? effectiveData.value.juilland_d : 'n/a'}`,
    `# CarrollD2: ${typeof effectiveData.value.carroll_d2 === 'number' ? effectiveData.value.carroll_d2 : 'n/a'}`,
    `# Range: ${typeof effectiveData.value.range_prop === 'number' ? effectiveData.value.range_prop : 'n/a'}`,
    `# VC: ${typeof effectiveData.value.vc === 'number' ? effectiveData.value.vc : 'n/a'}`,
    `# Classification: ${effectiveData.value.classification ?? 'n/a'}`,
    `# Unit: ${effectiveData.value.unit ?? 'n/a'}`,
    `# DocumentPartitions: ${documentPartitionCount.value || 'n/a'}`,
    `# PositionalWindowCount: ${effectiveData.value.positional_window_count ?? 'n/a'}`,
    `# PositionalDPWindowed: ${typeof effectiveData.value.positional_dp_windowed === 'number' ? effectiveData.value.positional_dp_windowed : 'n/a'}`,
    `# Basis: ${effectiveData.value.basis ?? t('analysis.dispersion.notReported')}`,
    `# Partial: ${effectiveData.value.partial ? 'true' : 'false'}`,
    `# Fallback: ${effectiveData.value.fallback ? 'true' : 'false'}`,
  ]
  const meta = [
    '# CandyConc Export',
    '# Analysis: Dispersion',
    `# Term: ${queryStore.term || 'n/a'}`,
    `# RequestedPositionWindows: ${partitions.value}`,
    `# Corpus: ${docsetStore.activeCorpus}`,
    `# Docset: ${docsetStore.activeDocsetId ?? 'all'}`,
    `# Docs: ${effectiveDocCount.value}`,
    `# Tokens: ${effectiveTokenCount.value}`,
    `# DispersionTokenBasis: ${effectiveData.value.token_count ?? 'n/a'}`,
    ...researchScopeCsvMeta(docsetStore),
    ...filterLines,
    ...formulaLines,
    `# Exported: ${new Date().toISOString()}`,
  ]
  const csv = buildCsv({
    meta,
    headers: ['document_partition', 'frequency'],
    rows: effectiveData.value.partitions.map((count, index) => [index + 1, count]),
  })
  downloadCsv(csv, `dispersion_${queryStore.term || 'term'}.csv`)
}

// Register action handler for Copilot
useActions({
  'analysis/dispersion': async () => {
    const params = queryParams.value
    const result = await refetch()
    if (result.error) {
      return {
        success: false,
        error: result.error instanceof Error ? result.error.message : t('analysis.dispersion.failed'),
      }
    }
    return {
      success: true,
      data: result.data ?? data.value,
      executionScope: executionScopeForApi(docsetStore, params.corpus ?? docsetStore.activeCorpus, params.docsetId),
    }
  }
})

// Refetch when term changes
watch(() => queryStore.term, () => {
  offsetsEvidence.value = null
  offsetsEvidenceError.value = null
  if (queryStore.term) {
    refetch()
  }
})

watch(queryParams, () => {
  offsetsEvidence.value = null
  offsetsEvidenceError.value = null
})

watch(
  () => presetsStore.pendingPreset,
  async (preset) => {
    if (!preset || preset.type !== 'dispersion') return
    sessionPresetId.value = preset.id
    let shouldRefetch = true
    const params = preset.params as { partitions?: number }
    if (params.partitions) partitions.value = params.partitions
    presetsStore.setPending(null)
    if (preset.result && typeof preset.result === 'object') {
      const valid = await presetsStore.isResultValid(preset)
      if (valid) {
        restoredData.value = preset.result as DispersionViewResult
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

async function persistDispersionResult(result: DispersionViewResult) {
  try {
    const cacheKey = await presetsStore.buildCacheKey({
      type: 'dispersion',
      corpus: docsetStore.activeCorpus,
      docset: docsetSnapshot.value,
      queryTerm: queryStore.term,
      params: { partitions: partitions.value },
    })
    const session = await presetsStore.upsertJobSession({
      id: sessionPresetId.value ?? undefined,
      name: t('analysis.dispersion.defaultName', { query: queryStore.term || t('analysis.dispersion.noQuery') }),
      type: 'dispersion',
      corpus: docsetStore.activeCorpus,
      docset: docsetSnapshot.value,
      queryTerm: queryStore.term,
      params: { partitions: partitions.value },
      status: 'done',
      jobId: undefined,
      kind: sessionPresetId.value ? undefined : 'session',
    })
    sessionPresetId.value = session.id
    await presetsStore.updateResult(
      session.id,
      result,
      {
        partitions: partitions.value,
        corpus: docsetStore.activeCorpus,
        docsetId: docsetStore.activeDocsetId ?? null,
        docCount: effectiveDocCount.value,
        tokenCount: effectiveTokenCount.value,
        basis: result.basis,
        partial: result.partial ?? false,
        fallback: result.fallback ?? false,
        cacheKey,
        cacheVersion: presetsStore.cacheVersion,
        generatedAt: Date.now(),
      }
    )
  } catch (err) {
    console.warn('Dispersion result could not be persisted', err)
  }
}

watch(
  () => data.value,
  (result) => {
    if (result && result.partitions?.length) {
      restoredData.value = null
      void persistDispersionResult(result)
    }
  }
)
</script>

<template>
  <div class="dispersion-tab">
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
        <label class="slider-label">
          <span class="label-text">{{ t('analysis.dispersion.windowsLabel') }}</span>
          <input
            v-model="partitions"
            type="range"
            min="10"
            max="100"
            step="10"
            class="slider"
            :title="t('analysis.dispersion.windowsTitle')"
          />
          <span class="slider-value">{{ partitions }}</span>
        </label>
      </template>

      <template #right>
        <JobStatusPill
          v-if="isLoading"
          status="running"
          :progress="0"
          :message="t('analysis.shared.loading')"
          :canCancel="true"
          @cancel="cancelDispersion"
        />
        <SaveAnalysisButton
          type="dispersion"
          :defaultName="t('analysis.dispersion.defaultName', { query: queryStore.term || t('analysis.dispersion.noQuery') })"
          :corpus="docsetStore.activeCorpus"
          :docset="docsetSnapshot"
          :queryTerm="queryStore.term"
          :params="{ partitions }"
          :result="effectiveData ? effectiveData : undefined"
          :resultMeta="effectiveData ? {
            partitions,
            corpus: docsetStore.activeCorpus,
            docsetId: docsetStore.activeDocsetId ?? null,
            docCount: effectiveDocCount,
            tokenCount: effectiveTokenCount,
            basis: effectiveData.basis,
            partial: effectiveData.partial ?? false,
            fallback: effectiveData.fallback ?? false,
            generatedAt: Date.now(),
          } : undefined"
        />
        <button class="btn-icon" :aria-label="t('analysis.dispersion.exportCsv')" @click="exportCSV" :disabled="!effectiveData">
          <Download class="w-4 h-4" />
        </button>
        <button class="btn-icon" :aria-label="t('analysis.dispersion.refresh')" @click="() => refetch()" :disabled="isLoading">
          <RefreshCw class="w-4 h-4" :class="{ 'animate-spin': isLoading }" />
        </button>
      </template>
    </AnalysisToolbar>

    <!-- No Query State -->
    <EmptyState
      v-if="!queryStore.term"
      :icon="Map"
      :title="t('analysis.dispersion.noQueryTitle')"
      :description="t('analysis.dispersion.noQueryDescription')"
      size="sm"
    />

    <!-- Loading -->
    <div v-else-if="isLoading" class="loading-container">
      <div class="w-full max-w-lg">
        <Skeleton height="120px" class="mb-4" />
        <div class="grid grid-cols-2 gap-4">
          <Skeleton height="80px" />
          <Skeleton height="80px" />
        </div>
      </div>
    </div>

    <!-- Error -->
    <EmptyState
      v-else-if="effectiveError"
      :icon="AlertTriangle"
      :title="t('analysis.shared.loadError')"
      :description="errorDescription"
      :action-label="t('analysis.shared.retry')"
      :secondary-action-label="t('analysis.shared.checkSubcorpus')"
      size="sm"
      @action="() => refetch()"
      @secondaryAction="uiStore.openSubcorpus()"
    />

    <!-- Content -->
    <div v-else-if="effectiveData" class="content">
      <!-- Stats Cards -->
      <div class="stats-grid">
        <div class="stat-card">
          <div class="stat-header">
            <span class="stat-label">{{ t('analysis.dispersion.dpRaw', { unit: dispersionUnitLabel }) }}</span>
            <!-- Formel + Erklärung + Referenz aus dem Methodenkatalog (T4) -->
            <MeasureInfo measure-key="dp" fallback-label="Gries DP" />
          </div>
          <span class="stat-value">{{ formatDecimal(effectiveData.dp, 4) }}</span>
          <span class="stat-hint">{{ t('analysis.dispersion.dpHint', { interpretation: dpInterpretation }) }}</span>
        </div>

        <div v-if="typeof effectiveData.dpnorm === 'number'" class="stat-card">
          <div class="stat-header">
            <span class="stat-label">{{ t('analysis.dispersion.dpNorm') }}</span>
            <MeasureInfo measure-key="dpnorm" :fallback-label="t('analysis.dispersion.dpNorm')" />
          </div>
          <span class="stat-value">{{ formatDecimal(effectiveData.dpnorm, 4) }}</span>
          <span class="stat-hint">{{ t('analysis.dispersion.dpNormHint') }}</span>
        </div>

        <div class="stat-card">
          <span class="stat-label">{{ t('analysis.dispersion.occurrences') }}</span>
          <span class="stat-value">{{ formatNumber(totalOccurrences) }}</span>
          <span class="stat-hint">{{ docsetStore.hasActiveDocset ? t('analysis.dispersion.inSubcorpus') : t('analysis.dispersion.inWholeCorpus') }}</span>
        </div>

        <div v-if="typeof effectiveData.positional_dp_windowed === 'number'" class="stat-card">
          <div class="stat-header">
            <span class="stat-label">{{ t('analysis.dispersion.windowDp') }}</span>
            <button class="info-btn" :title="t('analysis.dispersion.windowDpTitle')">
              <Info class="w-4 h-4" />
            </button>
          </div>
          <span class="stat-value">{{ formatDecimal(effectiveData.positional_dp_windowed, 4) }}</span>
          <span class="stat-hint">
            {{ t('analysis.dispersion.windowDpHint', { count: formatNumber(positionalWindowCount ?? partitions) }) }}
          </span>
        </div>

        <!-- Dispersion family (FT-DISPERSION-FAMILY): only rendered when supplied -->
        <div v-for="card in dispersionFamilyCards" :key="card.key" class="stat-card">
          <div class="stat-header">
            <span class="stat-label">{{ card.label }}</span>
            <!-- juilland_d / carroll_d2 / range_prop / vc sind Katalog-Keys -->
            <MeasureInfo :measure-key="card.key" :fallback-label="card.label" />
          </div>
          <span class="stat-value">{{ formatDecimal(card.value, 4) }}</span>
          <span class="stat-hint">{{ card.hint }}</span>
        </div>
      </div>

      <div class="basis-panel" :class="{ partial: effectiveData.partial || effectiveData.fallback }">
        <strong>{{ dispersionBasisLabel }}</strong>
        <span v-if="effectiveData.token_count">
          {{ t('analysis.dispersion.tokenBasis', { count: formatNumber(effectiveData.token_count) }) }}
        </span>
        <span v-if="documentPartitionCount">
          {{ t('analysis.dispersion.documentBasis', { count: formatNumber(documentPartitionCount) }) }}
        </span>
        <span v-if="positionalWindowLabel">
          {{ t('analysis.dispersion.windowComparison', { label: positionalWindowLabel }) }}
        </span>
        <span v-if="effectiveData.partial || effectiveData.fallback" class="basis-warning">
          {{ t('analysis.dispersion.partialLimited') }}
        </span>
        <ul v-if="dispersionWarnings.length" class="basis-list">
          <li v-for="warning in dispersionWarnings" :key="warning">{{ warning }}</li>
        </ul>
      </div>

      <section
        class="offset-evidence-panel"
        :class="{ focused: offsetsEvidenceFocused }"
        :aria-label="t('analysis.dispersion.offsets.title')"
      >
        <div>
          <strong>{{ t('analysis.dispersion.offsets.title') }}</strong>
          <p>
            {{ t('analysis.dispersion.offsets.description') }}
          </p>
          <span>{{ offsetsEvidenceLabel }}</span>
        </div>
        <button
          type="button"
          class="btn-secondary"
          :disabled="!canLoadDispersionOffsets || offsetsEvidenceLoading || !queryStore.term"
          @click="loadOffsetEvidence"
        >
          {{ offsetsEvidenceLoading ? t('analysis.shared.loading') : t('analysis.dispersion.offsets.check') }}
        </button>
        <p v-if="dispersionOffsetsBlockReason" class="offset-warning">
          {{ dispersionOffsetsBlockReason }}
        </p>
        <p v-if="offsetsEvidenceError" class="offset-warning">
          {{ offsetsEvidenceError }}
        </p>
        <div v-if="offsetsEvidenceSample.length" class="offset-sample">
          <span>{{ t('analysis.dispersion.offsets.first') }}</span>
          <code>{{ offsetsEvidenceSample.join(', ') }}</code>
        </div>
        <ul v-if="offsetsEvidence?.limitations?.length" class="basis-list">
          <li
            v-for="(item, index) in offsetsEvidence.limitations"
            :key="`${item.code || item.message || item.detail || 'offset-limitation'}-${index}`"
          >
            {{ item.message || item.detail || item.code }}
          </li>
        </ul>
      </section>

      <CapabilityBoundaryPanel
        capability-id="analysis.dispersion"
        :runtime-limitations="dispersionWarnings"
        :runtime-notes="dispersionBoundaryNotes"
        compact
      />

      <!-- Heatmap -->
      <div class="heatmap-container">
        <h3 class="heatmap-title">{{ t('analysis.dispersion.heatmapTitle') }}</h3>
        <p class="heatmap-subtitle">{{ t('analysis.dispersion.heatmapSubtitle') }}</p>
        <Heatmap :data="heatmapData" :height="120" />
      </div>

      <!-- Explanation -->
      <div class="explanation">
        <h4 class="explanation-title">{{ t('analysis.dispersion.explain.title') }}</h4>
        <i18n-t keypath="analysis.dispersion.explain.dp" tag="p" class="explanation-text" scope="global">
          <template #dp><strong>Gries DP</strong></template>
          <template #unit>{{ dispersionUnitLabel }}</template>
          <template #zero><strong>0</strong></template>
          <template #one><strong>1</strong></template>
          <template #normDp><strong>{{ t('analysis.dispersion.explain.normDp') }}</strong></template>
        </i18n-t>
        <i18n-t keypath="analysis.dispersion.explain.heatmap" tag="p" class="explanation-text mt-2" scope="global">
          <template #heatmap><strong>{{ t('analysis.dispersion.explain.heatmapWord') }}</strong></template>
        </i18n-t>
      </div>
    </div>

    <EmptyState
      v-else
      :icon="Map"
      :title="t('analysis.dispersion.emptyTitle')"
      :description="t('analysis.dispersion.emptyDescription')"
      :action-label="t('analysis.shared.recompute')"
      size="sm"
      @action="() => refetch()"
    />
  </div>
</template>

<style scoped>
@reference "../../style.css";

.dispersion-tab {
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

.slider-label {
  @apply flex items-center gap-2 text-sm;
}

.label-text {
  @apply text-neutral-600 dark:text-neutral-400;
}

.slider {
  @apply w-24 md:w-32 h-2 rounded-full;
  @apply bg-neutral-200 dark:bg-neutral-700;
  @apply accent-primary-500;
}

.slider-value {
  @apply w-8 text-center font-mono text-neutral-700 dark:text-neutral-300;
}

.btn-icon {
  @apply p-2 rounded-lg;
  @apply bg-neutral-100 dark:bg-neutral-800;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 disabled:cursor-not-allowed;
  @apply transition-colors;
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

.content {
  /* Results in the flow of the tab, which scrolls as a whole. */
  flex: 1 0 auto;
  @apply p-4 space-y-6;
}

.stats-grid {
  @apply grid grid-cols-1 sm:grid-cols-2 gap-4;
}

.basis-panel {
  @apply rounded-xl border border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800/60;
  @apply px-4 py-3 text-sm text-neutral-700 dark:text-neutral-200;
  @apply flex flex-wrap items-center gap-2;
}

.basis-panel.partial {
  @apply border-amber-300 bg-amber-50 text-amber-900;
  @apply dark:border-amber-700 dark:bg-amber-950/30 dark:text-amber-200;
}

.basis-warning {
  @apply rounded-full px-2 py-0.5 text-xs font-semibold uppercase tracking-wide;
  @apply bg-amber-200 text-amber-900;
  @apply dark:bg-amber-800 dark:text-amber-100;
}

.basis-list {
  @apply basis-full list-disc pl-5 text-xs;
}

.offset-evidence-panel {
  @apply rounded-xl border border-neutral-200 bg-white px-4 py-3 text-sm;
  @apply dark:border-neutral-700 dark:bg-neutral-900;
  @apply flex flex-col gap-3 md:flex-row md:items-start md:justify-between;
}

.offset-evidence-panel.focused {
  @apply ring-2 ring-amber-300 ring-offset-2 ring-offset-white;
  @apply dark:ring-amber-500/80 dark:ring-offset-neutral-950;
}

.offset-evidence-panel p {
  @apply mt-1 max-w-2xl text-xs text-neutral-500 dark:text-neutral-400;
}

.offset-evidence-panel span {
  @apply mt-1 block text-xs font-medium text-neutral-700 dark:text-neutral-300;
}

.btn-secondary {
  @apply rounded-lg border border-neutral-200 px-3 py-1.5 text-sm font-medium;
  @apply bg-white text-neutral-700 hover:bg-neutral-50;
  @apply dark:border-neutral-700 dark:bg-neutral-950 dark:text-neutral-200 dark:hover:bg-neutral-800;
  @apply disabled:cursor-not-allowed disabled:opacity-50;
}

.offset-warning {
  @apply md:basis-full text-xs text-amber-700 dark:text-amber-300;
}

.offset-sample {
  @apply md:basis-full rounded-lg border border-neutral-100 bg-neutral-50 px-3 py-2 text-xs;
  @apply dark:border-neutral-800 dark:bg-neutral-950;
}

.offset-sample code {
  @apply ml-2 font-mono text-neutral-800 dark:text-neutral-100;
}

.stat-card {
  @apply flex flex-col p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.stat-header {
  @apply flex items-center justify-between;
}

.stat-label {
  @apply text-sm text-neutral-500 dark:text-neutral-400;
}

.info-btn {
  @apply p-1 rounded text-neutral-400 hover:text-neutral-600 dark:hover:text-neutral-300;
}

.stat-value {
  @apply text-2xl md:text-3xl font-bold text-neutral-900 dark:text-neutral-100;
  @apply mt-1;
}

.stat-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-500;
  @apply mt-1;
}

.heatmap-container {
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.heatmap-title {
  @apply text-sm font-medium text-neutral-700 dark:text-neutral-300;
}

.heatmap-subtitle {
  @apply text-xs text-neutral-500 dark:text-neutral-500;
  @apply mb-3;
}

.explanation {
  @apply p-4 rounded-xl;
  @apply bg-primary-50 dark:bg-primary-900/20;
  @apply border border-primary-200 dark:border-primary-800;
}

.explanation-title {
  @apply text-sm font-medium text-primary-700 dark:text-primary-300;
  @apply mb-2;
}

.explanation-text {
  @apply text-sm text-primary-600 dark:text-primary-400;
  @apply leading-relaxed;
}
</style>
