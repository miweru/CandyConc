<script setup lang="ts">
/**
 * QueryResultsRenderer - Displays query execution results summary
 */
import { useI18n } from 'vue-i18n'
import { Search, Clock } from 'lucide-vue-next'
import { formatNumber } from '@/i18n/format'
import { formatDurationMs } from '@/lib/copilotNumbers'

interface Props {
  data: {
    total?: number | null
    sampleCount?: number
    truncated?: boolean
    queryTime?: number
  }
}

const props = defineProps<Props>()
const { t } = useI18n()

function formatCount(value: number): string {
  return formatNumber(value)
}
</script>

<template>
  <div class="query-results-renderer">
    <div class="result-icon">
      <Search class="w-5 h-5 text-success-500" />
    </div>
    
    <div class="result-content">
      <div class="result-title">
        {{ t('copilot.renderers.querySuccess') }}
      </div>
      <div class="result-stats">
        <span v-if="typeof data.total === 'number'" class="stat-item">
          <i18n-t keypath="copilot.renderers.queryHits" :plural="data.total" scope="global">
            <template #count><strong>{{ formatCount(data.total) }}</strong></template>
          </i18n-t>
          <span v-if="data.truncated">{{ t('copilot.renderers.queryPartial') }}</span>
        </span>
        <span v-else class="stat-item">
          <i18n-t keypath="copilot.renderers.queryLoadedLines" :plural="data.sampleCount ?? 0" scope="global">
            <template #count><strong>{{ formatCount(data.sampleCount ?? 0) }}</strong></template>
          </i18n-t>
          <span>{{ t('copilot.renderers.querySample') }}</span>
        </span>
        <span v-if="data.queryTime" class="stat-item">
          <Clock class="w-3 h-3" />
          {{ formatDurationMs(data.queryTime) }}
        </span>
      </div>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.query-results-renderer {
  @apply flex items-center gap-3 p-3 rounded-lg;
  @apply bg-success-50 dark:bg-success-900/20;
  @apply border border-success-200 dark:border-success-800;
}

.result-icon {
  @apply flex-shrink-0;
}

.result-content {
  @apply flex-1 min-w-0;
}

.result-title {
  @apply font-medium text-success-700 dark:text-success-300;
}

.result-stats {
  @apply flex items-center gap-3 mt-1 text-sm text-success-600 dark:text-success-400;
}

.stat-item {
  @apply flex items-center gap-1;
}
</style>
