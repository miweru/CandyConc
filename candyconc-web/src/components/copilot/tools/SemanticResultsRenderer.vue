<script setup lang="ts">
/**
 * SemanticResultsRenderer - Displays semantic search results
 *
 * Shares ONE score-kind decision with the analysis SemanticTab (sibling-surface
 * parity, SEM-01): a rerank/lexical score is rendered as a raw relevance value
 * with no percent sign and no green "perfect match" band; only a true cosine
 * earns the %/colour-band treatment.
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { Brain, ExternalLink } from 'lucide-vue-next'
import {
  type SemanticScoreKind,
  formatSemanticScore,
  semanticBarWidth,
  semanticScoreBand,
  semanticScoreUnitLabel,
} from '@/lib/semanticScore'
import { formatDecimal } from '@/i18n/format'

interface Props {
  data: Array<{
    doc_id: string
    chunk_id: string
    text: string
    score: number
    metadata?: Record<string, string>
  }>
  limit?: number
  /** 'cosine' for similar_words; 'rerank' for passage search unless meta proves cosine. */
  scoreKind?: SemanticScoreKind
}

const props = withDefaults(defineProps<Props>(), {
  limit: 5,
  scoreKind: 'rerank',
})
const { t } = useI18n()

const displayData = computed(() => props.data.slice(0, props.limit))

// Rerank scores have no fixed ceiling — normalise the bar against the batch max.
const maxScore = computed(() =>
  props.data.reduce((m, item) => (Number.isFinite(item.score) && item.score > m ? item.score : m), 0)
)

function scorePercent(score: number): number {
  return semanticBarWidth(score, props.scoreKind, maxScore.value)
}

function scoreLabel(score: number): string {
  return formatSemanticScore(score, props.scoreKind)
}

function getScoreColor(score: number): string {
  const band = semanticScoreBand(score, props.scoreKind)
  if (band === 'high') return 'bg-success-500'
  if (band === 'medium') return 'bg-primary-500'
  return 'bg-neutral-400'
}

const scoreUnitLabel = computed(() => semanticScoreUnitLabel(props.scoreKind))
</script>

<template>
  <div class="semantic-renderer">
    <div class="renderer-header">
      <Brain class="w-4 h-4 text-primary-500" />
      <span class="font-medium">{{ t('copilot.renderers.semanticTitle') }}</span>
      <span class="text-xs text-neutral-500">
        {{ t('copilot.renderers.semanticResults', { count: data.length }, data.length) }}
      </span>
    </div>

    <div class="results-list">
      <div
        v-for="(item, idx) in displayData"
        :key="idx"
        class="result-item"
      >
        <div class="result-header">
          <div class="result-doc">
            <ExternalLink class="w-3 h-3" />
            <span>{{ item.metadata?.title || item.doc_id }}</span>
          </div>
          <div class="result-score" :title="`${scoreUnitLabel}: ${formatDecimal(item.score, 3)}`">
            <div
              class="score-bar"
              :class="getScoreColor(item.score)"
              :style="{ width: `${scorePercent(item.score)}%` }"
            />
            <span class="score-unit">{{ scoreUnitLabel }}</span>
            <span class="score-text">{{ scoreLabel(item.score) }}</span>
          </div>
        </div>
        <p class="result-text">
          {{ item.text }}
        </p>
      </div>
    </div>

    <div v-if="data.length > limit" class="renderer-footer">
      {{ t('copilot.renderers.semanticMore', { count: data.length - limit }, data.length - limit) }}
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.semantic-renderer {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-hidden;
}

.renderer-header {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800;
}

.results-list {
  @apply p-3 space-y-3 max-h-96 overflow-y-auto;
}

.result-item {
  @apply p-3 rounded-lg;
  @apply bg-neutral-50 dark:bg-neutral-800;
  @apply hover:bg-neutral-100 dark:hover:bg-neutral-700;
  @apply transition-colors cursor-pointer;
}

.result-header {
  @apply flex items-center justify-between gap-3 mb-2;
}

.result-doc {
  @apply flex items-center gap-1 text-xs font-medium text-primary-600 dark:text-primary-400;
}

.result-score {
  @apply flex items-center gap-2;
}

.score-bar {
  @apply h-1.5 rounded-full;
  width: 40px;
}

.score-unit {
  @apply text-[10px] uppercase tracking-wide text-neutral-400 dark:text-neutral-500;
}

.score-text {
  @apply text-xs font-mono text-neutral-600 dark:text-neutral-400;
}

.result-text {
  @apply text-sm text-neutral-700 dark:text-neutral-300 leading-relaxed;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.renderer-footer {
  @apply px-3 py-2 text-xs text-neutral-500 text-center;
  @apply border-t border-neutral-200 dark:border-neutral-700;
}
</style>
