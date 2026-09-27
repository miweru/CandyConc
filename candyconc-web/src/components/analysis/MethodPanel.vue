<script setup lang="ts">
/**
 * MethodPanel — compact "Methode / Reproduzierbarkeit" provenance display (F1).
 *
 * Renders the server-provided `method` block (the single source of truth for
 * statistical provenance) instead of any client-side formula reconstruction.
 * Defensive: if the block is absent or empty, the panel renders nothing.
 */
import { computed } from 'vue'
import type { MethodBlock } from '@/api/client'
import { formatNumber } from '@/i18n/format'
import { safeMathml } from '@/lib/safeMathml'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  method?: MethodBlock | null
}>()

const { t } = useI18n()

interface StatRow {
  key: string
  name: string
  latex: string | null
  /** Presentation MathML of the formula from the server method block. */
  mathml: string | null
  smoothing: string | null
  sortKey: string | null
}


const statRows = computed<StatRow[]>(() => {
  const m = props.method
  if (!m) return []
  // Authoritative backend shape: an ordered `statistics` array where each
  // entry carries its own `key`.
  const arr = m.statistics
  if (Array.isArray(arr) && arr.length) {
    return arr.map((value, i) => {
      const key = typeof value?.key === 'string' && value.key ? value.key : String(i)
      return {
        key,
        name: typeof value?.name === 'string' && value.name ? value.name : key,
        latex: typeof value?.latex_formula === 'string' ? value.latex_formula : null,
        mathml: safeMathml(value?.formula_mathml),
        smoothing: typeof value?.smoothing === 'string' ? value.smoothing : null,
        sortKey: typeof value?.sort_key === 'string' ? value.sort_key : null,
      }
    })
  }
  // Back-compat: legacy object-keyed `stats` map.
  const stats = m.stats
  if (!stats || typeof stats !== 'object') return []
  return Object.entries(stats).map(([key, value]) => ({
    key,
    name: typeof value?.name === 'string' && value.name ? value.name : key,
    latex: typeof value?.latex_formula === 'string' ? value.latex_formula : null,
    mathml: safeMathml(value?.formula_mathml),
    smoothing: typeof value?.smoothing === 'string' ? value.smoothing : null,
    sortKey: typeof value?.sort_key === 'string' ? value.sort_key : null,
  }))
})

const fingerprint = computed(
  () => props.method?.indexFingerprint ?? props.method?.index_fingerprint ?? null
)

const reproItems = computed(() => {
  const m = props.method
  if (!m) return [] as Array<{ label: string; value: string }>
  const items: Array<{ label: string; value: string }> = []
  if (typeof m.target_total === 'number') {
    items.push({ label: t('analysis.methodPanel.targetTokens'), value: formatNumber(m.target_total) })
  }
  for (const key of ['scope_tokens', 'window_union_size', 'node_frequency']) {
    const value = m[key]
    if (typeof value === 'number') items.push({ label: t(`analysis.methodPanel.${key}`), value: formatNumber(value) })
  }
  if (typeof m.reference_total === 'number') {
    items.push({ label: t('analysis.methodPanel.referenceTokens'), value: formatNumber(m.reference_total) })
  }
  if (typeof m.window === 'number') {
    items.push({ label: t('analysis.methodPanel.window'), value: String(m.window) })
  }
  if (typeof m.within_sentence === 'boolean') {
    items.push({ label: t('analysis.methodPanel.withinSentence'), value: m.within_sentence ? t('analysis.methodPanel.yes') : t('analysis.methodPanel.no') })
  }
  if (m.event_space === 'anchor_token_pairs') {
    items.push({ label: t('analysis.methodPanel.eventSpace'), value: t('analysis.methodPanel.anchorTokenPairs') })
  }
  if (m.event_total_definition === 'anchor_count_times_scope_tokens') {
    items.push({ label: t('analysis.methodPanel.eventTotal'), value: t('analysis.methodPanel.anchorTimesScope') })
  }
  if (m.anchor_span_policy === 'own_match_span_excluded') {
    items.push({ label: t('analysis.methodPanel.anchorSpan'), value: t('analysis.methodPanel.anchorSpanExcluded') })
  }
  // Show the floor actually applied by the server, including adaptive defaults.
  const effectiveFloor = m.effective_min_cooccurrence
  if (typeof effectiveFloor === 'number') {
    items.push({ label: t('analysis.methodPanel.minFrequency'), value: formatNumber(effectiveFloor) })
  } else if (typeof m.min_freq === 'number') {
    items.push({ label: t('analysis.methodPanel.minFrequency'), value: formatNumber(m.min_freq) })
  }
  if (fingerprint.value) {
    items.push({ label: t('analysis.methodPanel.indexFingerprint'), value: fingerprint.value })
  }
  return items
})

