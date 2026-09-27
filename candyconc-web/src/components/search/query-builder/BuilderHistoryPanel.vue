<script setup lang="ts">
import { useI18n } from 'vue-i18n'
import { formatNumber } from '@/i18n/format'
import type { BuilderHistoryEntry } from '@/lib/queryBuilder/types'

/**
 * Undo/Redo timeline strip for the advanced query builder.
 * Extracted verbatim from QueryBuilderStudio.vue (Phase 2 split): pure
 * presentation over the useBuilderHistory composable state.
 */
defineProps<{
  summary: { title: string; detail: string }
  canUndo: boolean
  canRedo: boolean
  entries: Array<BuilderHistoryEntry & { index: number; active: boolean }>
}>()

defineEmits<{
  undo: []
  redo: []
  jump: [index: number]
}>()

const { t } = useI18n()
</script>

<template>
  <div class="history-panel">
    <div class="history-header">
      <div class="history-copy">
        <div class="history-title">{{ t('querybuilder.history.title') }}</div>
        <p class="history-detail">{{ summary.detail }}</p>
      </div>
      <div class="history-toolbar">
        <button
          type="button"
          class="history-btn"
          :disabled="!canUndo"
          @click="$emit('undo')"
        >
          {{ t('querybuilder.history.undo') }}
        </button>
        <button
          type="button"
          class="history-btn"
          :disabled="!canRedo"
          @click="$emit('redo')"
        >
          {{ t('querybuilder.history.redo') }}
        </button>
      </div>
    </div>
    <div class="history-summary-row">
      <span class="history-summary-title">{{ summary.title }}</span>
      <span class="history-shortcut">Cmd/Ctrl+Z · Shift+Cmd/Ctrl+Z</span><!-- i18n-ignore: key names -->
    </div>
    <div class="history-strip" role="list" :aria-label="t('querybuilder.history.title')">
      <button
        v-for="entry in entries"
        :key="entry.id"
        type="button"
        :class="['history-chip', { active: entry.active }]"
        role="listitem"
        @click="$emit('jump', entry.index)"
      >
        <span class="history-chip-step">{{ t('querybuilder.history.step', { index: formatNumber(entry.index + 1) }) }}</span>
        <span class="history-chip-label">{{ entry.label }}</span>
        <code class="history-chip-code">{{ entry.cql || '[]' }}</code>
      </button>
    </div>
  </div>
</template>

<style scoped>
@reference "../../../style.css";

.history-panel {
  @apply rounded-xl border p-4;
  @apply border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900/80 space-y-3;
}

.history-header,
.history-summary-row {
  @apply flex items-center gap-2;
}

.history-copy {
  @apply min-w-0 space-y-1;
}

.history-title {
  @apply text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.history-detail {
  @apply text-sm text-neutral-600 dark:text-neutral-300;
}

.history-toolbar {
  @apply flex flex-wrap items-center gap-2;
}

.history-btn {
  @apply inline-flex items-center rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm font-medium text-neutral-800 dark:text-neutral-100 transition-colors hover:border-primary-300 hover:bg-primary-50/50 dark:hover:bg-neutral-700;
  @apply disabled:cursor-not-allowed disabled:opacity-45;
}

.history-summary-row {
  @apply justify-between text-xs text-neutral-500 dark:text-neutral-400;
}

.history-summary-title {
  @apply font-semibold uppercase tracking-wide;
}

.history-shortcut {
  @apply rounded-lg bg-neutral-100 dark:bg-neutral-800 px-2 py-1;
}

.history-strip {
  @apply flex gap-3 overflow-x-auto pb-1;
}

.history-chip {
  @apply min-w-[12rem] max-w-[16rem] flex-shrink-0 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800/70 px-3 py-3 text-left transition-colors hover:border-primary-300 hover:bg-primary-50/50 dark:hover:bg-neutral-800;
}

.history-chip.active {
  @apply border-primary-400 bg-primary-50/80 shadow-sm dark:bg-primary-500/10;
}

.history-chip-step {
  @apply block text-[11px] font-semibold uppercase tracking-wide text-neutral-500 dark:text-neutral-400;
}

.history-chip-label {
  @apply mt-1 block text-sm font-semibold text-neutral-900 dark:text-neutral-100;
}

.history-chip-code {
  @apply mt-2 block rounded-lg bg-neutral-950 px-3 py-2 text-xs leading-5 text-emerald-300 break-all;
}

@media (max-width: 960px) {
  .history-toolbar {
    @apply w-full;
  }

  .history-btn {
    @apply flex-1 justify-center;
  }

  .history-summary-row {
    @apply flex-col items-start;
  }
}
</style>
