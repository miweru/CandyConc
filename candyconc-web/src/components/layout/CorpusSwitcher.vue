<script setup lang="ts">
/**
 * CorpusSwitcher - Switch the active corpus without restarting.
 *
 * Reads the corpus list from the corpusCapabilities store (single source of
 * truth) and binds the active corpus to the query store via store.setActive().
 */
import { computed, onMounted, watch } from 'vue'
import { Database, Check, ChevronDown, Settings2 } from 'lucide-vue-next'
import Dropdown from '@/components/ui/Dropdown.vue'
import DropdownItem from '@/components/ui/DropdownItem.vue'
import {
  CORPUS_CATALOGUE_OPERATIONS,
  useCorpusCapabilitiesStore,
} from '@/stores/corpusCapabilities'
import {
  canActivateCorpusSummary,
  corpusActivationBlockReason,
} from '@/lib/corpusCataloguePolicy'
import { useProductCapabilitiesStore } from '@/stores/productCapabilities'
import { useQueryStore } from '@/stores/query'
import { useUiStore } from '@/stores/ui'
import type { CorpusSummary } from '@/api/client'
import { formatNumber } from '@/i18n/format'
import { corpusLanguageLabel } from '@/lib/corpusLanguage'
import { useI18n } from 'vue-i18n'
import { corpusDisplayName } from '@/lib/corpusDisplayName'

const { t } = useI18n()

const store = useCorpusCapabilitiesStore()
const uiStore = useUiStore()
const productCapabilities = useProductCapabilitiesStore()
const queryStore = useQueryStore()

const queryRunningMessage = computed(() => t('layout.corpusSwitcher.queryRunning'))

function formatTokens(count: number): string {
  return formatNumber(count)
}

function corpusLabel(name: string, tokenCount: number): string {
  return t('layout.corpusSwitcher.corpusLabel', { name, tokens: formatTokens(tokenCount) })
}

const activeLabel = computed(() => {
  const summary = store.activeSummary
  if (summary) return corpusLabel(corpusDisplayName(summary), summary.token_count)
  // First start: the internal name "default" is no corpus a user created.
  if (store.catalogEmpty) return t('layout.corpusSwitcher.noCorpus')
  return store.activeCorpus
})

const catalogueAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_CATALOGUE_OPERATIONS.list, t('layout.corpusSwitcher.catalogue'))
)

const activationAvailability = computed(() =>
  productCapabilities.productOperationAvailability(CORPUS_CATALOGUE_OPERATIONS.activate, t('layout.corpusSwitcher.activation'))
)

const canReadCatalogue = computed(() => catalogueAvailability.value.enabled)
const canActivateCorpus = computed(() => activationAvailability.value.enabled)
const catalogueAccessMessage = computed(() => catalogueAvailability.value.disabledReason)
const activationAccessMessage = computed(() => activationAvailability.value.disabledReason)
const queryRunning = computed(() => queryStore.isLoading || queryStore.streamingProgress?.isStreaming === true)

function canSelectCorpus(corpus: CorpusSummary): boolean {
  return !queryRunning.value && canActivateCorpus.value && canActivateCorpusSummary(corpus)
}

function corpusSelectTitle(corpus: CorpusSummary): string {
  if (queryRunning.value) return queryRunningMessage.value
  if (!canActivateCorpus.value) return activationAccessMessage.value ?? t('layout.corpusSwitcher.activationNotEnabled')
  return corpusActivationBlockReason(corpus) ?? t('layout.corpusSwitcher.activate')
}

function select(corpus: CorpusSummary) {
  if (corpus.name === store.activeCorpus) return
  if (queryRunning.value) {
    uiStore.showToast(queryRunningMessage.value, 'warning')
    return
  }
  if (!canActivateCorpus.value) {
    uiStore.showToast(activationAccessMessage.value ?? t('layout.corpusSwitcher.activationNotEnabled'), 'warning')
    return
  }
  if (!canActivateCorpusSummary(corpus)) {
    uiStore.showToast(corpusActivationBlockReason(corpus) ?? t('layout.corpusSwitcher.notActivatable'), 'warning')
    return
  }
  void store.setActive(corpus.name)
}

function openManager() {
  uiStore.openCorpusManager()
}

onMounted(async () => {
  await productCapabilities.ensureAccessContext()
  if (!store.loaded && canReadCatalogue.value) {
    void store.fetchCorpora()
  }
})

// In multi-user mode the catalogue becomes readable only after sign-in, when
// the capability contract is loaded again. Load it then, as a reload would.
watch(canReadCatalogue, (readable) => {
  if (readable && !store.loaded && !store.isLoading) void store.fetchCorpora()
})
</script>

