<script setup lang="ts">
/**
 * WordSketchRenderer - Displays grammatical relations grouped by relation
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { BookOpen } from 'lucide-vue-next'
import { formatDecimal, formatNumber } from '@/i18n/format'

interface WordSketchRow {
  word?: string
  term?: string
  score?: number | null
  // Which measure `score` carries (backend single source of truth); default logDice.
  score_key?: string | null
  chi2_cell?: number | null
  f?: number | null
  frequency?: number | null
}

type WordSketchTables = Record<string, WordSketchRow[]>
type RelationMeta = { relation?: string; label?: string }

interface Props {
  data:
    | WordSketchTables
    | {
        tables?: WordSketchTables
        sketches?: WordSketchTables
        relations?: Record<string, RelationMeta>
      }
  limit?: number
}

const props = withDefaults(defineProps<Props>(), {
  limit: 6
})
const { t } = useI18n()

// Human labels for the measure carried in `score` (backend score_key). The
// default ranking measure is logDice (Rychlý 2008), NOT χ²-Zellbeitrag — the old
// hardcoded header mislabelled it (WS-COPILOT-RENDER-MISLABEL).
function scoreKeyLabel(key: string): string | undefined {
  if (key === 'logdice') return 'logDice'
  if (key === 'chi2_cell') return t('copilot.renderers.measureChi2Cell')
  if (key === 'll') return 'Log-Likelihood'
  if (key === 't') return 't-Score'
  if (key === 'f') return t('copilot.renderers.measureFrequency')
  return undefined
}

const tables = computed<WordSketchTables>(() => {
  const d = props.data as {
    tables?: WordSketchTables
    sketches?: WordSketchTables
  }
  return d.sketches ?? d.tables ?? (props.data as WordSketchTables)
})

// Backend-provided German relation glosses ({rel: {relation, label}}); the
// authoritative source. We no longer carry a stale local TIGER map.
const relationMeta = computed<Record<string, RelationMeta>>(
  () => (props.data as { relations?: Record<string, RelationMeta> }).relations ?? {}
)

const relationEntries = computed(() =>
  Object.entries(tables.value).filter(([, rows]) => Array.isArray(rows) && rows.length > 0)
)

function labelForRelation(relation: string): string {
  return relationMeta.value[relation]?.label ?? relation.replace(/_/g, ' ')
}

// Label the score column by the measure actually present in the rows.
const scoreLabel = computed(() => {
  for (const [, rows] of relationEntries.value) {
    const key = rows.find((r) => r.score_key)?.score_key
    if (key) return scoreKeyLabel(key) ?? key
  }
  return scoreKeyLabel('logdice')
})

function scoreForRow(row: WordSketchRow): number {
  return Number(row.score ?? row.chi2_cell ?? 0)
}

function frequencyForRow(row: WordSketchRow): number {
  return Number(row.f ?? row.frequency ?? 0)
}

function termForRow(row: WordSketchRow): string {
  return row.word ?? row.term ?? '—'
}
</script>

<template>
  <div class="wordsketch-renderer">
    <div class="renderer-header">
      <BookOpen class="w-4 h-4 text-primary-500" />
      <span class="font-medium">Word Sketch</span>
      <span class="text-xs text-neutral-500">
        {{ t('copilot.renderers.relations', { count: relationEntries.length }, relationEntries.length) }}
      </span>
      <span class="text-xs text-neutral-500">
        {{ t('copilot.renderers.scoreLabel', { label: scoreLabel }) }}
      </span>
    </div>

    <div v-if="relationEntries.length > 0" class="relations-list">
      <div
        v-for="[relation, rows] in relationEntries"
        :key="relation"
        class="relation-card"
      >
        <div class="relation-title">{{ labelForRelation(relation) }}</div>
        <div class="relation-items">
          <div
            v-for="(row, idx) in rows.slice(0, limit)"
            :key="`${relation}-${idx}`"
            class="relation-item"
          >
            <span class="item-term">{{ termForRow(row) }}</span>
            <span class="item-score">{{ formatDecimal(scoreForRow(row), 2) }}</span>
            <span class="item-freq">{{ formatNumber(frequencyForRow(row)) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div v-else class="empty-state">
      {{ t('copilot.renderers.noRelations') }}
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.wordsketch-renderer {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-white dark:bg-neutral-900;
  @apply overflow-hidden;
}

.renderer-header {
  @apply flex items-center gap-2 px-3 py-2;
  @apply border-b border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800;
}

.relations-list {
  @apply p-3 space-y-3 max-h-96 overflow-y-auto;
}

.relation-card {
  @apply rounded-lg border border-neutral-200 dark:border-neutral-700;
  @apply bg-neutral-50 dark:bg-neutral-800/70;
  @apply overflow-hidden;
}

.relation-title {
  @apply px-3 py-2 text-xs font-semibold uppercase tracking-wider;
  @apply text-neutral-600 dark:text-neutral-300;
  @apply border-b border-neutral-200 dark:border-neutral-700;
}

.relation-items {
  @apply divide-y divide-neutral-200 dark:divide-neutral-700;
}

.relation-item {
  @apply grid grid-cols-[1fr_auto_auto] gap-3 items-center;
  @apply px-3 py-2 text-sm;
}

.item-term {
  @apply font-medium text-neutral-900 dark:text-neutral-100 truncate;
}

.item-score {
  @apply text-xs font-mono text-primary-600 dark:text-primary-400;
}

.item-freq {
  @apply text-xs text-neutral-500 dark:text-neutral-400;
}

.empty-state {
  @apply px-3 py-4 text-sm text-neutral-500 dark:text-neutral-400;
}
</style>
