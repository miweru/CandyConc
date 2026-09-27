<script setup lang="ts">
/**
 * Shown in the copilot panel while no language model is configured. It names
 * the state and opens the model settings.
 */
import { Settings } from 'lucide-vue-next'
import { useUiStore } from '@/stores/ui'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const uiStore = useUiStore()

function openModelSettings() {
  uiStore.openSettings('modelroute')
}
</script>

<template>
  <div class="setup-notice" role="status" data-testid="copilot-setup-notice">
    <p class="setup-title">{{ t('copilot.setup.title') }}</p>
    <p class="setup-text">{{ t('copilot.setup.text') }}</p>
    <button type="button" class="setup-btn" @click="openModelSettings">
      <Settings class="w-4 h-4" />
      <span>{{ t('copilot.setup.openSettings') }}</span>
    </button>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.setup-notice {
  @apply m-3 rounded-lg border border-warning-300 bg-warning-50 p-3 text-sm;
  @apply dark:border-warning-700 dark:bg-warning-900/30;
}

.setup-title {
  @apply font-medium text-warning-800 dark:text-warning-200;
}

.setup-text {
  @apply mt-1 text-neutral-700 dark:text-neutral-300;
}

.setup-btn {
  @apply mt-3 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium;
  @apply bg-white text-neutral-800 border border-neutral-300 hover:bg-neutral-50;
  @apply dark:bg-neutral-800 dark:text-neutral-100 dark:border-neutral-600 dark:hover:bg-neutral-700;
}
</style>