<template>
  <Dropdown align="right" width="lg">
    <template #trigger="{ triggerProps }">
      <button
        type="button"
        class="corpus-switcher-trigger"
        :title="t('layout.corpusSwitcher.switch')"
        :aria-label="t('layout.corpusSwitcher.switch')"
        v-bind="triggerProps"
      >
        <Database class="w-4 h-4 flex-shrink-0" aria-hidden="true" />
        <span class="corpus-switcher-label">{{ activeLabel }}</span>
        <span
          v-if="store.isActivating"
          class="corpus-switcher-spinner"
          :aria-label="t('layout.corpusSwitcher.activating')"
        />
        <ChevronDown v-else class="w-4 h-4 flex-shrink-0 opacity-60" aria-hidden="true" />
      </button>
    </template>

    <div v-if="store.activationError" class="corpus-switcher-hint corpus-switcher-error">
      {{ store.activationError }}
    </div>
    <div v-if="store.activationNotice" class="corpus-switcher-hint" role="status">
      {{ store.activationNotice }}
    </div>
    <div v-if="queryRunning" class="corpus-switcher-hint">
      {{ queryRunningMessage }}
    </div>

    <template v-if="store.isLoading && !store.corpora.length">
      <div class="corpus-switcher-hint">{{ t('layout.corpusSwitcher.loading') }}</div>
    </template>
    <template v-else-if="!canReadCatalogue">
      <div class="corpus-switcher-hint corpus-switcher-error">
        {{ catalogueAccessMessage ?? t('layout.corpusSwitcher.catalogueNotEnabled') }}
      </div>
    </template>
    <template v-else-if="store.error && !store.corpora.length">
      <div class="corpus-switcher-hint corpus-switcher-error">{{ store.error }}</div>
    </template>
    <template v-else-if="!store.corpora.length">
      <div class="corpus-switcher-hint">{{ t('layout.corpusSwitcher.empty') }}</div>
      <div class="corpus-switcher-footer">
        <button type="button" class="manager-link" @click="openManager">
          <Settings2 class="w-4 h-4" aria-hidden="true" />
          {{ t('layout.corpusSwitcher.importCorpus') }}
        </button>
      </div>
    </template>
    <template v-else>
      <DropdownItem
        v-for="corpus in store.corpora"
        :key="corpus.name"
        :disabled="!canSelectCorpus(corpus)"
        :title="corpusSelectTitle(corpus)"
        @click="select(corpus)"
      >
        <span class="corpus-item">
          <Check
            class="corpus-item-check"
            :class="{ 'is-active': corpus.name === store.activeCorpus }"
            aria-hidden="true"
          />
          <span class="corpus-item-text">
            <span class="corpus-item-name">{{ corpusDisplayName(corpus) }}</span>
            <span class="corpus-item-meta">
              {{ t('layout.corpusSwitcher.tokens', { tokens: formatTokens(corpus.token_count) }) }}
              · <span data-testid="corpus-switcher-language">{{ corpusLanguageLabel(corpus) }}</span>
              <template v-if="corpus.status && corpus.status !== 'ready'"> · {{ corpus.status }}</template>
            </span>
          </span>
        </span>
      </DropdownItem>
      <div class="corpus-switcher-footer">
        <button type="button" class="manager-link" @click="openManager">
          <Settings2 class="w-4 h-4" aria-hidden="true" />
          {{ t('layout.corpusSwitcher.manage') }}
        </button>
      </div>
    </template>
  </Dropdown>
</template>

<style scoped>
@reference "../../style.css";

.corpus-switcher-trigger {
  @apply inline-flex items-center gap-2 max-w-[16rem];
  @apply px-3 py-1.5 rounded-lg;
  @apply bg-white dark:bg-neutral-800;
  @apply border border-neutral-200 dark:border-neutral-700;
  @apply text-sm text-neutral-700 dark:text-neutral-200;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-700;
  @apply transition-colors duration-150;
}

.corpus-switcher-label {
  @apply truncate font-medium;
}

.corpus-switcher-hint {
  @apply px-4 py-2.5 text-sm text-neutral-500 dark:text-neutral-400;
}

.corpus-switcher-error {
  @apply text-error-600 dark:text-error-400;
}

.corpus-switcher-spinner {
  @apply w-4 h-4 flex-shrink-0 rounded-full;
  @apply border-2 border-neutral-300 border-t-primary-500;
  @apply animate-spin;
}

.corpus-item {
  @apply flex items-center gap-2 w-full;
}

.corpus-item-check {
  @apply w-4 h-4 flex-shrink-0 opacity-0;
  @apply text-primary-600 dark:text-primary-400;
}

.corpus-item-check.is-active {
  @apply opacity-100;
}

.corpus-item-text {
  @apply flex flex-col min-w-0;
}

.corpus-item-name {
  @apply truncate font-medium text-neutral-800 dark:text-neutral-100;
}

.corpus-item-meta {
  @apply text-[11px] text-neutral-500 dark:text-neutral-400;
}

.corpus-switcher-footer {
  @apply mt-1 pt-1 border-t border-neutral-200 dark:border-neutral-700;
}

.manager-link {
  @apply flex items-center gap-2 w-full px-4 py-2.5;
  @apply text-sm font-medium text-neutral-700 dark:text-neutral-200;
  @apply hover:bg-neutral-50 dark:hover:bg-neutral-700;
  @apply transition-colors;
}
</style>