const hasContent = computed(() => statRows.value.length > 0 || reproItems.value.length > 0)
</script>

<template>
  <details v-if="hasContent" class="method-panel">
    <summary class="method-summary">
      <span class="method-title">{{ t('analysis.methodPanel.title') }}</span>
      <span class="method-hint">{{ t('analysis.methodPanel.hint') }}</span>
    </summary>
    <div class="method-body">
      <table v-if="statRows.length" class="method-table">
        <thead>
          <tr>
            <th>{{ t('analysis.methodPanel.statistic') }}</th>
            <th>{{ t('analysis.methodPanel.formula') }}</th>
            <th>{{ t('analysis.methodPanel.smoothing') }}</th>
            <th>{{ t('analysis.methodPanel.sortKey') }}</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="row in statRows" :key="row.key">
            <td class="stat-name">{{ row.name }}</td>
            <td class="stat-formula">
              <!-- eslint-disable-next-line vue/no-v-html -- checked presentation MathML from the own method catalog -->
              <span v-if="row.mathml" class="stat-math" :title="row.latex ?? undefined" v-html="row.mathml" />
              <code v-else-if="row.latex">{{ row.latex }}</code>
              <span v-else class="muted">–</span>
            </td>
            <td>{{ row.smoothing ?? '–' }}</td>
            <td class="stat-sort"><code v-if="row.sortKey">{{ row.sortKey }}</code><span v-else class="muted">–</span></td>
          </tr>
        </tbody>
      </table>

      <dl v-if="reproItems.length" class="repro-grid">
        <template v-for="item in reproItems" :key="item.label">
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value }}</dd>
        </template>
      </dl>
    </div>
  </details>
</template>

<style scoped>
@reference "../../style.css";

.method-panel {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50/70 dark:bg-neutral-900/50;
  @apply px-3 py-2 text-sm;
}

.method-summary {
  @apply flex items-center justify-between gap-2 cursor-pointer select-none;
  @apply text-neutral-700 dark:text-neutral-300;
}

.method-summary::-webkit-details-marker {
  display: none;
}

.method-title {
  @apply font-medium;
}

.method-hint {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.method-body {
  @apply mt-3 space-y-3;
}

.method-table {
  @apply w-full text-left text-xs;
  border-collapse: collapse;
}

.method-table th {
  @apply py-1 pr-3 font-medium text-neutral-500 dark:text-neutral-400;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.method-table td {
  @apply py-1 pr-3 align-top;
  @apply border-b border-neutral-100 dark:border-neutral-800;
}

.stat-name {
  @apply font-medium text-neutral-800 dark:text-neutral-200 whitespace-nowrap;
}

.stat-formula code,
.method-table code {
  @apply font-mono text-[11px] text-neutral-700 dark:text-neutral-300;
  word-break: break-word;
}

.stat-math {
  @apply text-sm text-neutral-800 dark:text-neutral-200;
}

/* Fractions at full size, as in a displayed formula. */
.stat-math :deep(math) {
  math-style: normal;
}

/* Sort keys are identifiers: they stay on one line. */
.method-table .stat-sort code {
  @apply whitespace-nowrap;
  word-break: normal;
}

.muted {
  @apply text-neutral-400 dark:text-neutral-500;
}

.repro-grid {
  @apply grid gap-x-4 gap-y-1 text-xs;
  grid-template-columns: max-content 1fr;
}

.repro-grid dt {
  @apply text-neutral-500 dark:text-neutral-400;
}

.repro-grid dd {
  @apply font-mono text-neutral-700 dark:text-neutral-300;
  word-break: break-all;
}
</style>
