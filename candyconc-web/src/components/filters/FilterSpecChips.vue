<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import type { FilterSpec } from '@/api/client'
import { filterSpecChips } from '@/lib/filterSpec'
import { formatNumber } from '@/i18n/format'

const props = withDefaults(defineProps<{
  spec?: FilterSpec | null
  emptyLabel?: string
  max?: number
  dense?: boolean
}>(), {
  emptyLabel: undefined,
  max: 12,
  dense: false,
})

const { t } = useI18n()
const emptyText = computed(() => props.emptyLabel ?? t('subcorpus.chips.empty'))
const chips = computed(() => filterSpecChips(props.spec))
const visibleChips = computed(() => chips.value.slice(0, props.max))
const hiddenCount = computed(() => Math.max(0, chips.value.length - visibleChips.value.length))
</script>

<template>
  <div class="filter-spec-chips" :class="{ dense }">
    <template v-if="visibleChips.length">
      <span
        v-for="chip in visibleChips"
        :key="`${chip.field}:${chip.valueLabel}`"
        class="filter-chip"
        :class="`kind-${chip.kind}`"
        :title="chip.title"
      >
        <span class="filter-chip-field">{{ chip.label }}</span>
        <span class="filter-chip-value">{{ chip.valueLabel }}</span>
      </span>
      <span v-if="hiddenCount" class="filter-chip overflow" :title="t('subcorpus.chips.more', { count: formatNumber(hiddenCount) }, hiddenCount)">
        +{{ hiddenCount }}
      </span>
    </template>
    <span v-else class="filter-chip empty">{{ emptyText }}</span>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.filter-spec-chips {
  @apply flex flex-wrap gap-1.5;
}

.filter-spec-chips.dense {
  @apply gap-1;
}

.filter-chip {
  @apply inline-flex items-center gap-1 rounded-full border px-2 py-1;
  @apply border-neutral-200 bg-neutral-50 text-[11px] text-neutral-700;
  @apply dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-200;
}

.dense .filter-chip {
  @apply px-1.5 py-0.5;
}

.filter-chip-field {
  @apply font-semibold;
}

.filter-chip-value {
  @apply max-w-[18rem] truncate;
}

.kind-range,
.kind-comparison {
  @apply border-sky-200 bg-sky-50 text-sky-800 dark:border-sky-800 dark:bg-sky-950/40 dark:text-sky-200;
}

.kind-in {
  @apply border-emerald-200 bg-emerald-50 text-emerald-800 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200;
}

.filter-chip.overflow {
  @apply border-neutral-300 bg-neutral-100 font-semibold dark:border-neutral-700 dark:bg-neutral-800;
}

.filter-chip.empty {
  @apply border-dashed text-neutral-500 dark:text-neutral-400;
}
</style>
