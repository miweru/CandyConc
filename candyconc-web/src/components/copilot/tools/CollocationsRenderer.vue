<script setup lang="ts">
/**
 * CollocationsRenderer - Displays collocation analysis results
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Network } from 'lucide-vue-next'
import { formatDecimal, formatNumber } from '@/i18n/format'

interface Props {
  data: Array<{
    word: string
    frequency: number
    score: number
    measure: string
    observed?: number
    expected?: number | null
    chi2Cell?: number | null
  }>
  limit?: number
}

const props = withDefaults(defineProps<Props>(), {
  limit: 15
})
const { t } = useI18n()

const displayData = computed(() => props.data.slice(0, props.limit))
const maxScore = computed(() => 
  displayData.value.length > 0
    ? Math.max(...displayData.value.map(d => d.score))
    : 1
)

const measureLabel = computed(() => {
  const measure = props.data[0]?.measure
  return {
    mi: 'Mutual Information',
    lmi: 'LMI',
    npmi: 'NPMI',
    z: 'Z-Score',
    chi2_cell: t('copilot.renderers.measureChi2Cell'),
    ll: 'Log-Likelihood (G²)',
    freq: t('copilot.renderers.measureFrequency'),
    dice: 'Dice',
    logdice: 'logDice',
    tscore: 'T-Score',
    f: t('copilot.renderers.measureCooccurrence'),
    delta_p_nc: t('copilot.renderers.measureDeltaPNodeCollocate'),
    delta_p_cn: t('copilot.renderers.measureDeltaPCollocateNode'),
    'retired-mi2': t('copilot.renderers.measureRetiredMi2'),
  }[measure || 'mi'] || measure
})

/** A count measure: its score is the frequency the tile already shows. */
function isCountMeasure(measure: string): boolean {
  return measure === 'f' || measure === 'freq'
}

function getScoreColor(score: number): string {
  const normalized = score / maxScore.value
  if (normalized > 0.7) return 'text-success-600'
  if (normalized > 0.4) return 'text-warning-600'
  return 'text-neutral-600'
}
</script>

<template>
  <div class="collocations-renderer">
    <div class="renderer-header">
      <Network class="w-4 h-4 text-primary-500" />
      <span class="font-medium">{{ t('copilot.renderers.collocationsTitle') }}</span>
      <span class="text-xs text-neutral-500">
        {{ measureLabel }}
      </span>
    </div>

    <div class="collocations-grid">
      <div
        v-for="(item, idx) in displayData"
        :key="idx"
        class="collocation-item"
      >
        <div class="item-header">
          <span class="item-word">{{ item.word }}</span>
          <span class="item-freq">{{ formatNumber(item.frequency) }}×</span>
        </div>
        <div v-if="!isCountMeasure(item.measure)" class="item-score" :class="getScoreColor(item.score)">
          {{ formatDecimal(item.score, 3) }}
        </div>
        <div
          v-if="item.measure === 'chi2_cell' && typeof item.expected === 'number'"
          class="item-basis"
        >
          O11 {{ formatNumber(item.observed ?? item.frequency) }} · E11 {{ formatDecimal(item.expected, 2) }}
        </div>
      </div>
    </div>

    <div v-if="data.length > limit" class="renderer-footer">
      {{ t('copilot.renderers.moreCollocations', { count: formatNumber(data.length - limit) }, data.length - limit) }}
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.collocations-renderer {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-hidden;
}

.renderer-header {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800;
}

.collocations-grid {
  @apply grid grid-cols-2 gap-2 p-3 max-h-80 overflow-y-auto;
}

.collocation-item {
  @apply p-2 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors cursor-pointer;
}

.item-header {
  @apply flex items-center justify-between mb-1;
}

.item-word {
  @apply font-medium text-sm;
}

.item-freq {
  @apply text-xs text-neutral-500;
}

.item-score {
  @apply text-xs font-mono font-semibold;
}

.item-basis {
  @apply mt-1 text-[11px] font-mono text-neutral-500;
}

.renderer-footer {
  @apply px-3 py-2 text-xs text-neutral-500 text-center;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}
</style>
