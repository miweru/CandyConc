<script setup lang="ts">
/**
 * FilterField - Unified filter field wrapper (label, status, count, hint).
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

interface Props {
  label: string
  labelFor?: string
  hint?: string
  countText?: string
  state?: 'neutral' | 'ok' | 'warn' | 'empty' | 'loading'
  stateLabel?: string
}

const props = withDefaults(defineProps<Props>(), {
  state: 'neutral'
})

const { t } = useI18n()

const stateText = computed(() => {
  if (props.stateLabel) return props.stateLabel
  switch (props.state) {
    case 'ok':
      return t('subcorpus.field.ok')
    case 'warn':
      return t('subcorpus.field.hint')
    case 'empty':
      return '0'
    case 'loading':
      return t('subcorpus.field.loading')
    default:
      return ''
  }
})
</script>

<template>
  <div class="filter-field" :class="`state-${state}`">
    <div class="filter-head">
      <label v-if="labelFor" :for="labelFor" class="filter-label">{{ label }}</label>
      <span v-else class="filter-label">{{ label }}</span>
      <span v-if="countText" class="filter-count">{{ countText }}</span>
      <span v-if="stateText" class="filter-state">{{ stateText }}</span>
    </div>
    <div class="filter-control">
      <slot />
    </div>
    <p v-if="hint" class="filter-hint">{{ hint }}</p>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.filter-field {
  @apply flex flex-col gap-1;
}

.filter-head {
  @apply flex flex-wrap items-center gap-2;
}

.filter-label {
  @apply text-xs font-medium text-neutral-600 dark:text-neutral-400;
}

.filter-count {
  @apply text-[11px] font-medium text-neutral-500 dark:text-neutral-500;
  @apply px-2 py-0.5 rounded-full bg-neutral-100 dark:bg-neutral-800;
}

.filter-state {
  @apply text-[11px] font-medium px-2 py-0.5 rounded-full;
  @apply bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300;
}

.state-warn .filter-state {
  @apply bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300;
}

.state-ok .filter-state {
  @apply bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300;
}

.state-empty .filter-state {
  @apply bg-rose-100 text-rose-700 dark:bg-rose-900/40 dark:text-rose-300;
}

.state-loading .filter-state {
  @apply bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300;
}

.filter-control {
  @apply flex flex-col gap-1;
}

.filter-hint {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}
</style>
