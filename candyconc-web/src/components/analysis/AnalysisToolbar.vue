<script setup lang="ts">
/**
 * AnalysisToolbar - Consistent toolbar layout for analysis tabs
 */
</script>

<template>
  <div class="analysis-toolbar">
    <div class="analysis-toolbar-left">
      <slot name="left" />
    </div>
    <div v-if="$slots.center" class="analysis-toolbar-center">
      <slot name="center" />
    </div>
    <div class="analysis-toolbar-right">
      <slot name="right" />
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.analysis-toolbar {
  @apply flex flex-wrap items-center justify-between gap-3 p-3 md:p-4;
  @apply border-b border-neutral-200 dark:border-neutral-800;
  @apply bg-white dark:bg-neutral-900;
}

.analysis-toolbar-left,
.analysis-toolbar-center,
.analysis-toolbar-right {
  @apply flex items-center gap-2 md:gap-3 flex-wrap;
}

.analysis-toolbar-right {
  @apply ml-auto;
}
</style>
