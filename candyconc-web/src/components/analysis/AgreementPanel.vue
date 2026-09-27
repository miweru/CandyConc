<script setup lang="ts">
/**
 * AgreementPanel — inter-annotator agreement (IAA) display
 * (FT-ANNOTATION-RESEARCH, r9).
 *
 * Shows percentage agreement + Cohen's/Fleiss' kappa over rows coded by ≥ 2
 * annotators, plus per-category agreement. Multi-coder is opt-in: the panel only
 * loads/refreshes the agreement when the project enables it, and everything is
 * defensive against a backend that has not yet shipped the agreement endpoint.
 */
import { computed } from 'vue'
import { Users, RefreshCw, Info } from 'lucide-vue-next'
import { useAnnotationsStore } from '@/stores'
import EmptyState from '@/components/ui/EmptyState.vue'
import Skeleton from '@/components/ui/Skeleton.vue'
import { useI18n } from 'vue-i18n'
import { formatDecimal, formatPercent as formatLocalePercent } from '@/i18n/format'

const { t } = useI18n()
const annotationsStore = useAnnotationsStore()

const agreement = computed(() => annotationsStore.agreement)
const isLoading = computed(() => annotationsStore.isLoadingAgreement)
const error = computed(() => annotationsStore.agreementError)
const notice = computed(() => annotationsStore.agreementNotice)
const enabled = computed(() => annotationsStore.multiCoderEnabled)

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== 'number') return '–'
  return formatLocalePercent(value, 1)
}

function formatKappa(value: number | null | undefined): string {
  return typeof value === 'number' ? formatDecimal(value, 3) : '–'
}

/** Landis & Koch interpretation labels for a kappa value. */
function kappaLabel(value: number | null | undefined): string {
  if (typeof value !== 'number') return ''
  // The backend clamps kappa at 0, so exactly 0 is "no better than chance",
  // not "worse than chance" (ANNOTATION-03).
  if (value === 0) return t('analysis.agreement.kappa.chance')
  if (value < 0) return t('analysis.agreement.kappa.worse')
  if (value < 0.2) return t('analysis.agreement.kappa.slight')
  if (value < 0.4) return t('analysis.agreement.kappa.fair')
  if (value < 0.6) return t('analysis.agreement.kappa.moderate')
  if (value < 0.8) return t('analysis.agreement.kappa.substantial')
  return t('analysis.agreement.kappa.almostPerfect')
}

function categoryLabel(categoryId: string): string {
  return annotationsStore.categoryById.get(categoryId)?.label ?? categoryId
}

const hasComparableRows = computed(() => (agreement.value?.comparableRows ?? 0) > 0)

function toggleMultiCoder() {
  if (!annotationsStore.canManageMultiCoder) return
  // setMultiCoder now persists to the backend (PUT /annotations/settings) and may
  // reject; the store records the failure in `agreementError`, so swallow the
  // promise rejection here to avoid an unhandled rejection from the change event.
  void annotationsStore.setMultiCoder(!enabled.value).catch(() => {})
}
</script>

