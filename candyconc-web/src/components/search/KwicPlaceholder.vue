<script setup lang="ts">
/**
 * KwicPlaceholder - Temporary placeholder for KWIC table
 */
import { useQueryStore } from '@/stores'
import { useCorpusCapabilitiesStore } from '@/stores/corpusCapabilities'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useUiStore } from '@/stores/ui'
import { FolderInput, Search, Sparkles } from 'lucide-vue-next'
import { computed } from 'vue'
import { formatNumber } from '@/i18n/format'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const queryStore = useQueryStore()
const productCapabilities = useProductCapabilitiesStore()
const corpusCapabilities = useCorpusCapabilitiesStore()
const uiStore = useUiStore()
// First start: the catalogue loaded and holds no corpus. Offer the import
// instead of a search that has nothing to search.
const catalogueEmpty = computed(() => corpusCapabilities.catalogEmpty)
const hasExecutedSearch = computed(() => Boolean(queryStore.term.trim()) && queryStore.lastExecutedAt !== null)
const canUseCqlf = computed(() => productCapabilities.isVisible('query.cqlf'))
const canUseCopilot = computed(() => productCapabilities.isVisible('research.copilot_grounding'))
</script>

<template>
  <div class="kwic-placeholder">
    <!-- Empty state -->
    <div v-if="queryStore.isLoading || queryStore.streamingProgress?.isStreaming" class="loading-state">
      <div class="loading-spinner" />
      <p class="mt-4 text-neutral-600 dark:text-neutral-400">{{ t('kwic.placeholder.searching') }}</p>
    </div>

    <div v-else-if="catalogueEmpty && !hasExecutedSearch" class="empty-state" data-testid="kwic-no-corpus">
      <div class="icon-wrapper">
        <FolderInput class="w-12 h-12 text-neutral-300 dark:text-neutral-600" />
      </div>
      <h2 class="mt-4 text-lg font-medium text-neutral-700 dark:text-neutral-300">
        {{ t('kwic.placeholder.noCorpusTitle') }}
      </h2>
      <p class="mt-2 text-sm text-neutral-500 max-w-md text-center">
        {{ t('kwic.placeholder.noCorpusHint') }}
      </p>
      <button type="button" class="import-button mt-6" @click="uiStore.openCorpusManager()">
        {{ t('kwic.placeholder.importCorpus') }}
      </button>
    </div>

    <div v-else-if="!hasExecutedSearch" class="empty-state">
      <div class="icon-wrapper">
        <Search class="w-12 h-12 text-neutral-300 dark:text-neutral-600" />
      </div>
      <h2 class="mt-4 text-lg font-medium text-neutral-700 dark:text-neutral-300">
        {{ t('kwic.placeholder.startTitle') }}
      </h2>
      <p class="mt-2 text-sm text-neutral-500 max-w-md text-center">
        {{ canUseCqlf ? t('kwic.placeholder.startHintQuery') : t('kwic.placeholder.startHint') }}
      </p>
      <div v-if="canUseCopilot" class="mt-6 flex items-center gap-2 text-sm text-copilot-primary">
        <Sparkles class="w-4 h-4" />
        <i18n-t keypath="kwic.placeholder.copilotHint" tag="span" scope="global"><template #keys><kbd class="kbd">Cmd+Shift+K</kbd></template></i18n-t>
      </div>
    </div>

    <!-- Zero-results state -->
    <div v-else class="results-placeholder">
      <div class="results-header">
        <h3 class="font-medium">
          <template v-if="queryStore.countIsLowerBound">
            {{ t('kwic.placeholder.hitsPartialFor', { count: formatNumber(queryStore.totalHits) }, queryStore.totalHits) }}
          </template>
          <template v-else-if="queryStore.totalKnown">
            {{ t('kwic.placeholder.hitsFor', { count: formatNumber(queryStore.totalHits) }, queryStore.totalHits) }}
          </template>
          <template v-else>{{ t('kwic.placeholder.countingFor') }}</template>
          <span class="text-primary-600">„{{ queryStore.term }}"</span>
        </h3>
      </div>
      <p class="mt-4 text-neutral-500 text-center">
        {{ t('kwic.placeholder.noHits') }}
      </p>
    </div>
  </div>
</template>

<style scoped>
@reference "../../style.css";

.kwic-placeholder {
  /* Fills the workbench body, which grows with the tab (App.vue). */
  @apply flex items-center justify-center;
  flex: 1 0 auto;
  @apply bg-neutral-50 dark:bg-neutral-950;
}

.empty-state,
.loading-state,
.results-placeholder {
  @apply flex flex-col items-center text-center p-8;
}

.import-button {
  @apply px-4 py-2 rounded-md text-sm font-medium text-white bg-primary-600 hover:bg-primary-700;
}

.icon-wrapper {
  @apply p-6 rounded-full bg-neutral-100 dark:bg-neutral-800;
}

.kbd {
  @apply px-1.5 py-0.5 text-xs font-mono;
  @apply bg-neutral-200 dark:bg-neutral-700 rounded;
}

.loading-spinner {
  @apply w-10 h-10 border-4 rounded-full;
  @apply border-neutral-200 dark:border-neutral-700;
  @apply border-t-primary-500;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.results-header {
  @apply text-lg text-neutral-700 dark:text-neutral-300;
}
</style>
