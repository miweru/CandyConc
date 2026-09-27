<script setup lang="ts">
/**
 * FrequencyRenderer - Displays frequency_list tool results.
 *
 * Props contract mirrors the backend response schema
 * (tool_wrappers.FREQUENCY_RESPONSE): rows of {word, f, per_million?} plus
 * top-level {total, truncated, corpus_tokens}.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { BarChart2 } from 'lucide-vue-next'
import { formatNumber } from '@/i18n/format'

interface FrequencyRow {
  word: string
  f: number
  per_million?: number | null
}

interface FrequencyPayload {
  rows?: FrequencyRow[]
  total?: number
  truncated?: boolean
  corpus_tokens?: number
}

interface Props {
  data: FrequencyRow[] | FrequencyPayload
  limit?: number
}

const props = withDefaults(defineProps<Props>(), {
  limit: 20
})
const { t } = useI18n()

const rows = computed<FrequencyRow[]>(() => {
  if (Array.isArray(props.data)) return props.data
  return props.data.rows ?? []
})

const total = computed<number | null>(() => {
  if (Array.isArray(props.data)) return null
  return typeof props.data.total === 'number' ? props.data.total : null
})

const truncated = computed<boolean>(() => {
  if (Array.isArray(props.data)) return false
  return props.data.truncated === true
})

const displayRows = computed(() => rows.value.slice(0, props.limit))
const maxFrequency = computed(() =>
  displayRows.value.length > 0
    ? Math.max(...displayRows.value.map((row) => Number(row.f) || 0), 1)
    : 1
)

const countLabel = computed(() => {
  if (total.value !== null && total.value !== rows.value.length) {
    return t('copilot.renderers.frequencyOfTotal', {
      shown: formatNumber(rows.value.length),
      total: formatNumber(total.value),
    })
  }
  return t('copilot.renderers.frequencyEntries', { count: formatNumber(rows.value.length) }, rows.value.length)
})

function formatPerMillion(row: FrequencyRow): string {
  return typeof row.per_million === 'number'
    ? `${formatNumber(row.per_million)} pM`
    : '—'
}
</script>

<template>
  <div class="frequency-renderer">
    <div class="renderer-header">
      <BarChart2 class="w-4 h-4 text-primary-500" />
      <span class="font-medium">{{ t('copilot.renderers.frequencyTitle') }}</span>
      <span class="text-xs text-neutral-500">
        {{ countLabel }}
      </span>
    </div>

    <div class="frequency-list">
      <div
        v-for="(row, idx) in displayRows"
        :key="idx"
        class="frequency-item"
      >
        <span class="item-rank">{{ idx + 1 }}</span>
        <span class="item-word">{{ row.word }}</span>
        <div class="item-bar-container">
          <div
            class="item-bar"
            :style="{ width: `${((Number(row.f) || 0) / maxFrequency) * 100}%` }"
          />
        </div>
        <span class="item-freq">{{ formatNumber(Number(row.f) || 0) }}</span>
        <span class="item-relative">{{ formatPerMillion(row) }}</span>
      </div>
    </div>

    <div v-if="rows.length > limit || truncated" class="renderer-footer">
      <template v-if="rows.length > limit">
        {{ t('copilot.renderers.frequencyHiddenRows', { count: formatNumber(rows.length - limit) }, rows.length - limit) }}
      </template>
      <template v-if="truncated">
        {{ total !== null
          ? t('copilot.renderers.frequencyTruncatedTotal', { total: formatNumber(total) })
          : t('copilot.renderers.frequencyTruncated') }}
      </template>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.frequency-renderer {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-hidden;
}

.renderer-header {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800;
}

.frequency-list {
  @apply p-2 space-y-1 max-h-80 overflow-y-auto;
}

.frequency-item {
  @apply flex items-center gap-2 px-2 py-1.5 rounded;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-800;
  @apply text-sm;
}

.item-rank {
  @apply w-8 text-xs text-neutral-500 text-right;
}

.item-word {
  @apply w-32 font-medium truncate;
}

.item-bar-container {
  @apply flex-1 h-5 bg-neutral-100 dark:bg-neutral-800 rounded-full overflow-hidden;
}

.item-bar {
  @apply h-full bg-primary-500 rounded-full;
  @apply transition-all duration-300;
}

.item-freq {
  @apply w-16 text-right font-mono text-xs;
}

.item-relative {
  @apply w-20 text-right text-xs text-neutral-500;
}

.renderer-footer {
  @apply px-3 py-2 text-xs text-neutral-500 text-center;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}
</style>
