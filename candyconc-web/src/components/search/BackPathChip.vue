<script setup lang="ts">
/**
 * BackPathChip - says which analysis row the concordance was opened from and
 * how the lines relate to the number of that row.
 *
 * A word sketch row counts pairs of head and dependent, the concordance shows
 * one line per head. A trend period counts hits in the documents of the
 * period, the concordance runs the same search in that scope. A contrast row
 * counts collocate tokens in one group, the concordance shows the node hits
 * with the collocate in their window. Where the two numbers can differ, the
 * chip names both.
 */
import { computed } from 'vue'
import { CornerDownLeft } from 'lucide-vue-next'
import { useQueryStore } from '@/stores/query'
import { formatDecimal, formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const queryStore = useQueryStore()

const origin = computed(() => {
  const value = queryStore.backPathOrigin
  return value && value.term === queryStore.term ? value : null
})

/** The concordance count once it is final, else null. */
const lines = computed<number | null>(() =>
  queryStore.totalKnown && !queryStore.countIsLowerBound && !queryStore.isLoading ? queryStore.totalHits : null
)

const label = computed(() => {
  const o = origin.value
  if (!o) return ''
  if (o.kind === 'wordSketch') {
    return t('search.backPath.wordSketch', {
      node: o.node,
      relation: o.relationLabel,
      collocate: o.collocate,
      count: formatNumber(o.pairs),
    }, o.pairs)
  }
  if (o.kind === 'trend') {
    return t('search.backPath.trend', {
      query: o.query,
      period: o.period,
      field: o.field,
      count: formatNumber(o.hits),
    }, o.hits)
  }
  return t('search.backPath.contrast', {
    group: o.group,
    side: o.side === 'target' ? 'A' : 'B',
    node: o.node,
    collocate: o.collocate,
    perMillion: formatDecimal(o.perMillion, 1),
    count: formatNumber(o.cooccurrences),
  }, o.cooccurrences)
})

/** Shown when the concordance count differs from the row's number. */
const difference = computed(() => {
  const o = origin.value
  const n = lines.value
  if (!o || n === null) return ''
  if (o.kind === 'wordSketch' && n !== o.pairs) {
    return t('search.backPath.wordSketchDiffers', { lines: formatNumber(n), pairs: formatNumber(o.pairs) }, n)
  }
  if (o.kind === 'trend' && n !== o.hits) {
    return t('search.backPath.trendDiffers', { lines: formatNumber(n), hits: formatNumber(o.hits) }, n)
  }
  if (o.kind === 'contrast' && n !== o.cooccurrences) {
    return t('search.backPath.contrastDiffers', { lines: formatNumber(n), count: formatNumber(o.cooccurrences) }, n)
  }
  return ''
})

const title = computed(() => {
  const o = origin.value
  if (!o) return ''
  if (o.kind === 'wordSketch') {
    const parts = [t('search.backPath.wordSketchTitle')]
    if (!o.exact) parts.push(t('search.backPath.wordSketchFolded'))
    return parts.join(' ')
  }
  if (o.kind === 'trend') return t('search.backPath.trendTitle', { field: o.field, period: o.period })
  return t('search.backPath.contrastTitle', { group: o.group, node: o.node, collocate: o.collocate })
})
</script>

<template>
  <div v-if="origin" class="back-path" role="note" :title="title" data-testid="kwic-back-path">
    <CornerDownLeft class="back-path-icon" aria-hidden="true" />
    <span class="back-path-label" data-testid="kwic-back-path-label">{{ label }}</span>
    <span v-if="difference" class="back-path-difference" data-testid="kwic-back-path-difference">{{ difference }}</span>
    <span class="sr-only">{{ title }}</span>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.back-path {
  @apply flex flex-wrap items-center gap-x-2 gap-y-1 px-3 md:px-4 py-1.5 text-xs;
  @apply bg-primary-50 text-primary-900 border-b border-primary-100;
  @apply dark:bg-primary-900/20 dark:text-primary-100 dark:border-primary-900/40;
}

.back-path-icon {
  @apply w-3.5 h-3.5 shrink-0 text-primary-500 dark:text-primary-300;
}

.back-path-label {
  @apply font-medium;
}

.back-path-difference {
  @apply text-neutral-600 dark:text-neutral-300;
}
</style>