<template>
  <div class="agreement-panel">
    <div class="panel-header">
      <div class="panel-title">
        <Users class="w-4 h-4" />
        <span>{{ t('analysis.agreement.title') }}</span>
      </div>
      <div class="panel-actions">
        <label
          class="multi-toggle"
          :title="annotationsStore.multiCoderWriteBlockReason ?? t('analysis.agreement.enableMultiCoder')"
        >
          <input
            type="checkbox"
            :checked="enabled"
            :disabled="!annotationsStore.canManageMultiCoder"
            @change="toggleMultiCoder"
          />
          <span>{{ t('analysis.agreement.multiCoder') }}</span>
        </label>
        <button
          v-if="enabled"
          type="button"
          class="refresh-btn"
          :title="t('analysis.agreement.reload')"
          :disabled="isLoading || !annotationsStore.canLoadAgreement"
          @click="annotationsStore.loadAgreement()"
        >
          <RefreshCw class="w-3.5 h-3.5" :class="{ 'animate-spin': isLoading }" />
        </button>
      </div>
    </div>

    <EmptyState
      v-if="!enabled"
      :icon="Users"
      :title="t('analysis.agreement.singleCoderTitle')"
      :description="t('analysis.agreement.singleCoderDescription')"
      size="sm"
    />

    <div v-else-if="isLoading" class="agreement-loading">
      <Skeleton height="64px" class="mb-3" />
      <Skeleton height="120px" />
    </div>

    <p v-else-if="error" class="agreement-error">{{ error }}</p>

    <EmptyState
      v-else-if="!hasComparableRows"
      :icon="Info"
      :title="t('analysis.agreement.noDoubleCodedTitle')"
      :description="t('analysis.agreement.noDoubleCodedDescription')"
      size="sm"
    >
      <p v-if="notice" class="agreement-notice">
        <Info class="w-3.5 h-3.5" />
        <span>{{ notice }}</span>
      </p>
    </EmptyState>

    <template v-else-if="agreement">
      <p v-if="notice" class="agreement-notice">
        <Info class="w-3.5 h-3.5" />
        <span>{{ notice }}</span>
      </p>
      <div class="stats-grid">
        <div class="stat-card">
          <span class="stat-label">{{ t('analysis.agreement.observed') }}</span>
          <span class="stat-value">{{ formatPercent(agreement.percentAgreement) }}</span>
          <span class="stat-hint">{{ t('analysis.agreement.rowsCoders', { rows: agreement.comparableRows, coders: agreement.annotators.length }) }}</span>
        </div>
        <div v-if="agreement.cohensKappa !== null" class="stat-card">
          <span class="stat-label">{{ t('analysis.agreement.cohen') }}</span>
          <span class="stat-value">{{ formatKappa(agreement.cohensKappa) }}</span>
          <span class="stat-hint">{{ kappaLabel(agreement.cohensKappa) }}</span>
        </div>
        <div v-if="agreement.fleissKappa !== null" class="stat-card">
          <span class="stat-label">{{ t('analysis.agreement.fleiss') }}</span>
          <span class="stat-value">{{ formatKappa(agreement.fleissKappa) }}</span>
          <span class="stat-hint">{{ kappaLabel(agreement.fleissKappa) }}</span>
        </div>
      </div>

      <div v-if="agreement.perCategory.length" class="per-category">
        <h4 class="per-category-title">{{ t('analysis.agreement.perCategory') }}</h4>
        <table class="per-category-table">
          <tbody>
            <tr v-for="entry in agreement.perCategory" :key="entry.categoryId">
              <td class="cat-name">{{ categoryLabel(entry.categoryId) }}</td>
              <td class="cat-bar">
                <div class="cat-bar-track">
                  <div class="cat-bar-fill" :style="{ width: `${Math.max(0, Math.min(1, entry.agreement)) * 100}%` }" />
                </div>
              </td>
              <td class="cat-value">{{ formatPercent(entry.agreement) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <p v-if="agreement.annotators.length" class="annotators-line">
        {{ t('analysis.agreement.coders', { names: agreement.annotators.join(', ') }) }}
      </p>
    </template>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.agreement-panel {
  @apply p-4 rounded-xl;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply flex flex-col gap-3;
}

.panel-header {
  @apply flex items-center justify-between;
}

.panel-title {
  @apply flex items-center gap-2 text-sm font-medium;
  @apply text-neutral-700 dark:text-neutral-200;
}

.panel-actions {
  @apply flex items-center gap-2;
}

.multi-toggle {
  @apply inline-flex items-center gap-1.5 text-xs;
  @apply text-neutral-600 dark:text-neutral-300;
}

.refresh-btn {
  @apply p-1.5 rounded-md text-neutral-500;
  @apply hover:bg-neutral-200 dark:hover:bg-neutral-700;
  @apply disabled:opacity-50 transition-colors;
}

.agreement-loading {
  @apply w-full;
}

.agreement-error {
  @apply text-sm text-error-600 dark:text-error-400;
}

.agreement-notice {
  @apply flex items-center gap-1.5 text-xs text-primary-700 dark:text-primary-300 mb-3;
}

.stats-grid {
  @apply grid grid-cols-1 sm:grid-cols-3 gap-3;
}

.stat-card {
  @apply flex flex-col p-3 rounded-lg;
  @apply bg-white dark:bg-neutral-900;
  @apply border border-neutral-200 dark:border-neutral-700;
}

.stat-label {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.stat-value {
  @apply text-2xl font-bold text-neutral-900 dark:text-neutral-100 mt-1;
}

.stat-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-500 mt-1;
}

.per-category-title {
  @apply text-xs font-semibold uppercase tracking-wide;
  @apply text-neutral-500 dark:text-neutral-400 mb-2;
}

.per-category-table {
  @apply w-full;
}

.per-category-table td {
  @apply py-1;
}

.cat-name {
  @apply text-sm text-neutral-800 dark:text-neutral-200 pr-3;
}

.cat-bar {
  @apply w-full;
}

.cat-bar-track {
  @apply h-2 rounded-full overflow-hidden;
  @apply bg-neutral-200 dark:bg-neutral-700;
}

.cat-bar-fill {
  @apply h-full rounded-full bg-primary-500;
}

.cat-value {
  @apply text-xs font-mono text-neutral-600 dark:text-neutral-300 text-right pl-3;
}

.annotators-line {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}
</style>
