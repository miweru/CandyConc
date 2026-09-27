<script setup lang="ts">
/**
 * KeynessRenderer - Displays directed keyness scores with explicit statistics.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Scale } from 'lucide-vue-next'
import { formatDecimal, formatInterval, formatNumber } from '@/i18n/format'
import CodeSpanText from '@/components/ui/CodeSpanText.vue'

interface KeynessRow {
  word: string
  chi2_cell?: number | null
  ll?: number | null
  ll_signed?: number | null
  log_ratio?: number | null
  log_ratio_ci_low?: number | null
  log_ratio_ci_high?: number | null
  q_value?: number | null
  direction?: string | null
}

interface Props {
  data: KeynessRow[] | { rows?: KeynessRow[] }
  limit?: number
}

const props = withDefaults(defineProps<Props>(), {
  limit: 15
})
const { t } = useI18n()

const rows = computed<KeynessRow[]>(() => {
  if (Array.isArray(props.data)) return props.data
  return props.data.rows ?? []
})

// Default ordering by signed log-likelihood (over-represented words lead), with fallbacks.
const displayRows = computed(() =>
  [...rows.value]
    .sort((a, b) => orderValue(b) - orderValue(a))
    .slice(0, props.limit)
)

function orderValue(row: KeynessRow): number {
  return Number(row.ll_signed ?? row.chi2_cell ?? row.ll ?? 0)
}

function chi2Cell(row: KeynessRow): number | null {
  return row.chi2_cell ?? null
}

function formatLogRatio(row: KeynessRow): string {
  if (typeof row.log_ratio !== 'number') return '—'
  const low = row.log_ratio_ci_low
  const high = row.log_ratio_ci_high
  if (typeof low === 'number' && typeof high === 'number') {
    return `${formatDecimal(row.log_ratio, 2)} (${formatInterval(low, high, 1)})`
  }
  return formatDecimal(row.log_ratio, 2)
}
</script>

<template>
  <div class="keyness-renderer">
    <div class="renderer-header">
      <Scale class="w-4 h-4 text-primary-500" />
      <span class="font-medium">Keyness</span>
      <span class="text-xs text-neutral-500">
        {{ t('copilot.renderers.keynessWords', { count: formatNumber(rows.length) }, rows.length) }}
      </span>
    </div>

    <div class="keyness-table">
      <div class="table-head">
        <span>{{ t('copilot.renderers.keynessWord') }}</span>
        <span class="num">{{ t('copilot.renderers.keynessLogRatio') }}</span>
        <span class="num">{{ t('copilot.renderers.keynessChi2Cell') }}</span>
        <span class="num">q (FDR)</span>
      </div>

      <div
        v-for="row in displayRows"
        :key="row.word"
        class="table-row"
      >
        <span class="word">{{ row.word }}<small v-if="row.direction"> · {{ row.direction }}</small></span>
        <span class="num">{{ formatLogRatio(row) }}</span>
        <span class="num">{{ formatDecimal(chi2Cell(row), 2) }}</span>
        <span class="num">{{ formatDecimal(row.q_value, 3) }}</span>
      </div>
    </div>
    <p class="method-note">
      <CodeSpanText :text="t('copilot.renderers.keynessNote')" />
    </p>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.keyness-renderer {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-hidden;
}

.renderer-header {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800;
}

.keyness-table {
  @apply divide-y divide-neutral-200 dark:divide-neutral-700;
  @apply max-h-80 overflow-y-auto;
}

.table-head,
.table-row {
  @apply grid grid-cols-[1fr_auto_auto_auto] gap-3 items-center;
  @apply px-3 py-2 text-sm;
}

.table-head {
  @apply text-xs font-semibold uppercase tracking-wider;
  @apply text-neutral-500 dark:text-neutral-400;
  @apply bg-neutral-50 dark:bg-neutral-800/60;
}

.word {
  @apply font-medium text-neutral-900 dark:text-neutral-100 truncate;
}

.num {
  @apply text-xs font-mono text-neutral-600 dark:text-neutral-300 text-right;
}

.method-note {
  @apply px-3 py-2 text-xs text-neutral-500 dark:text-neutral-400;
}
</style>
